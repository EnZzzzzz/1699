# task-5-report — Step 4.1 文档修订（flow-architecture / AGENTS.md / fetcher README）

> implementer 报告。日期：2026-08-08。分支：refactor/retire-legacy-p5。
> 需求来源：task-5-brief.md（SPEC §3.6/§3.7）。纯文档改动，未跑 pytest/tsc，未碰代码。

## 状态

DONE

## 改了什么

### 改动 1：docs/flow-architecture.md（4 项，commit c9b7cf1）

- **1a 头部状态行**：版本行下方新增状态行（v1 原子层已落地 / flows DAG 编排未落地且被
  scheduler-architecture 路线取代 / §2§6§7 历史设计存档 / P5 已删 flows 表与 flow_id 列）。
- **1b §2 重写**：标题改「分层架构（现状）」；分层图改为四层现状（调度层 fetcher daemon
  QueueRouter+消费者池 → 引擎层 Engine+CrawlLoop/LocalLoop → 原子层 Atom Registry → 资源层
  通道池/BrowserManager/ShopDB），各层标注「现状」；四条关键决策按 brief 处理：
  ①②保留（微调措辞为「策略层」并注明现状一致）、③改写为 daemon 消费者执行 + 队列消费者池
  （scheduler-architecture.md §8）、④改写为事件/进度落 SQLite（task_events/progress_json）、
  无 Redis 心跳、协作式停止 stop_requested + 循环 Timer。无 Celery/Redis/TaskRuntime 寄生表述。
- **1c §6**：节首新增 ⚠️ 历史设计说明（flows 表从未承载生产语义，P5 表重建删除），SQL 块保留原文。
- **1d §7**：节首新增「本节 flows/atoms 端点为历史设计，未实现；任务 API 现仅 tasks 通用端点」；
  flows/atoms/validate/type=flow 端点逐一标注「未落地」；进度响应示例（progress.nodes jsonc）保留。
- **1e §10**：第一条改为区分表述（跨任务 DAG 编排不做 + 跨任务队列调度已由 daemon 实现），
  其余三条保留。
- §4/§5/§8/§9 未改，由头部状态行统一标注。

### 改动 2：AGENTS.md（3 项）

- **2a §1**：删 `app/wa_tasks.py（wa_check 进程内执行器）` 引用；runner 描述改为
  「（subprocess 输出泵 + 批次 sweeper + 循环重启 Timer）」。
- **2b §2 表**：runner 行改为「任务执行模型与 TASK_COMMANDS/BATCH_TYPES」。
- **2c §5**：改为三类模型（subprocess 类仅剩 yiwugo_search / 批次类 BATCH_TYPES 入队 work_items
  + daemon dispatcher 消费 + sweeper 派生状态 / daemon 纳管常驻 start.sh 拉起 stop.sh 退出）；
  删 IN_PROCESS_TYPES 叙述；保留任务终态、stop_requested、循环 Timer、新增类型同步清单。

### 改动 3：fetcher/README.md（1 项）

- 「本阶段边界」前新增定位行：平台任务走 daemon 批次模型（work_items 队列）；站点子命令 CLI
  （1688/madeinchina shop|contact|company）仅供手动/调试，与 daemon 同站互斥约定不变。

## 逐项对照结果

- 1a ✓ 状态行在版本行下方，内容与 brief 逐字一致
- 1b ✓ 四层现状图 + ①②保留③④改写，无 Celery/Redis/TaskRuntime 寄生表述
- 1c ✓ §6 节首 ⚠️ 标注，SQL 保留
- 1d ✓ §7 节首说明 + 端点逐一「未落地」，进度响应示例保留
- 1e ✓ §10 第一条区分表述，其余保留
- 2a ✓ AGENTS.md §1 无 wa_tasks.py 引用
- 2b ✓ §2 表同步为 TASK_COMMANDS/BATCH_TYPES
- 2c ✓ §5 三类模型，无 IN_PROCESS_TYPES
- 3 ✓ fetcher/README.md 定位行在「本阶段边界」之前

## grep 自查结果

`grep -c "wa_tasks\|IN_PROCESS\|cmdparse\|进程内" AGENTS.md README.md fetcher/README.md`
→ 三文件均 0 命中（exit=1），零残留。
flow-architecture.md 未纳入 grep 范围（brief 明确：其历史叙述中本就有 wa_tasks 一词，
属预期）。实际 flow-architecture.md 现有文本亦未出现 wa_tasks/IN_PROCESS/cmdparse/进程内。

## commit

- c9b7cf1 `docs(p5): 修订 flow-architecture/AGENTS/fetcher README 与现状同步`
- 仅含 3 个文件（docs/flow-architecture.md、AGENTS.md、fetcher/README.md，+42/-28）。
- plan 目录（brief/report/ledger）未进 commit，保持 untracked（主 Agent 另行记账）。

## 未改动（明确排除项核对）

- docs/scheduler-architecture.md：未动（§10 P5 行标完成归 Step 4.2）
- README.md（根）：未动（brief 已核对无死引用）
- docs/service-architecture.md：未动
- flow-architecture.md §4/§5/§8/§9：未动
- 任何代码文件：未动

## 疑虑

- 头部状态行按 brief 原文写「§2/§6/§7 相关段落为历史设计」，但同一 commit 内 §2 已重写为
  「现状」——两者语义略冲突。理解为：状态行描述文档总体定位（原 §2 的 DAG 编排设计属历史），
  §2 重写后其「现状」内容即真实现状。按 brief 逐字执行，未自行调和。
- brief 引用「scheduler-architecture.md §8」两处均按原文保留；实际该文档 §8 为「存储设计」，
  队列+消费者池调度在 §3/§5 描述。为不扩大改动面未自行改引用，建议 Step 4.2 终审时确认
  是否需要修正为 §3/§5。

---

## 修复轮 1 报告（Important：scheduler-architecture.md §8 引用错误 ×2）

### 改动
- `docs/flow-architecture.md:48`（§2 决策③「任务执行」）：`scheduler-architecture.md §8` → `scheduler-architecture.md §3/§5`
- `docs/flow-architecture.md:275`（§10 第一条非目标）：同上
- 其余内容未动（状态行 brief 逐字保留，属已裁决 Minor）
- commit: `2b10892`（仅 1 文件 +2/-2）

### 自查 grep
- `grep -n 'scheduler-architecture.md §8' docs/flow-architecture.md` → 无命中（exit=1）
- 注：行 4 仍含 `§4~§8`，经核实为 flow-architecture.md **自身章节**自引用（§4 DAG 定义~§8 前端设计），非 scheduler 引用，正确保留
