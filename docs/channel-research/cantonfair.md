# 渠道侦察 · 广交会（Canton Fair）参展商名录

> 侦察日期：2026-08-06 · 方式：Kimi WebBridge 控制真实浏览器（session: probe-cantonfair）+ SPA JS bundle 静态分析 + 接口实测
> 结论先行：**名录枚举极易（明文 JSON API、无鉴权、可全量拉取），但手机号/邮箱登录墙后不可见（服务端强制 null）。作为「企业名单 + 官网」一级渠道优秀，作为「手机号直采」渠道不可行（匿名态），需二跳企业官网或登录账号。**

---

## 1. 入口与站点结构

广交会官网（`www.cantonfair.org.cn`）本身是 JS SPA（无 `<a>` 标签），展商名录**不在主站**，而在独立子站「广交会365」：

| 站点 | URL | 说明 |
|---|---|---|
| 365 平台首页（中） | `https://365.cantonfair.org.cn/zh-CN` | 永不落幕的广交会，展商+展品 |
| 365 平台首页（英） | `https://365.cantonfair.org.cn/en-US` | 同一套 API，locale 切换 |
| 展商搜索页（中） | `https://365.cantonfair.org.cn/zh-CN/search?queryType=supplier&searchWord=<kw>` | queryType=supplier 为展商搜索 |
| 展商搜索页（英） | `https://365.cantonfair.org.cn/en-US/search?queryType=supplier&searchWord=<kw>` | 实测可用 |
| 展商详情页 | `https://365.cantonfair.org.cn/zh-CN/shops?id=<shopNo>` | shopNo 为 10 位数字 ID |
| 产品搜索 | `…/search?queryType=product&searchWord=<kw>` | 顺带可用 |

注意：`www.cantonfair.org.cn/zh-CN/shops`（主站路径）404，勿用。

## 2. 核心 JSON API（重点：明文、无鉴权、可直接打）

所有接口在浏览器匿名态实测成功（HTTP 200 + errCode 0）。网关域名固定为 `https://www.cantonfair.org.cn/appbuyerapi`（从 365 子站跨域调用，CORS 放行）。

**必需请求头**（缺一返回 400 参数有误/服务器异常）：

```
Content-Type: application/json;charset=utf-8
cus-os-type: WEB
deviceid: <32位大写字母数字串，任意固定值即可>
locale: zh-CN        # 或 en-US，控制返回语言
accept-language: zh-CN
```

### 2.1 展商列表搜索（采集主接口）

```
POST https://www.cantonfair.org.cn/appbuyerapi/exhibition/queryshop
```

请求体（实测可用组合）：

```json
{
  "categoryId": "461147080727994368",   // 类目ID；与 keyword 二选一（都空则400）
  "keyword": "",                        // 关键词；用 categoryId 枚举时可空
  "pageIndex": 1,
  "pageSize": 20,                       // 展商搜索 UI 固定 20；产品搜索 40
  "searchProductShop": "N",
  "searchBooth": "N",                   // Y = 按展位号搜索
  "isOffline": "N",                     // Y = 仅线下参展企业
  "companyType": "",
  "businessTypeList": ["外贸企业"]       // 可选：业务类型筛选（生产企业/外贸企业）
}
```

- 响应：`result.itemList[]` + `result.totalElements`（总数）。
- **深分页无上限实测**：类目 1980 条翻到 pageIndex=99（偏移 1960）正常返回 20 条，100 页为空。
- **全局 5000 条截断**：总量 > 5000 时 totalElements 只报 5000（时尚类目实测）。规避：按 **56 个二级类目**枚举（实测最大二级类目 1482 条，远低于上限）。
- itemList 单条字段（很丰富）：`shopNo/id/code`、`name`（随 locale 中英文）、`shopMainImg`、`tagDescList`（如 "Brand Enterprise"/"Multiple-session Exhibitor"）、`offlineShops[].areas[].booth`（**届数 session=139、期数 period、展馆 hall、楼层 floor、展位号 booth**）、`isPremiumSupplier/isBrandEnterprise/isNewHighTechEnterprise/isAeo/isCfAward…` 布尔标签、`imAccount`、`session`/`period`。
- 列表**不含**电话/邮箱/联系人。

