# wa-check 重试与风控冷却 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 wa_check 增加「单号瞬断重连重试 + 连续失败风控中止」和「批级错误率长冷却」，降低 Connection Closed 导致的 NULL 数量并防止风控升级。

**Architecture:** 分层——check.js（协议层）做单号重连重试与连续失败中止（新增可单测的 `createQueryRunner`）；wa_tasks.py（策略层）统计批内错误率、≥30% 触发 20~30 分钟额外冷却（抽出可复用的 `_rest_with_heartbeat`）；原子只把超时公式 +360s 重试预算，不做决策。数据语义不变：重试后仍失败的号码保持 `wa_registered=NULL` 下轮补查。

**Tech Stack:** Node 24（`node:test`，CommonJS）、Python 3.12（unittest）、Baileys、FastAPI 平台。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `fetcher/vendor/wa-check/retry.js` | 纯重试逻辑，可单测 | 新建 |
| `fetcher/vendor/wa-check/check.js` | CLI 主循环接入重试器 | 修改 |
| `fetcher/vendor/wa-check/test/retry.test.cjs` | retry.js 单测 | 新建 |
| `fetcher/fetcher/atoms/wa_check.py` | 超时公式 +360s | 修改 |
| `fetcher/tests/test_wa_check.py` | 原子超时测试 | 修改（新增一个测试） |
| `platform/server/app/wa_tasks.py` | 抽 `_rest_with_heartbeat` + 风控冷却 + checked 计数修正 | 修改 |
| `platform/server/tests/test_wa_tasks_cooldown.py` | 心跳/冷却/计数测试 | 新建 |

---

## Task 1: 新增 retry.js（可单测重试器）

**Files:**
- Create: `fetcher/vendor/wa-check/retry.js`
- Test: `fetcher/vendor/wa-check/test/retry.test.cjs`

- [ ] **Step 1: 写失败测试**

创建 `fetcher/vendor/wa-check/test/retry.test.cjs`：

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createQueryRunner } = require('../retry.js');

test('成功查询返回 registered 结果', async () => {
  const runner = createQueryRunner({ maxRetries: 2, throttleThreshold: 5, backoffMs: 1 });
  const r = await runner.run('861234', async () => [{ exists: true, jid: '861234@s.whatsapp.net' }]);
  assert.equal(r.registered, true);
  assert.equal(r.jid, '861234@s.whatsapp.net');
  assert.equal(runner.isThrottled(), false);
});

test('未注册号码返回 registered:false', async () => {
  const runner = createQueryRunner({ maxRetries: 2, throttleThreshold: 5, backoffMs: 1 });
  const r = await runner.run('861234', async () => []);
  assert.equal(r.registered, false);
  assert.equal(r.jid, null);
});

test('失败一次后重连成功 → 返回结果且失败计数清零', async () => {
  let calls = 0;
  let reconnects = 0;
  const runner = createQueryRunner({
    maxRetries: 2, throttleThreshold: 5, backoffMs: 1,
    sleep: async () => {},
    reconnect: async () => { reconnects++; },
  });
  const query = async () => {
    calls++;
    if (calls === 1) throw new Error('Connection Closed');
    return [{ exists: false, jid: null }];
  };
  const r = await runner.run('861234', query);
  assert.equal(calls, 2);
  assert.equal(reconnects, 1);
  assert.equal(r.registered, false);
  assert.equal(runner.isThrottled(), false);
});

test('重试耗尽 → 返回 error 且 registered:null，未判风控', async () => {
  const runner = createQueryRunner({ maxRetries: 2, throttleThreshold: 5, backoffMs: 1 });
  const r = await runner.run('861234', async () => { throw new Error('Connection Closed'); });
  assert.equal(r.registered, null);
  assert.ok(r.error.includes('Connection Closed'));
  assert.equal(runner.isThrottled(), false);
});

test('连续失败达阈值 → 风控中止，后续号码短路', async () => {
  const runner = createQueryRunner({ maxRetries: 2, throttleThreshold: 3, backoffMs: 1 });
  const query = async () => { throw new Error('Connection Closed'); };
  const r = await runner.run('1', query);
  assert.ok(r.error.includes('风控'));
  assert.equal(runner.isThrottled(), true);
  const r2 = await runner.run('2', query);
  assert.ok(r2.error.includes('风控'));
});

