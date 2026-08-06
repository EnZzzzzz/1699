# Meta Ad Library API（广告库 API）调研

> 调研时间：2026-08。关联：[../facebook-groups.md](../facebook-groups.md) §11 渠道全景。Demo：`ad_library_demo.py`。
> 结论速览：**对本项目是"低优先级补充源"** —— API 的商业广告覆盖被 DSA 地域规则卡死：只有投放目标含欧盟/欧洲经济区国家的商业广告才进 API；中国供应商/货代的主战场（美国、中东、东南亚、非洲）投放的商业广告 **API 一条都不返回**。零成本替代是网页版广告库（匿名可搜，但只能人工用或走爬虫）。

## 1. 访问条件

| 项 | 结论 |
|---|---|
| 凭证 | Graph API **user access token**（无独立 API key）；短期 token 60 分钟，可经 `oauth/access_token` 换 60 天长期 token |
| 身份确认 | **强制**。facebook.com/ID 上传政府签发证件 + 确认所在国家，审核约 1-3 个工作日；中国大陆身份证常被拒，常见做法是护照/境外主体 |
| App | developers.facebook.com 创建 Business 类型 App，添加 "Ad Library API" 产品并接受条款 |
| 政治 vs 全部广告 | 同一个 token、同一个端点；差异不在权限而在 `ad_reached_countries` 的地域规则（见 §2/§3） |
| EEA 特殊规则 | DSA 合规要求下，**投放到欧盟/EEA 的商业广告进 API 且带专属字段**（`eu_total_reach`、`total_reach_by_location`、`age_country_gender_reach_breakdown`、`target_*`），约 1 年保留期；政治广告全球覆盖、保留 7 年 |
| 费用 | API 本身免费；商业广告全量数据（含非欧盟）只有 Meta Content Library（CASD 研究员通道，$371/team/月 + $1000 启动费，仅欧盟学术 affiliation，中国大陆基本申请不到） |

## 2. 端点与参数

唯一端点：`GET https://graph.facebook.com/v<版本>/ads_archive`（调研时社区实测 v20.0/v21.0 均可用）。

| 参数 | 必填 | 说明 |
|---|---|---|
| `access_token` | 是 | user token |
| `ad_reached_countries` | 是 | ISO-2 国家代码数组（`['US','DE']`）或 `['ALL']`；**决定覆盖范围**（见下） |
| `search_terms` 或 `search_page_ids` | 二选一 | 关键词（空格=AND、引号=短语，模糊匹配弱）；`search_page_ids` 按广告主 Page ID 拉（每次最多约 10 个，更快更稳） |
| `ad_type` | 否 | `POLITICAL_AND_ISSUE_ADS`（默认）/ `ALL` / `HOUSING_ADS` / `EMPLOYMENT_ADS` / `CREDIT_ADS`（后三个仅美国）。**查商业广告必须显式传 `ALL`** |
| `ad_active_status` | 否 | `ACTIVE` / `INACTIVE` / `ALL` |
| `ad_delivery_date_min/max` | 否 | `YYYY-MM-DD`，按开始投放日过滤 |
| `media_type` | 否 | `ALL` / `IMAGE` / `VIDEO` / `MEME` / `NONE` |
| `publisher_platforms` | 否 | `FACEBOOK` / `INSTAGRAM` / `AUDIENCE_NETWORK` / `MESSENGER` / `THREADS` |
| `languages` | 否 | ISO 语言代码数组 |
| `fields` | 否 | 逗号分隔字段清单（默认只返回 id、snapshot_url、起止时间、page_id） |
| `limit` | 否 | 每页条数；标称上限 5000，实测常在 1000-2000 截断，需配合分页 |

**覆盖范围关键规则**：`ad_reached_countries=['US']` 时无论 `ad_type` 传什么都只返回政治/议题广告；换成欧盟国家代码（`DE`、`FR`…）才返回该市场的商业广告。

**分页**：响应带 `paging.cursors.after` 和完整 `paging.next` URL，第二页起直接 GET `paging.next` 即可（demo 已实现）。

**速率限制**：Meta 未公布固定数字，社区实测约 **200 calls / user / hour**（App + User 维度），触发返回 HTTP 429 或 `error.code` 4/17/613，需等 30-60 分钟；只拉必需字段、按 page_id 查询、夜间跑大批量、指数退避是通行做法。另有组织级隐藏配额，堆 App 轮换收益有限。

## 3. 返回字段对本项目的价值矩阵

| 字段 | 政治广告 | 欧盟商业广告 | 非欧盟商业广告 | 本项目价值 |
|---|---|---|---|---|
| `page_id` / `page_name` | ✓ | ✓ | ✗ | **高**：广告主主页，可直接转线索 |
| `ad_creative_bodies` / `link_titles` / `link_descriptions` | ✓ | ✓ | ✗ | **高**：广告正文，可提取联系方式/WhatsApp 号/域名 |
| `ad_snapshot_url` | ✓ | ✓ | ✗ | **高**：素材快照嵌入页（带 token 参数），可看原素材和落地页跳转 |
| `publisher_platforms` / `languages` | ✓ | ✓ | ✗ | 中 |
| `ad_delivery_start/stop_time`、`ad_creation_time` | ✓ | ✓ | ✗ | 中：判断在投活跃度 |
| `spend` / `impressions` / `currency` | ✓（区间值，如 lower 1000 / upper 4999） | ✗ | ✗ | —（**商业广告一律不给花费/曝光**，只政治广告给） |
| `demographic_distribution` / `delivery_by_region` / `estimated_audience_size` / `bylines` | ✓ | ✗ | ✗ | — |
| `eu_total_reach` / `total_reach_by_location` / `age_country_gender_reach_breakdown` / `target_*` | ✗ | ✓ | ✗ | 中：欧盟广告的触达量与定向 |

