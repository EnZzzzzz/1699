# Review package — Step 4.1 (BASE 46fcc656f072bb518b647aa59bfe50b4923ebc0b..HEAD)

## git log
c9b7cf1 docs(p5): 修订 flow-architecture/AGENTS/fetcher README 与现状同步

## git diff --stat
 AGENTS.md                 | 11 +++++-----
 docs/flow-architecture.md | 56 ++++++++++++++++++++++++++++-------------------
 fetcher/README.md         |  3 +++
 3 files changed, 42 insertions(+), 28 deletions(-)

## git diff -U10
diff --git a/AGENTS.md b/AGENTS.md
index 02eb080..8f18f7b 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -8,37 +8,37 @@
 fetcher/          采集框架（Python 包，可独立安装）：
                   核心层 core/（ActionResult/Outcome/WorkerContext）· 原子层 atoms/（Atom 协议）
                   网络层 net/ · 判断层 detect/ · 策略层 strategy/ · 站点插件 sites/
                   CLI：python -m fetcher 1688 shop|contact|company / yiwugo search / taobao search
                   CLI 另有 daemon 常驻模式：多队列调度（5 条 work_items 队列：1688/madeinchina
                   双站 contact + shop/company feeder），按站点冷却跨队列填充（`--queues` 指定子集，
                   默认全量；与旧 CLI 同站互斥），见 docs/scheduler-architecture.md
                   vendor/wa-check/：内置 Node/Baileys CLI（WhatsApp 查号协议实现）
 platform/         管理系统（前后端分离）
   server/         FastAPI 后端（端口 8765）：app/api/ REST + SSE · app/runner.py 任务监督器
-                  app/wa_tasks.py（wa_check 进程内执行器）· app/wa_login.py（WhatsApp 扫码登录）
+                  （subprocess 输出泵 + 批次 sweeper + 循环重启 Timer）· app/wa_login.py（WhatsApp 扫码登录）
   web/            React 18 + Vite + TS + Tailwind + shadcn/ui 前端（端口 3000，vite dev 有 HMR）
   start.sh        一键启动后端+前端；stop.sh 停止
 .cache/1688.db    SQLite 主库（WAL 模式）：shops / contacts / tasks / task_events /
                   providers / proxy_channels / task_templates
 scraper/ util/    旧版脚本，**只读参考，禁止修改**（新代码一律进 fetcher/ 或 platform/）
 docs/             flow-architecture.md（fetcher 框架设计）、scheduler-architecture.md（调度器设计：
                   队列+消费者池+跨站 IP 复用，跨任务编排以此为准）、service-architecture.md（旧方案，存档）
 ```
 
 ## 2. 必读文档（按改动范围）
 
 | 改动范围 | 必读 |
 |---|---|
 | `platform/web` 任何文件 | **[DESIGN.md](DESIGN.md)**（设计规范唯一来源，新增页面/组件前先读） |
 | `fetcher/` 框架或原子 | `docs/flow-architecture.md`（Atom 契约、分层职责） |
-| 任务系统 / runner | `platform/server/app/runner.py` 头部注释（subprocess 与进程内两类模型） |
+| 任务系统 / runner | `platform/server/app/runner.py` 头部注释（任务执行模型与 TASK_COMMANDS/BATCH_TYPES） |
 | 数据库访问 | 见下方 §4 数据库约定 |
 
 ## 3. 设计规范摘要（完整约束以 DESIGN.md 为准）
 
 **改 `platform/web` 前必须逐条对照 DESIGN.md，以下是最容易被违反的铁律：**
 
 - **颜色 Token 唯一来源** `src/styles/tokens.css`：禁止在组件里散落硬编码色值（如 `#fff`、`rgb(...)`）；新增颜色走「tokens.css 加 token → tailwind.config.js 映射」两步，`:root` 与 `.dark` 两组 token 必须成对新增。
 - **Select 与按钮并排**：`SelectTrigger` 必须 `h-8` + 显式 `font-medium`（默认 `font-normal` 会与按钮不齐）；长文案 trigger（如「每页 20 条」）**不要写死小宽度**，用 `w-fit` 自适应避免箭头压住文字；列表项文案与 trigger 一致。
 - **按钮**：工具栏/分页条内统一 `variant="outline" size="sm"`；主操作才 `default`，危险操作 `destructive`。
 - **状态徽标**：成功态用 `border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400`；同一状态全局同色（参考 `ShopsTab.shopStatusBadge`、`data/ContactsTab.tsx` 的 waBadge）。
