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

1. **fetcher 新增 `facebook` 站点插件（批次类任务）**：

   > 2026-08-08 架构修订：scheduler P4/P5 已落地（docs/scheduler-architecture.md §10），subprocess 采集路径退役（`TASK_COMMANDS` 仅剩 yiwugo_search），新采集任务一律走 **BATCH_TYPES → work_items 队列 → daemon 消费者**。接入点随之改变：
   > - `cli/main.py _build_registry()` 注册 `QueueSpec(queue="crawl_fb_post", site="facebook", task=FbPostTask(), requires={"channel","browser"})`——BrowserConsumer 消费，天然获得跨站冷却填充（FB 冷却期间通道可跑 1688/mic）与 `(facebook:ip)` 身份分桶（P2 已落地，无需额外改造）；
   > - 站点插件侧需实现 Task 协议（`control/task.py`）包装 `FetchFbPost` 原子（`make_task` 目前抛 KeyError）；
   > - 平台侧走 `runner.py BATCH_TYPES` 注册（kind 类似 feeder），不再拼 CLI 起子进程；
   > - 第三方 API 路线（`FetchFbGroupPosts`，调 BD/Apify HTTPS 接口、不需要代理通道）适合 `requires={"local"}` 的无浏览器消费者（wa_check 同型）。
   - Step 1 发现：对关键词矩阵（外贸/货代/跨境电商/亚马逊卖家/china sourcing × whatsapp/微信/+86/chat.whatsapp.com）做 Google `site:facebook.com/groups` 搜索，解析出帖子 permalink，落库去重（表：`fb_posts`，字段：url、group_id、discovered_at、status）。
   - Step 2 抓取：**一律渲染抓 DOM + og**（PoC 实测修正：纯 HTTP GET 被 FB 以 TLS/HTTP 指纹识别，一律 400，拿不到任何 HTML，"便宜的免渲染 GET"不存在）。实现可选 Playwright / WebBridge / curl-impersonate（待验证）。og:description 与 DOM 正文同页取得，og 截断点之后的号码有实测增量（PoC 10 帖中 3 帖靠 DOM 多捞到 4 个号）。
   - Step 3 提取：正则集 `1[3-9]\d{9}`、`\+86[\s-]?\d{11}`、`\+?\d{7,15}`（ws 号）、`chat\.whatsapp\.com/\S+`、`wa\.me/\S+`，附带微信/TG 号入 contacts 备注。**同时抓首屏评论**（PoC 实测部分帖子评论区匿名可见，含留号，侦察时未发现的增量）。
   - Step 4 查号（分层，**不全量过 wa_check**，见 §8）。
2. **速率**：Google 查询 ≤ 1 req/3-5s、query 轮换；FB permalink 抓取 ≤ 1 req/2s、住宅出口。通道由 daemon 统一持有（单 dispatcher 消除跨进程撞通道），冷却时长由策略层输出、消费者冷却表执行（P1 模型），原子内不 sleep。
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
- 已做（2026-08-09 三期落地后更新）：发现层已换 **DDG html 端点自建**落地
  （docs/feat_2026-08-09_fb-discovery-group-feed/，fetcher 侧 FetchDdgSerp
  原子 + FbDiscoverTask + discover_fb 队列 + 平台 fb_discover 批次）；群
  feed 已接队列（FbGroupTask + crawl_fb_group + 平台 fb_group 批次）。其余
  二期项（落库 fb_posts/fb_contacts、daemon 队列 crawl_fb_post + FbPostTask、
  平台 fb_post 批次类型+前端、wa_check 双源衔接）均已落地并冒烟通过。
  Apify SERP 路线仍为非目标（自建优先）。

## 11. 附：其他渠道全景（2026-08 调研）

群帖 permalink 是本项目的选定路线，调研时同时评估了其他渠道，存档备查：

### 官方渠道（合规但受限，2026-08-07 深入调研修正）

- **Graph API**：2018 年剑桥分析事件后对第三方基本锁死，深入调研确认：读别人 Page 公开 posts/comments、搜索公开内容的路径**全部收敛到 Page Public Content Access 特性**（Advanced Access + App Review，采集用途基本不可能过审）；Post Search 2014 年已下线，oEmbed Read 2025-10 弃用。能用的只有**自己拥有/授权的 Page** 数据（`pages_show_list` + `pages_read_engagement`，Standard Access 免审）。速率限额随日活浮动（200×DAU/小时），新应用额度极低。**结论：不值得接入采集链路**，只适合自有 Page 管理。（详见 `facebook-apis/README.md`）
- **Ad Library API**：调研修正了"最干净"的初判——**商业广告只有 `ad_reached_countries` 含欧盟/EEA 国家才返回**（DSA 合规产物），中国供应商主投的美国/中东/东南亚市场拿不到；花费/曝光区间只给政治广告；token 需政府证件身份认证（中国大陆身份证常被拒）。**结论：降为低优先级补充源**（仅欧盟定向广告）。（详见 `facebook-apis/AD_LIBRARY.md`）
- **网页版广告库**（facebook.com/ads/library）：真实浏览器**匿名可搜全球全量在投广告**（含商业广告），裸 HTTP 403——与群帖 permalink 同构，可复用同一套 CloakBrowser 抓取层，是"找在投广告的中国供应商"的正确补充路线（二期候选）。
- **Meta Content Library / API**：CrowdTangle 已于 2024 年 8 月关停，替代品只面向**学术机构和非营利研究者**申请（ICPSR 审批 + 费用，仅欧盟学术 affiliation），商业用途不用考虑。

### 第三方采集服务（省事、要钱，2026-08-07 深入调研）

