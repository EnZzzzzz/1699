# SPEC — Facebook 发现层（DDG SERP 自建）+ 群 feed 全量采集

> 版本：v1 · 2026-08-09 · 评审稿
> 依据文档：docs/channel-research/facebook-groups.md（侦察+PoC+原子落地，§10/§12）、
> docs/channel-research/facebook-summary.md（选型与经济账）、
> docs/scheduler-architecture.md（daemon 队列+消费者池）、
> docs/archive/feat_2026-08-09_facebook-daemon-integration/SPEC.md（二期编排，
> 发现层 Apify 路线卡 APIFY_TOKEN 暂缓，本 feature 换自建 SERP 复活同队列拓扑）
> spike 证据：本目录 spike/ddg_sample_1.html（DDG html 端点实测 HTML 样本）
> 已落地能力：fb_posts/fb_contacts 表 + crawl_fb_post 队列 + FbPostTask +
> FetchFbPost 原子 + FetchFbGroupPosts 原子（BD/Apify，17 测全过，真机实测）
> + wa_check 双源衔接

## 1. 背景与目标

FB 群帖采集的一期链路已完整且真机验证：fb_posts（pending→in_progress→done/failed）
→ 平台 `BATCH_TYPES["fb_post"]` → `enqueue_fb_post_batch` → daemon 队列
`crawl_fb_post`（BrowserConsumer）→ `FbPostTask` → `FetchFbPost` 原子（匿名渲染抓
permalink）→ `parse_post` 四桶分桶 → `fb_contacts` → wa_check 双源衔接（查号漏斗）。

本 feature 补齐两个缺口：

1. **发现层缺失**：fb_posts 至今没有生产写入方，无帖可采。原 Apify SERP 路线
   （归档 SPEC §5.3 有完整设计）卡在 APIFY_TOKEN 缺失，用户已裁定改走
   **Bing/DuckDuckGo 自建 SERP 抓取**（urllib 裸 HTTP，零第三方费用）。
2. **FetchFbGroupPosts 孤岛**：按群 URL 拉全量帖的原子（BD/Apify，正文全文不截断）
   已实现且 17 测全过，但无任何队列/任务消费。用户已裁定本期接上队列。

目标（两条新批次任务线）：

- **A. 帖子发现层 `fb_discover`**：DDG SERP 裸抓 → 解析 FB 群 URL → 帖 permalink
  落 fb_posts（既有 crawl_fb_post 消费）、群主页 URL 落新表 fb_groups（见 B）。
- **B. 群 feed 全量采集 `fb_group`**：fb_groups pending 群 → `FetchFbGroupPosts`
  （BD/Apify）拉全量帖 → 号码直接落 fb_contacts（正文全文在手，无需再走
  crawl_fb_post）→ 群状态机 done/failed。

## 2. 范围

**包含（五个功能单元，对应 PLAN 五个 Phase）：**

1. **发现层（fetcher 侧）**：`FetchDdgSerp` 原子（urllib 裸 HTTP 抓 DDG html 端点）
   + `parse_serp_results`/`classify_fb_url` 纯函数 + `FbDiscoverTask`（local 消费者）
   + `discover_fb` 队列注册。
2. **群采集（fetcher 侧）**：新表 fb_groups + `FbGroupTask`（local 消费者包装
   FetchFbGroupPosts）+ `crawl_fb_group` 队列注册 + `FbPostTask.on_success` 群
   upsert 补位（种子路径②）。
3. **平台批次接线**：runner `BATCH_TYPES` 两类型 + `enqueue_batch_for_task` 两分支
   + app/db.py `enqueue_fb_discover_batch`/`enqueue_fb_group_batch` + api/tasks.py
   `TaskParams` 四字段 + 平台测试。
4. **前端**：TaskType/TaskParams/task-ui.tsx/TaskFormDialog.tsx/Tasks.tsx 四处+一处
   同步（交互形态 §7 定死）。
5. **端到端冒烟 + 文档收尾**：真实批次跑通 + AGENTS.md/渠道文档同步 + 归档。

**明确的非目标：**

- Bing 常规搜索裸抓（spike 实测恒 challenge，本期引擎仅 DDG；浏览器渲染回退分支
  见 §8.2，预案不执行）。
- Apify SERP 路线复活（回退分支之二，仅当自建全线失败）。
- API key 入 providers 表管理（沿用环境变量 `BRIGHTDATA_API_KEY` / `APIFY_TOKEN`，
  与 FetchFbGroupPosts 一致；缺失时原子 FATAL 是既有行为，本期不新增凭证体系）。
