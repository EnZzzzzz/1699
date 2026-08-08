# Review Package — Step 3.2 (SwapIP 两阶段 + release 链路)

## Commits
5c1afe8 feat(multiqueue-p3): SwapIP 两阶段拆分 + 策略冷却让出/release 链路（TDD 18 新用例，438 passed）

## Stat
 fetcher/fetcher/control/loop.py         |  24 +-
 fetcher/fetcher/control/queue_router.py |  17 +
 fetcher/fetcher/control/task.py         |   7 +
 fetcher/fetcher/strategy/strategies.py  |  60 ++-
 fetcher/tests/test_cooldown.py          |  43 +-
 fetcher/tests/test_swapip_two_phase.py  | 780 ++++++++++++++++++++++++++++++++
 6 files changed, 888 insertions(+), 43 deletions(-)

## Diff
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index 977b972..4902728 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -209,20 +209,27 @@ class CrawlLoop:
 
                 # ---- 冷启动（acquire 后的任务，如先逛店铺首页）----
                 if self._take_warm():
                     self.ctx.set_status(state="冷启动软着陆…")
                     self.task.cold_start(self.ctx, item)
 
                 # ---- item 级重试循环（策略表驱动）----
                 kind, count = self._process_item(item)
                 if kind in ("abort", "stop"):
                     return self.stats
+                if kind == "release":
+                    # 策略冷却让出：释放 item 回 pending（attempts 熔断），
+                    # 冷却到期重领时策略链从头开始（SPEC §3.4）
+                    self.task.release_item(self.ctx)
+                    self.task.after_item(self.ctx, item)
+                    # stop 由下一轮 acquire 的 condvar 检查处理
+                    continue
                 self.done_in_batch += count
                 self.total_done += count
                 if kind == "success":
                     # 每次成功后回写最新 Cookie（含轮换的 x5sec）——
                     # 进程意外退出也不丢信任链
                     try:
                         self.ctx.browser_manager.save_cookies(self.ctx.session)
                     except Exception:  # noqa: BLE001
                         pass
 
@@ -435,28 +442,29 @@ class CrawlLoop:
             # ---- 执行策略后重试同一任务项 ----
             strategy = self.policy.strategies[decision.strategy]
             ctx.state["attempt"] = decision.attempt
             ctx.set_status(state=f"处置: {decision.strategy}"
                                  f"（{decision.attempt} 次）")
             self.log(f"⚠ {reason} → 策略 {decision.strategy}"
                      f"（第 {decision.attempt} 次）")
             step = strategy.run(ctx)
             if step.solved:
                 self.log(f"✓ 策略 {decision.strategy} 完成: {step.detail}")
-            # 策略冷却经 chokepoint 执行（Step 2.1 起策略只算时长不自
-            # 等）；被 stop 中断按现状 stop 路径退出（与旧策略内
-            # ctx.wait 中断 → 循环条件退出 → return "stop" 的终局一致）
-            # item 未完成路径暂保留原地等待（默认）；
-            # P3-3 router 接 release 后改让出
-            if step.cooldown and self._cooldown(
-                    step.cooldown, f"strategy:{decision.strategy}"):
-                return "stop", 0
+            # 策略冷却统一让出 + release（P3 SPEC §3.4）：冷却期间该
+            # 站点队列不可见，item 释放回 pending（attempts 熔断），
+            # 冷却到期重领（策略链从头开始）
+            if step.cooldown:
+                if self._cooldown(step.cooldown,
+                                  f"strategy:{decision.strategy}",
+                                  yield_=True):
+                    return "stop", 0
+                return "release", 0
         return "stop", 0
 
     def _bind_item_site(self):
         """daemon 多站点路径：按 ctx.state["active_site"] 切换
         ctx.site / inspector / policy。CLI 路径（sites=None）无操作。"""
         if self.sites is None:
             return
         site_name = self.ctx.state.get("active_site")
         if site_name is None or site_name == self._bound_site:
             return
diff --git a/fetcher/fetcher/control/queue_router.py b/fetcher/fetcher/control/queue_router.py
index 5c2cfc7..5b944e6 100644
--- a/fetcher/fetcher/control/queue_router.py
+++ b/fetcher/fetcher/control/queue_router.py
@@ -270,19 +270,36 @@ class QueueRouter:
     def on_success(self, ctx, item, result) -> int:
         count = self._task_for(ctx).on_success(ctx, item, result)
         self._finish(ctx, "done")
         return count
 
     def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
         phrase = self._task_for(ctx).on_giveup(ctx, item, reason, kind)
         self._finish(ctx, "failed", result={"reason": reason, "kind": kind})
         return phrase
 
+    def release_item(self, ctx) -> str:
+        """当前 worker 的 item 释放回 pending（attempts+1，耗尽置 failed）。
+
+        返回终态（"pending"/"failed"）供日志；无认领记录时返回 ""。
+        """
+        item_id = ctx.state.pop(_STATE_KEY, None)
+        if item_id is None:
+            return ""
+        try:
+            status = self._db(ctx).release_work_item(item_id, max_attempts=3)
+            if status == "failed":
+                ctx.log(f"[!] 工作项 #{item_id} attempts exhausted，已置 failed")
+            return status
+        except Exception as e:  # noqa: BLE001
+            ctx.log(f"[!] 工作项 #{item_id} 释放失败: {e}")
+            return ""
+
     def _finish(self, ctx, status: str, result: dict | None = None):
         """把当前 worker 认领的 work_item 落终态（done/failed）。"""
         item_id = ctx.state.pop(_STATE_KEY, None)
         if item_id is None:
             return
         try:
             self._db(ctx).finish_work_item(item_id, status, result)
         except Exception as e:  # noqa: BLE001
             ctx.log(f"[!] 工作项 #{item_id} 落终态 {status} 失败: {e}")
