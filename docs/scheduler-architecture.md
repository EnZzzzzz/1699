# 资源感知调度器架构设计（队列 + 消费者池 + 观测事件）

> 版本：v1 · 2026-08-07 · 设计基准文档
> 关联文档：docs/flow-architecture.md（原子能力 + DAG 流水线；本文档把「跨任务编排」从该文档的非目标提升为正式目标，落地时同步修订其 §2/§10）
> 动机：当前一任务一进程、一 worker 独占一个通道，样本间隔/批休/风控冷却期间出口 IP 完全闲置；同时任务类型在增多（浏览器采集、facebook API、wa_check），需要一个统一的执行底座。

## 1. 需求确认结论

| 议题 | 结论 |
|---|---|
| 核心目标 | ① 出口 IP 利用率拉满：某站点冷却期间，同一通道可执行其他站点/类型的工作；② 新任务类型（API 类、本地类）接入不需要新架构 |
| 核心抽象 | **工作项（WorkItem）+ 资源需求 + 消费者（Consumer）**；调度器只做一件事：把空闲消费者和满足其资源约束的队首工作项配对 |
| 分派模式 | **拉模式**（消费者主动取）。推模式/pub-sub 表达不了「本通道对站点 X 仍在冷却」，禁止用于工作分派 |
| 事件总线定位 | 只做**观测通知**（进度、风控事件、SSE 推送），复用现有 `task_events` + SSE；不做工作分派 |
| 外部 MQ | **不引入**（Redis/Celery/RabbitMQ）。核心调度约束（通道独占、per-site 冷却、浏览器席位）是非标的，MQ 表达不了；SQLite + 原子认领足够 |
| 滑块等会话内处置 | **不上总线**。滑块/换 IP/风控修复需要活的 page 对象与会话链路，留在原子层、会话内完成（沿用 flow-architecture 的原子契约） |
| 执行模型 | 单 dispatcher 常驻进程（`python -m fetcher daemon`），消费者为线程；原子保持同步执行，**不做 asyncio 重写** |
| 身份模型 | `identity` 从「出口 IP」升级为「(出口 IP, site)」二元组，Cookie/指纹/风控簿记/请求预算按站点分桶 |

## 2. 现状与问题（改造依据）

- 一任务一进程：平台 `runner.py` 拼 CLI → `Popen` 一个 fetcher 子进程；进程内 N 个 worker 线程（`control/engine.py:189`），一 worker 一通道独占（`engine.py:60-78` `_alloc_workers`）。
- 等待全部内联在持有通道的 worker 线程里：样本间隔 13~20s（`control/loop.py:194-200`）、批休 900s±10%（`loop.py:123-141`）、周期长休 60~180s（`loop.py:203-213`）、风控原地休息 600~900s（`strategy/strategies.py:53-67`）、换 IP 等轮换 600~900s（`strategies.py:114-129`）。等待期间 IP 纯闲置。
- 通道分配无全局协调：`QingGuoProvider.acquire()` 是进程内轮询游标（`net/proxy/qingguo.py:197-205`）；两个并发任务的子进程读同一隧道缓存、各自从游标 0 开始 → **不同任务的 w0 会撞同一个出口 IP 且互不知晓**。`proxy_channels.used_by_task` 租约字段已在 schema 中但零写入者。
- 身份即 IP：`Session.identity = 出口 IP`（`core/session.py:29`），Cookie（`net/identity.py`）、指纹种子、风控簿记（`loop.py:399-446`）、请求预算（madeinchina shop=60页/IP、contact=80/IP）全部按 IP 记账。
- CloakBrowser 席位是全局硬上限（`net/browser.py:46`，solo=5），超限 exit 76。

关键判断：**跨站点共享 IP 是安全的**——风控、预算、Cookie 实际都按 (站点, IP) 生效，1688 看不到该 IP 在爬 madeinchina；**同站点双执行流共享 IP 是危险的**——预算翻倍、同指纹双会话、Cookie 互踩/burn。调度器的约束设计据此展开。

## 3. 分层架构