- wa_check 双源衔接改动（群 feed 落的号码自动进查号漏斗，**零改动**）。
- 群 feed 评论翻页抓取（FetchFbGroupPosts 原子已支持首屏机会增量，本期不扩展）。
- DDG 多账号/代理轮换规避限流（单 IP 限流由查询节奏 + 202 退避吸收，spike 实测
  封禁窗口约 4 分钟，见 §8.1）。
- fb_groups 平台数据浏览页（发现/采集链路本期闭环，数据展示后续单独排期）。

## 3. 总体设计

### 3.1 队列拓扑

```
平台任务 fb_discover ──入队──► work_items(discover_fb, requires=["local"])
                                    │ local 消费者（FbDiscoverTask）
                                    ▼
                          FetchDdgSerp 原子（urllib 裸 HTTP，DDG html 端点）
                                    │ parse_serp_results → classify_fb_url 双路分类
                                    ▼
      ┌─────────────────────────────┴─────────────────────────────┐
      ▼                                                            ▼
 fb_posts（帖 permalink，source='ddg'）                    fb_groups（群主页 URL）
      │ 既有 crawl_fb_post 队列（BrowserConsumer）                │ 平台 fb_group 批次入队
      ▼                                                            ▼
 fb_contacts ←── parse_post 四桶                              work_items(crawl_fb_group)
      │                                                            │ local 消费者（FbGroupTask）
      ▼                                                            ▼
 wa_check 双源衔接（既有，零改动）                    FetchFbGroupPosts（BD/Apify 全量帖）
                                                                    │ 逐帖 save_fb_contacts
                                                                    ▼
                                                              fb_contacts（四桶分桶）
                                                                    │
                                                                    ▼
                                                          wa_check 双源衔接（既有）
```

### 3.2 关键选型裁定

| 决策点 | 裁定 | 理由 |
|---|---|---|
| SERP 引擎 | **DDG html 端点**（`html.duckduckgo.com/html/?q=`） | spike 实测：Bing 恒 challenge 不可裸抓；DDG GET+浏览器 UA+gzip 可抓、无验证码（§8.1） |
| 发现层消费者 | local 消费者（`requires={"local"}`），site=None | 裸 HTTP 无浏览器无通道；冷却键退 queue 名（既有泛化，P4-1 已就绪） |
| 群采集消费者 | local 消费者（`requires={"local"}`），site=None | BD/Apify 是 HTTPS 第三方 API，不需要代理通道/浏览器 |
| SERP 结果分类 | 双正则：帖 `groups/[^/]+/(posts\|permalink)/\d+`；群主页 `groups/[^/]+` | spike 实测 SERP 结果 ~90% 群主页、~10% 帖 permalink，两路都要收（§8.1） |
| 原子命名 | `FetchDdgSerp`（初稿名 FetchBingSerp 废弃） | 引擎裁定为 DDG，命名跟随实际；payload 保留 `engine` 字段供未来扩展 |
| 群采集 | 直接接 `FetchFbGroupPosts` 原子（零改动） | 原子已实现 + 17 测全过 + 真机实测记录（facebook-groups.md §12） |
| discover 队列 site | site=None | 与 wa_check 同型；无冷却语义冲突 |
| fb_discover 幂等 | 同 query+page 已有 pending 跳过 | 防循环模式重入时批量重复堆栈；fb_posts/fb_groups 落库再按 url UNIQUE 去重 |

## 4. 数据模型

### 4.1 新表 `fb_groups`（fetcher 侧建表，平台防御性探测）

```sql
CREATE TABLE IF NOT EXISTS fb_groups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,     -- 群 URL https://www.facebook.com/groups/{gid}
    group_id        TEXT,                     -- 群 id（数字或 slug，URL 解析）
    name            TEXT,                     -- 群名（发现层取自 SERP 标题，溯源用，近似值）
    source          TEXT NOT NULL DEFAULT 'ddg',  -- 发现来源 ddg / fb_post（帖派生）
    status          TEXT NOT NULL DEFAULT 'pending', -- pending/in_progress/done/failed
    post_count      INTEGER,                  -- 已采帖数（fb_group on_success 回写）
    has_contact     INTEGER,                  -- 是否提到联系方式（fb_group 回写）
    first_seen_at   TEXT NOT NULL,            -- 北京时间字符串
    last_crawled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fb_groups_status ON fb_groups(status, id);
```

状态机对齐 fb_posts：`pending → in_progress → done/failed`。`in_progress` 是
「已入队未终态」的互斥标记——平台 enqueue_fb_group_batch 与群采集消费之间靠它
防重复喂货（语义与 fb_posts 双写入方一致，§8.5）。

### 4.2 既有表增量（零 DDL）

- `fb_posts`：本期不改结构；新增写入方 discover，`source` 取值新增 `'ddg'`
  （原 `'apify'` 语义保留）。
