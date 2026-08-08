# SPEC — Facebook 采集接入 daemon 调度（二期编排）

> 版本：v1 · 2026-08-09 · 评审稿
> 依据文档：docs/channel-research/facebook-groups.md（侦察+PoC+原子落地）、
> docs/channel-research/facebook-summary.md（选型与经济账）、
> docs/scheduler-architecture.md（daemon 队列+消费者池，P0-P5 已收官）
> 已落地能力：`fetch_fb_post` 原子（匿名抓 permalink，真机 10/10）、
> `fetch_fb_group_posts` 原子（BD/Apify 灾备）、`parse_post` 四桶提取、
> FacebookPlugin 判断侧（detectors/block_reason）

## 1. 背景与目标

FB 群帖匿名采集的一期原子能力已验证（无需登录、10 帖样本 60% 含明文中国
手机号、CloakBrowser 无头 10/10 成功）。二期目标是把「发现 → 抓取 → 落库
→ 查号」编成平台可调度的批次任务，接入 daemon 调度体系（scheduler P4/P5
后采集一律 BATCH_TYPES → work_items 队列 → daemon 消费者，subprocess 路径
已退役）。

业务闭环：fb_posts 发现表 → crawl_fb_post 队列抓取提号 → fb_contacts 落库
分桶 → 不确定桶进 wa_check 队列验证注册态 → 可售线索（¥3/条）。

## 2. 范围

**包含（三个功能单元，对应三个 Phase）：**

1. **核心抓取链路**：`fb_posts` 表 + `FbPostTask`（Task 协议包装
   `FetchFbPost` 原子）+ `crawl_fb_post` 队列注册 + 平台 `fb_post` 批次
   任务类型（含前端表单）+ 提取号码落 `fb_contacts` 表。
2. **发现层（Apify SERP 外包先行）**：`discover_fb` 队列（local 消费者，
   urllib 调 Apify Google Search Scraper）+ 平台 `fb_discover` 批次任务
   类型（关键词矩阵 × 页数展开入队）+ 结果解析去重落 `fb_posts`。
3. **wa_check 衔接**：`fb_contacts` 不确定桶（含自声明桶 5-10% 抽样校准）
   进现有 wa_check 链路（fetcher topup + 平台 enqueue 双侧扩展、回写双表）。

**明确的非目标：**

- 自建 Google SERP 抓取（consent/人机验证特征表 + 限速策略是全新站点级
  工作量；后续演进，同 `discover_fb` 队列加第二种 payload kind 即可）。
- 网页版广告库采集、FetchFbGroupPosts 队列化（灾备通道保留原子备用）。
- 评论翻页抓取（无头会话渲染不稳定，只收首屏机会增量，原子已支持）。
- API key 入 providers 表管理（本期沿用环境变量 `APIFY_TOKEN`，与
  `FetchFbGroupPosts` 一致）。
- 单 IP 安全日量爬坡实测（运营动作；`ip_request_budget` 先给保守初始值，
  实测后调配置，不改代码）。
- Bright Data 群帖端点平台化（已实测，灾备备用）。

## 3. 总体设计

### 3.1 队列拓扑

```
平台任务 fb_discover ──入队──► work_items(discover_fb, requires=["local"])
                                    │ LocalExecutor 消费
                                    ▼
                          Apify Google SERP → 解析 permalink
                                    │ INSERT OR IGNORE
                                    ▼
                              fb_posts 表（status 状态机）
                                    │ topup / 平台 fb_post 批次入队
                                    ▼
平台任务 fb_post ────入队──► work_items(crawl_fb_post, requires=["channel","browser"])
                                    │ BrowserConsumer 消费（site="facebook"）
                                    ▼
                          FbPostTask → FetchFbPost 原子 → parse_post
                                    │ 号码 upsert
                                    ▼
                       fb_contacts（四桶分桶 + wa_source）
                                    │ 不确定桶 + declared 抽样
                                    ▼
                       wa_check 队列（现有 LocalExecutor，零新基建）
```

### 3.2 关键选型裁定

