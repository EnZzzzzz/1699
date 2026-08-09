# Step 3.2 — app/db.py enqueue 双函数（TDD）执行报告

## 状态：DONE

## 实现了什么

### `platform/server/app/db.py`（新增两个函数，插在 `enqueue_fb_post_batch` 与 `enqueue_feeder_batch` 之间）

1. **`enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`**
   - keywords 按 `splitlines()` 拆词 → strip → 过滤空行；空 → 返回 0。
   - 每词 × 每页（1..pages，`pages<1` 视为 1）展开；payload
     `{"kind":"serp","engine":"ddg","query":kw,"page":N}`。
   - INSERT `work_items (queue='discover_fb', site=NULL, batch_id, payload_json,
     requires='["local"]', created_at=_bj_now())`。
   - 幂等：INSERT 前查 `work_items WHERE queue='discover_fb' AND status='pending'
     AND json_extract(payload_json,'$.query')=? AND json_extract(payload_json,'$.page')=?`
     存在则跳过（json_extract 模式参照 `enqueue_feeder_batch`）。
   - 返回实际入队数。

2. **`enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`**
   - 结构对齐 `enqueue_fb_post_batch`：`sqlite3.connect(DB_PATH, timeout=30)` +
     `PRAGMA busy_timeout=30000` + sqlite_master 探测 fb_groups 表（无 → 0）+
     `BEGIN IMMEDIATE` 单事务。
   - SELECT pending fb_groups（`ORDER BY first_seen_at, id`，limit>0 时 `LIMIT ?`）→
     INSERT work_items（queue='crawl_fb_group'、site=NULL、batch_id、payload
     `{"url":r["url"],"provider":provider,"limit":posts_per_group}`、
     requires='["local"]'、created_at）→ UPDATE fb_groups `status='in_progress'`。
   - 异常 rollback + raise；finally close。返回入队行数。

### `platform/server/app/runner.py`（懒导入收尾，跨 Step 必做项）

- `enqueue_fb_discover_batch` / `enqueue_fb_group_batch` 并入 `enqueue_batch_for_task`
  函数顶部既有 `from app.db import (...)` 集中 import；
- 删掉 fb_discover/fb_group 两分支内的懒导入与「Step 3.2 提供真实函数」占位注释
  （改为描述缺省值语义的注释）。

### `platform/server/tests/test_batch_tasks.py`（新增 `FbBatchEnqueueTest`，7 个测试）

临时 sqlite（复用 `BatchTasksTestBase` patch DB_PATH）断言真实行：

| 测试 | 覆盖 |
|---|---|
| `test_fb_discover_expands_keywords_times_pages` | 2 词 × 2 页 = 4 条；payload 全键（kind/engine/query/page）、requires=['local']、site=NULL、batch_id；词×页组合恰好各一条 |
| `test_fb_discover_idempotent_same_query_page` | 二次调用同 query+page（已有 pending）→ 入队 0，总条数不变 |
| `test_fb_discover_empty_keywords_returns_zero` | 空串 / 纯空白行 → 0，不产生 item |
| `test_fb_discover_pages_less_than_one_treated_as_one` | pages=0 → 按 1 页 |
| `test_fb_group_enqueues_and_marks_in_progress` | limit=2 取 2 群；payload {url,provider,limit}（limit=50=posts_per_group）；源行前 2 群 in_progress、第 3 群仍 pending |
| `test_fb_group_limit_zero_unlimited` | limit=0 → 全部 3 群入队 |
| `test_fb_group_missing_table_returns_zero` | fb_groups 表不存在 → 0（防御性探测），不产生 item |

## TDD 证据

### RED

命令：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks.FbBatchEnqueueTest -v`

```
ERROR: test_fb_discover_expands_keywords_times_pages ...
ImportError: cannot import name 'enqueue_fb_discover_batch' from 'app.db'
...
ERROR: test_fb_group_missing_table_returns_zero ...
ImportError: cannot import name 'enqueue_fb_group_batch' from 'app.db'
...
Ran 7 tests in 0.274s
FAILED (errors=7)
```

符合预期：失败原因是功能缺失（两个函数尚未实现），非笔误。7/7 全 error。

### GREEN

命令：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks.FbBatchEnqueueTest -v`

```
Ran 7 tests in 0.227s
OK
```

实现最小化：只加了 brief 规定的两个函数 + runner 懒导入收尾，无多余改动。

## 测试结果（验收命令 + 回归）

```
$ .venv/bin/python -m unittest tests.test_batch_tasks          # 28 tests OK（21 既有 + 7 新增）
$ .venv/bin/python -m unittest tests.test_fb_batch             # 14 tests OK（未触碰文件回归）
```

- 既有 `FbBatchDispatchTest`（Step 3.1，mock `db_module.enqueue_fb_*`）在懒导入
  收尾后仍全过：集中 import 在函数调用时解析模块属性，patch.object 依然生效。
- 输出干净，无 error/warning。

## 改动的文件

- `platform/server/app/db.py`（+96 行：两个 enqueue 函数）
- `platform/server/app/runner.py`（-6/+4 行：懒导入收尾）
- `platform/server/tests/test_batch_tasks.py`（+118 行：FbBatchEnqueueTest）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-brief.md` / `task-3.2-report.md`（本 Step 文档）

## 自查

- **完整性**：SPEC §6.2 两条 + 协调者裁定 1-7 逐条对照，全部落实。边界覆盖：
  空关键词（含纯空白行）、limit=0、pages<1、fb_groups 表缺失、同 query+page 幂等。
- **质量**：`enqueue_fb_group_batch` 直接对齐 `enqueue_fb_post_batch` 的事务/探测结构
  （BEGIN IMMEDIATE、sqlite_master、LIMIT 拼装、rollback/raise/finally）；
  `enqueue_fb_discover_batch` 幂等模式对齐 `enqueue_feeder_batch` 的 json_extract 写法；
  注释为中文、顶部一行说明函数职责。
- **纪律**：只做了 brief 要求的内容（含跨 Step 懒导入收尾）；未重构任务范围外代码。
- **测试**：真实行为断言（临时 sqlite 真实行 + payload 解析断言），无 mock 实现；
  TDD 流程完整（先 RED 亲眼看失败 → 最小实现 → GREEN）。

## 疑虑

- `enqueue_fb_discover_batch` 未用 BEGIN IMMEDIATE（与 `enqueue_feeder_batch` 同型）：
  幂等检查与 INSERT 之间理论上存在并发窗口，但代码库既有 feeder 模式即如此，
  brief 裁定 2 明确参照该模式，未加锁属有意对齐（YAGNI，不扩大范围）。
