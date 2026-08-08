# Re-review Package — Step 3.2 fix round 1

## Commits
6ff09e1 fix(multiqueue-p3): Step 3.2 review 修复 I1/M1/M2/M3（solved 守护、site=None 防御、ctx.wait 断言、result_json 去耦合）
53f14cd docs(multiqueue-p3): task-3.2 brief 入库

## Stat
 .../task-3.2-brief.md                              | 144 +++++++++++++++++++++
 .../task-3.2-report.md                             | 113 ++++++++++++++++
 fetcher/fetcher/control/loop.py                    |   6 +-
 fetcher/fetcher/strategy/strategies.py             |   4 +
 fetcher/tests/test_cooldown.py                     |  33 ++++-
 fetcher/tests/test_swapip_two_phase.py             |  33 ++++-
 6 files changed, 321 insertions(+), 12 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-brief.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-brief.md
new file mode 100644
index 0000000..7928dcd
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-brief.md
@@ -0,0 +1,144 @@
+# Task 3.2 Brief — SwapIP 两阶段拆分 + 策略冷却让出/release 链路
+
+> 来源：PLAN.md P3-3 Step 3.2 全文 + SPEC §3.4/§3.5。本文件是本次任务的唯一需求来源。
+
+## 目标
+
+1. **SwapIP 无头两阶段拆分**（SPEC §3.5）：relaunch 未轮换 → 回写本站 Cookie、关闭本站 context（浏览器进程保留，其他站点 view 不受影响）、登记 `needs_relaunch[site]=True` → 输出让出型冷却 → 当前 item release 回 pending → 冷却到期重领时 context 懒建路径发现 needs_relaunch → 走完整 relaunch（Step 2.2 已建懒建消费机制，本 Step 接 SwapIP 置位）
+2. **策略冷却统一语义**（SPEC §3.4）：策略给出让出型冷却但 item 未完成（block_rest / swap_ip 无头）→ release 回 pending（attempts 熔断防无限循环）——本 Step 把 loop 的策略冷却从「原地等待」（Step 1.3 遗留）改为「让出 + release」
+3. **有头 WaitHumanLogin 例外保留**：注释更新「P3 已拆无头路径」
+
+## 规格
+
+### 1. SwapIPStrategy 无头两阶段（strategy/strategies.py）
+
+现状（已读码 strategies.py:86-135）：relaunch 未轮换 → 原地等 rest（有头走 WaitHumanLogin 轮询，无头 ctx.wait）→ 第二次 relaunch。
+
+改后无头路径：
+
+```python
+def run(self, ctx) -> StepResult:
+    ...
+    old_identity = ctx.session.identity
+    result = RelaunchBrowser().run(ctx, self._params)
+    if result.outcome is Outcome.SKIPPED:
+        return StepResult(False, "用户中断")
+    if result.outcome is not Outcome.OK:
+        return StepResult(False, result.detail, result.data)
+    if result.data.get("rotated") or not ctx.config.use_proxy:
+        return StepResult(True, result.detail, result.data)
+
+    # 未轮换（青果 30 分钟时效）——P3 无头两阶段第一步：
+    site = ctx.state.get("active_site")
+    if ctx.headed:
+        # 有头例外保留：WaitHumanLogin 轮询人工登录（需活 page，不拆分）
+        rest = random.uniform(ctx.config.block_rest_min, ctx.config.block_rest_max)
+        login = WaitHumanLogin().run(ctx, {"seconds": rest})
+        if login.outcome is Outcome.OK:
+            SaveCookies().run(ctx, {})
+            return StepResult(True, f"等轮换期间手动登录成功: {login.detail}")
+        if login.outcome is Outcome.SKIPPED:
+            return StepResult(False, "用户中断")
+        return StepResult(False, "未轮换", cooldown=rest)   # 有头也改让出+release
+    # 无头：
+    #  1. 回写本站 Cookie（SaveCookies 或等价）
+    #  2. 关闭本站 context（session.close_site(site)）——进程保留，其他 view 不受影响
+    #  3. 登记 needs_relaunch[site]=True（browser_manager.mark_needs_relaunch）
+    #  4. 输出让出型冷却 uniform(block_rest_min, block_rest_max)
+    rest = random.uniform(ctx.config.block_rest_min, ctx.config.block_rest_max)
+    ctx.log(f"    [!] 出口 IP 尚未轮换（青果 30 分钟时效），"
+            f"登记 needs_relaunch[{site}]，让出冷却 {rest / 60:.1f} 分钟，"
+            f"冷却到期重领时走完整 relaunch")
+    ...（回写+close_site+mark_needs_relaunch，注意异常容错）
+    return StepResult(False, f"未轮换，已登记两阶段", cooldown=rest)
+```
+
+- `close_site(site)` 已存在（Step 2.1）；`mark_needs_relaunch` 已存在（Step 2.2）；SaveCookies 原子存在
+- 有头路径：也改为「返回 cooldown + release」？SPEC §3.5 裁定「有头 WaitHumanLogin 原地等待保留」——即**有头分支维持原地等待现状**（不拆）？再读 SPEC：「**有头模式例外保留**：WaitHumanLogin 人工登录轮询需要活 page，维持原地等待不拆分（有头=人工辅助场景，利用率不是目标）；代码注释同步更新『P3 已拆无头路径』」。
+  - 裁定：有头分支**保留原地等待**（WaitHumanLogin 轮询 + 必要时原地等 rest），不做让出——但「第二次 relaunch」是否保留？SPEC 说「第二次 relaunch 由此并入正常 launch 路径」——无头路径下第二次 relaunch 不再显式执行（靠 needs_relaunch 懒建消费）。有头路径保留现状（等轮换后仍可原地第二次 relaunch 或直接 solved）。**有头 = 人工辅助场景，保持现状行为**（含原地 rest + 第二次 relaunch），只更新注释。
+  - 所以有头分支代码基本不动，只加注释「P3 已拆无头路径，有头保留原地（人工辅助场景）」。
+- `needs_release` 语义：无头路径返回 StepResult(cooldown=rest)——loop 的策略冷却统一语义（见规格 2）会自动 release。不需要额外字段——**策略冷却 + item 未完成 = release** 是统一规则（SPEC §3.4），不是 swap_ip 特有。
+
+### 2. loop 策略冷却改为「让出 + release」（control/loop.py）
+
+`_process_item` 策略执行段（现状 loop.py:430-437）：
+
+```python
+if step.cooldown and self._cooldown(
+        step.cooldown, f"strategy:{decision.strategy}"):
+    return "stop", 0
+```
+
+改为：
+
+```python
+if step.cooldown:
+    # P3：策略冷却统一让出 + release（SPEC §3.4）——冷却期间该站点
+    # 队列不可见，item 释放回 pending（attempts 熔断），冷却到期重领
+    if self._cooldown(step.cooldown, f"strategy:{decision.strategy}",
+                      yield_=True):
+        return "stop", 0
+    return "release", 0
+```
+
+- `run()` 的 kind 分支处理新增 `"release"`：
+  - 不计数（`done_in_batch`/`total_done` 不变）
+  - 调 `self.task.release_item(ctx)`（QueueRouter 新方法：`db.release_work_item(item_id)` + 返回终态记日志；Task 基类默认空实现保证 CLI 兼容——CLI 路径不会产生 release kind，防御性 no-op）
+  - `after_item` 照常调用
+  - 继续循环（下一轮 acquire——该 site 队列冷却中不可见，自然转其他队列；单队列时 condvar 等冷却到期）
+- **item 未完成 + 让出型冷却 = release 是统一规则**——block_rest（BlockRestStrategy 返回 cooldown 且未 solved）同样走 release 重领重试（attempts 熔断）。注意现状 BlockRest 后是原地等再重试同一 item（链式升级）——改为 release 后**策略链在 item 重领后从头开始**（SPEC §3.4 裁定：attempts 不跨认领保留策略链进度；全局限速寄托于 (site,IP) 簿记与预算）
+- stop 语义：release 路径中 stop 置位由下一轮 acquire 的 stop 检查处理（与让出型一致）
+
+### 3. QueueRouter.release_item（control/queue_router.py）
+
+```python
+def release_item(self, ctx) -> str:
+    """当前 worker 的 item 释放回 pending（attempts+1，耗尽置 failed）。
+
+    返回终态（"pending"/"failed"）供日志；无认领记录时返回 ""。
+    """
+```
+
+- 用 `ctx.state["daemon_work_item_id"]` → `db.release_work_item(item_id, max_attempts=3)`（Step 1.1 已有）
+- 终态 "failed"（attempts 耗尽）时记日志「attempts exhausted」——**类目链不死的补插是 P3-4/5 feeder 的事，本 Step 不接**（contact 队列无链式语义）
+- 错误容错同 _finish（落库失败只记日志）
+- Task 基类加 `release_item(self, ctx) -> str: return ""` 默认实现
+
+### 4. 注释同步
+
+- strategies.py SwapIP docstring：「P3 已拆无头两阶段；有头 WaitHumanLogin 例外保留原地（人工辅助场景）」
+- loop._process_item 策略冷却段注释更新（Step 1.3 写的「P3-3 router 接 release 后改让出」→ 已实现）
+
+## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）
+
+至少覆盖：
+
+1. **SwapIP 无头未轮换两阶段**：mock RelaunchBrowser rotated=False + 无头 → 断言 close_site 被调（该 site view 移除）、mark_needs_relaunch 置位、返回 cooldown 非空、无原地 wait（ctx.wait 未被调）
+2. **SwapIP 轮换成功**：rotated=True → solved 无 cooldown（现状回归）
+3. **SwapIP 有头例外**：headed=True → 保持现状（WaitHumanLogin 路径或原地 rest），不置 needs_relaunch
+4. **策略冷却 release 链路（核心）**：loop 集成——fake task fetch 恒 BLOCKED → 策略链走到 block_rest（返回 cooldown）→ loop 返回 "release" kind → router.release_item 落库（work_items attempts+1 回 pending）→ 下一轮重领同一 item（attempts 递增）→ attempts 耗尽置 failed
+5. **release 后冷却过滤**：release 后该 site 队列在冷却中不可见（eligible_queues 过滤）
+6. **attempts 熔断**：max_attempts=3 第三次 release 置 failed（result_json="attempts exhausted"）
+7. **Task 基类 release_item 默认空实现**（CLI 兼容）
+8. **stop 语义**：release 路径 stop 后退出干净（集成测试或单测）
+
+## 上下文
+
+- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 420 passed）
+- 现状（已读码）：strategies.py SwapIPStrategy（:86-135，原地等待 + 第二次 relaunch）；loop.py _process_item 策略冷却（`if step.cooldown and self._cooldown(...)` 原地型）；queue_router.py QueueRouter（Step 3.1 完成，含 _finish 模式）；Task 基类（control/task.py，Step 3.1 已加 budget_for）
+- 基础设施已就绪：close_site（Step 2.1）、mark_needs_relaunch/懒建消费（Step 2.2）、release_work_item（Step 1.1）、_cooldown yield_（Step 1.3）
+- 本 Step 不动 db.py、engine.py、cli/main.py、Session/BrowserManager（如 close_site 有缺可微调但保持语义）
+- 注意：block_rest 让出+release 后**策略链重领重置**是行为变化（SPEC §3.4 裁定接受）——相关既有测试（test_control_loop.py 的策略链测试、test_policy.py）若断言「同 item 链式升级」需要适配为「release 重领」语义
+
+## Git
+
+- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/strategy/strategies.py`、`fetcher/fetcher/control/loop.py`、`fetcher/fetcher/control/queue_router.py`、`fetcher/fetcher/control/task.py`、`fetcher/tests/` 下本次改动文件
+- 工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**绝不碰绝不带**，不要 `git add -A`
+- commit 标题风格：`feat(multiqueue-p3): <一句话>`
+
+## 验收
+
+1. TDD 证据（RED→GREEN）
+2. 全量 `cd fetcher && python -m pytest tests -q` 绿
+3. 单测覆盖：SwapIP 无头两阶段状态流转（mock rotated=False）、策略冷却 release→重领→attempts 熔断全链路
+4. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-report.md`：实现摘要、测试列表、TDD 证据、改动文件、自查发现
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-report.md
new file mode 100644
index 0000000..315f251
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-report.md
@@ -0,0 +1,113 @@
+# Task 3.2 Report — SwapIP 两阶段拆分 + 策略冷却让出/release 链路
+
+> 基线 commit：5c1afe8（438 passed）· 分支 `feat/multiqueue-p3`
+
+## 实现摘要
+
+修复 Step 3.2 review 发现 4 条问题（I1 + M1/M2/M3），详情见 Fix Round 1 文档
+`task-3.2-fix1.md`。
+
+### I1（Important，防御性）— loop.py `_process_item` 策略冷却无条件优先
+
+**问题**：`if step.cooldown:` 无条件优先于 `step.solved`，若未来策略返回
+`StepResult(solved=True, cooldown=0.5)`，item 会被误 release 而非成功。
+
+**修复**：`loop.py:456` cooldown 分支加 `not step.solved` 守护——
+```python
+if step.cooldown and not step.solved:
+```
+solved=True 时不 release，cooldown 仅作冷却建议不计。
+
+**适配测试**：`test_cooldown.py`
+- 原 `test_strategy_cooldown_via_chokepoint_then_retry_success`（solved=True+cooldown）
+  → 重命名为 `test_strategy_cooldown_with_solved_true_skips_release`：
+  断言 solved 优先、cooldown 未被调用、fetch 重试后成功（fetches=2, succeeded=["item1"]）
+- 新增 `test_strategy_cooldown_solved_false_triggers_release`：solved=False+cooldown
+  → 触发让出+release（原路径全覆盖保留）
+
+**适配测试**：`test_swapip_two_phase.py`
+- `FakeReleaseStrategy` 实例化从 `solved=True` 改为 `solved=False`（2 处），
+  使其正确测试 release 路径
+
+### M1 — strategies.py site=None 时两阶段静默输出 cooldown
+
+**问题**：`if site:` 守卫正确防空指针，但 site=None 时继续输出 cooldown，item 重试
+至 attempts 耗尽而不报错。
+
+**修复**：`strategies.py:196-200` 加 else 分支——
+```python
+else:
+    ctx.log(f"    [WARNING] active_site 未设置，无法登记两阶段")
+    return StepResult(False, "active_site 未设置，无法登记两阶段")
+```
+不输出 cooldown，避免静默耗尽 attempts。
+
+### M2 — test_swapip_two_phase.py 缺 ctx.wait 未调用断言
+
+**修复**：`test_not_rotated_headless_triggers_two_phase` 内用
+`patch.object(ctx, 'wait')` mock + `assert_not_called()` 验证无头路径不含原地 wait。
+
+### M3 — test_swapip_two_phase.py result_json 断言脆弱
+
+**修复**：`json.loads(row["result_json"])` → `assertIn("attempts exhausted", row["result_json"])`，
+不再与 `json.dumps("attempts exhausted")` 格式耦合；顺带移除未使用的 `import json`。
+
+## 测试列表
+
+### 改动文件
+
+| 文件 | 改动 |
+|---|---|
+| `fetcher/fetcher/control/loop.py` | I1: cooldown 分支加 `not step.solved` 守护 |
+| `fetcher/fetcher/strategy/strategies.py` | M1: site=None else 分支返回错误不输出 cooldown |
+| `fetcher/tests/test_cooldown.py` | I1 适配：重命名 1 测试 + 新增 1 测试 |
+| `fetcher/tests/test_swapip_two_phase.py` | M1/M2/M3 修复：新增 M1 测试、M2 mock、M3 断言去耦合、solved 参数修正 |
+
+### 测试覆盖
+
+| 测试 | 覆盖项 |
+|---|---|
+| `test_strategy_cooldown_with_solved_true_skips_release` | I1: solved=True+cooldown → solved 优先，cooldown 不触发 |
+| `test_strategy_cooldown_solved_false_triggers_release` | I1: solved=False+cooldown → release（原路径回归） |
+| `test_strategy_cooldown_interrupted_by_stop_is_stop_terminal` | stop 语义（solved=False 无变更） |
+| `test_no_active_site_headless_returns_error_no_cooldown` | M1: active_site 未设置 → 错误无 cooldown |
+| `test_not_rotated_headless_triggers_two_phase` | M2: ctx.wait 未被调用断言 |
+| `test_release_item_exhaustion_returns_failed` | M3: assertIn 替代 json.loads |
+| 全量 | 440 passed, 2 subtests passed |
+
+## TDD 证据
+
+### I1 TDD（RED → GREEN）
+
+1. **RED**：运行 `test_strategy_cooldown_with_solved_true_skips_release`
+   （原名 test_strategy_cooldown_via_chokepoint_then_retry_success）：
+   solved=True+cooldown 时原断言 fetches=1 / succeeded=[] 与新守护不兼容
+   ——策略被调后 solved 优先，会重试 fetch 成功（fetches=2, succeeded=["item1"]）
+2. **GREEN**：加 `not step.solved` 守护 → 更新断言后通过
+
+### M1 TDD（RED → GREEN）
+
+1. **RED**：`test_no_active_site_headless_returns_error_no_cooldown`
+   ——加 else 分支前，site=None 走默认路径输出 cooldown，断言 `assertIsNone(result.cooldown)` 失败
+2. **GREEN**：加 else 分支 return StepResult(False, …, cooldown=None 即默认) → 通过
+
+### M2/M3（测试本身改动，修复前后行为确认）
+
+- M2：mock ctx.wait → assert_not_called，SwapIP 无头路径未调 ctx.wait（结构验证）
+- M3：`assertIn("attempts exhausted", …)` 替代 `json.loads(…)"`，db.py `json.dumps("attempts exhausted")` 不变
+
+## 修复记录
+
+| 编号 | 严重程度 | 描述 | 状态 |
+|---|---|---|---|
+| I1 | Important | loop.py cooldown 无条件优先 solved | ✅ 已修复 |
+| M1 | Minor | strategies.py site=None 静默输出 cooldown | ✅ 已修复 |
+| M2 | Minor | test 缺 ctx.wait 未调用断言 | ✅ 已修复 |
+| M3 | Minor | test result_json 断言脆弱 | ✅ 已修复 |
+
+## 全量测试
+
+```
+cd fetcher && python -m pytest tests -q
+440 passed, 2 subtests passed in 26.59s
+```
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index 4902728..b8a9ba8 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -444,22 +444,24 @@ class CrawlLoop:
             ctx.state["attempt"] = decision.attempt
             ctx.set_status(state=f"处置: {decision.strategy}"
                                  f"（{decision.attempt} 次）")
             self.log(f"⚠ {reason} → 策略 {decision.strategy}"
                      f"（第 {decision.attempt} 次）")
             step = strategy.run(ctx)
             if step.solved:
                 self.log(f"✓ 策略 {decision.strategy} 完成: {step.detail}")
             # 策略冷却统一让出 + release（P3 SPEC §3.4）：冷却期间该
             # 站点队列不可见，item 释放回 pending（attempts 熔断），
