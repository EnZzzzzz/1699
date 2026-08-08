# SPEC — P3 多队列跨站填充（fetcher 调度器改造第三阶段）

> 版本：v1 · 2026-08-08 · 待评审
> 设计基准：docs/scheduler-architecture.md（§4 核心概念 / §5 调度循环 / §6 冷却策略表 / §10 落地路线 P3 行）
> 前置：P0（daemon 骨架）、P1（冷却迁移）、P2（identity 分桶）均已合并 main。

## 1. 背景与目标

P0~P2 完成后，daemon 仍是**单队列单站点**（`crawl_1688_contact`），`_cooldown` chokepoint 仍是「登记 + 原地等待」——worker 线程在样本间隔/批休/风控冷却期间抱着通道和浏览器空睡，IP 利用率问题没有实际解开。

P3 目标（对齐基准文档 §10 P3 行验收）：

1. daemon 升级为**多队列多站点**：5 条浏览器队列统一注册、统一消费。
2. 消费者按「资源满足 ∧ 该站点冷却已到期」跨队列取项；某站点冷却期间，同一通道自动转去执行其他站点的工作项。
3. BrowserContext 多站点隔离（自 P2 移入）：一消费者一浏览器进程，每站点一个独立 context/storage state。
4. **验收**：同通道 madeinchina 冷却期间执行 1688 工作项（日志可证），两边各自请求预算不超标；全量测试绿。

## 2. 范围与非目标

### 范围

- 调度内核：`cooldown_until` 改建（reason→site）、`_cooldown` 让出语义、`claim_next_eligible`、work_items 挂起/重试语义。
- 队列路由：队列注册表（queue → site/task/topup/policy），`QueueRouter` 取代 `DaemonTaskProxy`。
- 浏览器层：`Session`/`BrowserManager` 多 context 改造；种子身份池认领粒度改 (consumer, site)。
- SwapIP 两阶段拆分（解开 P1 留下的例外）。
- 队列接入：madeinchina contact / madeinchina shop / 1688 shop / 1688 company（1688 contact 已在）。
- CloakBrowser 多 context 席位实测（Phase 0 spike，是浏览器层动工的准入条件）。
- daemon CLI 与启动互斥修复（`reset_in_progress` 无 domain 过滤的现存坑）。

### 非目标（P3 不做）

- yiwugo / taobao 队列接入（纯内存队列 + JSONL 落盘，无 DB 进度，接入价值低）。
- HttpConsumer / LocalExecutor / wa_check / facebook API（基准文档 P4+）。
- 平台侧集成（runner 批次提交、`start.sh` 拉 daemon、前端看板）——P4。
- work_items 的 `batch_id` / `stopped` 态 / 批次优先级——P4 平台切换时启用。
- 多 dispatcher 分布式、asyncio 重写、pub/sub 分派、优先级抢占（基准文档 §11 已裁定）。
- 长阻塞工作项期间消费者对其他队列不可用——v1 接受（基准文档 §5 已裁定）。
- 有头模式 SwapIP 的 `WaitHumanLogin` 人工登录轮询：保留原地等待（见 §3.5 裁定）。

## 3. 设计要点

### 3.1 队列注册表与 QueueRouter

新增 `fetcher/fetcher/control/queue_router.py`，`QueueRouter` 取代 `DaemonTaskProxy`（P0 组件，仅 daemon 使用、无平台依赖，直接替换不保留兼容）。注册表为启动期静态装配：

```python
@dataclass
class QueueSpec:
    queue: str            # "crawl_1688_contact" / "crawl_mic_contact" / ...
    site: str             # 注册名 "1688" / "madeinchina"
    task: Task            # 该队列工作项的执行流水线（站点插件 make_task 产出）
    topup: Callable[[ShopDB, int], int] | None   # 补货函数；feeder 类队列为 None
    domain_suffix: str    # contact 类 topup 用；启动 reset 用
```

5 条队列（名为最终定名，CLI/日志/DB 一致使用）：

