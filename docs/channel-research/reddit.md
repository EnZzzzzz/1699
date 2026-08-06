# Reddit 渠道侦察报告 —— 中国外贸从业者公开留号（WhatsApp/手机号）采集可行性

> 侦察日期：2026-08-06 · 方式：Kimi WebBridge（用户真实浏览器）+ 第三方 Reddit 档案 API 实测 · 仅侦察，未改任何项目代码

## TL;DR

**不建议把 Reddit 作为重点采集渠道。** 三个硬伤叠加：

1. **匿名访问已实质封死**：用户当前网络出口（代理，日本节点）下，www.reddit.com 全站（含板块页、搜索页）直接返回 "You've been blocked by network security" 封锁页；old.reddit.com 整站 "Blocked"；公开 `.json` 接口全部 403（命令行与浏览器内带 Cookie 请求均如此）。
2. **号码密度极低**：重点板块帖子中真实 `+86` 留号密度约为 **每月 1~2 个有效新号**（实测，详见下表）；大量 "whatsapp" 提及帖是卖家讨论话术，不留号。
3. **可用的第三方镜像（Arctic Shift）评论全文搜索基本不可用**（持续超时），而自荐留号恰恰更常出现在评论里，无法可靠测量与采集。

可作为**低优先级长尾源**保留（每日增量轮询，预期每周 1~3 个新号），不值得单独投入反爬对抗。

---

## 1. 直接访问与反爬实测（用户真实浏览器 + 本机 curl）

| 路径 | 结果 |
|---|---|
| `www.reddit.com/search/?q=...`（浏览器） | ❌ 封锁页："You've been blocked by network security. To continue, log in to your Reddit account or use your developer token" |
| `www.reddit.com/r/dropshipping/`（板块首页，浏览器） | ❌ 同上，全站封锁，非搜索特定 |
| `old.reddit.com/search?q=...`（浏览器） | ❌ 整站 "Blocked" 页（HTML 与 .json 均 403） |
| `www.reddit.com/search.json?...`（curl，浏览器 UA） | ❌ 403（返回 190KB 封锁 HTML） |
| 浏览器页面内 `fetch("/search.json")`（带用户 Cookie） | ❌ 403 —— 公开 .json 接口对匿名流量已实质关闭 |
| Bing / DuckDuckGo 搜索 `site:reddit.com ...`（浏览器） | ❌ 双双弹人机验证（Bing 拼图、DDG 选图），出口 IP 被普遍标记 |

**结论**：

- 当前代理出口 IP 被 Reddit 网络安全系统整体标记，匿名 HTML/JSON 抓取均不可行；连主流搜索引擎都对该 IP 出验证码。
- 封锁页明确给出唯一通路：**登录 Reddit 账号**或开发者 token。即官方 OAuth API（需注册 app，认证后约 100 req/min 配额）是唯一合规可用的直接接口；匿名 `.json` 时代已结束。
- 若要做直接抓取，需要「干净住宅代理 + 登录态 + OAuth」三件套，对抗成本高，与本任务低密度的收益不匹配。
- 未测试登录态下的可用性（侦察原则：不动用户账号）。

## 2. 第三方档案 API：Arctic Shift（本次唯一可用数据源）

`https://arctic-shift.photon-reddit.com/api` —— 匿名、无需 Key、返回 JSON、数据新鲜（实测含 2026-08-06 当天帖子）。

- ✅ `GET /api/posts/search?subreddit=X&query=Y&limit=100&sort=desc` 可用，支持板块内全文搜索。
- ❌ `GET /api/comments/search?subreddit=X&body=Y` 评论全文搜索**持续 422 "Timeout. Maybe slow down a bit"**（5 次重试、8s 间隔均失败）——评论维度不可采集。
- ⚠️ 限流敏感：约 10~15 次请求后进入硬性惩罚（所有查询连续 422），需 4~8s 间隔且仍会被封一阵。适合每日低频增量，不适合回填式批量。
- 同类备选 PullPush（api.pullpush.io）被 Cloudflare 人机验证拦截，不可用。

## 3. 板块密度实测（Arctic Shift，query=whatsapp，每板块取最新 100 帖）

