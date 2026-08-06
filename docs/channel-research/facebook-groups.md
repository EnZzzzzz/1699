# 渠道侦察：Facebook 群组 — 中国外贸从业者 WhatsApp/手机号采集

> 侦察时间：2026-05（通过 Kimi WebBridge 控制真实浏览器实测）
> 侦察方式：纯只读，未发帖/评论/加群/点击任何互动按钮
> 会话状态：**Facebook 未登录**，全程按匿名可见内容评估

## 1. 登录态结论

- 用户浏览器**未登录 Facebook**（首页、`m.facebook.com`、`mbasic.facebook.com` 均落到登录页）。
- 按侦察约定不尝试登录，以下所有实测均为**匿名（未登录）状态**下的结果。
- 这反而是一个重要发现：核心采集路径**不需要登录态**（见 §4）。

## 2. 群组生态规模（Google 索引量化）

匿名状态下 Facebook 自己的群搜索（`facebook.com/search/groups/?q=外贸`）返回 "Not Found"，群组主页直接 302 到登录页 —— **FB 站内的群发现与群浏览对匿名用户完全关闭**。

但 Google 对 FB 群帖的索引量巨大，足以作为群/帖发现层：

| Google 查询 | 结果量级 |
|---|---|
| `site:facebook.com/groups 外贸 whatsapp` | ~488,000 |
| `site:facebook.com/groups 跨境电商 whatsapp` | ~911,000 |
| `site:facebook.com/groups china sourcing whatsapp` | ~896,000 |
| `site:facebook.com/groups "+86" 外贸` | ~165,000 |
| `site:facebook.com/groups chat.whatsapp.com 外贸` | ~140,000 |
| `site:facebook.com/groups 货代 微信` | ~109,000 |
| `site:facebook.com/groups 亚马逊卖家 微信` | ~67,100 |

（Google 估算值有水分，去重后真实帖子数会低一个量级，但万级有效帖子的判断是保守的。）

实测出现的群组（从帖子标题还原群名）：

- `WhatsApp群发（外贸资源交流群）`— 直接就是外贸资源交换群
- `Shenzhen Expats 2026` — 货代在外籍人群里揽客
- `中国毛绒玩具批发`、`五金，汽配外贸资源拓客` — 行业货源群
- `外贸电商`、`China Export &Import Best supplier 中国贸易供应链`
- `Solar Water Pump Africa`、`China to Pakistan Air Cargo service`、`Freight Forwarder - Sea&air shipping` — 海外买家群，中国货代/服务商渗透其中

公开/私密比例：匿名态无法直接查看群属性，但从"帖子能被 Google 索引且匿名可读"推断，被索引的帖子绝大多数来自**公开群**（私密群帖子不会进 Google）。

## 3. 号码/联系方式密度实测（核心数据）

从 Google 结果中取 **10 个群帖 permalink 匿名实测**：

| 指标 | 命中 |
|---|---|
| 帖子匿名可打开（不跳登录页） | **10/10** |
| 含明文中国手机号（`1[3-9]\d{9}` 或 `+86`） | **6/10** |
| 含任意可触达联系方式（手机号/微信号/TG/ws 号） | **9/10** |
| 含 `chat.whatsapp.com` 邀请链接 | 0/10（本样本；Google 结果页正文中有命中，且 og:description 有截断，见 §4 限制） |

脱敏样例（均来自匿名可读的公开帖）：

- 货代揽客：「需要货代资源询价的工厂老板和外贸商们可以加我微信或者 WhatsApp…微信：181****1701 WhatsApp：+86181****1701」（深圳货代，发在 Shenzhen Expats 群）
- 货代揽客：「寻找非洲进口到中国的货代 微信 138****0524」（发在 China to Pakistan Air Cargo 群）
- 外贸获客软件商：「海外获客、海关数据、邮件 WhatsApp 营销…免费体验：131****6299」
- 外贸 CRM 厂商：「孚盟 MX…电话☎微信：132****1264」
- 获客服务商用美国虚拟号：「ws：+1 562****681」（中国人用 TextNow 类号码，查号时可识别为非 +86）
- 微信号内嵌手机号：「有没有货代微信群，拉我一下 V136****3989」

**角色构成判断**：留号的约 7-8 成是**中国供给侧**（货代、获客软件商、sourcing agent、工厂），目标受众是同行或海外买家；约 2-3 成是海外买家/华人买家反向找中国货代（如「我想找一家中国货代长期合作」）。中国号密度符合预期，海外买家号可作为副产出但需用号段/查号结果区分。