| queue | site | 工作项 | 喂养方式 |
|---|---|---|---|
| `crawl_1688_contact` | 1688 | 一个店铺 contact | `topup_contact_work_items`（现状，`.1688.com`） |
| `crawl_mic_contact` | madeinchina | 一个店铺 contact | 同函数复用（`.cn.made-in-china.com`，已参数化） |
| `crawl_1688_shop` | 1688 | 一个类目一页 offer_search | feeder（§3.7） |
| `crawl_1688_company` | 1688 | 一个关键词一页 company_search | feeder（进度键 `company:` 前缀，现状沿用） |
| `crawl_mic_shop` | madeinchina | 一个类目一页 market | feeder（§3.7） |

`QueueRouter` 实现 Task 协议的队列侧职责：

- `acquire_item(ctx)`：三段式沿用 P0 结构——`claim_next_eligible` → 各队列 topup → condvar 挂起；认领成功后把 `(item_id, queue)` 记入 `ctx.state`，并将 `ctx` 绑定到该 item 的站点（见 §3.3 的「当前站点」）。
- `on_success`/`on_giveup`：路由到 item 所属队列的 `task`，然后 `finish_work_item` / `release_work_item`（§3.4）。
- 检测与策略按 item.site 切换：Engine 启动时为注册表涉及的每个 site 构建 `Policy`（含该站点 `policy_overrides`）；处理 item 时 `ctx.site`、`ctx.policy` 绑定到该 item 的站点插件与 Policy。**一个 item 的处理全程站点不变**。

不变式（结构保证，基准文档 §4.3）：一消费者一线程、同一时刻只处理一个工作项；一通道同一时刻只属于一个消费者 → 同一 (通道, 站点) 永不并发。

### 3.2 消费者资格与 claim_next_eligible

```python
def eligible_queues(consumer, now) -> list[str]:
    return [q.queue for q in registry
            if q.requires <= consumer.resources           # P3 全部为 {"channel","browser"}
            and now >= consumer.cooldown_until.get(q.site, 0)]
```

新增 `ShopDB.claim_next_eligible(queues, consumer_id)`：`BEGIN IMMEDIATE` 内 `WHERE status='pending' AND queue IN (...) ORDER BY id LIMIT 1` + 置 claimed，返回 `{"id","queue","site","payload"}`（payload 解码后字典）。跨队列只做 FIFO（按 id），不做优先级（基准文档 §11）。

挂起等待：condvar `wait(timeout=min(最近冷却到期剩余, 30s))`——30s 自醒兜底沿用 P0（外部 INSERT 无 notify，最坏 30s 发现）；冷却到期靠 timeout 自然醒来。board 状态行显示「等货/等冷却 mm:ss」。

### 3.3 冷却表改建与 chokepoint 让出

- `WorkerContext.cooldown_until` 键从 **reason 改为 site**（`dict[site, 到期时刻]`，仍为每 worker 内存）。P1 注释中「P3 调度器的查询接口」即本次落地；P1 只写不读，无存量读取者，改建安全。
- 「当前站点」：router 在 `acquire_item` 成功时写 `ctx.state["active_site"]`；`_cooldown` 写 `cooldown_until[active_site]`。reason 参数保留，仅用于日志/board 展示。
- `_cooldown` 语义二分：
  - **让出型**（样本间隔、批休、周期长休、策略冷却 block_rest 等）：登记 `cooldown_until[site] = now + seconds` 后**立即返回不等待**；loop 继续到下一轮 `acquire_item`，claim 过滤使该站点队列对本消费者不可见 → 自然转取其他队列。无货可取时 condvar 挂起（§3.2）。
  - **原地型**（launch 重试退避 `loop.py` launch_backoff）：在 item 处理装配中途、秒级、换队列无意义，保留 `ctx.wait` 原地等待。SPEC 裁定：原地型仅此一处，新增等待一律让出型。