商业场景把账号、代理、反爬外包的方案。四家横向对比（详档：`third-party-apify.md` / `third-party-brightdata.md` / `third-party-oxylabs-decodo.md`）：

| 厂商 | FB 群帖能力 | 字段 | 1 万帖/月成本 | 免费额度 |
|---|---|---|---|---|
| **Apify** | 官方 Groups Scraper（群 URL→帖） | 结构化：permalink/正文/作者/互动数/top 评论 | ~$50（$5/1K 帖 + $29 档） | $5/月（≈1K 帖） |
| **Bright Data** | Posts by group URL 端点 | 偏薄：示例仅 7 字段且作者打码，互动数待实测 | **~$7.5**（$1.5/1K 条） | **5K 条/月免信用卡** |
| **Oxylabs** | 无 FB 解析器，通用 API 回原始 HTML | 需自己解析 | ~$49（Micro 档最低消费） | 2K 结果试用 |
| **Decodo** | 无 FB 模板（社媒 API 仅 YT/IG/Reddit/TikTok） | 需自己解析 | ~$20-50（费率不透明） | 3 天 100MB |

共同边界：**四家都只支持公开群、全部不支持登录态**（Decodo 把"不抓 post-login 内容"写进 Usage Policy）——私密群谁都补不上，第三方服务的覆盖范围与本项目自建匿名路线完全一致。

结论：**自建路线不迁移**（边际成本近零、字段自控），第三方定位为：
- **Bright Data 免费层（5K 条/月）**：~~值得实测一次群帖端点字段完整性~~ 已实测（见 §12），作灾备通道；
- **Apify**：发现层补充（Search Scraper 找 Page、Ad Library actor $0.75/1K 条）+ 字段对照基准（群帖能力已实测，见 §12）；
- **Decodo 住宅代理**（PAYG $4/GB）：自建路线代理渠道的性价比补充候选。

### 与本项目路线的关系

- 群帖 permalink 匿名抓取**零账号成本、零 API 费用**，且落在 Meta v. Bright Data（2024）判决认定的"未登录抓公开数据"安全区，是主路线。
- Ad Library API 可作为**补充线索源**（识别在投广告的中国供应商），接入成本是一个 Meta 开发者应用 + token，见 `facebook-apis/` 调研与 demo。
- 第三方服务是规模化受限时的兜底（按量付费买成功率），一期不引入。

## 12. 第三方服务实测与原子落地（2026-08-06）

对 §11 表格中免费额度最优的两家做了真实账号 + 小额付费额度验证（均无需绑卡）。

### 免费额度确认

| | Apify | Bright Data |
|---|---|---|
| 免费额度 | $5/月（≈1000 帖） | **5000 credits/月**（1 credit = 1 条记录，共享池） |
| 群帖单价 | $5/1K 帖 | **$1.5/1K 条**（便宜约 3 倍） |

### 对照实测（同群 `185879310028412` = Shenzhen Expats 2026、同限 10 帖、同时段）

- 两家返回**同一批帖子**（post_id 逐一吻合），正文**全文不截断**（优于自建路线 og:description 的 ~200 字符截断）。
- 密度一致：10 帖中 3 帖含中国手机号，去重后仅 1 个唯一号码（同一租房中介连发 3 帖）——**整群翻 feed 的打法必须跨帖去重**，唯一联系人率按 10-20% 估。
- 字段：BD 更全（38 字段：群名/群成员数/群简介/hashtags/作者主页 URL）；Apify 基础字段齐全但**官网示例的 topComments 实测未返回**（评论需单独 actor/接口，两家同）。
- 时延：Apify 同步一次调用 ~18s；BD 异步三段式 ~40s。

### 接入坑位（勿踩）

- BD 群帖发现**只能走异步 `POST /datasets/v3/trigger`**（dataset_id=`gd_lz11l67o2cb3r0lkj3`）；误用同步 `/scrape` 会报误导性错误 `Customer is not active`（账号本身正常）。
- BD 请求体是**裸数组** `[{"url":...}]`，不是部分文档示例里的 `{"input":[...]}`。
- BD 控制台查看 API key 需邮箱 6 位验证码（6 个独立输入框的 OTP 组件）。

### fetcher 原子已落地

- `fetcher/fetcher/atoms/facebook_group.py`：`FetchFbGroupPosts`（name=`fetch_fb_group_posts`），双 provider（默认 brightdata），输入群 URL + limit，输出归一化帖子 + 复用 `parse_post` 的四桶分桶（跨帖按号码去重）。Outcome 口径：402/429→BLOCKED（额度/限流）、401/403→FATAL、0 帖→EMPTY、轮询中断→SKIPPED。只用标准库 urllib；key 走 `api_key` 参数或环境变量 `BRIGHTDATA_API_KEY` / `APIFY_TOKEN`。
- 测试：`fetcher/tests/test_facebook_group.py` 17 例（mock HTTP，样本取自本次实测）。
- 真机验证：两家各采 5 帖均 `ok`，结果一致；花费 BD 5 credits + Apify $0.025，均在免费额度内。
- 已做（2026-08-09 三期落地后更新）：二期接入已完成——runner BATCH_TYPES
  注册 fb_post、daemon 队列 crawl_fb_post、落库 fb_posts/fb_contacts、平台
  前端 fb_post 任务类型；三期发现层已自建落地（DDG SERP，见 §10）。两家
  key 沿用环境变量（本期未入 DB，非目标保持，见 SPEC 非目标清单）。

## 附：实测原始数据

- 10 帖样本明细存于侦察会话 `/tmp/fb_posts.json`（临时文件，未入项目目录）。
- 61 个去重群/帖 URL 存于侦察会话 `/tmp/fb_links.txt`（临时文件）。