diff --git a/fetcher/fetcher/control/task.py b/fetcher/fetcher/control/task.py
index 7e2cf05..67ef3cd 100644
--- a/fetcher/fetcher/control/task.py
+++ b/fetcher/fetcher/control/task.py
@@ -115,12 +115,19 @@ class Task:
         return "跳过"
 
     def on_abort(self, ctx, item) -> str:
         """连续失败触发整体中止时的一行补充说明。"""
         return ""
 
     def giveup_cost(self, item) -> int:
         """放弃的任务项计入批次配额的数量。"""
         return 0
 
+    def release_item(self, ctx) -> str:
+        """当前 worker 的 item 释放回 pending（CLI 路径默认空实现）。
+
+        daemon 多队列路径由 QueueRouter 覆盖为 DB release_work_item。
+        """
+        return ""
+
     def after_item(self, ctx, item) -> None:
         """当前任务项处理完毕（含放弃）后的收尾（如释放类目占用）。"""
diff --git a/fetcher/fetcher/strategy/strategies.py b/fetcher/fetcher/strategy/strategies.py
index 557a52d..a6ed9e2 100644
--- a/fetcher/fetcher/strategy/strategies.py
+++ b/fetcher/fetcher/strategy/strategies.py
@@ -109,69 +109,95 @@ class SolveSliderStrategy(_AtomStrategy):
 
 class RelaunchBrowserStrategy(_AtomStrategy):
     """重启浏览器（浏览器死亡修复 / IP 轮换重绑）。"""
     name = "relaunch_browser"
     atom_cls = RelaunchBrowser
 
 
 class SwapIPStrategy:
     """换 IP：重启浏览器绑定新出口 IP（通道不变，靠出口轮换/重连）。
 
-    冷却例外：内部等待夹在两次 relaunch 之间，保持原地等待（P3-3 router 接 release 后改让出）。
+    P3 已拆无头两阶段；有头 WaitHumanLogin 例外保留原地（人工辅助场景）。
 
     迁移旧引擎 block_stage==1 的完整逻辑：
         1. 重启浏览器（旧 Cookie 先回写）；
-        2. 出口尚未轮换（青果 30 分钟时效，identity 没变）：休息一轮
-           等其过期（有头模式期间可人工登录，登录成功立即算解决），
-           再重启一次绑定新 IP；
+        2. 出口尚未轮换（青果 30 分钟时效，identity 没变）：
+           有头 → WaitHumanLogin 轮询人工登录（需活 page，不拆分），
+                 登录成功即可，否则第二次 relaunch；
+           无头 → P3 两阶段：回写 Cookie → 关闭本站 context →
+                 登记 needs_relaunch → 输出让出型冷却，冷却到期
+                 重领时由 ensure_site 懒建路径消费 needs_relaunch
+                 （完整 relaunch），不再显式执行第二次 relaunch。
         3. 两步都成功即 solved（是否真换到 IP 由 data["rotated"] 标注）。
     """
 
     name = "swap_ip"
 
     def __init__(self, **params):
         self._params = params
 
     def run(self, ctx) -> StepResult:
         if ctx.browser_manager is None or ctx.session is None:
             return StepResult(False, "未装配 browser_manager / session")
         old_identity = ctx.session.identity
         result = RelaunchBrowser().run(ctx, self._params)
         if result.outcome is Outcome.SKIPPED:
             return StepResult(False, "用户中断")
         if result.outcome is not Outcome.OK:
             return StepResult(False, result.detail, result.data)
         if result.data.get("rotated") or not ctx.config.use_proxy:
             return StepResult(True, result.detail, result.data)
 
-        # 出口还没轮换（休息不足 30 分钟）：再等一轮让青果轮换
+        # 出口还没轮换（休息不足 30 分钟）
         rest = random.uniform(ctx.config.block_rest_min,
                               ctx.config.block_rest_max)
-        ctx.log(f"    [!] 出口 IP 尚未轮换（青果 30 分钟时效），"
-                f"再休息 {rest / 60:.1f} 分钟等其过期后重试")
         if ctx.headed:
-            # 有头模式：等轮换期间轮询用户是否手动登录（Cookie 增量检测），
-            # 登录成功立即继续，不必等轮换
+            # P3 已拆无头两阶段；有头 WaitHumanLogin 例外保留原地（人工辅助场景）
+            ctx.log(f"    [!] 出口 IP 尚未轮换（青果 30 分钟时效），"
+                    f"再休息 {rest / 60:.1f} 分钟等其过期后重试")
             login = WaitHumanLogin().run(ctx, {"seconds": rest})
             if login.outcome is Outcome.OK:
                 SaveCookies().run(ctx, {})
                 return StepResult(True, f"等轮换期间手动登录成功: {login.detail}")
             if login.outcome is Outcome.SKIPPED:
                 return StepResult(False, "用户中断")
-        elif ctx.wait(rest):
-            return StepResult(False, "用户中断")
-        result2 = RelaunchBrowser().run(ctx, self._params)
-        if result2.outcome is Outcome.OK:
-            return StepResult(True, result2.detail, result2.data)
-        if result2.outcome is Outcome.SKIPPED:
-            return StepResult(False, "用户中断")
-        return StepResult(False, result2.detail, result2.data)
+            # WaitHumanLogin 非 OK 非 SKIPPED → 落回第二次 relaunch（有头保留原地逻辑）
+            result2 = RelaunchBrowser().run(ctx, self._params)
+            if result2.outcome is Outcome.OK:
+                return StepResult(True, result2.detail, result2.data)
+            if result2.outcome is Outcome.SKIPPED:
+                return StepResult(False, "用户中断")
+            return StepResult(False, result2.detail, result2.data)
+
+        # 无头两阶段（P3）：回写 Cookie → 关闭本站 context →
+        # 登记 needs_relaunch → 输出让出型冷却；冷却到期重领时由
+        # ensure_site 懒建路径消费 needs_relaunch（完整 relaunch）
+        site = ctx.state.get("active_site")
+        ctx.log(f"    [!] 出口 IP 尚未轮换（青果 30 分钟时效），"
+                f"登记 needs_relaunch[{site}]，让出冷却 {rest / 60:.1f} 分钟，"
+                f"冷却到期重领时走完整 relaunch")
+        # 回写本站 Cookie
+        try:
+            SaveCookies().run(ctx, {})
+        except Exception:  # noqa: BLE001
+            pass
+        # 关闭本站 context（浏览器进程保留，其他 site view 不受影响）
+        if site:
+            try:
+                ctx.session.close_site(site, store=ctx.store, log=ctx.log)
+            except Exception:  # noqa: BLE001
+                pass
+            try:
+                ctx.browser_manager.mark_needs_relaunch(ctx.session, site)
+            except Exception:  # noqa: BLE001
+                pass
+        return StepResult(False, f"未轮换，已登记两阶段", cooldown=rest)
 
 
 class WaitHumanVerifyStrategy(_AtomStrategy):
     name = "wait_human_verify"
     atom_cls = WaitHumanVerify
 
 
 class WaitHumanLoginStrategy(_AtomStrategy):
     name = "wait_human_login"
     atom_cls = WaitHumanLogin
