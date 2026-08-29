# AGENTS.md — 1688 采集平台开发约定

> 本文件是面向 AI 编码 agent 的项目级指令。改代码前先读本文件；**改前端前必须读 [DESIGN.md](DESIGN.md)**（设计规范唯一文字来源，本文件只做摘要与强制引用）。

## 1. 日常运行

**常驻采集脚本共 4 个，均在项目根目录下启动（先确认无残留进程再启动）：**

```bash
# ① FB 关键词直搜采号（memo23 + BD SERP 双源，常驻循环；
#    2026-08-21 重写为「牧场」模型，与 X 同款：每词隔 3 天刺探一次
#    （SERP 双引擎各 1 页 + memo23 最新 50 帖），有新号则 maxItems 按 ×4
#    倍增深翻（50→200→400 封顶，2026-08-22 起，挖到 +0 为止），
#    连续 3 次会话无新号自动退役；首次会话帖 <10 且无新号
#    直接退役不等连击，2026-08-23 起）
nohup python3 scraper/fb_keyword_search.py --keywords-file .cache/fb_keywords_extra.txt \
  --memo23-daily-results 5000 >> .cache/fb_keyword_search.log 2>&1 &

# ② X 关键词直搜采号（xquik/x-tweet-scraper 单源，常驻循环，10 分钟一轮；
#    2026-08-22 重写为「牧场」模型：每词隔 3 天刺探一次最新 50 帖，有新号
#    按 until_time 往历史翻页深挖（每批 50，封顶 20 批）直到某批 +0；
#    连续 3 次会话无新号自动退役，首次会话帖 <10 且无新号直接退役，
#    无回扫/增量之分）
nohup python3 scraper/x_keyword_search.py --keywords-file .cache/x_keywords_all.txt \
  --per-round 5 --interval 600 --delay 3 --daily-results 80000 \
  >> .cache/x_keyword_search.log 2>&1 &

# ③ WhatsApp 注册态查询（Apify，10 分钟一拍的常驻循环）
nohup bash -c 'while true; do python3 scraper/wa_check_apify.py \
  --bucket declared_wa,cn_uncertain --min-batch 100; sleep 600; done' \
  >> .cache/wa_check_apify.log 2>&1 &

# ④ 领英美国 HNW 采号（Apify 双 actor 常驻循环：harvestapi 搜人 →
#    skip-trace 查号 → 州级验证 → devscrapper 查 WA 注册态；
#    2026-08-25 上线，调研见 docs/linkedin-hnw-research.md。
#    目标：us_contacts wa_registered=1 达 500 条自动退出（exit 0）；
#    预算刹车 --max-budget 80（按各 run 官方 usageTotalUsd + WA $0.004/号
#    估算累计，到顶 exit 3）；30 地点 × 5 职位 = 150 组合搜完也会退出，
#    需加 --locations/--titles 新词重启。州级验证 = trace 记录地址州与
#    领英州一致才收号（同名错人严重，宁可漏不可错）；性别走 SSA 离线
#    数据集（.cache/ssa_gender.json 缓存，ssa.gov 直连 403，2026-08-25
#    实测需经 web.archive.org 镜像取 names.zip 放 .cache/ssa_names/ 构建）。
#    状态 .cache/linkedin_us_search_state.json；进度看 --stats）
nohup python3 scraper/linkedin_us_search.py \
  >> .cache/linkedin_us_search.log 2>&1 &
```

