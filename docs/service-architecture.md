# 1688 采集平台服务化改造方案

> 版本：v2 · 2026-08-01 · 已按实现同步（shadcn/ui、参数规格接口、任务事件流、loguru、随机启动等待）

## 1. 需求确认结论

| 议题 | 结论 |
|---|---|
| 部署形态 | 单机部署，仅本机 Mac 使用，单人无鉴权 |
| 有头浏览器/人工过滑块 | 保留现有流程（本机有显示环境） |
| 任务形态 | 前端手动创建任务；任务类型 = 店铺采集 / 联系方式抓取 |
| 并行 | 支持多任务同时并行；任务队列用 Celery |
| 数据浏览/导出 | 需要：店铺列表、联系方式列表（筛选分页）+ Excel/CSV 导出 |
| 直连模式 | 保留，IP 池中显示为"本机 IP"特殊条目 |
| 通道分配 | 全局共享池：系统统一管理通道，任务声明通道数，调度器分配，不足排队 |
| 代理厂商 | 可插拔 Provider 抽象；首期青果网络；密钥前端可配置 |
| 技术栈 | 后端 FastAPI + Celery + Redis + SQLite + loguru；前端 React + Vite + TS + Tailwind + shadcn/ui；实时推送 WebSocket |
| 数据迁移 | 沿用现有 .cache/1688.db，现有数据不丢 |

## 2. 总体架构

```
┌─────────────────────────── 本机 Mac ───────────────────────────┐
│                                                                │
│  浏览器 ──► React 前端 (Vite dev / 静态构建)                    │
│                 │  REST / WebSocket                            │
│                 ▼                                              │
│  FastAPI 后端 (uvicorn)                                        │
│   ├─ REST API: tasks / providers / pool / shops / export       │
│   ├─ WebSocket: /ws 实时进度 + IP 池状态推送                    │
│   ├─ ProxyPoolManager: 全局共享通道池（调度 + 状态 + 统计）      │
│   └─ 定时器: 出口 IP 探测、通道过期校准                          │
│                 │                                              │
│        Redis ◄──┼── Celery broker / 任务进度心跳                 │
│                 │                                              │
│  Celery worker 进程                                            │
│   ├─ task: shop_crawl     (改造自 shop_crawler.py)             │
│   └─ task: contact_fetch  (改造自 contact_fetcher.py)          │
│        │ 每个任务内按原有多线程模型起 CloakBrowser               │
│        ▼                                                       │
│  SQLite (.cache/1688.db, WAL) ◄── 所有进程共享                  │
└────────────────────────────────────────────────────────────────┘
```

关键决策说明：

- **SQLite 继续用**：单机 + WAL + busy_timeout（现有代码已具备），Celery worker 进程与 FastAPI 进程并发读写没有问题；不引入 PostgreSQL。
- **进度推送**：Celery 任务内定期把进度写库 + 写 Redis 心跳；FastAPI 的 WebSocket 端点聚合后推给前端。前端断线可降级为 2s 轮询 REST。
- **停止任务**：Celery `revoke` 只能杀还没开始的任务；运行中的任务走"协作式停止"——任务表加 `stop_requested` 标记，任务循环每轮检查，安全退出（浏览器正常关闭、Cookie 写回）。
- **共享池状态归属**：通道池状态必须只有一个权威来源。放在 FastAPI 主进程内存 + 落库，Celery 任务通过 REST/RPC 向池申请通道（`acquire/release`），不各自直连厂商 API。

## 3. 目录结构