- 中断残留：`cooldown_until` 纯内存，daemon 重启即清空（与现状一致——现状冷却也在内存）；残留过期值按「过期即无效」消费。
- 簿记键无需改动：P2 已把 ip_req/ip_stats/ip_events 按 `site:ip` 分桶。

### 3.4 work_items 挂起/重试语义

现状四态 `pending/claimed/done/failed` 够用，**不加新状态**；「挂起」= 释放回 pending。新增：

- 列：`attempts INTEGER NOT NULL DEFAULT 0`（`db.migrate()` 幂等 ALTER，PRAGMA table_info 探测模式）。
- `ShopDB.release_work_item(item_id, max_attempts=3) -> str`：`BEGIN IMMEDIATE` 内 attempts+1、清 claimed_by/claimed_at；`attempts >= max_attempts` 时置 `failed`（写 finished_at/result_json="attempts exhausted"），否则置 `pending`。返回终态供路由层记日志。
- 语义裁定：
  - 策略给出让出型冷却但 item 未完成（如 block_rest 后需重试）→ release（同 item 冷却后重试，attempts 计数熔断防无限循环）。
  - 策略链在 item 重领后从头开始（attempts 不跨认领保留策略链进度）——全局限速寄托于既有 (site,IP) 风控簿记与请求预算，不以单 item 链长为闸。
  - category 类 item 最终失败（attempts 耗尽）→ 路由层补插一条同 payload 新 item（attempts=0），保证类目链不死（§3.7）。

### 3.5 SwapIP 两阶段拆分

现状（P1 例外）：`SwapIPStrategy.run` 第一次 relaunch 未轮换 → 原地等 600~900s → 第二次 relaunch，等待夹在两次 relaunch 之间。

改造（无头模式）：

1. relaunch 未轮换 → 回写本站 Cookie、关闭本站 context（浏览器进程保留，其他站点 context 不受影响）、登记 `session.state["needs_relaunch"][site]=True`；
2. 输出让出型冷却 `uniform(block_rest_min, block_rest_max)`（青果 30 分钟轮换窗，参数沿用现状）；
3. 当前 item release 回 pending（§3.4）；
4. 该站点冷却到期后再次被认领时，context 懒建路径发现 `needs_relaunch` → 走完整 relaunch（全部 context 回写关闭 → 新进程绑轮换后新 IP → 懒建本站 context）。「第二次 relaunch」由此并入正常 launch 路径，无独立第二阶段代码。

裁定：

- **有头模式例外保留**：`WaitHumanLogin` 人工登录轮询需要活 page，维持原地等待不拆分（有头=人工辅助场景，利用率不是目标）；代码注释同步更新「P3 已拆无头路径」。
- 等待期间浏览器进程保留供其他站点使用（席位不空占），这是相对「关浏览器等轮换」方案的明确选择。

### 3.6 Session/BrowserManager 多 context 改造

**契约假设（动工前 spike 验证，见 §4 C1）**：CloakBrowser 席位按浏览器进程租约，一进程 N 个 context 只占 1 席。包源码证据：`license.py:368 get_active_session_count` + 退出码 76（session limit）；`launch()` 返回原生 Playwright `Browser`，`new_context()` 是进程内纯 Playwright API，服务端不可见。指纹/代理/WebRTC/时区均为**进程级 CLI 旗标**（`browser.py` `build_args`/`launch_context` 注释），同进程多 context 共享同指纹同出口——与「一消费者一通道一 IP」模型天然兼容（P2 已按 `site:ip` 分桶 Cookie/簿记）。

改造点：

