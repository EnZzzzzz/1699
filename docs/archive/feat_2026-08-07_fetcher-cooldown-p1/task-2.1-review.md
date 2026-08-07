=== git log ===
3e719d5 refactor(fetcher): Step 2.1 策略迁移——Sleep/BackoffSleep/BlockRest 只输出 cooldown 不再自等

=== diff --stat ===
 .../task-2.1-brief.md                              | 50 +++++++++++++
 .../task-2.1-report.md                             | 52 ++++++++++++++
 fetcher/fetcher/strategy/strategies.py             | 63 +++++++++++++----
 fetcher/tests/test_cooldown_contract.py            | 81 +++++++++++++++++++++-
 4 files changed, 231 insertions(+), 15 deletions(-)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.1-brief.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.1-brief.md
new file mode 100644
index 0000000..a2111d4
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.1-brief.md
@@ -0,0 +1,50 @@
+# Step 2.1 brief — 策略迁移（Sleep / BackoffSleep / BlockRest）
+
+> 来源：PLAN.md Phase 2 Step 2.1 + SPEC §3.2 + Step 1.1 回填的时长公式。本文本是你的需求唯一来源。
+
+## 内容
+
+改 `fetcher/fetcher/strategy/strategies.py` 三个策略，run() 不再触发任何等待，时长算好放进 `StepResult.cooldown` 返回。**时长公式逐字复刻**（Step 1.1 已读码验证，SPEC §4 假设 2）：
+
+### Sleep 分布（`human_pause_duration(lo, hi)`，atoms/sleep.py:21-27）
+
+```python
+lo >= hi → float(lo)
+否则：t = random.lognormvariate(math.log((lo + hi) / 2), 0.5)
+clamp：max(lo * 0.5, min(t, hi * 5))
+# 随机源：stdlib random 模块级实例
+```
+
+### BackoffSleep（atoms/sleep.py:57-66）
+
+```python
+attempt = params.get("attempt") or ctx.state.get("attempt", 1)   # or 短路逐字保留（0/空串会回落）
+t = min(base * int(attempt), cap)    # base=30.0, cap=180.0（现 BackoffSleepStrategy.params 同款）
+```
+
+### 逐个迁移要求
+
+| 策略 | 迁移后行为 |
+|---|---|
+| `SleepStrategy`（strategies.py:41） | 用上述分布算 t（lo/hi 来自 self._params min/max，与现原子取参路径一致——先读 atoms/sleep.py:36-44 确认），返回 `StepResult(True, detail, cooldown=t)`；不再调 Sleep 原子；detail/log 文案保持现状口径 |
+| `BackoffSleepStrategy`（:46-50） | 按上式算 t（attempt 获取路径逐字保留 or 短路），返回 `StepResult(True, detail, cooldown=t)`；不再调 BackoffSleep 原子 |
+| `BlockRestStrategy`（:53-67） | params 仍 run 时从 `ctx.config.block_rest_min/max` 取（任务级覆盖语义保留）；时长用 Sleep 同款分布（`human_pause_duration(min, max)` 公式逐字复刻——注意现状就是经 Sleep 原子走的对数正态，不是 uniform）；保留现有 log 行（⚠ 风控休息…）；返回 `StepResult(True, detail, cooldown=t)` |
+| `SwapIPStrategy`（:86-135） | **不动逻辑**，类 docstring 加一行例外标注：「冷却例外：内部等待夹在两次 relaunch 之间，不迁移（SPEC §2.2，P3 重议）」 |
+
+时长计算建议提取一个模块级辅助函数（如 `_pause_duration(lo, hi)`）放在 strategies.py 或从 atoms/sleep.py import `human_pause_duration`——**优先 import 复用**（atoms/sleep.py 是既有模块，直接 from import 其分布函数，避免复制公式漂移）；若该函数有不宜 import 的耦合再复制，report 说明选择。
+
+## 既有测试的处理
+
+迁移改变了策略契约（不再自己等待）。若有既有测试断言「策略调用了 ctx.wait / 等待发生了」，这些测试测的是旧契约——在同一 commit 中更新为断言新契约（cooldown 输出、零等待），report 逐条说明改了哪些既有测试、为什么改。不许为了让测试过而保留旧行为。
+
+## 验收
+
+- [ ] 三策略 grep 无 `ctx.wait`（strategies.py 中三策略代码路径）；SwapIP 有例外注释
+- [ ] 时长公式与 SPEC §4 假设 2 逐字一致（import 复用或逐字复刻，report 说明）
+- [ ] 全量 `cd fetcher && python -m pytest tests -x -q` 无回归（被更新的旧契约测试除外，逐条说明）
+
+## 约束
+
+- 只动 `fetcher/fetcher/strategy/strategies.py` + 必要的既有测试文件。
+- 不碰 loop.py（chokepoint 是 Step 2.2）——**注意**：本 Step 完成后 loop 尚未消费 cooldown，策略冷却暂时不会被执行（中间态），这是计划内的，Step 2.2 接上；因此本 Step 不做运行冒烟，只跑测试。
+- 不碰 atoms/sleep.py（原子保留）。
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.1-report.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.1-report.md
new file mode 100644
index 0000000..333dba3
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.1-report.md
@@ -0,0 +1,52 @@
+# Step 2.1 report — 策略迁移（Sleep / BackoffSleep / BlockRest）
+
+> 依据 task-2.1-brief.md 实现。本 Step 完成后 loop 尚未消费 cooldown（Step 2.2 才接），
+> 属计划内中间态，不做运行冒烟。
+
+## 实现内容
+
+改 `fetcher/fetcher/strategy/strategies.py`，三个策略脱离 `_AtomStrategy`，run() 不再触发任何等待，时长算好放进 `StepResult.cooldown` 返回：
+
+| 策略 | 迁移后行为 |
+|---|---|
+| `SleepStrategy` | `lo/hi` 从 `self._params.get("min"/"max", 2.0/5.0)` 取（与旧 Sleep 原子 atoms/sleep.py:37-38 取参路径一致），`t = human_pause_duration(lo, hi)`；log 文案保留 `...随机等待 {t:.1f}s`，detail 保留 `等待 {t:.1f}s`；返回 `StepResult(True, detail, cooldown=t)` |
+| `BackoffSleepStrategy` | `params = {"base": 30, "cap": 180}` 保留；`attempt = self._params.get("attempt") or ctx.state.get("attempt", 1)`（or 短路逐字保留，0/空串回落）；`t = min(base * int(attempt), cap)`；log 文案保留 `...退避等待 {t:.0f}s（第 {attempt} 次）`；返回 `StepResult(True, detail, cooldown=t)` |
+| `BlockRestStrategy` | min/max 仍 run 时从 `ctx.config.block_rest_min/max` 取（任务级覆盖语义保留）；时长用 Sleep 同款 `human_pause_duration(lo, hi)`（对数正态，与现状经 Sleep 原子走的分布一致）；⚠ 风控休息 log 行原样保留；返回 `StepResult(True, f"等待 {t:.1f}s", cooldown=t)` |
+| `SwapIPStrategy` | 逻辑未动，docstring 加例外标注：「冷却例外：内部等待夹在两次 relaunch 之间，不迁移（SPEC §2.2，P3 重议）」 |
+
+旧 `_AtomStrategy.run` 里 `ctx.state["attempt"] = ctx.state.get("attempt", 1)` 的写入副作用不再存在；新 BackoffSleep 直接以 `ctx.state.get("attempt", 1)` 读取，取值等价，无行为差异。
+
+## 时长复刻方式
+
+**import 复用**：`from fetcher.atoms.sleep import human_pause_duration`。atoms/sleep.py 是既有模块、该函数无耦合（纯 stdlib random/math），import 避免公式复制漂移。BackoffSleep 的 `min(base*int(attempt), cap)` 公式在 atoms/sleep.py 中没有独立函数（嵌在 BackoffSleep.run 内），故按 brief 逐字复刻（含 or 短路）。atoms/sleep.py 未改动（原子保留）。
+
+import 行同步调整：`Sleep, BackoffSleep` 两个原子类不再被 strategies.py 引用，从 import 中移除。
+
+## 更新的既有测试（逐条）
+
+- **无既有测试需要更新**：全仓 grep 确认没有任何既有测试直接 run 这三个策略或断言「策略调用了 ctx.wait」（test_control_loop.py / test_policy.py 均用 FakeStrategy 注入，从不实例化真 Sleep/BackoffSleep/BlockRest 策略）。旧契约无测试锁定，故无「为让测试过而保留旧行为」的问题。
+- **新增测试**（追加到既有文件 `fetcher/tests/test_cooldown_contract.py`，未新建文件，遵守「只动 strategies.py + 必要的既有测试文件」约束）：
+  - `test_sleep_outputs_cooldown_and_never_waits`：cooldown 落在截断区间 [lo*0.5, hi*5]，waits 为空
+  - `test_sleep_fixed_duration_when_min_eq_max`：min==max 时 cooldown == min
+  - `test_sleep_default_params`：缺省 2.0/5.0 取参路径
+  - `test_backoff_linear_with_state_attempt`：attempt=3 → 90s，零等待
+  - `test_backoff_capped`：attempt=99 → 封顶 180s
+  - `test_backoff_attempt_or_short_circuit`：params attempt=0 经 or 短路回落 state；有效值优先
+  - `test_block_rest_reads_config_and_outputs_cooldown`：从 ctx.config 取 min/max、cooldown 在截断区间、零等待、⚠ log 行保留
+
+## 测试结果
+
+- **RED**：新测试对旧代码（HEAD 版 strategies.py）运行失败——`test_backoff_attempt_or_short_circuit` AssertionError（旧实现经原子走 ctx.wait、cooldown 为 None）。
+- **GREEN**：新代码下 `pytest tests/test_cooldown_contract.py` → 12 passed。
+- **全量**：`cd fetcher && python -m pytest tests -x -q` → **243 passed, 2 subtests passed in 8.04s**，无回归。
+- **验收 grep**：strategies.py 中 `ctx.wait` 仅剩 1 处（line 163，SwapIPStrategy 内部等待，例外项）。
+
+## 改动文件
+
+- `fetcher/fetcher/strategy/strategies.py`（三策略迁移 + SwapIP 例外注释 + import 调整）
+- `fetcher/tests/test_cooldown_contract.py`（新增 StrategyCooldownMigrationTest 7 条用例 + 模块 docstring 更新）
+
+## 疑虑
+
+- 旧路径中 Sleep/BlockRest 的 `StepResult.data` 带 `{"seconds": t}`（原子 ActionResult.success 带出），brief 明确返回 `StepResult(True, detail, cooldown=t)`，故新实现不带 data。grep 确认无消费者读取该 data，无影响。
+- BlockRest 旧路径会多打一行 `...随机等待 {t:.1f}s`（来自 Sleep 原子）；brief 只点名保留 ⚠ 行，故该辅助行未保留。若 Step 2.2 chokepoint 会统一打等待日志，则信息不丢。
diff --git a/fetcher/fetcher/strategy/strategies.py b/fetcher/fetcher/strategy/strategies.py
index 67e5e6c..a8ac059 100644
--- a/fetcher/fetcher/strategy/strategies.py
+++ b/fetcher/fetcher/strategy/strategies.py
@@ -7,21 +7,21 @@
 """
 
 from __future__ import annotations
 
 import random
 
 from fetcher.atoms.browser_ops import RelaunchBrowser, SaveCookies
 from fetcher.atoms.human import WaitHumanLogin, WaitHumanVerify
 from fetcher.atoms.identity_ops import ClearIdentity
 from fetcher.atoms.refresh import Refresh
-from fetcher.atoms.sleep import BackoffSleep, Sleep
+from fetcher.atoms.sleep import human_pause_duration
 from fetcher.atoms.slider import SolveSlider
 from fetcher.core.types import Outcome
 from fetcher.strategy.base import StepResult
 
 
 class _AtomStrategy:
     """把单个原子包装成策略的基类（params 由策略固定或取默认值）。"""
 
     name = ""
     atom_cls = None
@@ -31,47 +31,80 @@ class _AtomStrategy:
         self._params = {**self.params, **params}
         self._atom = self.atom_cls()
 
     def run(self, ctx) -> StepResult:
         ctx.state["attempt"] = ctx.state.get("attempt", 1)
         result = self._atom.run(ctx, self._params)
         solved = result.outcome is Outcome.OK
         return StepResult(solved=solved, detail=result.detail, data=result.data)
 
 
-class SleepStrategy(_AtomStrategy):
+class SleepStrategy:
+    """拟人随机等待：只算时长输出冷却，不自己等待（等待由控制层执行）。
+
+    时长分布与 Sleep 原子同款（对数正态，截断 [min*0.5, max*5]），
+    取参路径一致：min/max 来自 params，缺省 2.0/5.0。
+    """
+
     name = "sleep"
-    atom_cls = Sleep
 
+    def __init__(self, **params):
+        self._params = params
+
+    def run(self, ctx) -> StepResult:
+        lo = float(self._params.get("min", 2.0))
+        hi = float(self._params.get("max", 5.0))
+        t = human_pause_duration(lo, hi)
+        ctx.log(f"    ...随机等待 {t:.1f}s")
+        return StepResult(True, f"等待 {t:.1f}s", cooldown=t)
+
+
+class BackoffSleepStrategy:
+    """网络层错误的退避等待（base=30, cap=180，与旧引擎一致）。
+
+    只算时长输出冷却，不自己等待（等待由控制层执行）。
+    """
 
-class BackoffSleepStrategy(_AtomStrategy):
-    """网络层错误的退避等待（base=30, cap=180，与旧引擎一致）。"""
     name = "backoff_sleep"
-    atom_cls = BackoffSleep
     params = {"base": 30, "cap": 180}
 
+    def __init__(self, **params):
+        self._params = {**self.params, **params}
+
+    def run(self, ctx) -> StepResult:
+        base = float(self._params.get("base", 30.0))
+        cap = float(self._params.get("cap", 180.0))
+        attempt = self._params.get("attempt") or ctx.state.get("attempt", 1)
+        t = min(base * int(attempt), cap)
+        ctx.log(f"    ...退避等待 {t:.0f}s（第 {attempt} 次）")
+        return StepResult(True, f"退避 {t:.0f}s", cooldown=t)
+
 
-class BlockRestStrategy(_AtomStrategy):
+class BlockRestStrategy:
     """风控原地休息：当前 IP 上长休息后再试（block_rest_min~max）。
 
