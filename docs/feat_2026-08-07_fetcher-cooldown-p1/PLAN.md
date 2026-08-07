# PLAN — 冷却策略迁移（P1）

> 需求与设计唯一来源：同目录 SPEC.md（上游：docs/scheduler-architecture.md §6/§10 P1）
> Step checkbox 只有验收通过后才能标 done，并随代码 commit；执行细节记 ledger.md。

## Phase 总览

| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
|---|---|---|---|---|
| P1 | 读码回填 + 契约层（StepResult.cooldown / WorkerContext.cooldown_until） | 2 | 无 | pending |
| P2 | 策略迁移 + loop chokepoint 收敛 + 单测 | 3 | P1 | pending |
| P3 | 等价性冒烟 + 文档收尾 | 2 | P2 | pending |

---

## Phase 1 — 读码回填 + 契约层

**准入条件**：无。
**完成标准**：SPEC §4 假设 2、3 回填「已读码验证」；契约层单测全绿；既有测试无回归。本 Phase 无运行时行为变化（字段纯加法），不要求冒烟。

### Step 1.1 读码确认（SPEC §4 假设 2、3）
- 预估：10 min · 依赖：无 · 状态：done（commit 39f3420）
- 内容：① 读 `fetcher/fetcher/atoms/sleep.py` 全文，把 Sleep/BackoffSleep 的时长分布公式逐字摘出，回填 SPEC §4 假设 2（公式写进 SPEC，迁移要逐字复刻）；② 读 `fetcher/fetcher/strategy/policy.py` 的 `PolicyDecision`/`decide` 与 `control/loop.py:319-395` 的策略消费链路，确认 cooldown 是否需要经 PolicyDecision 透传，回填 SPEC §4 假设 3（若不需要，SPEC §3.1 的 PolicyDecision 字段取消）。
- 交付物：SPEC 回填 commit；report 附两处读码摘录。
- 验收：
  - [x] SPEC §4 假设 2、3 依据列改为「已读码验证（附 file:line）」，结论明确

