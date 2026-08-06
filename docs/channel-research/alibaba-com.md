# 渠道侦察报告：阿里国际站 alibaba.com

> 侦察时间：2026-08-06（北京时间），方式：Kimi WebBridge 控制真实浏览器（未登录状态），session `probe-alibaba`。
> 目的：评估 alibaba.com 作为「中国外贸供应商联系方式（手机号/WhatsApp）采集渠道」的可行性。

## 一、结论先行

**推荐，但走「目录页 + 店铺联系页 + 供应商官网二跳」链路，不走站内直采。**

- 站内页面（店铺首页 / 公司档案 / 联系信息页）在**未登录状态下不暴露** WhatsApp、wa.me、手机号（实测 3 家供应商、正则扫描全为 0 命中）；公司电话/移动电话被「查看详情」登录墙遮挡（实测点击弹出登录框）。
- 但联系信息页**免登录可见两个高价值字段**：联系人姓名+职位、**公司官网 URL**。供应商官网（外贸独立站）普遍挂 WhatsApp 挂件/号码——实测首跳官网即提取到 WhatsApp 号码（`+86 189 48** **5726`，脱敏）。
- 供应商列表发现应走 **showroom/类目目录页**（未触发验证码），**避开 /trade/search**（约 6 次快速翻页即触发滑块验证码，且该路径封锁 ≥15 分钟不解除）。

## 二、入口 URL 清单

| 用途 | URL 形式 | 备注 |
|---|---|---|
| 供应商搜索 | `https://www.alibaba.com/trade/search?SearchText=<kw>&tab=supplier&page=N` | 每页约 10 个供应商子域；**反爬严重，不推荐主用** |
| 产品搜索 | `https://www.alibaba.com/trade/search?SearchText=<kw>&tab=all&page=N` | 每页约 40-48 个产品，同上受限 |
| 类目/关键词目录（推荐） | `https://www.alibaba.com/showroom/<kw>.html` | 实测按浏览器 locale 302 到 `https://chinese.alibaba.com/g/<kw>.html`；fetcher 需固定英文 locale cookie / Accept-Language |
| 目录分页 | `https://chinese.alibaba.com/g/<kw>_2.html` … `_100.html` | 页码 1-100；英文形态 `/showroom/<kw>_<N>.html`（实测会被 locale 重定向，需固定 locale）；**每页约 40 个不重复供应商子域** |
| 店铺首页 | `https://<shop>.en.alibaba.com/` | |
| 公司档案页 | `https://<shop>.en.alibaba.com/company_profile.html` | 平台表现、主营产品、认证信息 |
| 联系信息页（核心） | `https://<shop>.en.alibaba.com/contactinfo.html` | 联系人姓名/职位 + 公司网站（免登录）；电话/手机（登录墙后） |
| 站内信联系 | `https://message.alibaba.com/msgsend/contact.htm?...&id=<companyId>&chatToken=...` | 需登录，不适合采集 |

供应商唯一标识：店铺子域名（如 `anhanglighting`）+ `companyId`（档案页 HTML 内嵌 JSON，如 `264191939`）。

## 三、联系方式出现位置（实测）

正则 `wa\.me|whatsapp|\+86|1[3-9]\d{9}` 扫描结果：

| 页面 | wa.me | whatsapp 关键词 | 手机号 | 说明 |
|---|---|---|---|---|
| 店铺首页（szcjlighting） | 0 | 0 | 0 | |
| 公司档案页（anhanglighting、reddotled） | 0 | 0 | 0 | 唯一 11 位数字命中是 JS 时间戳（误报，已排除） |
| 联系信息页 contactinfo.html | 0 | 0 | 0 | 电话/传真/移动电话均为「查看详情」占位 |
| 供应商官网（reddotled.com，二跳） | 0 | **20 次** | **有** | WhatsApp 聊天挂件绑定号码，脱敏样例：`+86 189 48** **5726` |

contactinfo.html 免登录可见内容样例（reddotled）：