要点：
- 词库：FB 用 `.cache/fb_keywords_extra.txt`（内置词之外的扩展词），X 用 `.cache/x_keywords_all.txt`；加词直接追加新行，**禁止 `sort -u` 重写词库**。
- 状态/预算记 `.cache/fb_keyword_search_state.json` 与 `.cache/x_keyword_search_state.json`；日志在 `.cache/*.log`，排查先看日志尾部。
- **深翻倍增策略（无游标数据源统一采用，2026-08-22 起）**：没有分页游标的数据源（如 memo23），深翻 = 用更大 maxItems 重跑整个 run、按交付结果计费（每批都重复交付前面所有帖），等步进加批会把钱烧在重复交付上。因此统一用「小批量刺探 + 出号倍增 + 单批封顶」：首批刺探 `PROBE_ITEMS`(50)，这批出号则下批 maxItems ×`DIG_MULTIPLIER`(4)（50→200→400），单批封顶 `DIG_MAX_ITEMS`(400)，任一批新号 +0 / 帖空 / 单批到顶即换词；热词单词会话最多交付 650 条 ≈ $1.24。参数集中在 `fb_keyword_search.py` 顶部（PROBE_ITEMS/DIG_MULTIPLIER/DIG_MAX_ITEMS），调策略只改这三个数。有真游标的源（X 的 until_time 翻页）不适用——每批都是新帖不重复计费，直接按批翻到 +0 为止。
- Apify 402/403 欠费时脚本会记 `providers.quota_exhausted_at` 并自动轮换账号，30 天账期内跳过耗尽账号；充值到账后需清掉该标记（`UPDATE providers SET quota_exhausted_at=NULL WHERE kind='apify'`）再重启脚本。
- 群线脚本（`fb_group_discover_bd.py` / `fb_group_bd.py`）**已封存，一律不启动**（单号成本是直搜的 10~40 倍，2026-08-19 用户拍板）。

**启动 platform（管理系统）：**

```bash
bash platform/start.sh   # 一键启动后端（FastAPI，端口 8765）+ 前端（Vite dev，端口 3000）
bash platform/stop.sh    # 停止
```

FB/X/WA 三个采集脚本也可在管理系统 `/scripts` 页启停、调参与看实时日志（2026-08-23 起；调参仅落库 `script_configs`，重启进程后才生效）；领英脚本（④）暂不接入 /scripts 页，只能命令行启停。

**巡检**：每小时跑一次，费用已自动同步（后端启动起每 30 分钟跑一轮 `costs.sync_all`，见 `app/main.py` 的 cost-sync 线程；要立刻刷新仍可手动 `curl -s -X POST http://127.0.0.1:8765/api/costs/sync`，或点供应商页卡片上的「同步余额/同步用量」按钮（按供应商单独同步，走 `/api/costs/sync?provider=<kind>&account=<name>`））→ 查 4 个脚本进程是否存活（领英脚本额外看 `--stats` 的 WA 已注册进度与 state 费用）→ 查近 1h/3h 逐小时新增（`scraper/inspect_stats.py`，只读）→ 查 fb_contacts 全量汇总（采集/已注册/待审核，按 post_url 域名分 FB/X，只读查询 `file:.cache/1688.db?mode=ro`）→ 对照 state JSON 日用量排除预算刹车 → 确认关键词枯竭才换词（`grep -qxF` 去重追加）并重启对应脚本生效。

换词触发条件：先对照表 4 排除预算刹车/额度耗尽等外部原因；确认是词库问题后——**某渠道连续 2 小时新增 < 30 条，即可尝试更换关键词**（不用等彻底枯竭）。词级判据用 `python3 scraper/kw_stats.py --aging`（只读）：脚本把每词每次查询的表现记在 state JSON 的 `kw_stats`（q/posts/new/last_new_at/zero_streak=连续新号+0 次数，2026-08-22 起累计，此前历史不回溯），报表按此推导状态——退役（X/FB 脚本自动判真枯竭，已移出轮转）、枯竭（>7 天无新号且查询 ≥5 次）、老化（3~7 天无新号或连续+0 ≥10）、活跃、观察（查询 <5 次）、未启用；**枯竭/老化词优先列入换词候选**，全量看 `kw_stats.py`、产量榜看 `--top N`。**词自动退役（X 2026-08-22 重写版起，FB 2026-08-21 重写版起同款）**：两脚本均为「牧场」模型——每词隔 3 天刺探一次，热词往深翻，连续 3 次会话无新号（≈9 天无产出）→ 自动记 `state.kw_retired` 并移出轮转（词库文件不动）；**首次会话帖数 <10 且无新号的词判定无潜力，首次即退役不等连击**（`FIRST_SESSION_MIN_POSTS`，2026-08-23 起，kw_retired 里带 `reason: first_session_few_posts`）；误判复活删 `kw_retired` 对应键，确认死词可手工从词库文件删行（`grep -vFx`，禁止 `sort -u` 重写）。