- `fb_contacts`：不改结构；新增写入方 FbGroupTask，`post_url` 溯源为群帖 URL。

### 4.3 迁移责任

- fetcher `db.py`：fb_groups 建表 + `save_fb_posts` / `upsert_fb_groups` /
  `mark_fb_group_done` / `mark_fb_group_failed` / `reset_fb_groups_in_progress`
  等写函数（短事务 + `PRAGMA busy_timeout = 30000`，WAL 并发安全）。
- 平台 `app/db.py`：`enqueue_fb_discover_batch` / `enqueue_fb_group_batch`
  （sqlite_master 防御性探测，表不存在返回 0——参照 enqueue_fb_post_batch 模式；
  平台不 import fetcher，SQL 平台侧重写，语义由同一 SPEC + 测试锚定）。

## 5. fetcher 侧设计

### 5.1 `FetchDdgSerp` 原子（新文件 `fetcher/fetcher/atoms/facebook_discover.py`）

```python
class FetchDdgSerp:
    name = "fetch_ddg_serp"
    title = "DDG抓FB群帖SERP"

    params = {
        "query":      str   必填，查询词（默认矩阵带 site:facebook.com/groups 前缀）
        "page":       int   可选，页码（1 起，offset=(page-1)*10，缺省 1）
        "sample_min": float 可选，查询间节奏下限秒（task 从 ctx.config 透传；
                             原子强制下限 60，spike 依据见 §8.1）
        "sample_max": float 可选，查询间节奏上限秒
        "timeout":    int   可选，HTTP 超时（缺省 30）
    }
```

- **HTTP**：urllib 裸 GET `https://html.duckduckgo.com/html/?q=<quote(query)>&s=<offset>`，
  浏览器 UA（Chrome 125 同款）+ `Accept-Language: zh-CN` + `Accept-Encoding: gzip`
  （响应 gzip 解压）。模块级 `_http_get(url, timeout) -> (status, html)` 独立成函数，
  单测 monkeypatch 即可覆盖全部 HTTP 路径（对齐 facebook_group.py 的 `_http_json` 模式）。
- **纯函数 `parse_serp_results(html) -> list[{"url","title"}]`**：正则抽
  `<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=<enc>&amp;rut=...">`
  锚点 → `uddg=` 参数 URL 解码 → 标题去标签/HTML 实体（&amp; 等）。返回**全部**有机
  结果（不过滤），FB 过滤在下一级纯函数。真实样本：spike/ddg_sample_1.html。
- **纯函数 `classify_fb_url(url) -> ("post"|"group", group_id, group_url) | None`**：
  - `POST_RE = facebook\.com/groups/[^/]+/(?:posts|permalink)/(\d+)` → kind="post"，
    group_url = 派生的群主页 `https://www.facebook.com/groups/{gid}`；
  - `GROUP_RE = facebook\.com/groups/([^/]+)` → kind="group"，group_url = URL 自身
    （归一化到 `https://www.facebook.com/groups/{gid}`，去尾部斜杠）；
  - 其余 URL（FB 视频/用户主页/广告页/非 FB）→ None。
- **节奏**：无论 outcome，请求后 `ctx.wait(random.uniform(sample_min', sample_max))`
  （`sample_min' = max(sample_min, 60)`，模块常量 MIN_SAMPLE_FLOOR 注释写明 spike
  依据）；**HTTP 202（anomaly 限流）时先 `ctx.wait(uniform(180, 240))` 再返回
  BLOCKED**（覆盖 spike 实测封禁窗口，§8.1）。
- **Outcome 口径**（对齐 FetchFbGroupPosts）：
  - 200 + results → **OK**，`data={"engine":"ddg","query","page","results":[
    {"url","title","kind","group_id","group_url"}...]}`
  - 200 + 0 结果 → **EMPTY**
  - 202（anomaly）/ 403 / 429 → **BLOCKED**
  - 传输错误 / 5xx / 超时 → **NET_ERROR**
  - 被停止信号中断 → **SKIPPED**

### 5.2 `FbDiscoverTask`（新文件 `fetcher/fetcher/sites/facebook/discover_task.py`）

local 消费者，参照 `fetcher/fetcher/wa_task.py` 的 WaCheckTask 形态：

- 类属性：`name="fb_discover"`、`unit="查询"`、`QUEUE="discover_fb"`。
- `prepare(config)`：打印队列待处理数（discover 无源表状态机，无需崩溃恢复）；
  返回 True。
- `acquire_item(ctx)`：`claim_next_eligible(["discover_fb"], consumer_id_for(ctx))`，
  payload 注入 `id`（对齐 WaCheckTask）。
- `label(item)`：`f"{item['query']} 第{item['page']}页"`。
- `fetch(ctx, item)`：调 FetchDdgSerp 原子，params 透传
  `query/page/sample_min/sample_max`（节奏取 `ctx.config.sample_min/max`）。