```
公司联系信息
Ms. Andy Li
Manager
公司电话： 查看详情      ← 点击弹登录框（Google/淘宝/Facebook/LinkedIn/邮箱）
公司传真： 查看详情
公司移动电话： 查看详情
公司网站： https://www.reddotled.com   ← 免登录直接可见
```

## 四、登录墙与反爬观察

- **登录墙**：仅「查看详情」（公司电话/手机/传真）、站内信、部分产品详情页（实测一个 product-detail 链接被 302 到 login.alibaba.com，可能与会话被标记有关）。列表页、店铺页、联系信息页本身**无需登录**。
- **滑块验证码**：在 `/trade/search` 路径约 2 秒间隔连续翻页，**第 6 次请求触发**「验证码拦截·请拖动滑块」整页拦截。
- **封锁范围与时长**：触发后 `/trade/search` 路径持续拦截 **≥15 分钟**（多次复测未解除）；但首页约 45-60 秒恢复，且 `/g/`、`/showroom/` 目录页与 `*.en.alibaba.com` 店铺子域**全程不受影响**。说明风控是按路径/行为维度而非纯 IP 一刀切。
- **目录页耐受**：8-10 秒间隔访问 `/g/<kw>_<N>.html` 与店铺子域多页，未触发验证码（showroom 一次 page load timeout 系网络慢，非拦截）。

## 五、规模粗估

- 类目目录：关键词页（showroom/g）量级为数千至数万（阿里 SEO 关键词矩阵），每词最多 100 页 × 约 40 供应商/页 = 单词上限约 4000 条店铺曝光（深页可能不满载），跨词去重后阿里公开口径供应商约 20 万+。
- 单类目实测：`led-light` 第 1、2 页各 39-40 个不重复店铺子域，无重叠。
- 按 200 个核心行业词 × 每词有效 500-2000 家去重店铺估算，可触达店铺量级 **10 万+**；配合官网二跳，WhatsApp 预期命中率 30-60%（外贸独立站挂 WhatsApp 为行业常态，已实测 1/1 命中）。

## 六、fetcher 站点插件建议（`fetcher/sites/alibaba_com/`）

1. **列表层**：种子为行业关键词表 → `GET /showroom/<kw>_<N>.html`（固定 locale cookie 防重定向；或直接解析 `chinese.alibaba.com/g/<kw>_<N>.html`，子域链接不受影响）。提取 `https://<shop>.en.alibaba.com` 子域去重入 `shops` 表。速率 ≤1 req/5-10s。
2. **详情层**：`GET <shop>.en.alibaba.com/contactinfo.html` → 抓 `contact_name`（如 Ms. Andy Li）、`title`（Manager）、`company_website`、`company_id`（页面内嵌 JSON）、子域名、所在地。顺带正则扫 `wa\.me|whatsapp|\+86|1[3-9]\d{9}`（预期命中率低，聊胜于无）。速率 ≤1 req/3-5s。
3. **二跳层（核心价值）**：`GET company_website` 首页 + `/contact*` 路径 → 正则提取 `wa\.me/(\d+)`、`api\.whatsapp\.com/send?phone=`、`\+?\d[\d\s-]{7,17}`。外贸站多为模板建站（挂件代码含明文号码），命中率高。每站 2-3 请求，速率按目标站容忍度 1 req/2-5s。
4. **反爬策略**：主链路全程避开 `/trade/search`；目录页与店铺子域走保守速率 + 指数退避；一旦返回「验证码拦截」页（title 特征可直接判）即对该路径冷却 ≥20 分钟，其他路径不停。`/trade/search` 仅作可选补充（需代理池/换 IP，速率 <1 req/10s）。
5. **可选增强**：若用户登录买家账号（cookie 注入），「查看详情」可解出公司电话/手机——但触发账号风控风险高，建议二期评估，不做进首版。
6. **字段落库映射**：`shops`（shop_subdomain, company_id, company_name, country, main_products, contact_name, contact_title, website, source_keyword）→ `contacts`（website, whatsapp, phone, email）→ wa_check 复用现有进程内任务。
