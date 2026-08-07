# Task 3.2 报告：冷却策略迁移 P1 文档同步

日期：2026-08-08
分支：feat/fetcher-cooldown-p1

## 改动

仅改动 `docs/scheduler-architecture.md` 一处文件，两处编辑：

1. **§10 落地路线表 P1 行**：「验收」格末尾追加
   `；✅ 已完成（2026-08-08，实施记录 docs/feat_2026-08-07_fetcher-cooldown-p1/）`，
   格式沿用 P0 行既有写法（分号续接 + 日期 + 实施记录路径）。其他行未动。
2. **§6 冷却策略表**：表格后追加一行注——
   「注：P1 已落地——Sleep/BackoffSleep/BlockRest 改为输出 StepResult.cooldown、
   loop 4 处等待收敛至 `_cooldown` chokepoint（control/loop.py）；
   SwapIP 内部等待为例外未迁移（P3 重议）。」

## 事实核对结论（写注前逐一核实）

- `_cooldown` chokepoint：`fetcher/fetcher/control/loop.py:108` 定义
  （注释明示「SPEC §3.3：唯一等待执行点」），4 处等待调用点
  （行 152 batch_rest / 215 sample_interval / 226 periodic_rest / 260 launch_backoff），
  另 410 行为策略冷却经 chokepoint 执行的消费点——「4 处等待收敛」指前者。
- 三策略：`fetcher/fetcher/strategy/strategies.py` 的 SleepStrategy（:58）、
  BackoffSleepStrategy（:79）、BlockRestStrategy（:97）均返回
  `StepResult(..., cooldown=t)`，类 docstring 均写明「只算时长输出冷却，不自己等待」。
- SwapIP 例外：`strategies.py:119` SwapIPStrategy docstring 明示
  「冷却例外：内部等待夹在两次 relaunch 之间，不迁移（SPEC §2.2，P3 重议）」。
  与所注内容一致。

## fetcher/README.md 核对结论：无需改动

- daemon 说明段（README.md:41-48）只描述 work_items 队列消费、补货、
  同站互斥等用户可见行为。
- P1 为内部等待机制重构（策略输出冷却时长、等待收敛到 chokepoint），
  CLI 参数、行为口径、产出均无用户可见变化，README 现有描述仍然准确，未动。

## 未做事项

无。仅按 Step 范围同步文档，未触碰任何代码。
