=== git log ===
b084129 feat(fetcher): Step 1.2 契约层纯加法——StepResult.cooldown + WorkerContext.cooldown_until

=== diff --stat ===
 .../task-1.2-brief.md                              | 28 ++++++++
 .../task-1.2-report.md                             | 82 ++++++++++++++++++++++
 fetcher/fetcher/core/context.py                    |  4 ++
 fetcher/fetcher/strategy/base.py                   |  4 ++
 fetcher/tests/test_cooldown_contract.py            | 47 +++++++++++++
 5 files changed, 165 insertions(+)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.2-brief.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.2-brief.md
new file mode 100644
index 0000000..53a843a
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.2-brief.md
@@ -0,0 +1,28 @@
+# Step 1.2 brief — 契约层实现 + 单测
+
+> 来源：PLAN.md Phase 1 Step 1.2 + SPEC §3.1（含 Step 1.1 已回填的修正）。本文本是你的需求唯一来源。
+
+## 内容
+
+纯加法契约变更，两处（PolicyDecision **不加**字段——Step 1.1 已验证 decide 链路接触不到策略结果，loop 直接消费 step.cooldown）：
+
+1. **`fetcher/fetcher/strategy/base.py`**：`StepResult`（:26-35）加第四字段 `cooldown: float | None = None`（放最后、带默认值，秒）。语义注释：**策略输出冷却、不执行冷却；cooldown 非空时策略保证自己没有为这段时长等待过**。
+2. **`fetcher/fetcher/core/context.py`**：`WorkerContext`（:83-128）加 `cooldown_until: dict[str, float]`（dataclass field，default_factory=dict）。语义注释：冷却截止时间登记处（reason → time.time()+seconds），唯一写入者是 loop 的 chokepoint（Step 2.2 落地），P1 阶段只写不读，是 P3 调度器的查询接口。
+
+## 测试
+
+新增或并入既有测试文件（先看 `fetcher/tests/` 有没有 strategy/context 相关测试文件，跟随既有组织）：
+
+1. `StepResult` 新字段默认值 None、关键字构造 `StepResult(True, "x", cooldown=12.5)` 生效；
+2. 既有三参数位置构造 `StepResult(True, "x", {"k":1})` 不破坏（cooldown 落默认 None）——grep 全包 `StepResult(` 既有调用点，确认全部是位置≤3 或关键字构造，测试锁定这个兼容性；
+3. `WorkerContext` 新字段初始化（默认空 dict、两实例不共享同一份 dict——default_factory 语义）。
+
+## 验收
+
+- [ ] 纯加法：grep `StepResult(` 与 `WorkerContext(` 全部既有调用点零改动（report 附 grep 结果）
+- [ ] 新单测全绿（TDD 先红后绿）+ 全量 `cd fetcher && python -m pytest tests -x -q` 无回归
+
+## 约束
+
+- 只动 `strategy/base.py`、`core/context.py` + 测试文件。
+- 不改任何策略/loop/atom 代码。
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.2-report.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.2-report.md
new file mode 100644
index 0000000..da43809
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.2-report.md
@@ -0,0 +1,82 @@
+# Step 1.2 report — 契约层实现（冷却策略迁移 P1，Phase 1）
+
+## 实现内容
+
+按 brief 纯加法两处契约变更，无其他改动：
+
+1. **`fetcher/fetcher/strategy/base.py`** — `StepResult` 加第四字段
+   `cooldown: float | None = None`（放最后、带默认值，秒）。语义注释：策略输出冷却、
+   不执行冷却；cooldown 非空时策略保证自己没有为这段时长等待过。
+2. **`fetcher/fetcher/core/context.py`** — `WorkerContext` 加
+   `cooldown_until: dict[str, float]`（dataclass field，default_factory=dict）。
+   语义注释：冷却截止时间登记处（reason → time.time()+seconds），唯一写入者是 loop
+   的 chokepoint（Step 2.2 落地），P1 阶段只写不读，是 P3 调度器的查询接口。
+
+`PolicyDecision` 未加字段（Step 1.1 已验证 decide 链路不接触策略结果）。
+
+## TDD 证据
+
+测试文件：`fetcher/tests/test_cooldown_contract.py`（新增；tests/ 下无既有
+strategy/context 契约测试文件，test_policy.py 只覆盖 Policy/AttemptTracker，故新建）。
+
+### RED（实现前）
+
+```
+$ cd fetcher && python -m pytest tests/test_cooldown_contract.py -q
+FAILED tests/test_cooldown_contract.py::StepResultCooldownTest::test_cooldown_default_none
+FAILED tests/test_cooldown_contract.py::StepResultCooldownTest::test_cooldown_keyword_construction
+FAILED tests/test_cooldown_contract.py::StepResultCooldownTest::test_positional_three_args_still_works
+FAILED tests/test_cooldown_contract.py::WorkerContextCooldownUntilTest::test_cooldown_until_default_empty_dict
+FAILED tests/test_cooldown_contract.py::WorkerContextCooldownUntilTest::test_cooldown_until_not_shared_between_instances
+5 failed in 0.06s
+（AttributeError / TypeError：字段尚不存在）
+```
+
+### GREEN（最小实现后）
+
+```
+$ cd fetcher && python -m pytest tests/test_cooldown_contract.py -q
+.....                                                                    [100%]
+5 passed in 0.03s
+```
+
+## 纯加法验证：`StepResult(` / `WorkerContext(` 全包 grep
+
+### `StepResult(`（全部 ≤3 位置参数或关键字构造，零改动）
+
+- `fetcher/tests/test_control_loop.py:177` `StepResult(solved, f"fake#{self.calls}")`
+- `fetcher/tests/test_control_loop.py:189` `StepResult(r.outcome is Outcome.OK, r.detail, r.data)`（3 位置）
+- `fetcher/tests/test_control_loop.py:356` `StepResult(False, "stop")`
+- `fetcher/fetcher/strategy/strategies.py:38` 关键字 `StepResult(solved=..., detail=..., data=...)`
+- `strategies.py:104/108/110/112/125/127/129/132/134/135` 均 ≤3 位置参数
+- `strategies.py:164` 关键字构造
+
+最严的兼容点是 3 位置参数构造（test_control_loop.py:189、strategies.py:110/112/135），
+新字段放第四且带默认值，不受影响；该兼容性由
+`test_positional_three_args_still_works` 锁定。
+
+### `WorkerContext(`（全部关键字构造，零改动）
+
+- 测试侧：test_contact_task.py:98、test_plugin_extension.py:108/126/142/166/256/280/297、
+  test_yiwugo.py:142/163/178/249/312/357/375、test_detectors.py:73、
+  test_daemon_task.py:152/312、test_madeinchina.py:223、test_control_loop.py:204
+- 生产侧：`fetcher/fetcher/control/engine.py:149`、`fetcher/fetcher/control/loop.py:67`
+
+全部为关键字参数构造，新增带 default_factory 的字段不影响任何既有调用点。
+
+## 全量测试
+
+```
+$ cd fetcher && python -m pytest tests -x -q
+236 passed, 2 subtests passed in 8.24s
+```
+
+## 改动文件
+
+- `fetcher/fetcher/strategy/base.py`（+5 行：字段 + 语义注释）
+- `fetcher/fetcher/core/context.py`（+5 行：字段 + 语义注释）
+- `fetcher/tests/test_cooldown_contract.py`（新增，5 个用例）
+
+## 疑虑
+
+无。两处均为纯加法；既有调用点 grep 复核全部兼容；未触碰任何策略/loop/atom 代码。
diff --git a/fetcher/fetcher/core/context.py b/fetcher/fetcher/core/context.py
index ef6b184..6e21cf3 100644
--- a/fetcher/fetcher/core/context.py
+++ b/fetcher/fetcher/core/context.py
@@ -100,20 +100,24 @@ class WorkerContext:
     wid: int = 0
     tag: str = ""
 
     # 最近一次抓取抛出的异常（Detector 分级 NET_ERROR/NET_STALL/
     # BROWSER_DEAD 的输入；由抓取原子/控制层写入）
     last_error: BaseException | None = None
     # 最近一次抓取的业务结果（抓取原子写回，persist 用）
     last_result: Any = None
     # 控制层/策略层暂存（如 AttemptTracker）
     state: dict = field(default_factory=dict)