一句话：**spend/impressions 只给政治广告；欧盟商业广告给 `eu_total_reach` 但不给花费**。对"找在投广告的中国供应商"这个需求，能用的是 page_name + 广告正文 + snapshot_url 这套素材与身份字段。

## 4. 网页版广告库（无需 API）匿名可用性

- https://www.facebook.com/ads/library 是公开产品，**真实浏览器不登录即可搜索全球全量在投广告（含商业广告）**，支持关键词、国家、平台、在投状态、媒体类型过滤。
- 本机 curl 实测（2026-08-06）：裸 curl 与带浏览器 UA 的 curl 均返回 **HTTP 403（481 字节质询页）**——Facebook 对非浏览器客户端有 TLS 指纹/挑战拦截，裸 HTTP 抓取不可行；要程序化抓网页版需要真实浏览器自动化（本项目 WebBridge/Playwright 路线可行，但那是另一条渠道的话题，与匿名群帖 permalink 路线同属网页抓取侧）。
- 作为**人工零成本补充**完全成立：运营在浏览器里搜 "china sourcing" / "freight forwarder"，10 分钟就能攒一批广告主主页。

## 5. Demo 用法

```bash
export META_ACCESS_TOKEN='EAABsb...'   # 获取步骤见下
cd docs/channel-research/facebook-apis

python3 ad_library_demo.py                                   # 默认搜 "china sourcing"，DE/FR/GB
python3 ad_library_demo.py --query "freight forwarder" --countries DE FR NL --max-ads 50
python3 ad_library_demo.py --query '"dropshipping agent"' --active-status ALL
```

注意：`--countries` 必须含欧盟国家代码，否则商业广告结果为空（不是 bug，是 §2 的覆盖规则）。

## 6. Token 获取逐步指引（需人工操作）

1. 注册 Meta 开发者账号：developers.facebook.com（需 Facebook 个人号；国内 IP + +86 手机号风控严格，建议境外主体/号码）。
2. 身份确认：facebook.com/ID 上传政府签发证件并确认国家，等 1-3 个工作日。
3. 创建 App：My Apps → Create App → 类型 Business。
4. App Dashboard → Add Product → "Ad Library API" → 接受条款。
5. Tools → Graph API Explorer → 选该 App → Generate Access Token；生产用建议换成 60 天长期 token 并定时续期（约每 55 天）。
6. `export META_ACCESS_TOKEN='...'` 后跑 demo。

## 7. 验证情况（诚实声明）

- ✅ 脚本 `--help`、无 token 打印指引并 exit 2：本机实测通过。
- ✅ 请求结构可达性：用假 token 实测，Meta 返回 `HTTP 400 code=190 "Invalid OAuth access token data"`——证明端点、参数编码、错误处理路径均正常到达 Graph API，仅差真实凭证。
- ❌ **真实 API 数据未验证**：无可用 token，字段实际返回形态、分页行为、商业广告覆盖率均依据下方来源文档，未经本机真实调用确认。
- ✅ 网页版匿名可用性：curl 实测被 403 拦截（如实记录）；浏览器匿名可用为 Meta 产品公开事实。

## 8. 来源

- [Meta Ad Library API 开发者指南：v20.0 代码 + CASD 访问（2026，AdMapix）](https://www.admapix.com/zh/blog/ad-intelligence/meta-ads-library-api-developers) — 2026-04 实测参数、限流、token 流程、CASD 细节
- [Facebook Ad Library API: The Developer's Guide to ads_archive（Ads Uploader，2026-07）](https://adsuploader.com/blog/facebook-ad-library-api) — 地域覆盖规则（US 仅政治、欧盟含商业）、字段分层
- [Meta Ads Library API 2026: Graph API v20.0 参数矩阵（AdMapix）](https://www.admapix.com/blog/ad-intelligence/meta-ads-library-api-developers) — 参数清单
- [Apify Meta Ads Library Scraper 技术说明](https://apify.com/harvestlab/facebook-ads-library-scraper) — 200 calls/hour 限流实测值、分页
- [How To Use the Facebook Ads Library API（admanage.ai，2026）](https://admanage.ai/blog/facebook-ads-library-api) — 访问条件与 token 流程
- [Ad Transparency Surfaces 2026（Primores）](https://primores.org/wiki/competitor-analysis/ad-transparency-surfaces/) — 跨平台对比：Meta 商业广告 spend 不给、欧盟层级更富
- [Meta Ad Library API: Access, Limits and Example Requests（swipekit，2025-07）](https://swipekit.app/articles/meta-ad-library-api) — token 生命周期
- 官方文档 https://developers.facebook.com/docs/marketing-api/reference/ads-archive/ 与 https://www.facebook.com/ads/library/api/ 本机访问被反爬拦截（404/403/400），未能直接引用原文，上述第三方来源均声称对照官方文档验证。