| 决策点 | 裁定 | 理由 |
|---|---|---|
| FbPostTask.fetch 实现 | **调 `FetchFbPost` 原子**（不内联 page 操作） | 原子已真机验证；符合「原子做事、Task 编排」分层；现有 contact Task 内联是历史形态，新代码不沿用 |
| 号码落库 | **新建 `fb_contacts` 表**（不造 shops 伪行进 contacts） | contacts.shop_id UNIQUE NOT NULL 是店铺语义硬约束，伪行污染 shops 统计/补货逻辑；fb_contacts 按号码 UNIQUE 天然去重 |
| 发现层路线 | **Apify SERP 外包先行**（local 消费者） | 零浏览器零通道占用、不烧代理 IP；自建 Google 需全新风控特征表，延后；两路线共用 fb_posts 数据面，演进无痛 |
| discover 队列 site | **site=None**（local 队列） | Apify API 调用无需代理通道；冷却键退 queue 名（queue_router 已泛化支持） |
| 帖子 payload 键名 | 沿用 `{"domain","name","url"}`（domain=群 URL、name=群名、url=帖子 permalink） | 平台 SSE `_item_label` 优先取 payload.domain，事件标签零改动 |
| FB 风控策略 | FacebookPlugin 补 `policy_overrides`：去掉 solve_slider（FB 无阿里式滑块），BLOCKED → block_rest → swap_ip → give_up | 参照 madeinchina 插件同款退化（sites/madeinchina/__init__.py:53-59） |
| `ip_request_budget` | 初始 **60**（匿名 permalink 抓取，参照 1688 contact） | 真实安全值待爬坡实测（summary §3 待办 1），配置可调 |

## 4. 数据模型

### 4.1 `fb_posts` 表（fetcher 侧建表，平台防御性探测）

```sql
CREATE TABLE IF NOT EXISTS fb_posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL UNIQUE,      -- 帖子 permalink
    group_id      TEXT,                      -- 群 id（URL 解析）
    group_name    TEXT,                      -- 群名（发现层取自 SERP 标题）
    keyword       TEXT,                      -- 溯源：发现所用查询词
    source        TEXT NOT NULL DEFAULT 'apify',  -- apify / google（后续自建）
    status        TEXT NOT NULL DEFAULT 'pending', -- pending/in_progress/done/failed
    has_contact   INTEGER,                   -- 抓取后回写：是否提到联系方式
    first_seen_at TEXT NOT NULL,             -- 北京时间字符串
    fetched_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_fb_posts_status ON fb_posts(status, id);
```

状态机对齐 shops：`pending → in_progress → done/failed`。
`in_progress` 是「已入队未终态」的互斥标记，双写入方（平台 enqueue /
daemon topup）靠它防重复喂货。

### 4.2 `fb_contacts` 表（fetcher 侧建表）

```sql
CREATE TABLE IF NOT EXISTS fb_contacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    number        TEXT NOT NULL UNIQUE,   -- 中国号裸 11 位；国际号纯数字带原国家码
    bucket        TEXT NOT NULL,          -- declared_wa / cn_uncertain / overseas
    wa_source     TEXT,                   -- 'declared'(自声明) / 'checked'(协议验证) / NULL
    wa_registered INTEGER,                -- 1/0/NULL（三态语义同 contacts）
    wa_checked_at TEXT,
    post_url      TEXT NOT NULL,          -- 来源帖
    group_id      TEXT,
    first_seen_at TEXT NOT NULL
);
```

- 写入规则（parse_post 输出 → 本表）：declared_wa 桶 `wa_source='declared'`；
  cn_uncertain / overseas 桶 `wa_source=NULL`、`wa_registered=NULL`。
- 微信号 / TG / 群邀请链接**不进本表**，随 `work_items.result_json` 留存
  （观测与后续导出用；`finish_work_item` 已有此机制）。
- 查号后回写：`wa_registered` + `wa_checked_at` + `wa_source='checked'`。

### 4.3 迁移责任

- fetcher `db.py`：`CREATE TABLE IF NOT EXISTS` 建两表 + `topup_fb_post_work_items`
  / `save_fb_contacts` / `mark_fb_post_*` 等写函数（短事务 +
  `PRAGMA busy_timeout = 30000`，WAL 并发安全）。
