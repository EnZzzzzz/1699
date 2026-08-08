# Re-review — 终审 M1-M4 修复 (Fix base 46c1193a413e3f3a187c273fcc8144ddbe7da07a..HEAD)

## git log
0a232df fix(p5): 终审 M1-M4——注释同步 + channels 整数校验 + 迁移回滚加固

## git diff -U10
diff --git a/docs/refactor_2026-08-08_retire-legacy-p5/plan/final-review.md b/docs/refactor_2026-08-08_retire-legacy-p5/plan/final-review.md
new file mode 100644
index 0000000..4b4ed7e
--- /dev/null
+++ b/docs/refactor_2026-08-08_retire-legacy-p5/plan/final-review.md
@@ -0,0 +1,2912 @@
+# FINAL REVIEW package — P5 全分支 (merge-base 46ee562..HEAD 46c1193)
+
+## git log main..HEAD
+46c1193 docs(p5): Step 4.1 checkbox 勾选
+c31d4d8 docs(p5): Step 4.1 验收通过——ledger 记账
+2b10892 docs(flow-architecture): 修正 scheduler-architecture 引用 §8 → §3/§5（队列+消费者池调度实际在 §3 分层架构 / §5 调度循环）
+c9b7cf1 docs(p5): 修订 flow-architecture/AGENTS/fetcher README 与现状同步
+46fcc65 docs(p5): Step 3.1 checkbox 勾选
+a5b34ac docs(p5): Step 3.1 验收通过——ledger 记账（含生产库提前迁移事件记录）
+61d6758 refactor(p5): tasks 表重建迁移——删 celery_id/flow_id 死列与 flows 表（方案 B 交换式）
+2fdb133 docs(p5): Step 3.1 决策点用户裁决——方案 B 交换式表重建
+3f70220 docs(p5): Step 2.1 checkbox 勾选
+e70aa42 docs(p5): Step 2.1 验收通过——ledger 记账 + PLAN checkbox 勾选
+63e758d chore(p5): 同步 TaskParams.retry_failed 注释（build_command 分支已删）
+b9ee35d refactor(p5): 前端同步——wa 表单裁剪 + 删从命令导入 UI + api.ts 类型失配修复
+cc5c163 docs(p5): Step 1.2 验收通过——ledger 记账 + PLAN checkbox 勾选
+27f1f5b docs(p5): Step 1.2 实施记录——task-2 report + 冒烟证据
+c46fc60 refactor(p5): 删除 cmdparse 从命令导入链路与 TaskParams 死字段
+7b5401c docs(p5): Step 1.1 验收通过——ledger 记账 + PLAN checkbox 勾选
+18e0cb8 refactor(p5): 删除 wa_tasks 进程内执行器与 runner 进程内机械
+
+## git diff --stat
+ AGENTS.md                                          |   11 +-
+ docs/flow-architecture.md                          |   56 +-
+ docs/refactor_2026-08-08_retire-legacy-p5/PLAN.md  |   53 +
+ .../plan/ledger.md                                 |   91 ++
+ .../plan/task-1-brief.md                           |   70 ++
+ .../plan/task-1-report.md                          |   70 ++
+ .../plan/task-1-review.md                          | 1110 ++++++++++++++++++++
+ .../plan/task-2-report.md                          |   87 ++
+ .../plan/task-2-smoke.txt                          |   14 +
+ fetcher/README.md                                  |    3 +
+ platform/server/app/api/tasks.py                   |   31 +-
+ platform/server/app/cmdparse.py                    |  169 ---
+ platform/server/app/db.py                          |   40 +-
+ platform/server/app/runner.py                      |   89 +-
+ platform/server/app/wa_tasks.py                    |  445 --------
+ platform/server/tests/test_batch_tasks.py          |    4 +-
+ platform/server/tests/test_dispatcher_api.py       |    5 +-
+ platform/server/tests/test_loop_restart.py         |    4 +-
+ platform/server/tests/test_task_waiting_status.py  |    2 -
+ platform/server/tests/test_tasks_table_rebuild.py  |  345 ++++++
+ platform/server/tests/test_wa_tasks_cooldown.py    |  168 ---
+ platform/server/tests/test_wa_tasks_guard.py       |  104 --
+ platform/web/src/lib/api.ts                        |   26 +-
+ platform/web/src/pages/tasks/TaskFormDialog.tsx    |  239 +----
+ platform/web/src/pages/tasks/task-ui.tsx           |   20 +-
+ 25 files changed, 1969 insertions(+), 1287 deletions(-)
+
+## git diff -U10 (代码部分为主，docs 提交含 plan 目录)
+diff --git a/AGENTS.md b/AGENTS.md
+index 02eb080..8f18f7b 100644
+--- a/AGENTS.md
++++ b/AGENTS.md
+@@ -8,37 +8,37 @@
+ fetcher/          采集框架（Python 包，可独立安装）：
+                   核心层 core/（ActionResult/Outcome/WorkerContext）· 原子层 atoms/（Atom 协议）
+                   网络层 net/ · 判断层 detect/ · 策略层 strategy/ · 站点插件 sites/
+                   CLI：python -m fetcher 1688 shop|contact|company / yiwugo search / taobao search
+                   CLI 另有 daemon 常驻模式：多队列调度（5 条 work_items 队列：1688/madeinchina
+                   双站 contact + shop/company feeder），按站点冷却跨队列填充（`--queues` 指定子集，
+                   默认全量；与旧 CLI 同站互斥），见 docs/scheduler-architecture.md
+                   vendor/wa-check/：内置 Node/Baileys CLI（WhatsApp 查号协议实现）
+ platform/         管理系统（前后端分离）
+   server/         FastAPI 后端（端口 8765）：app/api/ REST + SSE · app/runner.py 任务监督器
+-                  app/wa_tasks.py（wa_check 进程内执行器）· app/wa_login.py（WhatsApp 扫码登录）
++                  （subprocess 输出泵 + 批次 sweeper + 循环重启 Timer）· app/wa_login.py（WhatsApp 扫码登录）
+   web/            React 18 + Vite + TS + Tailwind + shadcn/ui 前端（端口 3000，vite dev 有 HMR）
+   start.sh        一键启动后端+前端；stop.sh 停止
+ .cache/1688.db    SQLite 主库（WAL 模式）：shops / contacts / tasks / task_events /
+                   providers / proxy_channels / task_templates
+ scraper/ util/    旧版脚本，**只读参考，禁止修改**（新代码一律进 fetcher/ 或 platform/）
+ docs/             flow-architecture.md（fetcher 框架设计）、scheduler-architecture.md（调度器设计：
+                   队列+消费者池+跨站 IP 复用，跨任务编排以此为准）、service-architecture.md（旧方案，存档）
+ ```
+ 
+ ## 2. 必读文档（按改动范围）
+ 
+ | 改动范围 | 必读 |
+ |---|---|
+ | `platform/web` 任何文件 | **[DESIGN.md](DESIGN.md)**（设计规范唯一来源，新增页面/组件前先读） |
+ | `fetcher/` 框架或原子 | `docs/flow-architecture.md`（Atom 契约、分层职责） |
+-| 任务系统 / runner | `platform/server/app/runner.py` 头部注释（subprocess 与进程内两类模型） |
++| 任务系统 / runner | `platform/server/app/runner.py` 头部注释（任务执行模型与 TASK_COMMANDS/BATCH_TYPES） |
+ | 数据库访问 | 见下方 §4 数据库约定 |
+ 
+ ## 3. 设计规范摘要（完整约束以 DESIGN.md 为准）
+ 
+ **改 `platform/web` 前必须逐条对照 DESIGN.md，以下是最容易被违反的铁律：**
+ 
+ - **颜色 Token 唯一来源** `src/styles/tokens.css`：禁止在组件里散落硬编码色值（如 `#fff`、`rgb(...)`）；新增颜色走「tokens.css 加 token → tailwind.config.js 映射」两步，`:root` 与 `.dark` 两组 token 必须成对新增。
+ - **Select 与按钮并排**：`SelectTrigger` 必须 `h-8` + 显式 `font-medium`（默认 `font-normal` 会与按钮不齐）；长文案 trigger（如「每页 20 条」）**不要写死小宽度**，用 `w-fit` 自适应避免箭头压住文字；列表项文案与 trigger 一致。
+ - **按钮**：工具栏/分页条内统一 `variant="outline" size="sm"`；主操作才 `default`，危险操作 `destructive`。
+ - **状态徽标**：成功态用 `border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400`；同一状态全局同色（参考 `ShopsTab.shopStatusBadge`、`data/ContactsTab.tsx` 的 waBadge）。
+@@ -49,23 +49,24 @@ docs/             flow-architecture.md（fetcher 框架设计）、scheduler-arc
+ - **圆角/阴影**：圆角以 `--radius: 0.625rem` 为基准（sm=-4px、md=-2px、lg=基准、xl=+4px）；阴影仅 `shadow-xs` 为基准微阴影，弹层 `shadow-md`。
+ 
+ ## 4. 后端与数据库约定
+ 
+ - 时间戳一律为**北京时间字符串**（`YYYY-MM-DD HH:MM:SS`），**不要再做 +8 偏移**（库里已是北京时区）。
+ - SQLite 为 WAL 模式、爬虫可能正在写库：读连接用 `app.db.connect()`（只读，禁写）；写一律**短事务 + `PRAGMA busy_timeout = 30000`**。
+ - 新增列/表走 `app.db.migrate()` 幂等迁移；涉及可能缺列的场景要**防御性探测**（参考 `api/data.py` 的 `PRAGMA table_info` 探测模式）。
+ - `wa_registered` 语义：`1`=已注册、`0`=未注册、`NULL`=未查（等价 `wa_checked_at IS NULL`）。
+ - 改后端代码后 uvicorn **不会自动 reload**，需重启才生效（重启见 `platform/start.sh`/`stop.sh`；注意 pidfile 记录的是父进程，杀端口占用进程时按实际监听 pid）。
+ 
+-## 5. 任务系统（两类执行模型，新增任务类型时二选一）
++## 5. 任务系统（三类执行模型）
+ 
+-- **subprocess 类**：`TASK_COMMANDS` 注册类型 → `build_command()` 拼 fetcher CLI → Popen，输出泵逐行写 task_events。适合已有 fetcher CLI 子命令的任务。
+-- **进程内类**：`IN_PROCESS_TYPES` 注册（如 `wa_check`）→ `_start_in_process` 在线程跑执行器（`wa_tasks.run`），`threading.Event` 协作式停止。适合数据在平台 DB、需分批写回的任务。
++- **subprocess 类**：`TASK_COMMANDS` 注册类型 → `build_command()` 拼 fetcher CLI → Popen，输出泵逐行写 task_events。现唯一 subprocess 类型为 yiwugo_search。
++- **批次类**：`BATCH_TYPES` 注册类型 → 入队 work_items 批次 → daemon dispatcher 消费；平台 sweeper 派生状态/聚合进度（1688/madeinchina 采集与 wa_check 均走此模型）。
++- **daemon 纳管**：fetcher daemon 常驻（start.sh 拉起，stop.sh 优雅退出），队列+消费者池调度、跨站冷却填充，见 docs/scheduler-architecture.md。
+ - 任务终态：`pending / running / done / failed / stopped`；停止先置 `stop_requested=1`；`repeat_interval>0` 走循环重启（Timer）。
+ - 新增任务类型需同步：`runner.py` 注册 + `api/tasks.py` 的 `TaskParams` 字段 + 前端 `TaskFormDialog.tsx` 表单分支 + `task-ui.tsx` 的 `TASK_TYPE_OPTIONS`。
+ 
+ ## 6. 通用代码约定
+ 
+ - 类名合并一律用 `cn()`（`@/lib/utils`）；注释用中文，文件顶部一行注释说明模块职责。
+ - 前端提交前跑 `npx tsc -b`（`platform/web` 下）；Python 改动保持 `fetcher` 分层不引入重依赖。
+ - 不动 `scraper/`、`util/` 旧脚本；新能力进 `fetcher/`（框架侧）或 `platform/`（平台侧）。
+ - fetcher 原子只「做一件事并报告 Outcome」，不做重试/换 IP 等决策（决策在策略层/上层执行器）。
+diff --git a/docs/flow-architecture.md b/docs/flow-architecture.md
+index 2398e02..eacc9f4 100644
+--- a/docs/flow-architecture.md
++++ b/docs/flow-architecture.md
+@@ -1,54 +1,59 @@
+ # 原子能力 + DAG 流水线架构设计
+ 
+ > 版本：v1 · 2026-08-01 · 设计基准文档（与 owner 逐条确认后的结论）
++> 状态：v1 原子层已按 §3 落地；flows 表 DAG 编排（§4~§8）**未落地**，且已被
++> docs/scheduler-architecture.md 的「work_items 队列 + 消费者池 + daemon 调度」路线取代；
++> §2/§6/§7 相关段落为历史设计，仅存档参考。2026-08-08（P5）已删除 flows 表与
++> tasks.flow_id 列（表重建迁移）。
+ > 关联文档：docs/service-architecture.md（服务化总体架构，本文档是其演进）
+ 
+ ## 1. 需求确认结论
+ 
+ | 议题 | 结论 |
+ |---|---|
+ | 核心目标 | 任务逻辑从"写死在 Python 控制流"升级为"原子能力（Atom）+ 编排层（DAG）"，流水线可保存、可复用、可视化 |
+ | 颗粒度 | 两级：编排 DAG 为粗粒度（单任务 5~15 节点）；重试/换 IP/熔断等控制流是**节点策略配置**，不画成 DAG 的边 |
+ | 循环表达 | 容器节点（如 `for_each_shop` 带子图），DAG 保持无环，不画回边 |
+ | 并发表达 | 容器节点的 `parallel: N` 属性，引擎负责起 N 个执行上下文并管理共享配额；不在图中画并行分支 |
+ | worker 可观测 | 并行容器节点可下钻，能看到每个 worker 独立的执行轨迹、当前所在子节点、各自进度 |
+ | 节点实时进度 | 每种节点实时上报运行时状态（elapsed / 自定义进度字段），前端看板画进度条/环形图；Sleep 要能看到已睡多久 |
+ | 资源生命周期 | 引擎统一管理：DAG 声明资源（通道/浏览器），入口 acquire、出口 release（含异常兜底）；原子经 `ctx` 取用；SwapIP 换通道必须经引擎接口报备 |
+ | 流水线保存 | `flows` 表存「DAG 结构 + 全部节点参数」为模板（重试策略、是否换 IP、sleep 时长与浮动区间等）；执行时选模板 + 补少量运行时变量一键运行；模板可复制出新版本 |
+ | 前端分期 | v1 只读流程图 + 实时节点状态看板（非静态图，轮询/SSE 刷新）；v2 可视化拖拽编辑器 |
+ | 迁移策略 | 不动现有 `shop_crawl` / `contact_fetch`；新增独立 `flow` 任务类型；内置模板 1:1 复刻现有两任务行为，灰度验证等价后逐步替代、最终下线旧实现 |
+ 
+-## 2. 分层架构
++## 2. 分层架构（现状）
+ 
+ ```
+ ┌────────────────────────────────────────────────────┐
+-│ 编排层  flows 表（DAG JSON 模板，可保存/复制/版本）   │  ← 新增
++│ 调度层  fetcher daemon：QueueRouter 多队列调度       │  ← 现状
++│         消费者池（work_items 队列 + 跨站冷却填充，   │
++│         见 scheduler-architecture.md）               │
+ ├────────────────────────────────────────────────────┤
+-│ 引擎层  FlowExecutor                                 │  ← 新增
+-│         拓扑执行 · 容器节点 · 并行上下文 · 资源管理     │
+-│         节点级状态上报 · 协作式停止                    │
++│ 引擎层  Engine + CrawlLoop / LocalLoop               │  ← 现状
++│         逐工作项执行（认领→IP 保鲜→fetch→簿记）      │
+ ├────────────────────────────────────────────────────┤
+-│ 原子层  Atom Registry（能力目录，标准契约）            │  ← 从现有代码抽取
+-│         sleep / swap_ip / fetch_contact / ...        │
++│ 原子层  Atom Registry（能力目录，标准契约）          │  ← 现状（§3 已落地）
++│         sleep / swap_ip / fetch_contact / ...       │
+ ├────────────────────────────────────────────────────┤
+-│ 资源层  通道池 PoolManager · CloakBrowser · ShopDB    │  ← 基本不变
+-│         TaskRuntime（事件/进度/心跳/停止）             │
++│ 资源层  通道池 · BrowserManager · ShopDB             │  ← 现状
++│         事件/进度落 SQLite（task_events/progress_json）│
+ └────────────────────────────────────────────────────┘
+ ```
+ 
+ 关键决策说明：
+ 
+-- **策略不下放成边**：`on_blocked: {do: swap_ip, retry: 2}` 这类声明式配置由引擎的策略拦截器统一执行，原子本身只负责"做一件事并报告结果分类（ok / blocked / net_error）"。控制流复杂度收敛在引擎一处，DAG 图保持干净。
+-- **原子只报告，不决策**：原子不感知重试次数、不决定是否换 IP；这些决策在引擎策略层。这使原子可独立测试。
+-- **引擎寄生在现有 Celery 模型上**：`flow` 任务类型 = 一个通用 Celery 入口 `run_flow(task_id)`，引擎在该进程内驱动整个 DAG；多 worker 并行仍是任务内多线程（与现状一致），不引入跨进程编排复杂度。
+-- **TaskRuntime 复用**：事件流、progress_json、Redis 心跳、stop_requested 协作式停止全部沿用，只是事件/进度的粒度从"任务"细化到"节点"（data 里带 `node_id` / `worker_id`）。
++- **策略不下放成边**：`on_blocked: {do: swap_ip, retry: 2}` 这类声明式配置由策略层统一执行，原子本身只负责"做一件事并报告结果分类（ok / blocked / net_error）"。控制流复杂度收敛在策略层一处，流水线保持干净。（现状一致，保留）
++- **原子只报告，不决策**：原子不感知重试次数、不决定是否换 IP；这些决策在策略层。这使原子可独立测试。（现状一致，保留）
++- **任务执行**：任务由 daemon 的消费者执行（Engine/CrawlLoop 或 LocalLoop），跨任务编排是队列 + 消费者池（见 scheduler-architecture.md §3/§5），无 Celery。
++- **事件与进度**：事件/进度写 SQLite（task_events / progress_json），无 Redis 心跳；协作式停止走 stop_requested 与循环 Timer（平台 runner）。
+ 
+ ## 3. 原子（Atom）契约与清单
+ 
+ ### 3.1 契约
+ 
+ ```python
+ class Atom:
+     name: str                    # 注册名，如 "swap_ip"
+     title: str                   # 显示名，如 "更换出口 IP"
+     inputs: dict                 # 需要的 ctx 键，如 {"channel": "Channel"}
+@@ -186,20 +191,23 @@ ctx.stop_requested()          # 协作式停止检查
+ ```
+ 
+ ### 5.4 节点级状态上报
+ 
+ - 每个节点（含 worker 实例维度）维护运行时状态：`pending / running / ok / failed / skipped / aborted`，`started_at / finished_at / elapsed`，以及原子自定义的 `progress` 字段。
+ - 落点：任务 `progress_json` 增加 `nodes: {node_key: {...}}`（node_key = `节点id` 或 `节点id#w0`），与现有任务级字段共存；`task_events.data_json` 统一带 `node_id` / `worker_id`。
+ - 前端轮询/SSE 取 `progress_json.nodes` 渲染看板，无需新增推送通道。
+ 
+ ## 6. 存储设计（新增 1 张表 + tasks 表加列）
+ 
++> ⚠️ 本节为历史设计：flows 表与 tasks.flow_id 从未承载生产语义，P5（2026-08-08）
++> 已通过幂等表重建删除 flows 表与 flow_id 列。SQL 仅为存档。
++
+ ```sql
+ -- 流水线模板（DAG + 节点参数整体保存，可复制出新版本）
+ CREATE TABLE flows (
+     id          INTEGER PRIMARY KEY AUTOINCREMENT,
+     name        TEXT NOT NULL,            -- 如 "联系人提取·标准"
+     description TEXT,
+     dag_json    TEXT NOT NULL,            -- §4 定义
+     builtin     INTEGER NOT NULL DEFAULT 0,  -- 1=内置复刻模板（只读防误改）
+     created_at  TEXT NOT NULL,
+     updated_at  TEXT NOT NULL
+@@ -208,30 +216,32 @@ CREATE TABLE flows (
+ -- tasks 表加列（ALTER TABLE，不动现有行）
+ ALTER TABLE tasks ADD COLUMN flow_id INTEGER REFERENCES flows(id);
+ -- type 新增取值 "flow"；params_json 存 run_inputs 实参（如 {"limit": 100}）
+ ```
+ 
+ - 任务创建（type=flow）：`{flow_id, run_inputs}` → 快照 `dag_json` 进任务（防止模板后改影响历史任务的可追溯；快照存于 params_json._dag_snapshot）。
+ - 节点运行状态不落新表，走 `progress_json.nodes`（易过期、易重写，符合"看板"语义）；需要审计的细节已在 `task_events`。
+ 
+ ## 7. API 设计（新增）
+ 
++> 本节 flows/atoms 端点为历史设计，未实现；任务 API 现仅 tasks 通用端点。
++
+ ```
+-GET    /api/flows                 # 模板列表
+-POST   /api/flows                 # 新建模板（含 DAG 校验）
+-GET    /api/flows/{id}            # 模板详情
+-PUT    /api/flows/{id}            # 更新（builtin=1 拒绝）
+-POST   /api/flows/{id}/duplicate  # 复制出新版本
+-DELETE /api/flows/{id}            # 删除（被任务引用时仅标记 archived）
+-GET    /api/atoms                 # 原子目录（name/title/param_spec），前端表单/编辑器用
+-POST   /api/flows/validate        # 独立 DAG 校验（保存前调用）
+-POST   /api/tasks                 # type=flow 时传 {flow_id, run_inputs}
++GET    /api/flows                 # 模板列表（未落地）
++POST   /api/flows                 # 新建模板（含 DAG 校验）（未落地）
++GET    /api/flows/{id}            # 模板详情（未落地）
++PUT    /api/flows/{id}            # 更新（builtin=1 拒绝）（未落地）
++POST   /api/flows/{id}/duplicate  # 复制出新版本（未落地）
++DELETE /api/flows/{id}            # 删除（被任务引用时仅标记 archived）（未落地）
++GET    /api/atoms                 # 原子目录（name/title/param_spec），前端表单/编辑器用（未落地）
++POST   /api/flows/validate        # 独立 DAG 校验（保存前调用）（未落地）
++POST   /api/tasks                 # 通用任务创建；type=flow 时传 {flow_id, run_inputs}（flow 分支未落地）
+ ```
+ 
+ 任务进度接口 `GET /api/tasks/{id}` 的响应中 `progress.nodes` 即节点看板数据，结构：
+ 
+ ```jsonc
+ {
+   "collected": 42, "pending": 300, "per_minute": 3.1,
+   "nodes": {
+     "start_delay": {"status": "ok", "elapsed": 12.0},
+     "loop":        {"status": "running", "batch": 2, "parallel": 2},
+@@ -255,14 +265,14 @@ POST   /api/tasks                 # type=flow 时传 {flow_id, run_inputs}
+ |---|---|---|
+ | P0 原子抽取 | Atom 契约 + Registry；从两个现有 worker 抽出 §3.2 清单原子（只改组织形式，不改行为） | 原子单测可独立跑通 |
+ | P1 引擎 | FlowExecutor（拓扑/容器/并行/策略拦截/资源管理/节点状态上报）+ flows 表 + `run_flow` + §7 API | 单元级 DAG 可执行 |
+ | P2 内置模板 | 内置 2 个模板 1:1 复刻 `shop_crawl` / `contact_fetch`；灰度跑通，对比旧任务行为等价（事件序列、抓取结果口径） | 同参数下产出一致 |
+ | P3 前端看板 | 流水线页 + 只读 DAG 图 + 节点实时看板 + worker 下钻 | 看板实时反映执行 |
+ | P4 替代 | 新任务默认走 flow；旧类型冻结（不再加功能），稳定一个周期后下线旧实现 | 旧代码路径删除 |
+ | P5 编辑器（v2） | 可视化拖拽编辑 + 保存/校验 | 前端可新建模板 |
+ 
+ ## 10. 明确的非目标（v1 不做）
+ 
+-- 跨任务/跨进程的 DAG 编排（引擎只在单任务进程内）
++- 跨任务 DAG 编排不做（引擎只消费队列，不关心流水线内部拓扑）；跨任务队列调度已由 daemon 实现（scheduler-architecture.md §3/§5）
+ - 任意条件分支图（if/else 边）；条件能力由策略配置覆盖
+ - 模板版本 diff / 回滚（仅支持复制出新模板）
+ - 多用户/权限（沿用单机无鉴权前提）
+diff --git a/fetcher/README.md b/fetcher/README.md
+index b946cbe..02b5284 100644
+--- a/fetcher/README.md
++++ b/fetcher/README.md
+@@ -82,14 +82,17 @@ python -m pytest tests -x -q
+ ```
+ 
+ 全部 mock：不起真实浏览器、不发真实网络请求、不碰真实数据库（临时 sqlite）。
+ 当前 85 个用例：Detector / Policy / IdentityStore（P0+P1）+ CrawlLoop
+ 集成 + contact 任务 + Engine 编排（P2+P3）+ 站点扩展性（P4：第三方
+ 最小站点注册并跑通 CrawlLoop、taobao 探测器域隔离、解析器/validate/
+ fetch 门控、策略覆盖）。
+ 
+ ## 本阶段边界
+ 
++平台任务走 daemon 批次模型（work_items 队列）；站点子命令 CLI（1688/madeinchina
++shop|contact|company）仅供手动/调试，与 daemon 同站互斥约定不变。
++
+ P2+P3 已交付控制层与 CLI。P3 已落地：多队列多站点调度（daemon 常驻）、
+ BrowserContext 多站点隔离（一消费者一浏览器进程、每站点独立 context）、
+ SwapIP 无头两阶段、shop/company feeder 队列（work_items 驱动）。
+ 遗留：多进程类目池互斥、换 IP 等待期的 item 级调度（见 docs/design.md §14）。
+diff --git a/platform/server/app/api/tasks.py b/platform/server/app/api/tasks.py
+index cdadc70..4378964 100644
+--- a/platform/server/app/api/tasks.py
++++ b/platform/server/app/api/tasks.py
+@@ -2,22 +2,22 @@
+ import asyncio
+ import json
+ import sqlite3
+ from datetime import datetime, timedelta
+ 
+ from fastapi import APIRouter, HTTPException, Request
+ from fastapi.responses import StreamingResponse
+ from pydantic import BaseModel, Field
+ 
+ from app.db import DB_PATH, connect
+-from app.runner import (BATCH_TYPE_NAMES, BATCH_TYPES, IN_PROCESS_TYPES,
+-                        PYTHON_BIN, TASK_COMMANDS, beijing_now, build_command,
++from app.runner import (BATCH_TYPE_NAMES, BATCH_TYPES, PYTHON_BIN,
++                        TASK_COMMANDS, beijing_now, build_command,
+                         enqueue_batch_for_task, runner, stop_batch_task,
+                         _insert_event)
+ 
+ router = APIRouter()
+ 
+ TASK_TYPES = sorted(set(TASK_COMMANDS) | set(BATCH_TYPES))
+ 
+ 
+ def _parse_json(text):
+     if not text:
+@@ -106,27 +106,23 @@ class TaskParams(BaseModel):
+     stagger_max: float | None = None        # → --stagger-max
+     ip_retry: int | None = None             # → --ip-retry
+     net_retry: int | None = None            # → --net-retry
+     max_consecutive_fail: int | None = None  # → --max-consecutive-fail
+     block_rest_min: float | None = None     # → --block-rest-min
+     block_rest_max: float | None = None     # → --block-rest-max
+     # 开关
+     use_proxy: bool | None = None           # true → --proxy
+     headless: bool | None = None            # false → --headed
+     auto_solve: bool | None = None          # false → --no-auto-solve
+-    retry_failed: bool | None = None        # true 且 1688_contact → --retry-failed
+-    # wa_check（进程内 WhatsApp 查号）专用：
+-    interval: float | None = None           # 旧参数：固定调用间隔秒（等价
+-                                            # sample_min == sample_max）
++    retry_failed: bool | None = None        # 前端 1688_contact 表单开关遗留，不映射 CLI
++    # wa_check 专用：
+     accounts: list[str] | None = None       # 账号池，空 = 仅默认账号
+-    batch_rest_min: float | None = None     # wa_check 批间休息下限（秒）
+-    batch_rest_max: float | None = None     # wa_check 批间休息上限（秒）
+     # 注：wa_check 复用上方 batch_num（每批调用次数）、
+     # sample_min / sample_max（调用间隔范围）三个字段
+     # 循环模式：本轮正常结束（done/failed）后 N 秒自动重启；None/<=0 = 不循环
+     repeat_interval: int | None = None
+ 
+ 
+ class TaskCreate(BaseModel):
+     type: str = Field(...)
+     params: TaskParams = Field(default_factory=TaskParams)
+ 
+@@ -161,54 +157,35 @@ def _get_task_row(task_id: int):
+         row = conn.execute("SELECT * FROM tasks WHERE id=?",
+                            (task_id,)).fetchone()
+     if not row:
+         raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
+     return row
+ 
+ 
+ # ---------------- 命令预览 / 参数修改 ----------------
+ 
+ 
+-class CommandParse(BaseModel):
+-    command: str = Field(..., min_length=1)
+-
+-
+-@router.post("/tasks/parse")
+-def parse_task_command(body: CommandParse):
+-    """把 fetcher CLI 命令文本解析回 type + params（build_command 的反向）。
+-
+-    容忍 python -m fetcher / 直接 fetcher 前缀与 while/for + sleep N 循环包裹。
+-    """
+-    from app.cmdparse import CommandParseError, parse_command
+-    try:
+-        return parse_command(body.command)
+-    except CommandParseError as e:
+-        raise HTTPException(status_code=422, detail=str(e))
+-
+-
+ @router.post("/tasks/preview")
+ def preview_task(body: TaskCreate):
+     """按 type + params 预览实际将执行的 fetcher CLI 命令（不落库）。"""
+     if body.type not in TASK_TYPES:
+         raise HTTPException(
+             status_code=422,
+             detail=f"未知任务类型 {body.type!r}，可选: {TASK_TYPES}")
+     params = body.params.model_dump()
+     if body.type in BATCH_TYPE_NAMES:
+         spec = BATCH_TYPES[body.type]
+         limit = params.get("limit")
+         desc = f"批次提交：{spec['queue']}"
+         if limit:
+             desc += f"，{limit} 条"
+         return {"cmd": None, "cmdline": desc}
+-    if body.type in IN_PROCESS_TYPES:
+-        return {"cmd": None, "cmdline": "进程内执行（CheckWhatsApp 原子）"}
+     try:
+         cmd = build_command(body.type, params)
+     except ValueError as e:
+         raise HTTPException(status_code=422, detail=str(e))
+     # 展示串：绝对路径 python 换成 python，保持真实可读
+     cmdline = " ".join("python" if p == PYTHON_BIN else p for p in cmd)
+     return {"cmd": cmd, "cmdline": cmdline}
+ 
+ 
+ class TaskUpdate(BaseModel):
+diff --git a/platform/server/app/cmdparse.py b/platform/server/app/cmdparse.py
+deleted file mode 100644
+index 8b554c5..0000000
+--- a/platform/server/app/cmdparse.py
++++ /dev/null
+@@ -1,169 +0,0 @@
+-# -*- coding: utf-8 -*-
+-"""fetcher CLI 命令文本 → 任务 type + params 的反向解析（POST /api/tasks/parse）。
+-
+-容忍形式：
+-- python -m fetcher ... / python3 -m fetcher ... / 直接 fetcher ...
+-- while/for 循环包裹 + sleep N → repeat_interval=N（秒）
+-
+-flag 映射与 runner.build_command 正好反向。
+-"""
+-
+-import re
+-import shlex
+-
+-
+-class CommandParseError(ValueError):
+-    """命令无法识别 → API 层转 422。"""
+-
+-
+-# (站点, 子任务) → 平台任务类型
+-SITE_TASKS = {
+-    ("1688", "shop"): "1688_shop",
+-    ("1688", "contact"): "1688_contact",
+-    ("1688", "company"): "1688_company",
+-    ("yiwugo", "search"): "yiwugo_search",
+-}
+-
+-# 开关 flag → (params 键, 置为的值)
+-_BOOL_FLAGS = {
+-    "--proxy": ("use_proxy", True),
+-    "--headed": ("headless", False),
+-    "--no-auto-solve": ("auto_solve", False),
+-    "--retry-failed": ("retry_failed", True),
+-}
+-
+-# 取值 flag → (params 键, 类型转换)；含 argparse 缩写形式 --worker
+-_VALUE_FLAGS = {
+-    "-n": ("batch_num", int),
+-    "--num": ("batch_num", int),
+-    "--limit": ("limit", int),
+-    "--max-batches": ("max_batches", int),
+-    "--workers": ("workers", int),
+-    "--worker": ("workers", int),
+-    "--channels": ("channels", int),
+-    "--batch-rest": ("batch_rest", float),
+-    "--sample-min": ("sample_min", float),
+-    "--sample-max": ("sample_max", float),
+-    "--rest-every": ("rest_every", int),
+-    "--rest-min": ("rest_min", float),
+-    "--rest-max": ("rest_max", float),
+-    "--stagger-min": ("stagger_min", float),
+-    "--stagger-max": ("stagger_max", float),
+-    "--ip-retry": ("ip_retry", int),
+-    "--net-retry": ("net_retry", int),
+-    "--max-consecutive-fail": ("max_consecutive_fail", int),
+-    "--block-rest-min": ("block_rest_min", float),
+-    "--block-rest-max": ("block_rest_max", float),
+-}
+-
+-# 解释器 / 模块调用前缀
+-_PREFIX_WORDS = {"python", "python3", "-m", "fetcher"}
+-
+-# shell 循环 / 结构关键字（静默忽略，不进 warnings）
+-_LOOP_WORDS = {"while", "do", "done", "true", "for", "in", "then", "fi",
+-               "if", "until", "until", "esac", "case"}
+-
+-_NUM_RE = re.compile(r"^\d+(\.\d+)?$")
+-
+-
+-def parse_command(command: str) -> dict:
+-    """命令文本 → {"type": ..., "params": {...}, "warnings": [...]}。
+-
+-    无法识别站点任务时抛 CommandParseError。
+-    """
+-    warnings: list[str] = []
+-    try:
+-        tokens = shlex.split(command or "")
+-    except ValueError as e:
+-        raise CommandParseError(f"命令切分失败: {e}")
+-    # shell 分号会黏在 token 尾部（如 "true;" "1800;"），统一剥掉
+-    tokens = [t.rstrip(";") for t in tokens]
+-    tokens = [t for t in tokens if t]
+-    if not tokens:
+-        raise CommandParseError("空命令")
+-
+-    params: dict = {}
+-
+-    # ---- 循环识别：sleep N（配合 while/for 循环或直接出现）----
+-    cleaned: list[str] = []
+-    i = 0
+-    while i < len(tokens):
+-        tok = tokens[i]
+-        if tok == "sleep" and i + 1 < len(tokens) and _NUM_RE.match(tokens[i + 1]):
+-            n = int(float(tokens[i + 1]))
+-            if n > 0:
+-                params["repeat_interval"] = n
+-                warnings.append(f"检测到循环包裹，已设为每 {n} 秒自动重启")
+-            i += 2
+-            continue
+-        cleaned.append(tok)
+-        i += 1
+-
+-    # ---- 定位站点任务：1688 shop/contact/company、yiwugo search ----
+-    idx = None
+-    for j, tok in enumerate(cleaned):
+-        if tok in ("1688", "yiwugo"):
+-            idx = j
+-            break
+-    if idx is None:
+-        raise CommandParseError(
+-            "无法识别站点任务：未找到 1688 / yiwugo 子命令；"
+-            "支持 1688 shop|contact|company、yiwugo search")
+-    if idx + 1 >= len(cleaned):
+-        raise CommandParseError(f"站点 {cleaned[idx]!r} 后缺少任务名")
+-    site, task = cleaned[idx], cleaned[idx + 1]
+-    task_type = SITE_TASKS.get((site, task))
+-    if not task_type:
+-        raise CommandParseError(
+-            f"无法识别的任务 {site} {task!r}；"
+-            "支持 1688 shop|contact|company、yiwugo search")
+-
+-    # ---- 站点前的 token：解释器前缀 / 循环关键字跳过，其余进 warnings ----
+-    for tok in cleaned[:idx]:
+-        if tok in _PREFIX_WORDS or tok in _LOOP_WORDS:
+-            continue
+-        warnings.append(f"无法识别的 token: {tok}")
+-
+-    # ---- flag 解析（与 build_command 反向）----
+-    rest = cleaned[idx + 2:]
+-    i = 0
+-    while i < len(rest):
+-        tok = rest[i]
+-        if tok in _BOOL_FLAGS:
+-            key, val = _BOOL_FLAGS[tok]
+-            params[key] = val
+-            i += 1
+-        elif tok in _VALUE_FLAGS:
+-            key, conv = _VALUE_FLAGS[tok]
+-            if i + 1 >= len(rest):
+-                warnings.append(f"参数 {tok} 缺少取值，已忽略")
+-                i += 1
+-                continue
+-            raw = rest[i + 1]
+-            try:
+-                params[key] = conv(raw)
+-            except ValueError:
+-                warnings.append(f"参数 {tok} 取值 {raw!r} 无法解析，已忽略")
+-            i += 2
+-        elif tok.startswith("--") and "=" in tok:
+-            # --flag=value 形式
+-            flag, _, raw = tok.partition("=")
+-            if flag in _VALUE_FLAGS:
+-                key, conv = _VALUE_FLAGS[flag]
+-                try:
+-                    params[key] = conv(raw)
+-                except ValueError:
+-                    warnings.append(f"参数 {flag} 取值 {raw!r} 无法解析，已忽略")
+-            elif flag in _BOOL_FLAGS:
+-                key, val = _BOOL_FLAGS[flag]
+-                params[key] = val
+-            else:
+-                warnings.append(f"无法识别的 token: {tok}")
+-            i += 1
+-        elif tok in _LOOP_WORDS:
+-            i += 1
+-        else:
+-            warnings.append(f"无法识别的 token: {tok}")
+-            i += 1
+-
+-    return {"type": task_type, "params": params, "warnings": warnings}
+diff --git a/platform/server/app/db.py b/platform/server/app/db.py
+index 7d3ab1e..ee6d11d 100644
+--- a/platform/server/app/db.py
++++ b/platform/server/app/db.py
+@@ -90,20 +90,58 @@ def migrate() -> None:
+             "CREATE INDEX IF NOT EXISTS idx_channels_task"
+             " ON proxy_channels(used_by_task)")
+         # P4：work_items 批次索引（生产库表由 fetcher 建，平台只补索引不建表；
+         # 探测式——表不存在则跳过，防御性）
+         tables = {r[0] for r in conn.execute(
+             "SELECT name FROM sqlite_master WHERE type='table'")}
+         if "work_items" in tables:
+             conn.execute(
+                 "CREATE INDEX IF NOT EXISTS idx_work_items_batch"
+                 " ON work_items(batch_id, status)")
++        # P5：tasks 表重建——删除 celery_id/flow_id 死列与 flows 表（方案 B 交换式）
++        # 守卫：旧 schema 才重建；已迁移库重跑 migrate() 零变化（幂等）。
++        # 交换顺序（建 tasks_new → INSERT SELECT → DROP tasks → RENAME）保证
++        # task_events/proxy_channels 的 REFERENCES tasks(id) 不被 SQLite RENAME
++        # 重写成指向被删表名（RENAME-first 会让外键悬空）。
++        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
++        if "celery_id" in cols:
++            conn.execute("BEGIN IMMEDIATE")
++            try:
++                conn.execute("""
++                    CREATE TABLE tasks_new (
++                        id INTEGER PRIMARY KEY AUTOINCREMENT,
++                        type TEXT NOT NULL,
++                        params_json TEXT NOT NULL,
++                        status TEXT NOT NULL DEFAULT 'pending',
++                        progress_json TEXT,
++                        stop_requested INTEGER NOT NULL DEFAULT 0,
++                        error TEXT,
++                        created_at TEXT NOT NULL,
++                        started_at TEXT,
++                        finished_at TEXT
++                    )""")
++                conn.execute("""
++                    INSERT INTO tasks_new (id, type, params_json, status,
++                                           progress_json, stop_requested, error,
++                                           created_at, started_at, finished_at)
++                    SELECT id, type, params_json, status, progress_json,
++                           stop_requested, error, created_at, started_at,
++                           finished_at
++                    FROM tasks""")
++                conn.execute("DROP TABLE tasks")
++                conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
++                conn.execute("DROP TABLE IF EXISTS flows")
++                conn.execute("CREATE INDEX idx_tasks_status ON tasks(status)")
++                conn.execute("COMMIT")
++            except Exception:
++                conn.execute("ROLLBACK")  # 失败留原表（tasks 未动）
++                raise
+         conn.commit()
+     finally:
+         conn.close()
+ 
+ 
+ # ==================== P4 批次入队（平台侧 SQL，与 fetcher 同事务语义） ====================
+ # SPEC §3.1 裁定：平台不 import fetcher，批次 SQL 平台侧重写；两边重复
+ # 是有意为之的边界，语义由同一 SPEC + 测试锚定。
+ 
+ 
+@@ -220,21 +258,21 @@ def _normalize_numbers(raw, default_cc="86"):
+         if 8 <= len(digits) <= 15 and digits not in seen:
+             seen.add(digits)
+             out.append(digits)
+     return out
+ 
+ 
+ def enqueue_wa_batch(batch_id: int, accounts: list[str],
+                      limit: int = 0) -> int:
+     """wa_check 批次入队：contacts 未查号码 → 50/块 → 账号按块轮换。
+ 
+-    accounts 为空拒绝（防空跑 default 主号，与 wa_tasks 拒绝语义一致）。
++    accounts 为空拒绝（防空跑 default 主号）。
+     requires=["local"]、site=NULL。返回入队 item 数。
+     """
+     accounts = [str(a).strip() for a in (accounts or []) if str(a).strip()]
+     if not accounts:
+         return 0
+     conn = sqlite3.connect(DB_PATH, timeout=30)
+     try:
+         conn.execute("PRAGMA busy_timeout = 30000")
+         sql = ("SELECT mobile FROM contacts WHERE wa_checked_at IS NULL"
+                " AND mobile IS NOT NULL AND TRIM(mobile) <> ''"
+diff --git a/platform/server/app/runner.py b/platform/server/app/runner.py
+index 22a4742..877ff9f 100644
+--- a/platform/server/app/runner.py
++++ b/platform/server/app/runner.py
+@@ -23,24 +23,20 @@ from datetime import datetime, timedelta, timezone
+ from app.db import DB_PATH, migrate
+ 
+ PROJECT_ROOT = "/Volumes/DataDrive/proj/public/1699"
+ PYTHON_BIN = os.path.join(PROJECT_ROOT, "platform/server/.venv/bin/python")
+ 
+ # 任务类型 → fetcher CLI 子命令（P4：只剩 yiwugo_search，其余批次化）
+ TASK_COMMANDS = {
+     "yiwugo_search": ["yiwugo", "search"],
+ }
+ 
+-# 进程内任务类型（P4：清空——wa_check 迁入 daemon LocalExecutor；
+-# wa_tasks.py 冻结不删，P5 移除）
+-IN_PROCESS_TYPES: set[str] = set()
+-
+ # 批次任务类型 → 队列映射（P4：平台创建/停止/监控全流程走 dispatcher）。
+ # 值：{"queue", "enqueue"}——enqueue 为平台侧批次入队函数。
+ # contact 类带 domain_suffix（按来源过滤）；feeder/wa 无。
+ BATCH_TYPES = {
+     "1688_contact": {
+         "queue": "crawl_1688_contact", "site": "1688",
+         "domain_suffix": ".1688.com", "kind": "contact",
+     },
+     "madeinchina_contact": {
+         "queue": "crawl_mic_contact", "site": "madeinchina",
+@@ -114,40 +110,36 @@ _NUMERIC_FLAGS = (
+ )
+ 
+ 
+ def build_command(task_type: str, params: dict) -> list:
+     """任务类型 + params → fetcher CLI 命令列表（subprocess 直接 Popen）。
+ 
+     规则：
+     - 数值/时长参数值非 None 才输出（缺省=CLI 自带默认值，保持命令干净）；
+     - 开关：use_proxy=true→--proxy；headless=false→--headed；
+       auto_solve=false→--no-auto-solve；
+-      retry_failed=true 且 1688_contact→--retry-failed；
+-    - wa_check 等进程内类型不走这里。
+     """
+     sub = TASK_COMMANDS.get(task_type)
+     if not sub:
+         raise ValueError(f"未知任务类型: {task_type}")
+     params = params or {}
+     cmd = [PYTHON_BIN, "-m", "fetcher"] + sub
+     for key, flag in _NUMERIC_FLAGS:
+         val = params.get(key)
+         if val is not None:
+             cmd += [flag, str(val)]
+     if params.get("use_proxy") is True:
+         cmd.append("--proxy")
+     if params.get("headless") is False:
+         cmd.append("--headed")
+     if params.get("auto_solve") is False:
+         cmd.append("--no-auto-solve")
+-    if task_type == "1688_contact" and params.get("retry_failed") is True:
+-        cmd.append("--retry-failed")
+     return cmd
+ 
+ 
+ def _db_write(sql: str, params=()) -> None:
+     """短事务写入；busy_timeout 避免与 WAL 写入者冲突。"""
+     conn = sqlite3.connect(DB_PATH, timeout=30)
+     try:
+         conn.execute("PRAGMA busy_timeout = 30000")
+         conn.execute(sql, params)
+         conn.commit()
+@@ -332,26 +324,24 @@ def _extract_worker(line: str):
+     m = _WORKER_NUM_RE.match(line)
+     if m:
+         return {"worker": int(m.group(1))}
+     m = _WORKER_IDENTITY_RE.search(line)
+     if m:
+         return {"worker": m.group(1)}
+     return None
+ 
+ 
+ class _RunEntry:
+-    __slots__ = ("proc", "thread", "stop_requested", "lines", "tail", "lock",
+-                 "stop_event")
++    __slots__ = ("proc", "thread", "stop_requested", "lines", "tail", "lock")
+ 
+-    def __init__(self, proc=None, stop_event=None):
+-        self.proc = proc              # subprocess 任务非空；进程内任务为 None
+-        self.stop_event = stop_event  # 进程内任务的停止信号
++    def __init__(self, proc=None):
++        self.proc = proc
+         self.thread = None
+         self.stop_requested = False
+         self.lines = 0
+         self.tail = []
+         self.lock = threading.Lock()
+ 
+ 
+ class TaskRunner:
+     """进程注册表在内存；随 FastAPI lifespan 初始化。"""
+ 
+@@ -423,70 +413,60 @@ class TaskRunner:
+         # 重启前处于循环模式等待期的任务：重新安排自动重启，避免丢失后
+         # 任务永远停在 done/failed（见 _recover_loop_restarts）。
+         try:
+             self._recover_loop_restarts()
+         except Exception as e:
+             print(f"[runner] 恢复循环重启失败: {e}")
+         # P4：启动批次 sweeper（对非终态批次任务做状态重建/进度聚合）
+         self._start_sweeper()
+ 
+     def shutdown(self) -> None:
+-        """服务关闭：停 sweeper；取消待重启 Timer；终止仍在跑的子进程 /
+-        通知进程内任务停止。"""
++        """服务关闭：停 sweeper；取消待重启 Timer；终止仍在跑的子进程。"""
+         # P4：停批次 sweeper
+         self._stop_sweeper()
+         with self._lock:
+             timers = list(self._timers.values())
+             self._timers.clear()
+             entries = list(self._runs.items())
+         for timer in timers:
+             timer.cancel()
+         for task_id, entry in entries:
+-            if entry.stop_event is not None:
+-                entry.stop_event.set()
+-                continue
+             proc = entry.proc
+             if proc is not None and proc.poll() is None:
+                 try:
+                     proc.terminate()
+                     proc.wait(timeout=5)
+                 except Exception:
+                     try:
+                         proc.kill()
+                     except Exception:
+                         pass
+-        # 等进程内任务线程收尾（wa 原子会随 stop_event 终止 node 子进程）
+-        for task_id, entry in entries:
+-            if entry.stop_event is not None and entry.thread:
+-                entry.thread.join(timeout=10)
+ 
+     # ---------- 启动 / 停止 ----------
+ 
+     def start(self, task_id: int, task_type: str, params: dict):
+         """启动任务：批次类型走平台入队；yiwugo 走 subprocess。
+ 
+         返回 pid（subprocess）或 None（批次）。
+         """
+         if task_type in BATCH_TYPE_NAMES:
+             try:
+                 n = enqueue_batch_for_task(task_id, task_type, params)
+             except Exception as e:  # noqa: BLE001
+                 print(f"[runner] 批次 {task_id} 入队失败: {e}")
+                 raise
+             _insert_event(
+                 task_id, "info",
+                 f"批次已提交：{BATCH_TYPES[task_type]['queue']}，"
+                 f"{n} 个工作项",
+                 {"queue": BATCH_TYPES[task_type]["queue"], "items": n})
+             return None
+-        if task_type in IN_PROCESS_TYPES:
+-            return self._start_in_process(task_id, task_type, params)
+         cmd = build_command(task_type, params)
+         env = dict(os.environ, PYTHONUNBUFFERED="1")
+         proc = subprocess.Popen(
+             cmd,
+             cwd=PROJECT_ROOT,
+             stdout=subprocess.PIPE,
+             stderr=subprocess.STDOUT,
+             text=True,
+             bufsize=1,
+             errors="replace",
+@@ -499,79 +479,23 @@ class TaskRunner:
+             target=self._pump, args=(task_id, entry, cmd), daemon=True,
+             name=f"task-pump-{task_id}",
+         )
+         entry.thread = t
+         t.start()
+         _insert_event(task_id, "info",
+                       f"进程已启动 pid={proc.pid} 命令={' '.join(cmd)}"[:500],
+                       {"pid": proc.pid, "cmd": cmd})
+         return proc.pid
+ 
+-    def _start_in_process(self, task_id: int, task_type: str, params: dict):
+-        """进程内任务：派生线程跑执行器（如 wa_tasks.run），stop_event 停止。"""
+-        stop_event = threading.Event()
+-        entry = _RunEntry(None, stop_event)
+-        with self._lock:
+-            self._runs[task_id] = entry
+-        t = threading.Thread(
+-            target=self._run_in_process,
+-            args=(task_id, entry, task_type, params),
+-            daemon=True, name=f"task-inproc-{task_id}",
+-        )
+-        entry.thread = t
+-        t.start()
+-        _insert_event(task_id, "info",
+-                      f"进程内任务已启动 type={task_type}",
+-                      {"type": task_type})
+-        return None
+-
+-    def _run_in_process(self, task_id: int, entry: _RunEntry,
+-                        task_type: str, params: dict) -> None:
+-        try:
+-            if task_type == "wa_check":
+-                from app import wa_tasks  # 延迟导入，避免与 runner 循环依赖
+-                wa_tasks.run(task_id, params, entry.stop_event)
+-            else:
+-                raise ValueError(f"未知进程内任务类型: {task_type}")
+-        except Exception as e:
+-            # 双保险：执行器自身已 try/finalize，这里兜底未捕获的异常
+-            print(f"[runner] 进程内任务 {task_id} 异常: {e}")
+-            try:
+-                _insert_event(task_id, "error", f"进程内执行器异常: {e}")
+-                _db_write(
+-                    "UPDATE tasks SET status='failed', error=?, finished_at=? "
+-                    "WHERE id=? AND status='running'",
+-                    (f"进程内执行器异常: {e}"[:500], beijing_now(), task_id),
+-                )
+-            except Exception:
+-                pass
+-        finally:
+-            with self._lock:
+-                self._runs.pop(task_id, None)
+-            # 进程内任务循环模式：执行器自身已回写终态，按 DB 状态决定是否重启
+-            try:
+-                conn = sqlite3.connect(DB_PATH, timeout=30)
+-                try:
+-                    conn.execute("PRAGMA busy_timeout = 30000")
+-                    row = conn.execute(
+-                        "SELECT status FROM tasks WHERE id=?",
+-                        (task_id,)).fetchone()
+-                finally:
+-                    conn.close()
+-                if row:
+-                    self._maybe_schedule_restart(task_id, row[0])
+-            except Exception as e:
+-                print(f"[runner] 进程内任务 {task_id} 重启调度失败: {e}")
+-
+     def stop(self, task_id: int) -> bool:
+         """先置 stop_requested=1；取消待重启 Timer；批次任务压 stopped
+-        pending 项；进程内任务置 stop_event，子进程 terminate。"""
++        pending 项；子进程 terminate。"""
+         _db_write("UPDATE tasks SET stop_requested=1 WHERE id=?", (task_id,))
+         # P4 批次：pending 项压 stopped（claimed 跑完自然终态）
+         try:
+             with self._lock:
+                 entry = self._runs.get(task_id)
+             if task_id not in self._runs:
+                 stop_batch_task(task_id)
+         except Exception as e:  # noqa: BLE001
+             print(f"[runner] 批次 {task_id} 停止失败: {e}")
+         timer_canceled = self.cancel_timer(task_id)
+@@ -582,23 +506,20 @@ class TaskRunner:
+                 # 本轮已结束、正在等待自动重启：直接落终态 stopped，不再重启
+                 _db_write(
+                     "UPDATE tasks SET status='stopped', finished_at=? "
+                     "WHERE id=? AND status IN ('done', 'failed')",
+                     (beijing_now(), task_id))
+                 _insert_event(task_id, "warning",
+                               "循环模式：已取消自动重启（手动停止）")
+                 return True
+             return False
+         entry.stop_requested = True
+-        if entry.stop_event is not None:
+-            entry.stop_event.set()
+-            return True
+         proc = entry.proc
+         if proc is not None and proc.poll() is None:
+             try:
+                 proc.terminate()
+                 proc.wait(timeout=5)
+             except subprocess.TimeoutExpired:
+                 proc.kill()
+             except Exception:
+                 pass
+         return True
+diff --git a/platform/server/app/wa_tasks.py b/platform/server/app/wa_tasks.py
+deleted file mode 100644
+index 5d50385..0000000
+--- a/platform/server/app/wa_tasks.py
++++ /dev/null
+@@ -1,445 +0,0 @@
+-# -*- coding: utf-8 -*-
+-"""wa_check 进程内任务执行器（WhatsApp 全量查号）。
+-
+-与 subprocess 类任务不同：本执行器在 API 进程内的线程里跑，分批调用
+-fetcher 的 CheckWhatsApp 原子（原子内部每次调用会拉起 node 子进程连接
+-WhatsApp，约 5-10s/批，属正常）。
+-
+-流程：
+-- 待查号码：contacts 中 wa_checked_at IS NULL 且 mobile 非空，按 id 升序，
+-  params["limit"]>0 时限量；
+-- 规范化：fetcher normalize_numbers(mobile, default_cc="86")；
+-- 每批 50 个号码调一次原子；params["accounts"] 非空时按批轮换账号
+-  （"default" 映射为原子的缺省账号），空列表 = 仅默认账号；
+-- 每批写回 contacts（wa_registered/wa_checked_at，北京时间；按号码后 11 位
+-  对齐 mobile/phone，仅更新规范化后严格匹配的行，歧义则跳过）；
+-- 每批写 task_events + throttle 更新 tasks.progress_json
+-  {"total","checked","registered","current_account"}；
+-- stop_event 置位或 tasks.stop_requested=1（每批检查一次 DB）→ 优雅停止；
+-- 原子连续 FATAL（未登录/登出，不可自愈）→ failed。
+-
+-节奏控制（与其他采集任务同策略）：
+-- 逐号码间隔：params["sample_min"]/["sample_max"]（秒）范围内的随机停顿，
+-  在 check.js 逐号循环内生效（默认 1.5s 固定）；兼容旧参数
+-  params["interval"]（等价于 min == max）；
+-- 批次：每 params["batch_num"] 个号码（默认 500）为一批，采满后批间
+-  休息 params["batch_rest_min"]~["batch_rest_max"] 秒随机时长；
+-- 批间休息可被 stop_event 中断。
+-
+-DB 写入一律短事务 + busy_timeout（1688.db 为 WAL，正被采集进程写入）。
+-"""
+-
+-import json
+-import random
+-import sqlite3
+-import threading
+-import time
+-
+-from fetcher.atoms.wa_check import CheckWhatsApp, normalize_numbers
+-from fetcher.core.context import WorkerContext
+-from fetcher.core.types import Outcome
+-
+-from app.db import DB_PATH, migrate
+-from app.runner import _db_write, _insert_event, beijing_now
+-
+-BATCH_SIZE = 50
+-DEFAULT_CC = "86"
+-MAX_CONSECUTIVE_FATAL = 2
+-_PROGRESS_THROTTLE_SEC = 1.0
+-
+-# 风控冷却：批内错误率 ≥ 阈值判定疑似风控，批后额外长冷却（防风控加重）
+-THROTTLE_RATIO = 0.3
+-THROTTLE_COOLDOWN_MIN = 1200.0   # 20 分钟
+-THROTTLE_COOLDOWN_MAX = 1800.0   # 30 分钟
+-
+-# 节奏默认值：逐号码随机间隔 1.5s 固定（check.js 内部缺省）；
+-# 每 500 个号码一批，批间休息随机 60~180s
+-DEFAULT_SAMPLE_MIN = 1.5
+-DEFAULT_SAMPLE_MAX = 1.5
+-DEFAULT_BATCH_NUM = 500
+-DEFAULT_BATCH_REST_MIN = 60.0
+-DEFAULT_BATCH_REST_MAX = 180.0
+-
+-
+-def _pacing_params(params: dict) -> tuple[float, float, int, float, float]:
+-    """解析节奏参数：(sample_min, sample_max, batch_num, rest_min, rest_max)。
+-
+-    sample_min/max 为逐号码随机间隔（秒），batch_num 为每批号码数，
+-    rest_min/max 为批间休息范围（秒）。兼容旧参数 interval（固定间隔）：
+-    显式给了 interval 而没给 sample_min/sample_max 时，等价于
+-    sample_min == sample_max == interval。
+-    """
+-    interval = params.get("interval")
+-    sample_min = params.get("sample_min")
+-    sample_max = params.get("sample_max")
+-    if interval is not None:
+-        interval = float(interval)
+-        if sample_min is None:
+-            sample_min = interval
+-        if sample_max is None:
+-            sample_max = interval
+-    lo = float(sample_min) if sample_min is not None else DEFAULT_SAMPLE_MIN
+-    hi = float(sample_max) if sample_max is not None else DEFAULT_SAMPLE_MAX
+-    lo, hi = max(0.0, lo), max(0.0, hi)
+-    if lo > hi:
+-        lo, hi = hi, lo
+-    batch_num = int(params.get("batch_num") or DEFAULT_BATCH_NUM)
+-    r_lo = float(params.get("batch_rest_min")
+-                 if params.get("batch_rest_min") is not None
+-                 else DEFAULT_BATCH_REST_MIN)
+-    r_hi = float(params.get("batch_rest_max")
+-                 if params.get("batch_rest_max") is not None
+-                 else DEFAULT_BATCH_REST_MAX)
+-    r_lo, r_hi = max(0.0, r_lo), max(0.0, r_hi)
+-    if r_lo > r_hi:
+-        r_lo, r_hi = r_hi, r_lo
+-    return lo, hi, max(0, batch_num), r_lo, r_hi
+-
+-
+-def _fetch_pending_rows(limit: int) -> list:
+-    """待查联系人：wa_checked_at IS NULL 且 mobile 非空，id 升序。"""
+-    sql = ("SELECT id, mobile FROM contacts "
+-           "WHERE wa_checked_at IS NULL "
+-           "AND mobile IS NOT NULL AND TRIM(mobile) <> '' "
+-           "ORDER BY id ASC")
+-    params = ()
+-    if limit > 0:
+-        sql += " LIMIT ?"
+-        params = (limit,)
+-    conn = sqlite3.connect(DB_PATH, timeout=30)
+-    try:
+-        conn.execute("PRAGMA busy_timeout = 30000")
+-        return conn.execute(sql, params).fetchall()
+-    finally:
+-        conn.close()
+-
+-
+-def _db_stop_requested(task_id: int) -> bool:
+-    conn = sqlite3.connect(DB_PATH, timeout=30)
+-    try:
+-        conn.execute("PRAGMA busy_timeout = 30000")
+-        row = conn.execute(
+-            "SELECT stop_requested FROM tasks WHERE id=?",
+-            (task_id,)).fetchone()
+-        return bool(row and row[0])
+-    finally:
+-        conn.close()
+-
+-
+-def _write_progress(task_id: int, total: int, checked: int,
+-                    registered: int, current_account: str) -> None:
+-    progress = {
+-        "total": total,
+-        "checked": checked,
+-        "registered": registered,
+-        "current_account": current_account,
+-        "updated_at": beijing_now(),
+-    }
+-    try:
+-        _db_write(
+-            "UPDATE tasks SET progress_json=? WHERE id=?",
+-            (json.dumps(progress, ensure_ascii=False), task_id),
+-        )
+-    except Exception as e:
+-        print(f"[wa_tasks] task {task_id} 更新进度失败: {e}")
+-
+-
+-def _finalize(task_id: int, status: str, error: str | None) -> None:
+-    ts = beijing_now()
+-    try:
+-        _db_write(
+-            "UPDATE tasks SET status=?, error=?, finished_at=? WHERE id=?",
+-            (status, error, ts, task_id),
+-        )
+-        _insert_event(
+-            task_id,
+-            "success" if status == "done" else (
+-                "warning" if status == "stopped" else "error"),
+-            f"任务结束，状态 → {status}" + (f"：{error}" if error else ""),
+-            {"status": status, "error": error},
+-        )
+-    except Exception as e:
+-        print(f"[wa_tasks] task {task_id} 回写状态失败: {e}")
+-
+-
+-def _apply_results(results: list) -> tuple[int, int, int]:
+-    """把一批查号结果写回 contacts。
+-
+-    匹配策略：按号码后 11 位（num11）做 LIKE 候选过滤（mobile 或 phone
+-    去空格后以此结尾），再用 normalize_numbers 规范化候选行号码做严格
+-    相等校验；仅当存在严格匹配行、或候选行唯一时才 UPDATE，歧义跳过。
+-
+-    返回 (写回行数, 结果错误跳过数, 歧义跳过数)。
+-    """
+-    written = skipped_err = skipped_amb = 0
+-    ts = beijing_now()
+-    conn = sqlite3.connect(DB_PATH, timeout=30)
+-    try:
+-        conn.row_factory = sqlite3.Row
+-        conn.execute("PRAGMA busy_timeout = 30000")
+-        for r in results:
+-            num = str(r.get("number") or "")
+-            reg = r.get("registered")
+-            if not num or reg is None:
+-                skipped_err += 1
+-                continue
+-            pat = "%" + num[-11:]
+-            rows = conn.execute(
+-                "SELECT id, mobile, phone FROM contacts "
+-                "WHERE REPLACE(mobile, ' ', '') LIKE :p "
+-                "OR REPLACE(phone, ' ', '') LIKE :p",
+-                {"p": pat}).fetchall()
+-            exact = [row for row in rows
+-                     if num in normalize_numbers([row["mobile"]], DEFAULT_CC)
+-                     or num in normalize_numbers([row["phone"]], DEFAULT_CC)]
+-            if exact:
+-                targets = exact
+-            elif len(rows) == 1:
+-                targets = rows
+-            else:
+-                skipped_amb += 1
+-                continue
+-            marks = ",".join("?" * len(targets))
+-            conn.execute(
+-                f"UPDATE contacts SET wa_registered=?, wa_checked_at=? "
+-                f"WHERE id IN ({marks})",
+-                (1 if reg else 0, ts,
+-                 *[row["id"] for row in targets]))
+-            written += len(targets)
+-        conn.commit()
+-    finally:
+-        conn.close()
+-    return written, skipped_err, skipped_amb
+-
+-
+-def _rest_with_heartbeat(task_id: int, seconds: float, label: str,
+-                         stop_event: threading.Event) -> bool:
+-    """分段等待 + 心跳日志，可被 stop_event 中断；返回是否被中断。
+-
+-    每段最多 30s 刷一条「剩余约 N 分钟」心跳，避免休息期间日志静默
+-    被误判为卡死；每段都可被 stop_event 中断。
+-    """
+-    deadline = time.monotonic() + seconds
+-    while True:
+-        remaining = deadline - time.monotonic()
+-        if remaining <= 0:
+-            return False
+-        if stop_event.wait(min(30.0, remaining)):
+-            return True
+-        remaining = deadline - time.monotonic()
+-        if remaining > 1:
+-            _insert_event(
+-                task_id, "info",
+-                f"⏸ {label}，剩余约 {remaining / 60:.1f} 分钟...")
+-
+-
+-def _atom_account(name: str) -> str:
+-    """API 账号名 → 原子 account 参数："default" 用缺省 auth_info/。"""
+-    return "" if name == "default" else name
+-
+-
+-def run(task_id: int, params: dict, stop_event: threading.Event) -> None:
+-    """wa_check 任务主循环（在 API 进程内线程中执行）。"""
+-    atom = CheckWhatsApp()
+-    try:
+-        migrate()  # 防御：服务未跑迁移时也能工作
+-        params = params or {}
+-        limit = int(params.get("limit") or 0)
+-        sample_min, sample_max, batch_num, rest_min, rest_max = \
+-            _pacing_params(params)
+-        accounts = [str(a).strip()
+-                    for a in (params.get("accounts") or []) if str(a).strip()]
+-
+-        # 防主号误用（曾因此误封主号）：wa_check 不显式指定账号时，过去会
+-        # 静默落到 default（= auth_info 主号），大批量协议查询有封号风险。
+-        # 空账号一律拒绝启动；显式选 default 则警告（default 目录已删除时
+-        # 原子层会以「未登录」FATAL，此处仅作提示）。
+-        if not accounts:
+-            _insert_event(
+-                task_id, "error",
+-                "wa_check 拒绝启动：未指定查号账号（accounts 为空）。"
+-                "为避免静默使用 default（主号）导致封号，任务已中止，"
+-                "请显式选择小号账号（如 xiaohao-1）后重试。",
+-                {"accounts": [], "action": "refused"})
+-            _finalize(
+-                task_id, "failed",
+-                "wa_check 未指定账号，拒绝启动（防空跑主号 default）")
+-            return
+-        if "default" in accounts:
+-            _insert_event(
+-                task_id, "warning",
+-                "警告：账号池包含 default（对应 auth_info 主号），"
+-                "协议批量查询有封号风险，请确认这是有意选择。",
+-                {"accounts": accounts, "contains_default": True})
+-
+-        rows = _fetch_pending_rows(limit)
+-        # 规范化 + 去重（保持顺序），一个号码可能对应多行联系人
+-        numbers: list[str] = []
+-        seen: set[str] = set()
+-        for _id, mobile in rows:
+-            for n in normalize_numbers([mobile], DEFAULT_CC):
+-                if n not in seen:
+-                    seen.add(n)
+-                    numbers.append(n)
+-        total = len(numbers)
+-        account_label = "、".join(accounts) if accounts else "default"
+-        _insert_event(
+-            task_id, "info",
+-            f"wa_check 启动：待查 {total} 个号码（{len(rows)} 行联系人），"
+-            f"账号池：{account_label}，每次连接查 {BATCH_SIZE} 个，"
+-            f"逐号间隔 {sample_min:g}~{sample_max:g}s（随机），"
+-            f"每 {batch_num} 个号码一批，批间休息 "
+-            f"{rest_min:g}~{rest_max:g}s（随机）",
+-            {"total": total, "rows": len(rows), "accounts": accounts,
+-             "batch_size": BATCH_SIZE,
+-             "sample_min": sample_min, "sample_max": sample_max,
+-             "batch_num": batch_num,
+-             "batch_rest_min": rest_min, "batch_rest_max": rest_max})
+-        if total == 0:
+-            _write_progress(task_id, 0, 0, 0, account_label)
+-            _finalize(task_id, "done", None)
+-            return
+-
+-        batches = [numbers[i:i + BATCH_SIZE]
+-                   for i in range(0, total, BATCH_SIZE)]
+-        checked = 0
+-        registered = 0
+-        consec_fatal = 0
+-        stopped = False
+-        fail_detail = None
+-        last_progress = 0.0
+-        nums_since_rest = 0  # 距上次批间休息已成功查号的号码数
+-        throttle_rest = False  # 本批疑似风控 → 批后额外长冷却
+-
+-        for bi, batch in enumerate(batches, 1):
+-            if stop_event.is_set() or _db_stop_requested(task_id):
+-                stopped = True
+-                break
+-            account_name = (accounts[(bi - 1) % len(accounts)]
+-                            if accounts else "default")
+-            ctx = WorkerContext(
+-                stop=stop_event,
+-                log=lambda m: _insert_event(
+-                    task_id, "info", m.strip()[:500]))
+-            res = atom.run(ctx, {
+-                "numbers": batch,
+-                "default_cc": DEFAULT_CC,
+-                "account": _atom_account(account_name),
+-                "sample_min": sample_min,
+-                "sample_max": sample_max,
+-            })
+-
+-            if res.outcome is Outcome.OK:
+-                consec_fatal = 0
+-                results = res.data.get("results") or []
+-                written, skipped_err, skipped_amb = _apply_results(results)
+-                hits = sum(1 for r in results if r.get("registered"))
+-                done = sum(1 for r in results
+-                           if r.get("registered") is not None)
+-                err_cnt = len(results) - done
+-                checked += done  # 只计有结果的号码，出错号码保持 NULL 待查
+-                registered += hits
+-                msg = (f"批次 {bi}/{len(batches)}：查 {done}/{len(batch)} 个，"
+-                       f"累计已注册 {registered}")
+-                extra = []
+-                if err_cnt and len(results):
+-                    ratio = err_cnt / len(results)
+-                    extra.append(f"{err_cnt} 个查询出错未写回")
+-                    if ratio >= THROTTLE_RATIO:
+-                        throttle_rest = True
+-                        _insert_event(
+-                            task_id, "warning",
+-                            f"批次 {bi}/{len(batches)} 错误率 {ratio:.0%}"
+-                            f"（{err_cnt}/{len(results)}）"
+-                            f" ≥{THROTTLE_RATIO:.0%}，疑似风控，批后将额外冷却",
+-                            {"err_cnt": err_cnt, "ratio": round(ratio, 2),
+-                             "throttle_rest": True})
+-                if skipped_amb:
+-                    extra.append(f"{skipped_amb} 个号码匹配歧义跳过")
+-                if extra:
+-                    msg += "（" + "，".join(extra) + "）"
+-                _insert_event(task_id, "info", msg, {
+-                    "batch": bi, "batches": len(batches),
+-                    "worker": account_name,
+-                    "account": account_name, "checked": checked,
+-                    "registered": registered, "written": written,
+-                })
+-            elif res.outcome is Outcome.FATAL:
+-                consec_fatal += 1
+-                _insert_event(
+-                    task_id, "error",
+-                    f"批次 {bi}/{len(batches)} FATAL（账号 {account_name}）："
+-                    f"{res.detail}")
+-                if consec_fatal >= MAX_CONSECUTIVE_FATAL:
+-                    fail_detail = (f"原子连续 {consec_fatal} 次 FATAL："
+-                                   f"{res.detail}")
+-                    break
+-            elif res.outcome is Outcome.SKIPPED:
+-                stopped = True
+-                _insert_event(task_id, "warning",
+-                              f"批次 {bi}/{len(batches)} 被停止信号中断")
+-                break
+-            else:  # NET_ERROR / EMPTY / BLOCKED：记警告后继续下一批
+-                consec_fatal = 0
+-                _insert_event(
+-                    task_id, "warning",
+-                    f"批次 {bi}/{len(batches)} {res.outcome.value}"
+-                    f"（账号 {account_name}）：{res.detail}")
+-
+-            now = time.monotonic()
+-            if now - last_progress >= _PROGRESS_THROTTLE_SEC:
+-                last_progress = now
+-                _write_progress(task_id, total, checked,
+-                                registered, account_name)
+-
+-            # 批次配额（号码数计）：采满 batch_num 个号码后批间随机长休息
+-            # （防风控）；逐号码间隔已在 check.js 循环内生效，批与批之间
+-            # 的间隔即重连开销本身，不再额外 sleep。
+-            if res.outcome is Outcome.OK:
+-                nums_since_rest += len(batch)
+-            if (bi < len(batches) and batch_num > 0
+-                    and nums_since_rest >= batch_num):
+-                rest = random.uniform(rest_min, rest_max)
+-                _insert_event(
+-                    task_id, "info",
+-                    f"⏸ 本批已查满 {nums_since_rest} 个号码，"
+-                    f"批间休息 {rest / 60:.1f} 分钟（防风控）...",
+-                    {"checked": checked, "registered": registered,
+-                     "rest_seconds": round(rest, 1)})
+-                if _rest_with_heartbeat(task_id, rest, "批间休息",
+-                                        stop_event):
+-                    stopped = True
+-                    break
+-                nums_since_rest = 0
+-                _insert_event(task_id, "info", "▶ 批间休息结束，继续查号")
+-
+-            # 风控冷却：高错误率批次后额外长休息（不等 batch_num 边界）
+-            if throttle_rest and bi < len(batches):
+-                cooldown = random.uniform(THROTTLE_COOLDOWN_MIN,
+-                                          THROTTLE_COOLDOWN_MAX)
+-                _insert_event(
+-                    task_id, "warning",
+-                    f"⏸ 疑似风控，额外冷却 {cooldown / 60:.1f} 分钟...",
+-                    {"checked": checked, "registered": registered,
+-                     "cooldown_seconds": round(cooldown, 1)})
+-                if _rest_with_heartbeat(task_id, cooldown, "风控冷却",
+-                                        stop_event):
+-                    stopped = True
+-                    break
+-                throttle_rest = False
+-
+-        if fail_detail:
+-            _finalize(task_id, "failed", fail_detail[:500])
+-        elif stopped:
+-            _finalize(task_id, "stopped", None)
+-        else:
+-            _finalize(task_id, "done", None)
+-        _write_progress(task_id, total, checked, registered,
+-                        accounts[-1] if accounts else "default")
+-    except Exception as e:
+-        print(f"[wa_tasks] task {task_id} 执行器异常: {e}")
+-        try:
+-            _insert_event(task_id, "error", f"执行器异常：{e}")
+-        except Exception:
+-            pass
+-        _finalize(task_id, "failed", f"执行器异常：{e}"[:500])
+diff --git a/platform/server/tests/test_batch_tasks.py b/platform/server/tests/test_batch_tasks.py
+index 752dbf7..22df547 100644
+--- a/platform/server/tests/test_batch_tasks.py
++++ b/platform/server/tests/test_batch_tasks.py
+@@ -20,29 +20,27 @@ import app.db as app_db
+ import app.runner as app_runner
+ from app import db as db_module
+ 
+ 
+ def _schema(conn):
+     conn.executescript("""
+     CREATE TABLE IF NOT EXISTS tasks (
+         id INTEGER PRIMARY KEY AUTOINCREMENT,
+         type TEXT NOT NULL,
+         params_json TEXT NOT NULL,
+-        celery_id TEXT,
+         status TEXT NOT NULL DEFAULT 'pending',
+         progress_json TEXT,
+         stop_requested INTEGER NOT NULL DEFAULT 0,
+         error TEXT,
+         created_at TEXT NOT NULL,
+         started_at TEXT,
+-        finished_at TEXT,
+-        flow_id INTEGER
++        finished_at TEXT
+     );
+     CREATE TABLE IF NOT EXISTS task_events (
+         id INTEGER PRIMARY KEY AUTOINCREMENT,
+         task_id INTEGER NOT NULL,
+         ts TEXT NOT NULL,
+         level TEXT NOT NULL,
+         message TEXT,
+         data_json TEXT
+     );
+     CREATE TABLE IF NOT EXISTS shops (
+diff --git a/platform/server/tests/test_dispatcher_api.py b/platform/server/tests/test_dispatcher_api.py
+index c30b441..eb7c696 100644
+--- a/platform/server/tests/test_dispatcher_api.py
++++ b/platform/server/tests/test_dispatcher_api.py
+@@ -20,25 +20,24 @@ import app.api.dispatcher as dispatcher_module
+ BATCH_QUEUES = {
+     "crawl_1688_contact", "crawl_mic_contact", "crawl_1688_shop",
+     "crawl_1688_company", "crawl_mic_shop", "wa_check",
+ }
+ 
+ 
+ def _schema(conn):
+     conn.executescript("""
+     CREATE TABLE IF NOT EXISTS tasks (
+         id INTEGER PRIMARY KEY AUTOINCREMENT,
+-        type TEXT NOT NULL, params_json TEXT NOT NULL, celery_id TEXT,
++        type TEXT NOT NULL, params_json TEXT NOT NULL,
+         status TEXT NOT NULL DEFAULT 'pending', progress_json TEXT,
+         stop_requested INTEGER NOT NULL DEFAULT 0, error TEXT,
+-        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
+-        flow_id INTEGER
++        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
+     );
+     CREATE TABLE IF NOT EXISTS task_events (
+         id INTEGER PRIMARY KEY AUTOINCREMENT,
+         task_id INTEGER NOT NULL, ts TEXT NOT NULL, level TEXT NOT NULL,
+         message TEXT, data_json TEXT
+     );
+     CREATE TABLE IF NOT EXISTS work_items (
+         id INTEGER PRIMARY KEY AUTOINCREMENT,
+         queue TEXT NOT NULL, site TEXT, batch_id INTEGER,
+         payload_json TEXT NOT NULL,
+diff --git a/platform/server/tests/test_loop_restart.py b/platform/server/tests/test_loop_restart.py
+index a2de2e2..29bee03 100644
+--- a/platform/server/tests/test_loop_restart.py
++++ b/platform/server/tests/test_loop_restart.py
+@@ -20,29 +20,27 @@ BJ_TZ = timezone(timedelta(hours=8))
+ 
+ 
+ def _make_db(path: str) -> None:
+     conn = sqlite3.connect(path)
+     conn.executescript(
+         """
+         CREATE TABLE tasks (
+             id INTEGER PRIMARY KEY,
+             type TEXT NOT NULL,
+             params_json TEXT NOT NULL,
+-            celery_id TEXT,
+             status TEXT NOT NULL DEFAULT 'pending',
+             progress_json TEXT,
+             stop_requested INTEGER NOT NULL DEFAULT 0,
+             error TEXT,
+             created_at TEXT NOT NULL,
+             started_at TEXT,
+-            finished_at TEXT,
+-            flow_id INTEGER
++            finished_at TEXT
+         );
+         CREATE TABLE task_events (
+             id INTEGER PRIMARY KEY AUTOINCREMENT,
+             task_id INTEGER NOT NULL,
+             ts TEXT NOT NULL,
+             level TEXT NOT NULL,
+             message TEXT NOT NULL,
+             data_json TEXT
+         );
+         """
+diff --git a/platform/server/tests/test_task_waiting_status.py b/platform/server/tests/test_task_waiting_status.py
+index 0fb3cdf..93ef0c5 100644
+--- a/platform/server/tests/test_task_waiting_status.py
++++ b/platform/server/tests/test_task_waiting_status.py
+@@ -18,22 +18,20 @@ def _row(status, params=None, stop_requested=0,
+         "id": 72,
+         "type": "1688_contact",
+         "params_json": json.dumps(params or {}),
+         "progress_json": None,
+         "status": status,
+         "stop_requested": stop_requested,
+         "finished_at": finished_at,
+         "started_at": "2026-08-05 10:19:43",
+         "created_at": "2026-08-05 02:18:05",
+         "error": None,
+-        "celery_id": None,
+-        "flow_id": None,
+     }
+ 
+ 
+ class LoopWaitStatusTest(unittest.TestCase):
+     def test_done_with_repeat_interval_is_waiting(self):
+         """done + repeat_interval → waiting，next_restart_at = finished + interval。"""
+         eff, next_at = _loop_wait(_row("done", {"repeat_interval": 1800}))
+         self.assertEqual(eff, "waiting")
+         self.assertEqual(next_at, "2026-08-05 10:51:47")
+ 
+diff --git a/platform/server/tests/test_tasks_table_rebuild.py b/platform/server/tests/test_tasks_table_rebuild.py
+new file mode 100644
+index 0000000..f36cc72
+--- /dev/null
++++ b/platform/server/tests/test_tasks_table_rebuild.py
+@@ -0,0 +1,345 @@
++# -*- coding: utf-8 -*-
++"""P5 Step 3.1: tasks 表重建迁移测试（方案 B 交换式）。
++
++覆盖：旧 schema（tasks 带 celery_id/flow_id + flows 表 + task_events/
++proxy_channels 子表）跑 migrate() 后——死列删除、flows 表删除、数据无损、
++idx_tasks_status 重建、子表外键路径保活；重跑幂等零变化；已迁移库 no-op。
++全部用临时 sqlite（patch DB_PATH），绝不碰生产库。
++"""
++
++import sqlite3
++import tempfile
++import unittest
++from pathlib import Path
++from unittest.mock import patch
++
++from app import db as db_module
++
++# 旧 schema（tasks 带 celery_id/flow_id，flows 表，子表外键指向 tasks）
++_OLD_SCHEMA = """
++CREATE TABLE tasks (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    type TEXT NOT NULL,
++    params_json TEXT NOT NULL,
++    celery_id TEXT,
++    status TEXT NOT NULL DEFAULT 'pending',
++    progress_json TEXT,
++    stop_requested INTEGER NOT NULL DEFAULT 0,
++    error TEXT,
++    created_at TEXT NOT NULL,
++    started_at TEXT,
++    finished_at TEXT,
++    flow_id INTEGER REFERENCES flows(id)
++);
++CREATE TABLE task_events (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    task_id INTEGER NOT NULL REFERENCES tasks(id),
++    ts TEXT NOT NULL,
++    level TEXT NOT NULL,
++    message TEXT NOT NULL,
++    data_json TEXT
++);
++CREATE TABLE proxy_channels (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    provider_id INTEGER REFERENCES providers(id),
++    tunnel TEXT,
++    exit_ip TEXT,
++    status TEXT NOT NULL DEFAULT 'idle',
++    used_by_task INTEGER REFERENCES tasks(id),
++    ip_expires_at TEXT,
++    last_probe_at TEXT,
++    UNIQUE(provider_id, tunnel)
++);
++CREATE TABLE flows (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    name TEXT NOT NULL,
++    description TEXT,
++    dag_json TEXT NOT NULL,
++    builtin INTEGER NOT NULL DEFAULT 0,
++    created_at TEXT NOT NULL,
++    updated_at TEXT NOT NULL
++);
++CREATE TABLE providers (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    kind TEXT NOT NULL,
++    name TEXT NOT NULL,
++    config_json TEXT NOT NULL,
++    enabled INTEGER NOT NULL DEFAULT 1,
++    created_at TEXT NOT NULL,
++    updated_at TEXT NOT NULL
++);
++CREATE TABLE contacts (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    mobile TEXT,
++    wa_registered INTEGER,
++    wa_checked_at TEXT
++);
++"""
++
++_NEW_SCHEMA = """
++CREATE TABLE contacts (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    mobile TEXT,
++    wa_registered INTEGER,
++    wa_checked_at TEXT
++);
++CREATE TABLE tasks (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    type TEXT NOT NULL,
++    params_json TEXT NOT NULL,
++    status TEXT NOT NULL DEFAULT 'pending',
++    progress_json TEXT,
++    stop_requested INTEGER NOT NULL DEFAULT 0,
++    error TEXT,
++    created_at TEXT NOT NULL,
++    started_at TEXT,
++    finished_at TEXT
++);
++CREATE INDEX idx_tasks_status ON tasks(status);
++CREATE TABLE task_events (
++    id INTEGER PRIMARY KEY AUTOINCREMENT,
++    task_id INTEGER NOT NULL REFERENCES tasks(id),
++    ts TEXT NOT NULL,
++    level TEXT NOT NULL,
++    message TEXT NOT NULL,
++    data_json TEXT
++);
++"""
++
++
++class TasksTableRebuildTest(unittest.TestCase):
++    """临时库基座：patch app.db.DB_PATH 指向临时库。"""
++
++    def setUp(self):
++        self._tmp = tempfile.TemporaryDirectory()
++        self.db_path = str(Path(self._tmp.name) / "t.db")
++        patcher = patch.object(db_module, "DB_PATH", self.db_path)
++        patcher.start()
++        self.addCleanup(patcher.stop)
++
++    def tearDown(self):
++        self._tmp.cleanup()
++
++    def _conn(self):
++        conn = sqlite3.connect(self.db_path)
++        conn.row_factory = sqlite3.Row
++        conn.execute("PRAGMA busy_timeout = 30000")
++        return conn
++
++    def _cols(self, conn, table):
++        return {r[1] for r in conn.execute(
++            f"PRAGMA table_info({table})")}
++
++    def _tables(self, conn):
++        return {r[0] for r in conn.execute(
++            "SELECT name FROM sqlite_master WHERE type='table'")}
++
++    def _seed_old(self, conn):
++        """建旧 schema + 造数：3 任务（含死列值）、2 事件、1 通道、2 flows。"""
++        conn.executescript(_OLD_SCHEMA)
++        rows = [
++            ("wa_check", '{"numbers":["8613800138000"]}', "done",
++             "2026-08-05 02:18:05", "2026-08-05 02:19:00",
++             "2026-08-05 02:20:00", "celery-1", 1),
++            ("crawl_1688_contact", '{"batch_id":7}', "running",
++             "2026-08-05 02:30:00", "2026-08-05 02:31:00", None,
++             "celery-2", 2),
++            ("crawl_mic_shop", "{}", "failed", "2026-08-05 03:00:00",
++             "2026-08-05 03:01:00", "2026-08-05 03:02:00", None, 3),
++        ]
++        for i, (typ, params, status, created, started, finished,
++                celery, flow) in enumerate(rows, start=1):
++            conn.execute(
++                "INSERT INTO tasks (id, type, params_json, status,"
++                " created_at, started_at, finished_at, celery_id, flow_id)"
++                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
++                (i, typ, params, status, created, started, finished,
++                 celery, flow))
++        conn.executescript("""
++        INSERT INTO task_events (task_id, ts, level, message)
++            VALUES (1, '2026-08-05 02:19:00', 'info', 'e1'),
++                   (1, '2026-08-05 02:19:30', 'success', 'e2');
++        INSERT INTO proxy_channels (provider_id, tunnel, status, used_by_task)
++            VALUES (1, 't1', 'in_use', 1);
++        INSERT INTO flows (name, dag_json, created_at, updated_at)
++            VALUES ('f1', '{}', '2026-08-01 00:00:00', '2026-08-01 00:00:00'),
++                   ('f2', '{}', '2026-08-02 00:00:00', '2026-08-02 00:00:00');
++        """)
++        conn.commit()
++
++
++class MigrateOldSchemaTest(TasksTableRebuildTest):
++    """RED→GREEN 主线：旧 schema 迁移后死列删除、数据无损、外键保活。"""
++
++    def test_migrate_drops_dead_columns_and_flows(self):
++        conn = self._conn()
++        self._seed_old(conn)
++        conn.close()
++
++        db_module.migrate()
++
++        conn = self._conn()
++        try:
++            cols = self._cols(conn, "tasks")
++            self.assertNotIn("celery_id", cols)
++            self.assertNotIn("flow_id", cols)
++            self.assertNotIn("flows", self._tables(conn))
++        finally:
++            conn.close()
++
++    def test_migrate_preserves_data_and_index(self):
++        conn = self._conn()
++        self._seed_old(conn)
++        before = conn.execute(
++            "SELECT id, type, params_json, status, progress_json,"
++            " stop_requested, error, created_at, started_at, finished_at"
++            " FROM tasks ORDER BY id").fetchall()
++        conn.close()
++
++        db_module.migrate()
++
++        conn = self._conn()
++        try:
++            after = conn.execute(
++                "SELECT id, type, params_json, status, progress_json,"
++                " stop_requested, error, created_at, started_at, finished_at"
++                " FROM tasks ORDER BY id").fetchall()
++            self.assertEqual([tuple(r) for r in before],
++                             [tuple(r) for r in after])
++            idx = {r[0] for r in conn.execute(
++                "SELECT name FROM sqlite_master WHERE type='index'"
++                " AND tbl_name='tasks'")}
++            self.assertIn("idx_tasks_status", idx)
++        finally:
++            conn.close()
++
++    def test_migrate_keeps_child_fk_paths_alive(self):
++        conn = self._conn()
++        self._seed_old(conn)
++        conn.close()
++
++        db_module.migrate()
++
++        conn = self._conn()
++        try:
++            # 子表 DDL 仍指向表名 tasks（方案 B 不重写子表定义）
++            master = " ".join(
++                r[0] for r in conn.execute(
++                    "SELECT sql FROM sqlite_master WHERE type='table'"
++                    " AND name IN ('task_events','proxy_channels')"))
++            self.assertIn("REFERENCES tasks", master)
++            # 外键路径实际可用：向子表插入新行成功
++            conn.execute("INSERT INTO task_events (task_id, ts, level,"
++                         " message) VALUES (1, '2026-08-06 00:00:00',"
++                         " 'info', 'after-migrate')")
++            conn.execute("INSERT INTO proxy_channels (provider_id, tunnel,"
++                         " status, used_by_task) VALUES (1, 't2', 'idle', 2)")
++            conn.commit()
++            self.assertEqual(conn.execute(
++                "SELECT COUNT(*) FROM task_events").fetchone()[0], 3)
++            self.assertEqual(conn.execute(
++                "SELECT COUNT(*) FROM proxy_channels").fetchone()[0], 2)
++        finally:
++            conn.close()
++
++
++class IdempotentTest(TasksTableRebuildTest):
++    """对已迁移库重跑 migrate() 零变化。"""
++
++    def test_rerun_migrate_is_noop(self):
++        conn = self._conn()
++        self._seed_old(conn)
++        conn.close()
++
++        db_module.migrate()
++        conn = self._conn()
++        snapshot = conn.execute(
++            "SELECT id, type, params_json, status, progress_json,"
++            " stop_requested, error, created_at, started_at, finished_at"
++            " FROM tasks ORDER BY id").fetchall()
++        conn.close()
++
++        db_module.migrate()  # 重跑
++
++        conn = self._conn()
++        try:
++            self.assertNotIn("celery_id", self._cols(conn, "tasks"))
++            self.assertNotIn("flow_id", self._cols(conn, "tasks"))
++            self.assertNotIn("flows", self._tables(conn))
++            after = conn.execute(
++                "SELECT id, type, params_json, status, progress_json,"
++                " stop_requested, error, created_at, started_at, finished_at"
++                " FROM tasks ORDER BY id").fetchall()
++            self.assertEqual([tuple(r) for r in snapshot],
++                             [tuple(r) for r in after])
++        finally:
++            conn.close()
++
++
++class NewSchemaNoopTest(TasksTableRebuildTest):
++    """已迁移库（新 schema 无死列）跑 migrate() 零变化。"""
++
++    def test_migrate_on_new_schema_is_noop(self):
++        conn = self._conn()
++        conn.executescript(_NEW_SCHEMA)
++        conn.execute(
++            "INSERT INTO tasks (type, params_json, status, created_at)"
++            " VALUES ('wa_check', '{}', 'pending', '2026-08-05 02:00:00')")
++        conn.commit()
++        before_cols = self._cols(conn, "tasks")
++        before_rows = conn.execute("SELECT * FROM tasks").fetchall()
++        conn.close()
++
++        db_module.migrate()
++
++        conn = self._conn()
++        try:
++            self.assertEqual(self._cols(conn, "tasks"), before_cols)
++            self.assertEqual(conn.execute("SELECT * FROM tasks").fetchall(),
++                             before_rows)
++        finally:
++            conn.close()
++
++
++class RollbackTest(TasksTableRebuildTest):
++    """失败回滚：DROP 处抛异常 → ROLLBACK 后原表（含死列与数据）保留。"""
++
++    def test_migrate_rollback_keeps_original_tasks(self):
++        conn = self._conn()
++        self._seed_old(conn)
++        conn.close()
++
++        class FlakyConn(sqlite3.Connection):
++            """在 DROP TABLE tasks 处抛异常的连接（模拟中途失败）。"""
++            def execute(self, sql, parameters=()):
++                if isinstance(sql, str) and sql.strip().upper().startswith(
++                        "DROP TABLE TASKS"):
++                    raise RuntimeError("simulated drop failure")
++                return super().execute(sql, parameters)
++
++        real_connect = sqlite3.connect
++
++        def flaky_connect(path, timeout=30, **kw):
++            return real_connect(path, timeout=timeout, factory=FlakyConn)
++
++        with patch("sqlite3.connect", side_effect=flaky_connect):
++            with self.assertRaises(RuntimeError):
++                db_module.migrate()
++
++        conn = self._conn()
++        try:
++            # 原表保留：死列仍在、数据未丢、flows 未删
++            cols = self._cols(conn, "tasks")
++            self.assertIn("celery_id", cols)
++            self.assertIn("flow_id", cols)
++            self.assertIn("flows", self._tables(conn))
++            self.assertEqual(conn.execute(
++                "SELECT COUNT(*) FROM tasks").fetchone()[0], 3)
++            self.assertEqual(conn.execute(
++                "SELECT COUNT(*) FROM task_events").fetchone()[0], 2)
++        finally:
++            conn.close()
++
++
++if __name__ == "__main__":
++    unittest.main()
+diff --git a/platform/server/tests/test_wa_tasks_cooldown.py b/platform/server/tests/test_wa_tasks_cooldown.py
+deleted file mode 100644
+index 17032d3..0000000
+--- a/platform/server/tests/test_wa_tasks_cooldown.py
++++ /dev/null
+@@ -1,168 +0,0 @@
+-# -*- coding: utf-8 -*-
+-"""wa_tasks 分段等待助手与风控冷却测试。"""
+-
+-import json
+-import os
+-import sqlite3
+-import tempfile
+-import threading
+-import unittest
+-from unittest.mock import patch
+-
+-from fetcher.core.types import ActionResult
+-from app import db, runner, wa_tasks
+-
+-
+-def _make_db(path: str) -> None:
+-    conn = sqlite3.connect(path)
+-    conn.executescript(
+-        """
+-        CREATE TABLE tasks (
+-            id INTEGER PRIMARY KEY,
+-            type TEXT NOT NULL,
+-            params_json TEXT NOT NULL,
+-            celery_id TEXT,
+-            status TEXT NOT NULL DEFAULT 'pending',
+-            progress_json TEXT,
+-            stop_requested INTEGER NOT NULL DEFAULT 0,
+-            error TEXT,
+-            created_at TEXT NOT NULL,
+-            started_at TEXT,
+-            finished_at TEXT,
+-            flow_id INTEGER
+-        );
+-        CREATE TABLE task_events (
+-            id INTEGER PRIMARY KEY AUTOINCREMENT,
+-            task_id INTEGER NOT NULL,
+-            ts TEXT NOT NULL,
+-            level TEXT NOT NULL,
+-            message TEXT NOT NULL,
+-            data_json TEXT
+-        );
+-        CREATE TABLE contacts (
+-            id INTEGER PRIMARY KEY,
+-            mobile TEXT,
+-            phone TEXT,
+-            wa_registered INTEGER,
+-            wa_checked_at TEXT
+-        );
+-        INSERT INTO tasks (id, type, params_json, status, created_at)
+-        VALUES (1, 'wa_check', '{"accounts": ["xiaohao-1"]}',
+-                'pending', '2026-08-05 12:00:00');
+-        """
+-    )
+-    conn.commit()
+-    conn.close()
+-
+-
+-class _Base(unittest.TestCase):
+-    def setUp(self):
+-        fd, self.db = tempfile.mkstemp(suffix=".db")
+-        os.close(fd)
+-        _make_db(self.db)
+-        self.old_db = db.DB_PATH
+-        self.old_runner_db = runner.DB_PATH
+-        self.old_wa_db = wa_tasks.DB_PATH
+-        db.DB_PATH = self.db
+-        runner.DB_PATH = self.db
+-        wa_tasks.DB_PATH = self.db
+-
+-    def tearDown(self):
+-        db.DB_PATH = self.old_db
+-        runner.DB_PATH = self.old_runner_db
+-        wa_tasks.DB_PATH = self.old_wa_db
+-        try:
+-            os.unlink(self.db)
+-        except OSError:
+-            pass
+-
+-
+-class RestHeartbeatTest(_Base):
+-    def test_short_rest_completes_not_interrupted(self):
+-        stop = threading.Event()
+-        result = wa_tasks._rest_with_heartbeat(1, 1, "测试", stop)
+-        self.assertFalse(result)
+-
+-    def test_interrupted_returns_true(self):
+-        stop = threading.Event()
+-        stop.set()
+-        result = wa_tasks._rest_with_heartbeat(1, 60, "测试", stop)
+-        self.assertTrue(result)
+-
+-
+-class ThrottleCooldownTest(_Base):
+-    def _ok(self, results):
+-        done = sum(1 for r in results if r.get("registered") is not None)
+-        hits = sum(1 for r in results if r.get("registered"))
+-        return ActionResult.success("ok", results=results,
+-                                    checked=done, registered=hits)
+-
+-    def _rows(self, n=50):
+-        return [(i, f"86130000000{i:02d}") for i in range(1, n + 1)]
+-
+-    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
+-    @patch("app.wa_tasks._fetch_pending_rows")
+-    @patch("app.wa_tasks.CheckWhatsApp")
+-    def test_high_error_ratio_triggers_cooldown(self, mock_cls, mock_rows, mock_apply):
+-        # 100 个号码 = 2 批，冷却在批 1 之后触发（需 bi < len(batches)）
+-        mock_rows.return_value = self._rows(100)
+-        # 40 个出错 + 60 个正常 → 错误率 40% ≥ 30%
+-        results = [{"number": f"8613{i:07d}", "registered": None, "error": "x"}
+-                   for i in range(40)]
+-        results += [{"number": f"8614{i:07d}", "registered": False}
+-                    for i in range(60)]
+-        mock_cls.return_value.run.return_value = self._ok(results)
+-
+-        with patch("app.wa_tasks.THROTTLE_COOLDOWN_MIN", 0.01), \
+-             patch("app.wa_tasks.THROTTLE_COOLDOWN_MAX", 0.02):
+-            wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())
+-
+-        conn = sqlite3.connect(self.db)
+-        warnings = conn.execute(
+-            "SELECT message FROM task_events WHERE task_id=1 "
+-            "AND level='warning' AND message LIKE '%风控%'").fetchall()
+-        conn.close()
+-        self.assertTrue(any("疑似风控" in w[0] for w in warnings))
+-        self.assertTrue(any("额外冷却" in w[0] for w in warnings))
+-
+-    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
+-    @patch("app.wa_tasks._fetch_pending_rows")
+-    @patch("app.wa_tasks.CheckWhatsApp")
+-    def test_low_error_ratio_no_cooldown(self, mock_cls, mock_rows, mock_apply):
+-        mock_rows.return_value = self._rows()
+-        results = [{"number": f"8613{i:07d}", "registered": False}
+-                   for i in range(50)]  # 0 出错
+-        mock_cls.return_value.run.return_value = self._ok(results)
+-
+-        wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())
+-
+-        conn = sqlite3.connect(self.db)
+-        cools = conn.execute(
+-            "SELECT COUNT(*) FROM task_events WHERE task_id=1 "
+-            "AND message LIKE '%额外冷却%'").fetchone()
+-        conn.close()
+-        self.assertEqual(cools[0], 0)
+-
+-    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
+-    @patch("app.wa_tasks._fetch_pending_rows")
+-    @patch("app.wa_tasks.CheckWhatsApp")
+-    def test_checked_counts_done_not_batch(self, mock_cls, mock_rows, mock_apply):
+-        # 2 个号码，1 个出错（registered:null）→ checked 应计 1 而非 2
+-        mock_rows.return_value = self._rows(2)
+-        results = [
+-            {"number": "8613000000001", "registered": False},
+-            {"number": "8613000000002", "registered": None, "error": "x"},
+-        ]
+-        mock_cls.return_value.run.return_value = self._ok(results)
+-
+-        wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())
+-
+-        conn = sqlite3.connect(self.db)
+-        prog = conn.execute(
+-            "SELECT progress_json FROM tasks WHERE id=1").fetchone()
+-        conn.close()
+-        self.assertEqual(json.loads(prog[0])["checked"], 1)
+-
+-
+-if __name__ == "__main__":
+-    unittest.main()
+diff --git a/platform/server/tests/test_wa_tasks_guard.py b/platform/server/tests/test_wa_tasks_guard.py
+deleted file mode 100644
+index 95a5d1d..0000000
+--- a/platform/server/tests/test_wa_tasks_guard.py
++++ /dev/null
+@@ -1,104 +0,0 @@
+-# -*- coding: utf-8 -*-
+-"""wa_check 空账号拦截测试。
+-
+-覆盖：wa_check 任务 accounts 为空时必须拒绝启动（防止静默落到
+-default 主号导致封号），而不是继续取数运行。
+-"""
+-
+-import os
+-import sqlite3
+-import tempfile
+-import threading
+-import unittest
+-
+-from app import db, runner, wa_tasks
+-
+-
+-def _make_db(path: str) -> None:
+-    conn = sqlite3.connect(path)
+-    conn.executescript(
+-        """
+-        CREATE TABLE tasks (
+-            id INTEGER PRIMARY KEY,
+-            type TEXT NOT NULL,
+-            params_json TEXT NOT NULL,
+-            celery_id TEXT,
+-            status TEXT NOT NULL DEFAULT 'pending',
+-            progress_json TEXT,
+-            stop_requested INTEGER NOT NULL DEFAULT 0,
+-            error TEXT,
+-            created_at TEXT NOT NULL,
+-            started_at TEXT,
+-            finished_at TEXT,
+-            flow_id INTEGER
+-        );
+-        CREATE TABLE task_events (
+-            id INTEGER PRIMARY KEY AUTOINCREMENT,
+-            task_id INTEGER NOT NULL,
+-            ts TEXT NOT NULL,
+-            level TEXT NOT NULL,
+-            message TEXT NOT NULL,
+-            data_json TEXT
+-        );
+-        CREATE TABLE contacts (
+-            id INTEGER PRIMARY KEY,
+-            mobile TEXT,
+-            phone TEXT,
+-            wa_registered INTEGER,
+-            wa_checked_at TEXT
+-        );
+-        INSERT INTO tasks (id, type, params_json, status, created_at)
+-        VALUES (1, 'wa_check', '{"accounts": []}',
+-                'pending', '2026-08-05 12:00:00');
+-        """
+-    )
+-    conn.commit()
+-    conn.close()
+-
+-
+-class WaaCheckEmptyAccountsGuardTest(unittest.TestCase):
+-    def setUp(self):
+-        fd, self.db = tempfile.mkstemp(suffix=".db")
+-        os.close(fd)
+-        _make_db(self.db)
+-        self.old_db = db.DB_PATH
+-        self.old_runner_db = runner.DB_PATH
+-        self.old_wa_db = wa_tasks.DB_PATH
+-        db.DB_PATH = self.db
+-        runner.DB_PATH = self.db
+-        wa_tasks.DB_PATH = self.db
+-
+-    def tearDown(self):
+-        db.DB_PATH = self.old_db
+-        runner.DB_PATH = self.old_runner_db
+-        wa_tasks.DB_PATH = self.old_wa_db
+-        try:
+-            os.unlink(self.db)
+-        except OSError:
+-            pass
+-
+-    def test_empty_accounts_refuses_to_run(self):
+-        # 若守卫失效，会走到 _fetch_pending_rows → 抛异常使测试失败
+-        def _boom():
+-            raise AssertionError("守卫失效：空账号仍然尝试取数运行")
+-        wa_tasks._fetch_pending_rows = _boom
+-
+-        stop = threading.Event()
+-        wa_tasks.run(1, {"accounts": []}, stop)
+-
+-        conn = sqlite3.connect(self.db)
+-        row = conn.execute(
+-            "SELECT status, error FROM tasks WHERE id=1").fetchone()
+-        ev = conn.execute(
+-            "SELECT level, message FROM task_events "
+-            "WHERE task_id=1 ORDER BY id LIMIT 1").fetchone()
+-        conn.close()
+-
+-        self.assertEqual(row[0], "failed")
+-        self.assertIn("拒绝启动", row[1])
+-        self.assertEqual(ev[0], "error")
+-        self.assertIn("拒绝启动", ev[1])
+-
+-
+-if __name__ == "__main__":
+-    unittest.main()
+diff --git a/platform/web/src/lib/api.ts b/platform/web/src/lib/api.ts
+index b952d12..d6c434d 100644
+--- a/platform/web/src/lib/api.ts
++++ b/platform/web/src/lib/api.ts
+@@ -81,69 +81,58 @@ export type TaskType =
+   | '1688_contact'
+   | 'madeinchina_contact'
+   | 'madeinchina_shop'
+   | 'yiwugo_search'
+   | 'wa_check'
+ 
+ // 采集类参数全量可选键：留空即不传，由 CLI 默认值生效。
+ // 批次类型（1688/madeinchina 采集 + wa_check）只读 limit / repeat_interval /
+ // accounts，其余 daemon 级参数（workers/proxy/节奏等）已收敛到 daemon 启动，
+ // 逐任务覆盖取消（SPEC §3.2 用户可见变化）；旧模板多余字段后端忽略。
+-// wa_check 使用 limit / accounts / sample_min / sample_max / batch_num /
+-// batch_rest_min / batch_rest_max（interval 为旧参数，向后兼容）。
++// wa_check 只使用 limit / accounts；旧模板多余字段后端忽略（加载时忽略未知键）。
+ export interface TaskParams {
+   batch_num?: number
+   limit?: number
+   max_batches?: number
+   workers?: number
+-  channels?: string
++  channels?: number
+   batch_rest?: number
+   sample_min?: number
+   sample_max?: number
+   rest_every?: number
+   rest_min?: number
+   rest_max?: number
+   stagger_min?: number
+   stagger_max?: number
+   ip_retry?: number
+   net_retry?: number
+   max_consecutive_fail?: number
+   block_rest_min?: number
+   block_rest_max?: number
+   use_proxy?: boolean
+   headless?: boolean
+   auto_solve?: boolean
+-  retry_failed?: boolean // 仅 1688_contact
++  retry_failed?: boolean // 仅 1688_contact；已不映射 CLI（build_command 分支已删），表单开关遗留
+   // 任务结束后自动重启的间隔（秒）；0 或不传 = 不循环
+   repeat_interval?: number
+   // wa_check 专用
+-  interval?: number // 旧参数：固定调用间隔（等价 sample_min == sample_max）
+   accounts?: string[]
+-  batch_rest_min?: number // wa_check 批间休息下限（秒）
+-  batch_rest_max?: number // wa_check 批间休息上限（秒）
+ }
+ 
+ export interface CreateTaskRequest {
+   type: TaskType
+   params: TaskParams
+ }
+ 
+ export interface TaskPreview {
+-  cmd: string[] | null // wa_check 为进程内任务，返回 null
+-  cmdline: string // cmd 拼接的命令行，或 wa_check 的说明文案
+-}
+-
+-// 命令解析结果：422 时 request() 抛出带后端 detail 的 ApiError
+-export interface TaskParseResult {
+-  type: TaskType
+-  params: TaskParams
+-  warnings: string[]
++  cmd: string[] | null // 批次类型（含 wa_check）返回 null
++  cmdline: string // cmd 拼接的命令行，或批次类型的说明文案
+ }
+ 
+ export interface TaskTemplate {
+   id: number
+   name: string
+   type: TaskType
+   params: TaskParams
+   created_at: string
+ }
+ 
+@@ -318,25 +307,20 @@ export const api = {
+     if (period === '12h') qs = 'hours=12'
+     else if (period === 'custom') qs = `period=custom&start=${encodeURIComponent(start ?? '')}&end=${encodeURIComponent(end ?? '')}`
+     else qs = `period=${period}`
+     return request<Pipeline>(`/dashboard/pipeline?${qs}`)
+   },
+   tasks: async () => (await request<unknown[]>('/tasks')).map(normalizeTask),
+   createTask: async (body: CreateTaskRequest) =>
+     normalizeTask(await request<unknown>('/tasks', { method: 'POST', body: JSON.stringify(body) })),
+   previewTask: (body: CreateTaskRequest) =>
+     request<TaskPreview>('/tasks/preview', { method: 'POST', body: JSON.stringify(body) }),
+-  parseCommand: (command: string) =>
+-    request<TaskParseResult>('/tasks/parse', {
+-      method: 'POST',
+-      body: JSON.stringify({ command }),
+-    }),
+   putTask: async (id: number, params: TaskParams) =>
+     normalizeTask(
+       await request<unknown>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify({ params }) })),
+   getTask: async (id: number) => normalizeTask(await request<unknown>(`/tasks/${id}`)),
+   startTask: (id: number) => request<StartTaskResult>(`/tasks/${id}/start`, { method: 'POST' }),
+   stopTask: (id: number) => request<{ ok: boolean }>(`/tasks/${id}/stop`, { method: 'POST' }),
+   deleteTask: (id: number) => request<{ ok: boolean }>(`/tasks/${id}`, { method: 'DELETE' }),
+   batchTasks: (action: 'start' | 'stop' | 'delete', ids: number[]) =>
+     request<TaskBatchResult>('/tasks/batch', {
+       method: 'POST',
+diff --git a/platform/web/src/pages/tasks/TaskFormDialog.tsx b/platform/web/src/pages/tasks/TaskFormDialog.tsx
+index f21175b..4413d01 100644
+--- a/platform/web/src/pages/tasks/TaskFormDialog.tsx
++++ b/platform/web/src/pages/tasks/TaskFormDialog.tsx
+@@ -17,22 +17,21 @@ import {
+ } from '@/components/ui/collapsible'
+ import {
+   Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
+ } from '@/components/ui/dialog'
+ import { Input } from '@/components/ui/input'
+ import { Label } from '@/components/ui/label'
+ import {
+   Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
+ } from '@/components/ui/select'
+ import { Switch } from '@/components/ui/switch'
+-import { Textarea } from '@/components/ui/textarea'
+-import { ChevronDown, Save, Terminal, Trash2, Wand2 } from 'lucide-react'
++import { ChevronDown, Save, Terminal, Trash2 } from 'lucide-react'
+ import { TASK_TYPE_OPTIONS, taskTypeLabel } from './task-ui'
+ 
+ interface NumField {
+   key: string
+   label: string
+   placeholder: string
+   hint?: string
+ }
+ 
+ // 基础区常用数字参数
+@@ -66,21 +65,21 @@ const RETRY_FIELDS: NumField[] = [
+ 
+ // 高级参数：其他（数字类）
+ const MISC_NUM_FIELDS: NumField[] = [
+   { key: 'repeat_interval', label: '循环间隔（秒）', placeholder: '0 = 不循环，如 1800' },
+ ]
+ 
+ const ALL_NUM_KEYS = [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map(
+   (f) => f.key,
+ )
+ 
+-// 高级区包含的数字键（命令导入 / 模板加载命中时自动展开高级区）
++// 高级区包含的数字键（模板加载命中时自动展开高级区）
+ const ADVANCED_NUM_KEYS = [...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map((f) => f.key)
+ 
+ interface TaskFormDialogProps {
+   open: boolean
+   onOpenChange: (open: boolean) => void
+   onSaved: () => void
+   task?: Task | null // 传入 = 编辑模式（type 只读，回填 params）
+ }
+ 
+ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDialogProps) {
+@@ -91,112 +90,90 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
+   const [channels, setChannels] = useState('')
+   const [useProxy, setUseProxy] = useState(true)
+   const [headless, setHeadless] = useState(true)
+   const [autoSolve, setAutoSolve] = useState(true)
+   const [retryFailed, setRetryFailed] = useState(false)
+   const [advancedOpen, setAdvancedOpen] = useState(false)
+   const [submitting, setSubmitting] = useState(false)
+ 
+   // wa_check 专用表单状态
+   const [waLimit, setWaLimit] = useState('')
+-  const [waSampleMin, setWaSampleMin] = useState('')
+-  const [waSampleMax, setWaSampleMax] = useState('')
+-  const [waBatchNum, setWaBatchNum] = useState('')
+-  const [waRestMin, setWaRestMin] = useState('')
+-  const [waRestMax, setWaRestMax] = useState('')
+   const [waAccounts, setWaAccounts] = useState<WaAccount[]>([])
+   const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])
+ 
+   // P4 批次采集专用：limit（contact=条数、shop/company=页数）
+   const [batchLimit, setBatchLimit] = useState('')
+ 
+   // 命令预览
+   const [preview, setPreview] = useState<TaskPreview | null>(null)
+ 
+-  // 从命令导入
+-  const [importOpen, setImportOpen] = useState(false)
+-  const [importText, setImportText] = useState('')
+-  const [parsing, setParsing] = useState(false)
+-
+   // 任务模板
+   const [templates, setTemplates] = useState<TaskTemplate[]>([])
+   const [templateSel, setTemplateSel] = useState('')
+   const [saveTplOpen, setSaveTplOpen] = useState(false)
+   const [tplName, setTplName] = useState('')
+   const [savingTpl, setSavingTpl] = useState(false)
+   const [tplToDelete, setTplToDelete] = useState<TaskTemplate | null>(null)
+   const [deletingTpl, setDeletingTpl] = useState(false)
+   const [tplManageOpen, setTplManageOpen] = useState(false)
+ 
+   const isWaCheck = type === 'wa_check'
+   // P4 批次采集类型：表单只留 limit + repeat_interval（节奏/代理收敛 daemon 级）
+   const isBatch = ['1688_shop', '1688_company', '1688_contact',
+                    'madeinchina_shop', 'madeinchina_contact'].includes(type)
+ 
+   const setValue = (key: string, v: string) =>
+     setValues((prev) => ({ ...prev, [key]: v }))
+ 
+-  // 用一组 params 回填整个表单（编辑初始化 / 命令导入 / 模板加载共用）
++  // 用一组 params 回填整个表单（编辑初始化 / 模板加载共用）
+   const fillFromParams = (p: Record<string, unknown>) => {
+     const next: Record<string, string> = {}
+     for (const key of ALL_NUM_KEYS) {
+       if (typeof p[key] === 'number') next[key] = String(p[key])
+     }
+     setValues(next)
+-    setChannels(typeof p.channels === 'string' ? (p.channels as string) : '')
++    setChannels(typeof p.channels === 'number' ? String(p.channels) : '')
+     setUseProxy(p.use_proxy !== false)
+     setHeadless(p.headless !== false)
+     setAutoSolve(p.auto_solve !== false)
+     setRetryFailed(p.retry_failed === true)
+     setWaLimit(typeof p.limit === 'number' ? String(p.limit) : '')
+     setBatchLimit(typeof p.limit === 'number' ? String(p.limit) : '')
+-    // 节奏参数：sample_min/max 缺省时用旧参数 interval 回填（向后兼容）
+-    const legacyInterval = typeof p.interval === 'number' ? String(p.interval) : ''
+-    setWaSampleMin(typeof p.sample_min === 'number' ? String(p.sample_min) : legacyInterval)
+-    setWaSampleMax(typeof p.sample_max === 'number' ? String(p.sample_max) : legacyInterval)
+-    setWaBatchNum(typeof p.batch_num === 'number' ? String(p.batch_num) : '')
+-    setWaRestMin(typeof p.batch_rest_min === 'number' ? String(p.batch_rest_min) : '')
+-    setWaRestMax(typeof p.batch_rest_max === 'number' ? String(p.batch_rest_max) : '')
++    // wa 表单只保留 limit + accounts：历史任务 params_json 中的旧字段
++    // （batch_num/sample_min/… 等）后端忽略，回填时跳过未知键（SPEC C3）
+     setSelectedAccounts(
+       Array.isArray(p.accounts)
+         ? (p.accounts as unknown[]).filter((a): a is string => typeof a === 'string')
+         : [],
+     )
+     if (ADVANCED_NUM_KEYS.some((k) => typeof p[k] === 'number')) setAdvancedOpen(true)
+   }
+ 
+   // 打开时初始化：编辑模式回填 task.params，新建模式重置为空白默认
+   useEffect(() => {
+     if (!open) return
+     setPreview(null)
+     setAdvancedOpen(false)
+-    setImportOpen(false)
+-    setImportText('')
+     setTemplateSel('')
+     if (task) {
+       setType(task.type as TaskType)
+       fillFromParams((task.params ?? {}) as Record<string, unknown>)
+       setAdvancedOpen(false) // 编辑初始化不强制展开高级区
+     } else {
+       setType('1688_shop')
+       setValues({})
+       setChannels('')
+       setUseProxy(true)
+       setHeadless(true)
+       setAutoSolve(true)
+       setRetryFailed(false)
+       setWaLimit('')
+-      setWaSampleMin('')
+-      setWaSampleMax('')
+-      setWaBatchNum('')
+-      setWaRestMin('')
+-      setWaRestMax('')
+       setSelectedAccounts([])
+     }
+     // eslint-disable-next-line react-hooks/exhaustive-deps
+   }, [open, task])
+ 
+   // 打开时拉取模板列表
+   useEffect(() => {
+     if (!open) return
+     api.getTaskTemplates()
+       .then(setTemplates)
+@@ -227,66 +204,54 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
+       }
+       const riRaw = (values.repeat_interval ?? '').trim()
+       const riN = Number(riRaw)
+       if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
+       return params
+     }
+     if (isWaCheck) {
+       const params: TaskParams = { accounts: selectedAccounts }
+       const limitN = Number(waLimit)
+       if (waLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) params.limit = limitN
+-      const numOrUndef = (raw: string): number | undefined => {
+-        if (raw.trim() === '') return undefined
+-        const n = Number(raw)
+-        return Number.isFinite(n) && n >= 0 ? n : undefined
+-      }
+-      const sampleMin = numOrUndef(waSampleMin)
+-      if (sampleMin !== undefined) params.sample_min = sampleMin
+-      const sampleMax = numOrUndef(waSampleMax)
+-      if (sampleMax !== undefined) params.sample_max = sampleMax
+-      const batchNum = numOrUndef(waBatchNum)
+-      if (batchNum !== undefined && Number.isInteger(batchNum)) params.batch_num = batchNum
+-      const restMin = numOrUndef(waRestMin)
+-      if (restMin !== undefined) params.batch_rest_min = restMin
+-      const restMax = numOrUndef(waRestMax)
+-      if (restMax !== undefined) params.batch_rest_max = restMax
+-      // 循环间隔：由命令导入 / 模板回填时透传（wa 表单不展示该字段）
++      // 循环间隔：由模板回填时透传（wa 表单不展示该字段）
+       const riRaw = (values.repeat_interval ?? '').trim()
+       const riN = Number(riRaw)
+       if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
+       return params
+     }
+     const params: TaskParams = { use_proxy: useProxy, headless, auto_solve: autoSolve }
+     for (const key of ALL_NUM_KEYS) {
+       const raw = (values[key] ?? '').trim()
+       if (raw === '') continue
+       const n = Number(raw)
+       if (!Number.isInteger(n) || n < 0) continue
+       if (key === 'repeat_interval' && n === 0) continue // 0 = 不循环，不传
+       ;(params as Record<string, unknown>)[key] = n
+     }
+-    if (channels.trim() !== '') params.channels = channels.trim()
++    // 后端 channels 为 int（代理通道 id）：非空才转 Number 提交，NaN 丢弃
++    const channelsRaw = channels.trim()
++    if (channelsRaw !== '') {
++      const channelsN = Number(channelsRaw)
++      if (Number.isFinite(channelsN)) params.channels = channelsN
++    }
+     if (retryFailed && type === '1688_contact') params.retry_failed = true
+     return params
+   }
+ 
+   // 参数签名：内容变化时触发防抖预览
+   const paramsKey = useMemo(
+     () =>
+       JSON.stringify({
+         type, values, channels, useProxy, headless, autoSolve, retryFailed,
+-        waLimit, waSampleMin, waSampleMax, waBatchNum, waRestMin, waRestMax,
+-        selectedAccounts,
++        waLimit, selectedAccounts,
+       }),
+     [type, values, channels, useProxy, headless, autoSolve, retryFailed,
+-      waLimit, waSampleMin, waSampleMax, waBatchNum, waRestMin, waRestMax,
+-      selectedAccounts],
++      waLimit, selectedAccounts],
+   )
+ 
+   // 命令预览：防抖 500ms 调 preview 接口，失败静默不阻塞
+   useEffect(() => {
+     if (!open) return
+     const timer = setTimeout(() => {
+       api.previewTask({ type, params: buildParams() })
+         .then((res) => setPreview(res))
+         .catch(() => setPreview(null))
+     }, 500)
+@@ -307,45 +272,20 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
+       return true
+     }
+     if (isWaCheck) {
+       if (waLimit.trim() !== '') {
+         const n = Number(waLimit)
+         if (!Number.isInteger(n) || n < 0) {
+           toast.error('查号上限需为不小于 0 的整数（0 = 全部未查）')
+           return false
+         }
+       }
+-      const ranges: [string, string, string][] = [
+-        ['查号间隔', waSampleMin, waSampleMax],
+-        ['批间休息', waRestMin, waRestMax],
+-      ]
+-      for (const [label, loRaw, hiRaw] of ranges) {
+-        for (const [side, raw] of [['下限', loRaw], ['上限', hiRaw]] as const) {
+-          if (raw.trim() === '') continue
+-          const n = Number(raw)
+-          if (!Number.isFinite(n) || n < 0) {
+-            toast.error(`${label}${side}需为不小于 0 的数字（秒）`)
+-            return false
+-          }
+-        }
+-        if (loRaw.trim() !== '' && hiRaw.trim() !== '' && Number(loRaw) > Number(hiRaw)) {
+-          toast.error(`${label}下限不能大于上限`)
+-          return false
+-        }
+-      }
+-      if (waBatchNum.trim() !== '') {
+-        const n = Number(waBatchNum)
+-        if (!Number.isInteger(n) || n < 0) {
+-          toast.error('每批查号数量需为不小于 0 的整数（0 = 不分批）')
+-          return false
+-        }
+-      }
+       return true
+     }
+     for (const f of [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS]) {
+       const raw = (values[f.key] ?? '').trim()
+       if (raw === '') continue
+       const n = Number(raw)
+       if (!Number.isInteger(n) || n < 0) {
+         toast.error(`「${f.label}」需为不小于 0 的整数，或留空使用默认值`)
+         return false
+       }
+@@ -377,56 +317,35 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
+         toast.warning('任务状态已变化，当前状态不允许修改参数')
+         onSaved() // 刷新列表反映最新状态
+       } else {
+         toast.error(e instanceof Error ? e.message : editing ? '保存参数失败' : '创建任务失败')
+       }
+     } finally {
+       setSubmitting(false)
+     }
+   }
+ 
+-  // 编辑模式类型只读：导入 / 模板类型与当前任务不同时忽略 type，仅回填参数
++  // 编辑模式类型只读：模板类型与当前任务不同时忽略 type，仅回填参数
+   const applyImportedType = (incoming: TaskType): boolean => {
+     if (!editing) {
+       setType(incoming)
+       return true
+     }
+     if (incoming !== task.type) {
+       toast.info(
+         `类型不可修改，已忽略「${taskTypeLabel(incoming)}」，仅回填参数`,
+       )
+       return false
+     }
+     return true
+   }
+ 
+-  // 从命令导入：调 parse 接口，成功回填 type + 全部参数
+-  const handleParse = async () => {
+-    const command = importText.trim()
+-    if (command === '') {
+-      toast.warning('请先粘贴命令')
+-      return
+-    }
+-    setParsing(true)
+-    try {
+-      const res = await api.parseCommand(command)
+-      const applied = applyImportedType(res.type)
+-      fillFromParams((res.params ?? {}) as Record<string, unknown>)
+-      for (const w of res.warnings ?? []) toast.warning(w)
+-      toast.success(applied ? '命令解析成功，已回填类型与参数' : '命令解析成功，已回填参数')
+-    } catch (e) {
+-      toast.error(e instanceof Error ? e.message : '命令解析失败')
+-    } finally {
+-      setParsing(false)
+-    }
+-  }
+-
+   // 从模板加载：选中即回填
+   const handleLoadTemplate = (idStr: string) => {
+     setTemplateSel('') // 加载动作而非选中态，复位占位
+     const tpl = templates.find((t) => String(t.id) === idStr)
+     if (!tpl) return
+     applyImportedType(tpl.type)
+     fillFromParams((tpl.params ?? {}) as Record<string, unknown>)
+     toast.success(`已加载模板「${tpl.name}」`)
+   }
+ 
+@@ -500,50 +419,20 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
+         <DialogHeader>
+           <DialogTitle>{editing ? `编辑任务 #${task.id} 参数` : '新建任务'}</DialogTitle>
+           <DialogDescription>
+             {editing
+               ? '任务类型不可修改；留空的参数将使用 CLI 默认值。'
+               : '选择任务类型并配置参数，留空即使用 CLI 默认值，创建后进入排队。'}
+           </DialogDescription>
+         </DialogHeader>
+ 
+         <div className="space-y-4">
+-          {/* 从命令导入：折叠区 */}
+-          <Collapsible open={importOpen} onOpenChange={setImportOpen}>
+-            <CollapsibleTrigger asChild>
+-              <Button variant="outline" size="sm" className="w-full justify-between">
+-                <span className="flex items-center gap-1.5">
+-                  <Wand2 className="h-3.5 w-3.5" />
+-                  从命令导入
+-                </span>
+-                <ChevronDown
+-                  className={`h-4 w-4 transition-transform ${importOpen ? 'rotate-180' : ''}`}
+-                />
+-              </Button>
+-            </CollapsibleTrigger>
+-            <CollapsibleContent className="space-y-2 pt-2">
+-              <Textarea
+-                value={importText}
+-                onChange={(e) => setImportText(e.target.value)}
+-                placeholder="python -m fetcher 1688 company --proxy --headed -n 50 --worker 1"
+-                rows={3}
+-                className="font-mono text-xs"
+-              />
+-              <p className="text-xs text-muted-foreground">
+-                支持 while 循环 + sleep 写法（解析为循环间隔）
+-              </p>
+-              <Button size="sm" onClick={handleParse} disabled={parsing}>
+-                {parsing ? '解析中…' : '解析'}
+-              </Button>
+-            </CollapsibleContent>
+-          </Collapsible>
+-
+           {/* 从模板加载 */}
+           <div className="space-y-2">
+             <Label>从模板加载</Label>
+             <div className="flex gap-2">
+               <Select value={templateSel} onValueChange={handleLoadTemplate}>
+                 <SelectTrigger className="flex-1">
+                   <SelectValue
+                     placeholder={templates.length > 0 ? '选择模板，立即回填表单' : '暂无已保存模板'}
+                   />
+                 </SelectTrigger>
+@@ -621,104 +510,32 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
+                 <p className="text-xs text-muted-foreground">
+                   批次跑完后 N 秒自动重启同参数批次（0 = 不循环）
+                 </p>
+               </div>
+               <p className="text-xs text-muted-foreground">
+                 节奏/代理/并发已收敛到 daemon 启动参数，不再逐任务下发。
+               </p>
+             </>
+           ) : isWaCheck ? (
+             <>
+-              <div className="grid grid-cols-2 gap-3">
+-                <div className="space-y-2">
+-                  <Label htmlFor="wa-limit">查号上限</Label>
+-                  <Input
+-                    id="wa-limit"
+-                    type="number"
+-                    min={0}
+-                    value={waLimit}
+-                    placeholder="0 = 全部未查"
+-                    onChange={(e) => setWaLimit(e.target.value)}
+-                  />
+-                  <p className="text-xs text-muted-foreground">0 = 全部未查</p>
+-                </div>
+-                <div className="space-y-2">
+-                  <Label htmlFor="wa-batch-num">每批查号数量（个）</Label>
+-                  <Input
+-                    id="wa-batch-num"
+-                    type="number"
+-                    min={0}
+-                    value={waBatchNum}
+-                    placeholder="默认 500"
+-                    onChange={(e) => setWaBatchNum(e.target.value)}
+-                  />
+-                  <p className="text-xs text-muted-foreground">默认 500 个号码/批，0 = 不分批</p>
+-                </div>
+-              </div>
+-
+-              <div className="grid grid-cols-2 gap-3">
+-                <div className="space-y-2">
+-                  <Label htmlFor="wa-sample-min">查号间隔下限（秒）</Label>
+-                  <Input
+-                    id="wa-sample-min"
+-                    type="number"
+-                    min={0}
+-                    step={0.5}
+-                    value={waSampleMin}
+-                    placeholder="默认 1.5"
+-                    onChange={(e) => setWaSampleMin(e.target.value)}
+-                  />
+-                </div>
+-                <div className="space-y-2">
+-                  <Label htmlFor="wa-sample-max">查号间隔上限（秒）</Label>
+-                  <Input
+-                    id="wa-sample-max"
+-                    type="number"
+-                    min={0}
+-                    step={0.5}
+-                    value={waSampleMax}
+-                    placeholder="默认 1.5"
+-                    onChange={(e) => setWaSampleMax(e.target.value)}
+-                  />
+-                </div>
+-              </div>
+-              <p className="-mt-1.5 text-xs text-muted-foreground">
+-                每个号码查询之间随机停顿，上下限相等 = 固定间隔
+-              </p>
+-
+-              <div className="grid grid-cols-2 gap-3">
+-                <div className="space-y-2">
+-                  <Label htmlFor="wa-rest-min">批间休息下限（秒）</Label>
+-                  <Input
+-                    id="wa-rest-min"
+-                    type="number"
+-                    min={0}
+-                    value={waRestMin}
+-                    placeholder="默认 60"
+-                    onChange={(e) => setWaRestMin(e.target.value)}
+-                  />
+-                </div>
+-                <div className="space-y-2">
+-                  <Label htmlFor="wa-rest-max">批间休息上限（秒）</Label>
+-                  <Input
+-                    id="wa-rest-max"
+-                    type="number"
+-                    min={0}
+-                    value={waRestMax}
+-                    placeholder="默认 180"
+-                    onChange={(e) => setWaRestMax(e.target.value)}
+-                  />
+-                </div>
++              <div className="max-w-xs space-y-2">
++                <Label htmlFor="wa-limit">查号上限</Label>
++                <Input
++                  id="wa-limit"
++                  type="number"
++                  min={0}
++                  value={waLimit}
++                  placeholder="0 = 全部未查"
++                  onChange={(e) => setWaLimit(e.target.value)}
++                />
++                <p className="text-xs text-muted-foreground">0 = 全部未查</p>
+               </div>
+-              <p className="-mt-1.5 text-xs text-muted-foreground">
+-                每采满一批后随机长休息（防风控），随后自动开始下一批
+-              </p>
+ 
+               <div className="space-y-2 rounded-md border border-border px-3 py-2">
+                 <Label>查号账号</Label>
+                 {waAccounts.length === 0 ? (
+                   <p className="text-xs text-muted-foreground">
+                     暂无已登录账号，将使用默认账号
+                   </p>
+                 ) : (
+                   <div className="space-y-2">
+                     {waAccounts.map((a) => (
+@@ -807,21 +624,21 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
+                           onCheckedChange={setRetryFailed}
+                         />
+                       </div>
+                     )}
+                   </div>
+                 </CollapsibleContent>
+               </Collapsible>
+             </>
+           )}
+ 
+-          {/* 命令预览：wa_check 返回 cmd=null + 说明文案 */}
++          {/* 命令预览：批次类型（含 wa_check）返回 cmd=null + 批次文案 */}
+           <div className="space-y-1.5">
+             <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
+               <Terminal className="h-3.5 w-3.5" />
+               命令预览
+             </div>
+             <div className="min-h-12 rounded-md border border-border bg-muted/50 px-3 py-2">
+               {preview ? (
+                 <code className="block whitespace-pre-wrap break-all font-mono text-xs text-foreground">
+                   {preview.cmdline}
+                 </code>
+diff --git a/platform/web/src/pages/tasks/task-ui.tsx b/platform/web/src/pages/tasks/task-ui.tsx
+index 8f1e886..c8aa31e 100644
+--- a/platform/web/src/pages/tasks/task-ui.tsx
++++ b/platform/web/src/pages/tasks/task-ui.tsx
+@@ -117,50 +117,35 @@ export function eventWorker(ev: { message: string; data?: { worker?: number | st
+ 
+ // 秒数人性化：>=3600 显小时、>=60 显分钟、否则显秒（最多 1 位小数）
+ function humanizeSeconds(sec: number): string {
+   const trim = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))
+   if (sec >= 3600) return `${trim(sec / 3600)}小时`
+   if (sec >= 60) return `${trim(sec / 60)}分钟`
+   return `${sec}秒`
+ }
+ 
+ // 任务参数摘要：表格 params 列的小字展示
+-// 采集类示例：n=10 批=4 代理 无头 循环30分钟；wa_check：上限=500 间隔=2~5s 批=10次
++// 采集类示例：n=10 批=4 代理 无头 循环30分钟；wa_check：上限=500 账号=xiaohao-1
++// 批次类型：上限=200 循环30分钟
+ export function paramsSummary(task: { type: string; params: Record<string, unknown> }): string {
+   const p = task.params ?? {}
+   const num = (k: string): number | null =>
+     typeof p[k] === 'number' && Number.isFinite(p[k] as number) ? (p[k] as number) : null
+   const repeat = num('repeat_interval')
+   const repeatPart = repeat !== null && repeat > 0 ? `循环${humanizeSeconds(repeat)}` : null
+-  const range = (loK: string, hiK: string): string | null => {
+-    const lo = num(loK)
+-    const hi = num(hiK)
+-    if (lo === null && hi === null) return null
+-    if (lo !== null && hi !== null) return lo === hi ? `${lo}` : `${lo}~${hi}`
+-    return `${lo ?? ''}~${hi ?? ''}`
+-  }
+ 
+   if (task.type === 'wa_check') {
+     const parts: string[] = []
+     const limit = num('limit')
+     if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '全部未查')
+     const accs = Array.isArray(p.accounts) ? (p.accounts as unknown[]).filter((a) => typeof a === 'string') : []
+     if (accs.length > 0) parts.push(`账号=${accs.join(',')}`)
+-    const interval = num('interval') // 旧参数：固定间隔
+-    const sample = range('sample_min', 'sample_max')
+-    if (sample !== null) parts.push(`间隔=${sample}s`)
+-    else if (interval !== null) parts.push(`间隔=${interval}s`)
+-    const batchNum = num('batch_num')
+-    const rest = range('batch_rest_min', 'batch_rest_max')
+-    if (batchNum !== null && batchNum > 0) {
+-      parts.push(`批=${batchNum}个` + (rest !== null ? `·休${rest}s` : ''))
+-    }
+     if (repeatPart) parts.push(repeatPart)
+     return parts.length > 0 ? parts.join(' ') : '默认参数'
+   }
+ 
+   // P4 批次采集类型（1688/madeinchina shop/company/contact）：
+   // 只读 limit（contact=条数、shop/company=页数）+ repeat_interval
+   const BATCH_TYPES = new Set(['1688_shop', '1688_company', '1688_contact',
+                                'madeinchina_shop', 'madeinchina_contact'])
+   if (BATCH_TYPES.has(task.type)) {
+     const parts: string[] = []
+@@ -175,14 +160,13 @@ export function paramsSummary(task: { type: string; params: Record<string, unkno
+   if (batchNum !== null) parts.push(`n=${batchNum}`)
+   const maxBatches = num('max_batches')
+   if (maxBatches !== null) parts.push(maxBatches > 0 ? `批=${maxBatches}` : '批=∞')
+   const limit = num('limit')
+   if (limit !== null && limit > 0) parts.push(`上限=${limit}`)
+   const workers = num('workers')
+   if (workers !== null) parts.push(`w=${workers}`)
+   if (p.use_proxy === true) parts.push('代理')
+   if (p.headless === true) parts.push('无头')
+   else if (p.headless === false) parts.push('有头')
+-  if (p.retry_failed === true) parts.push('重试失败')
+   if (repeatPart) parts.push(repeatPart)
+   return parts.length > 0 ? parts.join(' ') : '默认参数'
+ }
+
+---
+
+# 终审 Minor 修复报告（M1–M4）
+
+> 终审 reviewer 给出 MERGE READY，另附 4 条建议性 Minor。本报告记录修复内容与验证结果。
+> commit：`fix(p5): 终审 M1-M4——注释同步 + channels 整数校验 + 迁移回滚加固`
+
+## 修复清单
+
+| # | 文件 | 修复 |
+|---|---|---|
+| M1 | `platform/server/app/api/tasks.py` | 过期注释同步：`batch_num/sample_min/sample_max` 实为 subprocess 类型（yiwugo）节奏参数；wa_check 走 daemon 批次（`enqueue_wa_batch` 只收 accounts/limit），只消费 `limit/accounts` |
+| M2 | `platform/web/src/pages/tasks/TaskFormDialog.tsx` | channels 转换 `Number.isFinite` → `Number.isInteger`：`'1.5'` 不再放行（后端 int 字段会 422）；空串/NaN/小数均不提交 |
+| M3 | `platform/server/app/db.py` | 迁移 except 分支 `conn.execute("ROLLBACK")` → `conn.rollback()`：Python sqlite3 幂等、无事务时不抛，避免掩盖原始异常（已实测：`execute('ROLLBACK')` 在无事务时抛 `OperationalError: cannot rollback - no transaction is active`，方法版为 no-op） |
+| M4 | `platform/server/app/db.py` | 迁移段注释补充前提：「本库从未启用 PRAGMA foreign_keys；若启用，DROP TABLE tasks 会因 task_events/proxy_channels 引用直接失败」 |
+
+## 不做（parked，主 Agent 已裁决）
+
+- M5（PRAGMA table_info(tasks) 无表守卫）：非 P5 回归、无当前触发路径。
+- M6（证据卫生 flows 行数 1 vs 3）：只改 ledger 说明，不动代码。
+
+## 验证
+
+- 前端：`platform/web` 下 `npx tsc -b` → **零错误**（exit 0）。
+- 后端：`platform/server` 下 `.venv/bin/python -m pytest tests/ -q` → **62 passed**（1 StarletteDeprecationWarning，既有）。
+- 仅上述 4 处改动，未触及其他文件。
diff --git a/platform/server/app/api/tasks.py b/platform/server/app/api/tasks.py
index 4378964..fba97b2 100644
--- a/platform/server/app/api/tasks.py
+++ b/platform/server/app/api/tasks.py
@@ -109,22 +109,22 @@ class TaskParams(BaseModel):
     max_consecutive_fail: int | None = None  # → --max-consecutive-fail
     block_rest_min: float | None = None     # → --block-rest-min
     block_rest_max: float | None = None     # → --block-rest-max
     # 开关
     use_proxy: bool | None = None           # true → --proxy
     headless: bool | None = None            # false → --headed
     auto_solve: bool | None = None          # false → --no-auto-solve
     retry_failed: bool | None = None        # 前端 1688_contact 表单开关遗留，不映射 CLI
     # wa_check 专用：
     accounts: list[str] | None = None       # 账号池，空 = 仅默认账号
-    # 注：wa_check 复用上方 batch_num（每批调用次数）、
-    # sample_min / sample_max（调用间隔范围）三个字段
+    # 注：batch_num/sample_min/sample_max 为 subprocess 类型（yiwugo）节奏参数；
+    # wa_check 走 daemon 批次，只消费 limit/accounts
     # 循环模式：本轮正常结束（done/failed）后 N 秒自动重启；None/<=0 = 不循环
     repeat_interval: int | None = None
 
 
 class TaskCreate(BaseModel):
     type: str = Field(...)
     params: TaskParams = Field(default_factory=TaskParams)
 
 
 @router.post("/tasks", status_code=201)
diff --git a/platform/server/app/db.py b/platform/server/app/db.py
index ee6d11d..9a05948 100644
--- a/platform/server/app/db.py
+++ b/platform/server/app/db.py
@@ -95,20 +95,22 @@ def migrate() -> None:
             "SELECT name FROM sqlite_master WHERE type='table'")}
         if "work_items" in tables:
             conn.execute(
                 "CREATE INDEX IF NOT EXISTS idx_work_items_batch"
                 " ON work_items(batch_id, status)")
         # P5：tasks 表重建——删除 celery_id/flow_id 死列与 flows 表（方案 B 交换式）
         # 守卫：旧 schema 才重建；已迁移库重跑 migrate() 零变化（幂等）。
         # 交换顺序（建 tasks_new → INSERT SELECT → DROP tasks → RENAME）保证
         # task_events/proxy_channels 的 REFERENCES tasks(id) 不被 SQLite RENAME
         # 重写成指向被删表名（RENAME-first 会让外键悬空）。
+        # 前提：本库从未启用 PRAGMA foreign_keys；若启用，DROP TABLE tasks 会
+        # 因 task_events/proxy_channels 引用直接失败。
         cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
         if "celery_id" in cols:
             conn.execute("BEGIN IMMEDIATE")
             try:
                 conn.execute("""
                     CREATE TABLE tasks_new (
                         id INTEGER PRIMARY KEY AUTOINCREMENT,
                         type TEXT NOT NULL,
                         params_json TEXT NOT NULL,
                         status TEXT NOT NULL DEFAULT 'pending',
@@ -126,21 +128,21 @@ def migrate() -> None:
                     SELECT id, type, params_json, status, progress_json,
                            stop_requested, error, created_at, started_at,
                            finished_at
                     FROM tasks""")
                 conn.execute("DROP TABLE tasks")
                 conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
                 conn.execute("DROP TABLE IF EXISTS flows")
                 conn.execute("CREATE INDEX idx_tasks_status ON tasks(status)")
                 conn.execute("COMMIT")
             except Exception:
-                conn.execute("ROLLBACK")  # 失败留原表（tasks 未动）
+                conn.rollback()  # 幂等：无事务时不抛；失败留原表（tasks 未动）
                 raise
         conn.commit()
     finally:
         conn.close()
 
 
 # ==================== P4 批次入队（平台侧 SQL，与 fetcher 同事务语义） ====================
 # SPEC §3.1 裁定：平台不 import fetcher，批次 SQL 平台侧重写；两边重复
 # 是有意为之的边界，语义由同一 SPEC + 测试锚定。
 
diff --git a/platform/web/src/pages/tasks/TaskFormDialog.tsx b/platform/web/src/pages/tasks/TaskFormDialog.tsx
index 4413d01..9ef73bc 100644
--- a/platform/web/src/pages/tasks/TaskFormDialog.tsx
+++ b/platform/web/src/pages/tasks/TaskFormDialog.tsx
@@ -219,25 +219,25 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     }
     const params: TaskParams = { use_proxy: useProxy, headless, auto_solve: autoSolve }
     for (const key of ALL_NUM_KEYS) {
       const raw = (values[key] ?? '').trim()
       if (raw === '') continue
       const n = Number(raw)
       if (!Number.isInteger(n) || n < 0) continue
       if (key === 'repeat_interval' && n === 0) continue // 0 = 不循环，不传
       ;(params as Record<string, unknown>)[key] = n
     }
-    // 后端 channels 为 int（代理通道 id）：非空才转 Number 提交，NaN 丢弃
+    // 后端 channels 为 int（代理通道 id）：整数才提交（Number.isFinite 会放行 '1.5'，后端 int 会 422）
     const channelsRaw = channels.trim()
     if (channelsRaw !== '') {
       const channelsN = Number(channelsRaw)
-      if (Number.isFinite(channelsN)) params.channels = channelsN
+      if (Number.isInteger(channelsN)) params.channels = channelsN
     }
     if (retryFailed && type === '1688_contact') params.retry_failed = true
     return params
   }
 
   // 参数签名：内容变化时触发防抖预览
   const paramsKey = useMemo(
     () =>
       JSON.stringify({
         type, values, channels, useProxy, headless, autoSolve, retryFailed,