```
1699/
├── docs/service-architecture.md     # 本文档
├── server/                          # 后端（新建）
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口 +  lifespan(启动池管理器/定时器)
│   │   ├── config.py
│   │   ├── db.py                    # SQLAlchemy session（指向 .cache/1688.db）
│   │   ├── models.py                # 新增表 ORM
│   │   ├── api/
│   │   │   ├── tasks.py             # 任务 CRUD / 启动 / 停止 / 进度查询
│   │   │   ├── providers.py         # 厂商配置 CRUD / 连通性测试
│   │   │   ├── pool.py              # IP 池状态 / 通道占用 / 使用统计
│   │   │   ├── shops.py             # 店铺 + 联系方式分页查询 / 导出
│   │   │   └── ws.py                # WebSocket 聚合推送
│   │   ├── services/
│   │   │   ├── proxy/
│   │   │   │   ├── base.py          # ProxyProvider 抽象接口
│   │   │   │   ├── qingguo.py       # 迁移自 util/proxy_qingguo.py
│   │   │   │   └── manager.py       # 全局共享池调度器
│   │   │   ├── usage.py             # 使用事件记录与聚合（近 N 分钟频率）
│   │   │   └── exporter.py          # Excel/CSV 导出
│   │   └── workers/
│   │       ├── celery_app.py        # Celery 实例（broker/backend = redis）
│   │       ├── shop_crawl.py        # Celery task：店铺采集
│   │       └── contact_fetch.py     # Celery task：联系方式抓取
├── web/                             # 前端（新建，React+Vite+TS+AntD）
│   └── src/
│       ├── pages/Tasks.tsx          # 任务列表 + 新建任务弹窗
│       ├── pages/Pool.tsx           # IP 池监控
│       ├── pages/Providers.tsx      # 厂商密钥配置
│       ├── pages/Data.tsx           # 店铺/联系方式浏览 + 导出
│       └── pages/Dashboard.tsx      # 总览
├── scraper/ util/                   # 现有脚本（原样保留，不被 server import，仅作逻辑参考与独立 CLI 兜底）
└── .cache/1688.db                   # SQLite（沿用，迁移加新表）
```

## 4. 数据库设计（新增表，沿用现有 5 张表不动）

> 实现后新增第 5 张表 `task_events`（任务实时事件：`id / task_id / ts / level(info|success|warning|error) / message / data_json`，索引 `(task_id, id)`，每任务保留最近 500 条）。

```sql
-- 代理厂商配置（密钥前端可编辑；单机明文存储，界面上密码字段掩码显示）
CREATE TABLE providers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,           -- qingguo / 未来厂商标识
    name        TEXT NOT NULL,           -- 显示名，如 "青果-长效动态"
    config_json TEXT NOT NULL,           -- {key, auth_key, auth_pwd, channels, area, isp}
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 通道（一条 = 厂商的一个通道/隧道入口；直连是 kind='direct' 的特殊行）
CREATE TABLE proxy_channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id  INTEGER REFERENCES providers(id),  -- NULL = 直连
    tunnel       TEXT,                 -- 隧道入口 host:port（直连为空）
    exit_ip      TEXT,                 -- 最近探测到的出口 IP（直连=本机 IP）
    status       TEXT NOT NULL DEFAULT 'idle',  -- idle / in_use / error
    used_by_task INTEGER REFERENCES tasks(id),
    ip_expires_at TEXT,                -- 出口 IP 预计轮换/过期时间（青果=上次轮换+30min）
    last_probe_at TEXT,
    UNIQUE(provider_id, tunnel)
);

-- 任务（业务层任务记录，与 Celery task_id 关联）
CREATE TABLE tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT NOT NULL,       -- shop_crawl / contact_fetch
    params_json   TEXT NOT NULL,       -- {target, category, workers, channels, proxy, headed...}
    celery_id     TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
                  -- pending / waiting_channel / running / stopping / done / failed / stopped
    progress_json TEXT,                -- {collected, pending, per_minute, ...} 任务内周期更新
    stop_requested INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    TEXT NOT NULL,
    started_at    TEXT, finished_at TEXT
);

-- 通道使用事件（算"近 N 分钟请求数/频率"的原始数据，定期清理旧数据）
CREATE TABLE proxy_usage_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES proxy_channels(id),
    task_id    INTEGER REFERENCES tasks(id),
    task_type  TEXT,
    exit_ip    TEXT,                   -- 事件发生时的出口 IP
    result     TEXT,                   -- ok / blocked / error
    ts         TEXT NOT NULL
);
CREATE INDEX idx_usage_ts ON proxy_usage_events(ts);
CREATE INDEX idx_usage_channel_ts ON proxy_usage_events(channel_id, ts);
```

## 5. 代理 Provider 抽象

```python
# server/app/services/proxy/base.py
class ProxyProvider(Protocol):
    kind: str                                # "qingguo"
    config_schema: dict                      # 前端动态渲染配置表单用

    def validate(self, config: dict) -> None: ...          # 校验密钥格式
    def test_connectivity(self, config: dict) -> dict: ... # 前端"测试"按钮
    def sync_channels(self, config: dict) -> list[Channel]: ...
        # 校准通道列表：青果 = .cache 缓存 -> /query 在用 -> /get 补齐（现有逻辑）
    def make_proxies(self, channel: Channel, config: dict) -> dict: ...
    def exit_ip_ttl(self, config: dict) -> int: ...        # 出口 IP 存活秒数（青果 1800）
```