diff --git a/fetcher/tests/test_cooldown.py b/fetcher/tests/test_cooldown.py
index fc50fc6..e41e8a6 100644
--- a/fetcher/tests/test_cooldown.py
+++ b/fetcher/tests/test_cooldown.py
@@ -258,79 +258,86 @@ class CooldownChokepointTest(CooldownTestBase):
         loop._cooldown(0.1, "any_reason")
         self.assertEqual(ctx.cooldown_until, {})
 
 
 # ---------- 用例 2：_process_item 策略冷却集成 ----------
 
 class StrategyCooldownIntegrationTest(CooldownTestBase):
     TABLE = {Scenario.RISK_SLIDER_PAGE: [("cool", 1), ("give_up", None)]}
 
     def test_strategy_cooldown_via_chokepoint_then_retry_success(self):
-        """首次 fetch 自报 blocked → 策略输出 cooldown=0.3 → loop 经
-        chokepoint 真实等待后重试 fetch → 成功收尾。
-        同时验证策略冷却保持 yield_=False（原地型，P3-3 改让出）。"""
+        """首次 fetch 自报 blocked → 策略输出 cooldown=0.3 → P3 策略冷却
+        统一让出 + release（yield_=True）：登记冷却后立即返回，item 释放
+        回 pending 然后循环退出（单 item 无更多任务）。"""
         strategy = CooldownStrategy(cooldown=0.3, solved=True)
         task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1})])
         loop, ctx = self.make_loop(task, self.TABLE, {"cool": strategy})
         calls = spy_cooldown_full(loop)
 
         t0 = time.monotonic()
         loop.run()
         elapsed = time.monotonic() - t0
 
-        # 重试发生且终态正确
-        self.assertEqual(task.fetches, 2)
-        self.assertEqual(task.succeeded, ["item1"])
+        # P3：策略冷却 → release（不再 wait + retry）
+        self.assertEqual(task.fetches, 1)
+        self.assertEqual(task.succeeded, [])
         self.assertEqual(task.given_up, [])
         # 冷却经 chokepoint：spy 记录 reason=f"strategy:cool"、秒数原样透传
         strat_calls = [c for c in calls if c[1] == "strategy:cool"]
         self.assertEqual(len(strat_calls), 1)
         seconds, _reason, prefix, yield_ = strat_calls[0]
         self.assertAlmostEqual(seconds, 0.3, delta=1e-6)
         self.assertIsNone(prefix)  # 策略冷却走静默路径
-        self.assertFalse(yield_, "策略冷却应保持 yield_=False（原地型）")
-        # 真实等待过（spy 调的是真实实现）
-        self.assertGreaterEqual(elapsed, 0.25)
+        self.assertTrue(yield_, "P3 策略冷却已改为 yield_=True（让出型）")
+        # 让出型不等待（立即返回）
+        self.assertLess(elapsed, 0.2)
         # 无 active_site，cooldown_until 保持空（P3 site 键语义）
         self.assertEqual(ctx.cooldown_until, {})
 
     def test_strategy_cooldown_interrupted_by_stop_is_stop_terminal(self):
-        """冷却中被 stop 中断 → _process_item return "stop" 终局：
-        当前 item 不放弃、后续 item 不再认领，loop 快速退出。
-        同时验证策略冷却保持 yield_=False。"""
+        """P3 策略冷却让出 + release：stop 由下一轮 acquire 处理。
+        设 active_site 后 cooldown 登记冷却，stop 置位后 while 循环退出。
+        当前 item 不放弃、后续 item 不再认领，loop 快速退出。"""
         strategy = CooldownStrategy(cooldown=30.0)
-        task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1}),
-                             ("ok", {"v": 2})], items=("item1", "item2"))
+        # 在 fetch 中设 stop：第一次 fetch 后 stop 置位，
+        # release+continue 后 while 循环立即捕获
+        class StopAfterFetch(ScriptedTask):
+            def fetch(self, ctx, item):
+                result = super().fetch(ctx, item)
+                ctx.stop.set()
+                return result
+        task = StopAfterFetch([("blocked", "滑块拦截"), ("ok", {"v": 1}),
+                               ("ok", {"v": 2})], items=("item1", "item2"))
         stop = threading.Event()
         config = make_config(self.tmp)
         ctx = make_ctx(config, self.mgr, stop=stop)
+        ctx.state["active_site"] = "1688"
         policy = Policy(table=self.TABLE, strategies={"cool": strategy},
                         max_consecutive_fail=config.max_consecutive_fail)
         loop = CrawlLoop(ctx, task, policy=policy)
         calls = spy_cooldown_full(loop)
 
-        threading.Timer(0.15, stop.set).start()
         t0 = time.monotonic()
         loop.run()
         elapsed = time.monotonic() - t0
 
