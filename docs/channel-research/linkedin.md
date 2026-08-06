# LinkedIn 渠道侦察报告：中国外贸从业者主动公开 WhatsApp/手机号

> 侦察日期：2026 年（本次会话）；方式：Kimi WebBridge 控制用户真实浏览器实测，只读、未发任何连接请求/点赞/评论。
> 结论先行：**LinkedIn 直连路径（登录后站内搜索）当前不可用（用户未登录且全站 authwall），但「Google dork 收割 LinkedIn 公开索引」路径实测高度可行**——号码大量直接出现在搜索结果标题/摘要中，无需访问 LinkedIn 页面本身即可收割。

---

## 1. 登录态结论

- 用户浏览器 **未登录 LinkedIn**：访问 `/feed/` 被 302 至 `/login`。
- 实测确认 LinkedIn **全站 authwall**：
  - 站内内容搜索 `/search/results/content/` → 重定向到登录页；
  - 个人资料页 `linkedin.com/in/<slug>` → 重定向到 `linkedin.com/authwall`（页面仅剩注册表单，正文不可见，页面文本仅 243 字符）。
- 因此本次**无法实测站内内容搜索/人员搜索的登录态密度**；所有密度数据来自 Google 公开索引旁路（§3）。如未来用户提供登录会话，站内搜索路径可补充验证，但风控风险极高（§4）。

## 2. 站内路径（登录态）可行性预判

未实测，基于公开认知的定性判断：

- LinkedIn 免费账号存在**商业使用限制**（搜索次数/资料浏览量月度上限，约千次级），超限直接锁搜索；
- 对自动化行为（高频搜索、批量 profile view、Headless 特征）风控以严格著称，处罚为账号限制乃至封禁，**账号本身是消耗品**；
- 站内人员搜索（`foreign trade` / `sourcing` / `export sales` + China）理论上命中率高，但资料页 Headline/About 是否留号需逐页打开，触发风控的速度远快于收益积累。

**定性结论：站内直连采集不推荐作为主路径。**

## 3. Google dork 旁路实测（核心发现）

### 3.1 各 dork 实测数据

| Dork | Google 估算结果量 | 首页 LinkedIn 链接 | 标题/摘要直含号码密度 | 页面号码正则命中 |
|---|---|---|---|---|
| `site:linkedin.com/in whatsapp "+86"` | ≈78,400 | 9/10 | 5/9 标题直含 | 14 处 |
| `… + sourcing agent` | ≈1,010 | 10/10 | 摘要普遍含完整号码+邮箱 | 多处 |
| `… + export sales` | ≈10,400 | 10/10 | 摘要含号码 | 多处 |
| `… + freight forwarder` | ≈1,580 | 10/10 | 标题/摘要均含 | 11 处 |
| `… + factory` | ≈34,100 | 10/10 | **5/10 标题直含** | 14 处 |
| `site:linkedin.com/posts …`（两次） | — | — | **触发 Google 验证码，未取到数据** | — |

翻页深度实测：`start=10 / 30 / 60`（第 2/4/7 页）均正常返回，每页稳定 10 条 LinkedIn 结果、12–14 处号码正则命中，**深翻不衰减**。

### 3.2 脱敏样例（真实命中，号码已脱敏）

- `Poppy Chen - Whatsapp number: +86 153****3085`（标题直含）
- `Helen Zhu - 📞whatsapp: +86 159****9435 | 📮Email…`（标题直含）
- `Ander Lee - WhatsApp: +86 199****6156`（标题直含）
- `Mr Bill guo - Sales Manager，whatsapp +86 159****5600`（标题直含）
- `Janna Mai - WhatsApp : +86 132****4994/ Sales Manager`（标题直含）
- `Cici Guo - WhatsApp Me: +86 137****5034 PC&Mobile…`（标题直含）
- 摘要样例：`中国 山东省 潍坊市 · 外贸业务员 · Self-employed … WhatsApp: +86 132****8763 Email: yong****@gmail.com`（**号码+邮箱+角色+地区一次收割**）
- 摘要样例：`Export Manager … Contact Harriet on WhatsApp: +86 150****8401`

### 3.3 旁路路径的关键特性

