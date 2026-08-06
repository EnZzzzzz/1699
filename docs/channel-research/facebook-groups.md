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
   - Step 2 抓取：对 permalink 发匿名 GET，优先解析 `og:description`（便宜）；命中 `wa\.me|chat\.whatsapp` 或 desc 被截断时升级为渲染抓取（复用 WebBridge 或轻量无头）取 DOM 全文。
   - Step 3 提取：正则集 `1[3-9]\d{9}`、`\+86[\s-]?\d{11}`、`\+?\d{7,15}`（ws 号）、`chat\.whatsapp\.com/\S+`、`wa\.me/\S+`，附带微信/TG 号入 contacts 备注。
   - Step 4 查号：中国号走现有 `wa_check` 进程内执行器验证 WhatsApp 注册态。
2. **速率**：Google 查询 ≤ 1 req/3-5s、query 轮换；FB permalink 抓取 ≤ 1 req/2s、住宅出口。ProxyChannel 直接复用现有 `proxy_channels` 表。
3. **角色区分**：`+86`/`1[3-9]` 号标记为「中国供给侧」（主目标）；其他国际号标记「海外买家」入独立分桶，暂不查号。
4. **不建议**：登录态批量进群翻 feed（封号风险高、收益边际低）；mbasic 路径（匿名已死）。
5. 后续可选增量：若用户日后登录 FB，可加「群 feed 评论扫描」作为二期，但不阻塞一期。

## 附：实测原始数据

- 10 帖样本明细存于侦察会话 `/tmp/fb_posts.json`（临时文件，未入项目目录）。
- 61 个去重群/帖 URL 存于侦察会话 `/tmp/fb_links.txt`（临时文件）。