- `Session` 从「单 browser+单 context+单 page」改为：持有 `browser`、`channel`、`req_proxies` + `views: dict[site, SiteView]`；`SiteView = {context, page, identity(=site:ip), seed_kit}`。
- **懒建**：router 绑定 item 站点时 `session.ensure_site(site)` 无 view 则创建（`browser.new_context(locale="zh-CN")` → 按 `site:ip` 装载 Cookie（空库播种种子/白板，沿用现状分支）→ new_page → warmup/冷启动标记）。`ctx.page`/`session.page` 路由到当前活动 site 的 view。
- **关闭语义**：`Session.close` 现状直接 `browser.close()`；改为两层——`close_site(site)`（回写本站 Cookie、关 context）与 `close()`（全部 site 回写后关 browser，daemon 退出/relaunch 用）。
- **relaunch**：全部 view 回写 Cookie → `browser.close()` → `launch()` 新进程 → 清空 views（懒重建）。`check_ip_fresh`/指纹种子仍按裸 IP（`bare_identity`），不变。
- **种子身份池**：`_alloc_seed_kits` 认领粒度从「每 worker 一份」改为「每 (worker, site) 一份」——`load_seed_kits(domain=站点cookie域)` 逐站点加载后按下标分配；种子 Cookie 播种落 `site:ip` 键（现状已是 identity 键，零改动）。`SeedBurnTracker` 键为 identity，天然分桶，零改动。
- 单 context 假设的消费方迁移（冲突扫描 §6 全清单）：`session.ctx` property、`browser_ops.RelaunchBrowser`、`WaitHumanVerify` 等取 `ctx.page` 的策略/原子——全部经「活动 site view」路由，禁止直接持有 page 引用跨 item 复用。

### 3.7 shop 类任务源队列适配（feeder 模式）

难点（侦察结论）：shop/company 任务源是「进程内 CategoryPool/KeywordPool + cold_start 探索式发现 + category_progress 页码表」，任务项自带 page_no。译为 work_items：

- **类目页工作项**：payload `{"kind":"category","keyword":..,"name":..}`（mic 另带 `"fmt":"market"|"plain"`）。**page_no 不进 payload**——认领时读 `category_progress.next_page`（单一事实来源沿用现状，多消费者不会同页撞车：同类目下一页 item 只在上一页成功后插入）。
- **发现工作项**：payload `{"kind":"discover"}`。执行 = 现状 `cold_start` 的类目提取（1688 首页 offer_search 关键词 + mtop 握手；mic 首页+市场导航页），新类目（不在 category_progress 且无同 keyword pending item）逐条 INSERT category item。
- **启动播种**：daemon 启动时每个 feeder 队列：① 从 `category_progress` 读未采完类目（新增统一查询 `iter_active_categories(prefix="")`，mic 沿用纯拼音 slug 过滤、company 用 `company:` 前缀）逐条插 category item；② 插一条 discover item。队列已有 pending 同类 item 时跳过（幂等，重启不重复播种）。
- **链式续喂**：category item `on_success` → `advance_category_page`/`mark_category_exhausted`（含 mic 的 ZERO_NEW_LIMIT=2 保护，原逻辑迁移）→ 未采完则 INSERT 下一页 item。最终失败按 §3.4 补插同 payload 新 item。
- **发现节奏**：v1 仅启动时播种 + discover item 执行一次；不做周期再发现（类目集合极少变化，重启 daemon 即触发）。裁定记录于此，后续需要再加。
- 进程内 CategoryPool/KeywordPool/ACQUIRE_WAIT_MAX 空转逻辑随接入**退役**（旧 CLI 路径同步改造见 §3.9 裁定）。

### 3.8 daemon CLI 与互斥修复

- `python -m fetcher daemon`：`--queue`（单值，P0 限制）替换为 `--queues`，nargs 多值 + choices=注册表键，**默认全部 5 条**；help 文案注明默认全量。`--queue` 删除（P0 仅手动使用、无平台调用方，不留 deprecated 别名）。
- 启动修复现存坑：`cli/main.py` daemon 分支的 `reset_in_progress()` 无 domain 过滤会重置所有站点 → 改为按注册表逐 site 调 `reset_in_progress(domain_suffix)`；`reset_claimed_work_items()` 全量保留（daemon 唯一写者）。
- 旧 CLI 站点子命令（`1688 shop` 等）保留可用（基准文档「P0~P3 期间旧 CLI 保持可用」）；feeder 改造涉及的 task 类以「item 处理逻辑可独立于内存池调用」为准重构，旧 CLI 的 acquire 路径改为从对应 work_items 队列认领（与 daemon 同一代码路径，避免双份流水线）。互斥约定不变：同站 daemon 与旧 CLI 不同时跑（README 已有说明，更新队列清单）。