test('重连失败 → 中止本批', async () => {
  const runner = createQueryRunner({
    maxRetries: 2, throttleThreshold: 5, backoffMs: 1,
    sleep: async () => {},
    reconnect: async () => { throw new Error('已登出'); },
  });
  const r = await runner.run('861234', async () => { throw new Error('Connection Closed'); });
  assert.ok(r.error.includes('重连失败'));
  assert.equal(runner.isThrottled(), true);
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd fetcher/vendor/wa-check && node --test test/retry.test.cjs`
Expected: FAIL — `Cannot find module '../retry.js'`（retry.js 尚不存在）。

- [ ] **Step 3: 实现 retry.js**

创建 `fetcher/vendor/wa-check/retry.js`：

```js
'use strict';

// 单号查询重试器：查询失败时按退避重连重试，连续失败达到阈值判定风控并中止本批。
// 依赖注入（query / reconnect / sleep）便于单测；check.js 传入真实 Baileys socket。
function createQueryRunner({
  maxRetries = 2,
  throttleThreshold = 5,
  backoffMs = 3000,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
  reconnect = async () => {},
} = {}) {
  let consecutiveFails = 0;
  let throttled = false;

  async function run(num, query) {
    if (throttled) {
      return { number: num, registered: null, error: '批次已风控中止' };
    }
    for (let attempt = 0; ; attempt++) {
      try {
        const res = await query(num);
        consecutiveFails = 0;
        const hit = res && res[0];
        return { number: num, registered: !!hit?.exists, jid: hit?.jid || null };
      } catch (e) {
        consecutiveFails += 1;
        if (consecutiveFails >= throttleThreshold) {
          throttled = true;
          return { number: num, registered: null,
                   error: `Connection Closed×${consecutiveFails} 疑似风控，中止本批` };
        }
        if (attempt < maxRetries) {
          try {
            await sleep(backoffMs * (attempt + 1));
            await reconnect();
          } catch (re) {
            throttled = true;
            return { number: num, registered: null,
                     error: `重连失败，中止本批: ${re.message || re}` };
          }
        } else {
          return { number: num, registered: null, error: String(e.message || e) };
        }
      }
    }
  }

  return { run, isThrottled: () => throttled };
}

module.exports = { createQueryRunner };
```

- [ ] **Step 4: 运行确认通过**

Run: `cd fetcher/vendor/wa-check && node --test test/retry.test.cjs`
Expected: `# pass 6` / `# fail 0`。

- [ ] **Step 5: 提交**

```bash
git add fetcher/vendor/wa-check/retry.js fetcher/vendor/wa-check/test/retry.test.cjs
git commit -m "feat(wa-check): 可单测的重试器（单号重连重试 + 连续失败风控中止）"
```

---

## Task 2: check.js 主循环接入重试器

**Files:**
- Modify: `fetcher/vendor/wa-check/check.js`

- [ ] **Step 1: 加常量 + require + 重写主循环**

在 `check.js` 顶部（`const AUTH_DIR = ...` 之后）加常量：

```js
// 单号查询失败重试：重试次数 / 连续失败风控阈值 / 退避基值（可 env 覆盖）
const MAX_RETRIES        = parseInt(process.env.WA_QUERY_RETRIES        || '2');
const THROTTLE_THRESHOLD = parseInt(process.env.WA_THROTTLE_THRESHOLD  || '5');
const RETRY_BACKOFF_MS   = 3000;
```

在 `const { ... } = require('@whiskeysockets/baileys');` 附近加：

```js
const { createQueryRunner } = require('./retry.js');
```

将 `main()` 中的 `const sock = await connectWithRetry(...)` 改为 `let sock`（重连需重赋值），并把查询循环替换为：

```js
  let sock = await connectWithRetry(state, saveCreds, version);
  console.log('已连接，开始查询...\n');

  const results = [];
  // 逐个查询并加随机延时（WA_DELAY_MIN/WA_DELAY_MAX，秒，缺省固定 1.5s），
  // 降低触发风控的概率；最后一个号码后不再等待
  const delayMin = parseFloat(process.env.WA_DELAY_MIN || '1.5');
  const delayMax = parseFloat(process.env.WA_DELAY_MAX || String(delayMin));
  const randDelay = () =>
    delayMax > delayMin
      ? (delayMin + Math.random() * (delayMax - delayMin)) * 1000
      : delayMin * 1000;

  // 单号失败：退避→重连→重试；连续失败 ≥THROTTLE_THRESHOLD 判定风控中止本批
  const runner = createQueryRunner({
    maxRetries: MAX_RETRIES,
    throttleThreshold: THROTTLE_THRESHOLD,
    backoffMs: RETRY_BACKOFF_MS,
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
    reconnect: async () => {
      sock.end();
      sock = await connectWithRetry(state, saveCreds, version, 3);
    },
  });

  for (const [i, num] of numbers.entries()) {
    const r = await runner.run(num, (n) => sock.onWhatsApp(n));
    results.push(r);
    if (r.error) {
      console.log(`${num}\t⚠️ ${r.error}`);
    } else {
      console.log(`${num}\t${r.registered ? '✅ 已注册' : '❌ 未注册'}${r.jid ? `\t${r.jid}` : ''}`);
    }
    if (i < numbers.length - 1) {
      await new Promise((r2) => setTimeout(r2, randDelay()));
    }
  }

  const out = process.env.WA_RESULTS || path.join(__dirname, 'results.json');
  fs.writeFileSync(out, JSON.stringify({
    checkedAt: new Date().toISOString(), results,
    throttled: runner.isThrottled(),
  }, null, 2));
```

> 原循环里的 try/catch（push error / 记日志）已被 runner 统一替代；`sock.end()` 收尾逻辑保留在 `main()` 末尾不动。

- [ ] **Step 2: 冒烟验证不破坏正常查询**

Run: `cd fetcher/vendor/wa-check && node check.js --auth=xiaohao-1 8613670586279`
Expected: 输出 `已连接，开始查询...` 与 `8613670586279 ❌ 未注册`，退出码 0。

- [ ] **Step 3: 提交**

```bash
git add fetcher/vendor/wa-check/check.js
git commit -m "feat(wa-check): 主循环接入重试器，Connection Closed 单号重连重试"
```

---

## Task 3: 原子超时 +360s 重试预算

**Files:**
- Modify: `fetcher/fetcher/atoms/wa_check.py`
- Test: `fetcher/tests/test_wa_check.py`

- [ ] **Step 1: 写失败测试**

在 `fetcher/tests/test_wa_check.py` 的 `TestAtomOutcomes` 类末尾新增：

```python
    def test_timeout_includes_retry_budget(self):
        """超时公式含 +360s 重试预算（重试会拉长单批时长，须计入原子超时）。"""
        d = self._fake_wa_dir()
        seen = {}

        def fake_run(cmd, ctx, timeout, *, cwd, results_path, auth_dir=None):
            seen["timeout"] = timeout
            Path(results_path).write_text('{"results": []}', encoding="utf-8")
            return 0, ""

        self.atom._run_node = fake_run  # type: ignore[assignment]
        self.atom.run(FakeCtx(), {
            "numbers": ["8615156667272"], "wa_check_dir": d, "sample_max": 1.0})
        base = (60 + 1 * (1.0 + 5)) * 1.2
        self.assertGreaterEqual(seen["timeout"], base + 360)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd fetcher && python3 -m unittest tests.test_wa_check -v`
Expected: `test_timeout_includes_retry_budget ... FAIL`（当前 timeout = base，不满足 ≥ base+360）。

- [ ] **Step 3: 修改超时公式**

在 `fetcher/fetcher/atoms/wa_check.py` 中，把：

```python
            # 超时自适应：连接 ~60s + 每号码（查询 ~5s + 最大间隔），上浮 20%
            timeout = (60 + len(numbers) * (delay_max + 5)) * 1.2
```

改为：

```python
            # 超时自适应：连接 ~60s + 每号码（查询 ~5s + 最大间隔），上浮 20%；
            # 另加固定 360s 重试预算——单号失败会退避重连重试，最坏情况
            # 为「连续 5 号各重试 2 次」≈300s，因风控中止有上限，故不随号码数放大
            timeout = (60 + len(numbers) * (delay_max + 5)) * 1.2 + 360
```

- [ ] **Step 4: 运行确认通过**

Run: `cd fetcher && python3 -m unittest tests.test_wa_check -v`
Expected: `test_timeout_includes_retry_budget ... ok`，其余全部 `ok`。

- [ ] **Step 5: 提交**

```bash
git add fetcher/fetcher/atoms/wa_check.py fetcher/tests/test_wa_check.py
git commit -m "fix(wa-check): 原子超时含 360s 重试预算，防重试批被超时误杀"
```

---

## Task 4: wa_tasks 抽 `_rest_with_heartbeat` 助手

**Files:**
- Modify: `platform/server/app/wa_tasks.py`
- Test: `platform/server/tests/test_wa_tasks_cooldown.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `platform/server/tests/test_wa_tasks_cooldown.py`：

```python
# -*- coding: utf-8 -*-
"""wa_tasks 分段等待助手与风控冷却测试。"""

import os
import sqlite3
import tempfile
import threading
import unittest

from app import db, runner, wa_tasks


def _make_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            params_json TEXT NOT NULL,
            celery_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            progress_json TEXT,
            stop_requested INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            flow_id INTEGER
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT
        );
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY,
            mobile TEXT,
            phone TEXT,
            wa_registered INTEGER,
            wa_checked_at TEXT
        );
        INSERT INTO tasks (id, type, params_json, status, created_at)
        VALUES (1, 'wa_check', '{"accounts": ["xiaohao-1"]}',
                'pending', '2026-08-05 12:00:00');
        """
    )
    conn.commit()
    conn.close()


class _Base(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        _make_db(self.db)
        self.old_db = db.DB_PATH
        self.old_runner_db = runner.DB_PATH
        self.old_wa_db = wa_tasks.DB_PATH
        db.DB_PATH = self.db
        runner.DB_PATH = self.db
        wa_tasks.DB_PATH = self.db

    def tearDown(self):
        db.DB_PATH = self.old_db
        runner.DB_PATH = self.old_runner_db
        wa_tasks.DB_PATH = self.old_wa_db
        try:
            os.unlink(self.db)
        except OSError:
            pass


class RestHeartbeatTest(_Base):
    def test_short_rest_completes_not_interrupted(self):
        stop = threading.Event()
        result = wa_tasks._rest_with_heartbeat(1, 0.01, "测试", stop)
        self.assertFalse(result)

    def test_interrupted_returns_true(self):
        stop = threading.Event()
        stop.set()
        result = wa_tasks._rest_with_heartbeat(1, 60, "测试", stop)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd platform/server && ./.venv/bin/python -m unittest tests.test_wa_tasks_cooldown -v`
Expected: FAIL — `AttributeError: module 'app.wa_tasks' has no attribute '_rest_with_heartbeat'`。

- [ ] **Step 3: 实现助手并替换批间休息**

在 `wa_tasks.py` 中 `_apply_results` 之后新增：

```python
def _rest_with_heartbeat(task_id: int, seconds: float, label: str,
                         stop_event: threading.Event) -> bool:
    """分段等待 + 心跳日志，可被 stop_event 中断；返回是否被中断。

    每段最多 30s 刷一条「剩余约 N 分钟」心跳，避免休息期间日志静默
    被误判为卡死；每段都可被 stop_event 中断。
    """
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if stop_event.wait(min(30.0, remaining)):
            return True
        remaining = deadline - time.monotonic()
        if remaining > 1:
            _insert_event(
                task_id, "info",
                f"⏸ {label}，剩余约 {remaining / 60:.1f} 分钟...")
```

把 `run()` 内批间休息的「分段等待 + 心跳」块（原 `deadline = time.monotonic() + rest` 到 `_insert_event(..., "▶ 批间休息结束，继续查号")`）替换为：

```python
            if (bi < len(batches) and batch_num > 0
                    and nums_since_rest >= batch_num):
                rest = random.uniform(rest_min, rest_max)
                _insert_event(
                    task_id, "info",
                    f"⏸ 本批已查满 {nums_since_rest} 个号码，"
                    f"批间休息 {rest / 60:.1f} 分钟（防风控）...",
                    {"checked": checked, "registered": registered,
                     "rest_seconds": round(rest, 1)})
                if _rest_with_heartbeat(task_id, rest, "批间休息",
                                        stop_event):
                    stopped = True
                    break
                nums_since_rest = 0
                _insert_event(task_id, "info", "▶ 批间休息结束，继续查号")
```

- [ ] **Step 4: 运行确认通过**

Run: `cd platform/server && ./.venv/bin/python -m unittest tests.test_wa_tasks_cooldown tests.test_wa_tasks_guard -v`
Expected: 全部 `ok`（含既有守卫生效测试）。

- [ ] **Step 5: 提交**

```bash
git add platform/server/app/wa_tasks.py platform/server/tests/test_wa_tasks_cooldown.py
git commit -m "refactor(wa_tasks): 抽取 _rest_with_heartbeat 分段等待助手，批间休息复用"
```

---

## Task 5: wa_tasks 风控冷却 + checked 计数修正

**Files:**
- Modify: `platform/server/app/wa_tasks.py`
- Test: `platform/server/tests/test_wa_tasks_cooldown.py`

- [ ] **Step 1: 写失败测试**

在 `platform/server/tests/test_wa_tasks_cooldown.py` 追加（顶部加 `import json` 与 `from unittest.mock import patch`，以及 `from fetcher.core.types import ActionResult`）：

```python
import json
from unittest.mock import patch

from fetcher.core.types import ActionResult


class ThrottleCooldownTest(_Base):
    def _ok(self, results):
        done = sum(1 for r in results if r.get("registered") is not None)
        hits = sum(1 for r in results if r.get("registered"))
        return ActionResult.success("ok", results=results,
                                    checked=done, registered=hits)

    def _rows(self, n=50):
        return [(i, f"86130000000{i:02d}") for i in range(1, n + 1)]

    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
    @patch("app.wa_tasks._fetch_pending_rows")
    @patch("app.wa_tasks.CheckWhatsApp")
    def test_high_error_ratio_triggers_cooldown(self, mock_cls, mock_rows, mock_apply):
        # 100 个号码 = 2 批，冷却在批 1 之后触发（需 bi < len(batches)）
        mock_rows.return_value = self._rows(100)
        # 40 个出错 + 60 个正常 → 错误率 40% ≥ 30%
        results = [{"number": f"8613{i:07d}", "registered": None, "error": "x"}
                   for i in range(40)]
        results += [{"number": f"8614{i:07d}", "registered": False}
                    for i in range(60)]
        mock_cls.return_value.run.return_value = self._ok(results)

        with patch("app.wa_tasks.THROTTLE_COOLDOWN_MIN", 0.01), \
             patch("app.wa_tasks.THROTTLE_COOLDOWN_MAX", 0.02):
            wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())

        conn = sqlite3.connect(self.db)
        warnings = conn.execute(
            "SELECT message FROM task_events WHERE task_id=1 "
            "AND level='warning' AND message LIKE '%风控%'").fetchall()
        conn.close()
        self.assertTrue(any("疑似风控" in w[0] for w in warnings))
        self.assertTrue(any("额外冷却" in w[0] for w in warnings))

    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
    @patch("app.wa_tasks._fetch_pending_rows")
    @patch("app.wa_tasks.CheckWhatsApp")
    def test_low_error_ratio_no_cooldown(self, mock_cls, mock_rows, mock_apply):
        mock_rows.return_value = self._rows()
        results = [{"number": f"8613{i:07d}", "registered": False}
                   for i in range(50)]  # 0 出错
        mock_cls.return_value.run.return_value = self._ok(results)

        wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())

        conn = sqlite3.connect(self.db)
        cools = conn.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id=1 "
            "AND message LIKE '%额外冷却%'").fetchone()
        conn.close()
        self.assertEqual(cools[0], 0)

    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
    @patch("app.wa_tasks._fetch_pending_rows")
    @patch("app.wa_tasks.CheckWhatsApp")
    def test_checked_counts_done_not_batch(self, mock_cls, mock_rows, mock_apply):
        # 2 个号码，1 个出错（registered:null）→ checked 应计 1 而非 2
        mock_rows.return_value = self._rows(2)
        results = [
            {"number": "8613000000001", "registered": False},
            {"number": "8613000000002", "registered": None, "error": "x"},
        ]
        mock_cls.return_value.run.return_value = self._ok(results)

        wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())

        conn = sqlite3.connect(self.db)
        prog = conn.execute(
            "SELECT progress_json FROM tasks WHERE id=1").fetchone()
        conn.close()
        self.assertEqual(json.loads(prog[0])["checked"], 1)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd platform/server && ./.venv/bin/python -m unittest tests.test_wa_tasks_cooldown -v`
Expected: `ThrottleCooldownTest` 三个测试 FAIL（风控逻辑尚未实现）。

- [ ] **Step 3: 实现常量 + 错误率统计 + 冷却 + 计数修正**

在 `wa_tasks.py` 常量区（`MAX_CONSECUTIVE_FATAL` 附近）新增：

```python
# 风控冷却：批内错误率 ≥ 阈值判定疑似风控，批后额外长冷却（防风控加重）
THROTTLE_RATIO = 0.3
THROTTLE_COOLDOWN_MIN = 1200.0   # 20 分钟
THROTTLE_COOLDOWN_MAX = 1800.0   # 30 分钟
```

在 `run()` 的 `nums_since_rest = 0` 后加：

```python
        throttle_rest = False  # 本批疑似风控 → 批后额外长冷却
```

把 OK 分支：

```python
            if res.outcome is Outcome.OK:
                consec_fatal = 0
                results = res.data.get("results") or []
                written, skipped_err, skipped_amb = _apply_results(results)
                hits = sum(1 for r in results if r.get("registered"))
                checked += len(batch)
                registered += hits
                msg = (f"批次 {bi}/{len(batches)}：查 {len(batch)} 个，"
                       f"累计已注册 {registered}")
                extra = []
                if skipped_err:
                    extra.append(f"{skipped_err} 个查询出错未写回")
                if skipped_amb:
                    extra.append(f"{skipped_amb} 个号码匹配歧义跳过")
                if extra:
                    msg += "（" + "，".join(extra) + "）"
                _insert_event(task_id, "info", msg, {
                    "batch": bi, "batches": len(batches),
                    "worker": account_name,
                    "account": account_name, "checked": checked,
                    "registered": registered, "written": written,
                })
```

替换为：

```python
            if res.outcome is Outcome.OK:
                consec_fatal = 0
                results = res.data.get("results") or []
                written, skipped_err, skipped_amb = _apply_results(results)
                hits = sum(1 for r in results if r.get("registered"))
                done = sum(1 for r in results
                           if r.get("registered") is not None)
                err_cnt = len(results) - done
                checked += done  # 只计有结果的号码，出错号码保持 NULL 待查
                registered += hits
                msg = (f"批次 {bi}/{len(batches)}：查 {done}/{len(batch)} 个，"
                       f"累计已注册 {registered}")
                extra = []
                if err_cnt and len(results):
                    ratio = err_cnt / len(results)
                    extra.append(f"{err_cnt} 个查询出错未写回")
                    if ratio >= THROTTLE_RATIO:
                        throttle_rest = True
                        _insert_event(
                            task_id, "warning",
                            f"批次 {bi}/{len(batches)} 错误率 {ratio:.0%}"
                            f"（{err_cnt}/{len(results)}）"
                            f" ≥{THROTTLE_RATIO:.0%}，疑似风控，批后将额外冷却",
                            {"err_cnt": err_cnt, "ratio": round(ratio, 2),
                             "throttle_rest": True})
                if skipped_amb:
                    extra.append(f"{skipped_amb} 个号码匹配歧义跳过")
                if extra:
                    msg += "（" + "，".join(extra) + "）"
                _insert_event(task_id, "info", msg, {
                    "batch": bi, "batches": len(batches),
                    "worker": account_name,
                    "account": account_name, "checked": checked,
                    "registered": registered, "written": written,
                })
```

在批间休息块之后（`▶ 批间休息结束，继续查号` 的 `_insert_event` 之后）追加风控冷却块：

```python
            # 风控冷却：高错误率批次后额外长休息（不等 batch_num 边界）
            if throttle_rest and bi < len(batches):
                cooldown = random.uniform(THROTTLE_COOLDOWN_MIN,
                                          THROTTLE_COOLDOWN_MAX)
                _insert_event(
                    task_id, "warning",
                    f"⏸ 疑似风控，额外冷却 {cooldown / 60:.1f} 分钟...",
                    {"checked": checked, "registered": registered,
                     "cooldown_seconds": round(cooldown, 1)})
                if _rest_with_heartbeat(task_id, cooldown, "风控冷却",
                                        stop_event):
                    stopped = True
                    break
                throttle_rest = False
```

- [ ] **Step 4: 运行确认通过**

Run: `cd platform/server && ./.venv/bin/python -m unittest discover -s tests -v`
Expected: 全部 `ok`（含 guard / cooldown / 既有 14 个测试）。

- [ ] **Step 5: 提交**

```bash
git add platform/server/app/wa_tasks.py platform/server/tests/test_wa_tasks_cooldown.py
git commit -m "feat(wa_tasks): 批级错误率≥30% 触发风控额外冷却；checked 只计有结果号码"
```

---

## Task 6: 端到端冒烟 + 全量回归

**Files:** 无（仅验证）

- [ ] **Step 1: Node 重试器单测**

Run: `cd fetcher/vendor/wa-check && node --test test/retry.test.cjs`
Expected: `# pass 6` / `# fail 0`。

- [ ] **Step 2: Python 全量测试（fetcher + server）**

Run:
```bash
cd fetcher && python3 -m unittest discover -s tests -v
cd platform/server && ./.venv/bin/python -m unittest discover -s tests -v
```
Expected: 两处全部 `ok`。

- [ ] **Step 3: check.js 冒烟（真实连接，1 个号码）**

Run: `cd fetcher/vendor/wa-check && node check.js --auth=xiaohao-1 8613670586279`
Expected: `已连接，开始查询...` → `8613670586279 ❌ 未注册` → `完成`，退出码 0。

- [ ] **Step 4: 说明**

后端改动需重启才生效（AGENTS.md 约定）：`platform/stop.sh && platform/start.sh`。重启后空账号拦截与风控冷却才在生产生效；check.js 改动即时生效（每次原子子进程都是新拉起）。

---

## 自检

**1. Spec 覆盖**
- 「单号重连重试 ≤2 次」→ Task 1/2 ✅
- 「连续失败 ≥5 中止本批 + throttled 字段」→ Task 1/2 ✅
- 「错误率 ≥30% 风控冷却 20~30 分钟」→ Task 5 ✅
- 「抽 _rest_with_heartbeat 复用」→ Task 4 ✅
- 「原子超时 +360s」→ Task 3 ✅
- 「checked 只计有结果号码」→ Task 5 ✅
- 「数据语义不变（NULL 待查）」→ 无代码改动（`_apply_results` 跳过 `registered:null` 既有行为）✅

**2. 占位符扫描**：所有代码块完整，无 TBD/TODO。

**3. 类型一致性**：
- `createQueryRunner({...})` 工厂参数 `maxRetries/throttleThreshold/backoffMs/sleep/reconnect` 在 Task 1 定义、Task 2 使用一致。
- `runner.run(num, query)` / `runner.isThrottled()` 在 Task 1/2 一致。
- `_rest_with_heartbeat(task_id, seconds, label, stop_event) -> bool` 在 Task 4/5 一致。
- `ActionResult.success("ok", results=..., checked=..., registered=...)` 与原子返回值一致。
