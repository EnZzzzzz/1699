=== git log ===
39f3420 docs(cooldown-p1): Step 1.1 读码确认回填 SPEC（时长公式逐字摘录 + PolicyDecision 免透传）

=== diff --stat ===
 docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md   | 12 ++--
 .../task-1.1-brief.md                              | 31 ++++++++
 .../task-1.1-report.md                             | 84 ++++++++++++++++++++++
 3 files changed, 121 insertions(+), 6 deletions(-)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md
index 479e920..08734c4 100644
--- a/docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md
@@ -14,21 +14,21 @@ P0 把 daemon 骨架立起来了，但所有等待仍内联在执行路径里：
 - `CrawlLoop` 新增唯一等待执行点 `_cooldown(seconds, reason)`，loop 自身的 4 处等待与策略上报的冷却全部经它执行；
 - 所有时长计算公式**逐字保留**，全部等待保持 stop 可中断；
 - 本阶段**不做**多队列调度、不做 item 挂起/让出——chokepoint 当前实现仍是「就地等待」，但契约（策略只输出时长、loop 唯一执行等待）让 P3 只需替换 chokepoint 实现即可做让出。
 
 验收口径：**同一批次总耗时、请求节奏分布与旧实现相当**（时长公式逐字保留 + 可中断语义保留，结构性保证等价，冒烟对比佐证）。
 
 ## 2. 范围与非目标
 
 ### 2.1 范围（P1 做）
 
-1. 契约层：`StepResult` 加 `cooldown: float | None` 字段（秒）；`PolicyDecision` 加同名透传字段；`WorkerContext` 加 `cooldown_until: dict[str, float]` 暂存（P3 的状态钩子，本阶段只写不读）。
+1. 契约层：`StepResult` 加 `cooldown: float | None` 字段（秒）；`WorkerContext` 加 `cooldown_until: dict[str, float]` 暂存（P3 的状态钩子，本阶段只写不读）。（`PolicyDecision` 不加透传字段，见 §4 假设 3 的读码结论。）
 2. 策略迁移（`strategy/strategies.py`）：`SleepStrategy` / `BackoffSleepStrategy` / `BlockRestStrategy` 的 run() 不再触发 `ctx.wait`，时长算好放进 `StepResult.cooldown` 返回。
 3. loop 收敛（`control/loop.py`）：新增 `_cooldown(seconds, reason)` chokepoint；4 处既有等待点（批次休息 :129-137、样本间隔 :195-200、周期长休 :203-213、启动退避 :243-249）全部改经 chokepoint；`_process_item` 在 `step.cooldown` 非空时调 chokepoint 执行等待。
 4. 单元测试 + 等价性冒烟。
 
 ### 2.2 非目标（P1 明确不做）
 
 - **SwapIPStrategy 的内部等待不迁移**（裁定见 §4 假设 1）：它的 600~900s 等待夹在「第一次 relaunch → 等青果轮换 → 第二次 relaunch」算法中间（strategies.py:114-135），外移需要把策略拆成跨 loop 迭代的两阶段状态机，且只有配合 P3 的 item 挂起机制才有收益。P1 保留现状并在代码注释中标注为例外。
 - **WaitHumanVerify/Login 的交互等待**不迁移（轮询人工操作，非冷却）。
 - **SolveSlider 的亚秒 `time.sleep`**（atoms/slider.py，拟人轨迹）不迁移。
 - **Engine 启动错开 sleep**（engine.py:201，主线程启动期行为）不动。
