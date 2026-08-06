# Apify 第三方 Facebook 采集服务调研（2026-08-07）

> 渠道调研子报告，主路线见 [../facebook-groups.md](../facebook-groups.md)。
> 结论先行：**Apify 官方 Facebook Groups Scraper 能稳定拿到公开群的帖子 permalink + 正文 + 互动数，约 $5 / 1000 帖，1 万帖/月总成本约 $50-80，可作为自建 CloakBrowser 路线的兜底/对照方案；但只支持公开群，私密群仍需自建登录态路线。**
> 所有价格以 2026-08-07 当日 apify.com 官方页面为准。

## 1. 平台模式

Apify 是一个「Actor 市场 + 云运行平台」：

- **Actor**：第三方或官方维护的云端爬虫程序（本质是打包的容器任务）。用户在控制台填输入 JSON（或表单）→ 点运行 → 结果落到 **dataset**，可导出 JSON/JSONL/CSV/Excel/HTML/XML。
- **API/SDK**：REST API（api.apify.com/v2）+ 官方 `apify-client`（PyPI / NPM）。可编程地传输入、启动 run、轮询状态、拉 dataset。所有 Store actor 的页面都有 "API" tab 给出调用示例。
- **Webhook**：run 完成/失败等事件可触发 webhook 回调，适合接到本平台 runner 里做异步收尾。
- **调度**：平台内置 Schedule（cron 式定时跑 actor）。
- **MCP**：每个 actor 可挂到 Apify MCP server（mcp.apify.com），供 AI agent 直接调用。
- **集成**：Zapier、Make、Google Sheets、Slack、Airbyte 等现成连接器。
- **代理**：FB 类 actor 在平台内自动走住宅代理（Apify Proxy），用户无需自配；住宅代理包含在付费档位的预付额度内（超量 $8/GB，Free/Starter 价）。

