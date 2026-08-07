# SPEC — fetcher daemon 骨架（P0）

> 上游设计：docs/scheduler-architecture.md（§10 落地路线 P0）
> 本文档是 P0 的需求与设计唯一来源；评审通过后相对稳定，变更在文末「变更记录」追加。

## 1. 背景与目标

当前 fetcher 一任务一进程、一 worker 独占一个通道，等待（样本间隔/批休/风控冷却）全部内联在持有 IP 的 worker 线程里，出口 IP 大量闲置。scheduler-architecture 给出的终态是「队列 + 资源感知调度器 + 消费者池」。

**P0 的目标只有一个：把 daemon 骨架立起来，并证明它与现有 CLI 行为等价。**

- work_items 表（SQLite，原子认领）；
- `python -m fetcher daemon` 常驻子命令；
- 消费者线程从 work_items 拉工作项，空队列时挂条件变量等待（而非退出）；
- 首接一个队列：`crawl_1688_contact`（1688 联系人提取）——它的现有 claim 模型（DB 原子认领 shops 行）与 work_items 天然 1:1，适配成本最低。

验收口径：**同参数下 daemon 模式与 `python -m fetcher 1688 contact` 的请求节奏、抓取结果、DB 落库口径一致**（事件序列允许日志格式差异）。

## 2. 范围与非目标

### 2.1 范围（P0 做）

1. `work_items` 表进 `fetcher/db.py` 的 `SCHEMA`（幂等建表）+ 配套 DB 方法（top-up / claim / finish / reset）。
2. daemon 子命令与装配：复用 `Engine`（通道分配、种子身份、错开启动、信号处理全部沿用），通过注入自定义 loop/task 包装实现常驻。
3. `crawl_1688_contact` 队列的按需补货（feeder）：消费者取不到工作项时，从 `shops` 表 pending 行补入 work_items（同事务标 `in_progress`，与现有 claim 语义一致）。
4. 单元测试 + 运行时冒烟（`--limit N` 跑有限数量后退出）。

### 2.2 非目标（P0 明确不做）

- **冷却策略迁移**（sleep → 冷却时长输出）：P1。P0 的 `CrawlLoop` 保持现有 sleep 不动，这是「行为等价」验收的前提。
- **跨站点填充 / 多队列调度**：P3。P0 只有一个队列，消费者资格判断退化为「队列里有没有项」。
- **1688 shop / company 队列适配**：两者的工作项是「关键词的一页」，依赖进程内 CategoryPool/KeywordPool，需要单独的适配层，排期在 P3 前另立计划。
- **identity (IP,site) 分桶**：P2。
- **平台侧任何改动**（runner 批次提交、API、前端）：P4。P0 的 daemon 只从 CLI 启动。
- **task_events / SSE 观测**：平台表，P4 接入；P0 沿用现有 stdout/StatusBoard 输出。
- **多 dispatcher**：单 dispatcher 持有全部通道，跨进程撞通道问题以「同一时刻只跑一个 daemon」为约束，文档化即可。

## 3. 关键设计

### 3.1 总体结构：Engine 复用 + Task 包装，不新写调度器

调研结论：`Engine`（`control/engine.py`）已具备 daemon 需要的全部装配能力——每 worker 独立 ShopDB/BrowserManager、一 worker 一通道、种子身份池、错开启动、SIGTERM/SIGHUP 优雅退出，且构造器预留了 `loop_factory` 注入点。`CrawlLoop` 唯一不符合 daemon 语义的地方是「`acquire_item` 返回 None 即退出」。

因此 P0 不新写调度循环，而是：

```
python -m fetcher daemon
  └─ main() 新增 daemon 分支（与 site 子命令平级，复用 config_from_args/make_provider/Policy 装配段）
       └─ Engine(cfg, task=DaemonTaskProxy(inner=ContactTask, queue="crawl_1688_contact"),
                 site=alibaba1688, provider=..., policy=...).run()     # 完全复用
            └─ 每 worker: CrawlLoop(ctx, DaemonTaskProxy).run()        # loop 本体不动
                 └─ acquire_item() → 阻塞式：claim work_items → 空则按需 top-up →
                    仍空则条件变量 wait（唤醒源：top-up 补到货 / stop 置位）
```

