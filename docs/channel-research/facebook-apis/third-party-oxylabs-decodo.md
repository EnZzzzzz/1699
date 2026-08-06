# Oxylabs / Decodo（原 Smartproxy）Facebook 采集能力调研（2026-08-07）

> 渠道调研子报告，主路线见 [../facebook-groups.md](../facebook-groups.md)，同目录另有 [third-party-apify.md](third-party-apify.md)、[third-party-brightdata.md](third-party-brightdata.md)。
> 结论先行：**两家都是「通用 Web Scraping API + 代理基础设施」厂商，都没有 Facebook 专用解析器；FB 只能走 universal 目标拿回原始 HTML 自己解析。按官方计费口径，1 万 FB 群帖/月在 Oxylabs 约 $49/月（Micro 档最低消费），Decodo 约 $20-50/月（价格透明度低、区间估计）。相对 Apify 的 $5/1000 帖结构化输出，两家在 FB 场景上既无字段优势也无明显价格优势，仅代理基础设施（住宅代理）对本项目有参考价值。**
> 所有价格以 2026-08-07 当日 oxylabs.io / decodo.com 官方页面为准；官方页面未公开的数字用第三方来源并标注。

## 1. 能力矩阵对比（产品 × FB 数据类型 × 字段 × 计费）

| 维度 | Oxylabs | Decodo（原 Smartproxy，2025-04 更名） |
|---|---|---|
| 社媒专用产品线 | ❌ 无独立 Social Media Scraper API；社媒需求并入 Web Scraper API | ⚠️ 曾有独立 Social Media Scraping API，**2025-04 起已并入统一 Web Scraping API**（官方博客确认四合一） |
| FB 专用端点/解析器 | ❌ 无。Target library 有 Google/Amazon/YouTube 等专用 source，**官方文档与 Playground 下拉中未见 Facebook**；FB 走 `universal` source | ❌ 无。模板库 100+ 个，社媒类模板为 **YouTube / Instagram / Reddit / TikTok，无 Facebook** |
| FB 公开主页（Page） | 可试：`universal` source 抓 URL，返回原始 HTML | 可试：`universal` target 抓 URL，返回原始 HTML（官方 GitHub 有 facebookpage.py 示例） |
| FB 公开帖子 permalink | 同上，原始 HTML；需 JS 渲染（$1.35/1K 档） | 同上，官方 GitHub 有 facebookpost.py 示例（带 headless 参数） |
| FB 公开群帖 | 同 universal 方案，无字段级支持 | 官方 GitHub 有 facebookgroup.py 示例，但**标注 not parseable，只回 HTML** |
| FB 私密群/登录态内容 | ❌ 不碰（无登录态机制） | ❌ 官方 Usage policy 明示：**不支持 post-login/认证后内容、私密数据** |
| 返回格式 | 原始 HTML 为主；可用 **Custom Parser**（XPath/CSS 自定义解析，免费功能）输出结构化 JSON | HTML/JSON/CSV/Markdown/PNG/XHR；FB 无预制 parser，结构化需自己解析 HTML |
| 计费模式 | 按成功结果计费（pay per successful result） | 按成功请求计费，价格 = f(代理池 Standard/Premium × 是否 JS 渲染) |
| FB 单价（推算） | FB 属 "Other" 目标：**$1.15/1K（无 JS）/ $1.35/1K（JS 渲染）**，Micro 档 | Premium 代理池 + JS 渲染的精确费率**官网未公开**；第三方口径约 $1-2/1K（见 §3） |
| 免费试用 | **2,000 结果免费**，免信用卡 | 免费 starter 计划（Free plan，免信用卡）+ 付费档 14 天退款保证 |

