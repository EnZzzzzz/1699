# AGENTS.md — 1688 采集平台开发约定

> 本文件是面向 AI 编码 agent 的项目级指令。改代码前先读本文件；**改前端前必须读 [DESIGN.md](DESIGN.md)**（设计规范唯一文字来源，本文件只做摘要与强制引用）。

## 1. 日常运行

**常驻采集脚本共 3 个，均在项目根目录下启动（先确认无残留进程再启动）：**

```bash
# ① FB 关键词直搜采号（memo23 + BD SERP 双源，常驻循环）
nohup python3 scraper/fb_keyword_search.py --keywords-file .cache/fb_keywords_extra.txt \
  --memo23-daily-results 5000 >> .cache/fb_keyword_search.log 2>&1 &

# ② X 关键词直搜采号（xquik/x-tweet-scraper 单源，常驻循环，已降频 10 分钟一轮）
nohup python3 scraper/x_keyword_search.py --keywords-file .cache/x_keywords_all.txt \
  --backfill-days 2 --max-items 2000 --per-round 5 --windows-per-word 20 \
  --daily-results 80000 --interval 600 --delay 3 >> .cache/x_keyword_search.log 2>&1 &

# ③ WhatsApp 注册态查询（Apify，10 分钟一拍的常驻循环）
nohup bash -c 'while true; do python3 scraper/wa_check_apify.py \
  --bucket declared_wa,cn_uncertain --min-batch 100; sleep 600; done' \
  >> .cache/wa_check_apify.log 2>&1 &
```

要点：
- 词库：FB 用 `.cache/fb_keywords_extra.txt`（内置词之外的扩展词），X 用 `.cache/x_keywords_all.txt`；加词直接追加新行，**禁止 `sort -u` 重写词库**。
- 状态/预算记 `.cache/fb_keyword_search_state.json` 与 `.cache/x_keyword_search_state.json`；日志在 `.cache/*.log`，排查先看日志尾部。
- Apify 402/403 欠费时脚本会记 `providers.quota_exhausted_at` 并自动轮换账号，30 天账期内跳过耗尽账号；充值到账后需清掉该标记（`UPDATE providers SET quota_exhausted_at=NULL WHERE kind='apify'`）再重启脚本。
- 群线脚本（`fb_group_discover_bd.py` / `fb_group_bd.py`）**已封存，一律不启动**（单号成本是直搜的 10~40 倍，2026-08-19 用户拍板）。

**启动 platform（管理系统）：**

```bash
bash platform/start.sh   # 一键启动后端（FastAPI，端口 8765）+ 前端（Vite dev，端口 3000）
bash platform/stop.sh    # 停止
```

**巡检**：每小时跑一次，先同步费用（`curl -s -X POST http://127.0.0.1:8765/api/costs/sync`，Apify 真实账单 + Bright Data + 渠道估算入 `cost_records` 表）→ 查 3 个脚本进程是否存活 → 查近 1h/3h 逐小时新增（`scraper/inspect_stats.py`，只读）→ 查 fb_contacts 全量汇总（采集/已注册/待审核，按 post_url 域名分 FB/X，只读查询 `file:.cache/1688.db?mode=ro`）→ 对照 state JSON 日用量排除预算刹车 → 确认关键词枯竭才换词（`grep -qxF` 去重追加）并重启对应脚本生效。

换词触发条件：先对照表 4 排除预算刹车/额度耗尽等外部原因；确认是词库问题后——**某渠道连续 2 小时新增 < 30 条，即可尝试更换关键词**（不用等彻底枯竭）。词级判据用 `python3 scraper/kw_stats.py --aging`（只读）：脚本把每词每次查询的表现记在 state JSON 的 `kw_stats`（q/posts/new/last_new_at/zero_streak=连续新号+0 次数，2026-08-22 起累计，此前历史不回溯），报表按此推导状态——枯竭（>7 天无新号且查询 ≥5 次）、老化（3~7 天无新号或连续+0 ≥10）、活跃、回扫中、观察（查询 <5 次）、未启用；**枯竭/老化词优先列入换词候选**，全量看 `kw_stats.py`、产量榜看 `--top N`。