1. **号码在 SERP 标题/摘要层即可收割，无需点击进 LinkedIn**——完全绕开 authwall，不依赖 LinkedIn 登录态，不产生任何 LinkedIn 侧风控暴露。
2. Google 对 `site:linkedin.com/in whatsapp "+86"` 估算 **7.8 万条**索引；组合角色关键词（sourcing/export/factory/freight/外贸）可切出多个数千至数万级的子池，总量估计 **十万级**。
3. 附带收获：摘要常同时含**邮箱、地区、公司角色**，对号码质量分级极有价值。

### 3.4 旁路的真实瓶颈：搜索引擎侧反爬

- 实测约 **8–10 次快速查询后触发 Google 验证码**（`unusual traffic`），Bing 同样触发人机验证；
- 停止约 1 分钟后 Google 恢复（无 IP 封禁迹象）；
- 结论：裸跑可行但**必须限速**（建议 ≥10–15s/查询 + 抖动），规模化需代理轮换或 SERP API 服务（SerpAPI/ScrapingDog 等，约 $1–3/千次）。项目已有 `proxy_channels` 基础设施可复用。

## 4. 风控定性评估

| 路径 | 风控主体 | 风险等级 | 说明 |
|---|---|---|---|
| LinkedIn 站内搜索（登录） | LinkedIn | **高** | 商业使用限制 + 自动化检测严格，账号封禁风险；本任务未实测触发 |
| Google dork SERP 收割 | Google | **中** | 验证码级限速，可恢复；限速+代理可控；不触及 LinkedIn |
| 点击进 LinkedIn 资料页 | LinkedIn | 高（未登录直接 authwall，无收益） | 旁路模式下**不需要**点击 |

## 5. 号码质量与留号者角色构成

基于命中标题/摘要的角色观察（样本约 50 条）：

- **货代/物流**（Freight Forwarder / Logistics / FCL/LCL/AIR）：占比最高，留号最主动（"Add my Whatsapp" 直接写进 Headline）；
- **工厂/制造商销售**（factory / manufacturer / Sales Manager）：占比高，工厂 dork 下 50% 标题直含号码；
- **外贸业务员/SOHO**（外贸业务员 · Self-employed / Freelancer）：明确存在，摘要含号码+邮箱；
- **采购代理/Sourcing Agent**（China Sourcing Agent / dropshipping）：稳定存在，1,010 条子池；
- 传统外贸公司 Export Manager / International Sales：存在。

**对号码质量的提示**：货代占比偏高意味着采集后需按角色标签分层（用户目标是开发外贸客户还是找同行/货代，策略不同）；号码格式多样（`+86 138…` / `86 138…` / 带空格连字符），需归一化后走项目现有 wa_check 查号验证。

## 6. 采集可行性结论

**可行，推荐作为新渠道落地，主路径为「Google dork SERP 收割」，而非 LinkedIn 站内采集。**

- 供给侧密度：✅ 实测极高（首页 50–100% 结果直含号码，总池十万级）；
- 技术可达性：✅ 纯 HTTP 收割 SERP，不需要 LinkedIn 登录态，与现有 fetcher 框架/net 层能力完全匹配；
- 主要风险：⚠️ Google 限速（可控）；LinkedIn 站内路径不碰；
- 号码有效性：需经 wa_check 验证后分级，货代噪声需角色过滤。

## 7. 落地路径建议

1. **新增 fetcher 站点插件 `sites/serp_linkedin/`（或直接复用现有 net 层）**：输入 dork 模板列表（`site:linkedin.com/in whatsapp "+86" {role}`，role ∈ sourcing/export sales/factory/freight forwarder/manufacturer/外贸），抓取 Google SERP（HTML 即可，无需 JS），正则抽取 `\+?86[\s-]?1[3-9]\d[\d\s-]{7,12}\d` 与邮箱、标题角色。
2. **限速与代理**：单 IP ≤4–6 查询/分钟 + 随机抖动；接现有 `proxy_channels` 轮换；遇验证码退避 60s+。规模化可评估 SerpAPI。
3. **深翻收割**：每 dork 翻 `start=0…~200`（Google 单查询实际上限约前几百条），多 dork 组合扩大覆盖；按 profile URL 去重。
4. **数据流**：SERP → 号码/邮箱/角色/地区抽取 → 归一化 → 写库（复用 contacts 表结构，来源标记 `linkedin_serp`）→ wa_check 分批查号 → 按角色分层输出。
5. **不做的**：不采集需登录的 LinkedIn 站内数据、不点击 authwall 页面、不碰用户 LinkedIn 账号。