- 青果实现整体迁移 `util/proxy_qingguo.py` 的 `ChannelPool`/`_api_get`/错误码逻辑，密钥从 `providers.config_json` 读，不再硬编码。
- 新增厂商 = 新增一个 provider 模块 + 注册进 `PROVIDER_REGISTRY`；前端配置表单由 `config_schema` 驱动，无需改前端代码。

## 6. 全局共享池调度器（ProxyPoolManager）

运行在 FastAPI 主进程，线程安全，状态落 `proxy_channels` 表：

- `acquire(task_id, n) -> list[Channel]`：空闲通道充足则标记 `in_use` 并返回；不足则返回空，任务置 `waiting_channel` 状态进入等待队列，有通道释放时按任务创建顺序唤醒。
- `release(task_id)`：任务结束/停止/异常时释放全部占用（API 层 finally + 任务心跳超时兜底，防止 worker 崩溃导致通道泄漏）。
- 直连视为一条永远 idle 可用的特殊通道（不互斥，但使用事件照常记录）。
- **出口 IP 探测**：主进程定时器每 60s 逐通道经代理请求 `ipinfo.io/json`（可配置开关与频率），更新 `exit_ip` 与 `ip_expires_at`（青果按"探测到 IP 变化 +30min"推算轮换时间）。
- **使用统计**：Celery 任务每次请求经池上报一条 `proxy_usage_events`（或批量上报）；前端"近 5 分钟请求数 / 频率"= 按 channel_id 窗口聚合。事件表保留 7 天，定时清理。

## 7. Celery 任务实现（已上线）

- `celery_app.py`：broker/backend 均为本地 Redis（owner 的 Docker 容器，6379）；worker 用 `--pool=threads --concurrency=8`；每个 Celery task 内部沿用多线程 worker 模型。
- **shop_crawl task**：`target` 语义为**本任务新增店铺数**（非库累计）；超采语义——整页提取全部入库、采完本轮再判停（owner 明确保留）。流程：启动等待 → 申请通道 → 有头引导浏览器 → 人工确认（`POST /api/tasks/{id}/confirm`，10min 超时）→ 多线程按类目分页采集 → 周期写 `progress_json` + Redis 心跳 → 每轮检查 `stop_requested`。
- **contact_fetch task**：认领逻辑沿用 `claim_pending_shops()` 原子认领；`limit` 为本任务处理数。
- **启动前等待**：`start_delay_min` / `start_delay_max`（默认 0；相等=固定，不等=区间内随机抽取一次），倒计时期间不占通道、可停止。
- **节奏参数全部区间随机**：页间 `delay_min/max`、长休 `rest_every + rest_min/max`、批间 `batch_rest ±10%` 抖动。
- **参数规格接口**：`GET /api/tasks/param-specs` 返回两类型全部参数定义（label/type/default/min/max/help/group），前端表单由它动态渲染；workers/channels 默认 1。
- **任务事件流**：`task_events` 表（每任务留 500 条）+ `GET /api/tasks/{id}/events?after_id=` 增量拉取 + WS 上行 `{"subscribe_task": id}` 订阅 `task_event` 帧；两个任务共 30+ 埋点（四级 info/success/warning/error）。
- **日志**：全后端 loguru——彩色 stderr + `server/logs/server.log`（50MB 滚动、14 天保留、enqueue 进程安全），uvicorn/celery 标准 logging 经 InterceptHandler 桥接。
- **重写而非复用**：现有 `scraper/`、`util/` 脚本原样保留、**不被 server import**；server 内的实现按相同逻辑重新编写，两个 CLI 脚本保持独立可用（调试/兜底）。

## 8. API 设计（FastAPI）