**X 换词标准流程（2026-08-21 起）**：X 词枯竭的判据是「帖还能搜到但新号连续 +0」（历史存量已采完，增量供给趋零，跨源去重也会吃掉一部分）。换词时不要盲目加词，先用 **WebBridge 在用户真实浏览器（带 X 登录态）逐词验证**：
1. 策展候选词（新品类 / 新语种 / 新形态，先对照 `.cache/x_keywords_all.txt` 排除已有词）。**品类词首选从 B2B 平台类目页批量采**：made-in-china 类目目录 `https://www.made-in-china.com/products-directory/`（英文、结构干净，钻进一级类目页抓二级类目名即可，2026-08-21 实测好用）；world.1688.com 会重定向死循环、alibaba.com 首页重 JS 加载慢且中文本地化，均不推荐；
2. 用 WebBridge 打开 `https://x.com/search?q=<url编码词>&f=live`（Latest 排序），`evaluate` 抽取 `article` 数、`article time` 最新时间戳、帖正文里的手机号正则命中；
3. 收录标准：有结果且帖内含手机号/联系方式形态；只搜出无关帖或零结果的词弃用；
4. 验证通过的词 `grep -qxF` 去重后追加到 `.cache/x_keywords_all.txt`（**禁止 `sort -u` 重写**），重启 X 脚本生效。
注意：新词在 state 里无 `kw_backfill` 记录，重启时用较大的 `--backfill-days`（如 180）可让新词回扫历史存量，老词已标 done 不受影响；但回扫吃行数预算，加词规模对照剩余预算（state 里 200000 行总上限）。

**X/FB 词库共享（2026-08-21 起）**：词库都存文件不在数据库——FB 为脚本内置 `KEYWORDS`（234 词）+ `.cache/fb_keywords_extra.txt` 追加，X 为内置 `X_KEYWORDS` + `.cache/x_keywords_all.txt` 覆盖。X 验证通过的新词应同步跑一遍 FB 验证（WebBridge 开 `https://www.facebook.com/search/posts/?q=<url编码词>`，统计正文中国手机号命中数 C，C>0 才收录，同 08-18 口径），通过的 `grep -qxF` 追加到 `.cache/fb_keywords_extra.txt` 并重启 FB 脚本；反向同理。两平台卖家人群重叠但帖源不同，跨平台复用验证过的词是低成本扩量手段。

**巡检输出一律用表格，不用文字长段落**，固定四张表 + 一行结论：

表 1 · 进程状态：

| 脚本 | PID | 状态 | 备注 |
|---|---|---|---|
| FB 直搜 | 18539 | ✅ 运行中 | 当前轮关键词：xxx |
| X 直搜 | — | ❌ 已退出 | 日志尾部原因一行 |
| WA 查号 | 17269 | ✅ 运行中 | 上轮已查 N 条 |

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
- `cost_records` 费用表（2026-08-21 起）：由 `POST /api/costs/sync`（`app/costs.py`）幂等 upsert；UNIQUE 键含 `service`，**估算行的 service 存 `''` 而非 NULL**（SQLite UNIQUE 中 NULL 互不相等，upsert 会失效）。估算单价常量与 scraper 写死值保持一致（来源行号见 `costs.py` 顶部注释），改价两边同步。
- `wa_registered` 语义：`1`=已注册、`0`=未注册、`NULL`=未查。**注意 NULL 不等价
  `wa_checked_at IS NULL`**：存在查了但结果为 NULL 的失败行（2026-08-20 实测约百条），
  「待查」口径一律用 `wa_registered IS NULL`。
- fb_contacts 号码入库口径：**只收中国手机号**。过滤统一走
  `fb_group_bd.is_cn_number(number, source)` 且 `bucket != 'overseas'`
  （intl/wa_me/wa_label_intl 形态剥壳后 11 位 1 开头的实为 +1 北美号，拒收；
  2026-08-20 已清库：overseas 406 条假中国号删除、0086 前缀 14 条救回 cn_uncertain）。
- 改后端代码后 uvicorn **不会自动 reload**，需重启才生效（重启见 `platform/start.sh`/`stop.sh`；注意 pidfile 记录的是父进程，杀端口占用进程时按实际监听 pid）。

## 5. 通用代码约定

- 类名合并一律用 `cn()`（`@/lib/utils`）；注释用中文，文件顶部一行注释说明模块职责。
- 前端提交前跑 `npx tsc -b`（`platform/web` 下）。
- 不动 `scraper/`、`util/` 旧脚本；新能力进 `platform/`（平台侧）。