来源：[Oxylabs Web Scraper API](https://oxylabs.io/products/scraper-api/web)、[Oxylabs Web Scraper API Playground 文档](https://developers.oxylabs.io/scraping-solutions/web-scraper-api/web-scraper-api-playground)、[Decodo Social Media Scraping](https://decodo.com/scraping/social-media)（页脚注明 "This scraper is now a part of Web Scraping API"）、[Decodo Web Scraping API 官方文档](https://help.decodo.com/docs/web-scraping-api-introduction)、[Decodo Web-Scraping-API GitHub](https://github.com/Decodo/Web-Scraping-API)、[Decodo 统一 API 公告](https://decodo.com/blog/new-web-scraping-api)、[Data4AI Decodo 评测（模板清单）](https://data4ai.com/vendors/web-data-extraction/decodo-review/)

### 关键边界判断

- **FB 公开群帖「理论上能抓、实际上没人给你兜底」**：两家的 universal 目标都能对一个 FB URL 发起带住宅代理+JS 渲染的请求并返回 HTML，Decodo GitHub 甚至有现成的 FB Page/Post/Group 三个代码示例。但这些示例最后提交于 2022 年，当前有效性未实测；且 FB 不在任何一家的「官方维护解析目标」清单里——**FB 改 DOM、上风控时，两家的支持团队没有义务帮你修**，这与 Apify 官方 FB actor（字段级维护）或 Bright Data 的 FB 数据集/专用采集器有本质差别。
- **登录 cookies**：两家都不支持带登录态。Decodo 把「不抓认证后内容」写进了 Usage policy；Oxylabs 无登录态传递机制（且其 Web Scraper API 对部分站点有 KYC 限制清单，"Professional & social networks" 类目里明确列了 LinkedIn，Facebook 未明确列出但清单注明"不限于此"，**FB 是否被限需联系客服+KYC 确认——未核实**）。
- **字段**：没有一家给出 FB 结构化字段（无 permalink/作者/互动数/评论的现成 JSON）。拿到 HTML 后仍需本项目自己的提取管线，与自建路线相比只省了「IP 轮换 + 渲染 + 反爬对抗」这一层。

来源：[Oxylabs 受限目标文档](https://developers.oxylabs.io/help-center/most-popular-questions/restricted-targets-proxy-solutions-and-web-scraper-api)、[Decodo Web Scraping API Usage policy](https://help.decodo.com/docs/web-scraping-api-introduction)

## 2. 定价详情（2026-08-07 官方价）

### Oxylabs Web Scraper API（按成功结果计费）

来源：[Oxylabs Web Scraper API 定价区](https://oxylabs.io/products/scraper-api/web)

| 档位 | 月费 | 含结果量 | "Other" 目标无 JS | "Other" 目标 + JS（FB 实际落此档） | 速率限制 |
|---|---|---|---|---|---|
| Free Trial | $0 | 2,000 结果 | 同 Micro 价 | 同 Micro 价 | 10 req/s |
| Micro | **$49/月** | 98,000 结果 | $1.15/1K | **$1.35/1K** | 50 req/s |
| Starter | $99/月 | 220,000 结果 | $1.10/1K | $1.30/1K | 50 req/s |
| Advanced | $249/月 | 622,500 结果 | $0.95/1K | $1.25/1K | 50 req/s |

- 参照价：Amazon $0.50/1K、Google $1.00/1K（无 JS，Micro 档）；媒体下载 $3/GB。
- 只按成功结果计费；可加 Custom Parser 免费做结构化；Micro 档可 top-up 至 $249。

### Decodo Web Scraping API（按成功请求计费，模块化定价）

Decodo 的定价页为 JS 动态渲染，本次未能抓到完整费率表，以下为可核实的口径：

- **计费结构（官方文档确认）**：单价由两个因子决定——代理池（Standard / Premium，FB 这类强反爬目标需 Premium）× JS 渲染（开/关），FB 落在最贵的「Premium + JS」象限。Core/Advanced 两档订阅，Advanced 才有预制模板、解析器、多格式输出与 Premium 代理池。
- **官方锚点数字**：Core 档大流量低至 **$0.08/1K 请求**（Standard 代理、无 JS 的简单目标，官方博客）；官方博客另有 "Web Scraping API starts from $0.09/1K" 的表述（2026-07）。
- **第三方口径**：入门 Advanced 档约 $20-29/月、含约 23,000 请求，折合约 **$1.25/1K**（Blackdown 2025-12）；scraperdb（2026-08）列档位 Free / Starter $19 / Professional $49 / Business $99 / Enterprise 定制，Business 档 Standard 请求约 $0.14/1K。**Premium+JS 的精确费率各来源均未给出，保守按 $1-2/1K 估。**
- 免费：Free plan（免信用卡，少量 Standard 请求额度）+ 付费档 14 天退款。

来源：[Decodo 统一 API 公告（Core from $0.08/1K）](https://decodo.com/blog/new-web-scraping-api)、[Decodo Web Scraping API 文档（计费因子）](https://help.decodo.com/docs/web-scraping-api-introduction)、[Decodo 博客 2026-07（from $0.09/1K）](https://decodo.com/blog/best-web-scraping-proxies)、[scraperdb Decodo 工具页](https://scraperdb.com/tools/decodo)、[Blackdown Decodo 实测](https://www.blackdown.org/google-search-scraping-with-decodo/)

### 住宅代理参考价（per GB）

| 厂商 | PAYG | 订阅档（官方页） | 免费试用 |
|---|---|---|---|
| Oxylabs | 第三方口径 $8/GB（官网订阅页未列 PAYG 价） | $6/GB（5GB，$30/月）→ $5/GB（20GB，$100）→ $4/GB（125GB，$500）→ **$2.50/GB**（1TB，$2500） | 需联系销售申请 |
| Decodo | **$4/GB** | $3.75/GB（3GB，$11.25/月）→ $3.5（10GB）→ $3.25（25GB）→ $3（50GB）→ **$2.75/GB**（100GB，$275）；更大档位宣传 "from $2/GB" | 3 天 100MB 免费 + 14 天退款 |

来源：[Oxylabs Residential Proxies](https://oxylabs.io/products/residential-proxy-pool)、[Decodo Pricing](https://decodo.com/pricing)

### 成本估算：本项目 1 万 FB 群帖/月

| 方案 | 计算 | 月成本 |
|---|---|---|
| Oxylabs Web Scraper API | 10K × $1.35/1K（JS 渲染）= $13.5 用量，但最低档 Micro **$49/月** 起 | **≈ $49/月**（用量远低于档位置，实际单价被拉高到 ~$4.9/1K） |
| Decodo Web Scraping API | 10K × 估 $1-2/1K（Premium+JS）= $10-20 用量 + 档位最低消费（Starter $19 或 Professional $49） | **≈ $20-50/月**（区间估计，精确费率未公开） |
| 对照：Apify 官方 Groups Scraper | 10K × $5/1K（含结构化字段、免解析） | ≈ $50/月（见 [third-party-apify.md](third-party-apify.md)） |
| 对照：自建 CloakBrowser 路线 | 住宅代理流量费（群帖页重，JS 渲染 + 滚动加载，粗估 50-150KB/帖有效流量 → 0.5-1.5GB/万帖，按 Decodo $2.75-4/GB 计） | **≈ $2-6/月代理费** + 自有维护人力 |

**要点：两家的 API 用量单价本身不贵，但都有 $19-49/月的档位最低消费；且在 FB 场景下它们只交付原始 HTML，相比 Apify 同价位直接给结构化字段，性价比明显更低。真正的参考价值在住宅代理层（见 §3）。**

## 3. 优劣势与定位

### Oxylabs

- 优势：企业级基础设施（175M+ 住宅 IP、195 国、99.9% API uptime、ISO 27001、Lloyd's 承保）；只按成功结果计费；Custom Parser（XPath/CSS）免费可把 HTML 解析成 JSON；2,000 结果免费试用免信用卡，PoC 成本低。
- 劣势：无 FB 专用解析器、无社媒产品线；最低消费 $49/月，小用量不划算；部分社媒目标（LinkedIn 已确认）要 KYC 才开放，FB 是否在限制清单内不透明；企业向销售流程重。
- 相对 Bright Data：同为企业级，但 Bright Data 有 FB 专用数据集/采集器产品线，Oxylabs 在 FB 上是空白。

### Decodo

- 优势：便宜——住宅代理 PAYG $4/GB、订阅低至 $2.75/GB，是主流大厂里最低档；Web Scraping API 模块化计费（简单目标不为难目标买单）；Free plan 免信用卡；GitHub 有 FB Page/Post/Group 的现成调用示例（虽旧）。
- 劣势：FB 能力弱是第三方评测共识（AIMultiple 2026-07：FB/IG 抓取弱于头部厂商）；社媒模板只有 YouTube/Instagram/Reddit/TikTok；价格页 JS 渲染难抓取、Premium+JS 费率不透明；FB 示例代码停留在 2022 年，维护状态存疑。
- 相对 Oxylabs：同档能力下价格约为 Oxylabs 的 1/2 到 2/3，企业背书与成功率数据弱一档。

### 与本项目自建路线及 Apify/Bright Data 的差异

| 维度 | 自建（fetcher + CloakBrowser） | Apify | Bright Data | Oxylabs / Decodo |
|---|---|---|---|---|
| FB 群帖结构化字段 | ✅ 自己提取，完全可控 | ✅ actor 现成字段 | ✅ 专用采集器/数据集 | ❌ 只有原始 HTML |
| 私密群（登录态） | ✅ 核心优势 | ❌ | ❌（公开数据定位） | ❌ |
| 反爬维护 | 自己扛 | actor 作者扛 | 平台扛 | 平台扛 IP/渲染层，解析层自己扛 |
| 1 万帖/月成本 | ~$2-6 代理费 + 人力 | ~$50 | 见 third-party-brightdata.md | ~$20-49 + 自解析 |
| 互补价值 | 主力 | 兜底/字段对照 | 兜底/数据集 | **住宅代理供应商（替代/补充现有代理渠道）** |

### 适用判断

- **Oxylabs / Decodo 的 Scraping API 不值得为 FB 采集单独采购**：无 FB 解析器、无登录态、最低消费吃掉单价优势，同价位 Apify 直接给字段。
- **值得关注的只有代理层**：若本项目自建 CloakBrowser 路线需要扩充住宅代理渠道，Decodo（PAYG $4/GB、3 天 100MB 免费试用、订阅低至 $2.75/GB）是主流厂家里性价比最高的候选之一；Oxylabs 代理质量好但 $30/月起、需联系销售开试用，适合量上来后再谈。
- **应急兜底排序建议**：Apify（字段全）> Bright Data > Oxylabs/Decodo 的 API（只回 HTML）；代理渠道补充排序：Decodo > Oxylabs（按本项目小体量）。

## 4. 诚实声明（未能核实项）

- Decodo Web Scraping API 的 **Premium 代理池 + JS 渲染精确费率**未能在官方页面抓到（定价页为动态渲染），$1-2/1K 为第三方区间估计；档位价格（$19/$49/$99）来自 scraperdb 2026-08，与 Decodo 官网当前展示可能有出入。
- Oxylabs Web Scraper API 对 Facebook 是否属于 KYC 限制目标**未确认**（官方清单只明确列了 LinkedIn，且注明"不限于此"）。
- Decodo GitHub 的 FB Page/Post/Group 示例为 2022 年提交，**当前是否仍能成功抓到 FB 群页 HTML 未实测**；FB 对匿名访问群内容的登录墙随时可能让 universal 方案失效。
- 两家均未注册账号、未实际调用 API；所有能力描述来自官方公开页面与文档。
- Oxylabs PAYG $8/GB、免费试用 100MB 等数字来自第三方评测（toptierproxy 2026-03），官网订阅页未直接展示。

## 来源汇总

- [Oxylabs Web Scraper API（产品+定价）](https://oxylabs.io/products/scraper-api/web)（2026-08-07 抓取）
- [Oxylabs Residential Proxies 定价](https://oxylabs.io/products/residential-proxy-pool)
- [Oxylabs 受限目标（KYC）文档](https://developers.oxylabs.io/help-center/most-popular-questions/restricted-targets-proxy-solutions-and-web-scraper-api)
- [Oxylabs Web Scraper API Playground 文档（source 列表无 FB）](https://developers.oxylabs.io/scraping-solutions/web-scraper-api/web-scraper-api-playground)
- [oxylabs/web-scraper-api GitHub（universal source、Custom Parser）](https://github.com/oxylabs/web-scraper-api)
- [Decodo Social Media Scraping API（已并入 Web Scraping API）](https://decodo.com/scraping/social-media)
- [Decodo Web Scraping API 官方文档（计费因子、Usage policy）](https://help.decodo.com/docs/web-scraping-api-introduction)
- [Decodo Web Scraping API 产品页](https://decodo.com/scraping/web)
- [Decodo Web-Scraping-API GitHub（FB Page/Post/Group 示例）](https://github.com/Decodo/Web-Scraping-API)
- [Decodo 统一 API 公告（Core from $0.08/1K）](https://decodo.com/blog/new-web-scraping-api)
- [Decodo Pricing（住宅代理档位）](https://decodo.com/pricing)
- [Decodo 博客：Best Web Scraping Proxies 2026（各家代理参考价）](https://decodo.com/blog/best-web-scraping-proxies)
- 第三方交叉验证：[AIMultiple Decodo Review 2026-07（FB/IG 能力弱）](https://aimultiple.com/decodo-review)、[Data4AI Decodo vs Oxylabs](https://data4ai.com/blog/vendors-comparison/decodo-vs-oxylabs/)、[scraperdb Decodo](https://scraperdb.com/tools/decodo)、[toptierproxy Oxylabs Pricing 2026](https://www.toptierproxy.com/blog/oxylabs-pricing-2026)