```
POST   /api/tasks                 创建任务（校验参数 → 入库 pending → celery.send_task）
GET    /api/tasks                 任务列表（含 progress）
GET    /api/tasks/{id}            任务详情（含 board：按类型现算的看板数据）
POST   /api/tasks/{id}/stop       置 stop_requested + revoke 兜底
POST   /api/tasks/{id}/confirm    有头任务人工确认（替代 CLI 终端 input）
GET    /api/tasks/param-specs     两类型参数定义（前端表单动态渲染）
GET    /api/tasks/{id}/events?after_id=&limit=  任务事件增量拉取
GET    /api/providers             厂商列表（另：GET /api/providers/kinds 返回 config_schema）
POST   /api/providers             新增厂商配置
PUT    /api/providers/{id}        修改密钥/参数
POST   /api/providers/{id}/test   连通性测试（返回 {ok,message,channels,exit_ip,latency_ms}）
POST   /api/providers/{id}/sync   校准通道
GET    /api/pool/channels         通道列表（含占用任务、出口 IP、过期时间、近5min请求数、freq_5m）
GET    /api/pool/usage?minutes=5  使用统计聚合
POST   /api/pool/acquire|release|events   通道申请/释放/使用上报（worker 侧调用）
GET    /api/shops?status=&category=&keyword=&page=  店铺分页
GET    /api/contacts?keyword=&page=                 联系方式分页
GET    /api/export/shops.xlsx|csv?status=&category=&keyword=  导出（openpyxl / 带 BOM CSV）
GET    /api/export/contacts.xlsx|csv?keyword=
GET    /api/stats/overview        Dashboard 总览（8 字段 + rate_last_hour 60 点）
WS     /ws                        下行 {task_progress, pool_status, task_event}，1s 节流；
                                  上行 {"subscribe_task": id, "after_id": n} 订阅任务事件
```

## 9. 前端页面（React + Vite + TS + Tailwind + shadcn/ui）

1. **Dashboard**：总店铺数、待抓取数、今日新增、运行中任务数、通道占用比、近 1 小时采集速率曲线。
2. **任务页**：任务表格（类型/状态标签/进度条（封顶100%）/已采/待采/每分钟速率/耗时/操作）；行点击进详情；"新建任务"Dialog 按 `param-specs` 动态渲染（分组成折叠区：基本/浏览器/节奏控制/重试策略，非默认值高亮）。
3. **任务详情页** `/tasks/:id`：公共看板（已采集/目标/剩余/速率/时长/ETA + 大进度条）+ 占用通道卡 + 类型专属区（shop_crawl：类目分页进度表；contact_fetch：全库状态分布堆叠条 + 本任务成功/失败）+ **实时事件控制台**（终端风深色面板，四级配色，历史 200 条 + WS 增量，自动跟随滚动，级别筛选）+ 参数卡 + 错误 Alert；运行中 2s 轮询刷新，终态停止。
4. **IP 池页**：按厂商分组 Tab；通道表格（隧道入口、当前出口 IP、状态、占用任务类型+ID、近 5 分钟请求数、频率迷你趋势图、过期倒计时）；直连"本机 IP"置顶显示。
5. **厂商配置页**：厂商卡片列表；新增/编辑弹窗（按 provider 的 config_schema 渲染，密码字段掩码）；"测试连通性"按钮实时返回结果。
6. **数据页**：店铺 Tab + 联系方式 Tab；状态/类目/关键词筛选，分页；导出 Excel/CSV 按钮（带当前筛选条件）。

实时更新统一走 `/ws`（含 subscribe_task 事件订阅），断线自动重连并降级轮询。

## 10. 实施里程碑

| # | 内容 | 产出 |
|---|---|---|
| M1 | 后端骨架 + DB 迁移 | FastAPI 起服务，新表落库，现有 1688.db 数据无损 |
| M2 | 代理层 | Provider 抽象 + 青果迁移 + 密钥入库 + 连通性测试 API |
| M3 | 共享池调度器 | acquire/release/等待队列 + 出口 IP 探测 + 使用统计 |
| M4 | Celery 任务 | 两个 task 在 server 内重写完成，逻辑与 CLI 脚本等价，进度/停止打通 |
| M5 | REST + WebSocket | 全部 API 完成 |
| M6 | 前端五个页面 | 联调通过 |
| M7 | 收尾 | `start.sh` 一键启动（redis + celery + uvicorn + web）、README、旧数据回归验证 |

## 11. 风险与注意点

- **SQLite 写竞争**：多 worker 高频写 usage 事件 → 批量插入 + WAL；若实测瓶颈，usage 事件可改走 Redis 缓冲再批量落库。
- **通道泄漏**：worker 崩溃可能残留 `in_use` → 任务心跳超时（如 90s 无心跳）自动回收通道。
- **探测消耗**：出口 IP 探测走代理请求，频率可配，默认 60s/通道，5 通道开销可忽略。
- **青果轮换与 Cookie 错配**：沿用现有"Cookie 按出口 IP 隔离"策略，池探测到出口 IP 变化时通知任务侧该 IP 的 Cookie 已失效，需重新过验证（README 已有此经验）。
- **密钥安全**：单机明文存库，前端掩码显示；不引入加密复杂度（如需可加 macOS Keychain 存储，留作后续可选项）。
