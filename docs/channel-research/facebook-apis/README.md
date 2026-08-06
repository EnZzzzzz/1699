# Meta Graph API 调研（2026-08）

> 渠道调研子报告，主路线见 [../facebook-groups.md](../facebook-groups.md) §11。
> 结论先行：**Graph API 对本项目「采集别人 Page / 群组的公开帖子」场景基本不可用**，只能作为「管理自己 Page」的辅助工具。

## 1. 版本与 Base URL

- 最新 stable 版本：**v25.0**（2026-02-18 发布）；v24.0（2025-10-08）、v23.0 等旧版本仍可用。版本按季度发布，不指定版本号时默认走最老可用版本，请求里应显式带版本。
- Base URL：`https://graph.facebook.com/v25.0/`，全 HTTPS。
- 本次调研日期 2026-08-07，v25.0 为当前最新版（已用无 token 请求实测 `https://graph.facebook.com/v25.0/facebook/picture?redirect=false` 返回 200，证明该版本在线）。

来源：[Graph API Changelog](https://developers.facebook.com/docs/graph-api/changelog)、[Graph API Overview](https://developers.facebook.com/docs/graph-api/overview)

## 2. Token 类型与获取路径

| Token 类型 | 用途 | 获取方式 |
|---|---|---|
| User Access Token | 代表真人用户读写其数据（/me、自己的 Page 列表等） | Facebook 登录弹窗授权；测试用 Graph API Explorer 直接生成 |
| Page Access Token | 读写某个 Page 的数据（发帖、读 Page insights/posts） | 先拿 User Token，再调 `/me/accounts` 换得（每个 Page 一个） |
| App Access Token | 改应用设置等 app 级操作 | 服务端用 `app_id + app_secret` 调 `/oauth/access_token?grant_type=client_credentials` |
| System User Token | 企业内自动化（广告、Page 管理），不依赖真人 | Business Manager → System Users 生成 |

- 短期 token 约 1-2 小时，长期 token 约 60 天（Web 登录拿的短期 token 可用 app secret 换长期）。
- App Token 形如 `{app_id}|{app_secret}`，仅限服务端使用，不能读用户数据。

来源：[Access Tokens 官方文档](https://developers.facebook.com/docs/facebook-login/guides/access-tokens)

## 3. 创建应用 → 拿 token 流程与审核门槛

权限体系分两档（[Access Levels](https://developers.facebook.com/docs/graph-api/overview/access-levels)）：

- **Standard Access**：所有 Business/Consumer/Gaming 应用**自动获得，免审**。但只对「在应用里有角色的用户」（管理员/开发者/测试员）生效。
- **Advanced Access**：对任意用户生效。需要 **Business Verification**，部分权限/特性还要逐项 **App Review**（提交 screencast、用途说明，人工审核）。通过后每年要做 Data Use Checkup。

最小可用路径（自用、免审）：

1. 注册开发者账号 → 创建 Business 类型应用；
2. Graph API Explorer（<https://developers.facebook.com/tools/explorer/>）选应用，勾选 `pages_show_list`、`pages_read_engagement`，生成 User Token；
3. 该 token 即可读 **自己的** Page 的 posts/comments/insights。

## 4. 本项目场景：能干什么 / 不能干什么

| 需求 | 可行性 | 说明 |
|---|---|---|
| 搜索公开帖子（关键词找供应商帖） | ✗ | Post Search 早在 Graph API v2.0（2014）就下线 |
| 搜索公开 Page（Pages Search API） | ✗（实际不可用） | 需要 **Page Public Content Access** 或 **Page Public Metadata Access** 特性，两者都要 App Review |
| 读别人 Page 的公开 posts/comments | ✗（实际不可用） | 同样需要 Page Public Content Access（Advanced Access + App Review）；官方允许的用途是「分析和/或展示 Page 上的帖子和互动」，纯采集用途几乎不可能过审 |
| 读自己 Page 的 posts/comments/insights | ✓ | `pages_read_engagement` / `pages_show_list`，Standard Access 免审 |
| 读指定群组帖子 | ✗ | Groups API 已于 2024 年起大规模收回，无公开读取路径 |
| oEmbed 读公开帖嵌入信息 | ✗ | oEmbed Read 特性 2025-10-01 完全弃用 |

关键证据：官方 Features Reference 明确「Page Public Content Access allows your app access to the Pages Search API and to read public data for Pages for which you lack the pages_read_engagement permission」，即**一切「读别人 Page」的行为都收敛到这一个需要审核的特性上**。

来源：[Features Reference](https://developers.facebook.com/docs/apps/review/feature)、[Access Levels](https://developers.facebook.com/docs/graph-api/overview/access-levels)、[Post search deprecated (Stack Overflow)](https://stackoverflow.com/questions/23491308/facebook-api-post-search-deprecated)

## 5. 速率限制概况

- 两套体系：Platform Rate Limits（user/app token）与 Business Use Case Rate Limits（page/system user token，用于 Pages API 等）。
- App 级（Platform）：`每小时调用数 = 200 × 日活用户数`，滚动 1 小时窗口。新应用没用户，额度极低。
- Pages API（Page/System User token）：`每 24 小时 = 4800 × 当日与该 Page 有互动的用户数`，小 Page 额度同样极低。
- 超限错误码：4（app）、17/32（user/page）、613（自定义限额）；BUC 类为 80001–80014。
- 用量实时看响应头 `X-App-Usage` / `X-Business-Use-Case-Usage`（demo 脚本会打印）。

来源：[Rate Limiting](https://developers.facebook.com/docs/graph-api/overview/rate-limiting)

## 6. Demo 用法

```bash
cd docs/channel-research/facebook-apis

# 无 token：打印获取指引，退出码 1
python3 graph_api_demo.py

# 有 token：验证 token + 列自己的 Page
export META_ACCESS_TOKEN="EAAG..."
python3 graph_api_demo.py

# 追加读指定 Page 的最近 10 条帖子
python3 graph_api_demo.py <page_id>
# 或 META_PAGE_ID=<page_id> python3 graph_api_demo.py
```

退出码：`0` 成功；`1` 缺 token（打印指引）；`2` token 无效（/me 失败）；`3` 读 Page posts 失败。

只依赖 Python 标准库（urllib），Python 3.8+ 可跑。

## 7. 验证情况（诚实标注）

| 项目 | 状态 |
|---|---|
| 最新版本 v25.0、base URL、token 类型、权限/特性体系、速率限制规则 | ✓ 已核实，均来自官方文档（见各节来源链接；官方站点拦直接抓取时经 web.archive.org 镜像读取） |
| v25.0 在线、无 token 端点行为 | ✓ 实测：`/v25.0/facebook/picture?redirect=false` 无 token 返回 200（头像图片 URL）；`/v25.0/me` 无 token 返回 400 + `(#2500) An active access token must be used...` |
| 脚本无 token 时的指引输出与退出码 | ✓ 已实测（退出码 1，指引完整打印） |
| 脚本带真实 token 的 (a)/(b)/(c) 三步调用 | ✗ **未验证**——调研范围内没有可用 token，需要人工注册 Meta 开发者账号后自行验证 |

## 8. 一句话判断

Graph API 对「采集外贸供应商公开内容」不值得接入：所有读第三方公开数据的路径都收敛到需要 App Review 的 Page Public Content Access，采集用途难过审且额度随互动量浮动；它只适合管理自有 Page。本项目保持「匿名抓群帖 permalink」主路线不变。