@@ -49,23 +49,24 @@ docs/             flow-architecture.md（fetcher 框架设计）、scheduler-arc
 - **圆角/阴影**：圆角以 `--radius: 0.625rem` 为基准（sm=-4px、md=-2px、lg=基准、xl=+4px）；阴影仅 `shadow-xs` 为基准微阴影，弹层 `shadow-md`。
 
 ## 4. 后端与数据库约定
 
 - 时间戳一律为**北京时间字符串**（`YYYY-MM-DD HH:MM:SS`），**不要再做 +8 偏移**（库里已是北京时区）。
 - SQLite 为 WAL 模式、爬虫可能正在写库：读连接用 `app.db.connect()`（只读，禁写）；写一律**短事务 + `PRAGMA busy_timeout = 30000`**。
 - 新增列/表走 `app.db.migrate()` 幂等迁移；涉及可能缺列的场景要**防御性探测**（参考 `api/data.py` 的 `PRAGMA table_info` 探测模式）。
 - `wa_registered` 语义：`1`=已注册、`0`=未注册、`NULL`=未查（等价 `wa_checked_at IS NULL`）。
 - 改后端代码后 uvicorn **不会自动 reload**，需重启才生效（重启见 `platform/start.sh`/`stop.sh`；注意 pidfile 记录的是父进程，杀端口占用进程时按实际监听 pid）。
 
-## 5. 任务系统（两类执行模型，新增任务类型时二选一）
+## 5. 任务系统（三类执行模型）
 
-- **subprocess 类**：`TASK_COMMANDS` 注册类型 → `build_command()` 拼 fetcher CLI → Popen，输出泵逐行写 task_events。适合已有 fetcher CLI 子命令的任务。
-- **进程内类**：`IN_PROCESS_TYPES` 注册（如 `wa_check`）→ `_start_in_process` 在线程跑执行器（`wa_tasks.run`），`threading.Event` 协作式停止。适合数据在平台 DB、需分批写回的任务。
+- **subprocess 类**：`TASK_COMMANDS` 注册类型 → `build_command()` 拼 fetcher CLI → Popen，输出泵逐行写 task_events。现唯一 subprocess 类型为 yiwugo_search。
+- **批次类**：`BATCH_TYPES` 注册类型 → 入队 work_items 批次 → daemon dispatcher 消费；平台 sweeper 派生状态/聚合进度（1688/madeinchina 采集与 wa_check 均走此模型）。
+- **daemon 纳管**：fetcher daemon 常驻（start.sh 拉起，stop.sh 优雅退出），队列+消费者池调度、跨站冷却填充，见 docs/scheduler-architecture.md。
 - 任务终态：`pending / running / done / failed / stopped`；停止先置 `stop_requested=1`；`repeat_interval>0` 走循环重启（Timer）。
 - 新增任务类型需同步：`runner.py` 注册 + `api/tasks.py` 的 `TaskParams` 字段 + 前端 `TaskFormDialog.tsx` 表单分支 + `task-ui.tsx` 的 `TASK_TYPE_OPTIONS`。
 
 ## 6. 通用代码约定
 
 - 类名合并一律用 `cn()`（`@/lib/utils`）；注释用中文，文件顶部一行注释说明模块职责。
 - 前端提交前跑 `npx tsc -b`（`platform/web` 下）；Python 改动保持 `fetcher` 分层不引入重依赖。
 - 不动 `scraper/`、`util/` 旧脚本；新能力进 `fetcher/`（框架侧）或 `platform/`（平台侧）。
 - fetcher 原子只「做一件事并报告 Outcome」，不做重试/换 IP 等决策（决策在策略层/上层执行器）。
diff --git a/docs/flow-architecture.md b/docs/flow-architecture.md
index 2398e02..76bc8a9 100644
--- a/docs/flow-architecture.md
+++ b/docs/flow-architecture.md
@@ -1,54 +1,59 @@
 # 原子能力 + DAG 流水线架构设计
 
 > 版本：v1 · 2026-08-01 · 设计基准文档（与 owner 逐条确认后的结论）
