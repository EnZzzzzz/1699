=== git log ===
56953e9 docs: 同步 daemon P0 完成状态（落地路线表/README CLI/AGENTS 项目结构）

=== diff --stat ===
 AGENTS.md                                          |  2 +
 .../task-3.2-brief.md                              | 22 +++++++++
 .../task-3.2-report.md                             | 52 ++++++++++++++++++++++
 docs/scheduler-architecture.md                     |  2 +-
 fetcher/README.md                                  | 10 +++++
 5 files changed, 87 insertions(+), 1 deletion(-)

=== diff -U10 ===
diff --git a/AGENTS.md b/AGENTS.md
index 7756a9d..64cb1e8 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -2,20 +2,22 @@
 
 > 本文件是面向 AI 编码 agent 的项目级指令。改代码前先读本文件；**改前端前必须读 [DESIGN.md](DESIGN.md)**（设计规范唯一文字来源，本文件只做摘要与强制引用）。
 
 ## 1. 项目结构
 
 ```
 fetcher/          采集框架（Python 包，可独立安装）：
                   核心层 core/（ActionResult/Outcome/WorkerContext）· 原子层 atoms/（Atom 协议）
                   网络层 net/ · 判断层 detect/ · 策略层 strategy/ · 站点插件 sites/
                   CLI：python -m fetcher 1688 shop|contact|company / yiwugo search / taobao search
+                  CLI 另有 daemon 常驻模式：1688 contact 从 work_items 表消费（空队列挂起等货，
+                  与旧 CLI 同站互斥），见 docs/scheduler-architecture.md
                   vendor/wa-check/：内置 Node/Baileys CLI（WhatsApp 查号协议实现）
 platform/         管理系统（前后端分离）
   server/         FastAPI 后端（端口 8765）：app/api/ REST + SSE · app/runner.py 任务监督器
                   app/wa_tasks.py（wa_check 进程内执行器）· app/wa_login.py（WhatsApp 扫码登录）
   web/            React 18 + Vite + TS + Tailwind + shadcn/ui 前端（端口 3000，vite dev 有 HMR）
   start.sh        一键启动后端+前端；stop.sh 停止
 .cache/1688.db    SQLite 主库（WAL 模式）：shops / contacts / tasks / task_events /
                   providers / proxy_channels / task_templates
 scraper/ util/    旧版脚本，**只读参考，禁止修改**（新代码一律进 fetcher/ 或 platform/）
 docs/             flow-architecture.md（fetcher 框架设计）、scheduler-architecture.md（调度器设计：
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.2-brief.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.2-brief.md
new file mode 100644
index 0000000..74612e2
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.2-brief.md
@@ -0,0 +1,22 @@
+# Step 3.2 brief — 文档同步
+
+> 来源：PLAN.md Phase 3 Step 3.2。本文本是你的需求唯一来源。
+
+## 内容
+
+三处文档更新（daemon P0 已完成的对外同步）：
+
+1. **`docs/scheduler-architecture.md` §10 落地路线表**：P0 行标注完成——在「内容」或「验收」单元格追加「✅ 已完成（2026-08-07，实施记录 docs/feat_2026-08-07_fetcher-daemon-p0/）」。不动其他行。
+2. **`fetcher/README.md`** CLI 用法段：补 daemon 子命令说明。先读 README 现有 CLI 文档的写法和详略程度，跟随其风格。要点：`python -m fetcher daemon` = 1688 contact 常驻模式（工作项从 work_items 表认领，shops pending 自动补货，空队列挂起等货）；支持 add_common_args 全套参数 + `--queue`（当前仅默认 `crawl_1688_contact`）；`--limit N` 可让 daemon 跑完 N 个后退出（联调用）；**与旧 CLI 同站互斥**（两边启动都会 reset in_progress，同站同跑会互相重置——这是 PLAN 冲突扫描的明文裁定，必须写清楚）。
+3. **`AGENTS.md` §1 项目结构**：fetcher/ 段补一句 daemon 模式（一行以内，如「CLI 另有 daemon 常驻模式：1688 contact 从 work_items 表消费，见 docs/scheduler-architecture.md」）。读 AGENTS.md §1 的现有格式，保持对齐。
+
+## 验收
+
+- [ ] 三处更新完成，风格与各自文件既有格式一致
+- [ ] README 的互斥约束写明
+- [ ] 不含任何代码改动
+
+## 约束
+
+- 只动这三个文件。
+- 事实口径以 `docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md` §3.3/§3.4 为准；不确定的行为描述先去读 `fetcher/fetcher/cli/main.py` 的 daemon 分支和 `control/daemon_task.py` 核实，不要凭印象写。
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.2-report.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.2-report.md
new file mode 100644
index 0000000..c0e6ab8
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.2-report.md
@@ -0,0 +1,52 @@
+# Step 3.2 report — 文档同步
+
+> 依据 brief：task-3.2-brief.md。只改三处文档，无代码改动。
+
+## 改动明细
+
+### 1. docs/scheduler-architecture.md §10 落地路线表
+
+P0 行的「验收」单元格末尾追加：
+
+```
+；✅ 已完成（2026-08-07，实施记录 docs/feat_2026-08-07_fetcher-daemon-p0/）
+```
+
+其他行未动。
+
+### 2. fetcher/README.md 快速上手 CLI 段
+
+- 代码块内新增一行：`python -m fetcher daemon --proxy  # 常驻模式：1688 contact 从 work_items 队列持续消费`（置于站点/任务命令之后、注册表说明注释之前）。
+- 代码块后新增一段说明，要点：
+  - daemon = 1688 contact 常驻模式：从 `work_items` 表认领工作项，shops pending 自动补货入队，队列取空挂起等货而非退出；
+  - 支持全部共享网络层参数（`--proxy` / `--workers` / `--headed` 等），另有 `--queue`（P0 仅默认值 `crawl_1688_contact`，不开放选择）；
+  - `--limit N` 跑完 N 个后退出，作冒烟/联调收工手段；
+  - **互斥约束明文写出**：daemon 与旧 CLI `1688 contact` 同站互斥——两边启动都会把 shops 的 in_progress 重置为 pending（daemon 另回收 work_items 的 claimed 残留），同站同跑会互相重置，同一时刻只跑一个。
+
+### 3. AGENTS.md §1 项目结构
+
+fetcher/ 段的 CLI 行后新增两行（缩进对齐既有块格式）：
+
+```
+                  CLI 另有 daemon 常驻模式：1688 contact 从 work_items 表消费（空队列挂起等货，
+                  与旧 CLI 同站互斥），见 docs/scheduler-architecture.md
+```
+
+（brief 要求「一行以内」，因项目结构块为多行续行格式、单行长行会明显超出对齐宽度，拆成两条续行，内容仍是一句话。）
+
+## 事实核对位置
+
+- `fetcher/fetcher/cli/main.py:51-61`：daemon parser 挂载（与站点平级）、`-n/--num`、`--limit`、`--queue`（默认 `crawl_1688_contact`）、`add_common_args(p_daemon, ...)` 全套共享参数 — 核实 README 参数描述。
+- `fetcher/fetcher/cli/main.py:202-243` `_run_daemon`：`get_site("1688")` + `make_task("contact")` 包 `DaemonTaskProxy`；启动时先 `reset_claimed_work_items()` 再 `reset_in_progress()` — 核实「1688 contact」「回收 claimed 残留」。
+- `fetcher/fetcher/sites/alibaba1688/contact.py:108`：旧 CLI contact 的 `prepare` 同样调 `reset_in_progress(...)` — 核实「两边启动都会 reset in_progress」的互斥表述。
+- SPEC §3.3（shops 状态流、空队列条件变量挂起）、§3.4（CLI 挂载、`--limit` 退出语义）— 口径与 brief 一致，未另行扩展。
+
+## 自查（对照 brief 验收）
+
+- [x] 三处更新完成，风格跟随各文件既有格式（表格单元格追加、README 代码块+说明段、AGENTS 续行缩进）
+- [x] README 互斥约束写明（加粗 + 原因说明）
+- [x] 不含任何代码改动（git status 仅三个文档文件 + brief/report）
+
+## 疑虑
+
+- AGENTS.md brief 原文要求「一行以内」，实际按项目结构块的既有续行格式拆为两条缩进续行（语义仍一句话）；若严格要物理一行可再合并，但会明显超出块内对齐宽度。
diff --git a/docs/scheduler-architecture.md b/docs/scheduler-architecture.md
index b94e0a5..a605cfb 100644
--- a/docs/scheduler-architecture.md
+++ b/docs/scheduler-architecture.md
@@ -198,21 +198,21 @@ CREATE INDEX idx_work_items_claim ON work_items(queue, status, id);
 
 - runner 新增 daemon 管理：`start.sh` 拉起 `python -m fetcher daemon`（常驻，与 uvicorn 同级），停止/重启走 pidfile；daemon 输出行泵入 `task_events` 的机制沿用。
 - `TASK_COMMANDS` 中浏览器采集类任务从「拼 CLI 起子进程」改为「INSERT work_items 批次」；API 类/本地类同理。wa_check 从 runner 进程内线程迁入 dispatcher 的 LocalExecutor。
 - API 变更：`POST /api/tasks` 创建批次；`GET /api/tasks/{id}` 进度响应增加 `queue` 维度统计与消费者分配情况；新增 `GET /api/dispatcher/consumers`（消费者列表：通道、当前工作项、各站点冷却剩余）用于前端看板。
 - 前端（另按 DESIGN.md 实施）：批次详情页展示工作项队列进度；新增消费者看板（每通道当前在干什么、各站点冷却倒计时——正好复用 flow-architecture §8 的 Sleep 环形进度设计）。
 
 ## 10. 落地路线
 
 | 阶段 | 内容 | 验收 |
 |---|---|---|