@@ -44,30 +44,30 @@ P0 把 daemon 骨架立起来了，但所有等待仍内联在执行路径里：
 # strategy/base.py
 @dataclass
 class StepResult:
     solved: bool
     detail: str = ""
     data: dict = field(default_factory=dict)
     cooldown: float | None = None   # 秒；非空=调用方（loop）应经 chokepoint 执行该冷却
 ```
 
 - 语义：**策略输出冷却、不执行冷却**。`cooldown` 非空时策略保证自己没有为这段时长等待过（调用方执行一次，不重复）。
-- `PolicyDecision`（policy.py:70-77）加 `cooldown: float | None = None` 透传字段；`Policy.decide` 不决策时长，只搬运（decide 当前不接触策略执行结果——实际透传点在 loop：`_process_item` 拿到 `step.cooldown` 直接消费。**若 decide 链路用不上该字段则不加，以读码核实为准，report 说明**）。
+- `PolicyDecision`（policy.py:70-77）**不加 cooldown 字段**（§4 假设 3 已读码验证：decide 只输出 action/strategy/attempt/detail，从不接触策略执行结果；`step = strategy.run(ctx)` 只有 loop 消费，cooldown 由 loop 直接取 `step.cooldown`，无需透传）。
 - `WorkerContext.cooldown_until: dict[str, float]`：chokepoint 每次执行等待时写入 `cooldown_until[reason] = time.time() + seconds`。P0/P1 单队列下无人读它，是 P3 调度器的查询接口。
 
 ### 3.2 策略迁移（逐个）
 
 | 策略 | 现状 | 迁移后 |
 |---|---|---|
 | `SleepStrategy`（:41） | Sleep 原子内 `ctx.wait(t)`（对数正态时长，params min/max） | run() 用同一分布算出 t，返回 `StepResult(True, cooldown=t)`，不调原子 |
-| `BackoffSleepStrategy`（:46-50） | BackoffSleep 原子 `ctx.wait(min(30*attempt,180))` | run() 算 `min(30*attempt,180)`（attempt 来源与现子一致：policy decide 给的 attempt——读码确认其传递路径），返回 cooldown |
-| `BlockRestStrategy`（:53-67） | run 时取 config block_rest_min/max → Sleep 原子 wait | 时长口径改为 `random.uniform(block_rest_min, block_rest_max)`（**注意**：现状经 Sleep 原子是对数正态 clamp 到 [min,max]——迁移时必须保留同一分布，读 atoms/sleep.py 确认分布公式后逐字复刻，report 给出公式对照），返回 cooldown，保留现有 log 行 |
+| `BackoffSleepStrategy`（:46-50） | BackoffSleep 原子 `ctx.wait(min(30*attempt,180))` | run() 算 `min(30*attempt,180)`（attempt 传递路径已读码确认：loop.py:387 `ctx.state["attempt"] = decision.attempt` → 原子读 `ctx.state.get("attempt", 1)`，见 atoms/sleep.py:60），返回 cooldown |
+| `BlockRestStrategy`（:53-67） | run 时取 config block_rest_min/max → Sleep 原子 wait | 时长口径改为策略层内联计算（**注意**：现状经 Sleep 原子是对数正态、clamp 到 `[min*0.5, max*5]`（读码确认，非 `[min,max]`）——迁移时必须保留同一分布，公式逐字复刻依据见 §4 假设 2），返回 cooldown，保留现有 log 行 |
 | `SwapIPStrategy`（:86-135） | 内部 ctx.wait/WaitHumanLogin | **不动**（§2.2 例外），类 docstring 加一行「冷却例外」标注 |
 
 ### 3.3 loop chokepoint
 
 ```python
 # control/loop.py
 def _cooldown(self, seconds: float, reason: str) -> bool:
     """唯一等待执行点：登记冷却截止时间 + 可中断等待。返回 True=被 stop 中断。"""
     self.ctx.cooldown_until[reason] = time.time() + seconds
     ...  # 现状的 wait_countdown / ctx.wait 逻辑收拢到这里
@@ -82,22 +82,22 @@ def _cooldown(self, seconds: float, reason: str) -> bool:
 - 初始化：`WorkerContext` 创建时 `cooldown_until = {}`（core/context.py，dataclass field）。
 - 写入：唯一写入者是 `_cooldown` chokepoint。
 - 读取：P1 无人读（P3 调度器读）。测试可断言写入正确。
 - 生命周期：进程内存态，随 worker 线程消亡；不落库（P3 若需要再议）。
 
 ## 4. 契约与行为后果（假设与验证）
 
 | # | 行为假设 | 依据 | 验证方式 |
 |---|---|---|---|
 | 1 | SwapIP 的内部等待外移需要两阶段状态机，P1 不做的损失可接受 | 已读码验证（主 Agent）：strategies.py:102-135，等待夹在两次 RelaunchBrowser 之间，外移后第二次 relaunch 无人执行会破坏换 IP 语义 | 无需 spike；P3 设计时重议（届时有 item 挂起机制） |
