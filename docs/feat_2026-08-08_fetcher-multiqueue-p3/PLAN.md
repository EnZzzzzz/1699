# PLAN — P3 多队列跨站填充

> 版本：v1 · 2026-08-08 · 待评审
> 配套：SPEC.md（同目录）。执行流程按 subagent-driven-development skill；ledger.md 随执行建立。

## Phase 清单

| Phase | 目标 | 预计 Step | 依赖 | 状态 |
|---|---|---|---|---|
| P3-0 | CloakBrowser 多 context 席位 spike（C1 实测） | 1 | 无 | done |
| P3-1 | 调度内核：work_items 扩展 + 冷却表改建 + 让出型 chokepoint | 3 | P3-0（可并行，不依赖其结果） | pending |
| P3-2 | 浏览器层：Session/BrowserManager 多 context + 种子池 (worker,site) 粒度 | 3 | P3-0 结论回填 SPEC §4 | pending |
| P3-3 | QueueRouter + daemon CLI + SwapIP 两阶段 | 3 | P3-1、P3-2 | pending |
| P3-4 | madeinchina 队列接入（contact + shop feeder） | 2 | P3-3 | pending |
| P3-5 | 1688 shop/company feeder 接入 | 2 | P3-4 | pending |
| P3-6 | 端到端验收冒烟 + 终审 | 2 | P3-5 | pending |

---

## P3-0 CloakBrowser spike

**准入**：无。**完成标准**：实测报告写入本目录 `spike-cloakbrowser-multicontext.md`，结论回填 SPEC §4 C1（推断→已验证）；若证伪，回 SPEC 重议降级方案再放行 P3-2。

- [x] **Step 0.1** 席位计数实测（估 30min，依赖无，状态 pending）
  - 脚本放 `/tmp`：读 baseline `get_active_session_count` → headless 直连 launch → 计数（应 +1）→ `browser.new_context()` 第二个 context → 计数（应不变）→ 第二 context 内 `page.goto("about:blank")` 确认可用 → close → 计数（应 -1）。
  - 环境纪律：本机活爬虫占 ~2 席，本次 +1 不超 solo=5；不开代理（避免占用青果隧道）；全程 headless。
  - 验收：报告含每次计数原始值与结论；报告文件放 plan 目录（不放 /tmp，防丢证据）。

## P3-1 调度内核

**准入**：无（与 P3-0 并行）。**完成标准**：新增 DB 函数与冷却语义单测全绿；`_cooldown` 让出型调用点全部改为登记即返回；现有测试基线不 regress。

- [ ] **Step 1.1** work_items 扩展（估 20min，依赖无，状态 pending）
  - `db.py`：migrate 幂等加 `attempts INTEGER NOT NULL DEFAULT 0`；新增 `release_work_item(item_id, max_attempts=3)`、`claim_next_eligible(queues, consumer_id)`。
  - 验收：TDD 单测覆盖——release 回 pending/attempts 耗尽置 failed/claim_next_eligible 按队列集合过滤+FIFO+并发不重复认领。
- [ ] **Step 1.2** 冷却表改建 + eligible_queues（估 20min，依赖 1.1，状态 pending）
  - `WorkerContext.cooldown_until` 键改 site；`ctx.state["active_site"]` 约定；新增 `eligible_queues(registry, ctx, now)`（纯函数，可单测）；claim 过滤 + condvar `timeout=min(最近冷却到期剩余, 30s)`。
  - 验收：单测——冷却中站点被过滤、到期恢复可见、timeout 计算正确。
- [ ] **Step 1.3** `_cooldown` 让出型改造（估 30min，依赖 1.2，状态 pending）
  - loop 让出型调用点（sample_interval/batch_rest/periodic_rest/策略冷却）登记即返回；launch_backoff 保留原地并加注释；P1 遗留注释同步更新。
  - 策略冷却后 item 未完成的路径暂保留现状（等 P3-3 router 接 release），本 Step 只保证单队列行为等价。
  - 验收：单队列 daemon 冒烟（`--workers 1` 直连临时库，日志放 plan 目录）行为与改造前等价；全量测试绿。
  - 注：直连环境 1688 滑块墙近乎必现，全 failed 是环境噪声，取结构证据（冷却登记日志）即可，不纠缠滑块。

## P3-2 浏览器层多 context

**准入**：P3-0 结论回填 SPEC §4 C1 = 已验证。**完成标准**：单站点路径行为等价（1688 contact 旧 CLI 冒烟）；多 context 隔离单测通过。

- [ ] **Step 2.1** Session/SiteView 重构（估 40min，依赖 P3-0，状态 pending）
  - `Session.views[site]` + `ensure_site` 懒建 + `close_site`/全量 `close` 两层语义；`ctx.page` 路由活动 view；`session.ctx` property 同步。
  - 验收：SPEC §6.1 清单中 session/browser 两侧消费方全部迁移；C2 隔离单测（同 browser 两 context Cookie 互不可见）。
- [ ] **Step 2.2** relaunch/warmup/种子池适配（估 30min，依赖 2.1，状态 pending）
  - relaunch 全 view 回写后关进程、views 清空懒重建；`_alloc_seed_kits` 改 (worker, site) 粒度；`needs_relaunch` 状态位。
  - 验收：单测 + 旧 CLI `1688 contact --workers 1` 直连冒烟等价。