-    时长在 run 时从 ctx.config 取，保证任务级覆盖生效。
+    时长在 run 时从 ctx.config 取，保证任务级覆盖生效；分布与 Sleep
+    同款（对数正态）。只算时长输出冷却，不自己等待（等待由控制层执行）。
     """
+
     name = "block_rest"
-    atom_cls = Sleep
+
+    def __init__(self, **params):
+        self._params = params
 
     def run(self, ctx) -> StepResult:
-        self._params = {"min": ctx.config.block_rest_min,
-                        "max": ctx.config.block_rest_max}
+        lo = float(ctx.config.block_rest_min)
+        hi = float(ctx.config.block_rest_max)
         ctx.log(f"    ⚠ 风控休息：保持当前 IP {ctx.identity}，"
-                f"休息 {self._params['min'] / 60:.0f}~"
-                f"{self._params['max'] / 60:.0f} 分钟后重试")
-        return super().run(ctx)
+                f"休息 {lo / 60:.0f}~{hi / 60:.0f} 分钟后重试")
+        t = human_pause_duration(lo, hi)
+        return StepResult(True, f"等待 {t:.1f}s", cooldown=t)
 
 
 class RefreshStrategy(_AtomStrategy):
     name = "refresh"
     atom_cls = Refresh
 
 
 class SolveSliderStrategy(_AtomStrategy):
     name = "solve_slider"
     atom_cls = SolveSlider
@@ -79,20 +112,22 @@ class SolveSliderStrategy(_AtomStrategy):
 
 class RelaunchBrowserStrategy(_AtomStrategy):
     """重启浏览器（浏览器死亡修复 / IP 轮换重绑）。"""
     name = "relaunch_browser"
     atom_cls = RelaunchBrowser
 
 
 class SwapIPStrategy:
     """换 IP：重启浏览器绑定新出口 IP（通道不变，靠出口轮换/重连）。
 