```
┌────────────────────────────────────────────────────────┐
│ 平台层  platform/server：任务=批次提交，监控/停止/进度展示    │
├────────────────────────────────────────────────────────┤
│ 调度层  Dispatcher（fetcher daemon，单进程常驻）             │
│         工作队列（DB）· 消费者池 · 资源匹配 · 冷却表          │
├────────────────────────────────────────────────────────┤
│ 执行层  消费者三类：                                       │
│         BrowserConsumer（通道+浏览器席位+站点冷却表）          │
│         HttpConsumer（可选通道，无浏览器）                    │
│         LocalExecutor（wa_check 等，无外部资源）              │
├────────────────────────────────────────────────────────┤
│ 原子层  Atom Registry（不变）：fetch/solve_slider/swap_ip/…  │
│         原子只报告 Outcome，不 sleep、不决策                  │
├────────────────────────────────────────────────────────┤
│ 资源层  通道池 · CloakBrowser（席位上限）· ShopDB · 冷却策略  │
├────────────────────────────────────────────────────────┤
│ 观测层  task_events + progress_json + SSE（=事件总线，只读）  │
└────────────────────────────────────────────────────────┘
```

与现状的映射：

- `engine.py`「一进程一 task、worker 固定绑定」退役；`CrawlLoop` 里单 item 的抓取流水线（认领→IP 保鲜→fetch→簿记）原样保留，变成 BrowserConsumer 处理一个工作项时执行的 body。
- `wa_tasks.py` 进程内执行器是 LocalExecutor 的雏形，从 runner 搬进 dispatcher。
- 策略层（`strategies.py`）不再执行 sleep，改为**输出冷却时长**，交给消费者的冷却表执行。

## 4. 核心概念

### 4.1 工作项（WorkItem）

```python
@dataclass
class WorkItem:
    id: int
    queue: str              # "crawl_1688" / "crawl_mic_contact" / "fb_api" / "wa_check" / ...
    site: str | None        # 浏览器类必填，用于冷却表与 identity 分桶
    payload: dict           # 工作参数（如 shop_id / 号码批次）
    batch_id: int           # 所属批次（= 平台任务），进度/停止的粒度
    requires: set[str]      # 资源需求：{"channel","browser"} / {"channel"} / set()
    status: str             # pending / claimed / done / failed / skipped
```

- 平台「创建任务」= 往指定队列批量插入工作项（一个 batch）。用户体验不变：进度按 batch 统计，停止按 batch 广播。
- 工作项的认领沿用现有 `BEGIN IMMEDIATE` 原子模式（`db.py` `claim_pending_shops`），多消费者并发安全。

### 4.2 消费者（Consumer）

```python
class Consumer:
    id: str
    resources: set[str]         # 本实例持有的资源，如 {"channel","browser"}
    channel: Channel | None     # BrowserConsumer 独占一个通道
    cooldown_until: dict[str, float]   # site -> 冷却到期时刻（仅浏览器类）

    def eligible(self, item: WorkItem, now: float) -> bool:
        if not item.requires <= self.resources:
            return False
        if item.site and now < self.cooldown_until.get(item.site, 0):
            return False
        return True
```

三类消费者的资源配置：

| 消费者 | resources | 数量上限 | 说明 |
|---|---|---|---|
| BrowserConsumer | `{channel, browser}` | min(通道数, CloakBrowser 席位) | 一实例一通道独占；内部按 site 各开一个 BrowserContext |
| HttpConsumer | `{channel}` 或 `{}` | 配置值（如 2~4） | 纯 API 任务；绑定通道时同样维护冷却表 |
| LocalExecutor | `{}` | 配置值 | wa_check 等；无需通道/浏览器 |

### 4.3 冷却表（cooldown_until）

- 每消费者维护 `site -> 到期时刻`。冷却未到期 = 该消费者对该站点队列**不可见**，自然转去取其他队列——这就是「等待时间被其他任务填满」的实现机制，无需任何显式配对逻辑。
- 冷却时长由**策略层**根据本次执行 Outcome 计算（见 §6），原子本身不 sleep。
- 同站点约束由结构保证：一个通道同一时刻只属于一个消费者，一个消费者同一时刻只处理一个工作项 → 同一 (通道, 站点) 永不并发。

### 4.4 观测事件（事件总线）

- 工作项状态变更、冷却设置、风控触发、批次进度 → 写 `task_events`（data_json 带 `batch_id / consumer_id / queue`）+ 更新 `progress_json` → SSE 推送前端。
- 这层是纯粹的发布侧，消费者状态不依赖任何事件回传，总线挂掉不影响执行正确性。