- `DaemonTaskProxy` 实现 Task 协议（`control/task.py`），除 `acquire_item` / `prepare` / `after_item` 外全部透传 inner task。fetch/on_success/簿记/节奏全部由现有 `ContactTask` + `CrawlLoop` 执行——**等价性由此结构性保证**，而不是靠测试逐个对。
- 条件变量在 proxy 内部（`threading.Condition`），唤醒源两个：本进程任意消费者 top-up 补到货后 `notify_all`；`stop` Event 置位后由超时 wait（兜底 30s 自醒检查 stop）退出。P0 没有「外部入队」路径，不需要进程外唤醒。

### 3.2 work_items 表与 DB 方法

DDL 进 `fetcher/db.py` 模块级 `SCHEMA`（`CREATE TABLE IF NOT EXISTS`，幂等；与 scheduler-architecture §8 对齐，P0 不用 `requires` 列做匹配但保留列）：

```sql
CREATE TABLE IF NOT EXISTS work_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    queue       TEXT NOT NULL,             -- P0 固定 "crawl_1688_contact"
    site        TEXT,                      -- "1688"
    batch_id    INTEGER,                   -- P0 恒 NULL（平台批次 P4 接入）
    payload_json TEXT NOT NULL,            -- contact: {"domain","name","url"}
    requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/claimed/done/failed
    claimed_by  TEXT,                      -- "w0".."wN"
    claimed_at  TEXT,
    finished_at TEXT,
    result_json  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_items_claim ON work_items(queue, status, id);
```

`ShopDB` 新增方法（全部短事务、`BEGIN IMMEDIATE`，仿 `claim_pending_shops` `db.py:286-318` 的既有模式）：

| 方法 | 语义 |
|---|---|
| `topup_contact_work_items(queue, site, domain_suffix, limit) -> int` | 单事务：SELECT shops pending → INSERT work_items + UPDATE shops 标 `in_progress` → 返回补货数。与现有 `claim_pending_shops` 的 shops 状态语义严格一致（shop 被领走的标志仍是 `in_progress`），保证 daemon 与旧 CLI 的数据口径相同 |
| `claim_work_item(queue, consumer_id) -> dict \| None` | 单事务：取该队列最老 pending 项 → 标 claimed + claimed_by/at → 返回行（dict） |
| `finish_work_item(id, status, result) -> None` | done/failed 落终态 + finished_at + result_json |
| `reset_claimed_work_items() -> int` | daemon 启动时调用：claimed → pending（对应现有 `reset_in_progress` 的崩溃恢复语义；单 dispatcher 前提下不需要租约心跳） |

### 3.3 DaemonTaskProxy 行为

- `prepare(config)`：调 inner.prepare；打印队列当前 pending 数（替代 contact 原 pending shops 计数展示，口径=未补货的 shops pending + work_items pending）。
- `acquire_item(ctx)`：
  1. `claim_work_item`；命中 → 返回 payload dict（`{"domain","name","url"}`，键访问与 sqlite Row 的 `item["domain"]` 访问兼容）；
  2. 未命中 → `topup_contact_work_items`（单次补货上限=消费者数×4，防单事务过大）→ 补到货则 `notify_all` 并重试 claim；
  3. 仍无货 → 条件变量 wait（超时 30s 自醒），醒后先查 `ctx.stop`，置位则返回 None（CrawlLoop 正常退出），否则回到 1。
- `after_item(...)`：透传 inner 后按结果 `finish_work_item`（done/failed）。
- 其余方法（`fetch/validate/on_success/on_giveup/cold_start/label/compose/summary/...`）全部透传 inner。