+> 状态：v1 原子层已按 §3 落地；flows 表 DAG 编排（§4~§8）**未落地**，且已被
+> docs/scheduler-architecture.md 的「work_items 队列 + 消费者池 + daemon 调度」路线取代；
+> §2/§6/§7 相关段落为历史设计，仅存档参考。2026-08-08（P5）已删除 flows 表与
+> tasks.flow_id 列（表重建迁移）。
 > 关联文档：docs/service-architecture.md（服务化总体架构，本文档是其演进）
 
 ## 1. 需求确认结论
 
 | 议题 | 结论 |
 |---|---|
 | 核心目标 | 任务逻辑从"写死在 Python 控制流"升级为"原子能力（Atom）+ 编排层（DAG）"，流水线可保存、可复用、可视化 |
 | 颗粒度 | 两级：编排 DAG 为粗粒度（单任务 5~15 节点）；重试/换 IP/熔断等控制流是**节点策略配置**，不画成 DAG 的边 |
 | 循环表达 | 容器节点（如 `for_each_shop` 带子图），DAG 保持无环，不画回边 |
 | 并发表达 | 容器节点的 `parallel: N` 属性，引擎负责起 N 个执行上下文并管理共享配额；不在图中画并行分支 |
 | worker 可观测 | 并行容器节点可下钻，能看到每个 worker 独立的执行轨迹、当前所在子节点、各自进度 |
 | 节点实时进度 | 每种节点实时上报运行时状态（elapsed / 自定义进度字段），前端看板画进度条/环形图；Sleep 要能看到已睡多久 |
 | 资源生命周期 | 引擎统一管理：DAG 声明资源（通道/浏览器），入口 acquire、出口 release（含异常兜底）；原子经 `ctx` 取用；SwapIP 换通道必须经引擎接口报备 |
 | 流水线保存 | `flows` 表存「DAG 结构 + 全部节点参数」为模板（重试策略、是否换 IP、sleep 时长与浮动区间等）；执行时选模板 + 补少量运行时变量一键运行；模板可复制出新版本 |
 | 前端分期 | v1 只读流程图 + 实时节点状态看板（非静态图，轮询/SSE 刷新）；v2 可视化拖拽编辑器 |
 | 迁移策略 | 不动现有 `shop_crawl` / `contact_fetch`；新增独立 `flow` 任务类型；内置模板 1:1 复刻现有两任务行为，灰度验证等价后逐步替代、最终下线旧实现 |
 
-## 2. 分层架构
+## 2. 分层架构（现状）
 
 ```
 ┌────────────────────────────────────────────────────┐
-│ 编排层  flows 表（DAG JSON 模板，可保存/复制/版本）   │  ← 新增
+│ 调度层  fetcher daemon：QueueRouter 多队列调度       │  ← 现状
+│         消费者池（work_items 队列 + 跨站冷却填充，   │
+│         见 scheduler-architecture.md）               │
 ├────────────────────────────────────────────────────┤
-│ 引擎层  FlowExecutor                                 │  ← 新增
-│         拓扑执行 · 容器节点 · 并行上下文 · 资源管理     │
-│         节点级状态上报 · 协作式停止                    │
+│ 引擎层  Engine + CrawlLoop / LocalLoop               │  ← 现状
+│         逐工作项执行（认领→IP 保鲜→fetch→簿记）      │
 ├────────────────────────────────────────────────────┤
-│ 原子层  Atom Registry（能力目录，标准契约）            │  ← 从现有代码抽取
-│         sleep / swap_ip / fetch_contact / ...        │
+│ 原子层  Atom Registry（能力目录，标准契约）          │  ← 现状（§3 已落地）
+│         sleep / swap_ip / fetch_contact / ...       │
 ├────────────────────────────────────────────────────┤
-│ 资源层  通道池 PoolManager · CloakBrowser · ShopDB    │  ← 基本不变
-│         TaskRuntime（事件/进度/心跳/停止）             │
+│ 资源层  通道池 · BrowserManager · ShopDB             │  ← 现状
+│         事件/进度落 SQLite（task_events/progress_json）│
 └────────────────────────────────────────────────────┘
 ```
 
 关键决策说明：
 