## 4. 匿名与移动版可用性（采集路径关键）

| 路径 | 匿名可用性 | 说明 |
|---|---|---|
| FB 群搜索页 `/search/groups/` | ❌ | 返回 Not Found |
| 群组主页 `/groups/{id}/` | ❌ | 302 → 登录页 |
| **帖子 permalink `/groups/{gid}/posts/{pid}/`** | ✅ | **不跳转**，正文完整在 DOM 中（登录弹窗只是遮罩） |
| 帖子 `og:description` meta | ✅ | 免渲染即可取，但**截断在 ~200 字符**；发帖人通常把联系方式放开头，命中率仍高 |
| `m.facebook.com` 帖子 | ✅ | 302 到 www 同名帖子页，正文同样可读 |
| `mbasic.facebook.com` | ❌ | 302 → `login.php`，匿名完全不可用 |

**结论：可用采集面 = "Google 发现帖子 URL → 匿名抓 permalink 页 → 从 og:description（免 JS）或 DOM 正文（需渲染）正则提号"。全程无需登录、无需加群、无需翻群 feed。**

限制：
- og:description 截断导致帖尾的 `chat.whatsapp.com` 长链接可能丢失；要拿全文需渲染页面读 DOM（无头浏览器或 WebBridge 式真实浏览器）。
- 无登录态无法做群内搜索、无法看评论（评论里也有留号，但属增量）。

## 5. 反爬/风控观察

- 本次侦察约 35 次页面导航（FB + Google），未触发验证码/频率限制。但样本小，不能外推。
- 定性评估：
  - **匿名抓 permalink（低并发、带正常 UA）**：风险低，等同 Googlebot 看到的公开内容；主要风险是 IP 级速率限制（FB 对数据中心 IP 敏感，住宅 IP + 限速可缓解）。
  - **Google 发现层**：批量 `site:` 查询会触发 Google 人机验证，需低速率/多 query 轮换/缓存结果。
  - **登录态规模化抓取群 feed/评论**：FB 对自动化行为（图谱 API 外的大量翻页、固定节奏滚动、新注册号加群）封号率高，外贸圈 FB 封号是常态；**不建议作为主路径**。
  - 号码提好后经 `wa_check` 查号注册态，与平台现有能力直接衔接，无新增风控面。

## 6. 采集可行性结论

**可行，且比预期更好：不需要登录 Facebook。**

- 供给量：Google 索引的相关群帖量级在万级以上，中国外贸从业者（尤其货代、获客服务商）主动留号行为密集且持续。
- 密度：匿名样本 60% 帖子含明文中国手机号，90% 含某种联系方式。
- 成本：发现层（Google）+ 抓取层（匿名 permalink）都不需要 FB 账号，规避了 FB 封号这个最大风险点。
- 短板：增量发现依赖 Google 索引延迟；og 截断丢部分尾部信息；无法按群系统化穷尽（除非登录）。

## 7. 落地路径建议

1. **fetcher 新增 `facebook` 站点插件（subprocess 类任务）**：
   - Step 1 发现：对关键词矩阵（外贸/货代/跨境电商/亚马逊卖家/china sourcing × whatsapp/微信/+86/chat.whatsapp.com）做 Google `site:facebook.com/groups` 搜索，解析出帖子 permalink，落库去重（表：`fb_posts`，字段：url、group_id、discovered_at、status）。
   - Step 2 抓取：**一律渲染抓 DOM + og**（PoC 实测修正：纯 HTTP GET 被 FB 以 TLS/HTTP 指纹识别，一律 400，拿不到任何 HTML，"便宜的免渲染 GET"不存在）。实现可选 Playwright / WebBridge / curl-impersonate（待验证）。og:description 与 DOM 正文同页取得，og 截断点之后的号码有实测增量（PoC 10 帖中 3 帖靠 DOM 多捞到 4 个号）。
   - Step 3 提取：正则集 `1[3-9]\d{9}`、`\+86[\s-]?\d{11}`、`\+?\d{7,15}`（ws 号）、`chat\.whatsapp\.com/\S+`、`wa\.me/\S+`，附带微信/TG 号入 contacts 备注。**同时抓首屏评论**（PoC 实测部分帖子评论区匿名可见，含留号，侦察时未发现的增量）。
   - Step 4 查号（分层，**不全量过 wa_check**，见 §8）。