**已知行为差异（Step 1.1 发现，裁定：接受）**：站点级 `cold_start`（`sites/alibaba1688/__init__.py:73`）对 dict item 走 `item["domain"]` 分支（逛**店铺**首页），对 sqlite Row 走 `getattr` 得 None（逛**站点**首页）。daemon 用 dict 后冷启动软着陆从站点首页变为店铺首页——该 dict 分支是既有代码显式预留的，方向更拟人（先逛目标店再抓该店联系方式），判定为可接受的等价性偏差，在 §5 等价性对比中不作为差异项。

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
| 1 | `ContactTask.fetch/on_success` 对 item 只做 `item["domain"]` 式键访问，dict 可 1:1 替代 sqlite Row | 已读码验证（Step 1.1）：`contact.py` 全部 item 访问点均为 `item["..."]` 键访问（163/171/180/182/227/230/245/252 行），键集合 = {`domain`,`name`,`url`}，无 `item.domain` 属性访问；间接消费方站点 `cold_start`（`sites/alibaba1688/__init__.py:73`）已显式兼容 dict | **dict 可直接替代**，无需 SimpleNamespace/子类适配；payload 必须含 `domain`/`name`/`url` 三键（`label` 用 `name`+`domain`，`fetch` 用 `domain`+`url`，`cold_start`/`on_success`/`on_giveup`/`on_abort` 用 `domain`） |
| 2 | `Engine` 注入 `loop_factory`/task 包装后行为与直跑一致（无对 task 具体类型的 isinstance 判断） | 已读码验证（Step 1.1）：全包 grep `isinstance` / `type(...) is` / `__class__`，`engine.py`/`loop.py`/`task.py`/`cli/main.py` 中对 task 零命中（现存 isinstance 均判 Scenario/dict/Channel 等数据类型），task 全程鸭子类型调用 | **无特判**：Engine/CrawlLoop/CLI 只经 Task 协议方法（`make_stats`/`compose`/`acquire_item`/`summary`…）调用 task，`DaemonTaskProxy` 实现协议即可经 `Engine(cfg, task=proxy)`（engine.py:36-41）与 `loop_factory`（engine.py:53）注入；Step 2.1 单测复刻 test_engine.py 模式 |
| 3 | work_items 表加进 fetcher `SCHEMA` 不影响平台侧：平台读库用 `app.db.connect()` 只读连接 + 防御性探测，不校验全表清单 | 项目约定（AGENTS.md §4）+ 推断 | P0 冒烟时平台服务保持运行，确认平台各页面/API 无异常 |
| 4 | 条件变量 wait 挂起期间，该消费者的通道/浏览器空转无额外风险（与现状批休期间状态相同） | 现状类比（批休 900s 也是持通道挂起） | 无需 spike；等价性冒烟覆盖 |
| 5 | 青果通道在 daemon 常驻（可能数天）下，隧道缓存 TTL 30 分钟刷新逻辑在长跑中稳定 | 推断（qingguo.py:50-55 缓存逻辑与运行时长无关） | 长跑观察留到 P1+；P0 冒烟为短时有限运行，不阻塞 |

唯一需要先做的是假设 1 的确认（PLAN 第一步）；无第三方库新依赖，无 CloakBrowser 席位语义假设（席位问题属 P2 多 context 设计，P0 每消费者仍是一个浏览器实例，与现状一致）。

## 5. 验收标准（P0 整体）

1. `cd fetcher && python -m pytest tests -x -q` 全绿（含新增用例）。
2. 冒烟：`python -m fetcher daemon --proxy --limit 5` 跑通——店铺联系人提取完成，work_items 全部落正确终态（done，或风控放弃时 failed 且带 reason/kind），shops 对应行落终态，contacts 落库字段口径与旧 CLI 相同。
3. 等价性对比：同批数据分别用旧 CLI 与 daemon 跑 `--limit 20`，对比每分钟请求数（事件时间戳）、成功率、contacts 字段完整度，无统计学可见差异（节奏参数相同即可，允许随机浮动）。
4. 空队列行为：shops 无 pending 时 daemon 不退出、CPU 空转≈0；stop 信号后 30s 内全部消费者退出、浏览器关闭。

## 6. 变更记录

- 2026-08-07（Step 3.1 验收裁定）：§5 第 2 条「work_items 5 行 done」放宽为「全部落正确终态」——实测 18 done + 2 failed（登录墙密集期策略链按既有规则放弃，A 组旧 CLI 同环境 1 failed），失败落终态本身是机制正确的体现，环境因素不应计入验收。