-            # 冷却到期重领（策略链从头开始）
-            if step.cooldown:
+            # 冷却到期重领（策略链从头开始）。
+            # 守护：solved=True 时不 release（防御未来策略同时返回
+            # solved+cooldown 的场景，此时 cooldown 仅作冷却建议不计）。
+            if step.cooldown and not step.solved:
                 if self._cooldown(step.cooldown,
                                   f"strategy:{decision.strategy}",
                                   yield_=True):
                     return "stop", 0
                 return "release", 0
         return "stop", 0
 
     def _bind_item_site(self):
         """daemon 多站点路径：按 ctx.state["active_site"] 切换
         ctx.site / inspector / policy。CLI 路径（sites=None）无操作。"""
diff --git a/fetcher/fetcher/strategy/strategies.py b/fetcher/fetcher/strategy/strategies.py
index a6ed9e2..3da9a86 100644
--- a/fetcher/fetcher/strategy/strategies.py
+++ b/fetcher/fetcher/strategy/strategies.py
@@ -183,20 +183,24 @@ class SwapIPStrategy:
         # 关闭本站 context（浏览器进程保留，其他 site view 不受影响）
         if site:
             try:
                 ctx.session.close_site(site, store=ctx.store, log=ctx.log)
             except Exception:  # noqa: BLE001
                 pass
             try:
                 ctx.browser_manager.mark_needs_relaunch(ctx.session, site)
             except Exception:  # noqa: BLE001
                 pass
