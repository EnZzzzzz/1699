# Step 2.1 brief — DaemonTaskProxy 实现

> 来源：PLAN.md Phase 2 Step 2.1 + SPEC §3.3。本文本是你的需求唯一来源。

## 内容

新增 `fetcher/fetcher/control/daemon_task.py`：`DaemonTaskProxy(inner, queue, site, domain_suffix)`，实现 Task 协议（`fetcher/fetcher/control/task.py`），包装既有 task（P0 为 ContactTask）让它的工作项来源从「自己 claim shops」换成「从 work_items 表认领」。

### acquire_item 三段式（SPEC §3.3）

1. `db.claim_work_item(queue, consumer_id)`；命中 → 返回 payload dict（必须含 `domain`/`name`/`url` 三键，name/url 允许 None 但键必须存在）；
2. 未命中 → `db.topup_contact_work_items(queue, site, domain_suffix, limit=消费者数×4)` → 补到货则对条件变量 `notify_all` 并重试 claim；
3. 仍无货 → 条件变量 wait（超时 30s 自醒），醒后先查 `ctx.stop`，置位则返回 None，否则回到 1。

consumer_id 用 `f"w{ctx.wid}"`。消费者数从 `ctx.config.workers` 取（注意 workers=0 时表示「按通道数」，此时退用 `len(provider.servers())` 不可行——proxy 拿不到 provider；裁定：workers<=0 时补货上限按 4×1=4 的兜底，或你在读码后发现 config 上有更合适的已解析字段，用那个并在 report 说明）。

### 必须处理的设计点（Step 1.1 已验证的事实）

- **proxy 实例跨 worker 线程共享**（Engine 把同一个 task 对象传给所有 worker 的 CrawlLoop）：条件变量、以及「当前 worker 认领的 work_item id」都必须线程安全。work_item id 的记录建议用 `ctx.state`（WorkerContext 每 worker 独立）或 wid 键字典+锁——你读 `control/loop.py`/`core/context.py` 后选定，report 说明理由。
- **proxy 不继承 Task 基类**，纯组合：显式定义 `acquire_item/prepare/after_item`，显式转发类属性 `unit/batch_unit/cold_start_before_acquire/ip_request_budget`，其余方法用 `__getattr__` 透传 inner。（若继承基类，基类默认实现会挡住 `__getattr__`，透传失效——这是坑，不许踩。）
- **finish_work_item 的挂载点**：要求「work_item 的终态必须反映该 item 的最终处置（成功→done，放弃→failed）」。你先读 `control/task.py` 的 `after_item/on_success/on_giveup` 签名和 `control/loop.py` 的调用点，判断 `after_item` 是否能拿到最终处置结果；拿不到就改挂 `on_success`/`on_giveup`（透传 inner 返回值的同时落终态）。选择哪个钩子、为什么，写进 report。注意 inner ContactTask 未定义 `after_item`（基类默认空实现），透传时容错。
- **prepare(config)**：调 inner.prepare；打印队列当前 pending 数（口径=shops pending 未补货数 + work_items pending 数——用现有 db 方法能拿到什么算什么，report 说明口径）。
- **dict payload 已被 Step 1.1 验证可 1:1 替代 sqlite Row**（contact.py 全部 8 处访问均为 `item["..."]` 键访问）；站点 cold_start 对 dict 走店铺首页分支是 SPEC §3.3 已裁定的可接受差异，无需处理。
- stop 置位时 acquire_item 最多 30s 内返回 None。

### 验收

- [ ] proxy 不显式 import ContactTask（对任意 inner task 成立）
- [ ] stop 置位时 acquire_item 最多 30s 内返回 None
- [ ] proxy 实例跨 worker 共享时无线程安全问题（条件变量、work_item id 记录）
- [ ] `__getattr__` 透传不被任何基类默认实现挡住（proxy 不继承 Task）

## 约束

- 只新增 `fetcher/fetcher/control/daemon_task.py` 一个文件；不改 loop.py/engine.py/task.py/contact.py 等任何既有文件。
- 本 Step 不写测试（测试在 Step 2.2），但你写的接口必须是可测的（DB 路径经 ctx.config.resolved_db_path() 或注入，参考既有代码怎么拿 ShopDB——读 `engine.py:48-51` 的 store_factory 和 `context.py` 再决定，report 说明）。
- 代码风格：中文注释、文件顶部一行注释说明模块职责（项目约定）。
