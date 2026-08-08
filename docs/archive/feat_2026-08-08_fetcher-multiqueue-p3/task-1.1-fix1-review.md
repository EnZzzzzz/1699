# Re-review Package — Step 1.1 fix round 1

## Commits
d682282 fix(multiqueue-p3): review 修复——claim_next_eligible 非法 payload 不泄漏（解析入事务前）+ 显式列 + release rowcount=0 rollback（319 passed）
3617fce docs(multiqueue-p3): P3-0 spike 完成——C1 已验证回填 SPEC §4 + ledger/brief/review 入库

## Stat
 docs/feat_2026-08-08_fetcher-multiqueue-p3/PLAN.md | 105 ++++++
 docs/feat_2026-08-08_fetcher-multiqueue-p3/SPEC.md | 201 +++++++++++
 .../ledger.md                                      |  31 ++
 .../task-0.1-review.md                             | 158 ++++++++
 .../task-1.1-brief.md                              |  92 +++++
 .../task-1.1-report.md                             |  86 +++++
 .../task-1.1-review.md                             | 402 +++++++++++++++++++++
 fetcher/fetcher/db.py                              |  17 +-
 fetcher/tests/test_work_items.py                   |  30 ++
 9 files changed, 1116 insertions(+), 6 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/PLAN.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/PLAN.md