### Step 1.2 契约层实现 + 单测
- 预估：15 min · 依赖：1.1 · 状态：done（commit b084129）
- 内容：`strategy/base.py` 的 `StepResult` 加 `cooldown: float | None = None`（dataclass 纯加法，不动既有三字段语义）；`core/context.py` 的 `WorkerContext` 加 `cooldown_until: dict[str, float]`（field default_factory）；若 Step 1.1 结论是需要，`policy.py` 的 `PolicyDecision` 加透传字段。单测：StepResult 默认值/构造兼容（既有三参数位置构造不破坏）、WorkerContext 新字段初始化。
- 交付物：代码 + `fetcher/tests/` 新增或并入既有契约测试文件。
- 验收：
  - [x] 纯加法：既有构造调用点零改动（grep StepResult( 全部调用点仍编译通过）
  - [x] 新单测全绿 + 全量无回归（TDD 先红后绿）

---

## Phase 2 — 策略迁移 + chokepoint 收敛

**准入条件**：Phase 1 完成。
**完成标准**：单测全绿；SPEC §5 第 2、3 条的 grep 验收达成；**运行时冒烟**：直连 `python -m fetcher daemon --db <临时库> --workers 1 --limit 3` 跑通（行为等价冒烟在 Phase 3 做完整版）。

### Step 2.1 策略迁移（Sleep/BackoffSleep/BlockRest）
- 预估：15 min · 依赖：P1 · 状态：done（commit 3e719d5）
- 内容：`strategy/strategies.py` 三个策略的 run() 改为「算时长 → StepResult(cooldown=t)」，时长分布按 SPEC §4 假设 2 回填的公式逐字复刻；BlockRest 保留现有 log 行；SwapIPStrategy docstring 加「冷却例外」标注（引用 SPEC §2.2）。attempt 的获取路径按 Step 1.1 核实的现状（BackoffSleep 的 attempt 从哪来就怎么来）。
- 验收：
  - [x] 三策略 grep 无 `ctx.wait`；SwapIP 有例外注释
  - [x] 时长公式与 SPEC 回填公式逐字一致

### Step 2.2 loop chokepoint + 4 处等待点收敛
- 预估：15 min · 依赖：2.1 · 状态：pending
- 内容：`control/loop.py` 新增 `_cooldown(seconds, reason)`（写 ctx.cooldown_until + 保留现状两种等待展示路径）；批次休息/样本间隔/周期长休/启动退避 4 处改经 chokepoint（时长公式逐字保留）；`_process_item` 消费 `step.cooldown`（reason=`f"strategy:{name}"`，中断按现状 stop 路径）。
- 验收：
  - [ ] loop.py 内 `ctx.wait`/`wait_countdown` 只出现在 `_cooldown` 一处
  - [ ] 4 处等待的时长公式与迁移前逐字一致（diff 对照）
  - [ ] `_process_item` 正确消费 step.cooldown 且中断语义不变

### Step 2.3 迁移单测
- 预估：15 min · 依赖：2.1、2.2 · 状态：pending
- 内容：新增 `fetcher/tests/test_cooldown.py`：① 三策略返回 cooldown 在预期区间且自身零等待（断言 run() 返回耗时 ≈0）；② cooldown 分布参数与旧公式一致（采样统计或公式级断言）；③ chokepoint 写 cooldown_until + stop 中断立即返回；④ `_process_item` 策略冷却路径集成测试（仿 test_daemon_task.py 用例 5 的 CrawlLoop 联跑：策略返回 cooldown → loop 执行等待 → 重试 fetch）；⑤ 4 处等待点各触发一次（小参数配置）断言走了 chokepoint（可 monkeypatch 计时）。
- 验收：
  - [ ] 5 个用例全绿（防假阳性证据：定向破坏至少一轮）
  - [ ] 全量无回归

---

## Phase 3 — 等价性冒烟 + 文档收尾

**准入条件**：Phase 2 完成。
**完成标准**：SPEC §5 全部达成。

### Step 3.1 等价性冒烟
- 预估：15 min（不含跑数时间）· 依赖：P2 · 状态：pending
- 内容：临时库预置 6 条 shops pending（生产库只读抄真实店铺），两条路径各跑一遍：① daemon `--db <临时库A> --workers 1 --limit 6 -n 3 --batch-rest 60`；② 旧 CLI `1688 contact` 同参数（临时库B）。对比日志时间戳：样本间隔落在 13~20s+wid 错峰区间、批休落在 60±10%、长休/退避如触发落各自区间。另做一次 stop 中断冒烟：冷却中（批休 60s 窗口）发 SIGTERM，确认秒级中断退出（不等满 60s）。全程 --workers 1、直连、--headed 可选。
- 交付物：report 含命令、日志时间戳序列表、中断证据、生产库零污染核查。
- 验收：
  - [ ] SPEC §5 第 4、5 条达成
  - [ ] 冷却中 SIGTERM 立即中断（证据）

### Step 3.2 文档同步 + 终审准备
- 预估：10 min · 依赖：3.1 · 状态：pending
- 内容：`docs/scheduler-architecture.md` §10 P1 行标完成；`docs/scheduler-architecture.md` §6 冷却策略表加注「P1 已落地：时长输出+chokepoint，SwapIP 为例外」；fetcher/README.md 如无用户可见变化则不动（确认 daemon 行为描述仍准确）。ledger 补全，终审。
- 验收：
  - [ ] 文档更新随代码同 commit
  - [ ] 全分支终审：旧行为等价（时长公式零变化）经 diff 逐处核实

---

## 冲突扫描（呈交前自查）

**PLAN 内部**：Step 2.1 依赖 Step 1.1 回填的分布公式——若 1.1 发现公式无法干净复刻（如分布依赖原子内部状态），2.1 需上报重议，不擅自改分布。Step 2.3 用例 ④ 的集成测试与 test_daemon_task.py 用例 5 模式重叠——裁定：允许复用基建，但断言目标不同（冷却路径），不算重复覆盖。

**PLAN vs 代码库现状**：
- `StepResult` 的全部构造调用点：_AtomStrategy.run、SwapIPStrategy.run、WaitHuman* 策略（strategies.py 全文）+ 测试。纯加法字段不破坏位置构造（cooldown 放最后且带默认值）。
- `wait_countdown`（board.py:134-148）目前仅 loop.py 三处使用；chokepoint 收敛后 board.py 不动（函数保留，调用点变为 chokepoint 内部）。
- `ctx.wait` 的其他使用者（策略层迁移后剩余：SwapIP、human.py 原子、atoms/ 内部）全部在非目标内保留。
- `WorkerContext` 的全部构造点（engine.py:149、测试基建）——dataclass 纯加法不破坏。
- 旧 CLI 路径（1688 contact 等）共享 loop.py/strategies.py——本 P1 改的是共享代码，旧 CLI 行为必须等价，Step 3.1 第 ② 条路径就是为此设的。

**PLAN vs 外部依赖**：无新依赖。等价性冒烟用直连模式，不耗代理资源；本机活爬虫在跑，--workers 1 直连不抢席位之外的资源（直连也占 1 个 CloakBrowser 席位，冒烟短，可接受）。
