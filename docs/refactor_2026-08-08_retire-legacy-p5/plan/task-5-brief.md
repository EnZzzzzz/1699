# task-5-brief — Step 4.1 文档修订（flow-architecture / AGENTS.md / fetcher README）

> 本文件是你（implementer）需求的唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699
> 模型：deepseek-v4-flash。前置：Step 1.1/1.2/2.1/3.1 已完成（代码删除面已落地）。

## 项目位置

「1688 采集平台调度器改造 P5」的文档同步 Step：删除型 refactor 的最后一块拼图——把与现状
脱节的文档修订到位。SPEC §3.7 是唯一需求来源，逐项照做，不自行扩大。

## 改动 1：docs/flow-architecture.md（按 SPEC §3.7 四项）

**1a. 头部状态行**：在版本行（`> 版本：v1 · 2026-08-01 ...`）下方新增：

```
> 状态：v1 原子层已按 §3 落地；flows 表 DAG 编排（§4~§8）**未落地**，且已被
> docs/scheduler-architecture.md 的「work_items 队列 + 消费者池 + daemon 调度」路线取代；
> §2/§6/§7 相关段落为历史设计，仅存档参考。2026-08-08（P5）已删除 flows 表与
> tasks.flow_id 列（表重建迁移）。
```

**1b. §2 分层架构重写**：分层图与「关键决策说明」按现状改（删除 Celery/Redis/TaskRuntime
寄生表述）：
- 分层图改为四层现状：**调度层**（fetcher daemon：QueueRouter 多队列调度 + 消费者池，见
  scheduler-architecture.md）→ **引擎层**（Engine + CrawlLoop / LocalLoop，逐工作项执行）→
  **原子层**（Atom Registry，§3 契约已落地）→ **资源层**（通道池 / BrowserManager /
  ShopDB）。图内各层标注「现状」而非「新增」。
- 四条关键决策：
  ①「策略不下放成边」——保留（现状一致：原子只报告，策略层决策）。
  ②「原子只报告，不决策」——保留。
  ③「引擎寄生在现有 Celery 模型上」——**改写**为：任务由 daemon 的消费者执行
    （Engine/CrawlLoop 或 LocalLoop），跨任务编排是队列+消费者池（见
    scheduler-architecture.md §8），无 Celery。
  ④「TaskRuntime 复用」——**改写**为：事件/进度写 SQLite（task_events/progress_json），
    无 Redis 心跳；协作式停止走 stop_requested 与循环 Timer（平台 runner）。

**1c. §6 存储设计**：整节标注「未落地 + 已随 P5 删除」。节首加醒目说明（如
`> ⚠️ 本节为历史设计：flows 表与 tasks.flow_id 从未承载生产语义，P5（2026-08-08）
> 已通过幂等表重建删除 flows 表与 flow_id 列。SQL 仅为存档。`）。SQL 块保留原文。

**1d. §7 API 设计**：flows 相关端点（`GET/POST /api/flows*`、`/api/atoms`、
`/api/flows/validate`、`POST /api/tasks type=flow`）标注「未落地」；节首加一句说明
（「本节 flows/atoms 端点为历史设计，未实现；任务 API 现仅 tasks 通用端点」）。
保留进度响应示例。

**1e. §10 非目标重写**：第一条「跨任务/跨进程的 DAG 编排（引擎只在单任务进程内）」改写为
区分表述：「跨任务 DAG 编排不做（引擎只消费队列，不关心流水线内部拓扑）；跨任务队列调度
已由 daemon 实现（scheduler-architecture.md §8）」。其余条目保留。

> 注意：§4（DAG 定义）、§5（FlowExecutor）、§8（前端设计）、§9（落地路线）**不改**，
> 由头部状态行统一标注为历史设计。

## 改动 2：AGENTS.md（按 SPEC §3.7 三项）

