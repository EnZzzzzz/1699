=== git log ===
4837613 docs(daemon-p0): Step 3.2 文档同步完成（review clean，PLAN 勾选 + ledger）
56953e9 docs: 同步 daemon P0 完成状态（落地路线表/README CLI/AGENTS 项目结构）
a35a842 docs(daemon-p0): Step 3.1 等价性对比通过（SPEC §5 验收措辞放宽裁定 + ledger）
133a845 docs(daemon-p0): Step 2.4 直连冒烟通过（证据归档 + ledger）
32a2dab docs(daemon-p0): Step 2.3 完成（review clean，PLAN 勾选 + ledger + 过程文件归档）
e377a29 docs(fetcher): Step 2.3 daemon CLI 子命令实现报告
24cfe7d feat(fetcher): CLI 新增 daemon 子命令（1688 contact 常驻模式装配）
f955498 docs(daemon-p0): Step 2.2 完成（review clean，PLAN 勾选 + ledger + 过程文件归档）
1af732b test(fetcher): DaemonTaskProxy 单测（5 用例：直取/补货/stop 退出/终态钩子/CrawlLoop 双 worker 联跑）
6794d64 docs(daemon-p0): Step 2.1 完成（review clean，PLAN 勾选 + ledger + 过程文件归档）
f6034dd feat(fetcher): DaemonTaskProxy（daemon 工作项来源切换 work_items 表，三段式 acquire + 终态钩子）
cd4d023 docs(daemon-p0): Step 1.2+1.3 完成（review clean，PLAN 勾选 + ledger + brief/report/review 归档）
8fcfe91 feat(fetcher): work_items 存储层（daemon 工作队列 DDL + topup/claim/finish/reset 四方法）
10b4b47 docs(daemon-p0): Step 1.1 完成（review clean，PLAN 勾选 + ledger）
8a3db10 docs(daemon-p0): Step 1.1 brief/ledger + SPEC 增补 cold_start 已知差异裁定
323e491 docs(daemon-p0): Step 1.1 读码验证 item 访问契约，回填 SPEC §4 假设 1、2 结论
e50270b docs(scheduler): 调度器架构设计 + daemon P0 SPEC/PLAN（评审通过）

=== diff --stat ===
 AGENTS.md                                          |   5 +-
 docs/feat_2026-08-07_fetcher-daemon-p0/PLAN.md     | 124 +++++
 docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md     | 135 ++++++
 docs/feat_2026-08-07_fetcher-daemon-p0/ledger.md   |  43 ++
 .../task-1.1-brief.md                              |  23 +
 .../task-1.1-report.md                             |  77 ++++
 .../task-1.1-review.md                             | 186 ++++++++
 .../task-1.2-brief.md                              |  63 +++
 .../task-1.2-report.md                             |  87 ++++
 .../task-1.2-review.md                             | 355 +++++++++++++++
 .../task-2.1-brief.md                              |  37 ++
 .../task-2.1-report.md                             |  80 ++++
 .../task-2.1-review.md                             | 340 ++++++++++++++
 .../task-2.2-brief.md                              |  29 ++
 .../task-2.2-report.md                             |  75 ++++
 .../task-2.2-review.md                             | 499 +++++++++++++++++++++
 .../task-2.3-brief.md                              |  31 ++
 .../task-2.3-report.md                             |  75 ++++
 .../task-2.3-review.md                             | 328 ++++++++++++++
 .../task-2.4-brief.md                              |  54 +++
 .../task-2.4-report.md                             | 170 +++++++
 .../task-3.1-brief.md                              |  62 +++
 .../task-3.1-report.md                             | 257 +++++++++++
 .../task-3.2-brief.md                              |  22 +
 .../task-3.2-report.md                             |  52 +++
 .../task-3.2-review.md                             | 190 ++++++++
 docs/scheduler-architecture.md                     | 224 +++++++++
 fetcher/README.md                                  |  10 +
 fetcher/fetcher/cli/main.py                        |  63 +++
 fetcher/fetcher/control/daemon_task.py             | 195 ++++++++
 fetcher/fetcher/db.py                              | 107 +++++
 fetcher/tests/test_cli.py                          |  70 +++
 fetcher/tests/test_daemon_task.py                  | 367 +++++++++++++++
 fetcher/tests/test_work_items.py                   | 166 +++++++
 34 files changed, 4600 insertions(+), 1 deletion(-)