- [ ] **Step 2.3** 原子/策略消费方迁移（估 30min，依赖 2.1，状态 pending）
  - RelaunchBrowser、WaitHumanLogin/WaitHumanVerify、loop 的 `_relaunch`/`_ensure_fresh_ip`/`_check_budget`/`_cleanup` 全部走活动 view。
  - 验收：全量测试绿；grep 无残留直接持有 page 跨 item 的引用。

## P3-3 QueueRouter + SwapIP

**准入**：P3-1、P3-2 完成。**完成标准**：`daemon --queues` 多队列装配跑通（先 1688 contact + mic contact 两条同构队列）；SwapIP 无头两阶段单测。

- [ ] **Step 3.1** QueueRouter + 注册表装配（估 40min，依赖 1.3、2.3，状态 pending）
  - `control/queue_router.py`：QueueSpec 注册表、acquire 三段式（claim_next_eligible→topup→condvar）、on_success/on_giveup 路由 + finish/release 回写、active_site 绑定、每 site Policy 装配；替换 DaemonTaskProxy；`cli/main.py` daemon 分支 `--queues`（choices+默认全量，删 `--queue`）；启动 reset 逐 site domain 过滤修复。
  - 验收：TDD；`test_daemon_task.py` 重写为 router 语义；双队列（1688 contact + mic contact）装配单测。
- [ ] **Step 3.2** SwapIP 两阶段（估 30min，依赖 3.1，状态 pending）
  - 无头：未轮换→回写关本站 context→置 needs_relaunch→让出冷却→release item；有头 WaitHumanLogin 保留原地例外（注释更新）；懒建路径消费 needs_relaunch。
  - 验收：单测覆盖两阶段状态流转（mock relaunch rotated=False）；策略冷却后 release→重领→attempts 熔断链路单测。
- [ ] **Step 3.3** 双队列跨站冒烟（估 30min，依赖 3.2，状态 pending）
  - `--workers 1` 直连临时库跑 `daemon --queues crawl_1688_contact,crawl_mic_contact`：人为注货两站店铺，日志验证同 worker 在一站冷却期认领另一站 item。
  - 验收：日志证据落 plan 目录（report 文件随跑随写）。

## P3-4 madeinchina 队列接入

**准入**：P3-3 完成。**完成标准**：`crawl_mic_shop` feeder 链路（播种→discover→类目页→链式续喂）单测+冒烟。

- [ ] **Step 4.1** contact 接入 + mic shop 任务拆分（估 40min，依赖 3.1，状态 pending）
  - `crawl_mic_contact` 入注册表（topup 复用现函数，`.cn.made-in-china.com`）；mic contact prepare 的 reset 副作用确认/修 domain 过滤。
  - mic shop task 拆出「单类目页处理」（payload 驱动，认朗读 next_page，on_success advance/exhausted + 链式续喂 + 失败补插）；discover item 执行 = 现 cold_start 提取逻辑。
  - 验收：TDD 单测（链式续喂、ZERO_NEW_LIMIT 保护、失败补插、幂等播种）。
- [ ] **Step 4.2** mic shop feeder 装配 + 冒烟（估 30min，依赖 4.1，状态 pending）
  - `iter_active_categories`（mic 拼音 slug 过滤沿用）；启动播种（幂等）；注册表加 `crawl_mic_shop`。
  - 验收：冒烟——临时库播种后 daemon 消费类目页 item，category_progress 推进、shops 落库；日志落 plan 目录。

## P3-5 1688 shop/company feeder 接入

**准入**：P3-4 完成（feeder 模式已跑通）。**完成标准**：两条 1688 内容队列接入，冒烟验证播种与链式续喂。

- [ ] **Step 5.1** 1688 shop/company 任务拆分（估 40min，依赖 4.2，状态 pending）
  - 同 §4.1 模式拆 offer_search/company_search 单页处理；company 进度键 `company:` 前缀沿用；discover = 首页类目提取 + mtop 握手。
  - 验收：TDD 单测（前缀隔离、续喂、补插）。
- [ ] **Step 5.2** 注册表装配 + 冒烟（估 30min，依赖 5.1，状态 pending）
  - `iter_active_categories` 1688 变体（无拼音过滤、支持 company: 前缀）；两条队列入注册表；启动播种。
  - 验收：冒烟（直连滑块墙环境噪声下取结构证据：播种→认领→progress 读写路径走通）；旧 CLI `1688 shop --workers 1` 等价性确认。

## P3-6 端到端验收 + 终审

**准入**：P3-5 完成。**完成标准**：SPEC §7 验收标准逐条取证；全分支终审 MERGE READY。

- [ ] **Step 6.1** 跨站填充端到端冒烟（估 40min，依赖 5.2，状态 pending）
  - `--workers 1` 全量 5 队列（或按环境可用子集）临时库：取证 ① 同 worker 跨站填充日志（双向）② ip_req 簿记不超各站预算 ③ 无重复认领。
  - 证据（命令+日志摘录+计数）落 plan 目录 report。
- [ ] **Step 6.2** 全量回归 + 终审（估 30min，依赖 6.1，状态 pending）
  - 全量测试；SPEC §7 逐条勾选；README/AGENTS.md 涉及段落同步（daemon 队列清单、互斥约定）；scheduler-architecture.md §10 P3 行标完成 + 归档本目录到 docs/archive/。
  - 验收：终审报告 MERGE READY 后呈用户合并。