- 平台 `app/db.py`：`sqlite_master` 防御性探测（参照 work_items 索引的
  探测模式），`enqueue_fb_post_batch` / `enqueue_fb_discover_batch` 平台侧
  重写 SQL（沿用「平台不 import fetcher」裁定）。

## 5. fetcher 侧设计

### 5.1 `FbPostTask`（新文件 `fetcher/fetcher/sites/facebook/post_task.py`）

照 `madeinchina/contact.py` 模板实现 Task 协议，差异点：

- 类属性：`name="post"`、`unit="帖"`、`ip_request_budget=60`。
- `fetch(ctx, item)`：`FetchFbPost().run(ctx, {"url": item["url"]})`，
  原子返回的 ActionResult 直接上交（loop 的 inspector/fallback 链路
  无需改动；原子 BLOCKED → RISK_SLIDER_PAGE 场景 → facebook 策略链已无
  solve_slider，走 block_rest/swap_ip）。
- `validate(ctx, item, result)`：`data["text"]` 非空且长度 ≥ 100（FB 帖
  页含遮罩文案，纯遮罩约 200 字符，有效帖页远超此值；阈值 PLAN 阶段按
  PoC 样本复核）。
- `on_success(ctx, item, result)`：`save_fb_contacts(item["url"], phones)`
  upsert + `mark_fb_post_done(url, has_contact)` + stats 计数
  （`{"ok","empty","failed"}`）；返回 1。
- `on_giveup`：`mark_fb_post_failed(url)` + stats；`giveup_cost` 返回 1。
- `prepare(config)`：daemon 启动时 `fb_posts` 表 `in_progress → pending`
  崩溃恢复重置（**注意**：`reset_daemon_state` 只认 domain_suffix 非空的
  contact 队列，不覆盖 fb_posts；重置放 Task.prepare 与 1688 contact 的
  prepare 语义一致，router.prepare 每队列都会调到）。
- `cold_start`：空实现（白板匿名会话无需软着陆；warmup 由框架负责，
  见 §7.3 行为后果）。

### 5.2 队列注册（`cli/main.py _build_registry`）

```python
site_fb = get_site("facebook")
specs.append(QueueSpec(
    queue="crawl_fb_post", site="facebook",
    task=site_fb.make_task("post"),
    topup=lambda db, limit: db.topup_fb_post_work_items(
        "crawl_fb_post", "facebook", limit),
    domain_suffix="",                 # 无 shops 语义；reset 走 Task.prepare
))
specs.append(QueueSpec(
    queue="discover_fb", site=None,
    task=FbDiscoverTask(),            # local 消费者（参照 WaCheckTask 形态）
    topup=None,                       # 货源=平台批次参数，无自喂
    requires={"local"},
))
```

`FacebookPlugin`：`task_names()` 加 `"post"`；`make_task` 支持之；补
`policy_overrides`（去 solve_slider，BLOCKED → block_rest → swap_ip →
give_up，参数沿用全局默认表其余项）。

### 5.3 发现层 Task + 原子

- 新原子 `FetchApifySerp`（`fetcher/fetcher/atoms/facebook_discover.py`）：
  urllib 调 Apify Google Search Scraper actor（run-sync-get-dataset-items，
  模式与 `fetch_apify_posts` 一致），输入 `{"query","page"}`，输出 organic
  results 中的 FB 群帖 permalink 列表。Outcome 口径复用
  `FetchFbGroupPosts` 的映射（402/429→BLOCKED、401/403→FATAL、0 结果→
  EMPTY、超时→NET_ERROR）。
- `FbDiscoverTask`（local 消费者形态，参照 `WaCheckTask`）：
  `fetch` 调原子 → `on_success` 把 permalink 逐条 `INSERT OR IGNORE` 进
  `fb_posts`（带 keyword/source/group 溯源），返回新增条数。
- permalink 判定正则：`facebook\.com/groups/[^/]+/(posts|permalink)/\d+`
  （PLAN 阶段按 spike 实测样本校准，SERP 还返回群主页/视频等噪声）。

## 6. 平台侧设计

### 6.1 批次类型注册（四处同步铁律）