- `on_success(ctx, item, result)`：把 `result.data["results"]` 分流落库：
  - 帖 permalink 类 → `db.save_fb_posts(keyword=item["query"], source="ddg",
    posts=[{"url","group_id","group_name"}...])`；
  - 全部 FB 群 URL（群主页 + 帖派生）→ `db.upsert_fb_groups([{"url","group_id",
    "name"}...])`（name 取 SERP 标题去 `" | Facebook"` / `" - Facebook"` 后缀，
    近似溯源）；
  - stats 计数（ok/empty/failed），返回新增帖数（计入批次配额）。
- `on_giveup(ctx, item, reason, kind)`：BLOCKED/NET_ERROR/EMPTY 无落库，仅日志短语
  + stats；返回短语。
- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。

### 5.3 `FbGroupTask`（新文件 `fetcher/fetcher/sites/facebook/group_task.py`）

包装 FetchFbGroupPosts 的 local 消费者：

- 类属性：`name="fb_group"`、`unit="群"`、`QUEUE="crawl_fb_group"`。
- `prepare(config)`：**fb_groups in_progress → pending 崩溃恢复**（对齐
  FbPostTask.prepare 模式；`reset_daemon_state` 只认 domain_suffix 非空的 contact
  队列，不覆盖 fb_groups，由本 Task 补位）。
- `acquire_item(ctx)`：`claim_next_eligible(["crawl_fb_group"], ...)`，payload 注入 id。
- `label(item)`：`f"{item['url']}（{provider}，≤{limit}帖）"`。
- `fetch(ctx, item)`：`FetchFbGroupPosts().run(ctx, {"url","provider","limit"})`
  （原子已有实现，零改动）。
- `on_success(ctx, item, result)`：
  - 逐帖 `db.save_fb_contacts(post_url, group_id, post["phones"])`——正文全文已在手，
    号码直接落库，**无需再走 crawl_fb_post**；
  - `db.mark_fb_group_done(url, post_count, has_contact)`（回写
    post_count/has_contact/last_crawled_at）；
  - stats 计数，返回帖数。
- `on_giveup(ctx, item, reason, kind)`：`db.mark_fb_group_failed(item["url"])`
  （402/429 额度/限流、网络错误、无帖均置 failed；重跑由平台重开批次）；
  返回短语。
- `on_abort`：群留在 in_progress，下次运行 prepare 自动放回 pending（对齐
  FbPostTask）。
- `giveup_cost(item)`：返回 1（计入批次配额）。
- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。

### 5.4 队列注册（`fetcher/fetcher/cli/main.py _build_registry`）

```python
specs.append(QueueSpec(
    queue="discover_fb", site=None,
    task=FbDiscoverTask(),
    topup=None,                      # 货源=平台批次参数，无自喂
    domain_suffix="",
    requires={"local"},
))
specs.append(QueueSpec(
    queue="crawl_fb_group", site=None,
    task=FbGroupTask(),
    topup=None,                      # 货源=平台批次参数（fb_groups pending）
    domain_suffix="",
    requires={"local"},
))
```

### 5.5 `FbPostTask.on_success` 改动（**唯一既有 Task 改动点，幂等**）

在现有「save_fb_contacts + mark_fb_post_done」之后追加：

```python
if group_id:
    db.upsert_fb_groups([{"url": f"https://www.facebook.com/groups/{group_id}",
                          "group_id": group_id, "name": item.get("name") or ""}])
```

语义：**每抓到一帖 = 发现一个群**（种子路径②）；INSERT OR IGNORE 幂等、不触碰
既有群状态机（只写 pending 新行），对既有 fb_posts/fb_contacts 状态流零影响。

### 5.6 fetcher/db.py 新增（建表区 + 写函数区）

- 建表区：fb_groups 表 + idx_fb_groups_status 索引（§4.1，幂等 CREATE IF NOT EXISTS）。
- `save_fb_posts(keyword, source, posts) -> int`：INSERT OR IGNORE（url UNIQUE），
  带 keyword/source/group_id/group_name/first_seen_at；返回新增行数。
- `upsert_fb_groups(groups) -> int`：INSERT OR IGNORE（url UNIQUE），status 默认
  pending；已存在行不动 status（保持采集进度）；返回新增行数。
- `mark_fb_group_done(url, post_count, has_contact)`：status=done + 回写三字段。
- `mark_fb_group_failed(url)`：status=failed。
- `reset_fb_groups_in_progress() -> int`：in_progress → pending。
- 全部短事务 + busy_timeout=30000。

## 6. 平台侧设计

### 6.1 批次类型注册（四处同步铁律 + Tasks.tsx）