-        # 被 stop 打断而非等满 30s
-        self.assertLess(elapsed, 5.0)
+        # stop 快速捕获（不等待 30s）
+        self.assertLess(elapsed, 0.3)
         self.assertTrue(stop.is_set())
         # "stop" 终局：item1 未成功也未放弃，item2 未被认领（fetch 只 1 次）
         self.assertEqual(task.fetches, 1)
         self.assertEqual(task.succeeded, [])
         self.assertEqual(task.given_up, [])
         strat_calls = [c for c in calls if c[1] == "strategy:cool"]
         self.assertEqual(len(strat_calls), 1)
         self.assertAlmostEqual(strat_calls[0][0], 30.0, delta=1e-6)
-        self.assertFalse(strat_calls[0][3], "策略冷却应保持 yield_=False")
+        self.assertTrue(strat_calls[0][3], "P3 策略冷却已改为 yield_=True（让出型）")
 
 
 # ---------- 用例 3：4 处等待点触发 ----------
 
 # ---------- 用例 1.5：yield_ 让出型 / 原地型语义 ----------
 
 class YieldCooldownTest(CooldownTestBase):
     def test_yield_returns_false_immediately(self):
         """yield_=True → 登记 site 键后立即返回 False，不等待（≠ ctx.wait）。"""
         loop, ctx = self.make_loop()