- `runner.py BATCH_TYPES`：
  - `"fb_post": {"queue":"crawl_fb_post","site":"facebook","domain_suffix":"","kind":"fb_post"}`
  - `"fb_discover": {"queue":"discover_fb","site":None,"domain_suffix":"","kind":"fb_discover"}`
- `enqueue_batch_for_task` 加两个分支：
  - `fb_post` → `enqueue_fb_post_batch(queue, site, batch_id, limit)`：
    `BEGIN IMMEDIATE` 单事务 SELECT pending fb_posts → INSERT work_items
    → 源行置 in_progress（复刻 `enqueue_contact_batch` 事务模式）。
  - `fb_discover` → `enqueue_fb_discover_batch(batch_id, keywords, pages)`：
    关键词矩阵 × 页数展开 INSERT work_items（payload
    `{"kind":"apify_serp","query":...,"page":N}`，`requires='["local"'`，
    同关键词同页已有 pending 则跳过幂等）。
- 类型枚举/校验/preview/start/stop/SSE/sweeper/循环重启全部自动兼容
  （runner/api 按 BATCH_TYPES 并集驱动，已核实代码路径）。

### 6.2 前端（交互形态定死）

- `task-ui.tsx TASK_TYPE_OPTIONS` 加两项：
  - `fb_post` → label「Facebook 帖子采集」
  - `fb_discover` → label「Facebook 帖子发现」
- `TaskFormDialog.tsx`：
  - `fb_post` 进 isBatch 列表（表单 = limit + 循环间隔，与现有批次一致）。
  - `fb_discover` 独立分支：关键词输入（Textarea，placeholder
    「每行一个查询词」，默认值见下）+ 每词页数（number input，默认 1，
    范围 1-10）+ limit（可选，0=不限）+ 循环间隔。
  - 默认关键词矩阵（表单预填，取自 facebook-groups.md §2 实测高命中词）：
    ```
    site:facebook.com/groups 外贸 whatsapp
    site:facebook.com/groups 跨境电商 whatsapp
    site:facebook.com/groups china sourcing whatsapp
    site:facebook.com/groups 货代 微信
    site:facebook.com/groups 亚马逊卖家 微信
    ```
- `lib/api.ts`：TaskType 加 `'fb_post' | 'fb_discover'`；TaskParams 加
  `keywords?: string`（换行分隔原文）、`pages?: number`。
- `Tasks.tsx BATCH_TYPE_NAMES` 加两个类型（启用批次进度渲染）；
  `paramsSummary` 加分支（fb_post 复用「上限=N」；fb_discover 显示
  「N 词 × M 页」）。

### 6.3 进度与观测

sweeper 聚合结构 `{total,done,failed,stopped,claimed,pending}` 与前端
`batchProgress()` 天然兼容；dispatcher 消费者看板按 queue 聚合，新队列
注册后自动出现（**冒烟验证项**，dispatcher API 未逐行核实）。

## 7. 契约与行为后果（含依据与验证方式）

### 7.1 FetchFbPost 在 daemon BrowserConsumer 下的 ctx 契约

- 假设：`ctx.page` 在消费 facebook item 时指向该消费者浏览器内 facebook
  站点的独立 BrowserContext 的 page，原子代码零改动可用。
- 依据：**已验证代码路径**——`Session.views` 按站点一 view
  （session.py:63），`page/identity` 属性路由到活动 view
  （session.py:112-128），`_bind_item_site` 认领时切换 + `ensure_site`
  懒建（loop.py:481-515）；原子 ctx 依赖（page/wait/stopped/log/
  last_error）在 WorkerContext 全部满足（逐项核对过）。
- 验证：daemon 多队列运行时冒烟（FB 队列与 1688 队列交替消费，page 指向
  正确 view）。

### 7.2 白板匿名会话

- 假设：facebook view 无 Cookie 可用（匿名抓取），`ensure_site` 白板路径
  （无 Cookie 且无种子 kit → 空 context + warmup 现场签发）正常工作。
- 依据：**代码路径已核实**（browser.py:466-468）+ PoC 实测匿名 10/10
  （但 PoC 是单站点 CloakBrowser 直连，非 daemon 多站点视图）。
- 验证：daemon 冒烟中确认 FB 帖抓取成功率与 PoC 基线一致。