## 5. 调度循环

```python
# Dispatcher 主循环（事件驱动，条件变量唤醒，无轮询空转）
cv = threading.Condition()

def on_wakeup_source():       # 三个唤醒源：新工作项入队 / 冷却到期定时器 / 消费者空闲
    with cv:
        cv.notify_all()

def consumer_loop(consumer):
    while not stop.is_set():
        item = queues.claim_next_eligible(consumer)   # DB 原子认领，按批次优先级/入队序
        if item is None:
            with cv:
                cv.wait(timeout=seconds_to_nearest_cooldown_expiry(consumer))
            continue
        result = run_pipeline(consumer, item)         # 站点/类型对应的流水线（原子组合）
        cooldown = policy.cooldown_for(item.queue, result.outcome)
        if item.site:
            consumer.cooldown_until[item.site] = now() + cooldown
        queues.finish(item, result)                   # 状态落库 + 观测事件
```

约束与细节：

- `claim_next_eligible` 的 SQL 过滤：只查 `consumer.eligible` 为真的队列；浏览器类站点队列用内存冷却表过滤（不进 SQL）。
- **长阻塞工作项**（滑块自愈、风控修复可能原地跑 10 分钟+）期间该消费者对其他队列不可用——v1 接受（仍远优于现状纯睡）；v2 可考虑修复类操作「换通道继续」而非原地等。
- 消费者异常崩溃：工作项 `claimed` 超租约时间未 finish → 调度器回收重置为 `pending`（租约字段 + 心跳）。
- 停止语义：平台停止批次 → 该批次 pending 项直接标记 `stopped`，claimed 项跑完当前项后不再取新项（协作式，沿用现有 stop Event 模式）。
- daemon 退出：各消费者回写 Cookie、关浏览器、释放通道（沿用 `Session.close` 语义）。

## 6. 冷却策略表（现有 sleep 的迁移映射）

| 现有等待 | 位置 | 迁移后 |
|---|---|---|
| 样本间隔 13~20s（按 worker 错峰） | `loop.py:194-200` | outcome=ok → 冷却 uniform(sample_min, sample_max)，错峰由多消费者天然成立 |
| 批休 900s±10% | `loop.py:123-141` | 批次计数满 n → 冷却 uniform(810, 990) |
| 周期长休 60~180s / 20 个 | `loop.py:203-213` | 计数器触发 → 冷却 uniform(60,180) |
| 风控原地休息 600~900s | `strategies.py:53-67` | outcome=blocked → 冷却 uniform(600,900)（保 IP 冷却语义） |
| 换 IP 等轮换 600~900s | `strategies.py:114-129` | 换 IP 原子执行后出口未轮换 → 冷却对应时长 |
| 网络错误退避 30~180s | `strategies.py:47-50` | outcome=net_error → min(30×attempt, 180) |
| 页面渲染等待 2~5s | 站点插件内 `time.sleep` | 保留在原子内（属于执行过程，非调度间隔） |
| worker 启动错开 15~60s | `engine.py:198-201` | 消费者启动时一次性冷却 |

- 所有冷却参数进配置（站点插件声明默认值，平台可覆盖），单位统一秒。
- 请求预算（如 60 页/IP）保持按 (IP, site) 记账，达预算 → 触发换 IP 原子 + 长冷却，与现状一致。

## 7. identity 改造（(IP) → (IP, site)）

改动点：

- `Session.identity` 增加 site 维度：实际键为 `f"{site}:{ip}"`（直连为 `f"{site}:direct"`）。`core/session.py` 注释与默认值同步更新。
- `IdentityStore`（`net/identity.py`）：load/save/burn 全部带 site 键；burn 只烧对应站点的 Cookie，不殃及同 IP 其他站点。
- 风控簿记（`loop.py:399-446` 的 ip_req/ip_stats/ip_events）：表加 site 列或键拼 site 前缀（走 `app.db.migrate()` 幂等迁移，防御性探测）。
- 指纹种子按 (site, IP) 生成；BrowserConsumer 内每站点一个独立 BrowserContext（独立 storage state），共享一个浏览器进程以缓解席位压力——**需实测 CloakBrowser 席位按进程还是按 context 计数**（若按 context，则退为一站一浏览器，消费者数量受席位硬约束）。
- 种子身份池（`engine.py:80-111`）：认领粒度改为 (消费者, site)。

