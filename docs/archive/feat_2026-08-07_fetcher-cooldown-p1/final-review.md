=== git log ===
9096948 docs: P1 冷却策略迁移落地同步——路线表标记完成 + §6 迁移注
eb54ce7 docs(cooldown-p1): Step 3.1 完成（PLAN 勾选 + ledger）
4570271 docs(cooldown-p1): Step 3.1 等价性冒烟收尾（D 段两路径节奏一致；E 段用户裁定按单测+运行时证据收口；F 段零污染）
1fe25c1 docs(cooldown-p1): Step 3.1 首次派发失联，裁定整体重跑（ledger）
0bf5fa9 docs(cooldown-p1): Step 2.3 完成（review clean，PLAN 勾选 + ledger + 过程文件归档）
9e5b005 test(fetcher): Step 2.3 冷却迁移 loop 侧单测——chokepoint/策略冷却集成/4 处等待点（含防假阳性破坏证据）
44e4c49 docs(cooldown-p1): Step 2.2 完成（review clean，PLAN 勾选 + ledger + 过程文件归档）
df1a925 refactor(fetcher): Step 2.2 loop 冷却 chokepoint——4 处等待点与策略冷却收敛至 _cooldown
9f0f403 docs(cooldown-p1): Step 2.1 完成（review clean，PLAN 勾选 + ledger + 过程文件归档）
3e719d5 refactor(fetcher): Step 2.1 策略迁移——Sleep/BackoffSleep/BlockRest 只输出 cooldown 不再自等
23044ed docs(cooldown-p1): Step 1.2 完成（review clean，PLAN 勾选 + ledger + 过程文件归档）
b084129 feat(fetcher): Step 1.2 契约层纯加法——StepResult.cooldown + WorkerContext.cooldown_until
635b170 docs(cooldown-p1): Step 1.1 完成（review clean，PLAN 勾选 + ledger + 过程文件归档）
39f3420 docs(cooldown-p1): Step 1.1 读码确认回填 SPEC（时长公式逐字摘录 + PolicyDecision 免透传）
71bde8f docs(cooldown-p1): SPEC/PLAN（评审通过）+ ledger

=== diff --stat ===
 docs/feat_2026-08-07_fetcher-cooldown-p1/PLAN.md   | 100 ++++
 docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md   | 107 +++++
 docs/feat_2026-08-07_fetcher-cooldown-p1/ledger.md |  31 ++
 .../smoke/e2.pid                                   |   1 +
 .../smoke/e_sigterm.out                            |   1 +
 .../smoke/e_sigterm.sh                             |  23 +
 .../smoke/e_sigterm2.out                           |  65 +++
 .../smoke/seed.py                                  |  45 ++
 .../smoke/seed_list.txt                            |   6 +
 .../task-1.1-brief.md                              |  31 ++
 .../task-1.1-report.md                             |  84 ++++
 .../task-1.1-review.md                             | 223 +++++++++
 .../task-1.2-brief.md                              |  28 ++
 .../task-1.2-report.md                             |  82 ++++
 .../task-1.2-review.md                             | 245 ++++++++++
 .../task-2.1-brief.md                              |  50 ++
 .../task-2.1-report.md                             |  52 ++
 .../task-2.1-review.md                             | 386 +++++++++++++++
 .../task-2.2-brief.md                              |  46 ++
 .../task-2.2-report.md                             | 136 ++++++
 .../task-2.2-review.md                             | 411 ++++++++++++++++
 .../task-2.3-brief.md                              |  26 +
 .../task-2.3-report.md                             |  96 ++++
 .../task-2.3-review.md                             | 533 +++++++++++++++++++++
 .../task-3.1-brief.md                              |  60 +++
 .../task-3.1-report.md                             | 303 ++++++++++++
 .../task-3.2-report.md                             |  40 ++
 docs/scheduler-architecture.md                     |   4 +-
 fetcher/fetcher/control/loop.py                    |  38 +-
 fetcher/fetcher/core/context.py                    |   4 +
 fetcher/fetcher/strategy/base.py                   |   4 +
 fetcher/fetcher/strategy/strategies.py             |  60 ++-
 fetcher/tests/test_cooldown.py                     | 383 +++++++++++++++
 fetcher/tests/test_cooldown_contract.py            | 126 +++++
 34 files changed, 3805 insertions(+), 25 deletions(-)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/PLAN.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/PLAN.md