**X 换词标准流程（2026-08-21 起）**：X 词枯竭的判据是「帖还能搜到但新号连续 +0」（历史存量已采完，增量供给趋零，跨源去重也会吃掉一部分）。换词时不要盲目加词，先用 **WebBridge 在用户真实浏览器（带 X 登录态）逐词验证**：
1. 策展候选词（新品类 / 新语种 / 新形态，先对照 `.cache/x_keywords_all.txt` 排除已有词）。**品类词首选从 B2B 平台类目页批量采**：1688 国际站即阿里巴巴国际站 `https://www.alibaba.com/`（2026-08-22 用户确认官网，类目目录 `catalog.html`；首页重 JS，navigate 后等 6~10s 再 evaluate），或 made-in-china 类目目录 `https://www.made-in-china.com/products-directory/`（英文、结构干净，2026-08-21 实测好用）；world.1688.com 在真实浏览器里也 ERR_TOO_MANY_REDIRECTS 死循环（2026-08-22 实测），禁用；完整挖词流程见项目 skill `.kimi-code/skills/1688-keyword-mining/`；
2. **禁止 URL 拼接关键词直链（2026-08-22 用户指定）**：用 WebBridge 打开 `https://x.com/` 首页 → snapshot 找搜索框（`data-testid="SearchBox_Search_Input"`）→ fill 输入关键词 → 回车 → 切 Latest 标签；然后 `evaluate` 抽取 `article` 数、`article time` 最新时间戳、帖正文里的手机号正则命中；全程控制频率（搜索间隔 5~15s 随机，连续操作 ≤15 分钟停手汇报），防风控封号；
3. 收录标准：有结果且帖内含手机号/联系方式形态；只搜出无关帖或零结果的词弃用；
4. 验证通过的词 `grep -qxF` 去重后追加到 `.cache/x_keywords_all.txt`（**禁止 `sort -u` 重写**），重启 X 脚本生效。
注意：新词在 state 里无 `kw_stats` 记录即视为「到期」，重启后下一轮就会刺探它的最新 50 帖，无任何回扫成本；加词规模只需对照总预算（state 里 200000 行总上限，现行刺探模式每天顶格 ~92 次 × 50 帖 ≈ $0.7）。

**X/FB 词库共享（2026-08-21 起）**：词库都存文件不在数据库——FB 为脚本内置 `KEYWORDS`（234 词）+ `.cache/fb_keywords_extra.txt` 追加，X 为内置 `X_KEYWORDS` + `.cache/x_keywords_all.txt` 覆盖。X 验证通过的新词应同步跑一遍 FB 验证（WebBridge 开 `https://www.facebook.com/` 首页 → 顶部搜索框输入关键词回车 → 切「帖子/Posts」标签，统计正文中国手机号命中数 C，C>0 才收录，同 08-18 口径；同样禁止拼 `?q=` 直链），通过的 `grep -qxF` 追加到 `.cache/fb_keywords_extra.txt` 并重启 FB 脚本；反向同理。两平台卖家人群重叠但帖源不同，跨平台复用验证过的词是低成本扩量手段。

**巡检输出一律用表格，不用文字长段落**，固定四张表 + 一行结论：

表 1 · 进程状态：

| 脚本 | PID | 状态 | 备注 |
|---|---|---|---|
| FB 直搜 | 18539 | ✅ 运行中 | 当前轮关键词：xxx |
| X 直搜 | — | ❌ 已退出 | 日志尾部原因一行 |
| WA 查号 | 17269 | ✅ 运行中 | 上轮已查 N 条 |
| 领英直采 | — | ❌ 已退出 | WA 已注册 N/500，原因一行 |

表 2 · 逐小时明细（近 4 小时，按采集时间 first_seen_at 分小时；每小时采集的号按当前查号结果细分为 已注册/待审核/其中无效号，FB/X 分列；WA 已查 = 该小时查号完成数）：

| 小时 | FB 采集 | FB 已注册 | FB 待审核 | FB 无效号 | X 采集 | X 已注册 | X 待审核 | X 无效号 | WA 已查 |
|---|---|---|---|---|---|---|---|---|---|
| 08:00 | 45 | 30 | 5 | 1 | 12 | 8 | 2 | 0 | 100 |
| 09:00 | 38 | 25 | 3 | 0 | 0 | 0 | 0 | 0 | 100 |