### 7.3 warmup homepage 的已知偏差

- 行为：facebook view 首次建立时 warmup 访问的 homepage 取自
  BrowserManager 装配值（daemon 首个浏览器站点，即 1688 首页），**不是**
  facebook.com（browser.py:483-485，Engine 单 homepage 传入）。
- 后果评估：FB 匿名抓取不依赖 Cookie/会话热身，访问一次 1688 首页对 FB
  链路无害（仅多一次无害导航）；FB 侧软着陆不必要（cold_start 空实现）。
- 裁定：**接受偏差**，不为 FB 改 warmup 机制；若未来需 FB 登录态再议。

### 7.4 fb_posts 双写入方互斥

- 假设：平台 `enqueue_fb_post_batch` 与 daemon `topup_fb_post_work_items`
  并发喂同一批 pending 行不会产生重复 work_items。
- 依据：两者都是「BEGIN IMMEDIATE 单事务 SELECT pending → INSERT →
  UPDATE in_progress」（复刻 enqueue_contact_batch/topup_contact_work_items
  已验证的事务模式，WAL + BEGIN IMMEDIATE 串行化写）。
- 验证：并发集成测试（平台入队与 daemon topup 同时跑，断言无重复
  work_items 且无漏置 in_progress）。

### 7.5 Apify Google Search Scraper 行为（依据=推断，**动工前必须 spike**）

- 假设：① actor（`apify/google-search-scraper`）接受 `site:` 运算符查询；
  ② 分页参数可控、单查询可取多页；③ 返回 organic results 含 URL 字段；
  ④ 价格 $1.8-4.5/1K 查询页（facebook-summary.md §30 的数字在
  third-party-apify.md **无出处**，需实测确认）。
- 验证方式（PLAN Phase 2 前置 spike，免费 $5 额度内完成）：
  实调 actor 跑 2 个实测查询词 × 2 页，确认返回结构、permalink 占比、
  单价，回填本节与 third-party-apify.md。**spike 不通过（actor 不支持
  site: 或价格离谱）→ 回退方案：发现层 Phase 暂缓，核心链路 Phase 1 +
  wa_check Phase 3 不受影响**（fb_posts 可手工/脚本灌种子）。

> **执行记录（2026-08-09 二期落地）**：P1/P3 已按本 SPEC 落地并冒烟
> 通过；P2（发现层）因 **APIFY_TOKEN 未提供**（环境变量/仓库/配置均无，
> facebook-groups.md §12 明确 key 仅存于验证会话）暂缓——spike 无法
> 在无 token 的情况下实调。待 token 就位后按 PLAN 2.1→2.6 推进：
> 实调 spike（§7.5 四项确认）→ FetchApifySerp 原子 → FbDiscoverTask →
> 平台/前端 fb_discover → 发现→抓取闭环冒烟。熔断期间 fb_posts 可
> 手工/脚本灌种子（P1 冒烟已验证此路径）。

### 7.6 wa_check 双货源衔接

- 假设：`fb_contacts` 的中国号（裸 11 位，口径与 contacts.mobile 一致）
  进现有 wa_check 链路无需改 LocalExecutor 消费者与 Baileys CLI。
- 改动面：① fetcher `wa_check_topup` 与平台 `enqueue_wa_batch` 的挑号
  SQL 扩展为 `contacts ∪ fb_contacts`（仅 cn_uncertain 桶 + declared 桶
  5-10% 随机抽样，DISTINCT 去重）；② WaCheckTask 结果回写按号码双表
  UPDATE（两表各 UPDATE 一次，幂等命中）；③ fb_contacts 回写时
  `wa_source='checked'`。
- 依据：wa_check payload（numbers+account）与回写（按号码）均与来源表
  无关，已核实 `enqueue_wa_batch`/`wa_check_topup` 代码。
- 验证：集成测试——fb_contacts 种子号进 wa_check 批次、回写落
  fb_contacts 且 contacts 行为不回归。

## 8. 职责分配（初始化 + 变更路径）