-| P0 daemon 骨架 | work_items 表 + Dispatcher + 条件变量调度循环 + BrowserConsumer（单站点 1688）；CLI 新增 `daemon` 子命令 | 单站点行为与现有 CLI 等价（节奏、产出、事件口径一致） |
+| P0 daemon 骨架 | work_items 表 + Dispatcher + 条件变量调度循环 + BrowserConsumer（单站点 1688）；CLI 新增 `daemon` 子命令 | 单站点行为与现有 CLI 等价（节奏、产出、事件口径一致）；✅ 已完成（2026-08-07，实施记录 docs/feat_2026-08-07_fetcher-daemon-p0/） |
 | P1 冷却策略迁移 | `strategies.py` 的 sleep 全部改为输出冷却时长；`loop.py` 流水线原子化改造 | 同一批次总耗时、请求节奏分布与旧实现相当 |
 | P2 identity 分桶 | (IP,site) 键改造 + BrowserContext 隔离 + 簿记表迁移 | 同 IP 两站点 Cookie/簿记互不污染（单测覆盖） |
 | P3 第二站点接入 | madeinchina 队列接入，跨站填充生效 | 同通道 madeinchina 冷却期间执行 1688 工作项，两边各自预算不超标 |
 | P4 平台切换 | runner 改批次提交、wa_check 迁入、API + 前端看板 | 平台创建/停止/监控全流程走 dispatcher |
 | P5 退役旧路径 | 旧 subprocess 采集路径冻结→删除；修订 flow-architecture.md §2/§10 | 旧代码路径删除，文档同步 |
 
 每个阶段独立可回滚：P0~P3 期间旧 CLI 路径保持可用，灰度对比等价后再切。
 
 ## 11. 明确的非目标（v1 不做）
 