-- **策略不下放成边**：`on_blocked: {do: swap_ip, retry: 2}` 这类声明式配置由引擎的策略拦截器统一执行，原子本身只负责"做一件事并报告结果分类（ok / blocked / net_error）"。控制流复杂度收敛在引擎一处，DAG 图保持干净。
-- **原子只报告，不决策**：原子不感知重试次数、不决定是否换 IP；这些决策在引擎策略层。这使原子可独立测试。
-- **引擎寄生在现有 Celery 模型上**：`flow` 任务类型 = 一个通用 Celery 入口 `run_flow(task_id)`，引擎在该进程内驱动整个 DAG；多 worker 并行仍是任务内多线程（与现状一致），不引入跨进程编排复杂度。
-- **TaskRuntime 复用**：事件流、progress_json、Redis 心跳、stop_requested 协作式停止全部沿用，只是事件/进度的粒度从"任务"细化到"节点"（data 里带 `node_id` / `worker_id`）。
+- **策略不下放成边**：`on_blocked: {do: swap_ip, retry: 2}` 这类声明式配置由策略层统一执行，原子本身只负责"做一件事并报告结果分类（ok / blocked / net_error）"。控制流复杂度收敛在策略层一处，流水线保持干净。（现状一致，保留）
+- **原子只报告，不决策**：原子不感知重试次数、不决定是否换 IP；这些决策在策略层。这使原子可独立测试。（现状一致，保留）
+- **任务执行**：任务由 daemon 的消费者执行（Engine/CrawlLoop 或 LocalLoop），跨任务编排是队列 + 消费者池（见 scheduler-architecture.md §8），无 Celery。
+- **事件与进度**：事件/进度写 SQLite（task_events / progress_json），无 Redis 心跳；协作式停止走 stop_requested 与循环 Timer（平台 runner）。
 
 ## 3. 原子（Atom）契约与清单
 
 ### 3.1 契约
 
 ```python
 class Atom:
     name: str                    # 注册名，如 "swap_ip"
     title: str                   # 显示名，如 "更换出口 IP"
     inputs: dict                 # 需要的 ctx 键，如 {"channel": "Channel"}
@@ -186,20 +191,23 @@ ctx.stop_requested()          # 协作式停止检查
 ```
 
 ### 5.4 节点级状态上报
 
 - 每个节点（含 worker 实例维度）维护运行时状态：`pending / running / ok / failed / skipped / aborted`，`started_at / finished_at / elapsed`，以及原子自定义的 `progress` 字段。
 - 落点：任务 `progress_json` 增加 `nodes: {node_key: {...}}`（node_key = `节点id` 或 `节点id#w0`），与现有任务级字段共存；`task_events.data_json` 统一带 `node_id` / `worker_id`。
 - 前端轮询/SSE 取 `progress_json.nodes` 渲染看板，无需新增推送通道。
 
 ## 6. 存储设计（新增 1 张表 + tasks 表加列）
 
+> ⚠️ 本节为历史设计：flows 表与 tasks.flow_id 从未承载生产语义，P5（2026-08-08）
+> 已通过幂等表重建删除 flows 表与 flow_id 列。SQL 仅为存档。
+
 ```sql
 -- 流水线模板（DAG + 节点参数整体保存，可复制出新版本）
 CREATE TABLE flows (
     id          INTEGER PRIMARY KEY AUTOINCREMENT,
     name        TEXT NOT NULL,            -- 如 "联系人提取·标准"
     description TEXT,
     dag_json    TEXT NOT NULL,            -- §4 定义
     builtin     INTEGER NOT NULL DEFAULT 0,  -- 1=内置复刻模板（只读防误改）
     created_at  TEXT NOT NULL,
     updated_at  TEXT NOT NULL
@@ -208,30 +216,32 @@ CREATE TABLE flows (
 -- tasks 表加列（ALTER TABLE，不动现有行）
 ALTER TABLE tasks ADD COLUMN flow_id INTEGER REFERENCES flows(id);
 -- type 新增取值 "flow"；params_json 存 run_inputs 实参（如 {"limit": 100}）
 ```
 
 - 任务创建（type=flow）：`{flow_id, run_inputs}` → 快照 `dag_json` 进任务（防止模板后改影响历史任务的可追溯；快照存于 params_json._dag_snapshot）。
 - 节点运行状态不落新表，走 `progress_json.nodes`（易过期、易重写，符合"看板"语义）；需要审计的细节已在 `task_events`。
 
 ## 7. API 设计（新增）
 