`runner.py BATCH_TYPES` 追加（BATCH_TYPE_NAMES 自动并集）：

```python
"fb_discover": {"queue": "discover_fb", "site": None,
                "domain_suffix": "", "kind": "fb_discover"},
"fb_group":    {"queue": "crawl_fb_group", "site": None,
                "domain_suffix": "", "kind": "fb_group"},
```

`enqueue_batch_for_task` 追加两分支：

```python
if spec["kind"] == "fb_discover":
    return enqueue_fb_discover_batch(task_id, params.get("keywords") or "",
                                     int(params.get("pages") or 1))
if spec["kind"] == "fb_group":
    return enqueue_fb_group_batch(task_id,
                                  (params.get("provider") or "brightdata"),
                                  int(params.get("posts_per_group") or 50),
                                  limit)
```

### 6.2 app/db.py 新增

- `enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`：
  关键词（换行分隔）逐词 × 页码展开；payload
  `{"kind":"serp","engine":"ddg","query":kw,"page":N}`；`requires='["local"]'`、
  site=NULL、batch_id；**幂等：同 query+page 已有 pending 跳过**；keywords 空 → 0。
  返回入队 item 数。
- `enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`：
  `BEGIN IMMEDIATE` 单事务：SELECT pending fb_groups（limit>0 限量）→ INSERT
  work_items（payload `{"url","provider","limit"}`，limit=posts_per_group）→
  源行置 in_progress；**fb_groups 表不存在（fetcher 侧未建）→ 返回 0**（防御性
  探测，对齐 enqueue_fb_post_batch）。返回入队行数。

### 6.3 api/tasks.py TaskParams 追加

```python
keywords: str | None = None         # fb_discover：查询词，换行分隔原文
pages: int | None = None            # fb_discover：每词页数（1-10）
provider: str | None = None         # fb_group：brightdata / apify
posts_per_group: int | None = None  # fb_group：每群帖数上限
```

### 6.4 进度与观测（自动兼容，冒烟验证）

sweeper / stopped 兜底 / 循环重启 / SSE / dispatcher 看板均按 BATCH_TYPES 并集 +
work_items 泛化驱动：新类型**自动兼容**（dispatcher.queue_depth 无白名单，已核实
`platform/server/app/api/dispatcher.py` GROUP BY queue, status）。冒烟验证项：看板
出现 discover_fb / crawl_fb_group 两条队列。

### 6.5 运维：platform/start.sh

追加（daemon 启动前，pass-through 幂等）：

```bash
# FB 群采集第三方 API key（fb_group 批次用；缺失时该群采集 FATAL → 批次 failed）
export BRIGHTDATA_API_KEY="${BRIGHTDATA_API_KEY:-}"
export APIFY_TOKEN="${APIFY_TOKEN:-}"
```

注释注明：key 由部署方在启动 shell 环境提供（`.env` 已 gitignore，不入库）；
daemon 继承该环境（start.sh 的 nohup 子进程天然继承）。**缺失时原子 FATAL 是既有
行为，本期不新增凭证体系。**

## 7. 前端设计（交互形态定死，不留二选一）

### 7.1 lib/api.ts

- `TaskType` 追加 `'fb_discover' | 'fb_group'`。
- `TaskParams` 追加 `keywords?: string`（换行分隔原文）、`pages?: number`、
  `provider?: string`、`posts_per_group?: number`。

### 7.2 task-ui.tsx

- `TASK_TYPE_OPTIONS` 追加两项：
  - `fb_discover` → label **「Facebook 帖子发现」**
  - `fb_group` → label **「Facebook 群帖采集」**
- `paramsSummary` 追加两分支：
  - `fb_discover` → `N 词 × M 页` + 循环（N=keywords 按换行拆词计数，M=pages 缺省 1）。
  - `fb_group` → `provider=Bright Data|Apify` + `每群≤N帖`（posts_per_group）+
    `群数上限=M`（limit，0=不限）+ 循环。

### 7.3 TaskFormDialog.tsx（两独立表单分支）

`fb_discover`、`fb_group` **不进 isBatch 共用简表单**，各开独立分支（现有
isBatch / isWaCheck / 默认 三选一扩为五形态）：

- **fb_discover 分支**：
  - 关键词 Textarea（`min-h-24 font-mono text-xs`，每行一个查询词，**预填默认
    矩阵**，见 §7.4）。
  - 每词页数 number input（label「每词页数」，默认 1，min 1，max 10）。
  - 循环间隔（秒）number input（0 = 不循环）。
  - hint（text-xs text-muted-foreground）：`DDG SERP 单 IP 限流（实测约 2 连查即
    封、约 4 分钟恢复），查询间有节奏冷却，整批约 8-15 分钟跑完`。