| 板块 | whatsapp 帖速率 | 近 90 天帖数 | 真实 +86 号码帖 | 备注 |
|---|---|---|---|---|
| r/dropshipping | ~4.5 帖/周 | 55 | **2 / 100**（近 5 个月） | 留号者确为中国供应商自荐 |
| r/ecommerce | ~2.6 帖/周 | 41 | 0（2 例为美国 +1 646 误判） | 多为卖家讨论 WhatsApp 营销 |
| r/smallbusiness | ~21.7 帖/周 | 100（33 天打满） | **0 / 100** | 量大但与中国货源无关 |
| r/Entrepreneur | ~3.5 帖/周 | 13 | 0 / 100 | 同上 |
| r/dropship | ~0.2 帖/周（已衰落） | 1 | ~7 / 100（跨度 8 年） | 历史有号，现无增量 |
| r/FulfillmentByAmazon | ~0.1 帖/周 | 1 | 1 / 50（跨度 11 年） | 货代留号（forestshipping） |
| r/importing | 可忽略 | — | — | 半年仅 2 帖 |

**脱敏样例**（验证留号者角色）：

- r/dropshipping，2026-05-26："US POD factory — My whatsapp: **+86 199\*\*\*\*88**"（中国工厂自荐）
- r/dropshipping，2026-05-22："Company: GermanDrop Co., Ltd. — WhatsApp: **+86 158\*\*\*\*94** (you can call or video me anytime)"（中国公司贴德国牌自荐）
- r/dropship，2023-12-28："Dm me if you want product from china. WhatsApp **+86195\*\*\*\*46**"（帖已被删 [removed]）
- r/FulfillmentByAmazon，2023-08-18："contact information whatsapp **+86 198\*\*\*\*36** (cs.os04@forestshipping.com)"（货代）

**质量判断**：留 +86 号的确实几乎全是中国 sourcing agent / 供应商 / 货代在自荐，号码为真实手机号格式，角色与目标画像高度吻合——问题是**量太少**：6 个重点板块帖子维度合计约 **每月 1~2 个有效新 +86 号**。评论维度（自荐更高发处）因接口超时无法测量，是本次侦察的主要盲区；即使按帖子密度 3~5 倍乐观估计评论，量级也就每周 1~3 个。

**时效性注意**：自荐帖被版主删除比例高（样例中即见 [removed]），采集必须每日增量、抓到即存，周级回填会丢号。

## 4. 采集可行性结论

| 方案 | 可行性 | 说明 |
|---|---|---|
| 匿名 HTML/JSON 直连抓取 | ❌ 不可行 | 全站封锁 + .json 403；需住宅代理 + 登录态 + OAuth，成本远超收益 |
| 官方 OAuth API（注册 app + 账号） | ⚠️ 技术上可行 | ~100 req/min，搜索接口可用；但密度不会因接口变好而变高，且账号有封禁风险 |
| Arctic Shift 每日增量（帖子维度） | ✅ 低成本可行 | 6 板块 × query=whatsapp，4~8s 间隔，每天 ~10 次请求即可覆盖；**评论维度不可用** |
| 搜索引擎 site: 搜索 | ❌ 当前 IP 不可行 | Bing/DDG 均出验证码 |

**建议速率**：每日 1 次增量轮询，每次 ≤10 请求、间隔 ≥6s，预计每周新增 1~3 个有效 +86 号码。

## 5. fetcher 插件建议（若决定做）

- 定位为**低优先级长尾源**：`fetcher/sites/reddit.py`，不走 Reddit 官方，走 Arctic Shift。
- 原子设计：单原子 = 「查询一个板块的 whatsapp 新帖（after=上次水位线）并抽取 +86 手机号」，只报告 Outcome；限流退避（422→sleep 30s+）交给策略层。
- 板块清单：dropshipping、ecommerce、smallbusiness、Entrepreneur、dropship、FulfillmentByAmazon（可后续扩展 importing/FBA）。
- 抽号正则须排除 `+1` 开头的美国号码误判（本次实测出现 +1 646/+1 360 被 `\b1[3-9]\d{9}\b` 误中）；建议以 `\+86[\s\-.]?1[3-9]\d{9}` 为主、裸 11 位需上下文含 china/whatsapp/agent 才采信。
- 入库字段建议带 subreddit/permalink/created_utc，便于溯源与去重（sha 号码即可）。
- **不要把本渠道列入高预期 KPI**；优先级应低于 1688/义乌购等站内渠道。

## 附：本次侦察副作用说明

- 在用户浏览器新建了标签组「渠道侦察·Reddit」用于探查，未关闭、未触碰用户既有标签页。
- 所有号码样例已脱敏（中间打码）。