2. **速率**：Google 查询 ≤ 1 req/3-5s、query 轮换；FB permalink 抓取 ≤ 1 req/2s、住宅出口。ProxyChannel 直接复用现有 `proxy_channels` 表。
3. **角色区分**：`+86`/`1[3-9]` 号标记为「中国供给侧」（主目标）；其他国际号标记「海外买家」入独立分桶，暂不查号。
4. **不建议**：登录态批量进群翻 feed（封号风险高、收益边际低）；mbasic 路径（匿名已死）。
5. 后续可选增量：若用户日后登录 FB，可加「群 feed 评论扫描」作为二期，但不阻塞一期。

## 8. 查号分层策略（2026-08 PoC 后修订）

wa_check 走 WhatsApp 协议、有封号成本且吞吐受风控节奏限制，是链路最贵资源；FB 帖中大量号码是发帖人**自声明的 WhatsApp 联系方式**，无需协议验证。分层如下：

| 桶 | 判定规则 | 处理 |
|---|---|---|
| 自声明 WA | `wa.me/<号>`、号码紧邻 "WhatsApp/ws" 标签、微信与 WA 同号双标 | 标记 `wa_source='declared'`，**不查** |
| 群组线索 | `chat.whatsapp.com/...` 邀请链接 | 非号码，独立入桶，不查 |
| 不确定 | 裸手机号、仅标微信的号 | **进 wa_check 队列** |
| 海外号 | 非 +86 国际号 | 独立分桶，暂缓查号 |

配套动作：

- **抽样校准**：从「自声明 WA」桶随机抽 5-10% 过 wa_check，量化自声明与实际注册的一致率；低于 ~80% 时下调信任级别。
  首个数据点（2026-08-06，10 号小样本，账号 xiaohao-2）：自声明桶 **2/2 已注册**；不确定桶 **3/8 已注册**（其中 2 个仅标微信的号实际已注册 WA）——不确定桶"查了有增量、不查会浪费一半触达"的判断成立。
- **懒验证**：自声明号码若日后用于群发/营销，使用前再补一次 wa_check 终验。
- **数据模型**：`wa_registered` 三态（1/0/NULL）塞不下"自声明未验证"，需经 `app.db.migrate()` 加 `wa_source` 列（`'declared' | 'checked'`）区分协议验证与帖子自述。
- **已知缺陷**：`normalize_numbers(default_cc="86")` 会把 11 位 1 开头的**国际号**误判为中国号补 86 前缀（实测美国虚拟号 `+15623147681` → `8615623147681`）。提取阶段应先按显式国家码/上下文标记号码归属国，非 +86 号不带 default_cc 走规范化。

## 9. PoC 实测记录（2026-08-06，WebBridge 真实浏览器）

对侦察基线 10 帖全量重抓（脚本/结果：会话 `/tmp/fb_wb_poc.py`、`/tmp/fb_poc_results.json`）：

- 纯 HTTP（urllib/curl，带浏览器 UA）直连 permalink **全部 400**，TLS/HTTP 指纹拦截，HTML 都拿不到 → 抓取层必须真实浏览器或指纹伪造客户端。
- 真实浏览器匿名抓 **10/10 成功**（2 帖首次 30s 加载超时，重试即成功），og:description 与基线 100% 一致，基线手机号零漏提。
- DOM 全文增量：3 帖在 og 截断点后多捞出 4 个手机号。
- 新发现：**部分帖子首屏评论匿名可见**（样本帖 9 带出 15 条评论，内含留号），原 §4「无法看评论」需修正为「首屏评论部分可见，翻页加载更多需登录」。
- 12 次导航住宅 IP 未触发验证码/限速，与 §5 低风险判断一致。

## 10. 一期原子能力已落地（2026-08-06）