new file mode 100644
index 0000000..fb0b872
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/PLAN.md
@@ -0,0 +1,100 @@
+# PLAN — 冷却策略迁移（P1）
+
+> 需求与设计唯一来源：同目录 SPEC.md（上游：docs/scheduler-architecture.md §6/§10 P1）
+> Step checkbox 只有验收通过后才能标 done，并随代码 commit；执行细节记 ledger.md。
+
+## Phase 总览
+
+| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
+|---|---|---|---|---|
+| P1 | 读码回填 + 契约层（StepResult.cooldown / WorkerContext.cooldown_until） | 2 | 无 | pending |
+| P2 | 策略迁移 + loop chokepoint 收敛 + 单测 | 3 | P1 | pending |
+| P3 | 等价性冒烟 + 文档收尾 | 2 | P2 | pending |
+
+---
+
+## Phase 1 — 读码回填 + 契约层
+
+**准入条件**：无。
+**完成标准**：SPEC §4 假设 2、3 回填「已读码验证」；契约层单测全绿；既有测试无回归。本 Phase 无运行时行为变化（字段纯加法），不要求冒烟。
+
+### Step 1.1 读码确认（SPEC §4 假设 2、3）
+- 预估：10 min · 依赖：无 · 状态：done（commit 39f3420）
+- 内容：① 读 `fetcher/fetcher/atoms/sleep.py` 全文，把 Sleep/BackoffSleep 的时长分布公式逐字摘出，回填 SPEC §4 假设 2（公式写进 SPEC，迁移要逐字复刻）；② 读 `fetcher/fetcher/strategy/policy.py` 的 `PolicyDecision`/`decide` 与 `control/loop.py:319-395` 的策略消费链路，确认 cooldown 是否需要经 PolicyDecision 透传，回填 SPEC §4 假设 3（若不需要，SPEC §3.1 的 PolicyDecision 字段取消）。
+- 交付物：SPEC 回填 commit；report 附两处读码摘录。
+- 验收：
+  - [x] SPEC §4 假设 2、3 依据列改为「已读码验证（附 file:line）」，结论明确
+
+### Step 1.2 契约层实现 + 单测
+- 预估：15 min · 依赖：1.1 · 状态：done（commit b084129）
+- 内容：`strategy/base.py` 的 `StepResult` 加 `cooldown: float | None = None`（dataclass 纯加法，不动既有三字段语义）；`core/context.py` 的 `WorkerContext` 加 `cooldown_until: dict[str, float]`（field default_factory）；若 Step 1.1 结论是需要，`policy.py` 的 `PolicyDecision` 加透传字段。单测：StepResult 默认值/构造兼容（既有三参数位置构造不破坏）、WorkerContext 新字段初始化。
+- 交付物：代码 + `fetcher/tests/` 新增或并入既有契约测试文件。
+- 验收：
+  - [x] 纯加法：既有构造调用点零改动（grep StepResult( 全部调用点仍编译通过）
+  - [x] 新单测全绿 + 全量无回归（TDD 先红后绿）
+
+---
+
+## Phase 2 — 策略迁移 + chokepoint 收敛
+
+**准入条件**：Phase 1 完成。
+**完成标准**：单测全绿；SPEC §5 第 2、3 条的 grep 验收达成；**运行时冒烟**：直连 `python -m fetcher daemon --db <临时库> --workers 1 --limit 3` 跑通（行为等价冒烟在 Phase 3 做完整版）。
+
+### Step 2.1 策略迁移（Sleep/BackoffSleep/BlockRest）
+- 预估：15 min · 依赖：P1 · 状态：done（commit 3e719d5）
+- 内容：`strategy/strategies.py` 三个策略的 run() 改为「算时长 → StepResult(cooldown=t)」，时长分布按 SPEC §4 假设 2 回填的公式逐字复刻；BlockRest 保留现有 log 行；SwapIPStrategy docstring 加「冷却例外」标注（引用 SPEC §2.2）。attempt 的获取路径按 Step 1.1 核实的现状（BackoffSleep 的 attempt 从哪来就怎么来）。
+- 验收：
+  - [x] 三策略 grep 无 `ctx.wait`；SwapIP 有例外注释
+  - [x] 时长公式与 SPEC 回填公式逐字一致
+
+### Step 2.2 loop chokepoint + 4 处等待点收敛
+- 预估：15 min · 依赖：2.1 · 状态：done（commit df1a925）
+- 内容：`control/loop.py` 新增 `_cooldown(seconds, reason)`（写 ctx.cooldown_until + 保留现状两种等待展示路径）；批次休息/样本间隔/周期长休/启动退避 4 处改经 chokepoint（时长公式逐字保留）；`_process_item` 消费 `step.cooldown`（reason=`f"strategy:{name}"`，中断按现状 stop 路径）。
+- 验收：
+  - [x] loop.py 内 `ctx.wait`/`wait_countdown` 只出现在 `_cooldown` 一处
+  - [x] 4 处等待的时长公式与迁移前逐字一致（diff 对照）
+  - [x] `_process_item` 正确消费 step.cooldown 且中断语义不变
+
+### Step 2.3 迁移单测
+- 预估：15 min · 依赖：2.1、2.2 · 状态：done（commit 9e5b005；策略层用例①②已由 Step 2.1 覆盖，本 Step 做 loop 侧 3 组）
+- 内容：新增 `fetcher/tests/test_cooldown.py`：① 三策略返回 cooldown 在预期区间且自身零等待（断言 run() 返回耗时 ≈0）；② cooldown 分布参数与旧公式一致（采样统计或公式级断言）；③ chokepoint 写 cooldown_until + stop 中断立即返回；④ `_process_item` 策略冷却路径集成测试（仿 test_daemon_task.py 用例 5 的 CrawlLoop 联跑：策略返回 cooldown → loop 执行等待 → 重试 fetch）；⑤ 4 处等待点各触发一次（小参数配置）断言走了 chokepoint（可 monkeypatch 计时）。
+- 验收：
+  - [x] 用例全绿（防假阳性证据：两轮定向破坏）
+  - [x] 全量无回归
+
+---
+
+## Phase 3 — 等价性冒烟 + 文档收尾
+
+**准入条件**：Phase 2 完成。
+**完成标准**：SPEC §5 全部达成。
+
+### Step 3.1 等价性冒烟
+- 预估：15 min（不含跑数时间）· 依赖：P2 · 状态：done（证据见 task-3.1-report.md；SIGTERM 严格场景经用户裁定按单测+运行时证据收口）
+- 内容：临时库预置 6 条 shops pending（生产库只读抄真实店铺），两条路径各跑一遍：① daemon `--db <临时库A> --workers 1 --limit 6 -n 3 --batch-rest 60`；② 旧 CLI `1688 contact` 同参数（临时库B）。对比日志时间戳：样本间隔落在 13~20s+wid 错峰区间、批休落在 60±10%、长休/退避如触发落各自区间。另做一次 stop 中断冒烟：冷却中（批休 60s 窗口）发 SIGTERM，确认秒级中断退出（不等满 60s）。全程 --workers 1、直连、--headed 可选。
+- 交付物：report 含命令、日志时间戳序列表、中断证据、生产库零污染核查。
+- 验收：
+  - [x] SPEC §5 第 4、5 条达成
+  - [x] 冷却中 SIGTERM 立即中断（单元测试锁定 + 两次运行时 ≤11s 退出；严格批休窗口场景用户裁定接受）
+
+### Step 3.2 文档同步 + 终审准备
+- 预估：10 min · 依赖：3.1 · 状态：pending
+- 内容：`docs/scheduler-architecture.md` §10 P1 行标完成；`docs/scheduler-architecture.md` §6 冷却策略表加注「P1 已落地：时长输出+chokepoint，SwapIP 为例外」；fetcher/README.md 如无用户可见变化则不动（确认 daemon 行为描述仍准确）。ledger 补全，终审。
+- 验收：
+  - [ ] 文档更新随代码同 commit
+  - [ ] 全分支终审：旧行为等价（时长公式零变化）经 diff 逐处核实
+
+---
+
+## 冲突扫描（呈交前自查）
+
+**PLAN 内部**：Step 2.1 依赖 Step 1.1 回填的分布公式——若 1.1 发现公式无法干净复刻（如分布依赖原子内部状态），2.1 需上报重议，不擅自改分布。Step 2.3 用例 ④ 的集成测试与 test_daemon_task.py 用例 5 模式重叠——裁定：允许复用基建，但断言目标不同（冷却路径），不算重复覆盖。
+
+**PLAN vs 代码库现状**：
+- `StepResult` 的全部构造调用点：_AtomStrategy.run、SwapIPStrategy.run、WaitHuman* 策略（strategies.py 全文）+ 测试。纯加法字段不破坏位置构造（cooldown 放最后且带默认值）。
+- `wait_countdown`（board.py:134-148）目前仅 loop.py 三处使用；chokepoint 收敛后 board.py 不动（函数保留，调用点变为 chokepoint 内部）。
+- `ctx.wait` 的其他使用者（策略层迁移后剩余：SwapIP、human.py 原子、atoms/ 内部）全部在非目标内保留。
+- `WorkerContext` 的全部构造点（engine.py:149、测试基建）——dataclass 纯加法不破坏。
+- 旧 CLI 路径（1688 contact 等）共享 loop.py/strategies.py——本 P1 改的是共享代码，旧 CLI 行为必须等价，Step 3.1 第 ② 条路径就是为此设的。
+
+**PLAN vs 外部依赖**：无新依赖。等价性冒烟用直连模式，不耗代理资源；本机活爬虫在跑，--workers 1 直连不抢席位之外的资源（直连也占 1 个 CloakBrowser 席位，冒烟短，可接受）。
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md
new file mode 100644
index 0000000..08734c4
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md
@@ -0,0 +1,107 @@
+# SPEC — 冷却策略迁移（P1）
+
+> 上游设计：docs/scheduler-architecture.md（§6 冷却策略表、§10 落地路线 P1）
+> 前置：daemon P0 已合并（docs/archive/feat_2026-08-07_fetcher-daemon-p0/）
+> 本文档是 P1 的需求与设计唯一来源；评审通过后相对稳定，变更在文末「变更记录」追加。
+
+## 1. 背景与目标
+
+P0 把 daemon 骨架立起来了，但所有等待仍内联在执行路径里：loop 4 处、策略层 N 处各自为政，没有统一的「冷却到什么时候」状态可查询——多队列调度器（P3）拿不到冷却截止时间，就无法做「冷却期间去干别的队列」。
+
+**P1 的目标：时长计算策略化 + 等待执行收敛到单一 chokepoint，行为完全等价。**
+
+- 策略不再自己执行冷却等待，改为**输出冷却时长**（`StepResult.cooldown`）；
+- `CrawlLoop` 新增唯一等待执行点 `_cooldown(seconds, reason)`，loop 自身的 4 处等待与策略上报的冷却全部经它执行；
+- 所有时长计算公式**逐字保留**，全部等待保持 stop 可中断；
+- 本阶段**不做**多队列调度、不做 item 挂起/让出——chokepoint 当前实现仍是「就地等待」，但契约（策略只输出时长、loop 唯一执行等待）让 P3 只需替换 chokepoint 实现即可做让出。
+
+验收口径：**同一批次总耗时、请求节奏分布与旧实现相当**（时长公式逐字保留 + 可中断语义保留，结构性保证等价，冒烟对比佐证）。
+
+## 2. 范围与非目标
+
+### 2.1 范围（P1 做）
+
+1. 契约层：`StepResult` 加 `cooldown: float | None` 字段（秒）；`WorkerContext` 加 `cooldown_until: dict[str, float]` 暂存（P3 的状态钩子，本阶段只写不读）。（`PolicyDecision` 不加透传字段，见 §4 假设 3 的读码结论。）
+2. 策略迁移（`strategy/strategies.py`）：`SleepStrategy` / `BackoffSleepStrategy` / `BlockRestStrategy` 的 run() 不再触发 `ctx.wait`，时长算好放进 `StepResult.cooldown` 返回。
+3. loop 收敛（`control/loop.py`）：新增 `_cooldown(seconds, reason)` chokepoint；4 处既有等待点（批次休息 :129-137、样本间隔 :195-200、周期长休 :203-213、启动退避 :243-249）全部改经 chokepoint；`_process_item` 在 `step.cooldown` 非空时调 chokepoint 执行等待。
+4. 单元测试 + 等价性冒烟。
+
+### 2.2 非目标（P1 明确不做）
+
+- **SwapIPStrategy 的内部等待不迁移**（裁定见 §4 假设 1）：它的 600~900s 等待夹在「第一次 relaunch → 等青果轮换 → 第二次 relaunch」算法中间（strategies.py:114-135），外移需要把策略拆成跨 loop 迭代的两阶段状态机，且只有配合 P3 的 item 挂起机制才有收益。P1 保留现状并在代码注释中标注为例外。
+- **WaitHumanVerify/Login 的交互等待**不迁移（轮询人工操作，非冷却）。
+- **SolveSlider 的亚秒 `time.sleep`**（atoms/slider.py，拟人轨迹）不迁移。
+- **Engine 启动错开 sleep**（engine.py:201，主线程启动期行为）不动。
+- 多队列调度、work_items 冷却态、chokepoint 让出实现：P3。
+- `atoms/sleep.py` 的 Sleep/BackoffSleep 原子保留不删（旧路径与其他调用方兼容）。
+- 平台侧、identity 模型、daemon_task.py 均不动。
+
+## 3. 关键设计
+
+### 3.1 契约变更
+
+```python
+# strategy/base.py
+@dataclass
+class StepResult:
+    solved: bool
+    detail: str = ""
+    data: dict = field(default_factory=dict)
+    cooldown: float | None = None   # 秒；非空=调用方（loop）应经 chokepoint 执行该冷却
+```
+
+- 语义：**策略输出冷却、不执行冷却**。`cooldown` 非空时策略保证自己没有为这段时长等待过（调用方执行一次，不重复）。
+- `PolicyDecision`（policy.py:70-77）**不加 cooldown 字段**（§4 假设 3 已读码验证：decide 只输出 action/strategy/attempt/detail，从不接触策略执行结果；`step = strategy.run(ctx)` 只有 loop 消费，cooldown 由 loop 直接取 `step.cooldown`，无需透传）。
+- `WorkerContext.cooldown_until: dict[str, float]`：chokepoint 每次执行等待时写入 `cooldown_until[reason] = time.time() + seconds`。P0/P1 单队列下无人读它，是 P3 调度器的查询接口。
+
+### 3.2 策略迁移（逐个）
+
+| 策略 | 现状 | 迁移后 |
+|---|---|---|
+| `SleepStrategy`（:41） | Sleep 原子内 `ctx.wait(t)`（对数正态时长，params min/max） | run() 用同一分布算出 t，返回 `StepResult(True, cooldown=t)`，不调原子 |
+| `BackoffSleepStrategy`（:46-50） | BackoffSleep 原子 `ctx.wait(min(30*attempt,180))` | run() 算 `min(30*attempt,180)`（attempt 传递路径已读码确认：loop.py:387 `ctx.state["attempt"] = decision.attempt` → 原子读 `ctx.state.get("attempt", 1)`，见 atoms/sleep.py:60），返回 cooldown |
+| `BlockRestStrategy`（:53-67） | run 时取 config block_rest_min/max → Sleep 原子 wait | 时长口径改为策略层内联计算（**注意**：现状经 Sleep 原子是对数正态、clamp 到 `[min*0.5, max*5]`（读码确认，非 `[min,max]`）——迁移时必须保留同一分布，公式逐字复刻依据见 §4 假设 2），返回 cooldown，保留现有 log 行 |
+| `SwapIPStrategy`（:86-135） | 内部 ctx.wait/WaitHumanLogin | **不动**（§2.2 例外），类 docstring 加一行「冷却例外」标注 |
+
+### 3.3 loop chokepoint
+
+```python
+# control/loop.py
+def _cooldown(self, seconds: float, reason: str) -> bool:
+    """唯一等待执行点：登记冷却截止时间 + 可中断等待。返回 True=被 stop 中断。"""
+    self.ctx.cooldown_until[reason] = time.time() + seconds
+    ...  # 现状的 wait_countdown / ctx.wait 逻辑收拢到这里
+```
+
+- 4 处既有等待点改为：算时长（公式逐字保留，含 wid 错峰、±10% 浮动）→ `self._cooldown(t, reason)`。reason 取值：`"batch_rest" / "sample_interval" / "periodic_rest" / "launch_backoff"`；策略冷却的 reason 用 `f"strategy:{strategy.name}"`。
+- `_process_item` 策略执行后：`if step.cooldown: interrupted = self._cooldown(step.cooldown, f"strategy:{...}")`，中断则按现状 stop 路径退出。
+- 倒计时状态行展示（wait_countdown 的 set_status 效果）在 chokepoint 内保留——长等待仍有秒级倒计时，短等待（样本间隔）维持现状的 ctx.wait 即可（读码确认现状哪种等待配哪种展示，逐字保留）。
+
+### 3.4 状态流（职责分配）
+
+- 初始化：`WorkerContext` 创建时 `cooldown_until = {}`（core/context.py，dataclass field）。
+- 写入：唯一写入者是 `_cooldown` chokepoint。
+- 读取：P1 无人读（P3 调度器读）。测试可断言写入正确。
+- 生命周期：进程内存态，随 worker 线程消亡；不落库（P3 若需要再议）。
+
+## 4. 契约与行为后果（假设与验证）
+
+| # | 行为假设 | 依据 | 验证方式 |
+|---|---|---|---|
+| 1 | SwapIP 的内部等待外移需要两阶段状态机，P1 不做的损失可接受 | 已读码验证（主 Agent）：strategies.py:102-135，等待夹在两次 RelaunchBrowser 之间，外移后第二次 relaunch 无人执行会破坏换 IP 语义 | 无需 spike；P3 设计时重议（届时有 item 挂起机制） |
+| 2 | Sleep 原子的时长分布（对数正态 clamp）可以在策略层逐字复刻 | 已读码验证（atoms/sleep.py:21-27 `human_pause_duration`、:36-44 `Sleep.run`、:57-66 `BackoffSleep.run`） | 时长公式逐字摘录（Step 2.1 逐字复刻的唯一依据）：**Sleep**：`lo = float(params.get("min", 2.0))`、`hi = float(params.get("max", 5.0))`，调 `human_pause_duration(lo, hi)`——`lo >= hi` 时返回 `float(lo)`（固定等待）；否则 `median = (lo + hi) / 2`，`t = random.lognormvariate(math.log(median), 0.5)`（随机源：stdlib `random` 模块级实例，对数正态，mu=ln(中位数)、sigma=0.5），clamp `max(lo * 0.5, min(t, hi * 5))`（下限 lo*0.5、上限 hi*5）。**BackoffSleep**：`base = float(params.get("base", 30.0))`、`cap = float(params.get("cap", 180.0))`、`attempt = params.get("attempt") or ctx.state.get("attempt", 1)`，`t = min(base * int(attempt), cap)`（纯线性退避，无随机）。原子内等待调用形式：`interrupted = ctx.wait(t)`，中断返回 `ActionResult(Outcome.SKIPPED, ...)`，否则 `ActionResult.success(..., seconds=t)`。测试断言样本落在 clamp 区间且分布参数一致 |
+| 3 | decide/PolicyDecision 链路不需要 cooldown 字段（loop 直接消费 step.cooldown） | 已读码验证（policy.py:70-77 PolicyDecision 仅 action/strategy/attempt/detail 四字段；decide :156-194 只做链推进决策，从不接触策略执行结果；loop.py:386-394 `step = strategy.run(ctx)` 的返回值只有 `_process_item` 自己消费） | 已验证：不需要透传，loop 直接消费 step.cooldown。§3.1 的 PolicyDecision 字段已取消 |
+| 4 | 迁移后 loop 的等待展示行为（倒计时状态行）不回归 | 现状：wait_countdown 仅 loop 三处使用（board.py:134-148） | chokepoint 实现保留两种展示路径；冒烟观察状态行 |
+| 5 | ctx.wait / wait_countdown 的 stop 可中断语义经 chokepoint 后不变 | 已读码验证：ctx.wait=stop.wait(timeout)（context.py:127-129），wait_countdown 循环 stop.wait(min(1,remain))（board.py:147） | 单测：冷却中置 stop → 立即中断返回 |
+
+## 5. 验收标准（P1 整体）
+
+1. `cd fetcher && python -m pytest tests -x -q` 全绿（含新增：策略 cooldown 输出、chokepoint 中断、时长边界）。
+2. 策略层不再有任何 `ctx.wait` 调用（Sleep/BackoffSleep/BlockRest 三个策略 grep 为零；SwapIP 例外有注释标注）。
+3. loop.py 的等待执行只出现在 `_cooldown` 内（grep `ctx.wait\|wait_countdown` 在 loop.py 仅 chokepoint 一处）。
+4. 等价性冒烟：直连 `python -m fetcher daemon --db <临时库> --workers 1 --limit 6 -n 3 --batch-rest 60`（小批次强制触发批休+样本间隔+长休路径），日志时间戳序列与旧实现同参数对比，节奏模式一致（间隔落在相同时长区间）；stop 中断等待的行为冒烟一次。
+5. 等价性冒烟：旧 CLI `1688 contact` 同参数跑一遍（同一临时库口径），确认非 daemon 路径也不回归。
+
+## 6. 变更记录
+
+（空——评审后变更在此追加）
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/ledger.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/ledger.md
new file mode 100644
index 0000000..f948601
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/ledger.md
@@ -0,0 +1,31 @@
+# SDD ledger — plan: docs/feat_2026-08-07_fetcher-cooldown-p1/PLAN.md
+
+- 分支：feat/fetcher-cooldown-p1（base main 3847934）
+- 环境偏差记录：本环境 Agent 工具无模型选择参数，implementer/reviewer 均用默认 coder 类型派发。
+
+## Step 进度
+
+（尚无完成记录）
+- Step 1.1: complete (commits 71bde8f..39f3420, review clean)
+  - 关键产出：Sleep 分布公式逐字回填（lognormvariate(ln((lo+hi)/2), 0.5)，clamp [lo*0.5, hi*5]）；SPEC §3.2 先验错误（clamp [min,max]）已更正；PolicyDecision 确认免透传
+  - Step 1.1: minor (deferred): report 内一处行号引用偏一行（:37-38 实为 :37-39），SPEC 正文无误
+- Step 1.2: complete (commits 635b170..b084129, review clean)
+  - Step 1.2: minor (deferred): report 行数计数误差（+5 实为 +4）；StepResult docstring 未提 cooldown 字段（行内注释已足够）
+- Step 2.1: complete (commits 23044ed..3e719d5, review clean)
+  - 实现要点：时长 import 复用 human_pause_duration（atoms/sleep.py），BackoffSleep 逐字复刻含 or 短路；三策略脱离 _AtomStrategy；注册表/调用方咬合经 review 核实
+  - Step 2.1: minor (deferred): BlockRestStrategy.__init__ 留存 self._params 但 run() 不读（惯性残留，Step 2.2 可顺手清理）
+  - Step 2.1: minor (deferred): 中间态下 Sleep 的「随机等待」日志先于实际等待打出（Step 2.2 接上后自洽）
+- Step 2.2: complete (commits 9f0f403..df1a925, review clean)
+  - 实现要点：_cooldown(seconds, reason, prefix=None)；中断终局与旧路径逐字同值（return "stop",0 → _cleanup）；BlockRestStrategy 死字段已清理
+  - Step 2.2: minor (deferred): ✓ 策略完成日志时序变化（先打 ✓ 再冷却；中断时 ✓ 会打出，旧路径不打）——终审分诊是否一行对齐
+  - Step 2.2: minor (deferred): cooldown=0.0 会跳过登记与等待（现状无此值，仅记录）
+  - Step 2.2: 记录（非问题）: 中断时 cooldown_until 残留未来时间戳，P3 按「过期即无效」消费即可
+- Step 2.3: complete (commits 44e4c49..9e5b005, review clean)
+  - Step 2.3: minor (deferred): deadline 断言容差 1s 相对小 seconds 偏宽（破坏 A 已锁「完全不写」，spy seconds 透传锁「算错」）
+  - Step 2.3: minor (deferred): 组③未断言 spy 无意外 reason；:381 elapsed 下界有理论时序抖动空间
+- Step 3.1: 首次派发（agent-30）中途失联——B/C/D 段据其 todo 记录已跑完，但 /tmp 证据文件与 report 全部丢失，子 Agent 实例已不存在。裁定：Step 3.1 整体重跑（走查 Step 不接受口头声明），要求新 implementer 证据随跑随写 report、日志文件放 plan 目录下 docs/feat_2026-08-07_fetcher-cooldown-p1/smoke/ 而非 /tmp。
+- Step 3.1: complete（走查 Step，无代码 commit；证据 task-3.1-report.md + smoke/ 日志，主 Agent 亲自收尾 E/F 段并核实）
+  - 首次派发 agent-30 失联证据全丢 → 重跑 agent-31（超时 2h，证据随跑随写保住）→ 用户裁定滑块环境打住，主 Agent 收尾
+  - 等价性结论：daemon vs 旧 CLI 三档间隔同区间（样本 12/12 vs 16/15s、长休 21/23 vs 22/27s、批休 66 vs 67s 几乎逐秒一致），SPEC §5 第 4、5 条达成
+  - SIGTERM 严格批休窗口场景未完成（滑块墙环境），单元测试（30s 冷却 0.1s 打断 <5s 退出）+ 两次运行时 SIGTERM ≤11s 佐证，用户裁定接受
+  - 生产库零污染硬证据：ip_events/ip_stats MAX 时间戳（17:29/17:38）早于冒烟开始（20:24）
diff --git a/docs/scheduler-architecture.md b/docs/scheduler-architecture.md
index 9fad83b..fc05d1f 100644
--- a/docs/scheduler-architecture.md
+++ b/docs/scheduler-architecture.md
@@ -149,20 +149,22 @@ def consumer_loop(consumer):
 |---|---|---|
 | 样本间隔 13~20s（按 worker 错峰） | `loop.py:194-200` | outcome=ok → 冷却 uniform(sample_min, sample_max)，错峰由多消费者天然成立 |
 | 批休 900s±10% | `loop.py:123-141` | 批次计数满 n → 冷却 uniform(810, 990) |
 | 周期长休 60~180s / 20 个 | `loop.py:203-213` | 计数器触发 → 冷却 uniform(60,180) |
 | 风控原地休息 600~900s | `strategies.py:53-67` | outcome=blocked → 冷却 uniform(600,900)（保 IP 冷却语义） |
 | 换 IP 等轮换 600~900s | `strategies.py:114-129` | 换 IP 原子执行后出口未轮换 → 冷却对应时长 |
 | 网络错误退避 30~180s | `strategies.py:47-50` | outcome=net_error → min(30×attempt, 180) |
 | 页面渲染等待 2~5s | 站点插件内 `time.sleep` | 保留在原子内（属于执行过程，非调度间隔） |
 | worker 启动错开 15~60s | `engine.py:198-201` | 消费者启动时一次性冷却 |
 
+注：P1 已落地——Sleep/BackoffSleep/BlockRest 改为输出 StepResult.cooldown、loop 4 处等待收敛至 `_cooldown` chokepoint（control/loop.py）；SwapIP 内部等待为例外未迁移（P3 重议）。
+
 - 所有冷却参数进配置（站点插件声明默认值，平台可覆盖），单位统一秒。
 - 请求预算（如 60 页/IP）保持按 (IP, site) 记账，达预算 → 触发换 IP 原子 + 长冷却，与现状一致。
 
 ## 7. identity 改造（(IP) → (IP, site)）
 
 改动点：
 
 - `Session.identity` 增加 site 维度：实际键为 `f"{site}:{ip}"`（直连为 `f"{site}:direct"`）。`core/session.py` 注释与默认值同步更新。
 - `IdentityStore`（`net/identity.py`）：load/save/burn 全部带 site 键；burn 只烧对应站点的 Cookie，不殃及同 IP 其他站点。
 - 风控簿记（`loop.py:399-446` 的 ip_req/ip_stats/ip_events）：表加 site 列或键拼 site 前缀（走 `app.db.migrate()` 幂等迁移，防御性探测）。
@@ -199,21 +201,21 @@ CREATE INDEX idx_work_items_claim ON work_items(queue, status, id);
 - runner 新增 daemon 管理：`start.sh` 拉起 `python -m fetcher daemon`（常驻，与 uvicorn 同级），停止/重启走 pidfile；daemon 输出行泵入 `task_events` 的机制沿用。
 - `TASK_COMMANDS` 中浏览器采集类任务从「拼 CLI 起子进程」改为「INSERT work_items 批次」；API 类/本地类同理。wa_check 从 runner 进程内线程迁入 dispatcher 的 LocalExecutor。
 - API 变更：`POST /api/tasks` 创建批次；`GET /api/tasks/{id}` 进度响应增加 `queue` 维度统计与消费者分配情况；新增 `GET /api/dispatcher/consumers`（消费者列表：通道、当前工作项、各站点冷却剩余）用于前端看板。
 - 前端（另按 DESIGN.md 实施）：批次详情页展示工作项队列进度；新增消费者看板（每通道当前在干什么、各站点冷却倒计时——正好复用 flow-architecture §8 的 Sleep 环形进度设计）。
 
 ## 10. 落地路线
 
 | 阶段 | 内容 | 验收 |
 |---|---|---|
 | P0 daemon 骨架 | work_items 表 + Dispatcher + 条件变量调度循环 + BrowserConsumer（单站点 1688）；CLI 新增 `daemon` 子命令 | 单站点行为与现有 CLI 等价（节奏、产出、事件口径一致）；✅ 已完成（2026-08-07，实施记录 docs/archive/feat_2026-08-07_fetcher-daemon-p0/） |
-| P1 冷却策略迁移 | `strategies.py` 的 sleep 全部改为输出冷却时长；`loop.py` 流水线原子化改造 | 同一批次总耗时、请求节奏分布与旧实现相当 |
+| P1 冷却策略迁移 | `strategies.py` 的 sleep 全部改为输出冷却时长；`loop.py` 流水线原子化改造 | 同一批次总耗时、请求节奏分布与旧实现相当；✅ 已完成（2026-08-08，实施记录 docs/feat_2026-08-07_fetcher-cooldown-p1/） |
 | P2 identity 分桶 | (IP,site) 键改造 + BrowserContext 隔离 + 簿记表迁移 | 同 IP 两站点 Cookie/簿记互不污染（单测覆盖） |
 | P3 第二站点接入 | madeinchina 队列接入，跨站填充生效 | 同通道 madeinchina 冷却期间执行 1688 工作项，两边各自预算不超标 |
 | P4 平台切换 | runner 改批次提交、wa_check 迁入、API + 前端看板 | 平台创建/停止/监控全流程走 dispatcher |
 | P5 退役旧路径 | 旧 subprocess 采集路径冻结→删除；修订 flow-architecture.md §2/§10 | 旧代码路径删除，文档同步 |
 
 每个阶段独立可回滚：P0~P3 期间旧 CLI 路径保持可用，灰度对比等价后再切。
 
 ## 11. 明确的非目标（v1 不做）
 
 - 多 dispatcher 分布式部署（单机单 dispatcher；DB 租约字段预留）
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index e898d57..a214e94 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -16,20 +16,21 @@ item 级重试循环 → 收尾清理），但风控状态机不再写死在控
     - SeedBurnTracker：首请求秒拦/登录墙记到种子头上，烧毁后
       session.seed_kit=None，后续重启按白板会话；
     - 网络层错误（NET_ERROR/BROWSER_DEAD/IP_ROTATED）不计入熔断；
     - 熔断按店计（每店首个风控类失败计 1），同一店的重试链不累计，
       防单个慢/卡店铺中止整个任务。
 """
 
 from __future__ import annotations
 
 import random
+import time
 
 from fetcher.atoms.browser_ops import RelaunchBrowser
 from fetcher.control.board import wait_countdown
 from fetcher.control.circuit import CircuitBreaker
 from fetcher.control.task import Task
 from fetcher.core.errors import UserInterrupted
 from fetcher.core.session import Session
 from fetcher.core.types import Outcome, Scenario
 from fetcher.detect.base import SceneInspector
 from fetcher.net.seeds import SeedBurnTracker
@@ -95,20 +96,37 @@ class CrawlLoop:
 
     # ---- 日志 / 状态行 ----
 
     @property
     def tag(self) -> str:
         return f"[w{self.ctx.wid}]"
 
     def log(self, msg: str):
         self.ctx.log(f"{self.tag} {msg}")
 
+    # ---- 冷却 chokepoint（SPEC §3.3：唯一等待执行点）----
+
+    def _cooldown(self, seconds: float, reason: str,
+                  prefix: str | None = None) -> bool:
+        """登记冷却截止时间 + 执行可中断等待。返回 True=被 stop 中断。
+
+        cooldown_until 的唯一写入者（P1 只写不读，P3 调度器查询接口）。
+        展示两路径逐字保留现状：prefix 非空走 wait_countdown（秒级倒计
+        时状态行，长等待用）；prefix=None 走 ctx.wait（静默，短等待用）。
+        """
+        self.ctx.cooldown_until[reason] = time.time() + seconds
+        if prefix is None:
+            return self.ctx.wait(seconds)
+        return wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
+                              seconds, prefix,
+                              set_status=self.ctx.set_status)
+
     # ---- 主流程 ----
 
     def run(self) -> dict:
         """worker 完整生命周期；返回本 worker 的统计字典。"""
         cfg = self.ctx.config
         self.ctx.state["warm"] = True  # 新会话冷启动软着陆标记
         try:
             self.ctx.set_status(state="启动浏览器…", force=True)
             self._launch_with_retry()
             self.log(f"浏览器就绪，出口 IP={self.ctx.identity}"
@@ -124,23 +142,21 @@ class CrawlLoop:
                     if cfg.max_batches and self.batch_no >= cfg.max_batches:
                         self.log(f"第 {self.batch_no} 批采满，"
                                  f"已达批次上限（--max-batches），收工")
                         self.ctx.set_status(state="收工")
                         return self.stats
                     rest = random.uniform(cfg.batch_rest * 0.9,
                                           cfg.batch_rest * 1.1)
                     self.log(f"⏸ 第 {self.batch_no} 批已采满 "
                              f"{cfg.batch_num} 个{self.task.batch_unit}，"
                              f"强制休息 {rest / 60:.1f} 分钟（防风控）...")
-                    if wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
-                                      rest, "批次休息",
-                                      set_status=self.ctx.set_status):
+                    if self._cooldown(rest, "batch_rest", prefix="批次休息"):
                         return self.stats
                     self.batch_no += 1
                     self.done_in_batch = 0
                     self.log(f"▶ 休息结束，开始第 {self.batch_no} 批")
                     self.ctx.set_status(batch=self.batch_no, state="采集中")
 
                 # ---- 冷启动（acquire 前的任务，如先逛首页填类目池）----
                 if self.task.cold_start_before_acquire and self._take_warm():
                     self.ctx.set_status(state="冷启动软着陆…")
                     self.task.cold_start(self.ctx, None)
@@ -189,34 +205,32 @@ class CrawlLoop:
                 if cfg.limit and self.total_done >= cfg.limit:
                     self.log(f"已达本次采集上限（--limit {cfg.limit}），收工")
                     self.ctx.set_status(state="收工")
                     return self.stats
 
                 # ---- 样本间隔（按 worker 编号递增错峰，避免集群同频）----
                 lo = cfg.sample_min + self.ctx.wid * 1.5
                 hi = cfg.sample_max + self.ctx.wid * 2.5
                 t = random.uniform(lo, hi)
                 self.ctx.set_status(state=f"{self.task.unit}间隔 {t:.1f}s")
-                if self.ctx.wait(t):
+                if self._cooldown(t, "sample_interval"):
                     return self.stats
 
                 # ---- 周期性随机长休息（模拟真人连续浏览后的停顿）----
                 n_rest = self.task.rest_counter(self.stats)
                 if (cfg.rest_every > 0 and n_rest > 0
                         and n_rest % cfg.rest_every == 0
                         and not self.ctx.stopped()):
                     t = random.uniform(cfg.rest_min, cfg.rest_max)
                     self.log(f"☕ 已连续抓取 {n_rest} 个{self.task.unit}，"
                              f"随机长休息 {t / 60:.1f} 分钟 ...")
-                    if wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
-                                      t, "长休息",
-                                      set_status=self.ctx.set_status):
+                    if self._cooldown(t, "periodic_rest", prefix="长休息"):
                         return self.stats
         except UserInterrupted:
             pass
         except Exception as e:  # noqa: BLE001
             self.log(f"[X] worker 异常退出: {e}")
         finally:
             self._cleanup()
         return self.stats
 
     # ---- 启动 / 收尾 ----
@@ -236,23 +250,21 @@ class CrawlLoop:
                     seed_kit=self.seed_tracker.kit, stop=self.ctx.stop)
                 self.seed_tracker.kit = self.ctx.session.seed_kit
                 return
             except UserInterrupted:
                 raise
             except (Exception, SystemExit) as e:  # noqa: BLE001
                 last_err = e
                 backoff = min(30 * attempt, 120)
                 self.log(f"  [!] 启动浏览器第 {attempt}/{cfg.ip_retry} "
                          f"次失败: {e}，{backoff}s 后重试...")
-                if wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
-                                  backoff, "启动退避",
-                                  set_status=self.ctx.set_status):
+                if self._cooldown(backoff, "launch_backoff", prefix="启动退避"):
                     raise UserInterrupted("用户中断") from e
         raise RuntimeError(f"启动浏览器重试 {cfg.ip_retry} 次仍失败: {last_err}")
 
     def _cleanup(self):
         """退出前回写 Cookie、关浏览器（任何路径都走这里）。"""
         session = self.ctx.session
         if session is not None:
             session.close(store=self.ctx.store, log=self.ctx.log)
             self.ctx.session.browser = None
         self.ctx.set_status(state="已退出", force=True)
@@ -385,20 +397,26 @@ class CrawlLoop:
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
+            # 策略冷却经 chokepoint 执行（Step 2.1 起策略只算时长不自
+            # 等）；被 stop 中断按现状 stop 路径退出（与旧策略内
+            # ctx.wait 中断 → 循环条件退出 → return "stop" 的终局一致）
+            if step.cooldown and self._cooldown(
+                    step.cooldown, f"strategy:{decision.strategy}"):
+                return "stop", 0
         return "stop", 0
 
     # ---- 簿记 ----
 
     def _bookkeep_request(self, scenario: Scenario):
         """tmd 计数：请求到了目标站才计（网络层错误不算）。"""
         if scenario in _NO_REQUEST_SCENARIOS or self.ctx.store is None:
             return
         identity = self.ctx.identity
         ctr = self.ip_req.setdefault(identity, {"n": 0, "since": 0})
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
diff --git a/fetcher/fetcher/strategy/strategies.py b/fetcher/fetcher/strategy/strategies.py
index 67e5e6c..7290fd7 100644
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
@@ -31,47 +31,77 @@ class _AtomStrategy:
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
 
-class BlockRestStrategy(_AtomStrategy):
+    def run(self, ctx) -> StepResult:
+        base = float(self._params.get("base", 30.0))
+        cap = float(self._params.get("cap", 180.0))
+        attempt = self._params.get("attempt") or ctx.state.get("attempt", 1)
+        t = min(base * int(attempt), cap)
+        ctx.log(f"    ...退避等待 {t:.0f}s（第 {attempt} 次）")
+        return StepResult(True, f"退避 {t:.0f}s", cooldown=t)
+
+
+class BlockRestStrategy:
     """风控原地休息：当前 IP 上长休息后再试（block_rest_min~max）。
 
-    时长在 run 时从 ctx.config 取，保证任务级覆盖生效。
+    时长在 run 时从 ctx.config 取，保证任务级覆盖生效；分布与 Sleep
+    同款（对数正态）。只算时长输出冷却，不自己等待（等待由控制层执行）。
     """
+
     name = "block_rest"
-    atom_cls = Sleep
 
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
@@ -79,20 +109,22 @@ class SolveSliderStrategy(_AtomStrategy):
 
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
 
diff --git a/fetcher/tests/test_cooldown.py b/fetcher/tests/test_cooldown.py
new file mode 100644
index 0000000..287ff1a
--- /dev/null
+++ b/fetcher/tests/test_cooldown.py
@@ -0,0 +1,383 @@
+# -*- coding: utf-8 -*-
+"""冷却 chokepoint（CrawlLoop._cooldown）loop 侧单测（P1 Step 2.3）。
+
+三组用例：
+1. chokepoint 单测：cooldown_until 写入（≈ time.time()+seconds）、
+   正常路径返回 False、等待期间 stop 立即返回 True（远小于 seconds）；
+   静默（prefix=None → ctx.wait）与倒计时（prefix 传 → wait_countdown）
+   两条展示路径各覆盖一次。
+2. _process_item 策略冷却集成：CrawlLoop 联跑——假 task 首次 fetch
+   自报 blocked、假策略输出 StepResult(cooldown=t)，断言冷却经
+   chokepoint 执行（spy 记录参数、调用真实实现）、随后重试成功；
+   再覆盖「冷却中被 stop 中断 → return "stop" 终局」分支。
+3. 4 处等待点（batch_rest / sample_interval / periodic_rest /
+   launch_backoff）均经 chokepoint 触发，reason 正确且时长落在公式区间。
+
+真实 threading.Event + 临时 sqlite + spy（不 mock 被测的 _cooldown
+本身）；假基建模式参照 test_control_loop.py / test_daemon_task.py。
+"""
+
+import tempfile
+import threading
+import time
+import unittest
+from pathlib import Path
+
+from fetcher import (
+    Alibaba1688Plugin,
+    IdentityStore,
+    RunConfig,
+    Scenario,
+    Session,
+    ShopDB,
+    WorkerContext,
+)
+from fetcher.control import CrawlLoop, Task
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.strategy.base import StepResult
+from fetcher.strategy.policy import Policy
+
+
+# ---------- mock 基础设施（模式同 test_control_loop.py） ----------
+
+class FakeBrowser:
+    def is_connected(self):
+        return True
+
+    def close(self):
+        pass
+
+
+class FakeContext:
+    def __init__(self):
+        self.browser = FakeBrowser()
+
+    def cookies(self):
+        return []
+
+
+class FakePage:
+    def __init__(self):
+        self.url = "https://shop123.1688.com/page/contactinfo.htm"
+        self._text = "正常页面文本，足够长，包含电话、手机、地址等字段标签，超过阈值。"
+        self.frames = []
+        self.context = FakeContext()
+
+    def evaluate(self, js):
+        return self._text
+
+    def query_selector(self, sel):
+        return None
+
+    def is_closed(self):
+        return False
+
+
+class MockBrowserManager:
+    """launch 返回带假 page 的 Session；fail_launch=True 时恒抛错。"""
+
+    def __init__(self, page, fail_launch=False):
+        self.page = page
+        self.fail_launch = fail_launch
+        self.launch_count = 0
+
+    def launch(self, seed_kit=None, stop=None):
+        self.launch_count += 1
+        if self.fail_launch:
+            raise RuntimeError("launch boom")
+        return Session(browser=FakeBrowser(), page=self.page,
+                       identity="1.1.1.1", seed_kit=seed_kit)
+
+    def check_ip_fresh(self, session):
+        return False, session.identity, ""
+
+    def save_cookies(self, session):
+        return 0
+
+
+class ScriptedTask(Task):
+    """可编程任务：fetch 按 script 逐条出账（只用到 ok / blocked）。
+
+    rest_counter 以 stats["done"] 为基准（供 periodic_rest 触发）。
+    """
+
+    name = "scripted"
+
+    def __init__(self, script=(), items=("item1",)):
+        self.script = list(script)
+        self.items = list(items)
+        self.fetches = 0
+        self.succeeded = []
+        self.given_up = []
+
+    def acquire_item(self, ctx):
+        return self.items.pop(0) if self.items else None
+
+    def fetch(self, ctx, item):
+        self.fetches += 1
+        step = self.script.pop(0) if self.script else ("ok", {"v": 1})
+        if step[0] == "ok":
+            return ActionResult(Outcome.OK, "", step[1])
+        if step[0] == "blocked":
+            return ActionResult.blocked(step[1])
+        raise ValueError(step[0])
+
+    def on_success(self, ctx, item, result):
+        self.succeeded.append(item)
+        stats = ctx.state["task"]["stats"]
+        stats["done"] = stats.get("done", 0) + 1
+        return 1
+
+    def on_giveup(self, ctx, item, reason, kind):
+        self.given_up.append((item, kind))
+        return "标记跳过"
+
+    def make_stats(self):
+        return {"done": 0}
+
+    def rest_counter(self, stats):
+        return stats.get("done", 0)
+
+
+class CooldownStrategy:
+    """假策略：只输出 cooldown（Step 2.1 起策略不自等）。"""
+
+    def __init__(self, cooldown, solved=False):
+        self.cooldown = cooldown
+        self.solved = solved
+        self.calls = 0
+
+    def run(self, ctx):
+        self.calls += 1
+        return StepResult(self.solved, f"cool#{self.calls}",
+                          cooldown=self.cooldown)
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
+def make_ctx(config, mgr, stop=None):
+    store = IdentityStore(ShopDB(config.resolved_db_path()))
+    return WorkerContext(config=config, store=store, browser_manager=mgr,
+                         site=Alibaba1688Plugin(),
+                         stop=stop or threading.Event(),
+                         log=lambda m: None)
+
+
+def spy_cooldown(loop):
+    """spy _cooldown：记录 (seconds, reason, prefix)，调用真实实现。"""
+    calls = []
+    orig = loop._cooldown
+
+    def spy(seconds, reason, prefix=None):
+        calls.append((seconds, reason, prefix))
+        return orig(seconds, reason, prefix)
+
+    loop._cooldown = spy
+    return calls
+
+
+class CooldownTestBase(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.tmp = self._tmp.name
+        self.page = FakePage()
+        self.mgr = MockBrowserManager(self.page)
+
+    def tearDown(self):
+        self._tmp.cleanup()
+
+    def make_loop(self, task=None, table=None, strategies=None, **cfg_kw):
+        config = make_config(self.tmp, **cfg_kw)
+        ctx = make_ctx(config, self.mgr)
+        policy = Policy(table=table or {}, strategies=strategies or {},
+                        max_consecutive_fail=config.max_consecutive_fail)
+        loop = CrawlLoop(ctx, task or ScriptedTask(), policy=policy)
+        return loop, ctx
+
+
+# ---------- 用例 1：chokepoint 单测 ----------
+
+class CooldownChokepointTest(CooldownTestBase):
+    def test_silent_path_writes_deadline_and_returns_false(self):
+        """静默路径（prefix=None → ctx.wait）：写入 cooldown_until[reason]
+        ≈ time.time()+seconds，正常等完返回 False。"""
+        loop, ctx = self.make_loop()
+        t0 = time.time()
+        interrupted = loop._cooldown(0.05, "ut_silent")
+        self.assertFalse(interrupted)
+        # 唯一写入者语义：只写了这一个 reason，值 ≈ 调用时刻 + seconds
+        self.assertEqual(set(ctx.cooldown_until), {"ut_silent"})
+        self.assertAlmostEqual(ctx.cooldown_until["ut_silent"], t0 + 0.05,
+                               delta=1.0)
+
+    def test_countdown_path_stop_interrupt_returns_true_fast(self):
+        """倒计时路径（prefix 传 → wait_countdown）：等待期间置 stop
+        立即返回 True（远小于 seconds），cooldown_until 同样登记。"""
+        loop, ctx = self.make_loop()
+        threading.Timer(0.1, ctx.stop.set).start()
+        t0 = time.monotonic()
+        interrupted = loop._cooldown(30.0, "ut_countdown", prefix="倒计时")
+        elapsed = time.monotonic() - t0
+        self.assertTrue(interrupted)
+        self.assertLess(elapsed, 5.0)  # 远小于 30s：确实被 stop 打断
+        self.assertGreaterEqual(elapsed, 0.05)  # 非「立即返回」的快路径
+        self.assertAlmostEqual(ctx.cooldown_until["ut_countdown"],
+                               time.time() + 30.0, delta=1.0)
+
+
+# ---------- 用例 2：_process_item 策略冷却集成 ----------
+
+class StrategyCooldownIntegrationTest(CooldownTestBase):
+    TABLE = {Scenario.RISK_SLIDER_PAGE: [("cool", 1), ("give_up", None)]}
+
+    def test_strategy_cooldown_via_chokepoint_then_retry_success(self):
+        """首次 fetch 自报 blocked → 策略输出 cooldown=0.3 → loop 经
+        chokepoint 真实等待后重试 fetch → 成功收尾。"""
+        strategy = CooldownStrategy(cooldown=0.3, solved=True)
+        task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1})])
+        loop, ctx = self.make_loop(task, self.TABLE, {"cool": strategy})
+        calls = spy_cooldown(loop)
+
+        t0 = time.monotonic()
+        loop.run()
+        elapsed = time.monotonic() - t0
+
+        # 重试发生且终态正确
+        self.assertEqual(task.fetches, 2)
+        self.assertEqual(task.succeeded, ["item1"])
+        self.assertEqual(task.given_up, [])
+        # 冷却经 chokepoint：spy 记录 reason=f"strategy:cool"、秒数原样透传
+        strat_calls = [c for c in calls if c[1] == "strategy:cool"]
+        self.assertEqual(len(strat_calls), 1)
+        seconds, _reason, prefix = strat_calls[0]
+        self.assertAlmostEqual(seconds, 0.3, delta=1e-6)
+        self.assertIsNone(prefix)  # 策略冷却走静默路径
+        # 真实等待过（spy 调的是真实实现）
+        self.assertGreaterEqual(elapsed, 0.25)
+        # cooldown_until 已登记，值 ≈ 写入时刻 + seconds
+        # （run 结束可能已过截止点，用宽容差而非「在未来」断言）
+        self.assertAlmostEqual(ctx.cooldown_until["strategy:cool"],
+                               time.time() + 0.3, delta=1.0)
+
+    def test_strategy_cooldown_interrupted_by_stop_is_stop_terminal(self):
+        """冷却中被 stop 中断 → _process_item return "stop" 终局：
+        当前 item 不放弃、后续 item 不再认领，loop 快速退出。"""
+        strategy = CooldownStrategy(cooldown=30.0)
+        task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1}),
+                             ("ok", {"v": 2})], items=("item1", "item2"))
+        stop = threading.Event()
+        config = make_config(self.tmp)
+        ctx = make_ctx(config, self.mgr, stop=stop)
+        policy = Policy(table=self.TABLE, strategies={"cool": strategy},
+                        max_consecutive_fail=config.max_consecutive_fail)
+        loop = CrawlLoop(ctx, task, policy=policy)
+        calls = spy_cooldown(loop)
+
+        threading.Timer(0.15, stop.set).start()
+        t0 = time.monotonic()
+        loop.run()
+        elapsed = time.monotonic() - t0
+
+        # 被 stop 打断而非等满 30s
+        self.assertLess(elapsed, 5.0)
+        self.assertTrue(stop.is_set())
+        # "stop" 终局：item1 未成功也未放弃，item2 未被认领（fetch 只 1 次）
+        self.assertEqual(task.fetches, 1)
+        self.assertEqual(task.succeeded, [])
+        self.assertEqual(task.given_up, [])
+        strat_calls = [c for c in calls if c[1] == "strategy:cool"]
+        self.assertEqual(len(strat_calls), 1)
+        self.assertAlmostEqual(strat_calls[0][0], 30.0, delta=1e-6)
+
+
+# ---------- 用例 3：4 处等待点触发 ----------
+
+class WaitPointsTest(CooldownTestBase):
+    def test_batch_sample_periodic_rest_via_chokepoint(self):
+        """小参数联跑：batch_rest / sample_interval / periodic_rest 均经
+        chokepoint 触发，reason 正确、时长落在公式区间、prefix 符合现状。"""
+        task = ScriptedTask(items=("item1", "item2"))
+        cfg = dict(batch_num=1, max_batches=2, batch_rest=0.2,
+                   sample_min=0.05, sample_max=0.10,
+                   rest_every=1, rest_min=0.06, rest_max=0.12)
+        loop, ctx = self.make_loop(task, **cfg)
+        calls = spy_cooldown(loop)
+
+        stats = loop.run()
+
+        self.assertEqual(task.succeeded, ["item1", "item2"])
+        self.assertEqual(stats["done"], 2)
+
+        by_reason = {}
+        for seconds, reason, prefix in calls:
+            by_reason.setdefault(reason, []).append((seconds, prefix))
+
+        # 三处等待点全部经 chokepoint
+        self.assertIn("batch_rest", by_reason)
+        self.assertIn("sample_interval", by_reason)
+        self.assertIn("periodic_rest", by_reason)
+
+        # batch_rest：±10% 抖动区间，倒计时路径（prefix="批次休息"）
+        self.assertEqual(len(by_reason["batch_rest"]), 1)  # max_batches=2 → 1 次
+        seconds, prefix = by_reason["batch_rest"][0]
+        self.assertGreaterEqual(seconds, 0.2 * 0.9)
+        self.assertLessEqual(seconds, 0.2 * 1.1)
+        self.assertEqual(prefix, "批次休息")
+
+        # sample_interval：wid=0 → [sample_min, sample_max]，静默路径
+        self.assertEqual(len(by_reason["sample_interval"]), 2)  # 每个 item 一次
+        for seconds, prefix in by_reason["sample_interval"]:
+            self.assertGreaterEqual(seconds, 0.05)
+            self.assertLessEqual(seconds, 0.10)
+            self.assertIsNone(prefix)
+
+        # periodic_rest：rest_every=1 → 每个 item 一次，[rest_min, rest_max]
+        self.assertEqual(len(by_reason["periodic_rest"]), 2)
+        for seconds, prefix in by_reason["periodic_rest"]:
+            self.assertGreaterEqual(seconds, 0.06)
+            self.assertLessEqual(seconds, 0.12)
+            self.assertEqual(prefix, "长休息")
+
+        # cooldown_until 三类 reason 均登记（唯一写入者语义）
+        for reason in ("batch_rest", "sample_interval", "periodic_rest"):
+            self.assertIn(reason, ctx.cooldown_until)
+
+    def test_launch_backoff_via_chokepoint(self):
+        """启动退避：首次 launch 失败 → _cooldown(backoff, "launch_backoff",
+        prefix="启动退避")，backoff=min(30*attempt,120)=30s；stop 中断后
+        按 UserInterrupted 路径快速退出（不等满 30s）。"""
+        self.mgr = MockBrowserManager(self.page, fail_launch=True)
+        stop = threading.Event()
+        config = make_config(self.tmp, ip_retry=2)
+        ctx = make_ctx(config, self.mgr, stop=stop)
+        policy = Policy(table={}, strategies={},
+                        max_consecutive_fail=config.max_consecutive_fail)
+        loop = CrawlLoop(ctx, ScriptedTask(), policy=policy)
+        calls = spy_cooldown(loop)
+
+        threading.Timer(0.15, stop.set).start()
+        t0 = time.monotonic()
+        loop.run()
+        elapsed = time.monotonic() - t0
+
+        self.assertEqual(self.mgr.launch_count, 1)  # 第 1 次失败即进退避
+        bo_calls = [c for c in calls if c[1] == "launch_backoff"]
+        self.assertEqual(len(bo_calls), 1)
+        seconds, _reason, prefix = bo_calls[0]
+        self.assertAlmostEqual(seconds, 30.0, delta=1e-6)  # min(30*1, 120)
+        self.assertEqual(prefix, "启动退避")
+        # 被 stop 中断（UserInterrupted），未等满 30s、未二次 launch
+        self.assertLess(elapsed, 5.0)
+        self.assertIn("launch_backoff", ctx.cooldown_until)
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/fetcher/tests/test_cooldown_contract.py b/fetcher/tests/test_cooldown_contract.py
new file mode 100644
index 0000000..0aad389
--- /dev/null
+++ b/fetcher/tests/test_cooldown_contract.py
@@ -0,0 +1,126 @@
+# -*- coding: utf-8 -*-
+"""冷却契约（P1）单测：StepResult.cooldown 与 WorkerContext.cooldown_until
+是纯加法字段——默认值、关键字构造生效、既有三参数位置构造兼容、
+default_factory 语义（两实例不共享同一份 dict）。
+
+Step 2.1 起追加策略迁移契约：Sleep / BackoffSleep / BlockRest 三策略
+run() 只算时长放进 StepResult.cooldown，自身零等待（不触 ctx.wait）。"""
+
+import unittest
+from types import SimpleNamespace
+
+from fetcher.core.context import WorkerContext
+from fetcher.strategy.base import StepResult
+from fetcher.strategy.strategies import (BackoffSleepStrategy,
+                                         BlockRestStrategy, SleepStrategy)
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
+if __name__ == "__main__":
+    unittest.main()