**2a. §1 平台段落**：删 `app/wa_tasks.py（wa_check 进程内执行器）` 引用，runner 描述更新
为现状（subprocess 泵 + 批次 sweeper + 循环 Timer）：
```
  server/         FastAPI 后端（端口 8765）：app/api/ REST + SSE · app/runner.py 任务监督器
                  （subprocess 输出泵 + 批次 sweeper + 循环重启 Timer）· app/wa_login.py（WhatsApp 扫码登录）
```

**2b. §2 必读文档表**「任务系统 / runner」行：`runner.py 头部注释（subprocess 与进程内
两类模型）` → `platform/server/app/runner.py` 头部注释（任务执行模型与 TASK_COMMANDS/BATCH_TYPES）`。

**2c. §5 任务系统重写**为现行三类模型（删 IN_PROCESS_TYPES 叙述）：
- **subprocess 类**：`TASK_COMMANDS` 注册类型 → `build_command()` 拼 fetcher CLI → Popen，
  输出泵逐行写 task_events。现唯一 subprocess 类型为 yiwugo_search。
- **批次类**：`BATCH_TYPES` 注册类型 → 入队 work_items 批次 → daemon dispatcher 消费；
  平台 sweeper 派生状态/聚合进度（1688/madeinchina 采集与 wa_check 均走此模型）。
- **daemon 纳管**：fetcher daemon 常驻（start.sh 拉起，stop.sh 优雅退出），队列+消费者池
  调度、跨站冷却填充，见 docs/scheduler-architecture.md。
- 保留：任务终态 `pending/running/done/failed/stopped`；停止先置 `stop_requested=1`；
  `repeat_interval>0` 走循环重启（Timer）；新增任务类型需同步：`runner.py` 注册 +
  `api/tasks.py` 的 `TaskParams` 字段 + 前端 `TaskFormDialog.tsx` 表单分支 +
  `task-ui.tsx` 的 `TASK_TYPE_OPTIONS`。

## 改动 3：fetcher/README.md（按 SPEC §3.6）

加一行定位说明（放在 CLI / daemon 相关段落的合适位置，如「本阶段边界」之前或 CLI 说明处）：

```
平台任务走 daemon 批次模型（work_items 队列）；站点子命令 CLI（1688/madeinchina
shop|contact|company）仅供手动/调试，与 daemon 同站互斥约定不变。
```

## 不改（明确排除）

- `docs/scheduler-architecture.md`（§10 P5 行标完成归 Step 4.2，终审后做）
- `README.md`（根目录）：已核对无任务类型清单/死引用，无需改
- `docs/service-architecture.md`（旧方案存档，P5 非目标）
- flow-architecture.md 的 §4/§5/§8/§9
- 任何代码文件（本 Step 纯文档）

## 环境与约束

- 纯文档改动，不跑 pytest/tsc；改完自查：AGENTS.md/README 无 `wa_tasks`/`IN_PROCESS`
  `cmdparse` 残留（flow-architecture 保留历史设计语句属预期——但「wa_tasks」一词在
  flow-architecture/scheduler 历史叙述中本就存在，grep 范围限定 AGENTS.md + 两个 README）。
- 禁止碰代码、禁止碰 scheduler-architecture.md。

## commit

- 单 commit：`git add docs/flow-architecture.md AGENTS.md fetcher/README.md`
  message：`docs(p5): 修订 flow-architecture/AGENTS/fetcher README 与现状同步`
- plan 目录（brief/report/ledger）不进本 commit（主 Agent 另行记账）。

## 验收标准

- [ ] flow-architecture：头部状态行 + §2 现状重写（无 Celery/Redis/TaskRuntime 寄生表述）+
      §6/§7 未落地标注 + §10 区分表述
- [ ] AGENTS.md：§1 无 wa_tasks.py 引用、§2 表同步、§5 三类模型
- [ ] fetcher/README.md 定位行在
- [ ] AGENTS.md + 两个 README 下 grep `wa_tasks\|IN_PROCESS\|cmdparse\|进程内` 零命中
      （AGENTS.md §5 若保留「进程内」一词描述历史需避免——改为纯现状表述）