+    冷却例外：内部等待夹在两次 relaunch 之间，不迁移（SPEC §2.2，P3 重议）。
+
     迁移旧引擎 block_stage==1 的完整逻辑：
         1. 重启浏览器（旧 Cookie 先回写）；
         2. 出口尚未轮换（青果 30 分钟时效，identity 没变）：休息一轮
            等其过期（有头模式期间可人工登录，登录成功立即算解决），
            再重启一次绑定新 IP；
         3. 两步都成功即 solved（是否真换到 IP 由 data["rotated"] 标注）。
     """
 
     name = "swap_ip"
 
diff --git a/fetcher/tests/test_cooldown_contract.py b/fetcher/tests/test_cooldown_contract.py
index eb84af5..0aad389 100644
--- a/fetcher/tests/test_cooldown_contract.py
+++ b/fetcher/tests/test_cooldown_contract.py
@@ -1,19 +1,25 @@
 # -*- coding: utf-8 -*-
 """冷却契约（P1）单测：StepResult.cooldown 与 WorkerContext.cooldown_until
 是纯加法字段——默认值、关键字构造生效、既有三参数位置构造兼容、
-default_factory 语义（两实例不共享同一份 dict）。"""
+default_factory 语义（两实例不共享同一份 dict）。
+
+Step 2.1 起追加策略迁移契约：Sleep / BackoffSleep / BlockRest 三策略
+run() 只算时长放进 StepResult.cooldown，自身零等待（不触 ctx.wait）。"""
 
 import unittest