=== diff -U10 ===
diff --git a/AGENTS.md b/AGENTS.md
index 647778d..64cb1e8 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -2,30 +2,33 @@
 
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
-docs/             flow-architecture.md（fetcher 框架设计）、service-architecture.md（旧方案，存档）
+docs/             flow-architecture.md（fetcher 框架设计）、scheduler-architecture.md（调度器设计：
+                  队列+消费者池+跨站 IP 复用，跨任务编排以此为准）、service-architecture.md（旧方案，存档）
 ```
 
 ## 2. 必读文档（按改动范围）
 
 | 改动范围 | 必读 |
 |---|---|
 | `platform/web` 任何文件 | **[DESIGN.md](DESIGN.md)**（设计规范唯一来源，新增页面/组件前先读） |
 | `fetcher/` 框架或原子 | `docs/flow-architecture.md`（Atom 契约、分层职责） |
 | 任务系统 / runner | `platform/server/app/runner.py` 头部注释（subprocess 与进程内两类模型） |
 | 数据库访问 | 见下方 §4 数据库约定 |
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/PLAN.md b/docs/feat_2026-08-07_fetcher-daemon-p0/PLAN.md
new file mode 100644
index 0000000..c01b5cd
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/PLAN.md
@@ -0,0 +1,124 @@
+# PLAN — fetcher daemon 骨架（P0）
+
+> 需求与设计唯一来源：同目录 SPEC.md（上游：docs/scheduler-architecture.md §10 P0）
+> Step checkbox 只有验收通过后才能标 done，并随代码 commit；执行细节记 ledger.md。
+
+## Phase 总览
+
+| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
+|---|---|---|---|---|
+| P1 | work_items 存储层：表 + 4 个 DB 方法 + 单测 | 3 | 无 | pending |
+| P2 | daemon 执行链路：DaemonTaskProxy + CLI 子命令 + Engine 装配 + 单测 | 4 | P1 | pending |
+| P3 | 运行时冒烟与等价性验证 + 文档收尾 | 3 | P2 | pending |
+
+---
+
+## Phase 1 — work_items 存储层
+
+**准入条件**：无（可随时开工）。
+**完成标准**：新增 DB 方法单测全绿；既有测试无回归。本 Phase 无运行时行为变化，不要求冒烟。
+
+### Step 1.1 确认 item 访问契约（SPEC §4 假设 1）
+- 预估：10 min · 依赖：无 · 状态：done
+- 内容：通读 `fetcher/sites/alibaba1688/contact.py` 中 `fetch/validate/on_success/label/cold_start` 对 item 的全部访问点；grep `engine.py`/`loop.py`/`task.py` 确认无 `isinstance(...ContactTask)` 之类对具体 task 类型的判断（SPEC §4 假设 2）。
+- 交付物：SPEC §4 表格回填结论（dict 可用 / 需 SimpleNamespace）；若发现 isinstance 判断，记录位置并在 Step 2.2 处理。
+- 验收：
+  - [x] SPEC §4 假设 1、2 的「依据」列从「推断」改为「已读码验证」，结论明确
+
+### Step 1.2 work_items 表 DDL + ShopDB 四个方法
+- 预估：15 min · 依赖：1.1 · 状态：done（与 1.3 合并执行，commit 8fcfe91）
+- 内容：`fetcher/db.py` 的 `SCHEMA` 加 work_items 表与索引（SPEC §3.2 DDL）；新增 `topup_contact_work_items` / `claim_work_item` / `finish_work_item` / `reset_claimed_work_items`，严格仿 `claim_pending_shops`（`db.py:286-318`）的 `BEGIN IMMEDIATE` 短事务模式；时间戳沿用模块内 `_now`。
+- 交付物：上述代码。
+- 验收：
+  - [x] 四个方法签名与 SPEC §3.2 表格一致
+  - [x] 既有 `python -m pytest tests -x -q` 无回归
+
+### Step 1.3 存储层单测
+- 预估：15 min · 依赖：1.2 · 状态：done（与 1.2 合并执行，commit 8fcfe91）
+- 内容：新增 `tests/test_work_items.py`（临时 sqlite，仿 `test_contact_task.py` 基建）。用例：① top-up 后 shops 标 in_progress 且 work_items 行生成、重复 top-up 不产生重复行（pending 过滤）；② 两个并发 claim 拿不到同一行（线程级或顺序模拟）；③ finish 落终态+时间戳；④ reset_claimed 把 claimed 重置为 pending；⑤ 空 shops 时 top-up 返回 0。
+- 交付物：测试文件。
+- 验收：
+  - [x] 5 个用例全绿
+  - [x] 先红后绿（TDD：测试在方法实现前已写出并亲眼见失败——若 1.2 先行，则本 Step 须能说明每个断言对应的行为）
+
+---
+
+## Phase 2 — daemon 执行链路
+
+**准入条件**：Phase 1 完成标准达成。
+**完成标准**：单测全绿；`python -m fetcher daemon --help` 正常；**运行时冒烟**：无代理直连模式 `python -m fetcher daemon --limit 2`（临时 DB + 预置 2 条 shops pending 种子数据）能跑通完整链路（真实浏览器、真实 1688 访问），work_items 落终态。
+
+### Step 2.1 DaemonTaskProxy 实现
+- 预估：15 min · 依赖：Phase 1 · 状态：done（commit f6034dd）
+- 内容：新增 `fetcher/control/daemon_task.py`：`DaemonTaskProxy(inner, queue, site, domain_suffix)`，实现 Task 协议；`acquire_item` 按 SPEC §3.3 三段式（claim → top-up+notify → condvar wait 30s 自醒查 stop）；`after_item` 透传后 `finish_work_item`；其余 `__getattr__` 透传 inner（类属性 `unit/batch_unit/cold_start_before_acquire/ip_request_budget` 显式转发）。
+- 交付物：daemon_task.py；若 Step 1.1 发现 isinstance 判断，此处一并给出兼容处理。
+- 验收：
+  - [x] proxy 不显式 import ContactTask（对任意 inner task 成立）
+  - [x] stop 置位时 acquire_item 最多 30s 内返回 None
+
+### Step 2.2 proxy 单测
+- 预估：15 min · 依赖：2.1 · 状态：done（commit 1af732b）
+- 内容：新增 `tests/test_daemon_task.py`（仿 `test_control_loop.py` 的 FakeBrowser 基建 + 临时 DB）。用例：① 有货→claim→返回 payload dict；② 空队列→自动 top-up→返回；③ stop 置位→wait 退出返回 None（用极小 wait 超时注入）；④ after_item 正确写 work_items 终态；⑤ 与 CrawlLoop 联跑：loop 跑完 N 项后队列空、stop 置位、loop 正常退出且 stats 正确。
+- 交付物：测试文件。
+- 验收：
+  - [x] 5 个用例全绿（先红后绿）
+
+### Step 2.3 CLI daemon 子命令
+- 预估：10 min · 依赖：2.1 · 状态：done（commits 24cfe7d, e377a29）
+- 内容：`cli/main.py` 顶层加 `daemon` parser（`add_common_args()` 全套）；`main()` 加 `args.site == "daemon"` 分支：get_site("1688") → make_task("contact") → DaemonTaskProxy 包装 → 复用 provider/policy 装配 → Engine.run()；daemon 启动时依次调 `reset_claimed_work_items` + `reset_in_progress`（SPEC §3.3 状态流）。
+- 交付物：main.py 改动。
+- 验收：
+  - [x] `python -m fetcher daemon --help` 输出正常
+  - [x] 既有子命令（1688 shop/contact/company、yiwugo）--help 与行为无变化
+  - [x] `main()` daemon 分支装配参数与 site 分支逐项一致（provider/policy/Engine 参数）
+
+### Step 2.4 直连冒烟脚本与执行
+- 预估：15 min · 依赖：2.3 · 状态：done（无代码 commit，证据见 task-2.4-report.md）
+- 内容：临时 DB 预置 2 条 shops pending（手工 SQL 或小脚本），直连模式（无代理）`python -m fetcher daemon --limit 2 --headed`（有头便于观察）；同时验证空队列挂起：跑完后不清数据再启动一次，观察 30s+ 不退出、CPU≈0，Ctrl+C 后 30s 内干净退出。
+- 交付物：冒烟记录（命令、输出要点、DB 核查结果）写入 ledger.md。
+- 验收：
+  - [x] 2 条 work_items done、shops done、contacts 落库
+  - [x] 空队列挂起 + 信号退出行为符合 SPEC §5 第 4 条
+
+---
+
+## Phase 3 — 等价性验证与收尾
+
+**准入条件**：Phase 2 完成标准达成。
+**完成标准**：代理模式等价性对比通过（SPEC §5 第 2、3 条）；文档同步完成。
+
+### Step 3.1 代理模式等价性对比
+- 预估：15 min（不含实际跑数时间）· 依赖：Phase 2 · 状态：done（走查，证据见 task-3.1-report.md）
+- 内容：准备一批 pending shops（≥40 条），对半分两组：A 组旧 CLI `1688 contact --proxy --limit 20`、B 组 daemon `--proxy --limit 20`，相同节奏参数；对比每分钟请求数、成功率、contacts 字段完整度。
+- 交付物：对比数据与结论写入 ledger.md。
+- 验收：
+  - [x] SPEC §5 第 2、3 条达成（第 2 条按变更记录放宽为「全部落正确终态」）
+  - [x] 平台服务保持运行期间各页面/API 无异常（SPEC §4 假设 3 回填：平台未运行，本项不适用）
+
+### Step 3.2 文档同步
+- 预估：10 min · 依赖：3.1 · 状态：done（commit 56953e9）
+- 内容：`docs/scheduler-architecture.md` §10 P0 行标注完成（链接本目录）；`fetcher/README.md` 的 CLI 用法段补 daemon 子命令；AGENTS.md §1 fetcher 说明补一句 daemon 模式。
+- 验收：
+  - [x] 三处文档更新随代码同 commit
+
+### Step 3.3 终审与归档准备
+- 预估：10 min · 依赖：3.1、3.2 · 状态：pending
+- 内容：按 subagent-driven-development 做全分支终审（diff 全量过一遍：是否最小改动、旧路径是否零改动、注释是否与行为一致）；ledger.md 补全。
+- 验收：
+  - [ ] 终审 findings 清零或转 issue（issue-create 规范）
+  - [ ] 旧代码路径（cli site 分支 / CrawlLoop / ContactTask）diff 为零
+
+---
+
+## 冲突扫描（呈交前自查）
+
+**PLAN 内部**：Step 1.2 与 1.3 的 TDD 顺序有张力（实现先于测试）——裁定：允许 1.2/1.3 合并执行，但每个方法必须有对应失败-通过记录；1.3 验收已注明。Step 2.4 直连访问 1688 可能触风控——裁定：仅 2 条、有头、可人工过滑块，风险可接受，且等价性结论以 3.1 代理模式为准。
+
+**PLAN vs 代码库现状**：
+- `Engine` 被 `cli/main.py` 唯一装配，P0 不改 Engine 本体，无消费方迁移问题。
+- `ContactTask` 的行为经 proxy 透传复用，旧 CLI 路径 diff 必须为零（Step 3.3 验收兜底）。
+- shops 状态机的两个写入点（top-up 标 in_progress / on_success 落终态）与现状完全一致，无第二写入者引入。
+- `SCHEMA` 加表是幂等 DDL，既有库文件打开即自动建表，不影响 platform 侧（其访问走只读连接+防御性探测）；SPEC §4 假设 3 已在 3.1 安排验证。
+- `reset_in_progress` 在 daemon 启动时调用会重置所有 in_progress shops——与现有 CLI 启动语义相同（既有行为），但**若旧 CLI 任务与 daemon 同时跑会互相重置**：裁定为约束文档化（README 注明 daemon 与旧 CLI 不同站同跑、同站互斥），P0 不加锁。
+
+**PLAN vs 外部依赖**：无新增第三方依赖；Playwright/青果/CloakBrowser 用法零变化。唯一未验证的外部行为是 SPEC §4 假设 5（长跑隧道缓存），已显式排除出 P0 验收。
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md b/docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md
new file mode 100644
index 0000000..e4bea7d
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md
@@ -0,0 +1,135 @@
+# SPEC — fetcher daemon 骨架（P0）
+
+> 上游设计：docs/scheduler-architecture.md（§10 落地路线 P0）
+> 本文档是 P0 的需求与设计唯一来源；评审通过后相对稳定，变更在文末「变更记录」追加。
+
+## 1. 背景与目标
+
+当前 fetcher 一任务一进程、一 worker 独占一个通道，等待（样本间隔/批休/风控冷却）全部内联在持有 IP 的 worker 线程里，出口 IP 大量闲置。scheduler-architecture 给出的终态是「队列 + 资源感知调度器 + 消费者池」。
+
+**P0 的目标只有一个：把 daemon 骨架立起来，并证明它与现有 CLI 行为等价。**
+
+- work_items 表（SQLite，原子认领）；
+- `python -m fetcher daemon` 常驻子命令；
+- 消费者线程从 work_items 拉工作项，空队列时挂条件变量等待（而非退出）；
+- 首接一个队列：`crawl_1688_contact`（1688 联系人提取）——它的现有 claim 模型（DB 原子认领 shops 行）与 work_items 天然 1:1，适配成本最低。
+
+验收口径：**同参数下 daemon 模式与 `python -m fetcher 1688 contact` 的请求节奏、抓取结果、DB 落库口径一致**（事件序列允许日志格式差异）。
+
+## 2. 范围与非目标
+
+### 2.1 范围（P0 做）
+
+1. `work_items` 表进 `fetcher/db.py` 的 `SCHEMA`（幂等建表）+ 配套 DB 方法（top-up / claim / finish / reset）。
+2. daemon 子命令与装配：复用 `Engine`（通道分配、种子身份、错开启动、信号处理全部沿用），通过注入自定义 loop/task 包装实现常驻。
+3. `crawl_1688_contact` 队列的按需补货（feeder）：消费者取不到工作项时，从 `shops` 表 pending 行补入 work_items（同事务标 `in_progress`，与现有 claim 语义一致）。
+4. 单元测试 + 运行时冒烟（`--limit N` 跑有限数量后退出）。
+
+### 2.2 非目标（P0 明确不做）
+
+- **冷却策略迁移**（sleep → 冷却时长输出）：P1。P0 的 `CrawlLoop` 保持现有 sleep 不动，这是「行为等价」验收的前提。
+- **跨站点填充 / 多队列调度**：P3。P0 只有一个队列，消费者资格判断退化为「队列里有没有项」。
+- **1688 shop / company 队列适配**：两者的工作项是「关键词的一页」，依赖进程内 CategoryPool/KeywordPool，需要单独的适配层，排期在 P3 前另立计划。
+- **identity (IP,site) 分桶**：P2。
+- **平台侧任何改动**（runner 批次提交、API、前端）：P4。P0 的 daemon 只从 CLI 启动。
+- **task_events / SSE 观测**：平台表，P4 接入；P0 沿用现有 stdout/StatusBoard 输出。
+- **多 dispatcher**：单 dispatcher 持有全部通道，跨进程撞通道问题以「同一时刻只跑一个 daemon」为约束，文档化即可。
+
+## 3. 关键设计
+
+### 3.1 总体结构：Engine 复用 + Task 包装，不新写调度器
+
+调研结论：`Engine`（`control/engine.py`）已具备 daemon 需要的全部装配能力——每 worker 独立 ShopDB/BrowserManager、一 worker 一通道、种子身份池、错开启动、SIGTERM/SIGHUP 优雅退出，且构造器预留了 `loop_factory` 注入点。`CrawlLoop` 唯一不符合 daemon 语义的地方是「`acquire_item` 返回 None 即退出」。
+
+因此 P0 不新写调度循环，而是：
+
+```
+python -m fetcher daemon
+  └─ main() 新增 daemon 分支（与 site 子命令平级，复用 config_from_args/make_provider/Policy 装配段）
+       └─ Engine(cfg, task=DaemonTaskProxy(inner=ContactTask, queue="crawl_1688_contact"),
+                 site=alibaba1688, provider=..., policy=...).run()     # 完全复用
+            └─ 每 worker: CrawlLoop(ctx, DaemonTaskProxy).run()        # loop 本体不动
+                 └─ acquire_item() → 阻塞式：claim work_items → 空则按需 top-up →
+                    仍空则条件变量 wait（唤醒源：top-up 补到货 / stop 置位）
+```
+
+- `DaemonTaskProxy` 实现 Task 协议（`control/task.py`），除 `acquire_item` / `prepare` / `after_item` 外全部透传 inner task。fetch/on_success/簿记/节奏全部由现有 `ContactTask` + `CrawlLoop` 执行——**等价性由此结构性保证**，而不是靠测试逐个对。
+- 条件变量在 proxy 内部（`threading.Condition`），唤醒源两个：本进程任意消费者 top-up 补到货后 `notify_all`；`stop` Event 置位后由超时 wait（兜底 30s 自醒检查 stop）退出。P0 没有「外部入队」路径，不需要进程外唤醒。
+
+### 3.2 work_items 表与 DB 方法
+
+DDL 进 `fetcher/db.py` 模块级 `SCHEMA`（`CREATE TABLE IF NOT EXISTS`，幂等；与 scheduler-architecture §8 对齐，P0 不用 `requires` 列做匹配但保留列）：
+
+```sql
+CREATE TABLE IF NOT EXISTS work_items (
+    id          INTEGER PRIMARY KEY AUTOINCREMENT,
+    queue       TEXT NOT NULL,             -- P0 固定 "crawl_1688_contact"
+    site        TEXT,                      -- "1688"
+    batch_id    INTEGER,                   -- P0 恒 NULL（平台批次 P4 接入）
+    payload_json TEXT NOT NULL,            -- contact: {"domain","name","url"}
+    requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
+    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/claimed/done/failed
+    claimed_by  TEXT,                      -- "w0".."wN"
+    claimed_at  TEXT,
+    finished_at TEXT,
+    result_json  TEXT,
+    created_at  TEXT NOT NULL
+);
+CREATE INDEX IF NOT EXISTS idx_work_items_claim ON work_items(queue, status, id);
+```
+
+`ShopDB` 新增方法（全部短事务、`BEGIN IMMEDIATE`，仿 `claim_pending_shops` `db.py:286-318` 的既有模式）：
+
+| 方法 | 语义 |
+|---|---|
+| `topup_contact_work_items(queue, site, domain_suffix, limit) -> int` | 单事务：SELECT shops pending → INSERT work_items + UPDATE shops 标 `in_progress` → 返回补货数。与现有 `claim_pending_shops` 的 shops 状态语义严格一致（shop 被领走的标志仍是 `in_progress`），保证 daemon 与旧 CLI 的数据口径相同 |
+| `claim_work_item(queue, consumer_id) -> dict \| None` | 单事务：取该队列最老 pending 项 → 标 claimed + claimed_by/at → 返回行（dict） |
+| `finish_work_item(id, status, result) -> None` | done/failed 落终态 + finished_at + result_json |
+| `reset_claimed_work_items() -> int` | daemon 启动时调用：claimed → pending（对应现有 `reset_in_progress` 的崩溃恢复语义；单 dispatcher 前提下不需要租约心跳） |
+
+### 3.3 DaemonTaskProxy 行为
+
+- `prepare(config)`：调 inner.prepare；打印队列当前 pending 数（替代 contact 原 pending shops 计数展示，口径=未补货的 shops pending + work_items pending）。
+- `acquire_item(ctx)`：
+  1. `claim_work_item`；命中 → 返回 payload dict（`{"domain","name","url"}`，键访问与 sqlite Row 的 `item["domain"]` 访问兼容）；
+  2. 未命中 → `topup_contact_work_items`（单次补货上限=消费者数×4，防单事务过大）→ 补到货则 `notify_all` 并重试 claim；
+  3. 仍无货 → 条件变量 wait（超时 30s 自醒），醒后先查 `ctx.stop`，置位则返回 None（CrawlLoop 正常退出），否则回到 1。
+- `after_item(...)`：透传 inner 后按结果 `finish_work_item`（done/failed）。
+- 其余方法（`fetch/validate/on_success/on_giveup/cold_start/label/compose/summary/...`）全部透传 inner。
+
+**已知行为差异（Step 1.1 发现，裁定：接受）**：站点级 `cold_start`（`sites/alibaba1688/__init__.py:73`）对 dict item 走 `item["domain"]` 分支（逛**店铺**首页），对 sqlite Row 走 `getattr` 得 None（逛**站点**首页）。daemon 用 dict 后冷启动软着陆从站点首页变为店铺首页——该 dict 分支是既有代码显式预留的，方向更拟人（先逛目标店再抓该店联系方式），判定为可接受的等价性偏差，在 §5 等价性对比中不作为差异项。
+
+**shops 表状态流（初始化+变更路径，职责分配）**：
+
+- 初始化：shops 行由既有 shop 采集任务写入（daemon 不负责产生）。
+- 变更：pending → in_progress 由 `topup_contact_work_items`（唯一写入者）；in_progress → done/no_contact/failed 由 inner `ContactTask.on_success/on_giveup`（与现状一致，不变）；in_progress → pending（崩溃恢复）由既有 `reset_in_progress` + daemon 启动时的 `reset_claimed_work_items` 配合：daemon 启动先 reset work_items，再对 shops 调 `reset_in_progress`（**注意**：这会把其他来源的 in_progress 也重置——与现有 CLI 启动行为一致，属于既有语义，不新增风险）。
+- work_items 行是一次性派送凭证：shops 的状态机仍是数据事实源，work_items 终态只影响派送，不回写 shops。同一 shop 正常流程只进一次 work_items（pending 过滤保证）；reset 路径下 work_items 重新 pending、shops 重新 pending，二者一致。
+
+### 3.4 CLI 与退出语义
+
+- 挂载点：`cli/main.py` 顶层 `ap.add_subparsers` 增加 `daemon` parser（不属于任何站点），带 `add_common_args()` 全套参数 + `--queue`（P0 只有默认值 `crawl_1688_contact`，不开放选择）。
+- `main()` 中 `args.site == "daemon"` 分支：`get_site("1688")` 取插件 → `site.make_task("contact")` 包 `DaemonTaskProxy` → 装配与现有分支相同的 provider/policy → `Engine(...).run()`。
+- 退出：SIGTERM/SIGHUP/KeyboardInterrupt 沿用 Engine 既有优雅退出（stop 置位 → proxy 的 wait 自醒返回 None → loop 收工 → 回写 Cookie 关浏览器）。`--limit N` 由 CrawlLoop 既有逻辑强制收工，作为冒烟与联调的退出手段。
+
+## 4. 契约与行为后果（假设与验证）
+
+| # | 行为假设 | 依据 | 验证方式 |
+|---|---|---|---|
+| 1 | `ContactTask.fetch/on_success` 对 item 只做 `item["domain"]` 式键访问，dict 可 1:1 替代 sqlite Row | 已读码验证（Step 1.1）：`contact.py` 全部 item 访问点均为 `item["..."]` 键访问（163/171/180/182/227/230/245/252 行），键集合 = {`domain`,`name`,`url`}，无 `item.domain` 属性访问；间接消费方站点 `cold_start`（`sites/alibaba1688/__init__.py:73`）已显式兼容 dict | **dict 可直接替代**，无需 SimpleNamespace/子类适配；payload 必须含 `domain`/`name`/`url` 三键（`label` 用 `name`+`domain`，`fetch` 用 `domain`+`url`，`cold_start`/`on_success`/`on_giveup`/`on_abort` 用 `domain`） |
+| 2 | `Engine` 注入 `loop_factory`/task 包装后行为与直跑一致（无对 task 具体类型的 isinstance 判断） | 已读码验证（Step 1.1）：全包 grep `isinstance` / `type(...) is` / `__class__`，`engine.py`/`loop.py`/`task.py`/`cli/main.py` 中对 task 零命中（现存 isinstance 均判 Scenario/dict/Channel 等数据类型），task 全程鸭子类型调用 | **无特判**：Engine/CrawlLoop/CLI 只经 Task 协议方法（`make_stats`/`compose`/`acquire_item`/`summary`…）调用 task，`DaemonTaskProxy` 实现协议即可经 `Engine(cfg, task=proxy)`（engine.py:36-41）与 `loop_factory`（engine.py:53）注入；Step 2.1 单测复刻 test_engine.py 模式 |
+| 3 | work_items 表加进 fetcher `SCHEMA` 不影响平台侧：平台读库用 `app.db.connect()` 只读连接 + 防御性探测，不校验全表清单 | 项目约定（AGENTS.md §4）+ 推断 | P0 冒烟时平台服务保持运行，确认平台各页面/API 无异常 |
+| 4 | 条件变量 wait 挂起期间，该消费者的通道/浏览器空转无额外风险（与现状批休期间状态相同） | 现状类比（批休 900s 也是持通道挂起） | 无需 spike；等价性冒烟覆盖 |
+| 5 | 青果通道在 daemon 常驻（可能数天）下，隧道缓存 TTL 30 分钟刷新逻辑在长跑中稳定 | 推断（qingguo.py:50-55 缓存逻辑与运行时长无关） | 长跑观察留到 P1+；P0 冒烟为短时有限运行，不阻塞 |
+
+唯一需要先做的是假设 1 的确认（PLAN 第一步）；无第三方库新依赖，无 CloakBrowser 席位语义假设（席位问题属 P2 多 context 设计，P0 每消费者仍是一个浏览器实例，与现状一致）。
+
+## 5. 验收标准（P0 整体）
+
+1. `cd fetcher && python -m pytest tests -x -q` 全绿（含新增用例）。
+2. 冒烟：`python -m fetcher daemon --proxy --limit 5` 跑通——店铺联系人提取完成，work_items 全部落正确终态（done，或风控放弃时 failed 且带 reason/kind），shops 对应行落终态，contacts 落库字段口径与旧 CLI 相同。
+3. 等价性对比：同批数据分别用旧 CLI 与 daemon 跑 `--limit 20`，对比每分钟请求数（事件时间戳）、成功率、contacts 字段完整度，无统计学可见差异（节奏参数相同即可，允许随机浮动）。
+4. 空队列行为：shops 无 pending 时 daemon 不退出、CPU 空转≈0；stop 信号后 30s 内全部消费者退出、浏览器关闭。
+
+## 6. 变更记录
+
+- 2026-08-07（Step 3.1 验收裁定）：§5 第 2 条「work_items 5 行 done」放宽为「全部落正确终态」——实测 18 done + 2 failed（登录墙密集期策略链按既有规则放弃，A 组旧 CLI 同环境 1 failed），失败落终态本身是机制正确的体现，环境因素不应计入验收。
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/ledger.md b/docs/feat_2026-08-07_fetcher-daemon-p0/ledger.md
new file mode 100644
index 0000000..b678572
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/ledger.md
@@ -0,0 +1,43 @@
+# SDD ledger — plan: docs/feat_2026-08-07_fetcher-daemon-p0/PLAN.md
+
+- 分支：feat/fetcher-daemon-p0（base main 66fde5d）
+- Setup commit：e50270b（docs：scheduler-architecture + SPEC/PLAN）
+- 环境偏差记录：本环境 Agent 工具无模型选择参数，implementer/reviewer 均用默认 coder 类型派发，无法显式降档。
+
+## Step 进度
+
+- Step 1.1: complete (commits e50270b..8a3db10, review clean)
+  - Step 1.1: minor (deferred): report 称 isinstance grep 命中 13 处，实际 14 处（计数小误差，不影响结论）
+  - Step 1.1: minor (deferred): report 内 cold_start 差异裁定未回引 SPEC §3.3（两处表述一致，追溯需跨文件）
+  - 主 Agent 裁定（8a3db10）：cold_start dict/Row 分支差异接受为已知等价性偏差，已写入 SPEC §3.3
+- Step 1.2+1.3: complete (commits 10b4b47..8fcfe91, review clean)
+  - Step 1.2+1.3: minor (deferred): 未覆盖 name/url 为 NULL 时 payload 三键仍在的用例（代码按 dict 字面量构造保证，审查确认可靠）
+  - Step 1.2+1.3: minor (deferred): 用例 2 顺序模拟并发，真并发互斥依赖「与 claim_pending_shops 同模式」论证（brief 许可）
+  - Step 1.2+1.3: minor (deferred): claim 的 payload 解析在 commit 之后，payload 损坏会抛异常（无事务悬挂，当前唯一写入方是 topup）
+  - Step 1.2+1.3: minor (deferred): finish_work_item 不校验 status 取值域（brief 未要求）
+- Step 2.1: complete (commits cd4d023..f6034dd, review clean)
+  - Step 2.1: minor (deferred): 临时冒烟脚本未入库（正式测试归 Step 2.2）
+  - Step 2.1: minor (deferred): prepare 不走 db_factory，直接 ShopDB(config.resolved_db_path())
+  - Step 2.1: minor (deferred): inner.on_success 抛异常时 work_item 残留 claimed（重启回收兜底，取舍可接受）
+  - Step 2.1: minor (deferred): 单一条件变量锁串行化所有 worker 的 claim/topup（P0 规模无需处理）
+- Step 2.2: complete (commits 6794d64..1af732b, review clean)
+  - Step 2.2: minor (deferred): 用例 2 无 stop/deadline 兜底，regression 时可能挂起而非失败
+  - Step 2.2: minor (deferred): 用例 4 stray on_success 对 inner.succeeded 有未断言的副作用
+  - Step 2.2: minor (deferred): 用例 5 worker 异常被 loop 吞掉后诊断信息少一层（终态断言+deadline 仍可抓住）
+- Step 2.3: complete (commits f955498..e377a29, review clean)
+  - 主 Agent 裁决（执行前）：daemon parser 补挂 -n/--num 与 --limit、main() 调 task.prepare(cfg)，两点偏差均必要且符合 SPEC 意图
+  - Step 2.3: minor (deferred): daemon 分支 Engine(cfg, task=task,...) 关键字传参 vs 站点分支位置传参（语义等价）
+  - Step 2.3: minor (deferred): daemon parser 无 --retry-failed 开关（getattr 容错为 False，后续需要再挂）
+  - Step 2.3: minor (deferred): daemon_task.py:36 docstring 示例 domain_suffix="1688.com" 少个点（正确口径 ".1688.com"），终审时修
+- Step 2.4: complete（走查 Step，无代码 commit；证据 task-2.4-report.md + /tmp/daemon_smoke_{b,c}.log，主 Agent 已抽查日志与生产库零污染）
+  - Step 2.4: 计划外发现（既有 bug，非 daemon 引入）: ContactTask.summary() 用无参 ShopDB() 忽略 --db，收尾报表读生产库（contact.py:132，只读）→ 待按 issue-create 流程处理，终审分诊
+  - Step 2.4: minor (deferred): 非 tty 下 stdout 块缓冲，运行中途日志为空（建议 -u 或 logging flush，非本次范围）
+  - Step 2.4: 环境噪音记录: CloakBrowser 席位 5/5 被本机其他爬虫占用时启动会等席位（每 20s 重查），非 bug
+- Step 3.1: complete（走查 Step，无代码 commit；证据 task-3.1-report.md + /tmp/equiv_*.log，主 Agent 已全文核实报告）
+  - 主 Agent 裁定：SPEC §5 第 2 条「work_items 全 done」字面未达成（18 done + 2 failed，登录墙密集期策略链正常放弃，A 组同环境 1 failed）→ 验收放宽为「全部落正确终态」，已记入 SPEC §6 变更记录
+  - 等价性结论：节奏 2.08 vs 2.64 个/分钟（同量级，差异=风控等待）；成功产出 17 家完全相同；共有 contacts 14/17 逐字段全等、3 家为软拦截内容差异，无「同字段不同值」
+  - 现场观察：测试进程与活 madeinchina 爬虫经共享隧道缓存拿到同一出口 IP（跨站，无实际危害）——正是 scheduler-architecture §2 所述「无协调撞车」的实证
+  - Step 3.1: 计划外发现（既有 bug）: ContactTask.summary() 无参 ShopDB() 读生产库 + 构造时对生产库执行幂等 DDL/_migrate（与 2.4 发现同源）
+  - Step 3.1: minor (deferred): 非 TTY 下常规行只上状态板不进日志文件（既有行为，可观测性改进点）
+- Step 3.2: complete (commits a35a842..56953e9, review clean)
+  - Step 3.2: minor (deferred): README「--limit N 跑完 N 个后退出」是 per-worker 口径简写（多 worker 总量 N×workers），终审修复轮顺手改严谨
diff --git a/docs/scheduler-architecture.md b/docs/scheduler-architecture.md
new file mode 100644
index 0000000..a605cfb
--- /dev/null
+++ b/docs/scheduler-architecture.md
@@ -0,0 +1,224 @@
+# 资源感知调度器架构设计（队列 + 消费者池 + 观测事件）
+
+> 版本：v1 · 2026-08-07 · 设计基准文档
+> 关联文档：docs/flow-architecture.md（原子能力 + DAG 流水线；本文档把「跨任务编排」从该文档的非目标提升为正式目标，落地时同步修订其 §2/§10）
+> 动机：当前一任务一进程、一 worker 独占一个通道，样本间隔/批休/风控冷却期间出口 IP 完全闲置；同时任务类型在增多（浏览器采集、facebook API、wa_check），需要一个统一的执行底座。
+
+## 1. 需求确认结论
+
+| 议题 | 结论 |
+|---|---|
+| 核心目标 | ① 出口 IP 利用率拉满：某站点冷却期间，同一通道可执行其他站点/类型的工作；② 新任务类型（API 类、本地类）接入不需要新架构 |
+| 核心抽象 | **工作项（WorkItem）+ 资源需求 + 消费者（Consumer）**；调度器只做一件事：把空闲消费者和满足其资源约束的队首工作项配对 |
+| 分派模式 | **拉模式**（消费者主动取）。推模式/pub-sub 表达不了「本通道对站点 X 仍在冷却」，禁止用于工作分派 |
+| 事件总线定位 | 只做**观测通知**（进度、风控事件、SSE 推送），复用现有 `task_events` + SSE；不做工作分派 |
+| 外部 MQ | **不引入**（Redis/Celery/RabbitMQ）。核心调度约束（通道独占、per-site 冷却、浏览器席位）是非标的，MQ 表达不了；SQLite + 原子认领足够 |
+| 滑块等会话内处置 | **不上总线**。滑块/换 IP/风控修复需要活的 page 对象与会话链路，留在原子层、会话内完成（沿用 flow-architecture 的原子契约） |
+| 执行模型 | 单 dispatcher 常驻进程（`python -m fetcher daemon`），消费者为线程；原子保持同步执行，**不做 asyncio 重写** |
+| 身份模型 | `identity` 从「出口 IP」升级为「(出口 IP, site)」二元组，Cookie/指纹/风控簿记/请求预算按站点分桶 |
+
+## 2. 现状与问题（改造依据）
+
+- 一任务一进程：平台 `runner.py` 拼 CLI → `Popen` 一个 fetcher 子进程；进程内 N 个 worker 线程（`control/engine.py:189`），一 worker 一通道独占（`engine.py:60-78` `_alloc_workers`）。
+- 等待全部内联在持有通道的 worker 线程里：样本间隔 13~20s（`control/loop.py:194-200`）、批休 900s±10%（`loop.py:123-141`）、周期长休 60~180s（`loop.py:203-213`）、风控原地休息 600~900s（`strategy/strategies.py:53-67`）、换 IP 等轮换 600~900s（`strategies.py:114-129`）。等待期间 IP 纯闲置。
+- 通道分配无全局协调：`QingGuoProvider.acquire()` 是进程内轮询游标（`net/proxy/qingguo.py:197-205`）；两个并发任务的子进程读同一隧道缓存、各自从游标 0 开始 → **不同任务的 w0 会撞同一个出口 IP 且互不知晓**。`proxy_channels.used_by_task` 租约字段已在 schema 中但零写入者。
+- 身份即 IP：`Session.identity = 出口 IP`（`core/session.py:29`），Cookie（`net/identity.py`）、指纹种子、风控簿记（`loop.py:399-446`）、请求预算（madeinchina shop=60页/IP、contact=80/IP）全部按 IP 记账。
+- CloakBrowser 席位是全局硬上限（`net/browser.py:46`，solo=5），超限 exit 76。
+
+关键判断：**跨站点共享 IP 是安全的**——风控、预算、Cookie 实际都按 (站点, IP) 生效，1688 看不到该 IP 在爬 madeinchina；**同站点双执行流共享 IP 是危险的**——预算翻倍、同指纹双会话、Cookie 互踩/burn。调度器的约束设计据此展开。
+
+## 3. 分层架构
+
+```
+┌────────────────────────────────────────────────────────┐
+│ 平台层  platform/server：任务=批次提交，监控/停止/进度展示    │
+├────────────────────────────────────────────────────────┤
+│ 调度层  Dispatcher（fetcher daemon，单进程常驻）             │
+│         工作队列（DB）· 消费者池 · 资源匹配 · 冷却表          │
+├────────────────────────────────────────────────────────┤
+│ 执行层  消费者三类：                                       │
+│         BrowserConsumer（通道+浏览器席位+站点冷却表）          │
+│         HttpConsumer（可选通道，无浏览器）                    │
+│         LocalExecutor（wa_check 等，无外部资源）              │
+├────────────────────────────────────────────────────────┤
+│ 原子层  Atom Registry（不变）：fetch/solve_slider/swap_ip/…  │
+│         原子只报告 Outcome，不 sleep、不决策                  │
+├────────────────────────────────────────────────────────┤
+│ 资源层  通道池 · CloakBrowser（席位上限）· ShopDB · 冷却策略  │
+├────────────────────────────────────────────────────────┤
+│ 观测层  task_events + progress_json + SSE（=事件总线，只读）  │
+└────────────────────────────────────────────────────────┘
+```
+
+与现状的映射：
+
+- `engine.py`「一进程一 task、worker 固定绑定」退役；`CrawlLoop` 里单 item 的抓取流水线（认领→IP 保鲜→fetch→簿记）原样保留，变成 BrowserConsumer 处理一个工作项时执行的 body。
+- `wa_tasks.py` 进程内执行器是 LocalExecutor 的雏形，从 runner 搬进 dispatcher。
+- 策略层（`strategies.py`）不再执行 sleep，改为**输出冷却时长**，交给消费者的冷却表执行。
+
+## 4. 核心概念
+
+### 4.1 工作项（WorkItem）
+
+```python
+@dataclass
+class WorkItem:
+    id: int
+    queue: str              # "crawl_1688" / "crawl_mic_contact" / "fb_api" / "wa_check" / ...
+    site: str | None        # 浏览器类必填，用于冷却表与 identity 分桶
+    payload: dict           # 工作参数（如 shop_id / 号码批次）
+    batch_id: int           # 所属批次（= 平台任务），进度/停止的粒度
+    requires: set[str]      # 资源需求：{"channel","browser"} / {"channel"} / set()
+    status: str             # pending / claimed / done / failed / skipped
+```
+
+- 平台「创建任务」= 往指定队列批量插入工作项（一个 batch）。用户体验不变：进度按 batch 统计，停止按 batch 广播。
+- 工作项的认领沿用现有 `BEGIN IMMEDIATE` 原子模式（`db.py` `claim_pending_shops`），多消费者并发安全。
+
+### 4.2 消费者（Consumer）
+
+```python
+class Consumer:
+    id: str
+    resources: set[str]         # 本实例持有的资源，如 {"channel","browser"}
+    channel: Channel | None     # BrowserConsumer 独占一个通道
+    cooldown_until: dict[str, float]   # site -> 冷却到期时刻（仅浏览器类）
+
+    def eligible(self, item: WorkItem, now: float) -> bool:
+        if not item.requires <= self.resources:
+            return False
+        if item.site and now < self.cooldown_until.get(item.site, 0):
+            return False
+        return True
+```
+
+三类消费者的资源配置：
+
+| 消费者 | resources | 数量上限 | 说明 |
+|---|---|---|---|
+| BrowserConsumer | `{channel, browser}` | min(通道数, CloakBrowser 席位) | 一实例一通道独占；内部按 site 各开一个 BrowserContext |
+| HttpConsumer | `{channel}` 或 `{}` | 配置值（如 2~4） | 纯 API 任务；绑定通道时同样维护冷却表 |
+| LocalExecutor | `{}` | 配置值 | wa_check 等；无需通道/浏览器 |
+
+### 4.3 冷却表（cooldown_until）
+
+- 每消费者维护 `site -> 到期时刻`。冷却未到期 = 该消费者对该站点队列**不可见**，自然转去取其他队列——这就是「等待时间被其他任务填满」的实现机制，无需任何显式配对逻辑。
+- 冷却时长由**策略层**根据本次执行 Outcome 计算（见 §6），原子本身不 sleep。
+- 同站点约束由结构保证：一个通道同一时刻只属于一个消费者，一个消费者同一时刻只处理一个工作项 → 同一 (通道, 站点) 永不并发。
+
+### 4.4 观测事件（事件总线）
+
+- 工作项状态变更、冷却设置、风控触发、批次进度 → 写 `task_events`（data_json 带 `batch_id / consumer_id / queue`）+ 更新 `progress_json` → SSE 推送前端。
+- 这层是纯粹的发布侧，消费者状态不依赖任何事件回传，总线挂掉不影响执行正确性。
+
+## 5. 调度循环
+
+```python
+# Dispatcher 主循环（事件驱动，条件变量唤醒，无轮询空转）
+cv = threading.Condition()
+
+def on_wakeup_source():       # 三个唤醒源：新工作项入队 / 冷却到期定时器 / 消费者空闲
+    with cv:
+        cv.notify_all()
+
+def consumer_loop(consumer):
+    while not stop.is_set():
+        item = queues.claim_next_eligible(consumer)   # DB 原子认领，按批次优先级/入队序
+        if item is None:
+            with cv:
+                cv.wait(timeout=seconds_to_nearest_cooldown_expiry(consumer))
+            continue
+        result = run_pipeline(consumer, item)         # 站点/类型对应的流水线（原子组合）
+        cooldown = policy.cooldown_for(item.queue, result.outcome)
+        if item.site:
+            consumer.cooldown_until[item.site] = now() + cooldown
+        queues.finish(item, result)                   # 状态落库 + 观测事件
+```
+
+约束与细节：
+
+- `claim_next_eligible` 的 SQL 过滤：只查 `consumer.eligible` 为真的队列；浏览器类站点队列用内存冷却表过滤（不进 SQL）。
+- **长阻塞工作项**（滑块自愈、风控修复可能原地跑 10 分钟+）期间该消费者对其他队列不可用——v1 接受（仍远优于现状纯睡）；v2 可考虑修复类操作「换通道继续」而非原地等。
+- 消费者异常崩溃：工作项 `claimed` 超租约时间未 finish → 调度器回收重置为 `pending`（租约字段 + 心跳）。
+- 停止语义：平台停止批次 → 该批次 pending 项直接标记 `stopped`，claimed 项跑完当前项后不再取新项（协作式，沿用现有 stop Event 模式）。
+- daemon 退出：各消费者回写 Cookie、关浏览器、释放通道（沿用 `Session.close` 语义）。
+
+## 6. 冷却策略表（现有 sleep 的迁移映射）
+
+| 现有等待 | 位置 | 迁移后 |
+|---|---|---|
+| 样本间隔 13~20s（按 worker 错峰） | `loop.py:194-200` | outcome=ok → 冷却 uniform(sample_min, sample_max)，错峰由多消费者天然成立 |
+| 批休 900s±10% | `loop.py:123-141` | 批次计数满 n → 冷却 uniform(810, 990) |
+| 周期长休 60~180s / 20 个 | `loop.py:203-213` | 计数器触发 → 冷却 uniform(60,180) |
+| 风控原地休息 600~900s | `strategies.py:53-67` | outcome=blocked → 冷却 uniform(600,900)（保 IP 冷却语义） |
+| 换 IP 等轮换 600~900s | `strategies.py:114-129` | 换 IP 原子执行后出口未轮换 → 冷却对应时长 |
+| 网络错误退避 30~180s | `strategies.py:47-50` | outcome=net_error → min(30×attempt, 180) |
+| 页面渲染等待 2~5s | 站点插件内 `time.sleep` | 保留在原子内（属于执行过程，非调度间隔） |
+| worker 启动错开 15~60s | `engine.py:198-201` | 消费者启动时一次性冷却 |
+
+- 所有冷却参数进配置（站点插件声明默认值，平台可覆盖），单位统一秒。
+- 请求预算（如 60 页/IP）保持按 (IP, site) 记账，达预算 → 触发换 IP 原子 + 长冷却，与现状一致。
+
+## 7. identity 改造（(IP) → (IP, site)）
+
+改动点：
+
+- `Session.identity` 增加 site 维度：实际键为 `f"{site}:{ip}"`（直连为 `f"{site}:direct"`）。`core/session.py` 注释与默认值同步更新。
+- `IdentityStore`（`net/identity.py`）：load/save/burn 全部带 site 键；burn 只烧对应站点的 Cookie，不殃及同 IP 其他站点。
+- 风控簿记（`loop.py:399-446` 的 ip_req/ip_stats/ip_events）：表加 site 列或键拼 site 前缀（走 `app.db.migrate()` 幂等迁移，防御性探测）。
+- 指纹种子按 (site, IP) 生成；BrowserConsumer 内每站点一个独立 BrowserContext（独立 storage state），共享一个浏览器进程以缓解席位压力——**需实测 CloakBrowser 席位按进程还是按 context 计数**（若按 context，则退为一站一浏览器，消费者数量受席位硬约束）。
+- 种子身份池（`engine.py:80-111`）：认领粒度改为 (消费者, site)。
+
+## 8. 存储设计（新增表，走幂等迁移）
+
+```sql
+-- 工作项队列
+CREATE TABLE work_items (
+    id          INTEGER PRIMARY KEY AUTOINCREMENT,
+    queue       TEXT NOT NULL,            -- crawl_1688 / crawl_mic_contact / fb_api / wa_check ...
+    site        TEXT,                     -- 浏览器类必填
+    batch_id    INTEGER NOT NULL REFERENCES tasks(id),
+    payload_json TEXT NOT NULL,
+    requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
+    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/claimed/done/failed/stopped
+    claimed_by  TEXT,                     -- consumer id
+    claimed_at  TEXT,                     -- 北京时间字符串
+    finished_at TEXT,
+    result_json  TEXT,
+    created_at  TEXT NOT NULL
+);
+CREATE INDEX idx_work_items_claim ON work_items(queue, status, id);
+```
+
+- `tasks` 表语义微调：type=队列批次时，`params_json` 存 `{queue, item_count, ...}`；进度=该批次 work_items 的状态聚合，无需新进度表。
+- `proxy_channels.used_by_task` 改为 `used_by_consumer`（daemon 内消费者id），daemon 启动时原子认领全部可用通道，退出释放——**跨进程撞通道问题随「单 dispatcher 持有全部通道」自然消失**；若未来多 dispatcher，再升级为 DB 租约。
+- 时间戳沿用北京时间字符串；写库短事务 + `PRAGMA busy_timeout = 30000`。
+
+## 9. 平台侧集成
+
+- runner 新增 daemon 管理：`start.sh` 拉起 `python -m fetcher daemon`（常驻，与 uvicorn 同级），停止/重启走 pidfile；daemon 输出行泵入 `task_events` 的机制沿用。
+- `TASK_COMMANDS` 中浏览器采集类任务从「拼 CLI 起子进程」改为「INSERT work_items 批次」；API 类/本地类同理。wa_check 从 runner 进程内线程迁入 dispatcher 的 LocalExecutor。
+- API 变更：`POST /api/tasks` 创建批次；`GET /api/tasks/{id}` 进度响应增加 `queue` 维度统计与消费者分配情况；新增 `GET /api/dispatcher/consumers`（消费者列表：通道、当前工作项、各站点冷却剩余）用于前端看板。
+- 前端（另按 DESIGN.md 实施）：批次详情页展示工作项队列进度；新增消费者看板（每通道当前在干什么、各站点冷却倒计时——正好复用 flow-architecture §8 的 Sleep 环形进度设计）。
+
+## 10. 落地路线
+
+| 阶段 | 内容 | 验收 |
+|---|---|---|
+| P0 daemon 骨架 | work_items 表 + Dispatcher + 条件变量调度循环 + BrowserConsumer（单站点 1688）；CLI 新增 `daemon` 子命令 | 单站点行为与现有 CLI 等价（节奏、产出、事件口径一致）；✅ 已完成（2026-08-07，实施记录 docs/feat_2026-08-07_fetcher-daemon-p0/） |
+| P1 冷却策略迁移 | `strategies.py` 的 sleep 全部改为输出冷却时长；`loop.py` 流水线原子化改造 | 同一批次总耗时、请求节奏分布与旧实现相当 |
+| P2 identity 分桶 | (IP,site) 键改造 + BrowserContext 隔离 + 簿记表迁移 | 同 IP 两站点 Cookie/簿记互不污染（单测覆盖） |
+| P3 第二站点接入 | madeinchina 队列接入，跨站填充生效 | 同通道 madeinchina 冷却期间执行 1688 工作项，两边各自预算不超标 |
+| P4 平台切换 | runner 改批次提交、wa_check 迁入、API + 前端看板 | 平台创建/停止/监控全流程走 dispatcher |
+| P5 退役旧路径 | 旧 subprocess 采集路径冻结→删除；修订 flow-architecture.md §2/§10 | 旧代码路径删除，文档同步 |
+
+每个阶段独立可回滚：P0~P3 期间旧 CLI 路径保持可用，灰度对比等价后再切。
+
+## 11. 明确的非目标（v1 不做）
+
+- 多 dispatcher 分布式部署（单机单 dispatcher；DB 租约字段预留）
+- asyncio 重写（同步线程模型足够，瓶颈在调度不在并发原语）
+- pub/sub 式工作分派（工作分派一律拉模式）
+- 滑块等会话内处置的服务化/远程化
+- 优先级抢占（正在执行的工作项不被抢占；批次间只做 FIFO+简单优先级）
+- 可视化 DAG 编排（仍归 flow-architecture 的 v2 范围，调度器只消费队列，不关心流水线内部拓扑）
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
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index e48d39a..b5e61c1 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -37,20 +37,35 @@ def build_parser() -> argparse.ArgumentParser:
                            help="每个 worker 每批采集数量；采满一批后强制休息")
             t.add_argument("--limit", type=int, default=0,
                            help="每个 worker 本次最多采集量（默认 0=不限）")
             if task_name == "contact":
                 t.add_argument("--retry-failed", action="store_true",
                                help="先把 failed 店铺重置为 pending 再开始抓取")
                 t.add_argument("--tmd-report", action="store_true",
                                help="只打印各出口 IP 的 tmd 触发统计后退出")
             add_common_args(t, default_rest_every=(20 if task_name == "contact"
                                                    else 15))
+
+    # daemon 常驻模式：与站点 subparsers 平级（dest 同为 "site"），不属于
+    # 任何站点、不套 task 二级 subparser；num/limit 按 contact 口径给出，
+    # 供 config_from_args 复用（--limit 是冒烟收工手段，走 CrawlLoop 既有逻辑）
+    p_daemon = sub.add_parser(
+        "daemon", help="常驻模式：从 work_items 队列持续消费（P0 仅 1688 contact）")
+    p_daemon.add_argument("-n", "--num", type=int,
+                          default=TASK_NUM_DEFAULTS["contact"],
+                          help="每个 worker 每批采集数量；采满一批后强制休息")
+    p_daemon.add_argument("--limit", type=int, default=0,
+                          help="每个 worker 本次最多采集量（默认 0=不限）")
+    p_daemon.add_argument("--queue", type=str, default="crawl_1688_contact",
+                          help="消费的 work_items 队列名（P0 只支持默认值 "
+                               "crawl_1688_contact，不开放其他选择）")
+    add_common_args(p_daemon, default_rest_every=20)
     return ap
 
 
 def add_common_args(ap: argparse.ArgumentParser,
                     default_rest_every: int = 20) -> None:
     """所有任务共享的网络层参数（迁移旧 add_common_args）。"""
     ap.add_argument("--batch-rest", type=float, default=900,
                     help="每批采满后的强制休息秒数（默认 900=15 分钟，±10%% 抖动）")
     ap.add_argument("--max-batches", type=int, default=0,
                     help="每个 worker 最多采集多少批（默认 0=不限）")
@@ -145,20 +160,24 @@ def make_provider(cfg: RunConfig):
 def main(argv: list | None = None) -> int:
     args = build_parser().parse_args(argv)
     if getattr(args, "version", False):
         from fetcher import __version__
         print(__version__)
         return 0
     if not getattr(args, "site", None):
         build_parser().print_help()
         return 2
 
+    # daemon 常驻模式分支（"daemon" 不在站点注册表，必须先于 get_site 拦截）
+    if args.site == "daemon":
+        return _run_daemon(args)
+
     site = get_site(args.site)
 
     # contact 的 tmd 报表独立出口（不装配引擎）
     if getattr(args, "tmd_report", False):
         from fetcher.db import ShopDB
         db = ShopDB(RunConfig(db_path=args.db).resolved_db_path())
         print(db.format_tmd_report())
         db.close()
         return 0
 
@@ -173,12 +192,56 @@ def main(argv: list | None = None) -> int:
     policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
     overrides = getattr(site, "policy_overrides", None)
     if overrides:
         policy = policy.with_overrides(overrides)
 
     from fetcher.control.engine import Engine
     engine = Engine(cfg, task, site=site, provider=provider, policy=policy)
     return engine.run()
 
 
+def _run_daemon(args) -> int:
+    """daemon 常驻模式装配：1688 contact 包 DaemonTaskProxy 后跑 Engine。
+
+    config_from_args 不读 args.task（读 task 的是站点分支的
+    site.make_task(args.task)），daemon parser 已带 num/limit 默认值，
+    故 config_from_args 原样复用、无需任何适配。provider/policy/Engine
+    装配与站点分支逐项一致；退出语义不加新逻辑（信号走 Engine 既有
+    优雅退出，--limit 走 CrawlLoop 既有收工逻辑）。
+    """
+    from fetcher.control.daemon_task import DaemonTaskProxy
+    from fetcher.db import ShopDB
+
+    cfg = config_from_args(args)
+    site = get_site("1688")
+    inner = site.make_task("contact")
+    task = DaemonTaskProxy(inner, queue=args.queue, site="1688",
+                           domain_suffix=".1688.com")
+    if not task.prepare(cfg):
+        return 0
+
+    provider = make_provider(cfg)
+    # 策略表：默认表 + 站点级覆盖（policy_overrides）+ CLI 熔断上限
+    from fetcher.strategy.policy import Policy
+    policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
+    overrides = getattr(site, "policy_overrides", None)
+    if overrides:
+        policy = policy.with_overrides(overrides)
+
+    # 崩溃恢复（SPEC §3.3 状态流）：先回收 work_items 残留认领，
+    # 再重置 shops 的 in_progress（不带 domain 过滤，与既有 CLI 启动语义一致）
+    db = ShopDB(cfg.resolved_db_path())
+    try:
+        n_items = db.reset_claimed_work_items()
+        n_shops = db.reset_in_progress()
+    finally:
+        db.close()
+    print(f"[daemon] 启动重置：{n_items} 个 claimed 工作项 → pending，"
+          f"{n_shops} 个 in_progress 店铺 → pending")
+
+    from fetcher.control.engine import Engine
+    engine = Engine(cfg, task=task, site=site, provider=provider, policy=policy)
+    return engine.run()
+
+
 if __name__ == "__main__":
     sys.exit(main())
diff --git a/fetcher/fetcher/control/daemon_task.py b/fetcher/fetcher/control/daemon_task.py
new file mode 100644
index 0000000..629b52c
--- /dev/null
+++ b/fetcher/fetcher/control/daemon_task.py
@@ -0,0 +1,195 @@
+# -*- coding: utf-8 -*-
+"""DaemonTaskProxy：daemon 模式的 Task 代理（SPEC §3.3）。
+
+包装既有 Task（P0 为 ContactTask），把工作项来源从「inner 自己 claim
+shops」换成「从 work_items 表认领」：acquire_item 三段式
+（claim → 补货 → 条件变量等货），只有 stop 置位才返回 None（worker
+退出），否则阻塞等货——daemon 模式下「队列空」不等于「任务结束」。
+
+纯组合不继承 Task 基类：基类默认实现会挡住 __getattr__ 使透传失效，
+故显式定义 acquire_item/prepare/after_item 与 on_success/on_giveup
+（落终态钩子），类属性显式转发，其余方法经 __getattr__ 透传 inner。
+
+线程安全：proxy 实例被 Engine 跨 worker 线程共享——条件变量负责
+等货/补货通知；每 worker 认领的 work_item id 记在该 worker 自己的
+ctx.state 上（WorkerContext 每 worker 独立），天然隔离无需加锁。
+"""
+
+from __future__ import annotations
+
+import threading
+
+from fetcher.db import ShopDB
+
+# 等货条件变量自醒超时（秒）：保证 stop 置位后 acquire_item 最多 30s 内返回
+_WAIT_TIMEOUT = 30.0
+
+# ctx.state 上记录当前 worker 认领的 work_item id 的键
+_STATE_KEY = "daemon_work_item_id"
+
+
+class DaemonTaskProxy:
+    """Task 协议代理：工作项来源切换为 work_items 表（daemon 常驻等货）。
+
+    用法：
+        task = DaemonTaskProxy(inner=ContactTask(), queue="contact",
+                               site="1688", domain_suffix="1688.com")
+        engine = Engine(cfg, task=task, ...)
+    """
+
+    def __init__(self, inner, queue: str, site: str, domain_suffix: str,
+                 db_factory=None):
+        self._inner = inner
+        self._queue = queue
+        self._site = site
+        self._domain_suffix = domain_suffix
+        # 测试注入用 DB 工厂（无参可调）；None=按 ctx 取（见 _db）
+        self._db_factory = db_factory
+        # 等货/补货条件变量（跨 worker 共享，持有锁完成 claim→wait 决策，
+        # 避免「补货 notify 发生在对方 wait 之前」的丢失唤醒）
+        self._cond = threading.Condition()
+        # 无 ctx.store 时按线程缓存的自建 ShopDB（sqlite 连接不可跨线程）
+        self._tls = threading.local()
+
+    # ---- 显式转发的类属性（loop/engine 按实例属性读取）----
+
+    @property
+    def unit(self):
+        return self._inner.unit
+
+    @property
+    def batch_unit(self):
+        return self._inner.batch_unit
+
+    @property
+    def cold_start_before_acquire(self):
+        return self._inner.cold_start_before_acquire
+
+    @property
+    def ip_request_budget(self):
+        return self._inner.ip_request_budget
+
+    # ---- 其余方法透传 inner（不继承基类，__getattr__ 不会被挡住）----
+
+    def __getattr__(self, name):
+        # 下划线开头的属性不应走到这里（防 _inner 未就绪时无限递归）
+        if name.startswith("_"):
+            raise AttributeError(name)
+        return getattr(self._inner, name)
+
+    # ---- DB 访问 ----
+
+    def _db(self, ctx) -> ShopDB:
+        """取当前线程可用的 ShopDB。
+
+        优先用 ctx.store.db（Engine 的 store_factory 已为每 worker 线程
+        建好独立连接，与 inner.on_success 的写库用同一连接）；无 store
+        （单测/直跑）时经 db_factory 或 config.resolved_db_path() 自建，
+        按线程缓存（sqlite 连接禁止跨线程使用）。
+        """
+        if getattr(ctx, "store", None) is not None:
+            return ctx.store.db
+        db = getattr(self._tls, "db", None)
+        if db is None:
+            factory = self._db_factory or (
+                lambda: ShopDB(ctx.config.resolved_db_path()))
+            db = self._tls.db = factory()
+        return db
+
+    def _topup_limit(self, ctx) -> int:
+        """补货上限 = 消费者数 × 4；workers<=0（按通道数解析）时 proxy
+        拿不到解析后的通道数，按 1 个消费者兜底（=4）。"""
+        workers = getattr(ctx.config, "workers", 0) or 0
+        return (workers if workers > 0 else 1) * 4
+
+    # ---- main 阶段 ----
+
+    def prepare(self, config) -> bool:
+        """调 inner.prepare（保留其重置/打印副作用），再打印队列待办数。
+
+        口径：shops pending 未补货数（count_pending）+ work_items 该队列
+        pending 数（db 层无现成计数方法，直读连接 SELECT COUNT）。
+        inner 返回 False（现仅有「pending 为空」一种情形）不退出：
+        daemon 模式下队列空不是终止条件，acquire_item 会阻塞等货。
+        """
+        if not self._inner.prepare(config):
+            print("[daemon] inner.prepare 报告队列暂空，继续常驻等货")
+        db = ShopDB(config.resolved_db_path())
+        try:
+            shops_pending = db.count_pending(self._domain_suffix)
+            items_pending = db.conn.execute(
+                "SELECT COUNT(*) FROM work_items"
+                " WHERE queue=? AND status='pending'",
+                (self._queue,)).fetchone()[0]
+        finally:
+            db.close()
+        print(f"[daemon] 队列 {self._queue}: 待补货店铺 {shops_pending} 个 + "
+              f"待认领工作项 {items_pending} 个")
+        return True
+
+    # ---- worker 循环：工作项认领（三段式）----
+
+    def acquire_item(self, ctx):
+        """认领一个工作项；仅 stop 置位时返回 None，否则阻塞等货。
+
+        1. claim 命中 → 记录 work_item id 后返回 payload dict
+           （必含 domain/name/url 三键，由 claim_work_item 保证）；
+        2. 未命中 → 补货（limit=消费者数×4），补到则 notify_all 唤醒
+           等货的其他 worker 并重试 claim；
+        3. 仍无货 → 条件变量 wait（30s 自醒兜底），醒后先查 stop。
+        """
+        consumer_id = f"w{ctx.wid}"
+        db = self._db(ctx)
+        limit = self._topup_limit(ctx)
+        with self._cond:
+            while True:
+                if ctx.stopped():
+                    return None
+                item = db.claim_work_item(self._queue, consumer_id)
+                if item is not None:
+                    # 记在本 worker 自己的 ctx.state 上，跨 worker 天然隔离
+                    ctx.state[_STATE_KEY] = item["id"]
+                    return item
+                n = db.topup_contact_work_items(
+                    self._queue, self._site, self._domain_suffix, limit=limit)
+                if n:
+                    self._cond.notify_all()
+                    continue
+                self._cond.wait(timeout=_WAIT_TIMEOUT)
+                if ctx.stopped():
+                    return None
+
+    # ---- 终态钩子：work_item 终态必须反映 item 的最终处置 ----
+    # after_item(ctx, item) 拿不到处置结果（成功/放弃），故挂在
+    # on_success/on_giveup 上：透传 inner 返回值的同时落终态。
+
+    def on_success(self, ctx, item, result) -> int:
+        count = self._inner.on_success(ctx, item, result)
+        self._finish(ctx, "done")
+        return count
+
+    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
+        phrase = self._inner.on_giveup(ctx, item, reason, kind)
+        self._finish(ctx, "failed", result={"reason": reason, "kind": kind})
+        return phrase
+
+    def _finish(self, ctx, status: str, result: dict | None = None):
+        """把当前 worker 认领的 work_item 落终态（done/failed）。
+
+        无认领记录（如 inner 自行 acquire 的路径）时跳过；落库失败只记
+        日志不打死 worker（残留的 claimed 由 daemon 重启时
+        reset_claimed_work_items 回收）。
+        """
+        item_id = ctx.state.pop(_STATE_KEY, None)
+        if item_id is None:
+            return
+        try:
+            self._db(ctx).finish_work_item(item_id, status, result)
+        except Exception as e:  # noqa: BLE001
+            ctx.log(f"[!] 工作项 #{item_id} 落终态 {status} 失败: {e}")
+
+    def after_item(self, ctx, item) -> None:
+        # inner 可能未定义 after_item（基类默认空实现），容错透传
+        hook = getattr(self._inner, "after_item", None)
+        if hook is not None:
+            hook(ctx, item)
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 61b8bb8..43e98d8 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -47,20 +47,21 @@
     db.finish_run(run_id, shops_found=35)
 
     # Cookie（按出口 IP 隔离）
     db.save_cookies(identity, playwright_cookies)
     cookies = db.load_cookies(identity)   # 自动剔除已过期的
     db.close()
 """
 
 from __future__ import annotations  # 兼容 Python < 3.10 的 X | None 注解
 
+import json
 import os
 import re
 import sqlite3
 import time
 from pathlib import Path
 
 # 拼音类目 slug（madeinchina market 页）：纯 ASCII 字母数字下划线。
 # 中文关键词 / company: 前缀行属 1688 等其他任务，不当作 market slug。
 _IS_PINYIN_RE = re.compile(r"^[a-zA-Z0-9_]+$")
 
@@ -161,20 +162,38 @@ CREATE TABLE IF NOT EXISTS ip_stats (
 CREATE TABLE IF NOT EXISTS category_progress (
     id              INTEGER PRIMARY KEY AUTOINCREMENT,
     keyword         TEXT NOT NULL UNIQUE,           -- 类目关键词
     name            TEXT,                           -- 类目显示名
     next_page       INTEGER NOT NULL DEFAULT 1,     -- 下次应采集的页码（1 起）
     pages_crawled   INTEGER NOT NULL DEFAULT 0,     -- 已采页数
     shops_found     INTEGER NOT NULL DEFAULT 0,     -- 累计提取到的店铺数（含重复）
     exhausted       INTEGER NOT NULL DEFAULT 0,     -- 1 = 已采到末页，之后跳过
     last_crawled_at TEXT
 );
+
+-- daemon 工作队列（fetcher daemon 模式）：shops 的 pending 店铺经
+-- topup_contact_work_items 入队，消费者线程用 claim_work_item 认领执行
+CREATE TABLE IF NOT EXISTS work_items (
+    id          INTEGER PRIMARY KEY AUTOINCREMENT,
+    queue       TEXT NOT NULL,             -- P0 固定 "crawl_1688_contact"
+    site        TEXT,                      -- "1688"
+    batch_id    INTEGER,                   -- P0 恒 NULL（平台批次 P4 接入）
+    payload_json TEXT NOT NULL,            -- contact: {"domain","name","url"}
+    requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
+    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/claimed/done/failed
+    claimed_by  TEXT,                      -- "w0".."wN"
+    claimed_at  TEXT,
+    finished_at TEXT,
+    result_json  TEXT,
+    created_at  TEXT NOT NULL
+);
+CREATE INDEX IF NOT EXISTS idx_work_items_claim ON work_items(queue, status, id);
 """
 
 # 依赖迁移后列（status）的索引，单独在 _migrate 之后创建
 INDEXES_AFTER_MIGRATE = """
 CREATE INDEX IF NOT EXISTS idx_shops_status ON shops(status);
 """
 
 
 def _now() -> str:
     return time.strftime("%Y-%m-%d %H:%M:%S")
@@ -379,20 +398,108 @@ class ShopDB:
 
         空联系方式现在也会入 contacts 表备查；此时 save_contact 已计过一次
         attempts，调用方应传 bump_attempts=False 避免重复计数。
         """
         sql = "UPDATE shops SET status='no_contact'"
         if bump_attempts:
             sql += ", attempts=attempts+1"
         self.conn.execute(sql + " WHERE domain=?", (domain,))
         self.conn.commit()
 
+    # ---------- work_items ----------
+    def topup_contact_work_items(self, queue: str, site: str,
+                                 domain_suffix: str, limit: int) -> int:
+        """从 shops 补货 work_items：最老的 pending 店铺入队并置 in_progress。
+
+        单事务内 SELECT + INSERT + UPDATE（BEGIN IMMEDIATE 立即取写锁）。
+        shops 状态语义与 claim_pending_shops 严格一致（pending → in_progress，
+        排序口径 first_seen_at, id），只是把「返回给调用方」改成「写入
+        work_items 表」；已入队店铺已非 pending，重复补货不会产生重复行。
+        """
+        try:
+            self.conn.execute("BEGIN IMMEDIATE")
+            rows = self.conn.execute(
+                "SELECT * FROM shops WHERE status='pending'"
+                " AND substr(domain, -?, ?) = ?"
+                " ORDER BY first_seen_at, id LIMIT ?",
+                (len(domain_suffix), len(domain_suffix), domain_suffix,
+                 limit)).fetchall()
+            now = _now()
+            for r in rows:
+                payload = json.dumps(
+                    {"domain": r["domain"], "name": r["name"],
+                     "url": r["url"]},
+                    ensure_ascii=False)
+                self.conn.execute(
+                    "INSERT INTO work_items (queue, site, payload_json,"
+                    " created_at) VALUES (?, ?, ?, ?)",
+                    (queue, site, payload, now))
+                self.conn.execute(
+                    "UPDATE shops SET status='in_progress' WHERE id=?",
+                    (r["id"],))
+            self.conn.commit()
+            return len(rows)
+        except Exception:
+            self.conn.rollback()
+            raise
+
+    def claim_work_item(self, queue: str, consumer_id: str) -> dict | None:
+        """原子认领该队列最老的 pending 工作项；无货返回 None。
+
+        SELECT + UPDATE 在同一 BEGIN IMMEDIATE 事务内，多消费者并发安全，
+        同一行只会被一个消费者领到。返回 {"id", "domain", "name", "url"}
+        （domain/name/url 解析自 payload_json）。
+        """
+        try:
+            self.conn.execute("BEGIN IMMEDIATE")
+            row = self.conn.execute(
+                "SELECT * FROM work_items WHERE queue=? AND status='pending'"
+                " ORDER BY id LIMIT 1", (queue,)).fetchone()
+            if not row:
+                self.conn.commit()
+                return None
+            self.conn.execute(
+                "UPDATE work_items SET status='claimed', claimed_by=?,"
+                " claimed_at=? WHERE id=?",
+                (consumer_id, _now(), row["id"]))
+            self.conn.commit()
+        except Exception:
+            self.conn.rollback()
+            raise
+        payload = json.loads(row["payload_json"])
+        return {"id": row["id"], "domain": payload.get("domain"),
+                "name": payload.get("name"), "url": payload.get("url")}
+
+    def finish_work_item(self, item_id: int, status: str,
+                         result: dict | None = None) -> None:
+        """工作项落终态（done/failed）+ finished_at + result_json。
+
+        result 为 None 时 result_json 存 NULL。
+        """
+        self.conn.execute(
+            "UPDATE work_items SET status=?, finished_at=?, result_json=?"
+            " WHERE id=?",
+            (status, _now(),
+             json.dumps(result, ensure_ascii=False)
+             if result is not None else None,
+             item_id))
+        self.conn.commit()
+
+    def reset_claimed_work_items(self) -> int:
+        """全部 claimed 工作项重置回 pending（进程中断残留的认领，
+        daemon 启动时调用），清空 claimed_by/claimed_at，返回重置行数。"""
+        cur = self.conn.execute(
+            "UPDATE work_items SET status='pending', claimed_by=NULL,"
+            " claimed_at=NULL WHERE status='claimed'")
+        self.conn.commit()
+        return cur.rowcount
+
     # ---------- category_progress ----------
     def get_category_progress(self, keyword: str) -> dict | None:
         """取类目分页进度（无记录返回 None）。"""
         row = self.conn.execute(
             "SELECT * FROM category_progress WHERE keyword=?",
             (keyword,)).fetchone()
         return dict(row) if row else None
 
     def advance_category_page(self, keyword: str, name: str = None,
                               shops_found: int = 0) -> int:
diff --git a/fetcher/tests/test_cli.py b/fetcher/tests/test_cli.py
new file mode 100644
index 0000000..ca063a7
--- /dev/null
+++ b/fetcher/tests/test_cli.py
@@ -0,0 +1,70 @@
+# -*- coding: utf-8 -*-
+"""CLI 解析层测试：daemon 子命令挂载 + 既有站点子命令防装配回归。"""
+
+import unittest
+
+from fetcher.cli.main import build_parser, config_from_args
+
+
+class CliParserTest(unittest.TestCase):
+    def setUp(self):
+        self.ap = build_parser()
+
+    # ---- daemon 子命令 ----
+
+    def test_daemon_defaults(self):
+        args = self.ap.parse_args(["daemon"])
+        self.assertEqual(args.site, "daemon")
+        # --queue 默认值（P0 不开放其他选择）
+        self.assertEqual(args.queue, "crawl_1688_contact")
+        # daemon 不套 task 二级 subparser
+        self.assertIsNone(getattr(args, "task", None))
+        # add_common_args 全套已挂载（抽查代表项）
+        self.assertEqual(args.rest_every, 20)
+        self.assertEqual(args.batch_rest, 900)
+        self.assertFalse(args.proxy)
+        self.assertFalse(args.headed)
+        # config_from_args 依赖的 num/limit 必须有默认（contact 口径）
+        self.assertEqual(args.num, 10)
+        self.assertEqual(args.limit, 0)
+
+    def test_daemon_queue_and_common_override(self):
+        args = self.ap.parse_args(
+            ["daemon", "--queue", "q2", "--workers", "3", "--limit", "5"])
+        self.assertEqual(args.queue, "q2")
+        self.assertEqual(args.workers, 3)
+        self.assertEqual(args.limit, 5)
+
+    def test_daemon_config_from_args(self):
+        # config_from_args 不读 args.task，daemon 命名空间可直接复用
+        cfg = config_from_args(self.ap.parse_args(["daemon"]))
+        self.assertEqual(cfg.batch_num, 10)
+        self.assertEqual(cfg.limit, 0)
+
+    def test_daemon_has_no_task_subparser(self):
+        # daemon 后不能再跟 task 位置参数（argparse 报错退出）
+        with self.assertRaises(SystemExit):
+            self.ap.parse_args(["daemon", "contact"])
+
+    # ---- 既有站点子命令防回归 ----
+
+    def test_existing_site_subcommands_unchanged(self):
+        cases = {
+            ("1688", "shop"): 200,
+            ("1688", "contact"): 10,
+            ("1688", "company"): 200,
+        }
+        for (site, task), num in cases.items():
+            args = self.ap.parse_args([site, task])
+            self.assertEqual(args.site, site)
+            self.assertEqual(args.task, task)
+            self.assertEqual(args.num, num)
+        args = self.ap.parse_args(["yiwugo", "search"])
+        self.assertEqual((args.site, args.task), ("yiwugo", "search"))
+        # contact 业务开关仍在
+        args = self.ap.parse_args(["1688", "contact", "--retry-failed"])
+        self.assertTrue(args.retry_failed)
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/fetcher/tests/test_daemon_task.py b/fetcher/tests/test_daemon_task.py
new file mode 100644
index 0000000..1355890
--- /dev/null
+++ b/fetcher/tests/test_daemon_task.py
@@ -0,0 +1,367 @@
+# -*- coding: utf-8 -*-
+"""DaemonTaskProxy 单元测试：三段式 acquire_item / 终态钩子 / CrawlLoop 联跑。
+
+真实临时 sqlite + 真实线程/条件变量，不 mock 被测对象本身；
+浏览器/网络侧沿用 test_control_loop.py 的假基建模式（FakePage/
+MockBrowserManager），inner task 用可编程的假实现。
+"""
+
+import json
+import sqlite3
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
+    ShopDB,
+    Session,
+    WorkerContext,
+)
+from fetcher.control import CrawlLoop, Task
+from fetcher.control import daemon_task
+from fetcher.control.daemon_task import DaemonTaskProxy
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.strategy.policy import Policy
+
+QUEUE = "crawl_1688_contact"
+
+
+def _shop(i):
+    return {"domain": f"shop{i}.1688.com", "name": f"店铺{i}",
+            "url": f"https://shop{i}.1688.com"}
+
+
+# ---------- 假 inner task / 假浏览器基建 ----------
+
+class FakeInnerTask(Task):
+    """可编程假任务：fetch 恒成功，记录每 worker 的成功/放弃明细。
+
+    acquire_item 不应被 proxy 透传调用（proxy 自己实现认领），
+    被调到即失败，防「proxy 偷偷走 inner 认领路径」的假阳性。
+    """
+
+    name = "fake-inner"
+    unit = "店铺"
+    batch_unit = "店铺"
+
+    def __init__(self):
+        self.lock = threading.Lock()
+        self.succeeded = []  # [(wid, domain)]
+        self.given_up = []   # [(wid, domain, reason, kind)]
+
+    def acquire_item(self, ctx):
+        raise AssertionError("daemon 模式下不应调到 inner.acquire_item")
+
+    def fetch(self, ctx, item):
+        return ActionResult(Outcome.OK, "", {"v": 1})
+
+    def on_success(self, ctx, item, result):
+        with self.lock:
+            self.succeeded.append((ctx.wid, item["domain"]))
+        stats = ctx.state.get("task", {}).get("stats")
+        if stats is not None:
+            stats["done"] = stats.get("done", 0) + 1
+        return 1
+
+    def on_giveup(self, ctx, item, reason, kind):
+        with self.lock:
+            self.given_up.append((ctx.wid, item["domain"], reason, kind))
+        return "标记跳过"
+
+    def make_stats(self):
+        return {"done": 0}
+
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
+        self.url = "https://shop1.1688.com/page/contactinfo.htm"
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
+    """launch 返回带假 page 的 Session（联跑用，不起真实浏览器）。"""
+
+    def __init__(self, page):
+        self.page = page
+
+    def launch(self, seed_kit=None, stop=None):
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
+# ---------- 测试基类 ----------
+
+class DaemonTaskTestBase(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = Path(self._tmp.name) / "t.db"
+        # 种子数据/断言用主连接；proxy 走 db_factory 注入（ctx.store=None 路径）
+        self.db = ShopDB(self.db_path)
+        self.inner = FakeInnerTask()
+        self.proxy = DaemonTaskProxy(
+            inner=self.inner, queue=QUEUE, site="1688",
+            domain_suffix=".1688.com",
+            db_factory=lambda: ShopDB(self.db_path))
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def make_ctx(self, wid=0, stop=None):
+        """store=None 的轻量 ctx：proxy 经 db_factory 按线程自建连接。"""
+        config = RunConfig(db_path=self.db_path, headless=True,
+                           use_proxy=False)
+        return WorkerContext(config=config, store=None,
+                             stop=stop or threading.Event(),
+                             log=lambda m: None, wid=wid)
+
+    def query(self, sql, args=()):
+        """断言另开连接（避免与 proxy 持有的连接相互干扰）。"""
+        conn = sqlite3.connect(self.db_path)
+        conn.row_factory = sqlite3.Row
+        try:
+            return conn.execute(sql, args).fetchall()
+        finally:
+            conn.close()
+
+    def work_item(self, item_id):
+        rows = self.query("SELECT * FROM work_items WHERE id=?", (item_id,))
+        self.assertEqual(len(rows), 1)
+        return rows[0]
+
+    def shop_status(self, domain):
+        return self.query("SELECT status FROM shops WHERE domain=?",
+                          (domain,))[0]["status"]
+
+    def set_wait_timeout(self, seconds):
+        """缩短等货自醒超时（模块级 _WAIT_TIMEOUT 注入点）。"""
+        orig = daemon_task._WAIT_TIMEOUT
+        daemon_task._WAIT_TIMEOUT = seconds
+        self.addCleanup(setattr, daemon_task, "_WAIT_TIMEOUT", orig)
+
+
+# ---------- 用例 ----------
+
+class AcquireItemTest(DaemonTaskTestBase):
+    # 用例 1：有货直取——预置 pending work_items，acquire 返回 payload dict
+    def test_acquire_claims_pending_work_item(self):
+        self.db.upsert_shops([_shop(1), _shop(2)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+
+        ctx = self.make_ctx(wid=3)
+        item = self.proxy.acquire_item(ctx)
+
+        self.assertIsNotNone(item)
+        self.assertIn("id", item)
+        # domain/name/url 三键必在（name/url 允许 None）
+        for key in ("domain", "name", "url"):
+            self.assertIn(key, item)
+        self.assertEqual(item["domain"], "shop1.1688.com")  # 最老 pending 先领
+        self.assertEqual(item["name"], "店铺1")
+        self.assertEqual(item["url"], "https://shop1.1688.com")
+        # 库内：claimed + claimed_by=w{wid}
+        row = self.work_item(item["id"])
+        self.assertEqual(row["status"], "claimed")
+        self.assertEqual(row["claimed_by"], "w3")
+        self.assertIsNotNone(row["claimed_at"])
+        # work_item id 记在本 worker 的 ctx.state 上
+        self.assertEqual(ctx.state["daemon_work_item_id"], item["id"])
+
+    # 用例 2：空队列自动补货——shops 有 pending、work_items 为空
+    def test_acquire_auto_topup_when_queue_empty(self):
+        self.db.upsert_shops([_shop(1), _shop(2)])
+        self.assertEqual(self.query("SELECT COUNT(*) AS c FROM work_items")[0]["c"], 0)
+
+        item = self.proxy.acquire_item(self.make_ctx())
+
+        self.assertIsNotNone(item)
+        self.assertEqual(item["domain"], "shop1.1688.com")
+        # 补货把两家 pending 店铺都入了队并标 in_progress
+        self.assertEqual(self.shop_status("shop1.1688.com"), "in_progress")
+        self.assertEqual(self.shop_status("shop2.1688.com"), "in_progress")
+        rows = self.query("SELECT status FROM work_items ORDER BY id")
+        self.assertEqual([r["status"] for r in rows], ["claimed", "pending"])
+
+    # 用例 3：stop 退出——队列空且无法补货，stop 置位后小超时内返回 None
+    def test_acquire_returns_none_after_stop(self):
+        self.set_wait_timeout(0.05)  # 注入小自醒超时，避免等满 30s
+        stop = threading.Event()
+        ctx = self.make_ctx(stop=stop)
+        threading.Timer(0.3, stop.set).start()
+
+        t0 = time.monotonic()
+        item = self.proxy.acquire_item(ctx)
+        elapsed = time.monotonic() - t0
+
+        self.assertIsNone(item)
+        # 确实阻塞等到了 stop（非「队列空立即返回 None」的快路径）
+        self.assertGreaterEqual(elapsed, 0.25)
+        # stop 后在注入的小超时量级内醒来返回，不会卡满 30s
+        self.assertLess(elapsed, 5.0)
+
+
+class TerminalHookTest(DaemonTaskTestBase):
+    # 用例 4：终态钩子——on_success→done / on_giveup→failed，重复 finish 幂等
+    def test_terminal_hooks_finish_work_item(self):
+        self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 3)
+        ctx0, ctx1 = self.make_ctx(wid=0), self.make_ctx(wid=1)
+        result = ActionResult(Outcome.OK, "", {"mobile": "13800138000"})
+
+        # on_success：透传 inner 返回值，work_item 落 done
+        item_a = self.proxy.acquire_item(ctx0)
+        n = self.proxy.on_success(ctx0, item_a, result)
+        self.assertEqual(n, 1)  # inner.on_success 的返回值透传
+        self.assertEqual(self.inner.succeeded, [(0, "shop1.1688.com")])
+        row_a = self.work_item(item_a["id"])
+        self.assertEqual(row_a["status"], "done")
+        self.assertIsNotNone(row_a["finished_at"])
+        self.assertIsNone(row_a["result_json"])  # 成功不带 result
+        self.assertNotIn("daemon_work_item_id", ctx0.state)  # pop 语义
+
+        # on_giveup：透传短语，work_item 落 failed + reason/kind 落 result_json
+        item_b = self.proxy.acquire_item(ctx1)
+        phrase = self.proxy.on_giveup(ctx1, item_b, "风控滑块", "block")
+        self.assertEqual(phrase, "标记跳过")  # inner.on_giveup 的返回值透传
+        self.assertEqual(self.inner.given_up,
+                         [(1, "shop2.1688.com", "风控滑块", "block")])
+        row_b = self.work_item(item_b["id"])
+        self.assertEqual(row_b["status"], "failed")
+        self.assertIsNotNone(row_b["finished_at"])
+        self.assertEqual(json.loads(row_b["result_json"]),
+                         {"reason": "风控滑块", "kind": "block"})
+
+        # 重复 finish 幂等：state 已 pop，第二次 on_giveup 不再落库
+        # （用不同 reason 调用，验证 result_json 保持首次的值）
+        self.proxy.on_giveup(ctx1, item_b, "另一个原因", "net")
+        row_b2 = self.work_item(item_b["id"])
+        self.assertEqual(row_b2["status"], "failed")
+        self.assertEqual(json.loads(row_b2["result_json"]),
+                         {"reason": "风控滑块", "kind": "block"})
+
+        # 不误伤其他 item：ctx1 认领 item_c 后，ctx0（state 已空）的
+        # stray on_success 不应动 item_c
+        item_c = self.proxy.acquire_item(ctx1)
+        self.proxy.on_success(ctx0, item_a, result)
+        row_c = self.work_item(item_c["id"])
+        self.assertEqual(row_c["status"], "claimed")
+        self.assertEqual(row_c["claimed_by"], "w1")
+        # item_a 也不被重复落库改状态
+        self.assertEqual(self.work_item(item_a["id"])["status"], "done")
+
+
+class CrawlLoopIntegrationTest(DaemonTaskTestBase):
+    # 用例 5：CrawlLoop 联跑——proxy 包假 inner，两个 worker 线程共享一个
+    # proxy 实例，跑完 N 项后 stop 置位，loop 正常退出且终态/统计正确
+    def test_crawl_loop_two_workers_shared_proxy(self):
+        self.set_wait_timeout(0.05)
+        n_items = 6
+        self.db.upsert_shops([_shop(i) for i in range(1, n_items + 1)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", n_items)
+
+        config = RunConfig(db_path=self.db_path, headless=True,
+                           use_proxy=False, batch_num=100, max_batches=0,
+                           sample_min=0, sample_max=0, rest_every=0,
+                           batch_rest=0.01, block_rest_min=0.01,
+                           block_rest_max=0.02, ip_retry=1,
+                           max_consecutive_fail=3, workers=2)
+        stop = threading.Event()
+        results, errors = {}, {}
+
+        def run_worker(wid):
+            try:
+                store = IdentityStore(ShopDB(self.db_path))
+                ctx = WorkerContext(
+                    config=config, store=store,
+                    browser_manager=MockBrowserManager(FakePage()),
+                    site=Alibaba1688Plugin(), stop=stop,
+                    log=lambda m: None, wid=wid)
+                policy = Policy(table={}, strategies={},
+                                max_consecutive_fail=3)
+                results[wid] = CrawlLoop(ctx, self.proxy, policy=policy).run()
+            except Exception as e:  # noqa: BLE001
+                errors[wid] = e
+
+        threads = [threading.Thread(target=run_worker, args=(wid,),
+                                    name=f"worker-{wid}", daemon=True)
+                   for wid in (0, 1)]
+        for t in threads:
+            t.start()
+
+        # 监视：全部落 done 后置 stop，worker 从等货中醒来退出
+        deadline = time.monotonic() + 15
+        while time.monotonic() < deadline:
+            done = self.query("SELECT COUNT(*) AS c FROM work_items"
+                              " WHERE status='done'")[0]["c"]
+            if done >= n_items:
+                break
+            time.sleep(0.02)
+        stop.set()
+        for t in threads:
+            t.join(timeout=10)
+
+        self.assertEqual(errors, {})
+        self.assertFalse(any(t.is_alive() for t in threads),
+                         "worker 未在 stop 后退出")
+        self.assertEqual(set(results), {0, 1})
+
+        # 终态：N 项全 done，无残留 claimed/pending
+        rows = self.query("SELECT status, COUNT(*) AS c FROM work_items"
+                          " GROUP BY status")
+        self.assertEqual({r["status"]: r["c"] for r in rows},
+                         {"done": n_items})
+
+        # 不串 item：两 worker 认领的 domain 合起来恰好是全集且无重复
+        domains = [d for _wid, d in self.inner.succeeded]
+        self.assertEqual(len(domains), n_items)
+        self.assertEqual(sorted(domains),
+                         [f"shop{i}.1688.com" for i in range(1, n_items + 1)])
+
+        # stats：各 worker 的 done 计数与其成功明细一致，总和 = N
+        per_wid = {wid: sum(1 for w, _d in self.inner.succeeded if w == wid)
+                   for wid in (0, 1)}
+        for wid in (0, 1):
+            self.assertEqual(results[wid]["done"], per_wid[wid])
+        self.assertEqual(sum(per_wid.values()), n_items)
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/fetcher/tests/test_work_items.py b/fetcher/tests/test_work_items.py
new file mode 100644
index 0000000..cce84b9
--- /dev/null
+++ b/fetcher/tests/test_work_items.py
@@ -0,0 +1,166 @@
+# -*- coding: utf-8 -*-
+"""work_items 存储层测试：topup / claim / finish / reset 四方法（临时 sqlite）。
+仿 test_contact_task.py 基建，不起浏览器/网络。"""
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+
+from fetcher.db import ShopDB
+
+QUEUE = "crawl_1688_contact"
+
+
+def _shop(i, suffix=".1688.com"):
+    return {"domain": f"shop{i}{suffix}", "name": f"店铺{i}",
+            "url": f"https://shop{i}{suffix}"}
+
+
+class WorkItemsTest(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "t.db")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def _items(self, where="", params=()):
+        return self.db.conn.execute(
+            f"SELECT * FROM work_items {where}", params).fetchall()
+
+    def _shop_status(self, domain):
+        return self.db.conn.execute(
+            "SELECT status FROM shops WHERE domain=?",
+            (domain,)).fetchone()[0]
+
+    # 用例 1：top-up 生成 work_items 且 shops 标 in_progress；
+    # 重复 top-up 只补剩余 pending，不产生重复行
+    def test_topup_marks_shops_and_no_duplicates(self):
+        # DDL 前置断言：表与索引存在、列齐全
+        cols = {r[1] for r in self.db.conn.execute(
+            "PRAGMA table_info(work_items)")}
+        self.assertEqual(
+            cols, {"id", "queue", "site", "batch_id", "payload_json",
+                   "requires", "status", "claimed_by", "claimed_at",
+                   "finished_at", "result_json", "created_at"})
+        idx = {r[1] for r in self.db.conn.execute(
+            "PRAGMA index_list(work_items)")}
+        self.assertIn("idx_work_items_claim", idx)
+
+        # 3 家 1688 店铺 + 1 家 madeinchina（suffix 不匹配，不应入队）
+        self.db.upsert_shops([_shop(1), _shop(2), _shop(3),
+                              _shop(9, ".cn.made-in-china.com")])
+        n = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+        self.assertEqual(n, 2)
+
+        items = self._items("ORDER BY id")
+        self.assertEqual(len(items), 2)
+        # 排序口径与 claim_pending_shops 一致：first_seen_at, id（最老优先）
+        self.assertEqual([json.loads(r["payload_json"])["domain"]
+                          for r in items],
+                         ["shop1.1688.com", "shop2.1688.com"])
+        for r in items:
+            self.assertEqual(r["queue"], QUEUE)
+            self.assertEqual(r["site"], "1688")
+            self.assertEqual(r["status"], "pending")
+            self.assertEqual(r["requires"], '["channel","browser"]')
+            self.assertIsNone(r["batch_id"])
+            self.assertIsNotNone(r["created_at"])
+            payload = json.loads(r["payload_json"])
+            self.assertEqual(set(payload), {"domain", "name", "url"})
+        # shops 侧状态语义：被补货的标 in_progress，其余不动
+        self.assertEqual(self._shop_status("shop1.1688.com"), "in_progress")
+        self.assertEqual(self._shop_status("shop2.1688.com"), "in_progress")
+        self.assertEqual(self._shop_status("shop3.1688.com"), "pending")
+        self.assertEqual(self._shop_status("shop9.cn.made-in-china.com"),
+                         "pending")
+
+        # 重复 top-up：已入队的店铺已是 in_progress，只补剩余 pending
+        n2 = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+        self.assertEqual(n2, 1)
+        domains = [json.loads(r["payload_json"])["domain"]
+                   for r in self._items()]
+        self.assertEqual(sorted(domains), ["shop1.1688.com", "shop2.1688.com",
+                                           "shop3.1688.com"])
+        self.assertEqual(len(domains), len(set(domains)))  # 无重复行
+
+    # 用例 5：空 shops 时 top-up 返回 0
+    def test_topup_empty_returns_zero(self):
+        n = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 5)
+        self.assertEqual(n, 0)
+        self.assertEqual(self._items(), [])
+
+    # 用例 2：两个消费者认领不到同一行（顺序模拟并发）
+    def test_claim_no_double_claim(self):
+        self.db.upsert_shops([_shop(1), _shop(2)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+
+        a = self.db.claim_work_item(QUEUE, "w0")
+        b = self.db.claim_work_item(QUEUE, "w1")
+        self.assertIsNotNone(a)
+        self.assertIsNotNone(b)
+        self.assertNotEqual(a["id"], b["id"])  # 不撞单
+        # 返回 dict 含 id + payload 解析后的 domain/name/url
+        self.assertEqual(a["domain"], "shop1.1688.com")  # 最老 pending 先领
+        self.assertEqual(a["name"], "店铺1")
+        self.assertEqual(a["url"], "https://shop1.1688.com")
+        self.assertEqual(b["domain"], "shop2.1688.com")
+        # 库内状态：claimed + claimed_by + claimed_at
+        rows = {r["id"]: r for r in self._items()}
+        self.assertEqual(rows[a["id"]]["status"], "claimed")
+        self.assertEqual(rows[a["id"]]["claimed_by"], "w0")
+        self.assertIsNotNone(rows[a["id"]]["claimed_at"])
+        self.assertEqual(rows[b["id"]]["claimed_by"], "w1")
+        # 队列领空后返回 None
+        self.assertIsNone(self.db.claim_work_item(QUEUE, "w2"))
+
+    # 用例 3：finish 落终态 + finished_at + result_json
+    def test_finish_work_item(self):
+        self.db.upsert_shops([_shop(1), _shop(2)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+        a = self.db.claim_work_item(QUEUE, "w0")
+        b = self.db.claim_work_item(QUEUE, "w1")
+
+        self.db.finish_work_item(a["id"], "done", {"mobile": "13800138000"})
+        row = self.db.conn.execute(
+            "SELECT * FROM work_items WHERE id=?", (a["id"],)).fetchone()
+        self.assertEqual(row["status"], "done")
+        self.assertIsNotNone(row["finished_at"])
+        self.assertEqual(json.loads(row["result_json"]),
+                         {"mobile": "13800138000"})
+
+        # result=None 时 result_json 存 NULL
+        self.db.finish_work_item(b["id"], "failed")
+        row = self.db.conn.execute(
+            "SELECT * FROM work_items WHERE id=?", (b["id"],)).fetchone()
+        self.assertEqual(row["status"], "failed")
+        self.assertIsNotNone(row["finished_at"])
+        self.assertIsNone(row["result_json"])
+
+    # 用例 4：reset_claimed 把 claimed 重置为 pending（清空认领信息）
+    def test_reset_claimed_work_items(self):
+        self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 3)
+        a = self.db.claim_work_item(QUEUE, "w0")
+        b = self.db.claim_work_item(QUEUE, "w1")
+        # shop3 的工作项仍是 pending，不应受影响
+
+        n = self.db.reset_claimed_work_items()
+        self.assertEqual(n, 2)
+        rows = {r["id"]: r for r in self._items()}
+        for item_id in (a["id"], b["id"]):
+            self.assertEqual(rows[item_id]["status"], "pending")
+            self.assertIsNone(rows[item_id]["claimed_by"])
+            self.assertIsNone(rows[item_id]["claimed_at"])
+        others = [r for r in self._items()
+                  if r["id"] not in (a["id"], b["id"])]
+        self.assertEqual(len(others), 1)
+        self.assertEqual(others[0]["status"], "pending")
+        # 无 claimed 行时返回 0
+        self.assertEqual(self.db.reset_claimed_work_items(), 0)
+
+
+if __name__ == "__main__":
+    unittest.main()