表 3 · 全量汇总（fb_contacts 全表快照，按 post_url 域名分 FB/X；待审核 = `wa_registered IS NULL`，其中无效号 = `wa_source='invalid'`，已标记永远查不出、不算真待查）：

| 平台 | 采集 | 已注册 | 待审核 | 其中无效号 |
|---|---|---|---|---|
| FB | 8155 | 5417 | 180 | 20 |
| X | 2633 | 1488 | 37 | 37 |

表 4 · 当日预算用量（对照 state JSON，排除预算刹车）：

| 项 | 已用 / 上限 | 状态 |
|---|---|---|
| FB memo23 | 2032 / 5000 | 正常 |
| FB SERP | 120 / 400 | 正常 |
| X 日结果 | 5000 / 80000 | 正常 |
| Apify 账号 | 可用 1 个 | ⚠️ apify-查号 额度耗尽标记中 |
| Apify 真实账单（昨日/今日） | $11.7 / $5.6 | 来自 cost_records real 行 |
| 今日渠道估算 | memo23 $2.2 / SERP $0.2 / X $2.0 / WA $1.1 | 来自 cost_records estimate 行 |

费用口径：表 4 费用行读 `cost_records` 表（巡检开头的 `/api/costs/sync` 负责入库）。`source='real'` = Apify 官方账单（`channel` 形如 `account:<账号名>`，账号级粒度，date 为 Apify 原始 UTC 账单日期）；`source='estimate'` = 单价折算（`channel` 为 fb_memo23/fb_serp/x_keyword/wa_check，date 为北京日期），仅作渠道分摊参考。Bright Data 真实账单需 token 开 Billing 权限（https://brightdata.com/cp/setting/users），未开通前只有 fb_serp 估算行。

最后一行**结论**：一句话说清本次动作（无动作 / 重启了谁 / 换了哪些词及原因）。异常才展开说明，正常就一行带过。

## 2. 必读文档（按改动范围）

| 改动范围 | 必读 |
|---|---|
| `platform/web` 任何文件 | **[DESIGN.md](DESIGN.md)**（设计规范唯一来源，新增页面/组件前先读） |
| 数据库访问 | 见下方 §4 数据库约定 |

## 3. 设计规范摘要（完整约束以 DESIGN.md 为准）

**改 `platform/web` 前必须逐条对照 DESIGN.md，以下是最容易被违反的铁律：**

- **颜色 Token 唯一来源** `src/styles/tokens.css`：禁止在组件里散落硬编码色值（如 `#fff`、`rgb(...)`）；新增颜色走「tokens.css 加 token → tailwind.config.js 映射」两步，`:root` 与 `.dark` 两组 token 必须成对新增。
- **Select 与按钮并排**：`SelectTrigger` 必须 `h-8` + 显式 `font-medium`（默认 `font-normal` 会与按钮不齐）；长文案 trigger（如「每页 20 条」）**不要写死小宽度**，用 `w-fit` 自适应避免箭头压住文字；列表项文案与 trigger 一致。
- **按钮**：工具栏/分页条内统一 `variant="outline" size="sm"`；主操作才 `default`，危险操作 `destructive`。
- **状态徽标**：成功态用 `border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400`；同一状态全局同色（参考 `ShopsTab.shopStatusBadge`、`data/ContactsTab.tsx` 的 waBadge）。
- **页面骨架**：`PageHeader` → 筛选工具栏（`flex flex-wrap items-center gap-4`）→ 内容 → 分页。
- **页面状态**：一律用 `components/PageState.tsx` 的 LoadingState / ErrorState / EmptyState；Toast 全局只挂一次（Layout 的 Toaster），页内不重复挂。
- **表格分页**：表格外层 `rounded-lg border border-border`，数值列 `text-right`；分页统一 `PaginationBar`（`pages/data/shared.tsx`），左侧页码信息+每页条数选择器，右侧翻页按钮+跳页；时间戳用 `showTime` 直接展示，不做时区换算。
- **排版**：页面标题 `text-xl font-semibold`、描述 `text-sm text-muted-foreground`（PageHeader）；正文/表格/表单 `text-sm`；辅助信息 `text-muted-foreground` / `text-xs`。
- **圆角/阴影**：圆角以 `--radius: 0.625rem` 为基准（sm=-4px、md=-2px、lg=基准、xl=+4px）；阴影仅 `shadow-xs` 为基准微阴影，弹层 `shadow-md`。