- **fb_group 分支**：
  - provider Select（brightdata →「Bright Data（默认）」/ apify →「Apify」）；
    `SelectTrigger` 必须 `h-8` + 显式 `font-medium`（DESIGN.md §5 Select 与按钮
    并排规范）。
  - 每群帖数 number input（label「每群帖数上限」，默认 50，min 1）。
  - 群数上限 number input（label「群数上限」，默认空 = 不限，min 0）。
  - 循环间隔（秒）number input。
  - hint：`Bright Data 免费层 5K 条/月额度；provider key 走环境变量
    BRIGHTDATA_API_KEY / APIFY_TOKEN（缺失时该群采集失败）`。
- `buildParams` / `validate` 增加两分支：keywords 透传原文（换行保留）、
  pages 校验 1-10、posts_per_group 校验 ≥1、provider 限定 {brightdata, apify}。
- `fillFromParams` 增加 keywords/pages/provider/posts_per_group 回填（编辑/模板
  加载）。
- `paramsKey` memo 增加新表单状态键（触发预览防抖）。

### 7.4 默认关键词矩阵（表单预填，取自 facebook-groups.md §2 实测高命中）

```
site:facebook.com/groups 外贸 whatsapp
site:facebook.com/groups 跨境电商 whatsapp
site:facebook.com/groups china sourcing whatsapp
site:facebook.com/groups 货代 微信
site:facebook.com/groups 亚马逊卖家 微信
```

### 7.5 Tasks.tsx

`BATCH_TYPE_NAMES` 追加 `'fb_discover' | 'fb_group'`（启用批次进度渲染；归档
SPEC §6.2 记录的坑：漏加则任务列表进度列不显示批次进度）。

## 8. 契约与行为后果（spike 实测回填）

### 8.1 DDG SERP 可抓性与限流（**动工前 spike，2026-08-09 本环境实测完成**）

| 项 | 结论 | 依据 |
|---|---|---|
| Bing 常规搜索裸抓 | ❌ 不可抓：恒返回 challenge 脚本（`bing.com/challenge/verify`），b_algo=0 | 实测 2 组查询（含 setlang/cc 变体）均 challenge |
| Bing RSS 端点 | ❌ 不可用：返回无关垃圾结果（IP 被标记后的空响应形态） | 实测 `?format=rss` |
| DDG html 端点裸抓 | ✅ 可抓：GET + 浏览器 UA + gzip 解压，返回 10 条有机结果，无验证码 | 实测 4 组查询 3 组 200（样本存 spike/ddg_sample_1.html） |
| DDG 限流 | **约 2 次连查后第 3 次 HTTP 202（anomaly 页）；202 触发到恢复的窗口实测约 4 分钟**（探测起点已在封禁中，再静置 120s 恢复） | 时序：q1@0s 200、q2@3s 200、q3@6s 202；30s 后 SSL EOF、90s 后仍 202、封禁中再静置 120s 后 200 |
| DDG 分页 | `&s=<offset>`（表单 `input name="s" value="10"` 确认） | 样本 HTML；**2026-08-09 复核（PLAN Step 1.1）：`&s=10` 实测 HTTP 200、响应 33KB、含 `class="result__a"` 结果锚点、无 anomaly 字样，分页可用** |
| 结果构成 | `site:facebook.com/groups` 中文词查询：10/10 为 FB 群 URL；**群主页 ~90%、帖 permalink ~10%** | 实测 2 组查询（外贸 whatsapp 1/10 帖、跨境电商 whatsapp 0/10 帖） |
| 结果形态 | redirect `//duckduckgo.com/l/?uddg=<enc>&rut=...`；标题 inner text（群主页带 `" \| Facebook"` 后缀） | 样本 HTML 结构核实 |

**设计数字（据此裁定，初值；Step 1.1 复核可调）**：原子查询间节奏下限 60s
（~1 查询/分钟，低于 2 连查即封的突发阈值，留安全余量）；202 时退避
uniform(180,240)s（覆盖 ~4 分钟封禁窗口）后返回 BLOCKED；默认矩阵 5 词 × 1 页
整批 ~8-15 分钟（循环模式建议 repeat_interval ≥ 30 分钟）。

### 8.2 回退分支（spike 不过时的预案，本期未触发）

1. **DDG 全量不可用**（长期 202/403）：改 BrowserConsumer 渲染抓 Bing——
   `discover_fb` 队列 site 改 "facebook"、requires 改 `{"channel","browser"}`、
   payload engine="bing"；原子换实现（渲染抓 SERP 页解析），Outcome 口径不变，
   parse_serp_results 保留（Bing HTML 结构另写解析纯函数）。