+        else:
+            # site 未设置：无法登记两阶段（无头路径标记 active_site 是上游职责）
+            ctx.log(f"    [WARNING] active_site 未设置，无法登记两阶段")
+            return StepResult(False, "active_site 未设置，无法登记两阶段")
         return StepResult(False, f"未轮换，已登记两阶段", cooldown=rest)
 
 
 class WaitHumanVerifyStrategy(_AtomStrategy):
     name = "wait_human_verify"
     atom_cls = WaitHumanVerify
 
 
 class WaitHumanLoginStrategy(_AtomStrategy):
     name = "wait_human_login"
diff --git a/fetcher/tests/test_cooldown.py b/fetcher/tests/test_cooldown.py
index e41e8a6..f3a72b5 100644
--- a/fetcher/tests/test_cooldown.py
+++ b/fetcher/tests/test_cooldown.py
@@ -257,34 +257,57 @@ class CooldownChokepointTest(CooldownTestBase):
         loop, ctx = self.make_loop()
         loop._cooldown(0.1, "any_reason")
         self.assertEqual(ctx.cooldown_until, {})
 
 
 # ---------- 用例 2：_process_item 策略冷却集成 ----------
 
 class StrategyCooldownIntegrationTest(CooldownTestBase):
     TABLE = {Scenario.RISK_SLIDER_PAGE: [("cool", 1), ("give_up", None)]}
 