## 4. 契约与行为后果（外部依赖假设表）

| # | 假设 | 依据 | 验证方式 |
|---|---|---|---|
| C1 | CloakBrowser 一进程多 context 只占 1 席位 | **已实测验证**（2026-08-08 spike，报告 `spike-cloakbrowser-multicontext.md`）：`get_active_session_count` 序列 n0=0 → launch n1=1（+1）→ new_context n2=1（不变）→ 第 2 context 内 goto n3=1（不变）→ close n4=0（-1），delta=1/0/-1 逐条命中；叠加包源码证据（`license.py:368` 会话计数 API、exit 76=session limit、`new_context` 为进程内 API） | **Phase 0 spike 已完成**（2026-08-08，P3-0 Step 0.1 验收通过；报告落本目录，结论已验证，P3-2 浏览器层可动工） |
| C2 | Playwright 多 context 间 storage state（Cookie/本地存储）完全隔离 | Playwright 官方文档（BrowserContext 独立存储契约） | 单测：同 browser 两 context 互不可见对方 Cookie |
| C3 | 同进程多 context 共享进程级指纹/代理旗标 | cloakbrowser `browser.py` build_args/launch_context 注释（已验证源码阅读） | 无需额外验证；设计已按「同指纹同出口」前提展开 |
| C4 | 青果隧道 30 分钟轮换窗 | 现状 SwapIP 策略注释与参数（生产经验） | 沿用现状参数，不重新标定 |
| C5 | `BEGIN IMMEDIATE` 原子认领在多消费者并发下无重复认领 | P0 已验证（test_work_items.py）+ SQLite WAL 语义 | 沿用既有测试模式补并发单测 |

## 5. 职责分配（初始化 + 变更路径）

| 状态 | 初始化 | 谁写 | 谁读 |
|---|---|---|---|
| `cooldown_until[site]`（每 worker 内存） | 空 dict | 唯一写入者：`_cooldown` chokepoint（让出型登记）；重启清空 | `eligible_queues`（claim 过滤）；board 状态行 |
| `ctx.state["active_site"/"daemon_work_item_id"/"queue"]` | router.acquire_item 成功时写 | router | `_cooldown`（取 site）、router.on_success/on_giveup（路由+回写） |
| `work_items.attempts` | 0（迁移默认） | `release_work_item`（+1/判失败） | release 内部熔断 |
| `work_items` 行（INSERT） | 启动播种 / topup / 链式续喂 / discover 产出 / 失败补插 | 上述各路径经 ShopDB 短事务 | claim_next_eligible |
| `Session.views[site]` | `ensure_site` 懒建 | BrowserManager（建/关/relaunch 清空） | loop/原子经 `ctx.page`（活动 view） |
| `session.state["needs_relaunch"]` | 空 | SwapIP 两阶段（置位）/ relaunch 完成（清除） | context 懒建路径 |
| `category_progress` | 现状存量 | 链式续喂（advance/exhausted） | 启动播种、category item 认领读 next_page |

## 6. 冲突扫描与裁定