2. **自建全线失败**：回 Apify SERP 路线（归档 SPEC §5.3 设计可用），fb_posts
   数据面不变，仅 discover 队列的原子/engine 替换。
3. **熔断判定**：Phase 1 冒烟连续 2 批全 BLOCKED → 启用回退 1；回退 1 也失败 →
   回退 2。判定记录回填本 SPEC。

### 8.3 限流与批次规模的交互

- 默认矩阵 5 词 × 1 页 = 5 item/批；节奏下限 60s → 单批 ~5 分钟 + 202 退避余量
  ≈ 8-15 分钟（含 1-2 次 202 的退避等待）。
- 同一时点建议只跑一个 fb_discover 批次（平台不强制；多批并发会互相触发 202，
  属运维注意，非代码约束——两个 local 消费者同查 DDG 时由各自节奏错峰）。

### 8.4 FetchFbGroupPosts 在 local 消费者下的 ctx 契约

- 假设：`ctx.wait` 可中断等待在 local 消费者（WorkerContext）可用，BD 轮询中断
  路径（_Interrupted → SKIPPED）正常。
- 依据：**已验证代码路径**——FetchFbGroupPosts 的 BD 异步三段式轮询已用
  `ctx.wait(interval)`（facebook_group.py:148），LocalLoop 不装配 page，原子无
  page 依赖（逐项核对过）。
- 验证：Phase 2 冒烟（真实 key 或 mock 集成测试）。

### 8.5 fb_groups 双写入方互斥（种子路径①+②）

- 写入方①：FbDiscoverTask.on_success（SERP 群主页 + 帖派生群 → upsert）；
  写入方②：FbPostTask.on_success（每抓一帖 → 其群 upsert）。
- 两路均 `INSERT OR IGNORE`（url UNIQUE）+ 不动既有行 status → 幂等、无重复行。
- `enqueue_fb_group_batch` 与群采集消费之间靠 in_progress 互斥（BEGIN IMMEDIATE
  单事务 SELECT+INSERT+UPDATE，与 enqueue_fb_post_batch/topup 已验证事务模式
  一致——归档 SPEC §7.4）。

### 8.6 validate 阈值 / 结果有效性

- discover 原子 200 但 0 结果（SERP 无 FB 链接或末页）→ EMPTY，on_giveup 无落库
  （不误报失败）。
- fb_group 原子 EMPTY（群无帖/无权限）→ on_giveup 置群 failed——语义=「该群本次
  无可采」，与 FbPostTask 的 failed 语义一致（重跑可再试）。

## 9. 职责分配（初始化 + 变更路径）

| 数据 | 初始化（谁写） | 变更（谁写/谁读） |
|---|---|---|
| fb_groups 行 | ① FbDiscoverTask.on_success（SERP 群主页 + 帖派生群）② FbPostTask.on_success（每抓一帖=发现一群）——均 INSERT OR IGNORE 幂等 | 状态：enqueue_fb_group_batch 置 in_progress；FbGroupTask.on_success/on_giveup 置 done/failed + post_count/has_contact/last_crawled_at；FbGroupTask.prepare 崩溃恢复 in_progress→pending。读：enqueue_fb_group_batch（pending）、平台数据页（后续，非本期） |
| fb_posts 行 | FbDiscoverTask.on_success `save_fb_posts`（source='ddg'）——**新增写入方** | 状态机既有：enqueue/topup 置 in_progress；FbPostTask.on_success/on_giveup 置 done/failed + has_contact；FbPostTask.prepare 崩溃恢复（不改） |
| fb_contacts 行 | FbGroupTask.on_success 逐帖 `save_fb_contacts`（post_url=群帖 URL）——**新增写入方** | wa_registered/wa_checked_at/wa_source：WaCheckTask 回写（既有，零改动）。读：wa_check 挑号双源（既有） |
| work_items(discover_fb) | 平台 enqueue_fb_discover_batch（**唯一写入方**，topup=None） | 终态：QueueRouter.finish/release；停止：runner 压 stopped |
| work_items(crawl_fb_group) | 平台 enqueue_fb_group_batch（**唯一写入方**，topup=None） | 同上 |
| 提取副产物（微信/TG/邀请链接） | FbGroupTask 经 on_success 数据带上 → QueueRouter 落 work_items.result_json（既有机制，自动兼容） | 只读观测，无变更路径 |
| 环境变量 | BRIGHTDATA_API_KEY / APIFY_TOKEN（start.sh 导出 pass-through，§6.5） | 缺失时原子 FATAL → 批次 failed（既有行为，不新增凭证体系） |

## 10. 验收标准（feature 级）

1. 平台创建 fb_discover 任务（默认矩阵 × 1 页）→ daemon local 消费者节奏跑批 →
   fb_posts 出现 source='ddg' 的帖行、fb_groups 出现群行（SERP 群主页 + 帖派生群），
   keyword 溯源正确；同批/循环重跑无重复行（url UNIQUE）。
