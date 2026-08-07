=== git log ===
8a3db10 docs(daemon-p0): Step 1.1 brief/ledger + SPEC 增补 cold_start 已知差异裁定
323e491 docs(daemon-p0): Step 1.1 读码验证 item 访问契约，回填 SPEC §4 假设 1、2 结论

=== diff --stat ===
 docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md     |  6 +-
 docs/feat_2026-08-07_fetcher-daemon-p0/ledger.md   |  9 +++
 .../task-1.1-brief.md                              | 23 +++++++
 .../task-1.1-report.md                             | 77 ++++++++++++++++++++++
 4 files changed, 113 insertions(+), 2 deletions(-)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md b/docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md
index f7511ba..c483c4b 100644
--- a/docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md
@@ -90,38 +90,40 @@ CREATE INDEX IF NOT EXISTS idx_work_items_claim ON work_items(queue, status, id)
 ### 3.3 DaemonTaskProxy 行为
 
 - `prepare(config)`：调 inner.prepare；打印队列当前 pending 数（替代 contact 原 pending shops 计数展示，口径=未补货的 shops pending + work_items pending）。
 - `acquire_item(ctx)`：
   1. `claim_work_item`；命中 → 返回 payload dict（`{"domain","name","url"}`，键访问与 sqlite Row 的 `item["domain"]` 访问兼容）；
   2. 未命中 → `topup_contact_work_items`（单次补货上限=消费者数×4，防单事务过大）→ 补到货则 `notify_all` 并重试 claim；
   3. 仍无货 → 条件变量 wait（超时 30s 自醒），醒后先查 `ctx.stop`，置位则返回 None（CrawlLoop 正常退出），否则回到 1。
 - `after_item(...)`：透传 inner 后按结果 `finish_work_item`（done/failed）。
 - 其余方法（`fetch/validate/on_success/on_giveup/cold_start/label/compose/summary/...`）全部透传 inner。
 
+**已知行为差异（Step 1.1 发现，裁定：接受）**：站点级 `cold_start`（`sites/alibaba1688/__init__.py:73`）对 dict item 走 `item["domain"]` 分支（逛**店铺**首页），对 sqlite Row 走 `getattr` 得 None（逛**站点**首页）。daemon 用 dict 后冷启动软着陆从站点首页变为店铺首页——该 dict 分支是既有代码显式预留的，方向更拟人（先逛目标店再抓该店联系方式），判定为可接受的等价性偏差，在 §5 等价性对比中不作为差异项。
+
 **shops 表状态流（初始化+变更路径，职责分配）**：
 
 - 初始化：shops 行由既有 shop 采集任务写入（daemon 不负责产生）。
 - 变更：pending → in_progress 由 `topup_contact_work_items`（唯一写入者）；in_progress → done/no_contact/failed 由 inner `ContactTask.on_success/on_giveup`（与现状一致，不变）；in_progress → pending（崩溃恢复）由既有 `reset_in_progress` + daemon 启动时的 `reset_claimed_work_items` 配合：daemon 启动先 reset work_items，再对 shops 调 `reset_in_progress`（**注意**：这会把其他来源的 in_progress 也重置——与现有 CLI 启动行为一致，属于既有语义，不新增风险）。
 - work_items 行是一次性派送凭证：shops 的状态机仍是数据事实源，work_items 终态只影响派送，不回写 shops。同一 shop 正常流程只进一次 work_items（pending 过滤保证）；reset 路径下 work_items 重新 pending、shops 重新 pending，二者一致。
 
 ### 3.4 CLI 与退出语义
 
 - 挂载点：`cli/main.py` 顶层 `ap.add_subparsers` 增加 `daemon` parser（不属于任何站点），带 `add_common_args()` 全套参数 + `--queue`（P0 只有默认值 `crawl_1688_contact`，不开放选择）。
 - `main()` 中 `args.site == "daemon"` 分支：`get_site("1688")` 取插件 → `site.make_task("contact")` 包 `DaemonTaskProxy` → 装配与现有分支相同的 provider/policy → `Engine(...).run()`。
 - 退出：SIGTERM/SIGHUP/KeyboardInterrupt 沿用 Engine 既有优雅退出（stop 置位 → proxy 的 wait 自醒返回 None → loop 收工 → 回写 Cookie 关浏览器）。`--limit N` 由 CrawlLoop 既有逻辑强制收工，作为冒烟与联调的退出手段。
 
 ## 4. 契约与行为后果（假设与验证）
 
 | # | 行为假设 | 依据 | 验证方式 |
 |---|---|---|---|