-    def test_strategy_cooldown_via_chokepoint_then_retry_success(self):
-        """首次 fetch 自报 blocked → 策略输出 cooldown=0.3 → P3 策略冷却
-        统一让出 + release（yield_=True）：登记冷却后立即返回，item 释放
-        回 pending 然后循环退出（单 item 无更多任务）。"""
+    def test_strategy_cooldown_with_solved_true_skips_release(self):
+        """策略同时返回 solved=True 和 cooldown → solved 优先，不触发
+        release（防御性：未来策略可能同时输出 solved+cooldown 作冷却建议）。"""
         strategy = CooldownStrategy(cooldown=0.3, solved=True)
         task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1})])
         loop, ctx = self.make_loop(task, self.TABLE, {"cool": strategy})
         calls = spy_cooldown_full(loop)
 
         t0 = time.monotonic()
         loop.run()
         elapsed = time.monotonic() - t0
 
-        # P3：策略冷却 → release（不再 wait + retry）
+        # solved 优先：策略返回 solved=True，cooldown 被忽略，不触发 release
+        # fetch 重试后成功
+        self.assertEqual(task.fetches, 2)
+        self.assertEqual(task.succeeded, ["item1"])
+        self.assertEqual(task.given_up, [])
+        # 冷却未被应用（solved 优先守护）
+        strat_calls = [c for c in calls if c[1] == "strategy:cool"]
+        self.assertEqual(len(strat_calls), 0,
+                         "solved=True 时 cooldown 应被忽略，不触发 _cooldown")
+        # 快速完成（无等待）
+        self.assertLess(elapsed, 0.2)
+
+    def test_strategy_cooldown_solved_false_triggers_release(self):
+        """策略返回 solved=False + cooldown → 触发让出 + release（P3
+        策略冷却统一语义），item 释放回 pending，单 item 循环退出。"""
+        strategy = CooldownStrategy(cooldown=0.3, solved=False)
+        task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1})])
+        loop, ctx = self.make_loop(task, self.TABLE, {"cool": strategy})
+        calls = spy_cooldown_full(loop)
+
+        t0 = time.monotonic()
+        loop.run()
+        elapsed = time.monotonic() - t0
+
+        # 策略冷却 → release（不再 wait + retry）
         self.assertEqual(task.fetches, 1)
         self.assertEqual(task.succeeded, [])
         self.assertEqual(task.given_up, [])
         # 冷却经 chokepoint：spy 记录 reason=f"strategy:cool"、秒数原样透传
         strat_calls = [c for c in calls if c[1] == "strategy:cool"]
         self.assertEqual(len(strat_calls), 1)
         seconds, _reason, prefix, yield_ = strat_calls[0]
         self.assertAlmostEqual(seconds, 0.3, delta=1e-6)
         self.assertIsNone(prefix)  # 策略冷却走静默路径
         self.assertTrue(yield_, "P3 策略冷却已改为 yield_=True（让出型）")