new file mode 100644
index 0000000..1e223c3
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/PLAN.md
@@ -0,0 +1,105 @@
+# PLAN — P3 多队列跨站填充
+
+> 版本：v1 · 2026-08-08 · 待评审
+> 配套：SPEC.md（同目录）。执行流程按 subagent-driven-development skill；ledger.md 随执行建立。
+
+## Phase 清单
+
+| Phase | 目标 | 预计 Step | 依赖 | 状态 |
+|---|---|---|---|---|
+| P3-0 | CloakBrowser 多 context 席位 spike（C1 实测） | 1 | 无 | done |
+| P3-1 | 调度内核：work_items 扩展 + 冷却表改建 + 让出型 chokepoint | 3 | P3-0（可并行，不依赖其结果） | pending |
+| P3-2 | 浏览器层：Session/BrowserManager 多 context + 种子池 (worker,site) 粒度 | 3 | P3-0 结论回填 SPEC §4 | pending |
+| P3-3 | QueueRouter + daemon CLI + SwapIP 两阶段 | 3 | P3-1、P3-2 | pending |
+| P3-4 | madeinchina 队列接入（contact + shop feeder） | 2 | P3-3 | pending |
+| P3-5 | 1688 shop/company feeder 接入 | 2 | P3-4 | pending |
+| P3-6 | 端到端验收冒烟 + 终审 | 2 | P3-5 | pending |
+
+---
+
+## P3-0 CloakBrowser spike
+
+**准入**：无。**完成标准**：实测报告写入本目录 `spike-cloakbrowser-multicontext.md`，结论回填 SPEC §4 C1（推断→已验证）；若证伪，回 SPEC 重议降级方案再放行 P3-2。
+
+- [x] **Step 0.1** 席位计数实测（估 30min，依赖无，状态 pending）
+  - 脚本放 `/tmp`：读 baseline `get_active_session_count` → headless 直连 launch → 计数（应 +1）→ `browser.new_context()` 第二个 context → 计数（应不变）→ 第二 context 内 `page.goto("about:blank")` 确认可用 → close → 计数（应 -1）。
+  - 环境纪律：本机活爬虫占 ~2 席，本次 +1 不超 solo=5；不开代理（避免占用青果隧道）；全程 headless。
+  - 验收：报告含每次计数原始值与结论；报告文件放 plan 目录（不放 /tmp，防丢证据）。
+
+## P3-1 调度内核
+
+**准入**：无（与 P3-0 并行）。**完成标准**：新增 DB 函数与冷却语义单测全绿；`_cooldown` 让出型调用点全部改为登记即返回；现有测试基线不 regress。
+
+- [ ] **Step 1.1** work_items 扩展（估 20min，依赖无，状态 pending）
+  - `db.py`：migrate 幂等加 `attempts INTEGER NOT NULL DEFAULT 0`；新增 `release_work_item(item_id, max_attempts=3)`、`claim_next_eligible(queues, consumer_id)`。
+  - 验收：TDD 单测覆盖——release 回 pending/attempts 耗尽置 failed/claim_next_eligible 按队列集合过滤+FIFO+并发不重复认领。
+- [ ] **Step 1.2** 冷却表改建 + eligible_queues（估 20min，依赖 1.1，状态 pending）
+  - `WorkerContext.cooldown_until` 键改 site；`ctx.state["active_site"]` 约定；新增 `eligible_queues(registry, ctx, now)`（纯函数，可单测）；claim 过滤 + condvar `timeout=min(最近冷却到期剩余, 30s)`。
+  - 验收：单测——冷却中站点被过滤、到期恢复可见、timeout 计算正确。
+- [ ] **Step 1.3** `_cooldown` 让出型改造（估 30min，依赖 1.2，状态 pending）
+  - loop 让出型调用点（sample_interval/batch_rest/periodic_rest/策略冷却）登记即返回；launch_backoff 保留原地并加注释；P1 遗留注释同步更新。
+  - 策略冷却后 item 未完成的路径暂保留现状（等 P3-3 router 接 release），本 Step 只保证单队列行为等价。
+  - 验收：单队列 daemon 冒烟（`--workers 1` 直连临时库，日志放 plan 目录）行为与改造前等价；全量测试绿。
+  - 注：直连环境 1688 滑块墙近乎必现，全 failed 是环境噪声，取结构证据（冷却登记日志）即可，不纠缠滑块。
+
+## P3-2 浏览器层多 context
+
+**准入**：P3-0 结论回填 SPEC §4 C1 = 已验证。**完成标准**：单站点路径行为等价（1688 contact 旧 CLI 冒烟）；多 context 隔离单测通过。
+
+- [ ] **Step 2.1** Session/SiteView 重构（估 40min，依赖 P3-0，状态 pending）
+  - `Session.views[site]` + `ensure_site` 懒建 + `close_site`/全量 `close` 两层语义；`ctx.page` 路由活动 view；`session.ctx` property 同步。
+  - 验收：SPEC §6.1 清单中 session/browser 两侧消费方全部迁移；C2 隔离单测（同 browser 两 context Cookie 互不可见）。
+- [ ] **Step 2.2** relaunch/warmup/种子池适配（估 30min，依赖 2.1，状态 pending）
+  - relaunch 全 view 回写后关进程、views 清空懒重建；`_alloc_seed_kits` 改 (worker, site) 粒度；`needs_relaunch` 状态位。
+  - 验收：单测 + 旧 CLI `1688 contact --workers 1` 直连冒烟等价。
+- [ ] **Step 2.3** 原子/策略消费方迁移（估 30min，依赖 2.1，状态 pending）
+  - RelaunchBrowser、WaitHumanLogin/WaitHumanVerify、loop 的 `_relaunch`/`_ensure_fresh_ip`/`_check_budget`/`_cleanup` 全部走活动 view。
+  - 验收：全量测试绿；grep 无残留直接持有 page 跨 item 的引用。
+
+## P3-3 QueueRouter + SwapIP
+
+**准入**：P3-1、P3-2 完成。**完成标准**：`daemon --queues` 多队列装配跑通（先 1688 contact + mic contact 两条同构队列）；SwapIP 无头两阶段单测。
+
+- [ ] **Step 3.1** QueueRouter + 注册表装配（估 40min，依赖 1.3、2.3，状态 pending）
+  - `control/queue_router.py`：QueueSpec 注册表、acquire 三段式（claim_next_eligible→topup→condvar）、on_success/on_giveup 路由 + finish/release 回写、active_site 绑定、每 site Policy 装配；替换 DaemonTaskProxy；`cli/main.py` daemon 分支 `--queues`（choices+默认全量，删 `--queue`）；启动 reset 逐 site domain 过滤修复。
+  - 验收：TDD；`test_daemon_task.py` 重写为 router 语义；双队列（1688 contact + mic contact）装配单测。
+- [ ] **Step 3.2** SwapIP 两阶段（估 30min，依赖 3.1，状态 pending）
+  - 无头：未轮换→回写关本站 context→置 needs_relaunch→让出冷却→release item；有头 WaitHumanLogin 保留原地例外（注释更新）；懒建路径消费 needs_relaunch。
+  - 验收：单测覆盖两阶段状态流转（mock relaunch rotated=False）；策略冷却后 release→重领→attempts 熔断链路单测。
+- [ ] **Step 3.3** 双队列跨站冒烟（估 30min，依赖 3.2，状态 pending）
+  - `--workers 1` 直连临时库跑 `daemon --queues crawl_1688_contact,crawl_mic_contact`：人为注货两站店铺，日志验证同 worker 在一站冷却期认领另一站 item。
+  - 验收：日志证据落 plan 目录（report 文件随跑随写）。
+
+## P3-4 madeinchina 队列接入
+
+**准入**：P3-3 完成。**完成标准**：`crawl_mic_shop` feeder 链路（播种→discover→类目页→链式续喂）单测+冒烟。
+
+- [ ] **Step 4.1** contact 接入 + mic shop 任务拆分（估 40min，依赖 3.1，状态 pending）
+  - `crawl_mic_contact` 入注册表（topup 复用现函数，`.cn.made-in-china.com`）；mic contact prepare 的 reset 副作用确认/修 domain 过滤。
+  - mic shop task 拆出「单类目页处理」（payload 驱动，认朗读 next_page，on_success advance/exhausted + 链式续喂 + 失败补插）；discover item 执行 = 现 cold_start 提取逻辑。
+  - 验收：TDD 单测（链式续喂、ZERO_NEW_LIMIT 保护、失败补插、幂等播种）。
+- [ ] **Step 4.2** mic shop feeder 装配 + 冒烟（估 30min，依赖 4.1，状态 pending）
+  - `iter_active_categories`（mic 拼音 slug 过滤沿用）；启动播种（幂等）；注册表加 `crawl_mic_shop`。
+  - 验收：冒烟——临时库播种后 daemon 消费类目页 item，category_progress 推进、shops 落库；日志落 plan 目录。
+
+## P3-5 1688 shop/company feeder 接入
+
+**准入**：P3-4 完成（feeder 模式已跑通）。**完成标准**：两条 1688 内容队列接入，冒烟验证播种与链式续喂。
+
+- [ ] **Step 5.1** 1688 shop/company 任务拆分（估 40min，依赖 4.2，状态 pending）
+  - 同 §4.1 模式拆 offer_search/company_search 单页处理；company 进度键 `company:` 前缀沿用；discover = 首页类目提取 + mtop 握手。
+  - 验收：TDD 单测（前缀隔离、续喂、补插）。
+- [ ] **Step 5.2** 注册表装配 + 冒烟（估 30min，依赖 5.1，状态 pending）
+  - `iter_active_categories` 1688 变体（无拼音过滤、支持 company: 前缀）；两条队列入注册表；启动播种。
+  - 验收：冒烟（直连滑块墙环境噪声下取结构证据：播种→认领→progress 读写路径走通）；旧 CLI `1688 shop --workers 1` 等价性确认。
+
+## P3-6 端到端验收 + 终审
+
+**准入**：P3-5 完成。**完成标准**：SPEC §7 验收标准逐条取证；全分支终审 MERGE READY。
+
+- [ ] **Step 6.1** 跨站填充端到端冒烟（估 40min，依赖 5.2，状态 pending）
+  - `--workers 1` 全量 5 队列（或按环境可用子集）临时库：取证 ① 同 worker 跨站填充日志（双向）② ip_req 簿记不超各站预算 ③ 无重复认领。
+  - 证据（命令+日志摘录+计数）落 plan 目录 report。
+- [ ] **Step 6.2** 全量回归 + 终审（估 30min，依赖 6.1，状态 pending）
+  - 全量测试；SPEC §7 逐条勾选；README/AGENTS.md 涉及段落同步（daemon 队列清单、互斥约定）；scheduler-architecture.md §10 P3 行标完成 + 归档本目录到 docs/archive/。
+  - 验收：终审报告 MERGE READY 后呈用户合并。
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/SPEC.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/SPEC.md
new file mode 100644
index 0000000..a2bcbcc
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/SPEC.md
@@ -0,0 +1,201 @@
+# SPEC — P3 多队列跨站填充（fetcher 调度器改造第三阶段）
+
+> 版本：v1 · 2026-08-08 · 待评审
+> 设计基准：docs/scheduler-architecture.md（§4 核心概念 / §5 调度循环 / §6 冷却策略表 / §10 落地路线 P3 行）
+> 前置：P0（daemon 骨架）、P1（冷却迁移）、P2（identity 分桶）均已合并 main。
+
+## 1. 背景与目标
+
+P0~P2 完成后，daemon 仍是**单队列单站点**（`crawl_1688_contact`），`_cooldown` chokepoint 仍是「登记 + 原地等待」——worker 线程在样本间隔/批休/风控冷却期间抱着通道和浏览器空睡，IP 利用率问题没有实际解开。
+
+P3 目标（对齐基准文档 §10 P3 行验收）：
+
+1. daemon 升级为**多队列多站点**：5 条浏览器队列统一注册、统一消费。
+2. 消费者按「资源满足 ∧ 该站点冷却已到期」跨队列取项；某站点冷却期间，同一通道自动转去执行其他站点的工作项。
+3. BrowserContext 多站点隔离（自 P2 移入）：一消费者一浏览器进程，每站点一个独立 context/storage state。
+4. **验收**：同通道 madeinchina 冷却期间执行 1688 工作项（日志可证），两边各自请求预算不超标；全量测试绿。
+
+## 2. 范围与非目标
+
+### 范围
+
+- 调度内核：`cooldown_until` 改建（reason→site）、`_cooldown` 让出语义、`claim_next_eligible`、work_items 挂起/重试语义。
+- 队列路由：队列注册表（queue → site/task/topup/policy），`QueueRouter` 取代 `DaemonTaskProxy`。
+- 浏览器层：`Session`/`BrowserManager` 多 context 改造；种子身份池认领粒度改 (consumer, site)。
+- SwapIP 两阶段拆分（解开 P1 留下的例外）。
+- 队列接入：madeinchina contact / madeinchina shop / 1688 shop / 1688 company（1688 contact 已在）。
+- CloakBrowser 多 context 席位实测（Phase 0 spike，是浏览器层动工的准入条件）。
+- daemon CLI 与启动互斥修复（`reset_in_progress` 无 domain 过滤的现存坑）。
+
+### 非目标（P3 不做）
+
+- yiwugo / taobao 队列接入（纯内存队列 + JSONL 落盘，无 DB 进度，接入价值低）。
+- HttpConsumer / LocalExecutor / wa_check / facebook API（基准文档 P4+）。
+- 平台侧集成（runner 批次提交、`start.sh` 拉 daemon、前端看板）——P4。
+- work_items 的 `batch_id` / `stopped` 态 / 批次优先级——P4 平台切换时启用。
+- 多 dispatcher 分布式、asyncio 重写、pub/sub 分派、优先级抢占（基准文档 §11 已裁定）。
+- 长阻塞工作项期间消费者对其他队列不可用——v1 接受（基准文档 §5 已裁定）。
+- 有头模式 SwapIP 的 `WaitHumanLogin` 人工登录轮询：保留原地等待（见 §3.5 裁定）。
+
+## 3. 设计要点
+
+### 3.1 队列注册表与 QueueRouter
+
+新增 `fetcher/fetcher/control/queue_router.py`，`QueueRouter` 取代 `DaemonTaskProxy`（P0 组件，仅 daemon 使用、无平台依赖，直接替换不保留兼容）。注册表为启动期静态装配：
+
+```python
+@dataclass
+class QueueSpec:
+    queue: str            # "crawl_1688_contact" / "crawl_mic_contact" / ...
+    site: str             # 注册名 "1688" / "madeinchina"
+    task: Task            # 该队列工作项的执行流水线（站点插件 make_task 产出）
+    topup: Callable[[ShopDB, int], int] | None   # 补货函数；feeder 类队列为 None
+    domain_suffix: str    # contact 类 topup 用；启动 reset 用
+```
+
+5 条队列（名为最终定名，CLI/日志/DB 一致使用）：
+
+| queue | site | 工作项 | 喂养方式 |
+|---|---|---|---|
+| `crawl_1688_contact` | 1688 | 一个店铺 contact | `topup_contact_work_items`（现状，`.1688.com`） |
+| `crawl_mic_contact` | madeinchina | 一个店铺 contact | 同函数复用（`.cn.made-in-china.com`，已参数化） |
+| `crawl_1688_shop` | 1688 | 一个类目一页 offer_search | feeder（§3.7） |
+| `crawl_1688_company` | 1688 | 一个关键词一页 company_search | feeder（进度键 `company:` 前缀，现状沿用） |
+| `crawl_mic_shop` | madeinchina | 一个类目一页 market | feeder（§3.7） |
+
+`QueueRouter` 实现 Task 协议的队列侧职责：
+
+- `acquire_item(ctx)`：三段式沿用 P0 结构——`claim_next_eligible` → 各队列 topup → condvar 挂起；认领成功后把 `(item_id, queue)` 记入 `ctx.state`，并将 `ctx` 绑定到该 item 的站点（见 §3.3 的「当前站点」）。
+- `on_success`/`on_giveup`：路由到 item 所属队列的 `task`，然后 `finish_work_item` / `release_work_item`（§3.4）。
+- 检测与策略按 item.site 切换：Engine 启动时为注册表涉及的每个 site 构建 `Policy`（含该站点 `policy_overrides`）；处理 item 时 `ctx.site`、`ctx.policy` 绑定到该 item 的站点插件与 Policy。**一个 item 的处理全程站点不变**。
+
+不变式（结构保证，基准文档 §4.3）：一消费者一线程、同一时刻只处理一个工作项；一通道同一时刻只属于一个消费者 → 同一 (通道, 站点) 永不并发。
+
+### 3.2 消费者资格与 claim_next_eligible
+
+```python
+def eligible_queues(consumer, now) -> list[str]:
+    return [q.queue for q in registry
+            if q.requires <= consumer.resources           # P3 全部为 {"channel","browser"}
+            and now >= consumer.cooldown_until.get(q.site, 0)]
+```
+
+新增 `ShopDB.claim_next_eligible(queues, consumer_id)`：`BEGIN IMMEDIATE` 内 `WHERE status='pending' AND queue IN (...) ORDER BY id LIMIT 1` + 置 claimed，返回 `{"id","queue","site","payload"}`（payload 解码后字典）。跨队列只做 FIFO（按 id），不做优先级（基准文档 §11）。
+
+挂起等待：condvar `wait(timeout=min(最近冷却到期剩余, 30s))`——30s 自醒兜底沿用 P0（外部 INSERT 无 notify，最坏 30s 发现）；冷却到期靠 timeout 自然醒来。board 状态行显示「等货/等冷却 mm:ss」。
+
+### 3.3 冷却表改建与 chokepoint 让出
+
+- `WorkerContext.cooldown_until` 键从 **reason 改为 site**（`dict[site, 到期时刻]`，仍为每 worker 内存）。P1 注释中「P3 调度器的查询接口」即本次落地；P1 只写不读，无存量读取者，改建安全。
+- 「当前站点」：router 在 `acquire_item` 成功时写 `ctx.state["active_site"]`；`_cooldown` 写 `cooldown_until[active_site]`。reason 参数保留，仅用于日志/board 展示。
+- `_cooldown` 语义二分：
+  - **让出型**（样本间隔、批休、周期长休、策略冷却 block_rest 等）：登记 `cooldown_until[site] = now + seconds` 后**立即返回不等待**；loop 继续到下一轮 `acquire_item`，claim 过滤使该站点队列对本消费者不可见 → 自然转取其他队列。无货可取时 condvar 挂起（§3.2）。
+  - **原地型**（launch 重试退避 `loop.py` launch_backoff）：在 item 处理装配中途、秒级、换队列无意义，保留 `ctx.wait` 原地等待。SPEC 裁定：原地型仅此一处，新增等待一律让出型。
+- 中断残留：`cooldown_until` 纯内存，daemon 重启即清空（与现状一致——现状冷却也在内存）；残留过期值按「过期即无效」消费。
+- 簿记键无需改动：P2 已把 ip_req/ip_stats/ip_events 按 `site:ip` 分桶。
+
+### 3.4 work_items 挂起/重试语义
+
+现状四态 `pending/claimed/done/failed` 够用，**不加新状态**；「挂起」= 释放回 pending。新增：
+
+- 列：`attempts INTEGER NOT NULL DEFAULT 0`（`db.migrate()` 幂等 ALTER，PRAGMA table_info 探测模式）。
+- `ShopDB.release_work_item(item_id, max_attempts=3) -> str`：`BEGIN IMMEDIATE` 内 attempts+1、清 claimed_by/claimed_at；`attempts >= max_attempts` 时置 `failed`（写 finished_at/result_json="attempts exhausted"），否则置 `pending`。返回终态供路由层记日志。
+- 语义裁定：
+  - 策略给出让出型冷却但 item 未完成（如 block_rest 后需重试）→ release（同 item 冷却后重试，attempts 计数熔断防无限循环）。
+  - 策略链在 item 重领后从头开始（attempts 不跨认领保留策略链进度）——全局限速寄托于既有 (site,IP) 风控簿记与请求预算，不以单 item 链长为闸。
+  - category 类 item 最终失败（attempts 耗尽）→ 路由层补插一条同 payload 新 item（attempts=0），保证类目链不死（§3.7）。
+
+### 3.5 SwapIP 两阶段拆分
+
+现状（P1 例外）：`SwapIPStrategy.run` 第一次 relaunch 未轮换 → 原地等 600~900s → 第二次 relaunch，等待夹在两次 relaunch 之间。
+
+改造（无头模式）：
+
+1. relaunch 未轮换 → 回写本站 Cookie、关闭本站 context（浏览器进程保留，其他站点 context 不受影响）、登记 `session.state["needs_relaunch"][site]=True`；
+2. 输出让出型冷却 `uniform(block_rest_min, block_rest_max)`（青果 30 分钟轮换窗，参数沿用现状）；
+3. 当前 item release 回 pending（§3.4）；
+4. 该站点冷却到期后再次被认领时，context 懒建路径发现 `needs_relaunch` → 走完整 relaunch（全部 context 回写关闭 → 新进程绑轮换后新 IP → 懒建本站 context）。「第二次 relaunch」由此并入正常 launch 路径，无独立第二阶段代码。
+
+裁定：
+
+- **有头模式例外保留**：`WaitHumanLogin` 人工登录轮询需要活 page，维持原地等待不拆分（有头=人工辅助场景，利用率不是目标）；代码注释同步更新「P3 已拆无头路径」。
+- 等待期间浏览器进程保留供其他站点使用（席位不空占），这是相对「关浏览器等轮换」方案的明确选择。
+
+### 3.6 Session/BrowserManager 多 context 改造
+
+**契约假设（动工前 spike 验证，见 §4 C1）**：CloakBrowser 席位按浏览器进程租约，一进程 N 个 context 只占 1 席。包源码证据：`license.py:368 get_active_session_count` + 退出码 76（session limit）；`launch()` 返回原生 Playwright `Browser`，`new_context()` 是进程内纯 Playwright API，服务端不可见。指纹/代理/WebRTC/时区均为**进程级 CLI 旗标**（`browser.py` `build_args`/`launch_context` 注释），同进程多 context 共享同指纹同出口——与「一消费者一通道一 IP」模型天然兼容（P2 已按 `site:ip` 分桶 Cookie/簿记）。
+
+改造点：
+
+- `Session` 从「单 browser+单 context+单 page」改为：持有 `browser`、`channel`、`req_proxies` + `views: dict[site, SiteView]`；`SiteView = {context, page, identity(=site:ip), seed_kit}`。
+- **懒建**：router 绑定 item 站点时 `session.ensure_site(site)` 无 view 则创建（`browser.new_context(locale="zh-CN")` → 按 `site:ip` 装载 Cookie（空库播种种子/白板，沿用现状分支）→ new_page → warmup/冷启动标记）。`ctx.page`/`session.page` 路由到当前活动 site 的 view。
+- **关闭语义**：`Session.close` 现状直接 `browser.close()`；改为两层——`close_site(site)`（回写本站 Cookie、关 context）与 `close()`（全部 site 回写后关 browser，daemon 退出/relaunch 用）。
+- **relaunch**：全部 view 回写 Cookie → `browser.close()` → `launch()` 新进程 → 清空 views（懒重建）。`check_ip_fresh`/指纹种子仍按裸 IP（`bare_identity`），不变。
+- **种子身份池**：`_alloc_seed_kits` 认领粒度从「每 worker 一份」改为「每 (worker, site) 一份」——`load_seed_kits(domain=站点cookie域)` 逐站点加载后按下标分配；种子 Cookie 播种落 `site:ip` 键（现状已是 identity 键，零改动）。`SeedBurnTracker` 键为 identity，天然分桶，零改动。
+- 单 context 假设的消费方迁移（冲突扫描 §6 全清单）：`session.ctx` property、`browser_ops.RelaunchBrowser`、`WaitHumanVerify` 等取 `ctx.page` 的策略/原子——全部经「活动 site view」路由，禁止直接持有 page 引用跨 item 复用。
+
+### 3.7 shop 类任务源队列适配（feeder 模式）
+
+难点（侦察结论）：shop/company 任务源是「进程内 CategoryPool/KeywordPool + cold_start 探索式发现 + category_progress 页码表」，任务项自带 page_no。译为 work_items：
+
+- **类目页工作项**：payload `{"kind":"category","keyword":..,"name":..}`（mic 另带 `"fmt":"market"|"plain"`）。**page_no 不进 payload**——认领时读 `category_progress.next_page`（单一事实来源沿用现状，多消费者不会同页撞车：同类目下一页 item 只在上一页成功后插入）。
+- **发现工作项**：payload `{"kind":"discover"}`。执行 = 现状 `cold_start` 的类目提取（1688 首页 offer_search 关键词 + mtop 握手；mic 首页+市场导航页），新类目（不在 category_progress 且无同 keyword pending item）逐条 INSERT category item。
+- **启动播种**：daemon 启动时每个 feeder 队列：① 从 `category_progress` 读未采完类目（新增统一查询 `iter_active_categories(prefix="")`，mic 沿用纯拼音 slug 过滤、company 用 `company:` 前缀）逐条插 category item；② 插一条 discover item。队列已有 pending 同类 item 时跳过（幂等，重启不重复播种）。
+- **链式续喂**：category item `on_success` → `advance_category_page`/`mark_category_exhausted`（含 mic 的 ZERO_NEW_LIMIT=2 保护，原逻辑迁移）→ 未采完则 INSERT 下一页 item。最终失败按 §3.4 补插同 payload 新 item。
+- **发现节奏**：v1 仅启动时播种 + discover item 执行一次；不做周期再发现（类目集合极少变化，重启 daemon 即触发）。裁定记录于此，后续需要再加。
+- 进程内 CategoryPool/KeywordPool/ACQUIRE_WAIT_MAX 空转逻辑随接入**退役**（旧 CLI 路径同步改造见 §3.9 裁定）。
+
+### 3.8 daemon CLI 与互斥修复
+
+- `python -m fetcher daemon`：`--queue`（单值，P0 限制）替换为 `--queues`，nargs 多值 + choices=注册表键，**默认全部 5 条**；help 文案注明默认全量。`--queue` 删除（P0 仅手动使用、无平台调用方，不留 deprecated 别名）。
+- 启动修复现存坑：`cli/main.py` daemon 分支的 `reset_in_progress()` 无 domain 过滤会重置所有站点 → 改为按注册表逐 site 调 `reset_in_progress(domain_suffix)`；`reset_claimed_work_items()` 全量保留（daemon 唯一写者）。
+- 旧 CLI 站点子命令（`1688 shop` 等）保留可用（基准文档「P0~P3 期间旧 CLI 保持可用」）；feeder 改造涉及的 task 类以「item 处理逻辑可独立于内存池调用」为准重构，旧 CLI 的 acquire 路径改为从对应 work_items 队列认领（与 daemon 同一代码路径，避免双份流水线）。互斥约定不变：同站 daemon 与旧 CLI 不同时跑（README 已有说明，更新队列清单）。
+
+## 4. 契约与行为后果（外部依赖假设表）
+
+| # | 假设 | 依据 | 验证方式 |
+|---|---|---|---|
+| C1 | CloakBrowser 一进程多 context 只占 1 席位 | **已实测验证**（2026-08-08 spike，报告 `spike-cloakbrowser-multicontext.md`）：`get_active_session_count` 序列 n0=0 → launch n1=1（+1）→ new_context n2=1（不变）→ 第 2 context 内 goto n3=1（不变）→ close n4=0（-1），delta=1/0/-1 逐条命中；叠加包源码证据（`license.py:368` 会话计数 API、exit 76=session limit、`new_context` 为进程内 API） | **Phase 0 spike 已完成**（2026-08-08，P3-0 Step 0.1 验收通过；报告落本目录，结论已验证，P3-2 浏览器层可动工） |
+| C2 | Playwright 多 context 间 storage state（Cookie/本地存储）完全隔离 | Playwright 官方文档（BrowserContext 独立存储契约） | 单测：同 browser 两 context 互不可见对方 Cookie |
+| C3 | 同进程多 context 共享进程级指纹/代理旗标 | cloakbrowser `browser.py` build_args/launch_context 注释（已验证源码阅读） | 无需额外验证；设计已按「同指纹同出口」前提展开 |
+| C4 | 青果隧道 30 分钟轮换窗 | 现状 SwapIP 策略注释与参数（生产经验） | 沿用现状参数，不重新标定 |
+| C5 | `BEGIN IMMEDIATE` 原子认领在多消费者并发下无重复认领 | P0 已验证（test_work_items.py）+ SQLite WAL 语义 | 沿用既有测试模式补并发单测 |
+
+## 5. 职责分配（初始化 + 变更路径）
+
+| 状态 | 初始化 | 谁写 | 谁读 |
+|---|---|---|---|
+| `cooldown_until[site]`（每 worker 内存） | 空 dict | 唯一写入者：`_cooldown` chokepoint（让出型登记）；重启清空 | `eligible_queues`（claim 过滤）；board 状态行 |
+| `ctx.state["active_site"/"daemon_work_item_id"/"queue"]` | router.acquire_item 成功时写 | router | `_cooldown`（取 site）、router.on_success/on_giveup（路由+回写） |
+| `work_items.attempts` | 0（迁移默认） | `release_work_item`（+1/判失败） | release 内部熔断 |
+| `work_items` 行（INSERT） | 启动播种 / topup / 链式续喂 / discover 产出 / 失败补插 | 上述各路径经 ShopDB 短事务 | claim_next_eligible |
+| `Session.views[site]` | `ensure_site` 懒建 | BrowserManager（建/关/relaunch 清空） | loop/原子经 `ctx.page`（活动 view） |
+| `session.state["needs_relaunch"]` | 空 | SwapIP 两阶段（置位）/ relaunch 完成（清除） | context 懒建路径 |
+| `category_progress` | 现状存量 | 链式续喂（advance/exhausted） | 启动播种、category item 认领读 next_page |
+
+## 6. 冲突扫描与裁定
+
+1. **单 context 假设消费方全清单**（均有对应 Step 迁移）：`core/session.py` Session 定义/`ctx` property/`close`；`net/browser.py` launch/relaunch/warmup/save_cookies/check_ip_fresh；`atoms/browser_ops.py` RelaunchBrowser；`strategy/strategies.py` WaitHumanLogin/WaitHumanVerify/SwapIP；`control/loop.py` `_launch_with_retry`/`_relaunch`/`_ensure_fresh_ip`/`_check_budget`/`_cleanup`。迁移原则：一律经「活动 site view」路由。
+2. **`cooldown_until` 键语义变更**：P1 只写不读、无存量消费方——安全改建；P1 留的注释（「reason 键」）同步更新。
+3. **DaemonTaskProxy 替换**：消费方仅 `cli/main.py` daemon 分支 + `tests/test_daemon_task.py`；测试重写为 router 语义。`test_work_items.py` 保留并扩 attempts/release/claim_next_eligible 用例。
+4. **`reset_in_progress` 无过滤坑**：daemon 启动改逐 site 过滤调用；madeinchina contact `prepare()` 的 reset 副作用确认带后缀过滤，不带则一并修。
+5. **1688 shop `prepare()` 不从进度库播种**（与 mic 差异）：feeder 启动播种统一走 `iter_active_categories`，1688 shop/company 的进度恢复改由播种保证，不再依赖「首页重新提取同名类目命中 next_page」的隐式路径。
+6. **策略链重领重置**（§3.4）：与现状「单 item 会话内链式升级」语义不同，裁定接受——全局限速在 (site,IP) 簿记与预算。
+7. **有头 WaitHumanLogin 原地等待保留**（§3.5）：与「新增等待一律让出型」原则的例外，仅 SwapIP 有头路径 + launch 退避两处。
+8. **引擎装配**：`Engine` 目前单 site 插件 + 单 Policy；daemon 分支改为注册表装配（每 site 一 Policy），站点 CLI 分支不受影响。
+9. **平台零影响**：平台不读写 work_items（侦察确认零命中），attempts 列迁移对平台透明；identity 格式不变。
+10. **席位预算**：solo=5 进程上限不变；多 context 不增加席位消耗（C1 实测背书后成立）。冒烟环境纪律：本机常有活爬虫占 2 席，测试 launch 控制在 +1 席以内。
+
+## 7. 验收标准
+
+- [ ] 端到端证据：单通道 daemon（`--workers 1`）日志显示 madeinchina 冷却登记后、到期前，同 worker 认领并执行 1688 工作项；反向同样成立。
+- [ ] 预算合规：日志中 ip_req 簿记显示同 (site,IP) 请求数不超各 task 的 `ip_request_budget`（mic shop=60、mic contact=80、1688 shop/company=12）。
+- [ ] 等价性：各队列产出（shops/contacts 写入、category_progress 推进）与旧 CLI 同路径代码一致；claim 无重复认领（并发单测 + 冒烟日志无重域名）。
+- [ ] C1 实测报告落 plan 目录并回填 §4。
+- [ ] 全量测试绿（现基线 309 passed + 新增）。
+
+## 8. 风险与回滚
+
+- **风险：C1 实测证伪**（席位按 context 计）→ 多 context 方案作废，降级为「一消费者一浏览器单 context、跨站填充仍成立」（多队列/冷却让出/feeder 不受影响，仅每 consumer 席位消耗不变但跨站串行复用同一进程单 context，需每次切站重建 context 装载本站 Cookie）。Phase 0 先行就是为把此风险拦在浏览器层动工前。
+- **风险：类目链喂养死锁/饿死**（全部 category item 失败、discover 已消费）→ 启动播种幂等，重启即恢复；链式补插兜底。
+- **回滚**：P3 全程旧 CLI 路径可用；daemon 为手动拉起，main 上按 Phase 合并，任一 Phase 可独立 revert。
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/ledger.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/ledger.md
new file mode 100644
index 0000000..81ccf8f
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/ledger.md
@@ -0,0 +1,31 @@
+# SDD ledger — plan: docs/feat_2026-08-08_fetcher-multiqueue-p3/PLAN.md
+
+- 分支：feat/multiqueue-p3（base main b127c84）
+- 环境记录：子 Agent 经 `pi -p --provider deepseek --model <model>` 独立进程派发（经济=deepseek-v4-flash，标准=deepseek-v4-pro，终审=deepseek-v4-pro）；会话 --session-id 固定便于修复轮 resume；制品全部文件交接（plan 目录）。
+- 仓库注意：工作区有另一功能（apify-provider-pairing-login）的未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），**P3 全程不碰不提交**，commit 一律 scoped add。
+
+## 主 Agent 裁定（冲突扫描，2026-08-08，开工前一次性裁决）
+
+1. **Step 1.3 让出型改造范围**：PLAN 文本同时写「策略冷却登记即返回」与「策略冷却后 item 未完成的路径暂保留现状」——若策略冷却（block_rest 等）登记即返回，`_process_item` 策略链会立即重试同一 item 形成无限快速循环。裁定：Step 1.3 只把 loop 三处节奏冷却（sample_interval / batch_rest / periodic_rest）改为让出型（登记 site 键后立即返回，等待转移到 acquire_item 的 condvar timeout=min(最近冷却到期剩余, 30s)）；策略冷却 + launch_backoff 保持原地等待（策略冷却待 P3-3 router 接 release 后改让出，符合 SPEC §3.4 落地时序）。
+2. **Step 1.2 前向依赖**：`eligible_queues` 的 registry 正式定义在 Step 3.1。裁定：Step 1.2 以纯函数 + duck-typed registry 实现（SimpleNamespace 模拟 QueueSpec 单测），Step 3.1 建真实注册表复用。
+3. **P3-1 单队列等价性口径**：让出型冷却后等待从 loop 内移到 acquire_item condvar，总节奏等价；状态行展示从「样本间隔 Ns」变为「等货/等冷却」。冒烟按节奏等价判定，不按展示文案。
+4. **P3-3 loop 多 site 绑定**（SPEC §6.8）：CrawlLoop 的 `SceneInspector.for_site(ctx.site)`（loop.py:81）与 `self.policy` 在 __init__ 固定；P3-3 需 per-item site 绑定（router acquire 后绑 ctx.site/ctx.policy，loop 按 active_site 切换 inspector/policy）。Step 3.1 brief 必须写明。
+5. **`_cooldown` 键语义变更**：test_cooldown.py 5 处断言 reason 键（:217/:232/:267/:351/:379），改 site 键须同步更新；原地型（launch_backoff/策略冷却）不写 site 键（等待期间消费者本就不可用）。
+6. **`Engine._alloc_seed_kits` daemon/CLI 共用**：P3-2 改 (worker,site) 粒度只影响 daemon 路径，CLI 单站点保持现状。
+7. **`Session.close` 双层语义的 Cookie 域过滤**：IdentityStore.domain 单站点属性，save_from_context 按 store.domain 子串过滤；多 context 后 close_site(site)/save_cookies 需按各 site 的 cookie_domain 过滤。P3-2 核心设计点。
+
+## Step 进度
+
+### P3-0（spike，C1 验证）
+
+- Step 0.1: complete (commit bdef641, review clean)
+  - 实现：脚本 /tmp/spike_cloak_multicontext.py 实测 get_active_session_count 序列；主 Agent 独立复跑确认（n0=0→n1=1→n2=1→n3=1→n4=0，delta=1/0/-1 逐条命中）；报告 docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md
+  - **C1 已验证**（SPEC §4 C1 已回填）；P3-2 准入达成，浏览器层可动工
+  - review 零 Critical/Important；3 Minor（n0=0 与 brief 环境假设出入——已诚实记录且不影响结论；表格冗余；报告未附终端原始输出——主 Agent 已亲跑脚本验证一致）→ 记 ledger，不进修复循环
+  - Step 0.1: minor (deferred): 同上 3 条 Minor
+
+### P3-1（调度内核）
+
+- Step 1.1: 修复轮 1 进行中（commit c87c616, review 2 Important）
+  - 实现：db.py _migrate 补 attempts 幂等迁移 + release_work_item + claim_next_eligible（TDD 9 新用例，全量 318 passed）；现有 work_items 方法未动
+  - review：spec 合规 ✅，2 Important（① claim_next_eligible json.loads 在 try 外/commit 后——payload_json 非法时行已 claimed 却拿不到返回，永久泄漏；② SELECT * 脆弱性→显式列名）+ 2 Minor（rowcount=0 路径 commit 一致性、返回位置不对称）
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-review.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-review.md
new file mode 100644
index 0000000..9c12961
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-review.md
@@ -0,0 +1,158 @@
+# Review Package — Step 0.1 (P3-0 spike)
+
+## Commits
+bdef641 P3-0 Step 0.1: CloakBrowser 多 context 席位计数实测 — C1 已验证
+
+## Stat
+ .../spike-cloakbrowser-multicontext.md             | 77 ++++++++++++++++++++++
+ .../task-0.1-brief.md                              | 58 ++++++++++++++++
+ 2 files changed, 135 insertions(+)
+
+## Diff
+diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md
+new file mode 100644
+index 0000000..8cd2ab6
+--- /dev/null
++++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md
+@@ -0,0 +1,77 @@
++# Spike Report — CloakBrowser 多 context 席位计数实测
++
++> P3-0 Step 0.1 | 执行时间: 2026-08-13
++> 来源: SPEC §4 C1 / PLAN.md P3-0 Step 0.1
++
++## 目标
++
++实测 CloakBrowser 会话席位按「浏览器二进制进程」还是按「BrowserContext」计数。
++结论直接决定 P3-2 浏览器层「一进程多 context 只占 1 席」方案是否成立。
++
++## 方法
++
++脚本 `/tmp/spike_cloak_multicontext.py`，严格按以下序列执行：
++
++1. **n0** — baseline：读取当前 `get_active_session_count(key)`
++2. **n1** — headless 直连 launch CloakBrowser（无代理），读计数
++3. **n2** — `browser.new_context(locale="zh-CN")`，读计数
++4. **n3** — `ctx2.new_page()` → `page.goto("about:blank")`，读计数
++5. **n4** — `browser.close()`，读计数
++
++每次计数之间等待 3 秒（服务端租约注册/释放有延迟）。
++
++Launch 参数：`headless=True, license_key=<key>, humanize=True, locale="zh-CN", timezone="Asia/Shanghai", stealth_args=False`（无代理、无 geoip）。
++
++## 原始结果
++
++| 步骤 | 操作 | 实测值 | 预期值 | 判定 |
++|------|------|--------|--------|------|
++| n0 | baseline | **0** | — | — |
++| n1 | launch | **1** | n0 + 1 = 1 | ✓ |
++| n2 | new_context | **1** | n1 = 1 | ✓ |
++| n3 | ctx2.new_page() + goto("about:blank") | **1** | n2 = 1 | ✓ |
++| n4 | browser.close() | **0** | n0 = 0 | ✓ |
++
++### 第二个 context 可用性
++
++- `ctx2.new_page()` — 成功
++- `page.goto("about:blank")` — 成功
++- context 完全可用，不受席位计数影响
++
++## 预期 vs 实测（逐条）
++
++| 断言 | 实测 | 预期 | 结果 |
++|------|------|------|------|
++| n1 = n0 + 1 | 1 | 1 | ✓ |
++| n2 = n1（多 context 不占新席位） | 1 | 1 | ✓ |
++| n3 = n2（goto 不占新席位） | 1 | 1 | ✓ |
++| n4 = n0（关闭释放席位） | 0 | 0 | ✓ |
++
++## 结论
++
++**C1「一进程多 context 只占 1 席位」= 已验证。**
++
++证据：launch 后席位 +1（n0→n1），创建第二个 BrowserContext 并实际使用（new_page + goto）后计数未变（n2=n3=n1=1），关闭浏览器后席位释放回基线（n4=n0=0）。CloakBrowser 会话席位以浏览器二进制进程为粒度计数，同一进程内的多个 BrowserContext 不额外占用席位。
++
++## 环境说明
++
++- 时间：2026-08-13（北京时间）
++- Python：系统 python3
++- 活爬虫占席情况：n0=0（本次执行时无活爬虫运行）
++- 套餐类型：solo（5 席上限）
++- 本次占用：最多 1 席（已确认释放）
++
++## 复现命令
++
++```bash
++cd /Volumes/DataDrive/proj/public/1699
++python3 /tmp/spike_cloak_multicontext.py
++```
++
++脚本内容见 `/tmp/spike_cloak_multicontext.py`（不入库）。
++
++## 对后续的影响
++
++P3-2 浏览器层「一进程多 context 只占 1 席」方案可安全推进。方案核心逻辑：
++一个 CloakBrowser 进程内可创建多个 BrowserContext，各自绑定不同的 site+identity，
++只占用 1 个会话席位，从而在有限席位下实现多队列跨站填充。
+diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-brief.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-brief.md
+new file mode 100644
+index 0000000..5bdd3d1
+--- /dev/null
++++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-brief.md
+@@ -0,0 +1,58 @@
++# Task 0.1 Brief — CloakBrowser 多 context 席位计数实测（P3-0 spike）
++
++> 来源：PLAN.md P3-0 Step 0.1 全文 + SPEC §4 C1。本文件是本次任务的唯一需求来源。
++
++## 目标
++
++实测 CloakBrowser 会话席位按「浏览器二进制进程」还是按「BrowserContext」计数（SPEC §4 C1 假设）。
++结论直接决定 P3-2 浏览器层「一进程多 context 只占 1 席」方案是否成立，也是 P3-2 动工的硬准入。
++
++## 步骤（严格按顺序）
++
++写脚本 `/tmp/spike_cloak_multicontext.py`，完成以下序列，每次计数后打印一行原始值：
++
++1. **baseline**：`get_active_session_count(key)` 读当前会话数（记为 n0）
++2. **launch**：headless 直连 launch 一个 CloakBrowser（**不加 proxy**），记计数 n1 —— 预期 n1 = n0 + 1
++3. **第二个 context**：`browser.new_context(locale="zh-CN")`，记计数 n2 —— 预期 n2 = n1（多 context 不占新席位）
++4. **第二个 context 可用性**：`ctx2.new_page()` 然后 `page.goto("about:blank")` 成功，记计数 n3 —— 预期 n3 = n2
++5. **close**：`browser.close()`，记计数 n4 —— 预期 n4 = n0
++
++若任意预期不符：把实测值与预期逐条记录（这是证伪 C1 的证据，同样写进报告，不要隐瞒）。
++
++## 技术要点
++
++- license key：环境变量 `CLOAKBROWSER_LICENSE_KEY` 优先，兜底读 `/Volumes/DataDrive/proj/public/1699/.cache/config.json` 的 `CLOAKBROWSER_LICENSE_KEY` 字段（可参考 `fetcher/fetcher/net/browser.py` 的 `load_license_key`）
++- API（已读码确认的用法，见 `fetcher/fetcher/net/browser.py:210-260`）：
++  - `from cloakbrowser import launch as cloak_launch`
++  - `from cloakbrowser.license import get_active_session_count, validate_license`
++  - launch 参数：`headless=True, license_key=<key>, humanize=True, locale="zh-CN", timezone="Asia/Shanghai", stealth_args=False`（**不要传 proxy/geoip**）
++  - launch 可能抛 `SystemExit`（退出码 76 = session limit）——捕获并打印后退出
++- 每次 `get_active_session_count` 之间 sleep 2~3 秒（服务端租约注册/释放有延迟）
++
++## 环境纪律（铁律，违反即失败）
++
++- **全程 headless**（本机有活爬虫在跑，不得弹窗干扰）
++- **不开代理**（不占用青果隧道）；直连 launch
++- **只 +1 席**：本机活爬虫约占 2 席，solo 套餐共 5 席，本次最多占用 1 席；跑完必须 close，并确认计数回落（n4≈n0）
++- 不 import fetcher 包内需要浏览器装配的模块（避免副作用）；不修改任何产品代码
++
++## 产出
++
++报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md`，内容：
++
++1. 每次计数的原始值（n0..n4）+ 预期 vs 实测逐条
++2. 第二个 context 的 goto 结果
++3. 结论：C1「一进程多 context 只占 1 席位」= **已验证** / **证伪**（带证据）
++4. 环境说明（时间、如可观察的活爬虫占席情况）
++5. 复现命令（脚本内容或路径）
++
++## Git
++
++- 分支 `feat/multiqueue-p3` 已就绪，直接在其上工作
++- commit 范围：**只 add 报告文件** `docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md`（可连同本 brief 一起 add，它们同属 plan 目录）；工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），**绝不碰绝不带**，不要用 `git add -A`
++- 脚本放 /tmp 不入库
++- 若 commit 遇到 `.git/index.lock` 竞态（可能有另一个 Step 并行提交），sleep 几秒重试一次，仍失败就只保留文件不 commit，并在报告里注明
++
++## 验收
++
++报告含：① 每次计数原始值 ② 预期 vs 实测逐条 ③ 明确结论（已验证/证伪）④ 复现命令。
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-brief.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-brief.md
new file mode 100644
index 0000000..81c3cb1
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-brief.md
@@ -0,0 +1,92 @@
+# Task 1.1 Brief — work_items 扩展（attempts / release_work_item / claim_next_eligible）
+
+> 来源：PLAN.md P3-1 Step 1.1 全文 + SPEC §3.2/§3.4 + 主 Agent 冲突扫描裁定。本文件是本次任务的唯一需求来源。
+
+## 目标
+
+在 `fetcher/fetcher/db.py` 的 work_items 存储层新增三个能力（全部 TDD，先写失败测试再看它失败）：
+
+1. 幂等迁移：work_items 加 `attempts INTEGER NOT NULL DEFAULT 0` 列
+2. `release_work_item(item_id, max_attempts=3) -> str`：挂起/重试语义（SPEC §3.4）
+3. `claim_next_eligible(queues, consumer_id)`：跨队列原子认领（SPEC §3.2）
+
+## 规格
+
+### 1. attempts 列（幂等迁移）
+
+- `_migrate()` 追加：`PRAGMA table_info(work_items)` 探测缺列时 `ALTER TABLE work_items ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0`
+- 存量行 attempts=0（迁移默认）；重复执行幂等
+
+### 2. release_work_item
+
+```python
+def release_work_item(self, item_id: int, max_attempts: int = 3) -> str:
+    """工作项释放回 pending（attempts+1）；attempts 达上限置 failed。
+
+    单事务（BEGIN IMMEDIATE）：attempts = attempts + 1，清空
+    claimed_by/claimed_at；attempts >= max_attempts 时置 failed
+    （写 finished_at、result_json="attempts exhausted"），否则置
+    pending。返回终态字符串："pending" / "failed"。
+    """
+```
+
+语义细节：
+- 只对 **claimed** 状态的行生效（`WHERE id=? AND status='claimed'`）；rowcount=0（非 claimed/不存在）时返回 `"failed"`（调用方视为不可恢复，防御性兜底）——实现与测试都按此口径
+- `attempts >= max_attempts` 时终态 `failed`，`result_json` 存 `"attempts exhausted"`（JSON 字符串，`json.dumps("attempts exhausted")`）
+- 写 `finished_at`（北京时间字符串，`_now()`）
+- 失败路径 `rollback` 后 `raise`（与既有 `claim_pending_shops` 同模式）
+
+### 3. claim_next_eligible
+
+```python
+def claim_next_eligible(self, queues: list[str], consumer_id: str) -> dict | None:
+    """跨队列原子认领最老 pending 工作项（FIFO 按 id，无优先级）。
+
+    单事务（BEGIN IMMEDIATE）：WHERE status='pending' AND queue IN (...)
+    ORDER BY id LIMIT 1 → 置 claimed（claimed_by/claimed_at）。返回
+    {"id", "queue", "site", "payload"}（payload 为 json.loads 解码后
+    的字典）；无货返回 None。
+    """
+```
+
+- 入参是队列**集合**，返回四键 `{"id","queue","site","payload"}`（与现有 `claim_work_item` 的平铺 domain/name/url 形态不同——新调用方是 P3-3 的 QueueRouter）
+- 空 queues 列表返回 None（或视为无货，防御性处理即可）
+- 失败路径 `rollback` 后 `raise`
+
+**现有方法一律不动**：`claim_work_item` / `topup_contact_work_items` / `finish_work_item` / `reset_claimed_work_items` 保持原样（旧路径兼容，P3-3 才替换调用方）。
+
+## TDD 要求
+
+新增测试放在 `tests/test_work_items.py`（仿既有基建：unittest + tempfile + ShopDB + `_shop()` helper）或新增 `tests/test_work_items_release.py`。至少覆盖：
+
+1. **release 回 pending**：claim 后 release → status=pending、attempts=1、claimed_by/claimed_at 清空；再次 claim 可重领（且 attempts 保留）
+2. **attempts 耗尽置 failed**：release 三次（max_attempts=3）→ 第三次返回 "failed"、status=failed、result_json 含 "attempts exhausted"、finished_at 非空
+3. **release 终态返回值**：不足上限返回 "pending"，达上限返回 "failed"
+4. **release 非 claimed 防御**：对 pending/done 行调用返回 "failed" 且行内容不变
+5. **claim_next_eligible 队列集合过滤**：只认领 queues 内的；混有他队 pending 时不碰
+6. **FIFO**：多队混排按 id 最老先领（可含不同 queue 的交叉插入）
+7. **并发不重复认领**：顺序模拟两个消费者各领一次，不撞单（仿 `test_claim_no_double_claim` 模式）
+8. **attempts 列存在性**：新建库 PRAGMA table_info 断言列存在；存量行（手工构造）默认 0
+9. **空队列返回 None**
+
+## 上下文
+
+- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`（测试命令 `cd fetcher && python -m pytest tests -q`）
+- 既有模式参考（已读码）：`db.py:325` `claim_pending_shops`（BEGIN IMMEDIATE + rollback + raise）、`:429` `topup_contact_work_items`、`:465` `claim_work_item`、`:492` `finish_work_item`
+- `_migrate()` 在 `db.py:225`（探测模式：`cols = {r[1] for r in self.conn.execute("PRAGMA table_info(shops)")}`）；work_items DDL 在 `db.py:174-189`；`_now()` 返回北京时间字符串
+- payload_json 列存 JSON 字符串；claim_next_eligible 返回前 `json.loads`
+- 现有测试基线 309 passed（`cd fetcher && python -m pytest tests -q`）——commit 前全量确认不 regress
+- 写库一律短事务；ShopDB.__init__ 已设 `PRAGMA busy_timeout=30000`
+
+## Git
+
+- 分支 `feat/multiqueue-p3` 已就绪，直接在其上工作
+- commit 范围：**scoped add**——只 add `fetcher/fetcher/db.py` + `fetcher/tests/` 下本次改动文件；工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），**绝不碰绝不带**，不要用 `git add -A`
+- commit 标题风格：`feat(multiqueue-p3): <一句话>`
+- 若 commit 遇到 `.git/index.lock` 竞态（可能有另一个 Step 并行提交），sleep 几秒重试一次，仍失败就只保留工作区改动不 commit，并在 report 里注明
+
+## 验收
+
+1. TDD 证据：RED（实现前跑新测试，失败输出符合预期）→ GREEN（实现后通过）
+2. 全量 `cd fetcher && python -m pytest tests -q` 绿（309 + 新增）
+3. 报告（task-1.1-report.md）含：实现摘要、测试列表、TDD RED/GREEN 证据（命令+输出）、改动文件、自查发现
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-report.md
new file mode 100644
index 0000000..26d751a
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-report.md
@@ -0,0 +1,86 @@
+# Task 1.1 Report — work_items 扩展（attempts / release_work_item / claim_next_eligible）
+
+> 分支：`feat/multiqueue-p3` ｜ 状态：DONE ｜ TDD 全流程完成，全量 318 passed（基线 309 + 新增 9）
+
+## 实现摘要
+
+在 `fetcher/fetcher/db.py` 的 work_items 存储层新增三个能力（现有方法一律未动）：
+
+1. **attempts 列（幂等迁移）**：`_migrate()` 追加 work_items 列探测（`PRAGMA table_info(work_items)` 模式，与 shops/ip_events 既有探测一致），缺列时 `ALTER TABLE work_items ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0`。存量行默认 0；重开库幂等。
+2. **`release_work_item(item_id, max_attempts=3) -> str`**（SPEC §3.4 挂起/重试语义）：
+   - 单事务 `BEGIN IMMEDIATE`：`attempts = attempts + 1`，清空 `claimed_by/claimed_at`；
+   - `attempts >= max_attempts` → 置 `failed`（写 `finished_at`、`result_json = json.dumps("attempts exhausted")`），返回 `"failed"`；
+   - 否则置 `pending`，返回 `"pending"`；
+   - 只对 `status='claimed'` 行生效；rowcount=0（非 claimed/不存在）返回 `"failed"`（防御性兜底，行内容不变）；
+   - 异常路径 rollback 后 raise（与 `claim_pending_shops` 同模式）。
+3. **`claim_next_eligible(queues: list[str], consumer_id) -> dict | None`**（SPEC §3.2 跨队列原子认领）：
+   - 空 queues 直接返回 None；
+   - 单事务 `BEGIN IMMEDIATE`：`WHERE status='pending' AND queue IN (...)` `ORDER BY id LIMIT 1` → 置 claimed（claimed_by/claimed_at），FIFO 按 id、无优先级；
+   - 返回四键 `{"id","queue","site","payload"}`，payload 为 `json.loads` 解码字典；无货返回 None；异常 rollback + raise。
+
+## 测试列表（tests/test_work_items.py，新增 9 个 + 更新 1 个既有断言）
+
+| 测试 | 覆盖点 |
+|---|---|
+| `test_release_returns_to_pending` | 用例 1：claim→release 回 pending、attempts=1、认领信息清空；重领不重置 attempts |
+| `test_release_exhausts_attempts_to_failed` | 用例 2：release×3（默认 max_attempts=3）→ 第三次 failed、result_json="attempts exhausted"、finished_at 非空 |
+| `test_release_terminal_return_with_custom_max_attempts` | 用例 3：自定义 max_attempts=2，返回值 pending→failed |
+| `test_release_on_non_claimed_is_defensive_failed` | 用例 4：pending/done 行与不存在 id 均返回 failed 且行内容不变 |
+| `test_claim_next_eligible_filters_queues` | 用例 5：只认领 queues 内；他队 pending 不碰；返回四键结构 |
+| `test_claim_next_eligible_fifo_by_id_across_queues` | 用例 6：A/B 队交叉插入，严格按 id 升序认领 |
+| `test_claim_next_eligible_no_double_claim` | 用例 7：两个消费者各领一次不撞单（仿 test_claim_no_double_claim） |
+| `test_attempts_column_present_and_legacy_migration` | 用例 8：新建库含列；手工构造无 attempts 旧库 → 打开补列、存量行=0、重开幂等 |
+| `test_claim_next_eligible_empty_queues_returns_none` | 用例 9：空队列返回 None 且不碰任何行 |
+| `test_topup_marks_shops_and_no_duplicates`（更新） | DDL 列集合断言加入 `attempts` |
+
+## TDD 证据
+
+### RED（实现前跑新测试，失败输出）
+
+```
+$ python -m pytest tests/test_work_items.py -q
+10 failed, 4 passed in 0.16s
+FAILED tests/test_work_items.py::WorkItemsTest::test_attempts_column_present_and_legacy_migration
+FAILED tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_empty_queues_returns_none
+FAILED tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_fifo_by_id_across_queues
+FAILED tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_filters_queues
+FAILED tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_no_double_claim
+FAILED tests/test_work_items.py::WorkItemsTest::test_release_exhausts_attempts_to_failed
+FAILED tests/test_work_items.py::WorkItemsTest::test_release_on_non_claimed_is_defensive_failed
+FAILED tests/test_work_items.py::WorkItemsTest::test_release_returns_to_pending
+FAILED tests/test_work_items.py::WorkItemsTest::test_release_terminal_return_with_custom_max_attempts
+FAILED tests/test_work_items.py::WorkItemsTest::test_topup_marks_shops_and_no_duplicates
+```
+
+失败原因均为预期：`release_work_item`/`claim_next_eligible` 不存在（AttributeError）、work_items 缺 attempts 列、既有列集合断言未含 attempts。
+
+### GREEN（实现后通过）
+
+```
+$ python -m pytest tests/test_work_items.py -q
+14 passed in 0.10s
+```
+
+### 全量无回归
+
+```
+$ cd fetcher && python -m pytest tests -q
+318 passed, 2 subtests passed in 15.92s   （基线 309 + 新增 9）
+```
+
+## 改动文件
+
+- `fetcher/fetcher/db.py`：`_migrate()` 追加 work_items attempts 迁移；新增 `release_work_item`、`claim_next_eligible` 两方法（`# ---------- work_items ----------` 段内，reset_claimed_work_items 之后）
+- `fetcher/tests/test_work_items.py`：更新 DDL 列集合断言 + 新增 9 个用例（含 `_insert_item` helper，绕过 topup 直接构造多队列行）
+
+## 自查发现
+
+- **既有测试受列新增影响**：`test_topup_marks_shops_and_no_duplicates` 硬编码了 work_items 列集合断言，必须同步加入 `attempts`（否则旧测试挂，属预期连锁改动，已在 scoped 内）。
+- **SCHEMA 未改动**：按 brief 仅实现 `_migrate()` 迁移（新建库同样经迁移补列，探测幂等）；SCHEMA 的 work_items DDL 保持原样，diff 最小。若后续希望新库 DDL 原生含列，可另行把 `attempts` 加进 SCHEMA，不属本任务范围。
+- **release 的 rowcount=0 路径**：用 commit 结束事务（未发生任何写，rollback/commit 等价），返回 "failed" 不 raise，与 brief「防御性兜底」口径一致。
+- **claim_next_eligible 空 queues**：前置 `if not queues: return None`，不进入事务（与「视为无货」语义一致）。
+- 他人未提交改动（platform/*、vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/）未触碰。
+
+## 提交
+
+scoped commit：仅 `fetcher/fetcher/db.py` + `fetcher/tests/test_work_items.py`（未用 `git add -A`）。
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-review.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-review.md
new file mode 100644
index 0000000..0fd0c11
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.1-review.md
@@ -0,0 +1,402 @@
+# Review Package — Step 1.1 (work_items 扩展)
+
+## Commits
+c87c616 feat(multiqueue-p3): work_items 扩展——attempts 幂等迁移 + release_work_item + claim_next_eligible（TDD 全绿 318 passed）
+
+## Stat
+ fetcher/fetcher/db.py            |  78 +++++++++++++++
+ fetcher/tests/test_work_items.py | 211 ++++++++++++++++++++++++++++++++++++++-
+ 2 files changed, 284 insertions(+), 5 deletions(-)
+
+## Diff
+diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
+index 7af8033..351a570 100644
+--- a/fetcher/fetcher/db.py
++++ b/fetcher/fetcher/db.py
+@@ -241,20 +241,26 @@ class ShopDB:
+                WHERE status='done' AND id IN (
+                    SELECT shop_id FROM contacts
+                    WHERE contact_person IS NULL AND phone IS NULL
+                      AND mobile IS NULL AND fax IS NULL AND address IS NULL)""")
+         # ip_events 补 req_since_block 列（tmd 触发阈值样本：
+         # 本次触发时距该 IP 上次触发已爬多少个页面请求）
+         evt_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(ip_events)")}
+         if "req_since_block" not in evt_cols:
+             self.conn.execute(
+                 "ALTER TABLE ip_events ADD COLUMN req_since_block INTEGER")
++        # work_items 补 attempts 列（P3 多队列：release 重试计数，达上限熔断置 failed）
++        wi_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(work_items)")}
++        if "attempts" not in wi_cols:
++            self.conn.execute(
++                "ALTER TABLE work_items ADD COLUMN attempts"
++                " INTEGER NOT NULL DEFAULT 0")
+         # cookies 表裸键按 domain→site 映射加前缀（P2 identity 升级：
+         # identity 键从裸 IP 升级为 site:ip）。部署窗口：旧进程裸键读不到
+         # 新前缀 Cookie → 白板重启一次（SPEC §3.4 运维注意）。
+         # 映射清单（先长后短，SPEC §3.4 回填）：
+         self.conn.execute(
+             "UPDATE cookies SET identity = 'madeinchina:' || identity"
+             " WHERE identity NOT LIKE '%:%'"
+             " AND domain LIKE '%made-in-china.com%'")
+         self.conn.execute(
+             "UPDATE cookies SET identity = '1688:' || identity"
+@@ -506,20 +512,92 @@ class ShopDB:
+ 
+     def reset_claimed_work_items(self) -> int:
+         """全部 claimed 工作项重置回 pending（进程中断残留的认领，
+         daemon 启动时调用），清空 claimed_by/claimed_at，返回重置行数。"""
+         cur = self.conn.execute(
+             "UPDATE work_items SET status='pending', claimed_by=NULL,"
+             " claimed_at=NULL WHERE status='claimed'")
+         self.conn.commit()
+         return cur.rowcount
+ 
++    def release_work_item(self, item_id: int, max_attempts: int = 3) -> str:
++        """工作项释放回 pending（attempts+1）；attempts 达上限置 failed。
++
++        单事务（BEGIN IMMEDIATE）：attempts = attempts + 1，清空
++        claimed_by/claimed_at；attempts >= max_attempts 时置 failed
++        （写 finished_at、result_json="attempts exhausted"），否则置
++        pending。返回终态字符串："pending" / "failed"。
++
++        只对 claimed 状态的行生效；rowcount=0（非 claimed/不存在）时
++        返回 "failed"（调用方视为不可恢复，防御性兜底）。
++        """
++        try:
++            self.conn.execute("BEGIN IMMEDIATE")
++            cur = self.conn.execute(
++                "UPDATE work_items SET attempts = attempts + 1,"
++                " claimed_by = NULL, claimed_at = NULL"
++                " WHERE id=? AND status='claimed'", (item_id,))
++            if cur.rowcount == 0:
++                self.conn.commit()
++                return "failed"
++            attempts = self.conn.execute(
++                "SELECT attempts FROM work_items WHERE id=?",
++                (item_id,)).fetchone()[0]
++            if attempts >= max_attempts:
++                self.conn.execute(
++                    "UPDATE work_items SET status='failed', finished_at=?,"
++                    " result_json=? WHERE id=?",
++                    (_now(), json.dumps("attempts exhausted"), item_id))
++                self.conn.commit()
++                return "failed"
++            self.conn.execute(
++                "UPDATE work_items SET status='pending' WHERE id=?",
++                (item_id,))
++            self.conn.commit()
++            return "pending"
++        except Exception:
++            self.conn.rollback()
++            raise
++
++    def claim_next_eligible(self, queues: list[str],
++                            consumer_id: str) -> dict | None:
++        """跨队列原子认领最老 pending 工作项（FIFO 按 id，无优先级）。
++
++        单事务（BEGIN IMMEDIATE）：WHERE status='pending' AND queue IN (...)
++        ORDER BY id LIMIT 1 → 置 claimed（claimed_by/claimed_at）。返回
++        {"id", "queue", "site", "payload"}（payload 为 json.loads 解码后
++        的字典）；无货（含空 queues）返回 None。
++        """
++        if not queues:
++            return None
++        placeholders = ",".join("?" * len(queues))
++        try:
++            self.conn.execute("BEGIN IMMEDIATE")
++            row = self.conn.execute(
++                f"SELECT * FROM work_items WHERE status='pending'"
++                f" AND queue IN ({placeholders})"
++                " ORDER BY id LIMIT 1", queues).fetchone()
++            if not row:
++                self.conn.commit()
++                return None
++            self.conn.execute(
++                "UPDATE work_items SET status='claimed', claimed_by=?,"
++                " claimed_at=? WHERE id=?",
++                (consumer_id, _now(), row["id"]))
++            self.conn.commit()
++        except Exception:
++            self.conn.rollback()
++            raise
++        return {"id": row["id"], "queue": row["queue"],
++                "site": row["site"],
++                "payload": json.loads(row["payload_json"])}
++
+     # ---------- category_progress ----------
+     def get_category_progress(self, keyword: str) -> dict | None:
+         """取类目分页进度（无记录返回 None）。"""
+         row = self.conn.execute(
+             "SELECT * FROM category_progress WHERE keyword=?",
+             (keyword,)).fetchone()
+         return dict(row) if row else None
+ 
+     def advance_category_page(self, keyword: str, name: str = None,
+                               shops_found: int = 0) -> int:
+diff --git a/fetcher/tests/test_work_items.py b/fetcher/tests/test_work_items.py
+index cce84b9..f329c62 100644
+--- a/fetcher/tests/test_work_items.py
++++ b/fetcher/tests/test_work_items.py
+@@ -1,20 +1,21 @@
+ # -*- coding: utf-8 -*-
+-"""work_items 存储层测试：topup / claim / finish / reset 四方法（临时 sqlite）。
+-仿 test_contact_task.py 基建，不起浏览器/网络。"""
++"""work_items 存储层测试：topup / claim / finish / reset / release / claim_next_eligible
++（临时 sqlite）。仿 test_contact_task.py 基建，不起浏览器/网络。"""
+ 
+ import json
++import sqlite3
+ import tempfile
+ import unittest
+ from pathlib import Path
+ 
+-from fetcher.db import ShopDB
++from fetcher.db import SCHEMA, ShopDB
+ 
+ QUEUE = "crawl_1688_contact"
+ 
+ 
+ def _shop(i, suffix=".1688.com"):
+     return {"domain": f"shop{i}{suffix}", "name": f"店铺{i}",
+             "url": f"https://shop{i}{suffix}"}
+ 
+ 
+ class WorkItemsTest(unittest.TestCase):
+@@ -36,22 +37,23 @@ class WorkItemsTest(unittest.TestCase):
+             (domain,)).fetchone()[0]
+ 
+     # 用例 1：top-up 生成 work_items 且 shops 标 in_progress；
+     # 重复 top-up 只补剩余 pending，不产生重复行
+     def test_topup_marks_shops_and_no_duplicates(self):
+         # DDL 前置断言：表与索引存在、列齐全
+         cols = {r[1] for r in self.db.conn.execute(
+             "PRAGMA table_info(work_items)")}
+         self.assertEqual(
+             cols, {"id", "queue", "site", "batch_id", "payload_json",
+-                   "requires", "status", "claimed_by", "claimed_at",
+-                   "finished_at", "result_json", "created_at"})
++                   "requires", "status", "attempts", "claimed_by",
++                   "claimed_at", "finished_at", "result_json",
++                   "created_at"})
+         idx = {r[1] for r in self.db.conn.execute(
+             "PRAGMA index_list(work_items)")}
+         self.assertIn("idx_work_items_claim", idx)
+ 
+         # 3 家 1688 店铺 + 1 家 madeinchina（suffix 不匹配，不应入队）
+         self.db.upsert_shops([_shop(1), _shop(2), _shop(3),
+                               _shop(9, ".cn.made-in-china.com")])
+         n = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+         self.assertEqual(n, 2)
+ 
+@@ -155,12 +157,211 @@ class WorkItemsTest(unittest.TestCase):
+             self.assertIsNone(rows[item_id]["claimed_by"])
+             self.assertIsNone(rows[item_id]["claimed_at"])
+         others = [r for r in self._items()
+                   if r["id"] not in (a["id"], b["id"])]
+         self.assertEqual(len(others), 1)
+         self.assertEqual(others[0]["status"], "pending")
+         # 无 claimed 行时返回 0
+         self.assertEqual(self.db.reset_claimed_work_items(), 0)
+ 
+ 
++    # ---------- P3 Step 1.1: attempts / release_work_item / claim_next_eligible ----------
++    def _insert_item(self, queue, payload, site="1688"):
++        """直接向 work_items 插 pending 行（绕过 topup，便于多队列交叉构造）。"""
++        cur = self.db.conn.execute(
++            "INSERT INTO work_items (queue, site, payload_json, created_at)"
++            " VALUES (?, ?, ?, ?)",
++            (queue, site, json.dumps(payload, ensure_ascii=False),
++             "2025-08-08 00:00:00"))
++        self.db.conn.commit()
++        return cur.lastrowid
++
++    # 用例 1：release 回 pending，可重领且 attempts 保留
++    def test_release_returns_to_pending(self):
++        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
++        got = self.db.claim_next_eligible(["q1"], "w0")
++        self.assertEqual(got["id"], iid)
++
++        ret = self.db.release_work_item(iid)
++        self.assertEqual(ret, "pending")
++        row = self.db.conn.execute(
++            "SELECT * FROM work_items WHERE id=?", (iid,)).fetchone()
++        self.assertEqual(row["status"], "pending")
++        self.assertEqual(row["attempts"], 1)
++        self.assertIsNone(row["claimed_by"])
++        self.assertIsNone(row["claimed_at"])
++        self.assertIsNone(row["finished_at"])
++
++        # 重领：attempts 保留（claim 不重置 attempts）
++        got2 = self.db.claim_next_eligible(["q1"], "w1")
++        self.assertEqual(got2["id"], iid)
++        row = self.db.conn.execute(
++            "SELECT status, attempts FROM work_items WHERE id=?",
++            (iid,)).fetchone()
++        self.assertEqual(row["status"], "claimed")
++        self.assertEqual(row["attempts"], 1)
++
++    # 用例 2：attempts 耗尽置 failed
++    def test_release_exhausts_attempts_to_failed(self):
++        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
++        results = []
++        for _ in range(3):
++            self.db.claim_next_eligible(["q1"], "w0")
++            results.append(self.db.release_work_item(iid))
++        self.assertEqual(results, ["pending", "pending", "failed"])
++        row = self.db.conn.execute(
++            "SELECT * FROM work_items WHERE id=?", (iid,)).fetchone()
++        self.assertEqual(row["status"], "failed")
++        self.assertEqual(row["attempts"], 3)
++        self.assertEqual(json.loads(row["result_json"]), "attempts exhausted")
++        self.assertIsNotNone(row["finished_at"])
++
++    # 用例 3：release 终态返回值（不足上限 pending，达上限 failed）
++    def test_release_terminal_return_with_custom_max_attempts(self):
++        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
++        self.db.claim_next_eligible(["q1"], "w0")
++        self.assertEqual(self.db.release_work_item(iid, max_attempts=2),
++                         "pending")
++        self.db.claim_next_eligible(["q1"], "w0")
++        self.assertEqual(self.db.release_work_item(iid, max_attempts=2),
++                         "failed")
++        row = self.db.conn.execute(
++            "SELECT status, attempts FROM work_items WHERE id=?",
++            (iid,)).fetchone()
++        self.assertEqual(row["status"], "failed")
++        self.assertEqual(row["attempts"], 2)
++
++    # 用例 4：release 非 claimed 防御（返回 failed 且行内容不变）
++    def test_release_on_non_claimed_is_defensive_failed(self):
++        # pending 行
++        pid = self._insert_item("q1", {"domain": "shop1.1688.com"})
++        self.assertEqual(self.db.release_work_item(pid), "failed")
++        row = self.db.conn.execute(
++            "SELECT * FROM work_items WHERE id=?", (pid,)).fetchone()
++        self.assertEqual(row["status"], "pending")
++        self.assertEqual(row["attempts"], 0)
++        self.assertIsNone(row["claimed_by"])
++        self.assertIsNone(row["finished_at"])
++        self.assertIsNone(row["result_json"])
++
++        # done 行
++        did = self._insert_item("q1", {"domain": "shop2.1688.com"})
++        self.db.claim_next_eligible(["q1"], "w0")
++        self.db.finish_work_item(did, "done", {"ok": True})
++        self.assertEqual(self.db.release_work_item(did), "failed")
++        row = self.db.conn.execute(
++            "SELECT * FROM work_items WHERE id=?", (did,)).fetchone()
++        self.assertEqual(row["status"], "done")
++        self.assertEqual(row["attempts"], 0)
++        self.assertEqual(json.loads(row["result_json"]), {"ok": True})
++
++        # 不存在的 id
++        self.assertEqual(self.db.release_work_item(99999), "failed")
++
++    # 用例 5：claim_next_eligible 队列集合过滤
++    def test_claim_next_eligible_filters_queues(self):
++        a = self._insert_item("queue_a", {"domain": "a1.1688.com"})
++        b = self._insert_item("queue_b", {"domain": "b1.1688.com"})
++        c = self._insert_item("queue_c", {"domain": "c1.1688.com"})
++
++        got = self.db.claim_next_eligible(["queue_a"], "w0")
++        self.assertEqual(got["id"], a)
++        self.assertEqual(got["queue"], "queue_a")
++        self.assertEqual(got["site"], "1688")
++        self.assertEqual(got["payload"], {"domain": "a1.1688.com"})
++        for iid in (b, c):
++            row = self.db.conn.execute(
++                "SELECT status FROM work_items WHERE id=?",
++                (iid,)).fetchone()
++            self.assertEqual(row["status"], "pending")
++
++        got2 = self.db.claim_next_eligible(["queue_a", "queue_b"], "w1")
++        self.assertEqual(got2["id"], b)
++        row_c = self.db.conn.execute(
++            "SELECT status FROM work_items WHERE id=?", (c,)).fetchone()
++        self.assertEqual(row_c["status"], "pending")
++
++    # 用例 6：FIFO（多队混排按 id 最老先领，无优先级）
++    def test_claim_next_eligible_fifo_by_id_across_queues(self):
++        ids = [self._insert_item(q, {"domain": f"{q}-{i}.1688.com"})
++               for i, q in enumerate(["A", "B", "A", "B"])]
++        claimed = []
++        for _ in range(4):
++            got = self.db.claim_next_eligible(["A", "B"], "w0")
++            self.assertIsNotNone(got)
++            claimed.append(got["id"])
++        self.assertEqual(claimed, ids)  # 严格按 id 升序
++        self.assertIsNone(self.db.claim_next_eligible(["A", "B"], "w0"))
++
++    # 用例 7：并发不重复认领（顺序模拟两个消费者）
++    def test_claim_next_eligible_no_double_claim(self):
++        i1 = self._insert_item("q1", {"domain": "shop1.1688.com"})
++        i2 = self._insert_item("q1", {"domain": "shop2.1688.com"})
++        a = self.db.claim_next_eligible(["q1"], "w0")
++        b = self.db.claim_next_eligible(["q1"], "w1")
++        self.assertIsNotNone(a)
++        self.assertIsNotNone(b)
++        self.assertNotEqual(a["id"], b["id"])
++        self.assertEqual(sorted([a["id"], b["id"]]), [i1, i2])
++        rows = {r["id"]: r for r in self._items()}
++        self.assertEqual(rows[a["id"]]["claimed_by"], "w0")
++        self.assertEqual(rows[b["id"]]["claimed_by"], "w1")
++        self.assertIsNone(self.db.claim_next_eligible(["q1"], "w2"))
++
++    # 用例 8：attempts 列存在性 + 旧库迁移（存量行默认 0）
++    def test_attempts_column_present_and_legacy_migration(self):
++        cols = {r[1] for r in self.db.conn.execute(
++            "PRAGMA table_info(work_items)")}
++        self.assertIn("attempts", cols)
++
++        # 手工构造无 attempts 列的旧库（模拟 P3 前 schema）
++        legacy_path = str(Path(self._tmp.name) / "legacy.db")
++        conn = sqlite3.connect(legacy_path)
++        conn.execute("PRAGMA journal_mode=WAL")
++        conn.executescript(SCHEMA)
++        conn.execute("DROP TABLE work_items")
++        conn.execute(
++            """CREATE TABLE work_items (
++                id          INTEGER PRIMARY KEY AUTOINCREMENT,
++                queue       TEXT NOT NULL,
++                site        TEXT,
++                batch_id    INTEGER,
++                payload_json TEXT NOT NULL,
++                requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
++                status      TEXT NOT NULL DEFAULT 'pending',
++                claimed_by  TEXT,
++                claimed_at  TEXT,
++                finished_at TEXT,
++                result_json TEXT,
++                created_at  TEXT NOT NULL)""")
++        conn.execute(
++            "INSERT INTO work_items (queue, site, payload_json, created_at)"
++            " VALUES ('q1', 's1', '{}', '2025-08-08 00:00:00')")
++        conn.commit()
++        conn.close()
++
++        db2 = ShopDB(legacy_path)
++        cols2 = {r[1] for r in db2.conn.execute(
++            "PRAGMA table_info(work_items)")}
++        self.assertIn("attempts", cols2)
++        row = db2.conn.execute(
++            "SELECT attempts FROM work_items WHERE queue='q1'").fetchone()
++        self.assertEqual(row["attempts"], 0)
++        # 幂等：重开再迁移不报错、列仍存在
++        db2.close()
++        db3 = ShopDB(legacy_path)
++        cols3 = {r[1] for r in db3.conn.execute(
++            "PRAGMA table_info(work_items)")}
++        self.assertIn("attempts", cols3)
++        db3.close()
++
++    # 用例 9：空队列返回 None
++    def test_claim_next_eligible_empty_queues_returns_none(self):
++        self._insert_item("q1", {"domain": "shop1.1688.com"})
++        self.assertIsNone(self.db.claim_next_eligible([], "w0"))
++        row = self.db.conn.execute(
++            "SELECT status FROM work_items").fetchone()
++        self.assertEqual(row["status"], "pending")  # 不碰任何行
++
++
+ if __name__ == "__main__":
+     unittest.main()
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 351a570..57374c8 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -530,21 +530,22 @@ class ShopDB:
         只对 claimed 状态的行生效；rowcount=0（非 claimed/不存在）时
         返回 "failed"（调用方视为不可恢复，防御性兜底）。
         """
         try:
             self.conn.execute("BEGIN IMMEDIATE")
             cur = self.conn.execute(
                 "UPDATE work_items SET attempts = attempts + 1,"
                 " claimed_by = NULL, claimed_at = NULL"
                 " WHERE id=? AND status='claimed'", (item_id,))
             if cur.rowcount == 0:
-                self.conn.commit()
+                # 非 claimed/不存在：无任何写发生，rollback 结束事务（防御性兜底）
+                self.conn.rollback()
                 return "failed"
             attempts = self.conn.execute(
                 "SELECT attempts FROM work_items WHERE id=?",
                 (item_id,)).fetchone()[0]
             if attempts >= max_attempts:
                 self.conn.execute(
                     "UPDATE work_items SET status='failed', finished_at=?,"
                     " result_json=? WHERE id=?",
                     (_now(), json.dumps("attempts exhausted"), item_id))
                 self.conn.commit()
@@ -559,44 +560,48 @@ class ShopDB:
             raise
 
     def claim_next_eligible(self, queues: list[str],
                             consumer_id: str) -> dict | None:
         """跨队列原子认领最老 pending 工作项（FIFO 按 id，无优先级）。
 
         单事务（BEGIN IMMEDIATE）：WHERE status='pending' AND queue IN (...)
         ORDER BY id LIMIT 1 → 置 claimed（claimed_by/claimed_at）。返回
         {"id", "queue", "site", "payload"}（payload 为 json.loads 解码后
         的字典）；无货（含空 queues）返回 None。
+
+        payload 解析在 commit 前完成：payload_json 非法（手工修库/上游
+        bug）时 JSONDecodeError 走 except → rollback，行保持 pending，
+        不会产生已 claimed 却拿不到 id 的泄漏行。
         """
         if not queues:
             return None
         placeholders = ",".join("?" * len(queues))
         try:
             self.conn.execute("BEGIN IMMEDIATE")
             row = self.conn.execute(
-                f"SELECT * FROM work_items WHERE status='pending'"
-                f" AND queue IN ({placeholders})"
+                f"SELECT id, queue, site, payload_json FROM work_items"
+                f" WHERE status='pending' AND queue IN ({placeholders})"
                 " ORDER BY id LIMIT 1", queues).fetchone()
             if not row:
                 self.conn.commit()
                 return None
+            payload = json.loads(row["payload_json"])
             self.conn.execute(
                 "UPDATE work_items SET status='claimed', claimed_by=?,"
                 " claimed_at=? WHERE id=?",
                 (consumer_id, _now(), row["id"]))
             self.conn.commit()
+            return {"id": row["id"], "queue": row["queue"],
+                    "site": row["site"], "payload": payload}
         except Exception:
             self.conn.rollback()
             raise
-        return {"id": row["id"], "queue": row["queue"],
-                "site": row["site"],
-                "payload": json.loads(row["payload_json"])}
 
     # ---------- category_progress ----------
     def get_category_progress(self, keyword: str) -> dict | None:
         """取类目分页进度（无记录返回 None）。"""
         row = self.conn.execute(
             "SELECT * FROM category_progress WHERE keyword=?",
             (keyword,)).fetchone()
         return dict(row) if row else None
 
     def advance_category_page(self, keyword: str, name: str = None,
diff --git a/fetcher/tests/test_work_items.py b/fetcher/tests/test_work_items.py
index f329c62..0f9a5d0 100644
--- a/fetcher/tests/test_work_items.py
+++ b/fetcher/tests/test_work_items.py
@@ -356,12 +356,42 @@ class WorkItemsTest(unittest.TestCase):
 
     # 用例 9：空队列返回 None
     def test_claim_next_eligible_empty_queues_returns_none(self):
         self._insert_item("q1", {"domain": "shop1.1688.com"})
         self.assertIsNone(self.db.claim_next_eligible([], "w0"))
         row = self.db.conn.execute(
             "SELECT status FROM work_items").fetchone()
         self.assertEqual(row["status"], "pending")  # 不碰任何行
 
 
+    # 用例 10：payload_json 非法时不泄漏（review Important-1）
+    def test_claim_next_eligible_invalid_payload_does_not_leak(self):
+        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
+        # 手工破坏 payload_json（模拟上游 bug / 手工修库）
+        self.db.conn.execute(
+            "UPDATE work_items SET payload_json='not-json{' WHERE id=?",
+            (iid,))
+        self.db.conn.commit()
+
+        # 调用方能看到异常
+        with self.assertRaises(json.JSONDecodeError):
+            self.db.claim_next_eligible(["q1"], "w0")
+
+        # 行未被认领：保持 pending，不产生无法回收的 claimed 泄漏
+        row = self.db.conn.execute(
+            "SELECT status, claimed_by FROM work_items WHERE id=?",
+            (iid,)).fetchone()
+        self.assertEqual(row["status"], "pending")
+        self.assertIsNone(row["claimed_by"])
+
+        # 修复 payload 后可正常认领（行未被卡死）
+        self.db.conn.execute(
+            "UPDATE work_items SET payload_json=? WHERE id=?",
+            (json.dumps({"domain": "shop1.1688.com"}), iid))
+        self.db.conn.commit()
+        got = self.db.claim_next_eligible(["q1"], "w1")
+        self.assertEqual(got["id"], iid)
+        self.assertEqual(got["payload"], {"domain": "shop1.1688.com"})
+
+
 if __name__ == "__main__":
     unittest.main()