### 2.2 展商详情

```
GET https://www.cantonfair.org.cn/appbuyerapi/supplier/detail?supplierNo=<shopNo>
```

响应 `result` 关键字段：

- `companyName` / `companyNameEn`、`companyLogo`
- `boothList[]`：本届展位（session/period/hall/floor/booth/areaName）
- **`lastTenEdition`: ["139","138","137",…]**：近十届参展历史（参展届数越多越是老外贸，质量信号极强；抽样 8 家中 6 家连续 10 届参展）
- `companyIntroduction`：企业简介
- **`companyContact`**：`{mobile, mobile_country_code, email, phone, phoneCountryCode, fax, position, companyWebsite, companyAddress, username}` —— **匿名态 mobile/email/phone/fax/addr 全部为 null**；**`companyWebsite` 多数公开**（抽样 8 家中 7 家有真实官网 URL，如 `http://www.tjhaishun.com`、阿里国际站店铺等）

### 2.3 类目树

```
GET https://www.cantonfair.org.cn/appbuyerapi/app/back/category/tree
```

- 返回 **13 个一级板块 → 56 个二级展区 → 661 个三级类目**（与官网「13个板块 54个展区」口径一致，含中英文名称）。
- JS 里标注 isCrypto（RSA 加密请求）的接口，实测**服务端不校验加密**，明文直调即可。

### 2.4 其他实测接口

| 接口 | 说明 |
|---|---|
| `GET /appbuyerapi/exhibition/suggest?q=<kw>&type=product&offline=0` | 搜索联想，无需鉴权 |
| `GET /tradeapi/buyer/inquiry/dist/shop/user?shopNo=<id>` | 返回店铺联系人**姓名**（如"张美财"）+ imAccount，无电话 |
| `POST /appbuyerapi/exhibition/queryproduct` | 产品搜索（同构） |

## 3. 手机号 / WhatsApp 实测结论（核心问题）

- 详情页 UI 有「手机号 查看」「邮箱 查看」按钮 → 点击弹「**请注册/登录后进行该操作**」，且**点击时不发任何请求**（前端拦截）。
- 接口层确认：匿名调 `supplier/detail`，`companyContact.mobile/email/phone` **服务端直接返回 null**（不是前端遮蔽），8 家抽样全 null。
- 页面正则实测 `1[3-9]\d{9}|whatsapp|wa\.me`：**0 命中**（匿名态全站无手机号暴露）。
- 联系人只有**姓名**公开（IM 系统对接），无号码。
- **登录后是否可见手机号未验证**（需注册买家账号，UI 暗示登录可查看，大概率可见但可能有每日查看上限/需先发询盘——留待有账号后复测）。
- 官网 `companyWebsite` 公开率高（~85%+），可做**二跳采集**：爬企业官网 contact 页提取手机号/WhatsApp/邮箱。

## 4. 反爬与登录墙观察

- 侦察全程连续发起 **40+ 次 API 请求**（含 13 次 ~600ms 间隔连发、8 次详情连发），**无验证码、无 403、无频率限制、无 IP 封禁**。
- 列表/详情 API **无需登录、无 token、无签名**；`deviceid` 头任意固定值即可（疑似埋点用途）。
- 埋点请求（`appmanager.cantonfair.org.cn/buryingapi`）有 RSA 加密，与采集无关，可忽略。
- 登录墙仅在：查看手机号/邮箱、给我留言/IM、收藏、发询盘。

## 5. 规模估算

按一级类目实测 totalElements 求和（2026-08，含纯线上企业）：