+from types import SimpleNamespace
 
 from fetcher.core.context import WorkerContext
 from fetcher.strategy.base import StepResult
+from fetcher.strategy.strategies import (BackoffSleepStrategy,
+                                         BlockRestStrategy, SleepStrategy)
 
 
 class StepResultCooldownTest(unittest.TestCase):
     def test_cooldown_default_none(self):
         r = StepResult(True)
         self.assertIsNone(r.cooldown)
 
     def test_cooldown_keyword_construction(self):
         r = StepResult(True, "x", cooldown=12.5)
         self.assertTrue(r.solved)
@@ -36,12 +42,85 @@ class WorkerContextCooldownUntilTest(unittest.TestCase):
         self.assertEqual(ctx.cooldown_until, {})
 
     def test_cooldown_until_not_shared_between_instances(self):
         a = WorkerContext(log=lambda m: None)
         b = WorkerContext(log=lambda m: None)
         a.cooldown_until["block"] = 123.0
         self.assertEqual(b.cooldown_until, {})
         self.assertIsNot(a.cooldown_until, b.cooldown_until)
 
 
+def _fake_ctx(**cfg):
+    """最小假 ctx：记录 log/wait 调用；config 只带 block_rest_min/max。"""
+    base = dict(block_rest_min=60.0, block_rest_max=120.0)
+    base.update(cfg)
+    ctx = SimpleNamespace(state={}, logs=[], waits=[], identity="1.1.1.1",
+                          config=SimpleNamespace(**base))
+    ctx.log = ctx.logs.append
+
+    def wait(t):
+        ctx.waits.append(t)
+        return False
+
+    ctx.wait = wait
+    return ctx
+
+
+class StrategyCooldownMigrationTest(unittest.TestCase):
+    """Step 2.1 新契约：三策略输出 cooldown、自身零等待（不触 ctx.wait）。"""
+
+    def test_sleep_outputs_cooldown_and_never_waits(self):
+        ctx = _fake_ctx()
+        r = SleepStrategy(min=2.0, max=5.0).run(ctx)
+        self.assertTrue(r.solved)
+        self.assertIsNotNone(r.cooldown)
+        # 对数正态截断区间 [lo*0.5, hi*5]
+        self.assertGreaterEqual(r.cooldown, 1.0)
+        self.assertLessEqual(r.cooldown, 25.0)
+        self.assertEqual(ctx.waits, [])
+
+    def test_sleep_fixed_duration_when_min_eq_max(self):
+        r = SleepStrategy(min=3.0, max=3.0).run(_fake_ctx())
+        self.assertEqual(r.cooldown, 3.0)
+
+    def test_sleep_default_params(self):
+        """缺省参数走 2.0/5.0（与旧原子取参路径一致）。"""
+        r = SleepStrategy().run(_fake_ctx())
+        self.assertGreaterEqual(r.cooldown, 1.0)
+        self.assertLessEqual(r.cooldown, 25.0)
+
+    def test_backoff_linear_with_state_attempt(self):
+        ctx = _fake_ctx()
+        ctx.state["attempt"] = 3
+        r = BackoffSleepStrategy().run(ctx)
+        self.assertEqual(r.cooldown, 90.0)
+        self.assertEqual(ctx.waits, [])
+
+    def test_backoff_capped(self):
+        ctx = _fake_ctx()
+        ctx.state["attempt"] = 99
+        r = BackoffSleepStrategy().run(ctx)
+        self.assertEqual(r.cooldown, 180.0)
+
+    def test_backoff_attempt_or_short_circuit(self):
+        """params['attempt']=0 经 or 短路回落到 state（逐字保留旧语义）。"""
+        ctx = _fake_ctx()
+        ctx.state["attempt"] = 2
+        r = BackoffSleepStrategy(attempt=0).run(ctx)
+        self.assertEqual(r.cooldown, 60.0)
+        # params 有有效 attempt 时优先
+        r2 = BackoffSleepStrategy(attempt=4).run(ctx)
+        self.assertEqual(r2.cooldown, 120.0)
+
+    def test_block_rest_reads_config_and_outputs_cooldown(self):
+        ctx = _fake_ctx(block_rest_min=120.0, block_rest_max=240.0)
+        r = BlockRestStrategy().run(ctx)
+        self.assertTrue(r.solved)
+        self.assertGreaterEqual(r.cooldown, 60.0)    # lo*0.5
+        self.assertLessEqual(r.cooldown, 1200.0)     # hi*5
+        self.assertEqual(ctx.waits, [])
+        # 现有 ⚠ 风控休息 log 行保留
+        self.assertTrue(any("风控休息" in m for m in ctx.logs))
+
+
 if __name__ == "__main__":
     unittest.main()