-| 1 | `ContactTask.fetch/on_success` 对 item 只做 `item["domain"]` 式键访问，dict 可 1:1 替代 sqlite Row | 推断（explore 报告：item 为 shops 行，用 domain/name/url） | Step 1.1 读 `contact.py` 确认全部 item 访问点；若有点属性访问（`item.domain`）则 payload 改用 `types.SimpleNamespace` 或 dict 子类，结论回填本节 |
-| 2 | `Engine` 注入 `loop_factory`/task 包装后行为与直跑一致（无对 task 具体类型的 isinstance 判断） | 推断（engine.py:36-53 构造器预留注入点，task 经参数传入） | Step 2.1 全文 grep `isinstance.*Task` 确认；单测 test_engine.py 模式复刻 |
+| 1 | `ContactTask.fetch/on_success` 对 item 只做 `item["domain"]` 式键访问，dict 可 1:1 替代 sqlite Row | 已读码验证（Step 1.1）：`contact.py` 全部 item 访问点均为 `item["..."]` 键访问（163/171/180/182/227/230/245/252 行），键集合 = {`domain`,`name`,`url`}，无 `item.domain` 属性访问；间接消费方站点 `cold_start`（`sites/alibaba1688/__init__.py:73`）已显式兼容 dict | **dict 可直接替代**，无需 SimpleNamespace/子类适配；payload 必须含 `domain`/`name`/`url` 三键（`label` 用 `name`+`domain`，`fetch` 用 `domain`+`url`，`cold_start`/`on_success`/`on_giveup`/`on_abort` 用 `domain`） |
+| 2 | `Engine` 注入 `loop_factory`/task 包装后行为与直跑一致（无对 task 具体类型的 isinstance 判断） | 已读码验证（Step 1.1）：全包 grep `isinstance` / `type(...) is` / `__class__`，`engine.py`/`loop.py`/`task.py`/`cli/main.py` 中对 task 零命中（现存 isinstance 均判 Scenario/dict/Channel 等数据类型），task 全程鸭子类型调用 | **无特判**：Engine/CrawlLoop/CLI 只经 Task 协议方法（`make_stats`/`compose`/`acquire_item`/`summary`…）调用 task，`DaemonTaskProxy` 实现协议即可经 `Engine(cfg, task=proxy)`（engine.py:36-41）与 `loop_factory`（engine.py:53）注入；Step 2.1 单测复刻 test_engine.py 模式 |
 | 3 | work_items 表加进 fetcher `SCHEMA` 不影响平台侧：平台读库用 `app.db.connect()` 只读连接 + 防御性探测，不校验全表清单 | 项目约定（AGENTS.md §4）+ 推断 | P0 冒烟时平台服务保持运行，确认平台各页面/API 无异常 |
 | 4 | 条件变量 wait 挂起期间，该消费者的通道/浏览器空转无额外风险（与现状批休期间状态相同） | 现状类比（批休 900s 也是持通道挂起） | 无需 spike；等价性冒烟覆盖 |
 | 5 | 青果通道在 daemon 常驻（可能数天）下，隧道缓存 TTL 30 分钟刷新逻辑在长跑中稳定 | 推断（qingguo.py:50-55 缓存逻辑与运行时长无关） | 长跑观察留到 P1+；P0 冒烟为短时有限运行，不阻塞 |
 
 唯一需要先做的是假设 1 的确认（PLAN 第一步）；无第三方库新依赖，无 CloakBrowser 席位语义假设（席位问题属 P2 多 context 设计，P0 每消费者仍是一个浏览器实例，与现状一致）。
 
 ## 5. 验收标准（P0 整体）
 
 1. `cd fetcher && python -m pytest tests -x -q` 全绿（含新增用例）。
 2. 冒烟：`python -m fetcher daemon --proxy --limit 5` 跑通——5 个店铺联系人提取完成，work_items 5 行 done，shops 对应行 done，contacts 落库字段口径与旧 CLI 相同。
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/ledger.md b/docs/feat_2026-08-07_fetcher-daemon-p0/ledger.md
new file mode 100644
index 0000000..85ac40e
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/ledger.md
@@ -0,0 +1,9 @@
+# SDD ledger — plan: docs/feat_2026-08-07_fetcher-daemon-p0/PLAN.md
+
+- 分支：feat/fetcher-daemon-p0（base main 66fde5d）
+- Setup commit：e50270b（docs：scheduler-architecture + SPEC/PLAN）
+- 环境偏差记录：本环境 Agent 工具无模型选择参数，implementer/reviewer 均用默认 coder 类型派发，无法显式降档。
+
+## Step 进度
+
+（尚无完成记录）
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-1.1-brief.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-1.1-brief.md
new file mode 100644
index 0000000..d12bb45
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-1.1-brief.md
@@ -0,0 +1,23 @@
+# Step 1.1 brief — 确认 item 访问契约（SPEC §4 假设 1、2）
+
+> 来源：PLAN.md Phase 1 Step 1.1。本文本是你的需求唯一来源。
+
+## 内容
+
+1. 通读 `fetcher/fetcher/sites/alibaba1688/contact.py` 中 `fetch / validate / on_success / on_giveup / label / cold_start / after_item`（以及它们调用的辅助函数）对 item（shops 表一行）的**全部访问点**，确认访问形式是 `item["domain"]` 式键访问还是 `item.domain` 式属性访问，逐处列出 file:line 和访问的键名。
+2. 在 `fetcher/fetcher/` 全包 grep `isinstance` 中带 Task 类名的判断（如 `isinstance(..., ContactTask)`、`type(task) is` 等），重点看 `control/engine.py`、`control/loop.py`、`control/task.py`、`cli/main.py`，确认 Engine/CrawlLoop/CLI 是否对 task 的具体类型有任何特判。
+3. 把结论回填到 SPEC：`docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md` §4 表格中假设 1、2 两行的「依据」列从「推断」改为「已读码验证（附 file:line）」，「验证方式」列补上结论（假设 1：dict 可直接替代 / 需 SimpleNamespace / 需其他适配——明确给出；假设 2：无特判 / 有特判在何处）。
+
+## 背景（为什么做这个）
+
+后续 Step 会用 `DaemonTaskProxy` 包装 ContactTask，`acquire_item` 返回的是 work_items 的 payload dict 而非 sqlite Row。本 Step 就是验证「dict 能否 1:1 替代 Row」和「Engine 是否对 task 类型有特判」这两个假设，结论直接决定 Step 2.1 的 payload 形态。
+
+## 验收
+
+- [ ] SPEC §4 假设 1、2 的「依据」列从「推断」改为「已读码验证」，结论明确无歧义
+- [ ] item 全部访问点有完整 file:line 清单（写进你的 report）
+
+## 约束
+
+- 本 Step 只读代码 + 改 SPEC.md 一处表格，**不改任何 fetcher 代码**。
+- 发现的访问点清单务必完整（漏一处，Step 2.1 就可能踩坑）。
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-1.1-report.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-1.1-report.md
new file mode 100644
index 0000000..368286f
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-1.1-report.md
@@ -0,0 +1,77 @@
+# Step 1.1 report — 确认 item 访问契约（SPEC §4 假设 1、2）
+
+> 执行日期：2026-08-07。范围：只读代码 + 回填 SPEC.md §4 表格假设 1、2 两行，未改任何 fetcher 代码。
+
+## 1. item 全部访问点清单（ContactTask 及其间接消费方）
+
+`ContactTask`（`fetcher/fetcher/sites/alibaba1688/contact.py`）对 item（shops 表一行，`sqlite3.Row`，见 `db.py:188` row_factory）的全部访问点——**全部为 `item["key"]` 键访问，零属性访问**：
+
+| file:line | 所在方法 | 访问形式 | 键名 |
+|---|---|---|---|
+| contact.py:163 | `label` | `item["name"] or item["domain"]` | `name`、`domain` |
+| contact.py:168 | `cold_start` | `item is None`（空值判断，非键访问） | — |
+| contact.py:171 | `cold_start` | `item['domain']` | `domain` |
+| contact.py:180 | `fetch` | `item["domain"]` | `domain` |
+| contact.py:182 | `fetch` | `item["url"] or f"https://{domain}/"` | `url` |
+| contact.py:227 | `on_success` | `item["domain"]`（save_contact） | `domain` |
+| contact.py:230 | `on_success` | `item["domain"]`（mark_shop_no_contact） | `domain` |
+| contact.py:245 | `on_giveup` | `item["domain"]`（mark_shop_failed） | `domain` |
+| contact.py:252 | `on_abort` | `item['domain']` | `domain` |
+
+不访问 item 的方法（逐一确认）：
+
+- `validate`（209-219）：只读 `result.data`，不碰 item。
+- `giveup_cost`（255-257）：常量返回 1。
+- `after_item`：ContactTask 未覆盖，基类 `control/task.py:113` 默认为空实现。
+- `prepare`/`summary`/`compose`/`make_stats`/`rest_counter`/`empty_message`：签名不含 item。
+- 辅助函数 `parse_contact_text`（49-82）：只处理页面文本，与 item 无关。
+- `on_success` 235-238 行的 `info[...]` 是 `result.data` 的拷贝，不是 item。
+
+item 离开 ContactTask 后的间接消费方（CrawlLoop 透传链）：
+
+| file:line | 访问形式 | 说明 |
+|---|---|---|
+| control/loop.py:154 | `self.ctx.state["item"] = item` | 只存不读键，类型无关 |
+| atoms/browser_ops.py:103-106 | `ctx.state.get("item")` → `ctx.site.cold_start(page, item, ...)` | 透传给站点插件 |
+| sites/alibaba1688/__init__.py:73-74 | `item["domain"] if isinstance(item, dict) else getattr(item, "domain", None)` | **已显式兼容 dict**；注：sqlite Row 无属性访问，现行为走 getattr 分支得 None 退回站点首页，dict 反而能命中 domain 分支（差异方向对 daemon 有利，且该原子失败不阻断） |
+
+**键集合结论：{`domain`, `name`, `url`}**。`domain` 为必需键；`name`/`url` 允许 falsy（两处均带 `or` 兜底），但键必须存在——dict 缺键会 `KeyError`，而 sqlite Row 缺列在 `item["name"]` 处同样抛错，语义一致。
+
+## 2. isinstance 特判 grep 结果
+
+命令：
+
+```
+grep -rn -E 'isinstance|type\(.*\)\s*(is|==)|__class__' fetcher/fetcher/
+```
+
+命中 13 处，**无一处针对 Task 具体类型**。逐条分类：
+
+- `strategy/policy.py:125` — 判 `Scenario` 枚举 key
+- `atoms/facebook_group.py:186`、`net/proxy/qingguo.py:140`、`yiwugo/features.py:183` 等 — 判 `dict`/`list` 数据形态
+- `net/browser.py:333` — 判 `Channel`
+- `sites/alibaba1688/__init__.py:73`、`sites/madeinchina/__init__.py:84` — 判 `dict`（即上述 item 兼容分支，反而是对 dict payload 友好的证据）
+- `sites/__init__.py:27` — 判 `str`
+
+重点文件逐一确认：
+
+- `control/engine.py`：全文无 isinstance；task 仅经 `self.task.compose`（172）、`self.task.summary`（214）调用，构造器 36-41 行 task 经参数传入、53 行 `loop_factory or CrawlLoop`。
+- `control/loop.py`：无 isinstance；task 仅经协议方法调用（`make_stats`/`cold_start_before_acquire`/`acquire_item`/`label`/`fetch`/`validate`/`on_success`/`on_abort`/`on_giveup`/`giveup_cost`/`after_item`/`rest_counter`/`batch_unit`/`unit`/`ip_request_budget`/`empty_message`）。
+- `control/task.py`：协议基类，无类型判断。
+- `cli/main.py`：`task = site.make_task(args.task)`（166 行）→ `task.prepare(cfg)`（167）→ `Engine(cfg, task, ...)`（179），无类型分支。
+
+补充：`Engine` 文档注释明确「Task 对象跨 worker 共享」——DaemonTaskProxy 内的条件变量等共享状态需注意线程安全（Step 2.1 实现时注意，不影响本假设结论）。
+
+## 3. SPEC 回填结论
+
+- **假设 1 → 成立：dict 可直接替代** sqlite Row，无需 `SimpleNamespace`/dict 子类等适配。约束：payload 必须含 `domain`/`name`/`url` 三键（与 SPEC §3.2 DDL 注释的 `{"domain","name","url"}` 一致，无需变更）。
+- **假设 2 → 成立：无特判**。Engine/CrawlLoop/CLI 对 task 全程鸭子类型，只走 Task 协议方法；`DaemonTaskProxy` 实现协议即可经 `Engine(cfg, task=proxy, ..., loop_factory=...)` 注入。
+
+SPEC.md §4 表格两行已更新：「依据」列由「推断」改为「已读码验证（附 file:line）」，「验证方式」列写入上述明确结论。
+
+## 4. 改动与提交
+
+- 改动文件（仅 1 个）：`docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md`（§4 表格假设 1、2 两行）
+- 本 report：`docs/feat_2026-08-07_fetcher-daemon-p0/task-1.1-report.md`
+- commit：见下方最终汇报（`docs(daemon-p0): ...`）
+- 未改任何 fetcher 代码；本 Step 无代码改动，未跑测试套件（按 brief 要求）。