diff --git a/fetcher/tests/test_swapip_two_phase.py b/fetcher/tests/test_swapip_two_phase.py
index 9d68763..bbe318c 100644
--- a/fetcher/tests/test_swapip_two_phase.py
+++ b/fetcher/tests/test_swapip_two_phase.py
@@ -5,21 +5,20 @@
   1. SwapIP 无头未轮换两阶段（close_site + mark_needs_relaunch + cooldown）
   2. SwapIP 轮换成功回归（solved，无 cooldown）
   3. SwapIP 有头例外保留原地（不置 needs_relaunch）
   4. 策略冷却 release 全链路（loop 集成：cooldown → release → 重领 → 熔断）
   5. release 后冷却过滤（eligible_queues 过滤）
   6. attempts 熔断（max_attempts=3）
   7. Task 基类 release_item 默认空实现
   8. release 路径 stop 语义
 """
 
-import json
 import sqlite3
 import tempfile
 import threading
 import time
 import unittest
 from pathlib import Path
 from unittest.mock import ANY, MagicMock, patch
 
 from fetcher import (
     Alibaba1688Plugin,
@@ -123,21 +122,24 @@ class SwapIPHeadlessTwoPhaseTest(SwapIPTwoPhaseTestBase):
         with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
             mock_relaunch.return_value = ActionResult.success(
                 "ok", identity="1688:1.1.1.1", rotated=False)
             # Mock SaveCookies.run
             with patch('fetcher.strategy.strategies.SaveCookies') as mock_save:
                 mock_save_instance = MagicMock()
                 mock_save.return_value = mock_save_instance
                 mock_save_instance.run.return_value = ActionResult.success(
                     "已回写 3 个 Cookie", count=3)
 
-                result = strategy.run(ctx)
+                # 无头路径不含原地 ctx.wait（结构验证）
+                with patch.object(ctx, 'wait') as mock_wait:
+                    result = strategy.run(ctx)
+                    mock_wait.assert_not_called()
 
         # 断言
         self.assertFalse(result.solved)
         self.assertIsNotNone(result.cooldown)
         self.assertGreater(result.cooldown, 0)
         self.assertIn("两阶段", result.detail)
         # RelaunchBrowser 只调了一次
         self.assertEqual(mock_relaunch.call_count, 1)
         # close_site 被调（on session）
         session.close_site.assert_called_once_with(
@@ -214,20 +216,41 @@ class SwapIPHeadlessTwoPhaseTest(SwapIPTwoPhaseTestBase):
         ctx.session = session
 
         strategy = SwapIPStrategy()
         with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
             mock_relaunch.return_value = ActionResult.fatal("重启失败")
             result = strategy.run(ctx)
 
         self.assertFalse(result.solved)
         self.assertIn("重启失败", result.detail)
 
+    def test_no_active_site_headless_returns_error_no_cooldown(self):
+        """无头 + active_site 未设置 → 返回错误、不输出 cooldown
+        （避免静默耗尽 attempts）。"""
+        ctx = self._make_ctx(headed=False)
+        # 不设 active_site
+        ctx.state.pop("active_site", None)
+        session = MagicMock()
+        session.identity = "1688:1.1.1.1"
+        ctx.session = session
+
+        strategy = SwapIPStrategy()
+        with patch.object(RelaunchBrowser, 'run') as mock_relaunch:
+            mock_relaunch.return_value = ActionResult.success(
+                "ok", identity="1688:1.1.1.1", rotated=False)
+            result = strategy.run(ctx)
+
+        self.assertFalse(result.solved)
+        self.assertIn("active_site 未设置", result.detail)
+        self.assertIsNone(result.cooldown,
+                          "site=None 时不应输出 cooldown（避免静默耗尽 attempts）")
+
 
 class SwapIPHeadedExceptionTest(SwapIPTwoPhaseTestBase):
     """SwapIP 有头例外保留：WaitHumanLogin + 第二次 relaunch 原地等待。"""
 
     def test_headed_preserves_wait_human_login_path(self):
         """有头 + 未轮换 → WaitHumanLogin 被调用（不触发两阶段拆分）。"""
         ctx = self._make_ctx(headed=True)
         session = MagicMock()
         session.identity = "1688:1.1.1.1"
         ctx.session = session
@@ -471,21 +494,21 @@ class StrategyCooldownReleaseTest(unittest.TestCase):
     def db_query(self, sql, args=()):
         conn = sqlite3.connect(str(self.db_path))
         conn.row_factory = sqlite3.Row
         try:
             return conn.execute(sql, args).fetchall()
         finally:
             conn.close()
 
     def test_strategy_cooldown_triggers_release_via_loop(self):
         """策略返回 cooldown → loop 返回 "release" → task.release_item 被调。"""
-        release_strat = FakeReleaseStrategy(solved=True, cooldown=0.05)
+        release_strat = FakeReleaseStrategy(solved=False, cooldown=0.05)
         task = ScriptedTask(
             [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {})])
         table = {Scenario.RISK_SLIDER_PAGE: [("fake_release", 2),
                                               ("give_up", None)]}
 
         config = make_config(self.tmp)
         ctx = make_ctx(self.tmp, self.page,
                        MockBrowserManager(self.page), config)
         policy = Policy(table=table,
                         strategies={"fake_release": release_strat},
@@ -499,21 +522,21 @@ class StrategyCooldownReleaseTest(unittest.TestCase):
                            "策略冷却应触发 release_item")
         # item 未被 mark success（释放了）
         self.assertEqual(task.succeeded, [])
         # item 未被 giveup
         self.assertEqual(task.given_up, [])
         # 循环正常退出（stop 未置位，无更多 item）
         self.assertFalse(ctx.stop.is_set())
 
     def test_release_with_stop_exits_cleanly(self):
         """stop 置位后 release 路径退出干净。"""
-        release_strat = FakeReleaseStrategy(solved=True, cooldown=0.05)
+        release_strat = FakeReleaseStrategy(solved=False, cooldown=0.05)
 
         class StopOnSecondFetch(ScriptedTask):
             def fetch(self, ctx, item):
                 result = super().fetch(ctx, item)
                 if self.fetches >= 2:
                     ctx.stop.set()
                 return result
 
         task = StopOnSecondFetch(
             [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {}),
@@ -681,21 +704,21 @@ class QueueRouterReleaseItemTest(ReleaseItemTestBase):
         # 第三次认领 + release → failed（attempts=3）
         ctx3 = self.make_ctx()
         self.router.acquire_item(ctx3)
         s3 = self.router.release_item(ctx3)
         self.assertEqual(s3, "failed")
 
         row = self.query("SELECT * FROM work_items WHERE id=?",
                          (item["id"],))[0]
         self.assertEqual(row["status"], "failed")
         self.assertEqual(row["attempts"], 3)
-        self.assertEqual(json.loads(row["result_json"]), "attempts exhausted")
+        self.assertIn("attempts exhausted", row["result_json"])
 
     def test_release_item_removes_state_key(self):
         """release 后 ctx.state 中的 daemon_work_item_id 被 pop。"""
         self.db.upsert_shops([_shop_1688(1)])
         self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
         ctx = self.make_ctx()
         self.router.acquire_item(ctx)
         self.assertIn(_STATE_KEY, ctx.state)
 
         self.router.release_item(ctx)