1. **单 context 假设消费方全清单**（均有对应 Step 迁移）：`core/session.py` Session 定义/`ctx` property/`close`；`net/browser.py` launch/relaunch/warmup/save_cookies/check_ip_fresh；`atoms/browser_ops.py` RelaunchBrowser；`strategy/strategies.py` WaitHumanLogin/WaitHumanVerify/SwapIP；`control/loop.py` `_launch_with_retry`/`_relaunch`/`_ensure_fresh_ip`/`_check_budget`/`_cleanup`。迁移原则：一律经「活动 site view」路由。
2. **`cooldown_until` 键语义变更**：P1 只写不读、无存量消费方——安全改建；P1 留的注释（「reason 键」）同步更新。
3. **DaemonTaskProxy 替换**：消费方仅 `cli/main.py` daemon 分支 + `tests/test_daemon_task.py`；测试重写为 router 语义。`test_work_items.py` 保留并扩 attempts/release/claim_next_eligible 用例。
4. **`reset_in_progress` 无过滤坑**：daemon 启动改逐 site 过滤调用；madeinchina contact `prepare()` 的 reset 副作用确认带后缀过滤，不带则一并修。
5. **1688 shop `prepare()` 不从进度库播种**（与 mic 差异）：feeder 启动播种统一走 `iter_active_categories`，1688 shop/company 的进度恢复改由播种保证，不再依赖「首页重新提取同名类目命中 next_page」的隐式路径。
6. **策略链重领重置**（§3.4）：与现状「单 item 会话内链式升级」语义不同，裁定接受——全局限速在 (site,IP) 簿记与预算。
7. **有头 WaitHumanLogin 原地等待保留**（§3.5）：与「新增等待一律让出型」原则的例外，仅 SwapIP 有头路径 + launch 退避两处。
8. **引擎装配**：`Engine` 目前单 site 插件 + 单 Policy；daemon 分支改为注册表装配（每 site 一 Policy），站点 CLI 分支不受影响。
9. **平台零影响**：平台不读写 work_items（侦察确认零命中），attempts 列迁移对平台透明；identity 格式不变。
10. **席位预算**：solo=5 进程上限不变；多 context 不增加席位消耗（C1 实测背书后成立）。冒烟环境纪律：本机常有活爬虫占 2 席，测试 launch 控制在 +1 席以内。

## 7. 验收标准

- [x] 端到端证据：单通道 daemon（`--workers 1`）日志显示 madeinchina 冷却登记后、到期前，同 worker 认领并执行 1688 工作项；反向同样成立。**证据**：smoke-step6.1/ run.log（[claim]/[finish] 同秒手递手双向：mic_shop item=1 @19:12:42 → finish done → claim 1688_shop item=2 @19:12:57 → failed → claim mic_shop @19:13:02 回切；次冒烟 1688→mic→1688 三向同秒）+ run-double.log；Step 3.3 smoke-step3.3/ daemon-run-5.log（1688↔mic 两轮双向）。
- [x] 预算合规：日志中 ip_req 簿记显示同 (site,IP) 请求数不超各 task 的 `ip_request_budget`（mic shop=60、mic contact=80、1688 shop/company=12）。**证据**：smoke-step6.1/——1688:direct 4~7 req ≤ 12；madeinchina:direct 2 req ≤ 60/80。
- [x] 等价性：各队列产出（shops/contacts 写入、category_progress 推进）与旧 CLI 同路径代码一致（Step 4.2/5.2 冒烟真实落库、Step 5.2 旧 CLI 等价确认）；claim 无重复认领（并发单测 test_work_items.py + 冒烟 DB total=distinct=1057，无重域名）。
- [x] C1 实测报告落 plan 目录并回填 §4。**证据**：spike-cloakbrowser-multicontext.md（n0=0→1→1→1→0）。
- [x] 全量测试绿（现基线 309 passed + 新增 → 517 passed）。

## 8. 风险与回滚

- **风险：C1 实测证伪**（席位按 context 计）→ 多 context 方案作废，降级为「一消费者一浏览器单 context、跨站填充仍成立」（多队列/冷却让出/feeder 不受影响，仅每 consumer 席位消耗不变但跨站串行复用同一进程单 context，需每次切站重建 context 装载本站 Cookie）。Phase 0 先行就是为把此风险拦在浏览器层动工前。
- **风险：类目链喂养死锁/饿死**（全部 category item 失败、discover 已消费）→ 启动播种幂等，重启即恢复；链式补插兜底。
- **回滚**：P3 全程旧 CLI 路径可用；daemon 为手动拉起，main 上按 Phase 合并，任一 Phase 可独立 revert。