+> 本节 flows/atoms 端点为历史设计，未实现；任务 API 现仅 tasks 通用端点。
+
 ```
-GET    /api/flows                 # 模板列表
-POST   /api/flows                 # 新建模板（含 DAG 校验）
-GET    /api/flows/{id}            # 模板详情
-PUT    /api/flows/{id}            # 更新（builtin=1 拒绝）
-POST   /api/flows/{id}/duplicate  # 复制出新版本
-DELETE /api/flows/{id}            # 删除（被任务引用时仅标记 archived）
-GET    /api/atoms                 # 原子目录（name/title/param_spec），前端表单/编辑器用
-POST   /api/flows/validate        # 独立 DAG 校验（保存前调用）
-POST   /api/tasks                 # type=flow 时传 {flow_id, run_inputs}
+GET    /api/flows                 # 模板列表（未落地）
+POST   /api/flows                 # 新建模板（含 DAG 校验）（未落地）
+GET    /api/flows/{id}            # 模板详情（未落地）
+PUT    /api/flows/{id}            # 更新（builtin=1 拒绝）（未落地）
+POST   /api/flows/{id}/duplicate  # 复制出新版本（未落地）
+DELETE /api/flows/{id}            # 删除（被任务引用时仅标记 archived）（未落地）
+GET    /api/atoms                 # 原子目录（name/title/param_spec），前端表单/编辑器用（未落地）
+POST   /api/flows/validate        # 独立 DAG 校验（保存前调用）（未落地）
+POST   /api/tasks                 # 通用任务创建；type=flow 时传 {flow_id, run_inputs}（flow 分支未落地）
 ```
 
 任务进度接口 `GET /api/tasks/{id}` 的响应中 `progress.nodes` 即节点看板数据，结构：
 
 ```jsonc
 {
   "collected": 42, "pending": 300, "per_minute": 3.1,
   "nodes": {
     "start_delay": {"status": "ok", "elapsed": 12.0},
     "loop":        {"status": "running", "batch": 2, "parallel": 2},
@@ -255,14 +265,14 @@ POST   /api/tasks                 # type=flow 时传 {flow_id, run_inputs}
 |---|---|---|
 | P0 原子抽取 | Atom 契约 + Registry；从两个现有 worker 抽出 §3.2 清单原子（只改组织形式，不改行为） | 原子单测可独立跑通 |
 | P1 引擎 | FlowExecutor（拓扑/容器/并行/策略拦截/资源管理/节点状态上报）+ flows 表 + `run_flow` + §7 API | 单元级 DAG 可执行 |
 | P2 内置模板 | 内置 2 个模板 1:1 复刻 `shop_crawl` / `contact_fetch`；灰度跑通，对比旧任务行为等价（事件序列、抓取结果口径） | 同参数下产出一致 |
 | P3 前端看板 | 流水线页 + 只读 DAG 图 + 节点实时看板 + worker 下钻 | 看板实时反映执行 |
 | P4 替代 | 新任务默认走 flow；旧类型冻结（不再加功能），稳定一个周期后下线旧实现 | 旧代码路径删除 |
 | P5 编辑器（v2） | 可视化拖拽编辑 + 保存/校验 | 前端可新建模板 |
 
 ## 10. 明确的非目标（v1 不做）
 
-- 跨任务/跨进程的 DAG 编排（引擎只在单任务进程内）
+- 跨任务 DAG 编排不做（引擎只消费队列，不关心流水线内部拓扑）；跨任务队列调度已由 daemon 实现（scheduler-architecture.md §8）
 - 任意条件分支图（if/else 边）；条件能力由策略配置覆盖
 - 模板版本 diff / 回滚（仅支持复制出新模板）
 - 多用户/权限（沿用单机无鉴权前提）
diff --git a/fetcher/README.md b/fetcher/README.md
index b946cbe..02b5284 100644
--- a/fetcher/README.md
+++ b/fetcher/README.md
@@ -82,14 +82,17 @@ python -m pytest tests -x -q
 ```
 
 全部 mock：不起真实浏览器、不发真实网络请求、不碰真实数据库（临时 sqlite）。
 当前 85 个用例：Detector / Policy / IdentityStore（P0+P1）+ CrawlLoop
 集成 + contact 任务 + Engine 编排（P2+P3）+ 站点扩展性（P4：第三方
 最小站点注册并跑通 CrawlLoop、taobao 探测器域隔离、解析器/validate/
 fetch 门控、策略覆盖）。
 
 ## 本阶段边界
 
+平台任务走 daemon 批次模型（work_items 队列）；站点子命令 CLI（1688/madeinchina
+shop|contact|company）仅供手动/调试，与 daemon 同站互斥约定不变。
+
 P2+P3 已交付控制层与 CLI。P3 已落地：多队列多站点调度（daemon 常驻）、
 BrowserContext 多站点隔离（一消费者一浏览器进程、每站点独立 context）、
 SwapIP 无头两阶段、shop/company feeder 队列（work_items 驱动）。
 遗留：多进程类目池互斥、换 IP 等待期的 item 级调度（见 docs/design.md §14）。