+    # 冷却截止时间登记处：reason → time.time()+seconds。唯一写入者是
+    # loop 的 chokepoint（Step 2.2 落地），P1 阶段只写不读，是 P3
+    # 调度器的查询接口。
+    cooldown_until: dict[str, float] = field(default_factory=dict)
 
     # ---- 便捷访问 ----
     @property
     def page(self):
         return self.session.page if self.session else None
 
     @property
     def identity(self) -> str:
         return self.session.identity if self.session else "direct"
 
diff --git a/fetcher/fetcher/strategy/base.py b/fetcher/fetcher/strategy/base.py
index a789074..f480360 100644
--- a/fetcher/fetcher/strategy/base.py
+++ b/fetcher/fetcher/strategy/base.py
@@ -26,20 +26,24 @@ class PolicyAction(enum.Enum):
 class StepResult:
     """策略执行结果。
 
     solved=True 表示处置后「可能」已恢复（控制层应重新检测场景确认）；
     solved=False 表示本次处置无效，Policy 推进到链上下一步。
     """
 
     solved: bool
     detail: str = ""
     data: dict = field(default_factory=dict)
+    # 策略输出的冷却时长（秒）：策略只「输出」冷却、不执行冷却（等待由
+    # 控制层 chokepoint 统一做）；cooldown 非空时策略保证自己没有为
+    # 这段时长等待过。
+    cooldown: float | None = None
 
 
 @runtime_checkable
 class Strategy(Protocol):
     """策略协议：run(ctx) -> StepResult。"""
 
     name: str
 
     def run(self, ctx) -> StepResult:
         ...
