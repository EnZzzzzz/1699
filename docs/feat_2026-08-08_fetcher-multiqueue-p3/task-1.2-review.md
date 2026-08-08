# Review Package — Step 1.2 (冷却表改建)

## Commits
ebd16ba feat(multiqueue-p3): cooldown key to site + eligible_queues + claim filter with condvar_timeout

## Stat
 .../task-1.2-report.md                             | 120 ++++++++++++++++++
 fetcher/fetcher/control/daemon_task.py             |  22 +++-
 fetcher/fetcher/control/loop.py                    |   9 +-
 fetcher/fetcher/control/queue_router.py            |  49 ++++++++
 fetcher/fetcher/core/context.py                    |   9 +-
 fetcher/tests/test_cooldown.py                     |  49 +++++---
 fetcher/tests/test_daemon_task.py                  |  56 +++++++++
 fetcher/tests/test_queue_router.py                 | 140 +++++++++++++++++++++
 8 files changed, 427 insertions(+), 27 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.2-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.2-report.md
new file mode 100644
index 0000000..628e91e
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.2-report.md
@@ -0,0 +1,120 @@
+# Task 1.2 Report — 冷却表改建（键改 site）+ eligible_queues + claim 过滤与 condvar timeout
+
+> 分支：`feat/multiqueue-p3` ｜ 状态：DONE ｜ TDD 全流程完成，全量 336 passed（基线 319 + 新增 17）
+
+## 实现摘要
+
+### 1. `WorkerContext.cooldown_until` 键语义改 site（core/context.py）
+
+- docstring 更新：「site 注册名 → 到期时刻」；删除 P1「只写不读」遗留注释，替换为 site 语义说明
+- 新增字段 `resources: set[str]`，默认 `{"channel", "browser"}`（与 SPEC §4.2 BrowserConsumer 一致）
+
+### 2. `eligible_queues` + `condvar_timeout` 纯函数（新建 control/queue_router.py）
+
+- `QueueSpec` dataclass：三字段 queue / site / requires
+- `eligible_queues(registry, ctx, now) -> list[str]`：资源满足 ∧ 冷却到期，返回队列名列表（按注册表顺序），纯函数无副作用
+- `condvar_timeout(cooldown_until, site, now, cap=30.0) -> float`：冷却中 → min(剩余, cap)；不在冷却 → cap；返回值总是 > 0
+
+### 3. `CrawlLoop._cooldown` 键改 site（control/loop.py）
+
+- 登记逻辑：`active_site = ctx.state.get("active_site")` → 有则 `cooldown_until[active_site] = time.time() + seconds`，无则不登记
+- `reason` 参数保留，仅用于日志/展示
+- 等待行为不变（原地等待）
+
+### 4. `DaemonTaskProxy.acquire_item` 冷却过滤 + condvar timeout + active_site（control/daemon_task.py）
+
+- claim 前查冷却：`now < ctx.cooldown_until.get(self._site, 0)` → 不 claim 不 topup，直接进 condvar wait（timeout 经 condvar_timeout 计算）
+- claim 成功后在 `ctx.state["active_site"] = self._site`
+- 其余（topup notify_all、stop 检查、_WAIT_TIMEOUT 兜底）保持现状
+
+## 测试列表
+
+### test_queue_router.py（新建，12 个用例）
+
+| 测试 | 覆盖点 |
+|---|---|
+| `test_construction_and_fields` | QueueSpec 构造与字段访问 |
+| `test_all_eligible_with_no_cooldown` | 无冷却时全队列可见 |
+| `test_cooldown_filters_site_queues` | 用例 1：site A 冷却中 → 该 site 队列被滤 |
+| `test_resource_filtering` | 用例 2：requires 超 resources → 被滤 |
+| `test_expiry_recovery` | 用例 3：now 推进到冷却到期 → 恢复可见 |
+| `test_empty_registry` | 空注册表 → 空列表 |
+| `test_empty_resources_still_matches_empty_requires` | 空 resources 仍可匹配空 requires 队列 |
+| `test_not_in_cooldown_returns_cap` | 不在冷却 → cap=30 |
+| `test_in_cooldown_returns_min_of_remaining_and_cap` | 用例 4：冷却中 → min(剩余, 30) |
+| `test_custom_cap` | 自定义 cap 生效 |
+| `test_very_small_remaining_returns_positive` | 剩余 0.01s → 返回 0.01（>0） |
+| `test_exactly_at_deadline_returns_cap` | now==到期 → cap |
+
+### test_cooldown.py（适配 7 处 + 新增 2 个用例）
+
+| 测试 | 变更 |
+|---|---|
+| `test_silent_path_writes_deadline_and_returns_false` | reason 键断言 → 空 dict 断言（无 active_site） |
+| `test_countdown_path_stop_interrupt_returns_true_fast` | reason 键断言 → 空 dict 断言 |
+| `test_strategy_cooldown_via_chokepoint_then_retry_success` | cooldown_until["strategy:cool"] 断言 → 空 dict |
+| `test_batch_sample_periodic_rest_via_chokepoint` | 三类 reason 均登记 → 空 dict + reason spy 证据 |
+| `test_launch_backoff_via_chokepoint` | cooldown_until 含 "launch_backoff" → 空 dict |
+| `test_site_key_when_active_site_set` | **新增**：设 active_site → 登记 site 键 |
+| `test_no_registration_without_active_site` | **新增**：未设 active_site → 不登记 |
+
+### test_daemon_task.py（新增 3 个用例）
+
+| 测试 | 覆盖点 |
+|---|---|
+| `test_cooldown_blocks_claim` | 用例 5：冷却中 → acquire 阻塞，不 claim 不 topup |
+| `test_cooldown_expired_allows_claim` | 用例 6：冷却到期 → 正常 claim |
+| `test_active_site_set_on_claim` | 用例 7：claim 成功后 state["active_site"] 正确 |
+
+## TDD 证据
+
+### RED（实现前）
+
+```
+$ python -m pytest tests/test_queue_router.py tests/test_cooldown.py tests/test_daemon_task.py -q
+ERROR collecting tests/test_queue_router.py — ModuleNotFoundError: No module named 'fetcher.control.queue_router'
+FAILED tests/test_cooldown.py::CooldownChokepointTest::test_countdown_path_stop_interrupt_returns_true_fast
+FAILED tests/test_cooldown.py::CooldownChokepointTest::test_no_registration_without_active_site
+FAILED tests/test_cooldown.py::CooldownChokepointTest::test_silent_path_writes_deadline_and_returns_false
+FAILED tests/test_cooldown.py::CooldownChokepointTest::test_site_key_when_active_site_set
+FAILED tests/test_cooldown.py::StrategyCooldownIntegrationTest::test_strategy_cooldown_via_chokepoint_then_retry_success
+FAILED tests/test_cooldown.py::WaitPointsTest::test_batch_sample_periodic_rest_via_chokepoint
+FAILED tests/test_cooldown.py::WaitPointsTest::test_launch_backoff_via_chokepoint
+FAILED tests/test_daemon_task.py::CooldownFilterTest::test_active_site_set_on_claim
+FAILED tests/test_daemon_task.py::CooldownFilterTest::test_cooldown_blocks_claim
+9 failed, 7 passed in 12.10s
+```
+
+失败全部预期：queue_router 模块不存在（ImportError）、cooldown_until 仍按 reason 键写入（site 键断言失败）、daemon 无冷却过滤（claim 立即成功）。
+
+### GREEN（实现后）
+
+```
+$ python -m pytest tests/test_queue_router.py tests/test_cooldown.py tests/test_daemon_task.py -q
+28 passed in 12.14s
+```
+
+### 全量无回归
+
+```
+$ cd fetcher && python -m pytest tests -q
+336 passed, 2 subtests passed in 24.64s   （基线 319 + 新增 17）
+```
+
+## 改动文件
+
+- `fetcher/fetcher/core/context.py`：cooldown_until docstring 更新 + 新增 resources 字段
+- `fetcher/fetcher/control/queue_router.py`（**新建**）：QueueSpec / eligible_queues / condvar_timeout
+- `fetcher/fetcher/control/loop.py`：_cooldown 键改 site（active_site 有则登记，无则跳过）
+- `fetcher/fetcher/control/daemon_task.py`：acquire_item 增加冷却过滤、condvar_timeout、active_site 写入
+- `fetcher/tests/test_queue_router.py`（**新建**）：12 个纯函数用例
+- `fetcher/tests/test_cooldown.py`：7 处断言适配 + 2 个新用例
+- `fetcher/tests/test_daemon_task.py`：新增 CooldownFilterTest 类（3 个用例）
+
+## 自查发现
+
+- **等待行为未改**：loop 原地等待、daemon_task queue-empty 路径仍用 _WAIT_TIMEOUT（30s 兜底），仅 cooldown-wait 路径改用 condvar_timeout。让出型行为是 Step 1.3 内容。
+- **active_site 设置时机**：仅 daemon_task claim 成功后才设，CLI 路径 / CrawlLoop 直接调用路径不设。这与 brief「acquire 前的原地型路径——launch_backoff——active_site 未设置，天然不登记」一致。
+- **cooldown_until 语义变更影响面**：既有 test_cooldown.py 全部 5 个 wait-point 测试的 cooldown_until 断言均改为空（因这些路径无 active_site）。不登记意味着 CLI 路径的等待无法被 daemon 调度器查询——这是刻意设计：site 键语义只服务于 daemon 消费者的跨队列冷却感知，CLI 路径本来就不该被调度器看到。
+- **condvar_timeout 与 _WAIT_TIMEOUT 分离**：cooldown wait 用 condvar_timeout（冷却感知），queue-empty wait 仍用 _WAIT_TIMEOUT（30s 兜底）。若 Step 1.3 需要统一，届时收敛不迟。
+- 他人未提交改动（platform/*、vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/）未触碰。
diff --git a/fetcher/fetcher/control/daemon_task.py b/fetcher/fetcher/control/daemon_task.py
index 27996a1..ab279f2 100644
--- a/fetcher/fetcher/control/daemon_task.py
+++ b/fetcher/fetcher/control/daemon_task.py
@@ -11,21 +11,23 @@ shops」换成「从 work_items 表认领」：acquire_item 三段式
 （落终态钩子），类属性显式转发，其余方法经 __getattr__ 透传 inner。
 
 线程安全：proxy 实例被 Engine 跨 worker 线程共享——条件变量负责
 等货/补货通知；每 worker 认领的 work_item id 记在该 worker 自己的
 ctx.state 上（WorkerContext 每 worker 独立），天然隔离无需加锁。
 """
 
 from __future__ import annotations
 
 import threading
+import time
 
+from fetcher.control.queue_router import condvar_timeout
 from fetcher.db import ShopDB
 
 # 等货条件变量自醒超时（秒）：保证 stop 置位后 acquire_item 最多 30s 内返回
 _WAIT_TIMEOUT = 30.0
 
 # ctx.state 上记录当前 worker 认领的 work_item id 的键
 _STATE_KEY = "daemon_work_item_id"
 
 
 class DaemonTaskProxy:
@@ -125,37 +127,47 @@ class DaemonTaskProxy:
             db.close()
         print(f"[daemon] 队列 {self._queue}: 待补货店铺 {shops_pending} 个 + "
               f"待认领工作项 {items_pending} 个")
         return True
 
     # ---- worker 循环：工作项认领（三段式）----
 
     def acquire_item(self, ctx):
         """认领一个工作项；仅 stop 置位时返回 None，否则阻塞等货。
 
-        1. claim 命中 → 记录 work_item id 后返回 payload dict
-           （必含 domain/name/url 三键，由 claim_work_item 保证）；
-        2. 未命中 → 补货（limit=消费者数×4），补到则 notify_all 唤醒
-           等货的其他 worker 并重试 claim；
-        3. 仍无货 → 条件变量 wait（30s 自醒兜底），醒后先查 stop。
+        1. 冷却过滤：claim 前查冷却（site 键），冷却中不 claim 不 topup，
+           直接进 condvar wait（timeout 经 condvar_timeout 计算）；
+        2. claim 命中 → 记录 work_item id + active_site 后返回 payload；
+        3. 未命中 → 补货（limit=消费者数×4），补到则 notify_all 并重试；
+        4. 仍无货 → 条件变量 wait（30s 自醒兜底），醒后先查 stop。
         """
         consumer_id = f"w{ctx.wid}"
         db = self._db(ctx)
         limit = self._topup_limit(ctx)
         with self._cond:
             while True:
                 if ctx.stopped():
                     return None
+                now = time.time()
+                # 冷却中：不 claim 不 topup，直接进 condvar wait
+                if now < ctx.cooldown_until.get(self._site, 0):
+                    timeout = condvar_timeout(
+                        ctx.cooldown_until, self._site, now)
+                    self._cond.wait(timeout=timeout)
+                    if ctx.stopped():
+                        return None
+                    continue
                 item = db.claim_work_item(self._queue, consumer_id)
                 if item is not None:
                     # 记在本 worker 自己的 ctx.state 上，跨 worker 天然隔离
                     ctx.state[_STATE_KEY] = item["id"]
+                    ctx.state["active_site"] = self._site
                     return item
                 n = db.topup_contact_work_items(
                     self._queue, self._site, self._domain_suffix, limit=limit)
                 if n:
                     self._cond.notify_all()
                     continue
                 self._cond.wait(timeout=_WAIT_TIMEOUT)
                 if ctx.stopped():
                     return None
 
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index 724af46..d6140db 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -102,25 +102,30 @@ class CrawlLoop:
 
     def log(self, msg: str):
         self.ctx.log(f"{self.tag} {msg}")
 
     # ---- 冷却 chokepoint（SPEC §3.3：唯一等待执行点）----
 
     def _cooldown(self, seconds: float, reason: str,
                   prefix: str | None = None) -> bool:
         """登记冷却截止时间 + 执行可中断等待。返回 True=被 stop 中断。
 
-        cooldown_until 的唯一写入者（P1 只写不读，P3 调度器查询接口）。
+        P3：cooldown_until 按 site 注册名登记（有 active_site 时才写入）；
+        reason 参数保留，仅用于日志/展示。无 active_site 时不登记（如
+        launch_backoff 在 acquire 前，active_site 未设置时天然跳过）。
+
         展示两路径逐字保留现状：prefix 非空走 wait_countdown（秒级倒计
         时状态行，长等待用）；prefix=None 走 ctx.wait（静默，短等待用）。
         """
-        self.ctx.cooldown_until[reason] = time.time() + seconds
+        active_site = self.ctx.state.get("active_site")
+        if active_site is not None:
+            self.ctx.cooldown_until[active_site] = time.time() + seconds
         if prefix is None:
             return self.ctx.wait(seconds)
         return wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
                               seconds, prefix,
                               set_status=self.ctx.set_status)
 
     # ---- 主流程 ----
 
     def run(self) -> dict:
         """worker 完整生命周期；返回本 worker 的统计字典。"""
diff --git a/fetcher/fetcher/control/queue_router.py b/fetcher/fetcher/control/queue_router.py
new file mode 100644
index 0000000..5897fe3
--- /dev/null
+++ b/fetcher/fetcher/control/queue_router.py
@@ -0,0 +1,49 @@
+# -*- coding: utf-8 -*-
+"""队列路由表与冷却感知的等待函数（P3 Step 1.2 纯函数，无副作用）。
+
+P3-3 将在此文件演进 QueueRouter 类，本 Step 先放基础成员。
+"""
+
+from __future__ import annotations
+
+from dataclasses import dataclass
+
+
+@dataclass
+class QueueSpec:
+    """队列注册表条目（P3-3 补全 task/topup/domain_suffix 字段）。"""
+    queue: str            # "crawl_1688_contact" / ...
+    site: str             # 站点注册名 "1688" / "madeinchina"
+    requires: set[str]    # 资源需求，如 {"channel", "browser"}
+
+
+def eligible_queues(registry, ctx, now: float) -> list[str]:
+    """当前消费者可认领的队列名列表：资源满足 ∧ 该站点冷却已到期。
+
+    registry: 可迭代的 QueueSpec（或鸭子类型：有 .queue/.site/.requires）。
+    ctx: 有 .resources（set）与 .cooldown_until（dict[site, float]）的对象。
+    纯函数，无副作用；返回按注册表顺序。
+    """
+    result = []
+    for q in registry:
+        if q.requires <= ctx.resources \
+                and now >= ctx.cooldown_until.get(q.site, 0):
+            result.append(q.queue)
+    return result
+
+
+def condvar_timeout(cooldown_until: dict[str, float], site: str,
+                    now: float, cap: float = 30.0) -> float:
+    """计算 Condition.wait 的超时值（秒）。
+
+    - site 在冷却中（now < 到期） → min(到期 - now, cap)
+    - site 不在冷却 → cap
+    - 返回值总是 > 0（若冷却剩余极小如 0.01s 则原样返回）。
+
+    cap 默认为 30s，作为自醒兜底（外部 INSERT 无 notify，最坏 30s 发现）。
+    """
+    deadline = cooldown_until.get(site, 0)
+    if now < deadline:
+        remaining = deadline - now
+        return remaining if remaining < cap else cap
+    return cap
diff --git a/fetcher/fetcher/core/context.py b/fetcher/fetcher/core/context.py
index 6e21cf3..9c17320 100644
--- a/fetcher/fetcher/core/context.py
+++ b/fetcher/fetcher/core/context.py
@@ -100,24 +100,27 @@ class WorkerContext:
     wid: int = 0
     tag: str = ""
 
     # 最近一次抓取抛出的异常（Detector 分级 NET_ERROR/NET_STALL/
     # BROWSER_DEAD 的输入；由抓取原子/控制层写入）
     last_error: BaseException | None = None
     # 最近一次抓取的业务结果（抓取原子写回，persist 用）
     last_result: Any = None
     # 控制层/策略层暂存（如 AttemptTracker）
     state: dict = field(default_factory=dict)
-    # 冷却截止时间登记处：reason → time.time()+seconds。唯一写入者是
-    # loop 的 chokepoint（Step 2.2 落地），P1 阶段只写不读，是 P3
-    # 调度器的查询接口。
+    # 冷却截止时间登记处：site 注册名 → 到期时刻（time.time()+seconds）。
+    # 唯一写入者是 loop 的 chokepoint（有 active_site 时才登记）；
+    # 查询者是 daemon_task 的冷却过滤与 queue_router 的 eligible_queues。
     cooldown_until: dict[str, float] = field(default_factory=dict)
+    # 消费者持有的资源集（供 eligible_queues 过滤用）；daemon 消费者
+    # 天然持有 {"channel", "browser"}（与 SPEC §4.2 BrowserConsumer 一致）
+    resources: set[str] = field(default_factory=lambda: {"channel", "browser"})
 
     # ---- 便捷访问 ----
     @property
     def page(self):
         return self.session.page if self.session else None
 
     @property
     def identity(self) -> str:
         return self.session.identity if self.session else "direct"
 
diff --git a/fetcher/tests/test_cooldown.py b/fetcher/tests/test_cooldown.py
index 3e74425..c51db1a 100644
--- a/fetcher/tests/test_cooldown.py
+++ b/fetcher/tests/test_cooldown.py
@@ -200,44 +200,56 @@ class CooldownTestBase(unittest.TestCase):
         policy = Policy(table=table or {}, strategies=strategies or {},
                         max_consecutive_fail=config.max_consecutive_fail)
         loop = CrawlLoop(ctx, task or ScriptedTask(), policy=policy)
         return loop, ctx
 
 
 # ---------- 用例 1：chokepoint 单测 ----------
 
 class CooldownChokepointTest(CooldownTestBase):
     def test_silent_path_writes_deadline_and_returns_false(self):
-        """静默路径（prefix=None → ctx.wait）：写入 cooldown_until[reason]
-        ≈ time.time()+seconds，正常等完返回 False。"""
+        """静默路径（prefix=None → ctx.wait）：无 active_site 时不登记冷却。
+        P3 键语义：cooldown_until 按 site 注册名登记，只有 active_site 设置
+        时才写入；本测试路径无 active_site，cooldown_until 保持空。"""
         loop, ctx = self.make_loop()
-        t0 = time.time()
         interrupted = loop._cooldown(0.05, "ut_silent")
         self.assertFalse(interrupted)
-        # 唯一写入者语义：只写了这一个 reason，值 ≈ 调用时刻 + seconds
-        self.assertEqual(set(ctx.cooldown_until), {"ut_silent"})
-        self.assertAlmostEqual(ctx.cooldown_until["ut_silent"], t0 + 0.05,
-                               delta=1.0)
+        self.assertEqual(ctx.cooldown_until, {})
 
     def test_countdown_path_stop_interrupt_returns_true_fast(self):
         """倒计时路径（prefix 传 → wait_countdown）：等待期间置 stop
-        立即返回 True（远小于 seconds），cooldown_until 同样登记。"""
+        立即返回 True（远小于 seconds）。无 active_site 时不登记冷却。"""
         loop, ctx = self.make_loop()
         threading.Timer(0.1, ctx.stop.set).start()
         t0 = time.monotonic()
         interrupted = loop._cooldown(30.0, "ut_countdown", prefix="倒计时")
         elapsed = time.monotonic() - t0
         self.assertTrue(interrupted)
         self.assertLess(elapsed, 5.0)  # 远小于 30s：确实被 stop 打断
         self.assertGreaterEqual(elapsed, 0.05)  # 非「立即返回」的快路径
-        self.assertAlmostEqual(ctx.cooldown_until["ut_countdown"],
-                               time.time() + 30.0, delta=1.0)
+        self.assertEqual(ctx.cooldown_until, {})
+
+    def test_site_key_when_active_site_set(self):
+        """设 active_site="1688" → 登记 cooldown_until["1688"] 而非 reason。"""
+        loop, ctx = self.make_loop()
+        ctx.state["active_site"] = "1688"
+        t0 = time.time()
+        loop._cooldown(10.0, "sample_interval")
+        self.assertNotIn("sample_interval", ctx.cooldown_until)
+        self.assertEqual(set(ctx.cooldown_until), {"1688"})
+        self.assertAlmostEqual(ctx.cooldown_until["1688"], t0 + 10.0, delta=1.0)
+
+    def test_no_registration_without_active_site(self):
+        """未设 active_site → _cooldown 不登记任何键（仍执行等待）。"""
+        loop, ctx = self.make_loop()
+        loop._cooldown(0.1, "any_reason")
+        self.assertEqual(ctx.cooldown_until, {})
 
 
 # ---------- 用例 2：_process_item 策略冷却集成 ----------
 
 class StrategyCooldownIntegrationTest(CooldownTestBase):
     TABLE = {Scenario.RISK_SLIDER_PAGE: [("cool", 1), ("give_up", None)]}
 
     def test_strategy_cooldown_via_chokepoint_then_retry_success(self):
         """首次 fetch 自报 blocked → 策略输出 cooldown=0.3 → loop 经
         chokepoint 真实等待后重试 fetch → 成功收尾。"""
@@ -255,24 +267,22 @@ class StrategyCooldownIntegrationTest(CooldownTestBase):
         self.assertEqual(task.succeeded, ["item1"])
         self.assertEqual(task.given_up, [])
         # 冷却经 chokepoint：spy 记录 reason=f"strategy:cool"、秒数原样透传
         strat_calls = [c for c in calls if c[1] == "strategy:cool"]
         self.assertEqual(len(strat_calls), 1)
         seconds, _reason, prefix = strat_calls[0]
         self.assertAlmostEqual(seconds, 0.3, delta=1e-6)
         self.assertIsNone(prefix)  # 策略冷却走静默路径
         # 真实等待过（spy 调的是真实实现）
         self.assertGreaterEqual(elapsed, 0.25)
-        # cooldown_until 已登记，值 ≈ 写入时刻 + seconds
-        # （run 结束可能已过截止点，用宽容差而非「在未来」断言）
-        self.assertAlmostEqual(ctx.cooldown_until["strategy:cool"],
-                               time.time() + 0.3, delta=1.0)
+        # 无 active_site，cooldown_until 保持空（P3 site 键语义）
+        self.assertEqual(ctx.cooldown_until, {})
 
     def test_strategy_cooldown_interrupted_by_stop_is_stop_terminal(self):
         """冷却中被 stop 中断 → _process_item return "stop" 终局：
         当前 item 不放弃、后续 item 不再认领，loop 快速退出。"""
         strategy = CooldownStrategy(cooldown=30.0)
         task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1}),
                              ("ok", {"v": 2})], items=("item1", "item2"))
         stop = threading.Event()
         config = make_config(self.tmp)
         ctx = make_ctx(config, self.mgr, stop=stop)
@@ -339,23 +349,27 @@ class WaitPointsTest(CooldownTestBase):
             self.assertLessEqual(seconds, 0.10)
             self.assertIsNone(prefix)
 
         # periodic_rest：rest_every=1 → 每个 item 一次，[rest_min, rest_max]
         self.assertEqual(len(by_reason["periodic_rest"]), 2)
         for seconds, prefix in by_reason["periodic_rest"]:
             self.assertGreaterEqual(seconds, 0.06)
             self.assertLessEqual(seconds, 0.12)
             self.assertEqual(prefix, "长休息")
 
-        # cooldown_until 三类 reason 均登记（唯一写入者语义）
+        # 无 active_site → cooldown_until 保持空（P3 site 键语义）
+        self.assertEqual(ctx.cooldown_until, {})
+        # reason 仍传对（spy 证据）
+        self.assertEqual(set(by_reason), {"batch_rest", "sample_interval",
+                                           "periodic_rest"})
         for reason in ("batch_rest", "sample_interval", "periodic_rest"):
-            self.assertIn(reason, ctx.cooldown_until)
+            self.assertIn(reason, by_reason)
 
     def test_launch_backoff_via_chokepoint(self):
         """启动退避：首次 launch 失败 → _cooldown(backoff, "launch_backoff",
         prefix="启动退避")，backoff=min(30*attempt,120)=30s；stop 中断后
         按 UserInterrupted 路径快速退出（不等满 30s）。"""
         self.mgr = MockBrowserManager(self.page, fail_launch=True)
         stop = threading.Event()
         config = make_config(self.tmp, ip_retry=2)
         ctx = make_ctx(config, self.mgr, stop=stop)
         policy = Policy(table={}, strategies={},
@@ -369,15 +383,16 @@ class WaitPointsTest(CooldownTestBase):
         elapsed = time.monotonic() - t0
 
         self.assertEqual(self.mgr.launch_count, 1)  # 第 1 次失败即进退避
         bo_calls = [c for c in calls if c[1] == "launch_backoff"]
         self.assertEqual(len(bo_calls), 1)
         seconds, _reason, prefix = bo_calls[0]
         self.assertAlmostEqual(seconds, 30.0, delta=1e-6)  # min(30*1, 120)
         self.assertEqual(prefix, "启动退避")
         # 被 stop 中断（UserInterrupted），未等满 30s、未二次 launch
         self.assertLess(elapsed, 5.0)
-        self.assertIn("launch_backoff", ctx.cooldown_until)
+        # 无 active_site（launch_backoff 在 acquire 前）→ 不登记
+        self.assertEqual(ctx.cooldown_until, {})
 
 
 if __name__ == "__main__":
     unittest.main()
diff --git a/fetcher/tests/test_daemon_task.py b/fetcher/tests/test_daemon_task.py
index 7daf876..3c7acd6 100644
--- a/fetcher/tests/test_daemon_task.py
+++ b/fetcher/tests/test_daemon_task.py
@@ -231,20 +231,76 @@ class AcquireItemTest(DaemonTaskTestBase):
         item = self.proxy.acquire_item(ctx)
         elapsed = time.monotonic() - t0
 
         self.assertIsNone(item)
         # 确实阻塞等到了 stop（非「队列空立即返回 None」的快路径）
         self.assertGreaterEqual(elapsed, 0.25)
         # stop 后在注入的小超时量级内醒来返回，不会卡满 30s
         self.assertLess(elapsed, 5.0)
 
 
+class CooldownFilterTest(DaemonTaskTestBase):
+    # 用例 4：冷却中不 claim——注入带冷却的 ctx → acquire 阻塞（等超时
+    # 唤醒路径），不 claim 不 topup
+    def test_cooldown_blocks_claim(self):
+        """冷却中 → acquire_item 不 claim 不 topup，等待冷却到期后才认领。"""
+        self.db.upsert_shops([_shop(1), _shop(2)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+        ctx = self.make_ctx(wid=0)
+        # 设置 0.25s 冷却（短但可观测）
+        ctx.cooldown_until["1688"] = time.time() + 0.25
+
+        result_holder = []
+        t = threading.Thread(target=lambda:
+                             result_holder.append(self.proxy.acquire_item(ctx)),
+                             daemon=True)
+        t.start()
+
+        # 0.1s 后冷却应仍有效：工作项未认领
+        time.sleep(0.10)
+        rows = self.query("SELECT status FROM work_items WHERE queue=?"
+                          " ORDER BY id", (QUEUE,))
+        self.assertEqual([r["status"] for r in rows], ["pending", "pending"])
+
+        # 等待 acquire 完成（冷却到期后自动认领）
+        t.join(timeout=5)
+        self.assertFalse(t.is_alive(), "acquire_item 线程应在冷却到期后完成")
+        self.assertEqual(len(result_holder), 1)
+        self.assertIsNotNone(result_holder[0])
+        self.assertEqual(result_holder[0]["domain"], "shop1.1688.com")
+
+    # 用例 5：冷却到期后恢复认领
+    def test_cooldown_expired_allows_claim(self):
+        """冷却已到期 → acquire_item 正常 claim（不阻塞）。"""
+        self.db.upsert_shops([_shop(1)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 1)
+        ctx = self.make_ctx(wid=0)
+        # 冷却已过期（过去）
+        ctx.cooldown_until["1688"] = time.time() - 1.0
+
+        item = self.proxy.acquire_item(ctx)
+
+        self.assertIsNotNone(item)
+        self.assertEqual(item["domain"], "shop1.1688.com")
+
+    # 用例 6：claim 成功后 active_site 正确写入
+    def test_active_site_set_on_claim(self):
+        """claim 成功后 ctx.state["active_site"] = self._site。"""
+        self.db.upsert_shops([_shop(1)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 1)
+        ctx = self.make_ctx(wid=0)
+
+        self.assertNotIn("active_site", ctx.state)
+        self.proxy.acquire_item(ctx)
+        self.assertEqual(ctx.state.get("active_site"), "1688")
+
+
 class TerminalHookTest(DaemonTaskTestBase):
     # 用例 4：终态钩子——on_success→done / on_giveup→failed，重复 finish 幂等
     def test_terminal_hooks_finish_work_item(self):
         self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
         self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 3)
         ctx0, ctx1 = self.make_ctx(wid=0), self.make_ctx(wid=1)
         result = ActionResult(Outcome.OK, "", {"mobile": "13800138000"})
 
         # on_success：透传 inner 返回值，work_item 落 done
         item_a = self.proxy.acquire_item(ctx0)
diff --git a/fetcher/tests/test_queue_router.py b/fetcher/tests/test_queue_router.py
new file mode 100644
index 0000000..1b5b756
--- /dev/null
+++ b/fetcher/tests/test_queue_router.py
@@ -0,0 +1,140 @@
+# -*- coding: utf-8 -*-
+"""queue_router 单元测试：QueueSpec / eligible_queues / condvar_timeout。
+
+本文件为 P3 Step 1.2 纯函数新增测试（新建文件）。
+"""
+
+import unittest
+
+from fetcher.control.queue_router import QueueSpec, condvar_timeout, eligible_queues
+
+
+# ---------- QueueSpec ----------
+
+class QueueSpecTest(unittest.TestCase):
+    """QueueSpec 数据类基本构造与字段访问。"""
+
+    def test_construction_and_fields(self):
+        qs = QueueSpec(queue="crawl_1688_contact", site="1688",
+                       requires={"channel", "browser"})
+        self.assertEqual(qs.queue, "crawl_1688_contact")
+        self.assertEqual(qs.site, "1688")
+        self.assertEqual(qs.requires, {"channel", "browser"})
+
+
+# ---------- eligible_queues ----------
+
+class EligibleQueuesTest(unittest.TestCase):
+    """eligible_queues 过滤逻辑：资源满足 + 冷却到期。"""
+
+    def _registry(self):
+        return [
+            QueueSpec(queue="crawl_1688_contact", site="1688",
+                      requires={"channel", "browser"}),
+            QueueSpec(queue="crawl_madeinchina", site="madeinchina",
+                      requires={"channel", "browser"}),
+            QueueSpec(queue="crawl_1688_search", site="1688",
+                      requires={"channel"}),
+        ]
+
+    def _ctx(self, resources=None, cooldown_until=None):
+        return type("FakeCtx", (), {
+            "resources": resources or {"channel", "browser"},
+            "cooldown_until": cooldown_until or {},
+        })()
+
+    # ---- 用例 1：冷却过滤 ----
+
+    def test_all_eligible_with_no_cooldown(self):
+        """无冷却时所有队列均可见。"""
+        result = eligible_queues(self._registry(), self._ctx(), 100.0)
+        self.assertEqual(result, ["crawl_1688_contact", "crawl_madeinchina",
+                                  "crawl_1688_search"])
+
+    def test_cooldown_filters_site_queues(self):
+        """site A 冷却中 → 该 site 所有队列被滤；site B 到期 → 保留。"""
+        ctx = self._ctx(cooldown_until={"1688": 200.0})
+        # now=100 < 到期=200 → 1688 冷却中
+        result = eligible_queues(self._registry(), ctx, 100.0)
+        # 1688 两队列被滤，只剩 madeinchina
+        self.assertEqual(result, ["crawl_madeinchina"])
+
+    # ---- 用例 2：资源过滤 ----
+
+    def test_resource_filtering(self):
+        """requires 超 resources 的队列被滤。"""
+        ctx = self._ctx(resources={"channel"})  # 缺 browser
+        result = eligible_queues(self._registry(), ctx, 100.0)
+        # crawl_1688_search 只需 channel → visible
+        self.assertEqual(result, ["crawl_1688_search"])
+
+    # ---- 用例 3：到期恢复 ----
+
+    def test_expiry_recovery(self):
+        """now 推进到冷却到期后 → 队列恢复可见。"""
+        ctx = self._ctx(cooldown_until={"1688": 100.0, "madeinchina": 200.0})
+        # now=100: 1688 到期（now>=100），madeinchina 仍在冷却（now<200）
+        result = eligible_queues(self._registry(), ctx, 100.0)
+        self.assertEqual(result, ["crawl_1688_contact", "crawl_1688_search"])
+
+        # now=200: 全部到期
+        result2 = eligible_queues(self._registry(), ctx, 200.0)
+        self.assertEqual(result2, ["crawl_1688_contact", "crawl_madeinchina",
+                                   "crawl_1688_search"])
+
+    def test_empty_registry(self):
+        """空注册表返回空列表。"""
+        self.assertEqual(eligible_queues([], self._ctx(), 100.0), [])
+
+    def test_empty_resources_still_matches_empty_requires(self):
+        """空 resources 仍可匹配空 requires 的队列。"""
+        registry = [QueueSpec(queue="no_resources", site="x",
+                              requires=set())]
+        ctx = self._ctx(resources=set())
+        result = eligible_queues(registry, ctx, 100.0)
+        self.assertEqual(result, ["no_resources"])
+
+
+# ---------- condvar_timeout ----------
+
+class CondvarTimeoutTest(unittest.TestCase):
+    """condvar_timeout 计算。"""
+
+    # ---- 用例 4：condvar_timeout 计算 ----
+
+    def test_not_in_cooldown_returns_cap(self):
+        """不在冷却中 → 返回 cap（默认 30.0）。"""
+        self.assertEqual(condvar_timeout({}, "1688", 100.0), 30.0)
+        self.assertEqual(condvar_timeout({"other": 200.0}, "1688", 100.0), 30.0)
+
+    def test_in_cooldown_returns_min_of_remaining_and_cap(self):
+        """冷却中 → min(到期 - now, cap)。"""
+        cooldown_until = {"1688": 120.0}
+        # 剩余 20s → min(20, 30)=20
+        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 100.0),
+                               20.0, delta=1e-9)
+        # 剩余 60s → min(60, 30)=30
+        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 60.0),
+                               30.0, delta=1e-9)
+
+    def test_custom_cap(self):
+        """自定义 cap 生效。"""
+        cooldown_until = {"1688": 110.0}  # 剩余 10s → min(10,5)=5
+        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 100.0,
+                                               cap=5.0), 5.0)
+
+    def test_very_small_remaining_returns_positive(self):
+        """剩余极小时返回剩余值（>0），不归零、不转负数。"""
+        cooldown_until = {"1688": 100.01}  # 剩余 0.01s
+        result = condvar_timeout(cooldown_until, "1688", 100.0)
+        self.assertGreater(result, 0.0)
+        self.assertAlmostEqual(result, 0.01, delta=1e-6)
+
+    def test_exactly_at_deadline_returns_cap(self):
+        """now == 到期 → 视为不在冷却，返回 cap。"""
+        cooldown_until = {"1688": 100.0}
+        self.assertEqual(condvar_timeout(cooldown_until, "1688", 100.0), 30.0)
+
+
+if __name__ == "__main__":
+    unittest.main()