| 板块 | 展商数 | 板块 | 展商数 |
|---|---|---|---|
| 礼品及装饰品 | 4,907 | 家庭用品 | 4,741 |
| 时尚 | 5,000（截断） | 电子家电 | 3,894 |
| 健康休闲 | 4,370 | 工业制造 | 3,357 |
| 建材及家具 | 4,198 | 五金工具 | 3,629 |
| 车辆及两轮车 | 2,277 | 照明及电气 | 1,891 |
| 家用纺织品 | 1,834 | 玩具及孕婴童 | 1,707 |
| 文具 | 1,063 | | |

**合计 ≥ 42,868 家**（时尚被 5000 截断，实际估 ~46k–48k；含多届累计入驻企业，非单届）。线下单届参展商通常 2.5万–3万家/届，`isOffline=Y` + `session=139` 展位数据可圈定本届企业。
- 业务类型筛选 `businessTypeList:["外贸企业"]` 可用（ shoes 关键词下 6 家中 3 家外贸企业，占比高）。
- 历届：lastTenEdition 覆盖 130–139 届，可筛「连续参展老外贸」。

## 6. 采集可行性结论

| 维度 | 评级 | 说明 |
|---|---|---|
| 企业名单枚举 | ★★★★★ | 明文 API、无鉴权、无频控、56 类目全量可拉，4 万+ 家 |
| 字段丰富度 | ★★★★☆ | 中英文公司名、展位（届/期/馆/位）、官网、参展史、资质标签、业务类型 |
| 手机号直采 | ★☆☆☆☆ | 服务端登录墙，匿名全 null；有买家账号后可复测 |
| 二跳手机号/WA | ★★★☆☆ | ~85% 企业有公开官网，爬官网 contact 页可提手机号/WhatsApp（成熟模式，命中率取决于官网质量） |
| 反爬风险 | 极低 | 实测 40+ 连发无限制；仍建议 1-2 req/s 礼貌速率 |

**定位建议：广交会365 = 优质「外贸企业种子名单 + 官网域名 + 参展质量标签」渠道**。手机号获取走两条路：(a) 二跳官网抓取；(b) 注册买家账号复测 companyContact 可见性（若可见则价值翻倍，直接命中手机号）。

## 7. fetcher 插件实现建议（`fetcher/sites/cantonfair365/`）

**阶段一：名录枚举（纯 HTTP，无浏览器）**
1. `GET /app/back/category/tree` 拉类目树（取 56 个二级类目 ID）。
2. 对每个二级类目 `POST /exhibition/queryshop`（`categoryId` + 空 keyword + `pageSize=20`）翻页至空；可选叠加 `businessTypeList:["外贸企业"]`、`isOffline:"Y"` 分流。
3. 对每家 `GET /supplier/detail?supplierNo=` 补 `companyWebsite`、`lastTenEdition`、`companyIntroduction`。
4. 请求头固定 5 个（见 §2），deviceid 全局复用一个即可。
5. 入库字段：shop_no, name_zh, name_en, website, booth(session/period/hall/booth_no), editions[], tags[], business_type, category_path, is_offline。

**速率预估**：列表 ~4.3 万家 ÷ 20 条/页 ≈ 2,200 请求 + 详情 4.3 万请求 ≈ **4.6 万请求**；按 1.5 req/s 约 **8.5 小时**跑完全量（可并发放到 3 req/s 压到 ~4h，实测服务端无频控但建议保守）。增量：按 `session=139` 或 isNewExhibition 标签过滤新企业。

**阶段二：手机号获取（二选一）**
- A. 官网二跳：对 website 非空企业跑通用官网 contact 抓取 atom（复用现有 detect 层提手机号/WhatsApp），预计覆盖 3.5 万+ 域名。
- B. 买家账号复测：注册广交会365买家账号 → 验证登录后 `companyContact.mobile` 是否返回；若可见，评估每日查看配额后做低速登录态采集（注意合规与账号风控）。

**风险**：接口为内部 API（无公开文档），字段/鉴权策略可能随时收紧（deviceid 校验、加签）——atom 需对 400/403 做 Outcome 上报而非硬失败；登录态采集有 ToS 与账号封禁风险，需用户决策。