diff --git a/fetcher/README.md b/fetcher/README.md
index 9b2b7af..1e59689 100644
--- a/fetcher/README.md
+++ b/fetcher/README.md
@@ -27,23 +27,33 @@ pip install -e ".[cloak]" # 另装 cloakbrowser（运行采集所需）
 
 ## 快速上手
 
 ```bash
 # CLI（console_scripts: fetcher；或 python -m fetcher）
 python -m fetcher 1688 contact --proxy --headed -n 100 --max-batches 4
 python -m fetcher 1688 shop --proxy -n 500 --max-batches 2
 python -m fetcher 1688 company --proxy --limit 300
 python -m fetcher 1688 contact --tmd-report     # 只出 tmd 报表
 python -m fetcher taobao search --proxy -n 30   # 第二个站点：淘宝商品搜索
+python -m fetcher daemon --proxy                # 常驻模式：1688 contact 从 work_items 队列持续消费
 # 站点/任务子命令由 sites 注册表自动发现生成，加目录即接入
 ```
 
+`daemon` 子命令 = 1688 contact 常驻模式：消费者从 `work_items` 表认领工作项，
+shops 表 pending 行自动补货入队，队列取空后挂起等货而非退出。支持全部共享
+网络层参数（`--proxy` / `--workers` / `--headed` 等，同各任务子命令），另有
+`--queue`（P0 仅默认值 `crawl_1688_contact`，不开放其他选择）；`--limit N`
+跑完 N 个后退出，作冒烟/联调的收工手段。
+**daemon 与旧 CLI `1688 contact` 同站互斥**：两边启动都会把 shops 的
+in_progress 重置为 pending（daemon 另回收 work_items 的 claimed 残留），
+同站同跑会互相重置，同一时刻只跑一个。
+
 ```python
 # 库用法（CLI 即以下装配的薄壳）
 from fetcher import RunConfig, Alibaba1688Plugin, Policy
 from fetcher.net.proxy import QingGuoProvider
 from fetcher.control import Engine
 
 cfg = RunConfig(use_proxy=True, headless=False, batch_num=100)
 site = Alibaba1688Plugin()
 task = site.make_task("contact")          # contact / shop / company
 task.prepare(cfg)