2. 平台创建 fb_group 任务 → daemon 调 FetchFbGroupPosts → 群状态机
   pending→in_progress→done/failed 流转、post_count/has_contact/last_crawled_at
   回写 → fb_contacts 出现群帖号码（post_url 溯源正确）。
3. FbPostTask 抓帖后其群自动出现在 fb_groups（种子路径②），对既有
   fb_posts/fb_contacts 状态流零回归。
4. wa_check 批次自动涵盖新落的 fb_contacts 号码（既有双源链路，零代码改动，冒烟
   观察）。
5. dispatcher 看板出现 discover_fb / crawl_fb_group 两条队列（queue_depth 自动
   聚合）。
6. 全量回归：fetcher 测试全绿（新增原子/Task/DB/CLI 测试 + 既有 FB 测试不动）、
   平台测试全绿、`npx tsc -b` 通过。

## 11. 冲突扫描结论（呈交前自查）

### 11.1 PLAN vs 代码库现状

- 所有改动点（_build_registry 两 QueueSpec、BATCH_TYPES 两类型、
  enqueue_batch_for_task 两分支、TaskParams 四字段、前端五处）均为**纯新增分支**，
  不改既有导出与签名。
- **唯一既有行为改动点**：FbPostTask.on_success 追加 upsert_fb_groups 一行
  （幂等 INSERT OR IGNORE，不触碰群状态机与既有状态流；回归由验收 #3 覆盖）。
- `reset_daemon_state` 不覆盖 fb_groups（domain_suffix="" 跳过）→ FbGroupTask.prepare
  补位（对齐 FbPostTask 既有模式，**无框架改动**）。
- Tasks.tsx BATCH_TYPE_NAMES 漏加 → 批次进度列不显示（归档 SPEC §6.2 记录的坑），
  列入 Step 4.4 硬性验收。
- 前端 buildParams/validate/fillFromParams 的三选一（isBatch/isWaCheck/默认）扩为
  五形态，涉及既有分支结构——是前端主要改动面，Step 4.3 单独列验收（既有类型
  行为零回归）。

### 11.2 PLAN 内部

- Phase 1（discover）与 Phase 2（fb_group）在**DB 层共享依赖**：upsert_fb_groups
  与 fb_groups 建表被两 Phase 的 on_success 共同使用 → 该 DB 前置步（建表 +
  写函数）列为 **Phase 1 Step 1.1**，Phase 2 依赖之（PLAN 依赖标注）。
- Phase 3 依赖 Phase 1+2（BATCH_TYPES 双类型）；Phase 4 依赖 3；Phase 5 依赖全部。
- 默认矩阵 5 词 × 1 页 + 60s 节奏 → 单批 8-15 分钟；若 spike 复核数字偏差（恢复
  更慢/更快），原子节奏/退避参数可调，验收 #1 不受影响。

### 11.3 PLAN vs 外部依赖

- DDG html 端点：spike 实测存在且可抓（§8.1），无 API key、无账号要求。
- FetchFbGroupPosts：已有实现 + 17 测全过 + 真机实测记录（facebook-groups.md §12），
  本期零改动只接队列。
- BRIGHTDATA_API_KEY / APIFY_TOKEN：环境变量（原子已支持）；缺失 → FATAL →
  批次 failed（既有行为，验收 #2 用 mock 场景覆盖，不依赖真实 key）。
- 无新 Python 包（urllib 标准库）、无新 npm 包。

### 11.4 遗留风险

- DDG 分页 `&s=` 的 200 态未实测（限流窗口内返回 202）→ 列入 PLAN Step 1.1 spike
  复核项（等待恢复后单次验证）；若 `&s=` 不生效，page>1 结果与 page1 重叠，靠
  INSERT OR IGNORE 天然去重，功能不损坏。
- FetchFbGroupPosts 在 local 消费者真机表现（BD 异步三段式 ~40s/群）→ Phase 2
  冒烟用真实 key 或 mock 验证。
- 平台侧测试基建已核实存在（platform/server/tests/test_batch_tasks.py，
  enqueue 批次测试模式可参照）。
- daemon 有头运行（start.sh DAEMON_ARGS 含 --headed）与本 feature 无关：新队列
  均为 local 消费者，不弹浏览器窗口。

## 12. 评审裁决记录（呈交后填写）

1. [ ] 范围裁定（两段全包 / 拆分）
2. [ ] 引擎裁定（DDG 优先，Bing 回退预案）
3. [ ] 节奏/限流数字（60s 下限 + 180-240s 退避）确认
4. [ ] 前端交互形态确认
5. [ ] 其他意见