| 数据 | 初始化（谁写） | 变更（谁写/谁读） |
|---|---|---|
| fb_posts 行 | discover 层 `INSERT OR IGNORE`（FbDiscoverTask.on_success） | 状态：enqueue/topup 置 in_progress；FbPostTask.on_success/on_giveup 置 done/failed + has_contact；Task.prepare 崩溃恢复 in_progress→pending。读：enqueue/topup（pending）、平台数据页（后续，非本期） |
| fb_contacts 行 | FbPostTask.on_success `INSERT OR IGNORE`（同号后帖不覆盖 first_seen/post_url） | wa_registered/wa_checked_at/wa_source：WaCheckTask 回写。读：wa_check 挑号（双源）、抽样校准统计 |
| work_items(crawl_fb_post) | 平台 enqueue_fb_post_batch 或 daemon topup | 终态：QueueRouter.finish/release；停止：runner 压 stopped |
| work_items(discover_fb) | 平台 enqueue_fb_discover_batch（唯一写入方，topup=None） | 同上 |
| contacts（1688/mic） | 现有链路，**本 feature 不动** | wa_check 挑号 SQL 扩展为双源 UNION 是唯一触达点，1688 侧行为必须零回归 |
| 提取副产物（微信/TG/邀请链接） | QueueRouter.finish_work_item 的 result_json（FbPostTask 经 on_success 数据带上） | 只读观测，无变更路径 |

## 9. 验收标准（feature 级）

1. 平台创建 fb_discover 任务（默认关键词矩阵 × 1 页）→ fb_posts 表出现
   去重后的 pending 帖子行，关键词溯源正确。
2. 平台创建 fb_post 任务 → daemon BrowserConsumer 认领抓取 → fb_posts
   状态机流转正确 → fb_contacts 出现四桶分桶的号码（declared_wa 桶
   wa_source='declared'）。
3. FB 抓取与 1688/mic 队列并行运行时：冷却填充生效（FB 冷却期间消费者
   转取其他队列）、identity 按 `facebook:ip` 分桶、互不污染。
4. wa_check 批次自动涵盖 fb_contacts 不确定桶，查号结果回写 fb_contacts
   （wa_source='checked'），contacts 侧行为零回归。
5. 全量回归：fetcher 测试全绿（新增 Task/原子/DB 测试 + 既有 37 例 FB
  测试不动）、`npx tsc -b` 通过、平台冒烟（创建→运行→停止→进度展示）
   走通两个新任务类型。

## 10. 冲突扫描结论（呈交前自查）

1. **PLAN vs 代码库现状**：所有改动点（`_build_registry`/BATCH_TYPES/
   TaskParams/前端四处/db.py 双侧）均为纯新增分支，不改动现有导出与
   签名；wa_check 挑号 SQL 扩展是唯一触达既有行为的点，已列验收 #4 防
   回归。`reset_daemon_state` 不覆盖 fb_posts 的缺口由 Task.prepare 补
   （§5.1），无框架改动。
2. **PLAN 内部**：Phase 2 依赖 Phase 1 的 fb_posts 表；Phase 3 依赖
   Phase 1 的 fb_contacts 表；Phase 2/3 互不依赖可并行。spike（§7.5）
   失败只影响 Phase 2，熔断路径已写明。
3. **外部依赖**：Apify token（环境变量，验证会话已有）；Apify Google
   Search Scraper actor 行为是推断，spike 前置（§7.5）。无新 Python 包
   （urllib 标准库）、无新 npm 包。
4. **遗留风险**：dispatcher 看板 API 对新队列的自动兼容未逐行核实
   （列为冒烟项）；validate 阈值与 permalink 判定正则需 PoC 样本校准
   （PLAN 阶段落实）。平台侧测试基建已核实存在
   （`platform/server/tests/test_batch_tasks.py` 等 6 个测试文件，
   enqueue 批次测试模式可参照）。

## 11. 评审裁决记录（2026-08-09）

1. 范围：**三段全包**（核心链路 / Apify 发现层 / wa_check 衔接），一次闭环到可售线索。
2. 号码落库：**独立 `fb_contacts` 表**，wa_check 挑号 SQL 改双源 UNION。
3. 发现层：**本期平台化**（fb_discover 任务类型 + 前端表单，与 fb_post 同批交付）。