-| 2 | Sleep 原子的时长分布（对数正态 clamp）可以在策略层逐字复刻 | 推断（explore 报告：atoms/sleep.py:41 对数正态，params min/max） | Step 1.1 读 atoms/sleep.py 全文，把分布公式逐字抄进 SPEC 本节回填；测试断言样本落在 [min,max] 且分布参数一致 |
-| 3 | decide/PolicyDecision 链路不需要 cooldown 字段（loop 直接消费 step.cooldown） | 推断（explore 报告：loop.py:386-394 消费 step，decision 只含 action/strategy/attempt） | Step 1.1 读 policy.py 确认；若确认无需透传，§3.1 的 PolicyDecision 字段取消并回填 |
+| 2 | Sleep 原子的时长分布（对数正态 clamp）可以在策略层逐字复刻 | 已读码验证（atoms/sleep.py:21-27 `human_pause_duration`、:36-44 `Sleep.run`、:57-66 `BackoffSleep.run`） | 时长公式逐字摘录（Step 2.1 逐字复刻的唯一依据）：**Sleep**：`lo = float(params.get("min", 2.0))`、`hi = float(params.get("max", 5.0))`，调 `human_pause_duration(lo, hi)`——`lo >= hi` 时返回 `float(lo)`（固定等待）；否则 `median = (lo + hi) / 2`，`t = random.lognormvariate(math.log(median), 0.5)`（随机源：stdlib `random` 模块级实例，对数正态，mu=ln(中位数)、sigma=0.5），clamp `max(lo * 0.5, min(t, hi * 5))`（下限 lo*0.5、上限 hi*5）。**BackoffSleep**：`base = float(params.get("base", 30.0))`、`cap = float(params.get("cap", 180.0))`、`attempt = params.get("attempt") or ctx.state.get("attempt", 1)`，`t = min(base * int(attempt), cap)`（纯线性退避，无随机）。原子内等待调用形式：`interrupted = ctx.wait(t)`，中断返回 `ActionResult(Outcome.SKIPPED, ...)`，否则 `ActionResult.success(..., seconds=t)`。测试断言样本落在 clamp 区间且分布参数一致 |
+| 3 | decide/PolicyDecision 链路不需要 cooldown 字段（loop 直接消费 step.cooldown） | 已读码验证（policy.py:70-77 PolicyDecision 仅 action/strategy/attempt/detail 四字段；decide :156-194 只做链推进决策，从不接触策略执行结果；loop.py:386-394 `step = strategy.run(ctx)` 的返回值只有 `_process_item` 自己消费） | 已验证：不需要透传，loop 直接消费 step.cooldown。§3.1 的 PolicyDecision 字段已取消 |
 | 4 | 迁移后 loop 的等待展示行为（倒计时状态行）不回归 | 现状：wait_countdown 仅 loop 三处使用（board.py:134-148） | chokepoint 实现保留两种展示路径；冒烟观察状态行 |
 | 5 | ctx.wait / wait_countdown 的 stop 可中断语义经 chokepoint 后不变 | 已读码验证：ctx.wait=stop.wait(timeout)（context.py:127-129），wait_countdown 循环 stop.wait(min(1,remain))（board.py:147） | 单测：冷却中置 stop → 立即中断返回 |
 
 ## 5. 验收标准（P1 整体）
 
 1. `cd fetcher && python -m pytest tests -x -q` 全绿（含新增：策略 cooldown 输出、chokepoint 中断、时长边界）。
 2. 策略层不再有任何 `ctx.wait` 调用（Sleep/BackoffSleep/BlockRest 三个策略 grep 为零；SwapIP 例外有注释标注）。
 3. loop.py 的等待执行只出现在 `_cooldown` 内（grep `ctx.wait\|wait_countdown` 在 loop.py 仅 chokepoint 一处）。
 4. 等价性冒烟：直连 `python -m fetcher daemon --db <临时库> --workers 1 --limit 6 -n 3 --batch-rest 60`（小批次强制触发批休+样本间隔+长休路径），日志时间戳序列与旧实现同参数对比，节奏模式一致（间隔落在相同时长区间）；stop 中断等待的行为冒烟一次。
 5. 等价性冒烟：旧 CLI `1688 contact` 同参数跑一遍（同一临时库口径），确认非 daemon 路径也不回归。
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.1-brief.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.1-brief.md
new file mode 100644
index 0000000..7392c51
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.1-brief.md
@@ -0,0 +1,31 @@
+# Step 1.1 brief — 读码确认（SPEC §4 假设 2、3）
+
+> 来源：PLAN.md Phase 1 Step 1.1。本文本是你的需求唯一来源。
+
+## 内容
+
+两个读码确认，结论回填 SPEC：
+
+### ① Sleep/BackoffSleep 的时长分布公式（SPEC §4 假设 2）
+
+读 `fetcher/fetcher/atoms/sleep.py` 全文，把 `Sleep`（约 :41）和 `BackoffSleep`（约 :63）两个原子的时长计算**逐字摘出**（分布类型、参数、clamp 逻辑、随机源），回填到 `docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md` §4 假设 2 行：依据列改「已读码验证（附 file:line）」，验证方式列写入完整公式（后续 Step 2.1 要逐字复刻，写错就全盘皆错）。顺带确认原子内 `ctx.wait` 的确切调用形式。
+
+### ② cooldown 是否需要经 PolicyDecision 透传（SPEC §4 假设 3）
+
+读 `fetcher/fetcher/strategy/policy.py`（PolicyDecision :70-77、decide :156-194）与 `fetcher/fetcher/control/loop.py:319-395`（_process_item 的策略消费链路），确认：`step = strategy.run(ctx)` 的返回值是不是只有 loop 消费、decide 链路是否根本接触不到策略执行结果。
+
+- 若确认 decide 用不上 → SPEC §3.1 中 `PolicyDecision` 加字段那条**删除**，假设 3 回填「已验证：不需要透传，loop 直接消费 step.cooldown」；
+- 若发现 decide 确实需要携带 → 回填「需要透传」并说明理由。
+
+## 背景
+
+P1 要把三个策略（Sleep/BackoffSleep/BlockRest）从「自己 ctx.wait」改成「输出 cooldown 时长」。时长公式必须逐字保留（等价性验收的根基），你摘的公式就是 Step 2.1 的唯一依据。
+
+## 验收
+
+- [ ] SPEC §4 假设 2、3 依据列改为「已读码验证（附 file:line）」，结论明确无歧义
+- [ ] 时长分布公式完整写入 SPEC（含 clamp 边界与随机源）
+
+## 约束
+
+- 只读代码 + 改 SPEC.md，**不改任何 fetcher 代码**。
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.1-report.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.1-report.md
new file mode 100644
index 0000000..2f0160b
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-1.1-report.md
@@ -0,0 +1,84 @@
+# Step 1.1 report — 读码确认（SPEC §4 假设 2、3）
+
+> 执行：2026-08-07，分支 feat/fetcher-cooldown-p1。纯读码 + 回填 SPEC，无 fetcher 代码改动。
+
+## ① 时长分布公式逐字摘录（假设 2 → 已验证）
+
+来源：`fetcher/fetcher/atoms/sleep.py` 全文（66 行）。
+
+### Sleep（Sleep.run :36-44，公式本体 human_pause_duration :21-27）
+
+参数读取（sleep.py:37-38）：
+
+```python
+lo = float(params.get("min", 2.0))
+hi = float(params.get("max", 5.0))
+t = human_pause_duration(lo, hi)
+```
+
+时长公式（sleep.py:21-27，逐字）：
+
+```python
+def human_pause_duration(lo: float = 2.0, hi: float = 5.0) -> float:
+    """拟人随机等待时长（对数正态分布，截断 [lo*0.5, hi*5]）。"""
+    if lo >= hi:
+        return float(lo)
+    median = (lo + hi) / 2
+    t = random.lognormvariate(math.log(median), 0.5)
+    return max(lo * 0.5, min(t, hi * 5))
+```
+
+- 分布类型：对数正态；退化分支 `lo >= hi` → 固定 `float(lo)`。
+- 参数：mu = `math.log((lo + hi) / 2)`（中位数取区间中点），sigma = `0.5`。
+- clamp：`max(lo * 0.5, min(t, hi * 5))`——**下限 lo×0.5、上限 hi×5**（注意：不是 [lo, hi]，SPEC §3.2 原表述「clamp 到 [min,max]」有误，已在回填中更正为 [min*0.5, max*5]）。
+- 随机源：stdlib `random` 模块级实例的 `random.lognormvariate`（无独立 seed/实例）。
+
+### BackoffSleep（BackoffSleep.run :57-66）
+
+```python
+base = float(params.get("base", 30.0))
+cap = float(params.get("cap", 180.0))
+attempt = params.get("attempt") or ctx.state.get("attempt", 1)
+t = min(base * int(attempt), cap)
+```
+
+- 纯线性退避 `min(base * attempt, cap)`，**无随机源、无 clamp 浮动**。
+- attempt 传递路径（已读码确认）：`loop.py:387` `ctx.state["attempt"] = decision.attempt`（decision 来自 policy.decide，attempt=tracker.used，1 起）→ 原子 `ctx.state.get("attempt", 1)`；`params["attempt"]` 非空时优先（`or` 短路，注意 `attempt=0`/空串也会回落到 ctx.state）。
+
+### 原子内 ctx.wait 调用形式（两原子同构）
+
+sleep.py:41-44 / :63-66：
+
+```python
+interrupted = ctx.wait(t)
+if interrupted:
+    return ActionResult(Outcome.SKIPPED, "被停止信号中断")
+return ActionResult.success(f"等待 {t:.1f}s", seconds=t)   # BackoffSleep 文案不同
+```
+
+即 `ctx.wait(t)` 返回 bool（True=被 stop 中断），中断→SKIPPED，正常→success(seconds=t)。
+
+## ② PolicyDecision 链路读码结论（假设 3 → 已验证：不需要透传）
+
+- `PolicyDecision`（policy.py:70-77）只有四字段：`action / strategy / attempt / detail`。
+- `Policy.decide`（policy.py:156-194）是纯链推进决策：输入 scenario+tracker，输出 PolicyDecision；**从不接触策略执行结果**（策略甚至还没执行，decide 在前、run 在后）。
+- 消费链路（loop.py `_process_item` :386-394）：`strategy = self.policy.strategies[decision.strategy]` → `ctx.state["attempt"] = decision.attempt` → `step = strategy.run(ctx)` → 只有 loop 自己读 `step.solved`/`step.detail`。step 返回值没有任何其他消费者。
+- 结论：**decide 链路用不上 cooldown**。`step.cooldown` 由 loop 在 `_process_item` 内直接消费即可，PolicyDecision 不加透传字段。SPEC §3.1 中「PolicyDecision 加字段」一条已删除，§2.1 范围描述同步加了备注。
+
+## SPEC 回填内容（docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md）
+
+1. §2.1 范围第 1 条：删去「`PolicyDecision` 加同名透传字段」，加备注指向假设 3 结论。
+2. §3.1 契约变更：PolicyDecision 条目改为「不加 cooldown 字段」并附读码依据。
+3. §3.2 BackoffSleep 行：attempt 传递路径标注为已读码确认（loop.py:387 → atoms/sleep.py:60）。
+4. §3.2 BlockRest 行：更正 clamp 区间为 `[min*0.5, max*5]`，公式依据指向 §4 假设 2（删除原「random.uniform」表述——与现状对数正态不一致，复刻依据以假设 2 摘录为准）。
+5. §4 假设 2：依据列改「已读码验证（附 file:line）」，验证方式列写入完整公式（分布、参数、clamp、随机源、ctx.wait 调用形式）。
+6. §4 假设 3：依据列改「已读码验证（附 file:line）」，结论「不需要透传，loop 直接消费 step.cooldown」。
+
+## 附带发现（供后续 Step 注意）
+
+- SPEC §3.2 原文「clamp 到 [min,max]」与代码不符（实为 [lo*0.5, hi*5]），已更正；等价性验收的时长区间断言应按 [min*0.5, max*5] 写。
+- `params["attempt"] or ctx.state.get("attempt", 1)` 是 `or` 短路不是 `is None` 判断，复刻时逐字保留。
+
+## commit
+
+（见下方 git log；message：`docs(cooldown-p1): Step 1.1 读码确认回填 SPEC（时长公式逐字摘录 + PolicyDecision 免透传）`）