## 4. 后端与数据库约定

- 时间戳一律为**北京时间字符串**（`YYYY-MM-DD HH:MM:SS`），**不要再做 +8 偏移**（库里已是北京时区）。
- SQLite 为 WAL 模式、爬虫可能正在写库：读连接用 `app.db.connect()`（只读，禁写）；写一律**短事务 + `PRAGMA busy_timeout = 30000`**。
- 新增列/表走 `app.db.migrate()` 幂等迁移；涉及可能缺列的场景要**防御性探测**（参考 `api/data.py` 的 `PRAGMA table_info` 探测模式）。
- `cost_records` 费用表（2026-08-21 起）：由 `POST /api/costs/sync`（`app/costs.py`）幂等 upsert，另由后端 cost-sync 线程每 30 分钟自动触发（2026-08-22 起）；UNIQUE 键含 `service`，**估算行的 service 存 `''` 而非 NULL**（SQLite UNIQUE 中 NULL 互不相等，upsert 会失效）。估算单价常量与 scraper 写死值保持一致（来源行号见 `costs.py` 顶部注释），改价两边同步。特殊 service 行：`BALANCE`（BD 余额快照，date 为北京快照日，存官方 API 原始值）、`USAGE_CYCLE`（Apify 当前账期累计用量快照，detail 含套餐额度/月度上限；Apify 为订阅+后付费无充值余额，2026-08-22 起），两者供供应商页展示余额/用量。**BD 余额口径**（2026-08-22 起）：官方 `/balance` API 的 `balance` 只扣待结算费用（`pending_costs`），不含 trial credit 抵扣的用量，与后台 Billing 页 Balance 差一个固定抵扣额；校准差值存 provider `config.billing_offset`（当前 7.57，源自 8/10 trial credit $7.50 抵扣），供应商页展示「可用余额 = balance − offset、本账期消耗 = pending_costs + offset」（`api/providers.py` `_bd_offset`），与官方后台一致；**新账期（9/1）或新增赠送额度后需重新校准/清零该 offset**。
- `wa_registered` 语义：`1`=已注册、`0`=未注册、`NULL`=未查。**注意 NULL 不等价
  `wa_checked_at IS NULL`**：存在查了但结果为 NULL 的失败行（2026-08-20 实测约百条），
  「待查」口径一律用 `wa_registered IS NULL`。
- fb_contacts 号码入库口径：**只收中国手机号，统一存裸 11 位**。过滤统一走
  `fb_group_bd.is_cn_number(number, source)` 且 `bucket != 'overseas'`
  （intl/wa_me/wa_label_intl 形态剥壳后 11 位 1 开头的实为 +1 北美号，拒收；
  2026-08-20 已清库：overseas 406 条假中国号删除、0086 前缀 14 条救回 cn_uncertain）。
  **2026-08-24 起 `save_fb_contacts`（fetcher/db.py）落库前把 +86/0086/86 +
  11 位手机段统一剥壳为裸 11 位**（此前 declared_wa 保留原文国家码/00 国际前缀
  致三种形态并存，已清洗：86 形态 7854 条、0086 形态 668 条，重复号合并字段后
  删除；清洗脚本 `util/strip_cn_prefix.py`（幂等、默认先备份）可反复跑；
  `8612345678901` 非标号段残留 1 条已标 invalid 未动）。
- fb_contacts WA 头像画像列（2026-08-25 起，由 `scraper/wa_avatar_profile.py`
  defensive ALTER 自建）：actor `clearpath/whatsapp-profile-avatar-age-gender-api`
  按号计费（实测 $7.53/千号，500 号起批/万号封顶，每个送检号都计费），
  只查 `wa_registered=1` 且 `wa_profiled_at IS NULL` 的号。`wa_gender`
  （male/female/unknown）与 `wa_age` 均为**头像推断，只做参考不做硬过滤**
  （实测 500 号：头像覆盖 94%、性别产出 47%、仅 individual_portrait
  子集出性别）；`wa_avatar_url` 是 waavatar.xyz 代理链、时效未知，
  要留图需送检后尽快另行下载；`wa_profile_json` 存原始行兜底。
  进度看 `python3 scraper/wa_avatar_profile.py --stats`。