## 8. 存储设计（新增表，走幂等迁移）

```sql
-- 工作项队列
CREATE TABLE work_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    queue       TEXT NOT NULL,            -- crawl_1688 / crawl_mic_contact / fb_api / wa_check ...
    site        TEXT,                     -- 浏览器类必填
    batch_id    INTEGER NOT NULL REFERENCES tasks(id),
    payload_json TEXT NOT NULL,
    requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/claimed/done/failed/stopped
    claimed_by  TEXT,                     -- consumer id
    claimed_at  TEXT,                     -- 北京时间字符串
    finished_at TEXT,
    result_json  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_work_items_claim ON work_items(queue, status, id);
```

- `tasks` 表语义微调：type=队列批次时，`params_json` 存 `{queue, item_count, ...}`；进度=该批次 work_items 的状态聚合，无需新进度表。
- `proxy_channels.used_by_task` 改为 `used_by_consumer`（daemon 内消费者id），daemon 启动时原子认领全部可用通道，退出释放——**跨进程撞通道问题随「单 dispatcher 持有全部通道」自然消失**；若未来多 dispatcher，再升级为 DB 租约。
- 时间戳沿用北京时间字符串；写库短事务 + `PRAGMA busy_timeout = 30000`。

## 9. 平台侧集成

- runner 新增 daemon 管理：`start.sh` 拉起 `python -m fetcher daemon`（常驻，与 uvicorn 同级），停止/重启走 pidfile；daemon 输出行泵入 `task_events` 的机制沿用。
- `TASK_COMMANDS` 中浏览器采集类任务从「拼 CLI 起子进程」改为「INSERT work_items 批次」；API 类/本地类同理。wa_check 从 runner 进程内线程迁入 dispatcher 的 LocalExecutor。
- API 变更：`POST /api/tasks` 创建批次；`GET /api/tasks/{id}` 进度响应增加 `queue` 维度统计与消费者分配情况；新增 `GET /api/dispatcher/consumers`（消费者列表：通道、当前工作项、各站点冷却剩余）用于前端看板。
- 前端（另按 DESIGN.md 实施）：批次详情页展示工作项队列进度；新增消费者看板（每通道当前在干什么、各站点冷却倒计时——正好复用 flow-architecture §8 的 Sleep 环形进度设计）。

## 10. 落地路线

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 daemon 骨架 | work_items 表 + Dispatcher + 条件变量调度循环 + BrowserConsumer（单站点 1688）；CLI 新增 `daemon` 子命令 | 单站点行为与现有 CLI 等价（节奏、产出、事件口径一致） |
| P1 冷却策略迁移 | `strategies.py` 的 sleep 全部改为输出冷却时长；`loop.py` 流水线原子化改造 | 同一批次总耗时、请求节奏分布与旧实现相当 |
| P2 identity 分桶 | (IP,site) 键改造 + BrowserContext 隔离 + 簿记表迁移 | 同 IP 两站点 Cookie/簿记互不污染（单测覆盖） |
| P3 第二站点接入 | madeinchina 队列接入，跨站填充生效 | 同通道 madeinchina 冷却期间执行 1688 工作项，两边各自预算不超标 |
| P4 平台切换 | runner 改批次提交、wa_check 迁入、API + 前端看板 | 平台创建/停止/监控全流程走 dispatcher |
| P5 退役旧路径 | 旧 subprocess 采集路径冻结→删除；修订 flow-architecture.md §2/§10 | 旧代码路径删除，文档同步 |

每个阶段独立可回滚：P0~P3 期间旧 CLI 路径保持可用，灰度对比等价后再切。

## 11. 明确的非目标（v1 不做）

- 多 dispatcher 分布式部署（单机单 dispatcher；DB 租约字段预留）
- asyncio 重写（同步线程模型足够，瓶颈在调度不在并发原语）
- pub/sub 式工作分派（工作分派一律拉模式）
- 滑块等会话内处置的服务化/远程化
- 优先级抢占（正在执行的工作项不被抢占；批次间只做 FIFO+简单优先级）
- 可视化 DAG 编排（仍归 flow-architecture 的 v2 范围，调度器只消费队列，不关心流水线内部拓扑）