- `fetcher/fetcher/sites/facebook/`：站点插件（特征表 features.py + 提取纯函数 post.py），`parse_post(og_desc, body_text)` 输出 §8 四桶分好类的联系方式（declared_wa / cn_uncertain / overseas / 群邀请链接，另附 wechat_ids / tg_handles）。
- `fetcher/fetcher/atoms/facebook.py`：`FetchFbPost` 原子（name=`fetch_fb_post`），复用 ctx.page 渲染抓 permalink，登录墙/频率限制 → BLOCKED，帖子删除 → EMPTY，导航超时 → NET_ERROR。
- 测试：`fetcher/tests/test_facebook.py` 20 例（含 PoC 真实样本与误标陷阱：产品名里的 WhatsApp、号码后换行+点赞计数、美国 11 位 1 开头号不补 86）。
- 号码口径：中国号存裸 11 位（86 由 wa 链路补）；国际号保留原国家码纯数字。
- **真机验证**（CloakBrowser 无头直连，10 基线帖全量）：**10/10 Outcome.OK**，og 层号码 8/8 全对、分桶全部正确（双标帖归 declared_wa、+86 国际格式去码入 cn_uncertain、产品名 WhatsApp 零误标）。
- **评论增量的局限**：WebBridge（真实 Chrome 窗口）里帖 8/9/10 评论区多捞到 4 个号，但 CloakBrowser 无头匿名会话两轮（含滚动触发懒加载）均未渲染出这些评论——评论是否匿名渲染**随会话/客户端随机**，不能作为稳定采集面，只能算"碰上就收"的机会增量。稳定采集面 = og:description + 帖子正文。
- 未做：Google 发现层、控制层任务/CLI、落库（`fb_posts` 表）、平台任务类型接入——均属二期编排工作。

## 11. 附：其他渠道全景（2026-08 调研）

群帖 permalink 是本项目的选定路线，调研时同时评估了其他渠道，存档备查：

### 官方渠道（合规但受限，2026-08-07 深入调研修正）

- **Graph API**：2018 年剑桥分析事件后对第三方基本锁死，深入调研确认：读别人 Page 公开 posts/comments、搜索公开内容的路径**全部收敛到 Page Public Content Access 特性**（Advanced Access + App Review，采集用途基本不可能过审）；Post Search 2014 年已下线，oEmbed Read 2025-10 弃用。能用的只有**自己拥有/授权的 Page** 数据（`pages_show_list` + `pages_read_engagement`，Standard Access 免审）。速率限额随日活浮动（200×DAU/小时），新应用额度极低。**结论：不值得接入采集链路**，只适合自有 Page 管理。（详见 `facebook-apis/README.md`）
- **Ad Library API**：调研修正了"最干净"的初判——**商业广告只有 `ad_reached_countries` 含欧盟/EEA 国家才返回**（DSA 合规产物），中国供应商主投的美国/中东/东南亚市场拿不到；花费/曝光区间只给政治广告；token 需政府证件身份认证（中国大陆身份证常被拒）。**结论：降为低优先级补充源**（仅欧盟定向广告）。（详见 `facebook-apis/AD_LIBRARY.md`）
- **网页版广告库**（facebook.com/ads/library）：真实浏览器**匿名可搜全球全量在投广告**（含商业广告），裸 HTTP 403——与群帖 permalink 同构，可复用同一套 CloakBrowser 抓取层，是"找在投广告的中国供应商"的正确补充路线（二期候选）。
- **Meta Content Library / API**：CrowdTangle 已于 2024 年 8 月关停，替代品只面向**学术机构和非营利研究者**申请（ICPSR 审批 + 费用，仅欧盟学术 affiliation），商业用途不用考虑。

### 第三方采集服务（省事、要钱）

商业场景最现实的方案，把账号、代理、反爬都外包：

- **Apify**：现成的 Facebook Pages/Posts/Comments/Groups/Ads Scraper 演员（actor），按量计费，直接 API 调用返回 JSON。
- **Bright Data / Oxylabs / Decodo**：Facebook 专用 Scraper API + 住宅代理池。Bright Data 自称成功率 98%+（[Best Facebook Scrapers 2026](https://brightdata.com/blog/web-data/best-facebook-scrapers)）。

### 与本项目路线的关系

- 群帖 permalink 匿名抓取**零账号成本、零 API 费用**，且落在 Meta v. Bright Data（2024）判决认定的"未登录抓公开数据"安全区，是主路线。
- Ad Library API 可作为**补充线索源**（识别在投广告的中国供应商），接入成本是一个 Meta 开发者应用 + token，见 `facebook-apis/` 调研与 demo。
- 第三方服务是规模化受限时的兜底（按量付费买成功率），一期不引入。

## 附：实测原始数据

- 10 帖样本明细存于侦察会话 `/tmp/fb_posts.json`（临时文件，未入项目目录）。
- 61 个去重群/帖 URL 存于侦察会话 `/tmp/fb_links.txt`（临时文件）。