- `us_leads` / `us_contacts` 领英美国采号表（2026-08-25 起，由
  `scraper/linkedin_us_search.py` 自建，CREATE TABLE IF NOT EXISTS，不走
  platform migrate，平台侧暂无页面读取）：`us_leads` 一人一行
  （linkedin_url 唯一；traced/trace_matched/state_verified 记查号进度，
  gender 为 SSA 名字推断 male/female/unknown；age 为采纳 trace 记录的
  age/born 字段推断，数据经纪来源只有约 39% 记录带值，NULL=未知，
  2026-08-25 起新增列，此前存量 lead 为 NULL）；`us_contacts` 一号一行
  （number 唯一，归一化 11 位 `1XXXXXXXXXX`；只收州级验证通过 lead 的号码，
  wa_source/wa_registered/wa_checked_at 三态语义同 fb_contacts）。
  进度与费用看 `python3 scraper/linkedin_us_search.py --stats`（只读）。
- `mined_corpus` 语料表（2026-08-22 起）：1688 国际站（alibaba.com）挖词 skill
  （`.kimi-code/skills/1688-keyword-mining/`）写入，**页面上看到的类目名/商品标题/链接全部入库**，
  商品标题是后期重要语料。`kind` = category1/category/product，UNIQUE(source,kind,title,url)，
  重复遇到只更新 `last_seen_at`。该 skill 流程：提取 → 清洗去重 → 语料入库 → 候选词直接追加
  X/FB 词库（**不做 X/FB 人工验证**，差词靠词库日落机制自动退役，2026-08-22 用户拍板）。
- `script_configs` 表（2026-08-23 起）：`/scripts` 页采集脚本启动参数配置，`name` 主键
  （fb/x/wa），`params` 为 JSON（fb `memo23_daily_results` / x `daily_results` / wa `min_batch`），
  由 `app/scripts.py` seed 默认值、`POST /api/scripts/{name}/params` upsert；脚本只认启动参数，
  改配置需重启进程才生效。进程探测用 `pgrep -f` 特征匹配（不写 pidfile），WA 停止时 bash
  循环壳与 python 子进程一起杀。
- `/scripts` 页选词启动（2026-08-23 起，仅 fb/x）：点「启动」弹选词面板（搜索/全选/清空，
  退役词带标记），`GET /api/scripts/{name}/keywords` 出词库清单（fb=内置 KEYWORDS+追加文件
  合并，x=`.cache/x_keywords_all.txt` 覆盖内置，内置词库用 ast 静态解析脚本源码不 import）。
  选词子集落盘 `.cache/{name}_keywords_selected.txt` 并记录到 `.cache/script_kw_selection.json`，
  启动命令改写词库参数（fb 用 `--keywords-only-file` 覆盖内置词库，x 直接换 `--keywords-file`
  路径）；**全选=默认词库并清除选词记录**，restart 不传选词、自动沿用上次记录。
  平台启动脚本时在日志写一段分隔标记（`=====` 横幅：时间/pid/参数/词库/完整命令，
  2026-08-24 起），区分历次运行；手动 nohup 启动的没有此标记。
- `/keywords` 词库页（2026-08-24 起）：`GET /api/keywords`（`app/api/keywords.py`）直接读
  两个 state JSON 的 `kw_stats`/`kw_retired` 按词合并两平台产量，**搜索/筛选/排序/分页全部
  服务端做**（page/page_size/q/platform/status/sort/order）。kw_stats 每词字段：
  q（累计轮数）/posts/new（累计新号）/**last_new（上一轮新号，2026-08-24 起记账，历史词为
  null）**/first_at/last_q_at/last_new_at/zero_streak；retired 口径=存在过的平台全部退役。
- 改后端代码后 uvicorn **不会自动 reload**，需重启才生效（重启见 `platform/start.sh`/`stop.sh`；注意 pidfile 记录的是父进程，杀端口占用进程时按实际监听 pid）。

## 5. 通用代码约定

- 类名合并一律用 `cn()`（`@/lib/utils`）；注释用中文，文件顶部一行注释说明模块职责。
- 前端提交前跑 `npx tsc -b`（`platform/web` 下）。
- 不动 `scraper/`、`util/` 旧脚本；新能力进 `platform/`（平台侧）。