diff --git a/fetcher/tests/test_cooldown_contract.py b/fetcher/tests/test_cooldown_contract.py
new file mode 100644
index 0000000..eb84af5
--- /dev/null
+++ b/fetcher/tests/test_cooldown_contract.py
@@ -0,0 +1,47 @@
+# -*- coding: utf-8 -*-
+"""冷却契约（P1）单测：StepResult.cooldown 与 WorkerContext.cooldown_until
+是纯加法字段——默认值、关键字构造生效、既有三参数位置构造兼容、
+default_factory 语义（两实例不共享同一份 dict）。"""
+
+import unittest
+
+from fetcher.core.context import WorkerContext
+from fetcher.strategy.base import StepResult
+
+
+class StepResultCooldownTest(unittest.TestCase):
+    def test_cooldown_default_none(self):
+        r = StepResult(True)
+        self.assertIsNone(r.cooldown)
+
+    def test_cooldown_keyword_construction(self):
+        r = StepResult(True, "x", cooldown=12.5)
+        self.assertTrue(r.solved)
+        self.assertEqual(r.detail, "x")
+        self.assertEqual(r.cooldown, 12.5)
+
+    def test_positional_three_args_still_works(self):
+        """既有三参数位置构造 StepResult(True, "x", {"k": 1}) 不破坏，
+        cooldown 落默认 None（锁定兼容性）。"""
+        r = StepResult(True, "x", {"k": 1})
+        self.assertTrue(r.solved)
+        self.assertEqual(r.detail, "x")
+        self.assertEqual(r.data, {"k": 1})
+        self.assertIsNone(r.cooldown)
+
+
+class WorkerContextCooldownUntilTest(unittest.TestCase):
+    def test_cooldown_until_default_empty_dict(self):
+        ctx = WorkerContext(log=lambda m: None)
+        self.assertEqual(ctx.cooldown_until, {})
+
+    def test_cooldown_until_not_shared_between_instances(self):
+        a = WorkerContext(log=lambda m: None)
+        b = WorkerContext(log=lambda m: None)
+        a.cooldown_until["block"] = 123.0
+        self.assertEqual(b.cooldown_until, {})
+        self.assertIsNot(a.cooldown_until, b.cooldown_until)
+
+
+if __name__ == "__main__":
+    unittest.main()