来源：[Apify Pricing](https://apify.com/pricing)、[Facebook Posts Scraper](https://apify.com/apify/facebook-posts-scraper)（FAQ 中 API/SDK/Webhook/MCP 描述）

### 计费双模型（重要）

每个 actor 二选一，页面会标注：

- **Pay per event（按事件/结果计费）**：开发者定价，如「$X / 1000 条结果」或「启动费 + 每条 $Y」。大多数此类 actor 的事件价已含平台资源消耗（CU/代理），少数另收，需看 actor 页说明。
- **Pay per usage（按用量计费）**：开发者不加价，只付平台资源费（CU、代理、存储、传输）。

两种模型都先从订阅档位的**预付额度（prepaid usage）**里扣，超额计入下月账单（付费档）或直接停用到下周期（Free 档）。**预付额度月底清零，不滚存。**

来源：[Apify Pricing](https://apify.com/pricing)

## 2. Facebook 相关 actor 能力矩阵（官方 apify/ 出品 + 主流第三方）

| Actor | 输入 | 能拿到的字段 | 需登录？ | 群支持 | 计费（官方页面标注） |
|---|---|---|---|---|---|
| [Facebook Groups Scraper](https://apify.com/apify/facebook-groups-scraper)（官方） | 公开群 URL 列表（可多个）；可选排序（新帖/最新活动/最相关）、时间窗、关键词过滤 | 帖子正文、**permalink URL**、作者名+ID、时间戳、点赞/反应分解（like/love/haha…）/分享数/评论数、**top comments（含评论者 profile URL/ID/昵称、评论正文）**、媒体 URL/缩略图/OCR 文本、群标题 | 否（页面明示：**只支持公开群**，私密群需登录违反 FB ToS，不支持） | 仅公开群 | 约 **$5 / 1000 帖**；Free 档可白嫖约 1000 帖；Starter $29 约 5,800 帖/月 |
| [Facebook Posts Scraper](https://apify.com/apify/facebook-posts-scraper)（官方） | Page / 个人 profile URL 列表；时间窗过滤、条数上限、视频转录开关 | 帖子正文、permalink、作者、时间戳、likes/comments/shares、反应分解、媒体/视频转录、外链、Page 广告库 ID | 否 | 不抓群 | 约 **$5-8 / 1000 帖**；500 帖免费额度 |
| [Facebook Comments Scraper](https://apify.com/apify/facebook-comments-scraper)（官方） | 帖子/视频/Reel 的 URL（**可喂群帖 permalink**） | 评论正文、评论 URL/ID、评论者昵称+profile ID/URL+头像、点赞数、回复数、嵌套层级（最深 3 层）、时间戳；支持按时间过滤（`onlyCommentsNewerThan`） | 否（只拿公开可见评论，私密账号评论拿不到） | 通过群帖 URL 间接支持 | **from $1.40 / 1000 评论**（Store 头部标价）；2000 评论免费 |
| [Facebook Pages Scraper](https://apify.com/apify/facebook-pages-scraper)（官方） | Page / profile URL 列表 | 主页名称/分类/简介、**电话、email、网站、Messenger 链接**、地址、粉丝数/点赞数、评分、创建日期、广告库 ID/在投广告状态 | 否（页面提示：部分 Page 有区域/登录限制，字段会缺） | — | **$10 / 1000 个 Page**；500 个免费 |
| [Facebook Search Scraper](https://apify.com/apify/facebook-search-scraper)（官方） | **关键词 + 地区**（国家/城市/省），可多组 | 命中的 Page：名称、URL、分类、**电话、email、网站**、地址、粉丝/点赞、评分、创建日期、广告状态 | 否 | 不搜群（搜的是 Page） | Pay per event：**$0.03 启动费 + $0.012 / 个 Page**（$5 免费额度 ≈ 416 个 Page） |
| [Facebook Ad Library Scraper](https://apify.com/curious_coder/facebook-ads-library-scraper)（第三方 curious_coder，30K 用户，评分 4.8） | 广告库搜索结果 URL，或 Page URL 列表（抓该 Page 全部在投广告） | Ad ID、Archive ID、广告素材快照、文案、投放起止、曝光/花费（欧盟透明度数据）、发布平台、Page ID/名称等 30+ 字段 | 否 | — | Store 头部标 **$0.75 / 1000 条广告**；页面正文又写「历史均值约 $0.2 / 1000 条（按用量）」——两个数字口径不一，以实测为准 |

### 值得注意的第三方替代（未逐一深查，仅列 Store 检索结果）

- [curious_coder/facebook-post-scraper](https://apify.com/curious_coder/facebook-post-scraper)：群/Page/搜索三合一抓帖，$25/月 + 用量，2.7K 用户，评分 3.1（评分偏低）。
- [easyapi/facebook-groups-search-scraper](https://apify.com/easyapi/facebook-groups-search-scraper)：**按关键词发现群**（群名/URL/成员数/发帖频率），from $2.99/1000 结果，评分 2.0——可做「群发现层」参考，但评分差需谨慎。
- [simpleapi/facebook-group-post-scraper](https://apify.com/simpleapi/facebook-groups-scraper)：公开群抓帖，$19.99/月 + 用量，评分 1.0。
- Store 里 FB 类 actor 有 20+ 个（Events、Reviews、Reels、Marketplace、Followers 等），官方全家桶列表见各 actor 页底部。

**关键结论：所有官方 actor 都不需要 cookies/登录，也因此都不支持私密群。** 官方 Groups Scraper FAQ 原文：私密群抓取需要登录凭证，这违反 Facebook ToS，故不支持。

## 3. 平台订阅档位与定价（2026-08-07 官方价）

来源：[Apify Pricing](https://apify.com/pricing)

| 档位 | 月费 | 预付额度 | CU 单价（1GB RAM·小时） | 住宅代理 | 备注 |
|---|---|---|---|---|---|
| Free | $0 | **$5/月** | $0.2 | $8/GB | 免信用卡；额度耗尽即停用至下周期；最大并发 25 |
| Starter | **$29/月** | $29 | $0.2 | $8/GB | FB actor 官方建议的入门档 |
| Scale | $199/月 | $199 | $0.16 | $7.5/GB | CU 与代理单价下降 |
| Business | $999/月 | $999 | $0.13 | $7/GB | 账号经理支持 |
| Enterprise | 定制 | 定制 | 定制 | 定制 | SSO 等 |

- 超额用量自动计入下月账单（付费档不用预先升级）。
- 学生 7 折（Starter/Scale）、初创公司 Scale 7 折、非营利机构可谈折扣。
- 存储/传输另有细价目（dataset 读 $0.0004/千次、写 $0.005/千次等），对本场景是零头。

### 成本估算：本项目 1 万帖/月（公开群帖 permalink + 正文）

按官方 Groups Scraper 标价 **$5 / 1000 帖**：

- 纯 actor 费用：10,000 × $0.005 = **$50/月**。
- 落地方案：Starter $29（预付 $29 抵扣）+ 超额约 $21 计入下月账单 ≈ **$50/月总成本**（官方口径 Starter 档约可跑 5,800 帖/月，与 $29/$5×1000 吻合；1 万帖即约 $50）。
- 若再加 Comments Scraper 补全评论（假设每帖平均抓 20 条评论 = 20 万条 × $1.40/1000 ≈ $280/月），评论层成本显著高于帖子层，建议只对有联系方式线索的帖二次抓评论。
- **PoC 成本：$0**。Free 档 $5 额度 ≈ 1,000 帖，足够验证字段质量、permalink 可用性与联系方式命中率。

对比参照：官方 Pages Scraper $10/1000 Page；Search Scraper $0.012/Page（做供应商 Page 发现层约 $12/千条）。

## 4. 与本项目自建路线的对比

| 维度 | Apify（第三方服务） | 本项目自建（fetcher + CloakBrowser 匿名抓群帖） |
|---|---|---|
| 公开群帖 permalink + 正文 | ✅ 开箱即用，字段规整（官方示例输出直接含 `url`、`text`、`legacyId`、互动数） | ✅ 已实现，边际成本近零（代理费） |
| 私密群 | ❌ 全平台都不支持（无登录态） | ✅ 可带登录 cookie（CloakBrowser 方案的核心优势） |
| 联系方式提取 | actor 只回原始文本，手机号/WhatsApp 仍需自己跑正则/提取层（与本项目现有提取逻辑复用） | 已有提取管线 |
| 维护成本 | 零维护，FB 改版由 actor 作者跟进 | 自己跟反爬，有封号/滑块风险 |
| 成本 | 1 万帖/月 ≈ $50（含平台订阅） | 代理 + 机器成本，量级相近或更低，但有开发/维护人力 |
| 稳定性/合规 | Apify 明示不碰私密数据，只抓公开内容；账号风险由平台承担 | 匿名浏览公开群合规性类似，但自己扛反爬 |
| 集成方式 | REST API + webhook，可接进 platform runner（类似 subprocess 任务的外部版） | 已深度集成 |

### 适用判断

- **值得用的场景**：① 自建路线被 FB 风控打死时的**应急兜底**；② 作为**字段对照基准**验证自建抓取是否漏字段；③ 用 Search Scraper / Groups Search（第三方）做**发现层**（关键词找群/找 Page），把 URL 喂回自管线的抓取层。
- **不值得的场景**：作为主力抓取层长期跑——私密群覆盖不了，且 $50/万帖相对自建的近零边际成本没有优势。

## 5. 诚实声明（未能核实项）

- 各官方 actor 的 Store 头部「from $X / 1000」精确标价仅取到 Comments（$1.40）；Posts/Groups 采用其页面正文的「约 $5-8 / $5 per 1000」区间表述，非精确价目。
- Ad Library Scraper 页面同时出现 $0.75/1000（Store 头部）与 $0.2/1000（正文历史均值）两个数字，差异原因（是否含平台用量费）未能从页面确认。
- 「FB 改版后 actor 的跟进速度」「住宅代理是否需要 Starter 以上才够量」未实测，来自官方 FAQ 表述。
- 未注册账号、未实际运行任何 actor；所有字段清单来自官方页面示例输出。

## 来源汇总

- [Apify Pricing](https://apify.com/pricing)（2026-08-07 抓取：档位、CU/代理单价、双计费模型）
- [Facebook Groups Scraper](https://apify.com/apify/facebook-groups-scraper)
- [Facebook Posts Scraper](https://apify.com/apify/facebook-posts-scraper)
- [Facebook Comments Scraper](https://apify.com/apify/facebook-comments-scraper)（价格见其 [Issues 页头部](https://apify.com/apify/facebook-comments-scraper/issues)标价 from $1.40/1000）
- [Facebook Pages Scraper](https://apify.com/apify/facebook-pages-scraper)
- [Facebook Search Scraper](https://apify.com/apify/facebook-search-scraper)
- [Facebook Ad Library Scraper（curious_coder）](https://apify.com/curious_coder/facebook-ads-library-scraper)
- [Facebook post scraper（curious_coder，第三方）](https://apify.com/curious_coder/facebook-post-scraper)
- [Facebook Groups Search Scraper（easyapi，第三方）](https://apify.com/easyapi/facebook-groups-search-scraper)
