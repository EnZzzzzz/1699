# Bright Data（第三方 FB 采集服务）调研

> 调研时间：2026-08-07（所有价格为该日期官网标价，可能随促销变动）。关联：[../facebook-groups.md](../facebook-groups.md) §11 渠道全景、[README.md](README.md)。
> 结论速览：**对本项目是"可用但不必需"的备选路线**。Bright Data 的 Facebook Scraper API 有现成的「公开群帖」端点（按群 URL 发现帖子，无需登录态），免费额度 5K 条/月，之后 $1.5/千条 —— 本项目「1 万群帖/月」场景约 **$7.5/月**。但官方示例输出字段偏薄（正文/时间/permalink/作者 URL，作者名还做了打码），互动数等字段营销页宣称有、示例里没出现；且只覆盖公开群，与本项目自建匿名路线范围一致。自建路线已跑通的情况下，Bright Data 的价值主要是**兜底/对照数据源**和**免维护**，而不是成本优势。

## 1. 产品线梳理（FB 采集相关）

| 产品 | 是什么 | 计费 | 调研日价格 |
|---|---|---|---|
| Web Scraper API（Facebook Scraper） | 预置 FB 采集器，发 URL 收结构化 JSON，免维护代理/验证码/解析 | 按成功返回的记录数 | 免费 5K 条/月；PAYG **$1.5/千条**；Scale $499/月含 384K 条（超出 $1.3/千条）；Enterprise 定制。来源：[产品页](https://brightdata.com/products/web-scraper/facebook) |
| Datasets（现成数据集） | 预采集的 FB 数据（posts/reels/events/comments/marketplace 共 10 个数据集、14 亿+ 条），按条购买 | 按记录，最低起订 | **$0.0025/条起，最低单 $250（100K 条一次性）**；订阅刷新折扣：半年 -25%、季度 -50%、月度 -80%。来源：[FB 数据集页](https://brightdata.com/products/datasets/facebook) |
| 住宅代理（基础设施） | 400M+ 住宅 IP，195 国 | 按流量 | PAYG $8/GB（促销码 RESIGB50 后 $4/GB）；$499/月→141GB（$7/GB）；$999→332GB（$6/GB）；$1999→798GB（$5/GB）。来源：[住宅代理页](https://brightdata.com/products/residential-proxies) |
| Web Unlocker（通用解锁层） | 单请求解锁任意站点，返 HTML/JSON | 按成功请求 | 免费 5K 请求/月；PAYG **$1.5/千次**；$499/月含 383K 次（超出 $1.3/千次）。来源：[Unlocker 定价页](https://brightdata.com/pricing/web-unlocker) |
| Browser API（原 Scraping Browser） | 托管浏览器跑 Puppeteer/Playwright/Selenium 脚本，内置解锁 | 按流量 | PAYG **$8/GB**；$499/月→71GB（$7/GB）；$999→166GB（$6/GB）；$1999→399GB（$5/GB）。来源：[Browser API 页](https://brightdata.com/products/scraping-browser) |

通用条款：免费层 5K 条/月**无需信用卡**，每月 1 日重置、不结转，可用于 Scrapers / Unlocker / SERP API；所有 Scraper/Unlocker 产品「只为成功结果付费」；新用户首充等额匹配最高 $500（促销，调研日在挂）。

## 2. Facebook Scraper API 能力细节

### 2.1 端点清单

官方文档 Quick Reference 列出 **10 个端点**（[send-first-request](https://docs.brightdata.com/datasets/scrapers/facebook/send-first-request)；产品页营销口径写"14 scrapers"，介绍页写"9 endpoints"，以 Quick Reference 的 10 个为准）：

| 端点 | dataset_id | 输入 URL 形态 |
|---|---|---|
| Pages Posts by Profile URL | `gd_lkaxegm826bjpoo9m5` | facebook.com/{page_name} |
| **Posts by group URL（群帖）** | `gd_lz11l67o2cb3r0lkj3` | facebook.com/groups/{group_id} |
| Posts by post URL | `gd_lyclm1571iy3mv57zw` | facebook.com/{user}/posts/{post_id} |
| Comments | `gd_lkay758p1eanlolqw8` | facebook.com/{user}/posts/{post_id} |
| Marketplace | `gd_lvt9iwuh6fbcwmx1a` | facebook.com/marketplace/item/{item_id} |
| Profiles | `gd_mf0urb782734ik94dz` | facebook.com/{username} |
| Pages and Profiles | `gd_mf124a0511bauquyow` | facebook.com/{page_or_profile} |
| Events | `gd_m14sd0to1jz48ppm51` | facebook.com/events/{event_id} |
| Reels by profile URL | `gd_lyclm3ey2q6rww027t` | facebook.com/{username} |
| Company Reviews | `gd_m0dtqpiu1mbcyc2g86` | facebook.com/{company_page} |

**没有 ads（广告）端点**——广告数据走 Ad Library（见 [AD_LIBRARY.md](AD_LIBRARY.md)），Bright Data 未提供 FB 广告采集器。

### 2.2 调用方式

- 同步 `POST /datasets/v3/scrape`：实时查询，单次最多 20 个 URL（profiles 约 10-30 秒返回）。
- 异步 `POST /datasets/v3/trigger`：批量，单次最多 **5,000 个 URL**，snapshot 轮询/ webhook / S3 / Snowflake / Azure / GCS 交付；发现模式（discover，如"某页/某群的全部帖子"）只走异步。
- 群帖端点输入参数：`url`（群 URL）、`start_date`、`end_date`、`user_to_not_include`；主页帖端点另有 `num_of_posts`（1-100）、`posts_to_not_include`。
- 输出 JSON / NDJSON / CSV。

### 2.3 群帖返回字段（关键考察点）

官方页面宣称群帖可拿：post ID、content、date posted、hashtags、comments 数、shares、likes 等（[群采集器页](https://brightdata.com/products/web-scraper/facebook/groups)）。但**官网示例实际输出只有 7 个字段**：

```json
{
  "url": "https://www.facebook.com/groups/1305282597018167/posts/1796051251274630/",  // 即 permalink
  "post_id": "1796051251274630",
  "user_url": "https://www.facebook.com/rowan.mohamed.35110",
  "user_username_raw": "Rawan M*****d",   // 注意：作者名被打码（合规脱敏）
  "content": "🔥 GGO is Hiring! ...",
  "date_posted": "2025-10-14T07:42:28.000Z",
  "timestamp": "2025-10-17"
}
```

诚实标注：**互动数（likes/comments/shares）、hashtags 在示例输出中未出现**，FAQ 宣称 posts 类记录含 likes、comments、shares、reaction types、attachments、page details，但无法在示例中验证，需注册后用免费额度实测。另外部分记录 `content: null`（纯图片/分享帖），这一点与自建路线一致。作者名打码（`user_username_raw`）是其隐私合规设计——对"按人名溯源"的用途是减分项，但 `user_url` 完整可用。

### 2.4 群覆盖与登录态

- **只支持公开群**，按群 URL 发现帖子；**不需要（也不允许）登录态**——Bright Data 的合规立场就是"只抓 logged-off 公开数据"（见 §4）。私有群/需入群可见的内容一概覆盖不了，与自建匿名路线范围相同。
- **关键词搜索**：没有"全站 FB 内容关键词搜索"端点。发现模式只支持「页/群 URL → 其下帖子」；Marketplace 支持按关键词发现。要按关键词找 FB 内容只能绕道（如 SERP API 搜 Google 索引），不是原生能力。

## 3. 定价模型与本项目成本估算

计费单元：1 条记录 = 1 个实体（1 条帖子、1 个主页、1 条评论…），**失败不计费**；PAYG 预充值无月承诺，Scale 档为月度订阅（可取消）。

**场景：1 万条 FB 群帖/月（Scraper API 群帖端点）**

| 方案 | 计算 | 月成本 |
|---|---|---|
| 免费层 + PAYG | 5K 免费 + 5K × $1.5/千条 | **$7.5/月** |
| 纯 PAYG（忽略免费层） | 10K × $1.5/千条 | $15/月 |
| Scale 订阅 | 远超需求，384K 条起步 | $499/月（不划算） |
| Datasets 现成数据 | 最低单 100K 条 $250，且是预采集通用数据、不保证覆盖目标群 | 不适合 |
| 自建路线（现状） | fetcher + CloakBrowser，边际成本≈代理/机器费 | ≈$0-低 |

附带：若用 **Web Unlocker + 自写解析**抓 FB，$1.5/千次成功请求同样量级的钱，但要把 CloakBrowser 已解决的解析维护问题重新背回来，无意义；**Browser API $8/GB** 对本项目更是纯增成本（自建 CloakBrowser 已覆盖）。

## 4. 合规面

- 主打卖点：**只采集公开数据 + KYC（客户实名审核）+ AUP（可接受使用政策）**，宣称 GDPR/CCPA 合规，ISO 27001、SOC 2/3、CSA STAR 认证，设有专职 Compliance & Ethics 团队；住宅代理 IP 全部用户明示 opt-in，Bright Shield 防 PII 采集。输出中作者名打码即是这套合规的产物。
- **Meta Platforms, Inc. v. Bright Data Ltd.**（N.D. Cal. 3:23-cv-00077）：2024-01-23，Edward M. Chen 法官**批准 Bright Data 的简易判决动议、驳回 Meta 的交叉动议**——Meta 未能举证 Bright Data 在登录态下抓取了非公开数据，法院认定其抓取 logged-off 公开数据不构成违反 Meta 条款。来源：[判决 PDF](https://www.courthousenews.com/wp-content/uploads/2024/01/meta-platforms-v-bright-data-ruling-motion-for-summary-judgment.pdf)、[Bright Data 声明](https://brightdata.com/blog/web-data/court-rules-in-favor-of-bright-data-in-meta-v-bright-data-case)、[Farella Braun 分析](https://www.fbm.com/publications/major-decision-affects-law-of-scraping-and-online-data-collection-meta-platforms-v-bright-data/)。
- 对本项目的含义：该判例支持「匿名抓公开群帖」这条路线本身的合法性立场（与 hiQ v. LinkedIn 一脉相承），**但不背书登录态抓取**；Bright Data 的合规边界（公开群、无登录态）与自建路线完全一致，换服务商不会扩大可采范围。

## 5. 优劣势与自建路线对比

| 维度 | Bright Data Scraper API | 本项目自建（fetcher + CloakBrowser） |
|---|---|---|
| 群帖覆盖 | 公开群，按群 URL 发现 | 公开群，permalink 级抓取 |
| 字段 | permalink/正文/时间/作者 URL 确定有；互动数宣称有、示例未见；作者名打码 | 字段自控，互动数、评论可按需扩展 |
| 成本（1 万帖/月） | ~$7.5/月（含免费层） | ≈$0 边际成本 |
| 维护 | 零维护（代理/验证码/解析全包，FB 改版由对方跟进） | 自维护，FB 改版需自己修 |
| 延迟/时效 | 实时按需抓，异步批量 5K URL/次 | 自控 |
| 登录态内容 | 不支持 | 不支持（同边界） |
| 合规 | 有 Meta 案胜诉背书、KYC 完备 | 同靠公开数据原则，无第三方背书 |
| 锁定风险 | 按条计费随规模线性涨；数据经第三方 | 无 |

**一句话判断**：自建路线已跑通时不必迁，但值得用免费额度（5K 条/月免信用卡）做兜底与字段对照——重点实测群帖端点是否真的返回 likes/comments/shares，若返回，它可作为低成本冷启动/灾备通道；年量百万条以上时 $1.3-1.5/千条 的线性成本才会成为决策因素。

## 6. 来源汇总

- 产品/定价：<https://brightdata.com/products/web-scraper/facebook>、<https://brightdata.com/products/web-scraper/facebook/groups>、<https://brightdata.com/products/datasets/facebook>、<https://brightdata.com/pricing/web-unlocker>、<https://brightdata.com/products/scraping-browser>、<https://brightdata.com/products/residential-proxies>
- 文档：<https://docs.brightdata.com/datasets/scrapers/facebook/introduction>、<https://docs.brightdata.com/datasets/scrapers/facebook/send-first-request>
- 诉讼：<https://www.courthousenews.com/wp-content/uploads/2024/01/meta-platforms-v-bright-data-ruling-motion-for-summary-judgment.pdf>、<https://www.govinfo.gov/app/details/USCOURTS-cand-3_23-cv-00077/USCOURTS-cand-3_23-cv-00077-7>
- 未实测声明：互动数字段、群帖端点实际成功率与字段完整性未注册账号实测；住宅代理促销价（50% off）与首充匹配为调研日在挂促销，非常态价。