diff --git a/fetcher/tests/test_swapip_two_phase.py b/fetcher/tests/test_swapip_two_phase.py
new file mode 100644
index 0000000..9d68763
--- /dev/null
+++ b/fetcher/tests/test_swapip_two_phase.py
@@ -0,0 +1,780 @@
+# -*- coding: utf-8 -*-
+"""Task 3.2: SwapIP 两阶段拆分 + 策略冷却让出/release 链路 TDD 测试。
+
+覆盖：
+  1. SwapIP 无头未轮换两阶段（close_site + mark_needs_relaunch + cooldown）
+  2. SwapIP 轮换成功回归（solved，无 cooldown）
+  3. SwapIP 有头例外保留原地（不置 needs_relaunch）
+  4. 策略冷却 release 全链路（loop 集成：cooldown → release → 重领 → 熔断）
+  5. release 后冷却过滤（eligible_queues 过滤）
+  6. attempts 熔断（max_attempts=3）
+  7. Task 基类 release_item 默认空实现
+  8. release 路径 stop 语义
+"""
+
+import json
+import sqlite3
+import tempfile
+import threading
+import time
+import unittest
+from pathlib import Path
+from unittest.mock import ANY, MagicMock, patch
+
+from fetcher import (
+    Alibaba1688Plugin,
+    IdentityStore,
+    RunConfig,
+    ShopDB,
+    Session,
+    WorkerContext,
+)
+from fetcher.atoms.browser_ops import RelaunchBrowser
+from fetcher.atoms.human import WaitHumanLogin
+from fetcher.control import CrawlLoop, Task
+from fetcher.control.queue_router import (
+    QueueRouter,
+    QueueSpec,
+    _STATE_KEY,
+    _WAIT_TIMEOUT,
+    eligible_queues,
+)
+from fetcher.core.session import SiteView
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.strategy.base import StepResult
+from fetcher.strategy.policy import Policy, Scenario, PolicyAction
+from fetcher.strategy.strategies import SwapIPStrategy, BlockRestStrategy
+
+
+# ============================================================
+# 1. SwapIP 无头两阶段测试
+# ============================================================
+
+class FakeBrowser:
+    def is_connected(self):
+        return True
+    def close(self):
+        pass
+
+
+class FakeContext:
+    def __init__(self):
+        self.browser = FakeBrowser()
+    def cookies(self):
+        return []
+
+
+class FakePage:
+    def __init__(self):
+        self.url = "https://shop123.1688.com/page/contactinfo.htm"
+        self._text = "正常页面文本，足够长"
+        self.frames = []
+        self.context = FakeContext()
+    def evaluate(self, js):
+        return self._text
+    def query_selector(self, sel):
+        return None
+    def is_closed(self):
+        return False
+
+
+class SwapIPTwoPhaseTestBase(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = Path(self._tmp.name) / "t.db"
+
+    def tearDown(self):
+        self._tmp.cleanup()
+
+    def _make_ctx(self, headed=False, use_proxy=True, wid=0, site_name="1688"):
+        config = RunConfig(
+            db_path=str(self.db_path), headless=not headed,
+            use_proxy=use_proxy, block_rest_min=0.01, block_rest_max=0.02,
+            ip_retry=1, max_consecutive_fail=3)
+        stop = threading.Event()
+        store = IdentityStore(ShopDB(self.db_path))
+        ctx = WorkerContext(
+            config=config, store=store,
+            browser_manager=MagicMock(),
+            site=Alibaba1688Plugin(), stop=stop,
+            log=lambda m: None, wid=wid)
+        ctx.state["active_site"] = site_name
+        return ctx
+
+
+class SwapIPHeadlessTwoPhaseTest(SwapIPTwoPhaseTestBase):
+    """SwapIP 无头未轮换 → 两阶段拆分。"""
+
+    def test_not_rotated_headless_triggers_two_phase(self):
+        """RelaunchBrowser rotated=False + 无头 → close_site + mark_needs_relaunch
+        + 返回 cooldown，不执行第二次 relaunch。"""
+        ctx = self._make_ctx(headed=False)
+        mgr = ctx.browser_manager
+        session = MagicMock()
+        session.identity = "1688:1.1.1.1"
+        ctx.session = session
+        # session.views 包含 1688 site view
+        view = MagicMock()
+        session.views = {"1688": view}
+
+        strategy = SwapIPStrategy()
+
+        # Mock RelaunchBrowser.run 返回 rotated=False
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            mock_relaunch.return_value = ActionResult.success(
+                "ok", identity="1688:1.1.1.1", rotated=False)
+            # Mock SaveCookies.run
+            with patch('fetcher.strategy.strategies.SaveCookies') as mock_save:
+                mock_save_instance = MagicMock()
+                mock_save.return_value = mock_save_instance
+                mock_save_instance.run.return_value = ActionResult.success(
+                    "已回写 3 个 Cookie", count=3)
+
+                result = strategy.run(ctx)
+
+        # 断言
+        self.assertFalse(result.solved)
+        self.assertIsNotNone(result.cooldown)
+        self.assertGreater(result.cooldown, 0)
+        self.assertIn("两阶段", result.detail)
+        # RelaunchBrowser 只调了一次
+        self.assertEqual(mock_relaunch.call_count, 1)
+        # close_site 被调（on session）
+        session.close_site.assert_called_once_with(
+            "1688", store=ctx.store, log=ctx.log)
+        # mark_needs_relaunch 被调
+        mgr.mark_needs_relaunch.assert_called_once_with(session, "1688")
+        # SaveCookies 被调
+        mock_save_instance.run.assert_called_once()
+        # 没有第二次 RelaunchBrowser（mock_relaunch call_count = 1）
+
+    def test_rotated_headless_solves_no_cooldown(self):
+        """RelaunchBrowser rotated=True → solved，无 cooldown。"""
+        ctx = self._make_ctx(headed=False)
+        session = MagicMock()
+        session.identity = "1688:1.1.1.1"
+        ctx.session = session
+
+        strategy = SwapIPStrategy()
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            mock_relaunch.return_value = ActionResult.success(
+                "ok", identity="1688:2.2.2.2", rotated=True)
+            result = strategy.run(ctx)
+
+        self.assertTrue(result.solved)
+        self.assertIsNone(result.cooldown)
+        self.assertEqual(mock_relaunch.call_count, 1)
+
+    def test_use_proxy_false_solves_no_cooldown(self):
+        """use_proxy=False → 视为已轮换（直连不需轮换），直接 solved。"""
+        ctx = self._make_ctx(headed=False, use_proxy=False)
+        session = MagicMock()
+        session.identity = "1688:direct"
+        ctx.session = session
+
+        strategy = SwapIPStrategy()
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            mock_relaunch.return_value = ActionResult.success(
+                "ok", identity="1688:direct", rotated=False)
+            result = strategy.run(ctx)
+
+        self.assertTrue(result.solved)
+        self.assertIsNone(result.cooldown)
+
+    def test_no_browser_manager_returns_error(self):
+        """无 browser_manager / session → 返回错误。"""
+        ctx = self._make_ctx()
+        ctx.browser_manager = None
+        ctx.session = None
+        strategy = SwapIPStrategy()
+        result = strategy.run(ctx)
+        self.assertFalse(result.solved)
+        self.assertIn("未装配", result.detail)
+
+    def test_relaunch_skipped_returns_interrupted(self):
+        """RelaunchBrowser 返回 SKIPPED → 用户中断。"""
+        ctx = self._make_ctx(headed=False)
+        session = MagicMock()
+        session.identity = "1688:1.1.1.1"
+        ctx.session = session
+
+        strategy = SwapIPStrategy()
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            mock_relaunch.return_value = ActionResult.skipped("用户中断")
+            result = strategy.run(ctx)
+
+        self.assertFalse(result.solved)
+        self.assertIn("用户中断", result.detail)
+
+    def test_relaunch_failed_returns_error(self):
+        """RelaunchBrowser 返回 FATAL → 传播错误。"""
+        ctx = self._make_ctx(headed=False)
+        session = MagicMock()
+        session.identity = "1688:1.1.1.1"
+        ctx.session = session
+
+        strategy = SwapIPStrategy()
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            mock_relaunch.return_value = ActionResult.fatal("重启失败")
+            result = strategy.run(ctx)
+
+        self.assertFalse(result.solved)
+        self.assertIn("重启失败", result.detail)
+
+
+class SwapIPHeadedExceptionTest(SwapIPTwoPhaseTestBase):
+    """SwapIP 有头例外保留：WaitHumanLogin + 第二次 relaunch 原地等待。"""
+
+    def test_headed_preserves_wait_human_login_path(self):
+        """有头 + 未轮换 → WaitHumanLogin 被调用（不触发两阶段拆分）。"""
+        ctx = self._make_ctx(headed=True)
+        session = MagicMock()
+        session.identity = "1688:1.1.1.1"
+        ctx.session = session
+
+        strategy = SwapIPStrategy()
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            # 第一次 relaunch 返回 rotated=False
+            mock_relaunch.return_value = ActionResult.success(
+                "ok", identity="1688:1.1.1.1", rotated=False)
+            with patch.object(WaitHumanLogin, 'run') as mock_login:
+                # WaitHumanLogin 返回 OK（登录成功）
+                mock_login.return_value = ActionResult.success("检测到登录态 Cookie")
+                with patch('fetcher.strategy.strategies.SaveCookies') as mock_save:
+                    mock_save_instance = MagicMock()
+                    mock_save.return_value = mock_save_instance
+                    mock_save_instance.run.return_value = ActionResult.success(
+                        "已回写", count=3)
+
+                    result = strategy.run(ctx)
+
+        self.assertTrue(result.solved)  # 登录成功 → solved
+        self.assertIn("手动登录成功", result.detail)
+        mock_login.assert_called_once()
+        # 没有触发 relaunch 两次（第一次被 mock 了，第二次不会到）
+        # 第一次 relaunch = 1
+        self.assertEqual(mock_relaunch.call_count, 1)
+
+    def test_headed_login_skipped_returns_interrupted(self):
+        """有头 + WaitHumanLogin SKIPPED → 用户中断。"""
+        ctx = self._make_ctx(headed=True)
+        session = MagicMock()
+        session.identity = "1688:1.1.1.1"
+        ctx.session = session
+
+        strategy = SwapIPStrategy()
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            mock_relaunch.return_value = ActionResult.success(
+                "ok", identity="1688:1.1.1.1", rotated=False)
+            with patch.object(WaitHumanLogin, 'run') as mock_login:
+                mock_login.return_value = ActionResult.skipped("用户中断")
+
+                result = strategy.run(ctx)
+
+        self.assertFalse(result.solved)
+        self.assertIn("用户中断", result.detail)
+        mock_login.assert_called_once()
+
+    def test_headed_login_timeout_falls_through_to_second_relaunch(self):
+        """有头 + WaitHumanLogin 超时（BLOCKED）→ 执行第二次 relaunch。"""
+        ctx = self._make_ctx(headed=True)
+        session = MagicMock()
+        session.identity = "1688:1.1.1.1"
+        ctx.session = session
+
+        strategy = SwapIPStrategy()
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            # 第一次 relaunch → not rotated
+            # 第二次 relaunch → rotated (success)
+            mock_relaunch.side_effect = [
+                ActionResult.success("ok", identity="1688:1.1.1.1", rotated=False),
+                ActionResult.success("ok", identity="1688:2.2.2.2", rotated=True),
+            ]
+            with patch.object(WaitHumanLogin, 'run') as mock_login:
+                # 超时（既不是 OK 也不是 SKIPPED）
+                mock_login.return_value = ActionResult.blocked("等待超时未检测到登录")
+
+                result = strategy.run(ctx)
+
+        # 第二次 relaunch 成功
+        self.assertTrue(result.solved)
+        self.assertEqual(mock_relaunch.call_count, 2)
+        mock_login.assert_called_once()
+        # 没有触发两阶段（cooldown 为 None，solved = True）
+        self.assertIsNone(result.cooldown)
+
+
+# ============================================================
+# 4. 策略冷却 release 全链路（loop 集成）
+# ============================================================
+
+class FakeBrowser:
+    def is_connected(self):
+        return True
+    def close(self):
+        pass
+
+
+class FakeContext:
+    def __init__(self):
+        self.browser = FakeBrowser()
+    def cookies(self):
+        return []
+
+
+class FakePage:
+    def __init__(self, url="https://shop1.1688.com/page/contactinfo.htm"):
+        self.url = url
+        self._text = "正常页面文本，足够长，包含电话、手机、地址等字段标签，超过阈值。"
+        self.frames = []
+        self.context = FakeContext()
+    def evaluate(self, js):
+        return self._text
+    def query_selector(self, sel):
+        return None
+    def is_closed(self):
+        return False
+
+
+class MockBrowserManager:
+    def __init__(self, page, identity="1688:1.1.1.1"):
+        self.page = page
+        self.identity = identity
+        self.needs_relaunch_calls = []
+
+    def launch(self, seed_kit=None, stop=None):
+        return Session(browser=FakeBrowser(), page=self.page,
+                       identity=self.identity, seed_kit=seed_kit)
+
+    def check_ip_fresh(self, session):
+        return False, session.identity, ""
+
+    def save_cookies(self, session):
+        return 0
+
+    def close_site(self, *args, **kwargs):
+        pass
+
+    def mark_needs_relaunch(self, session, site):
+        self.needs_relaunch_calls.append(site)
+
+
+class ScriptedTask(Task):
+    """可编程任务：fetch 按 script 逐条出账。"""
+
+    name = "scripted"
+    giveup_cost_value = 1
+
+    def __init__(self, script, items=("item1",), validate_ok=True):
+        self.script = list(script)
+        self.items = list(items)
+        self.fetches = 0
+        self.succeeded = []
+        self.given_up = []
+        self.aborted = []
+        self.released = []
+        self._validate_ok = validate_ok
+
+    def acquire_item(self, ctx):
+        return self.items.pop(0) if self.items else None
+
+    def fetch(self, ctx, item):
+        self.fetches += 1
+        step = self.script.pop(0) if self.script else ("ok", {"v": 1})
+        kind = step[0]
+        if kind == "ok":
+            return ActionResult(Outcome.OK, "", step[1] if len(step) > 1 else {})
+        if kind == "net":
+            ctx.last_error = Exception(step[1])
+            return ActionResult.net_error(step[1])
+        if kind == "page":
+            ctx.page.url = step[1]
+            ctx.page._text = step[2]
+            return ActionResult(Outcome.OK, "", step[3] if len(step) > 3 else {})
+        if kind == "blocked":
+            return ActionResult.blocked(step[1])
+        if kind == "none":
+            return None
+        raise ValueError(kind)
+
+    def validate(self, ctx, item, result):
+        return self._validate_ok
+
+    def on_success(self, ctx, item, result):
+        self.succeeded.append(item)
+        return 1
+
+    def on_giveup(self, ctx, item, reason, kind):
+        self.given_up.append((item, kind))
+        return "标记跳过"
+
+    def on_abort(self, ctx, item):
+        self.aborted.append(item)
+        return "补充说明"
+
+    def giveup_cost(self, item):
+        return self.giveup_cost_value
+
+    def make_stats(self):
+        return {"done": 0}
+
+    def release_item(self, ctx):
+        self.released.append(ctx.state.get("daemon_work_item_id"))
+        return "pending"
+
+
+class FakeReleaseStrategy:
+    """返回 cooldown 的假策略（模拟 block_rest 的让出语义）。"""
+
+    name = "fake_release"
+    calls = 0
+
+    def __init__(self, solved=True, cooldown=0.1):
+        self._solved = solved
+        self._cooldown = cooldown
+
+    def run(self, ctx):
+        self.calls += 1
+        return StepResult(self._solved, f"fake#{self.calls}",
+                          cooldown=self._cooldown)
+
+
+def make_config(tmp, **kw):
+    base = dict(headless=True, use_proxy=False, batch_num=1, max_batches=1,
+                sample_min=0, sample_max=0, rest_every=0, batch_rest=0.01,
+                block_rest_min=0.01, block_rest_max=0.02, ip_retry=1,
+                max_consecutive_fail=3,
+                db_path=str(Path(tmp) / "t.db"))
+    base.update(kw)
+    return RunConfig(**base)
+
+
+def make_ctx(tmp, page, mgr, config):
+    store = IdentityStore(ShopDB(config.resolved_db_path()))
+    return WorkerContext(config=config, store=store, browser_manager=mgr,
+                         site=Alibaba1688Plugin(), stop=threading.Event(),
+                         log=lambda m: None)
+
+
+class StrategyCooldownReleaseTest(unittest.TestCase):
+    """策略冷却 → release 全链路集成测试（loop + router）。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.tmp = self._tmp.name
+        self.db_path = Path(self.tmp) / "t.db"
+        self.page = FakePage()
+
+    def tearDown(self):
+        self._tmp.cleanup()
+
+    def db_query(self, sql, args=()):
+        conn = sqlite3.connect(str(self.db_path))
+        conn.row_factory = sqlite3.Row
+        try:
+            return conn.execute(sql, args).fetchall()
+        finally:
+            conn.close()
+
+    def test_strategy_cooldown_triggers_release_via_loop(self):
+        """策略返回 cooldown → loop 返回 "release" → task.release_item 被调。"""
+        release_strat = FakeReleaseStrategy(solved=True, cooldown=0.05)
+        task = ScriptedTask(
+            [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {})])
+        table = {Scenario.RISK_SLIDER_PAGE: [("fake_release", 2),
+                                              ("give_up", None)]}
+
+        config = make_config(self.tmp)
+        ctx = make_ctx(self.tmp, self.page,
+                       MockBrowserManager(self.page), config)
+        policy = Policy(table=table,
+                        strategies={"fake_release": release_strat},
+                        max_consecutive_fail=config.max_consecutive_fail)
+        loop = CrawlLoop(ctx, task, policy=policy)
+        stats = loop.run()
+
+        # 策略被调用，然后触发 release
+        self.assertEqual(release_strat.calls, 1)
+        self.assertGreater(len(task.released), 0,
+                           "策略冷却应触发 release_item")
+        # item 未被 mark success（释放了）
+        self.assertEqual(task.succeeded, [])
+        # item 未被 giveup
+        self.assertEqual(task.given_up, [])
+        # 循环正常退出（stop 未置位，无更多 item）
+        self.assertFalse(ctx.stop.is_set())
+
+    def test_release_with_stop_exits_cleanly(self):
+        """stop 置位后 release 路径退出干净。"""
+        release_strat = FakeReleaseStrategy(solved=True, cooldown=0.05)
+
+        class StopOnSecondFetch(ScriptedTask):
+            def fetch(self, ctx, item):
+                result = super().fetch(ctx, item)
+                if self.fetches >= 2:
+                    ctx.stop.set()
+                return result
+
+        task = StopOnSecondFetch(
+            [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {}),
+             ("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {})],
+            items=("item1", "item2"))
+        table = {Scenario.RISK_SLIDER_PAGE: [("fake_release", 2),
+                                              ("give_up", None)]}
+
+        config = make_config(self.tmp)
+        ctx = make_ctx(self.tmp, self.page,
+                       MockBrowserManager(self.page), config)
+        policy = Policy(table=table,
+                        strategies={"fake_release": release_strat},
+                        max_consecutive_fail=config.max_consecutive_fail)
+        loop = CrawlLoop(ctx, task, policy=policy)
+        loop.run()
+
+        # stop 被置位
+        self.assertTrue(ctx.stop.is_set())
+        # 至少有一次 release
+        self.assertGreater(len(task.released), 0)
+
+
+# ============================================================
+# 5 & 6. QueueRouter.release_item + attempts 熔断 + 冷却过滤
+# ============================================================
+
+QUEUE_A = "crawl_1688_contact"
+QUEUE_B = "crawl_mic_contact"
+
+
+def _shop_1688(i):
+    return {"domain": f"shop{i}.1688.com", "name": f"店铺{i}",
+            "url": f"https://shop{i}.1688.com"}
+
+
+def _shop_mic(i):
+    return {"domain": f"shop{i}.cn.made-in-china.com",
+            "name": f"MIC店铺{i}",
+            "url": f"https://shop{i}.cn.made-in-china.com"}
+
+
+class FakeInnerTask(Task):
+    name = "fake-inner"
+    unit = "店铺"
+    batch_unit = "店铺"
+
+    def __init__(self):
+        super().__init__()
+        self.lock = threading.Lock()
+        self.succeeded = []
+        self.fetched = []
+
+    def acquire_item(self, ctx):
+        raise AssertionError("daemon 模式下不应调到 inner.acquire_item")
+
+    def fetch(self, ctx, item):
+        with self.lock:
+            self.fetched.append((ctx.wid, item.get("domain", "?")))
+        return ActionResult(Outcome.OK, "", {"v": 1})
+
+    def on_success(self, ctx, item, result):
+        with self.lock:
+            self.succeeded.append((ctx.wid, item["domain"]))
+        stats = ctx.state.get("task", {}).get("stats")
+        if stats is not None:
+            stats["done"] = stats.get("done", 0) + 1
+        return 1
+
+    def on_giveup(self, ctx, item, reason, kind):
+        return "标记跳过"
+
+    def make_stats(self):
+        return {"done": 0}
+
+
+def make_dual_registry(inner_a=None, inner_b=None):
+    if inner_a is None:
+        inner_a = FakeInnerTask()
+    if inner_b is None:
+        inner_b = FakeInnerTask()
+    return [
+        QueueSpec(
+            queue=QUEUE_A, site="1688", task=inner_a,
+            topup=lambda db, limit: db.topup_contact_work_items(
+                QUEUE_A, "1688", ".1688.com", limit),
+            domain_suffix=".1688.com",
+        ),
+        QueueSpec(
+            queue=QUEUE_B, site="madeinchina", task=inner_b,
+            topup=lambda db, limit: db.topup_contact_work_items(
+                QUEUE_B, "madeinchina", ".cn.made-in-china.com", limit),
+            domain_suffix=".cn.made-in-china.com",
+        ),
+    ]
+
+
+class ReleaseItemTestBase(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = Path(self._tmp.name) / "t.db"
+        self.db = ShopDB(self.db_path)
+        self.inner_a = FakeInnerTask()
+        self.inner_b = FakeInnerTask()
+        registry = make_dual_registry(self.inner_a, self.inner_b)
+        self.router = QueueRouter(
+            registry, db_factory=lambda: ShopDB(self.db_path))
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def make_ctx(self, wid=0):
+        config = RunConfig(db_path=self.db_path, headless=True,
+                           use_proxy=False)
+        return WorkerContext(config=config, store=None,
+                             stop=threading.Event(),
+                             log=lambda m: None, wid=wid)
+
+    def query(self, sql, args=()):
+        conn = sqlite3.connect(self.db_path)
+        conn.row_factory = sqlite3.Row
+        try:
+            return conn.execute(sql, args).fetchall()
+        finally:
+            conn.close()
+
+
+class QueueRouterReleaseItemTest(ReleaseItemTestBase):
+    """QueueRouter.release_item 基本行为 + attempts 熔断。"""
+
+    def test_release_item_returns_pending_on_first_release(self):
+        """首次 release：attempts 1 < 3 → pending。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx()
+        item = self.router.acquire_item(ctx)
+
+        status = self.router.release_item(ctx)
+        self.assertEqual(status, "pending")
+
+        row = self.query("SELECT * FROM work_items WHERE id=?",
+                         (item["id"],))[0]
+        self.assertEqual(row["status"], "pending")
+        self.assertEqual(row["attempts"], 1)
+        self.assertIsNone(row["claimed_by"])
+
+    def test_release_item_exhaustion_returns_failed(self):
+        """连续 release 3 次（max_attempts=3）→ failed。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx()
+        item = self.router.acquire_item(ctx)
+
+        # 第一次 release → pending
+        s1 = self.router.release_item(ctx)
+        self.assertEqual(s1, "pending")
+
+        # 重新认领
+        ctx2 = self.make_ctx()
+        self.router.acquire_item(ctx2)  # 同一个 item
+        s2 = self.router.release_item(ctx2)
+        self.assertEqual(s2, "pending")
+
+        # 第三次认领 + release → failed（attempts=3）
+        ctx3 = self.make_ctx()
+        self.router.acquire_item(ctx3)
+        s3 = self.router.release_item(ctx3)
+        self.assertEqual(s3, "failed")
+
+        row = self.query("SELECT * FROM work_items WHERE id=?",
+                         (item["id"],))[0]
+        self.assertEqual(row["status"], "failed")
+        self.assertEqual(row["attempts"], 3)
+        self.assertEqual(json.loads(row["result_json"]), "attempts exhausted")
+
+    def test_release_item_removes_state_key(self):
+        """release 后 ctx.state 中的 daemon_work_item_id 被 pop。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx()
+        self.router.acquire_item(ctx)
+        self.assertIn(_STATE_KEY, ctx.state)
+
+        self.router.release_item(ctx)
+        self.assertNotIn(_STATE_KEY, ctx.state)
+
+    def test_release_item_no_claim_returns_empty(self):
+        """无认领记录时 release_item 返回 ""。"""
+        ctx = self.make_ctx()
+        status = self.router.release_item(ctx)
+        self.assertEqual(status, "")
+
+    def test_failed_item_not_re_claimable(self):
+        """attempts 耗尽置 failed 后不再被 claim。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+
+        for _ in range(3):
+            ctx = self.make_ctx()
+            item = self.router.acquire_item(ctx)
+            self.router.release_item(ctx)
+
+        # 第 4 次认领：item 已是 failed，不应被 claim
+        from fetcher.control.queue_router import _WAIT_TIMEOUT as WT
+        import fetcher.control.queue_router as qr
+        orig = qr._WAIT_TIMEOUT
+        qr._WAIT_TIMEOUT = 0.05
+        try:
+            ctx4 = self.make_ctx()
+            stop = threading.Event()
+            ctx4.stop = stop
+            threading.Timer(0.2, stop.set).start()
+            item4 = self.router.acquire_item(ctx4)
+            self.assertIsNone(item4)
+        finally:
+            qr._WAIT_TIMEOUT = orig
+
+
+class CooldownFilterAfterReleaseTest(ReleaseItemTestBase):
+    """release 后该 site 冷却中不可见。"""
+
+    def test_release_sets_cooldown_site_invisible(self):
+        """release 后 cooldown_until 设置 → eligible_queues 过滤该 site。"""
+        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        # 认领 A 的 item
+        ctx_a = self.make_ctx(wid=0)
+        item_a = self.router.acquire_item(ctx_a)
+
+        # 设置冷却（模拟策略返回 cooldown 后的 _cooldown 调用）
+        ctx_a.cooldown_until["1688"] = time.time() + 30
+
+        # release
+        self.router.release_item(ctx_a)
+
+        # 此时 1688 在冷却中 → 只认领 B 的 item
+        ctx_b = self.make_ctx(wid=1)
+        ctx_b.cooldown_until["1688"] = time.time() + 30
+        item_b = self.router.acquire_item(ctx_b)
+
+        self.assertIsNotNone(item_b)
+        self.assertEqual(ctx_b.state["queue"], QUEUE_B)
+        self.assertEqual(item_b["domain"], "shop1.cn.made-in-china.com")
+
+
+# ============================================================
+# 7. Task 基类 release_item 默认空实现
+# ============================================================
+
+class TaskBaseReleaseItemTest(unittest.TestCase):
+    def test_task_base_release_item_returns_empty_string(self):
+        """Task 基类 release_item 返回 ""（CLI 兼容）。"""
+        from fetcher.control.task import Task as BaseTask
+        task = BaseTask()
+        result = task.release_item(None)
+        self.assertEqual(result, "")
+
+
+if __name__ == "__main__":
+    unittest.main()
