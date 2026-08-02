# 一些爬虫反爬经验

一般来说，这种校验 cookies 里面的 x5sec 参数（成功绕过阿里滑块，即可获取），与 ip 质量无关
业务侧保持合法会话链路一致，Cookie、x5sec、UA、Referer、访问节奏和出口 IP 不要频繁错配，降低并发和频率。

## 最核心的一条教训（2026-08 实证）

**跨 IP 复制 Cookie 是最强的风控信号，比访问频率危险得多。**

实证：多 worker 改造后触发率暴增，查库发现 cookies 表已累积 134 个出口 IP，
而它们的 `cookie2` / `_tb_token_` / `sgcookie` 值完全相同（md5 逐一比对验证）。
在 1688 风控眼里：同一访客、同一安全凭证，在 134 个住宅 IP 间跳跃——教科书式
爬虫特征。同一轮实测还证明频率不是主因：Cookie 错配的 IP 访问第一家店铺就中
滑块，Cookie 配套的 IP 以同样节奏连采 2-3 家才触发。

推论：
- 任何「按 IP 签发」的 Cookie（x5sec/sgcookie/isg/sg）都不能跨 IP 复制；
- 匿名身份标识（cookie2/t/cna/_tb_token_）同样不能——不登录站点也用它
  们识别「同一个访客」，多 worker 并发时「同一访客多 IP 并发」的重放特征
  成倍放大；
- 因此代理模式新出口 IP **完全不播种**，空会话启动 + 首页预热（见下）。

## 代理与 Cookie 管理（1688）

- 直连模式的 Cookie 是本机浏览器种下的，出口 IP = 本机 IP；一旦换住宅代理出口，Cookie 与 IP 错配容易触发 x5sec 风控。
- Cookie 统一存 SQLite（.cache/1688.db 的 cookies 表），按出口 IP（identity）隔离：直连记 `direct`，代理模式记实际出口 IP，并记录每个 Cookie 的过期时间 `expires`，加载时自动剔除已过期的。
- 首次在代理下运行加 `--proxy --headed`，在代理出口下登录/过滑块；脚本退出时自动把浏览器里的最新 Cookie（含新 x5sec）写回该 IP 名下，之后同一出口 IP 直接复用。
- `.cache/cookies_1688.json` 只作为直连模式首次启动的种子导入一次；代理模式的新出口 IP 不播种（见下条）。
- 匿名 ≠ 无身份：1688 会给未登录访客签发 `cookie2` / `t` / `cna` / `_tb_token_` 等匿名身份标识。把它们跨 IP 复制，就是「同一访客同时从多个 IP 出现」的 Cookie 重放特征，多 worker 并发时成倍放大，比访问频率更容易触发风控。因此代理模式下新出口 IP 以空会话启动，由 warmup 访问首页时让站点为当前出口现场签发一套全新的匿名身份；同一出口 IP 复访才复用其名下的 Cookie（含 x5sec）。
- **首页预热（warmup）是绑定的关键一步**：launch_browser 启动后先访问一次首页，站点按「当前 IP + 当前会话」现场签发 isg/sgcookie/cna 等并立即回写该 IP 名下。任何时刻出现新 IP（首次启动、IP 轮换重启、风控修复重启），第一件事都是预热。顺带好处：首个店铺请求带上真实的站内浏览轨迹——直接深链 contactinfo.htm 而无首页访问记录本身也是爬虫特征。
- **登录态有生命周期，且与风控 Cookie 是两层东西**：`cookie2` / `_tb_token_` 有效期约 5 天（实测 7/30 导出 → 8/4 过期）。过滑块只能刷新风控 Cookie（x5sec 等），**不能续登录态**；到期前要用 `--headed` 跑一次并在窗口里重新登录，新登录态随退出写回库。
- 青果动态长效代理的出口 IP 每 30 分钟自动轮换：换 IP 后库里没有该 IP 的 Cookie，需重新过一次验证，这是产品特性，不要强行复用旧 IP 的 Cookie。

## 风控处置策略：先休息，再修复，最后才放弃（1688）

早期版本「一遇风控就换通道换 IP」，实测效果差：新 IP 没有配套 Cookie，
换过去触发更快。现在的三级处置（contact_fetcher / shop_crawler 一致）：

1. **第 1 次疑似风控 → 不换 IP，当前 IP 休息 10-15 分钟（随机）后重试**。
   滑块级风控有冷却期，实测同一 IP 被拦截 12 分钟后原样恢复。
   headed 模式下优先等人工在窗口里手动过滑块（脚本每 5-15s 检测当前页
   是否脱离拦截态，不发新请求），过了立即继续并把新 x5sec 写回该 IP。
2. **第 2 次 → 修复：重启浏览器拿新出口 IP**。青果 IP 时效 30 分钟，
   第一次休息 10-15 分钟 + 重试耗时，到第二次休息时旧 IP 通常已自然
   过期轮换，重启即得新 IP，预热自动配好新 Cookie。若发现 IP 未轮换，
   再等一轮让它过期，不要强行复用。
3. **第 3 次 → 放弃**：单店标记 failed 跳过 / 采集任务主动终止，
   避免反复请求加重风控。连续失败达上限（默认 5）判定整体被风控，
   立即中止整个任务。

配套纪律：
- **一 worker 一通道，终身绑定，不要切通道**。通道数 = 购买的并发配额
  （青果 5 通道 ↔ CloakBrowser 5 席位），切通道就是抢别的 worker 的
  出口，互相串号。通道池 acquire() 轮询分配即天然互斥。
- **出口 IP 查询失败不要用伪 identity**（如 `qingguo:host`）：Cookie
  会绑到永远查不到 IP 的假对象上，真实 Cookie 无法沉淀。查询失败应
  短重试后抛错，由上层退避重试（曾因此产生 650 行孤儿 Cookie）。

## 异常三分类：浏览器死亡 ≠ 网络故障 ≠ 风控（重要）

「页面加载失败」不是一个筐。早期版本把所有非 net::ERR 异常都当风控，
曾在死浏览器上空等 10-15 分钟重试。现在严格分三类：

1. **浏览器进程死亡**（TargetClosedError / "has been closed" /
   Target crashed / 连接断开）：多是 CloakBrowser 会话被服务端终止
   （席位满、租约被顶掉）。**与风控完全无关**，直接重启浏览器重试，
   不计入风控计数。
2. **网络/代理层故障**（ERR_TUNNEL_CONNECTION_FAILED、连接重置、DNS
   失败等 net::ERR）：请求根本没到目标站，换不了目标站的风控状态。
   原通道重启 + 退避重试，不计入风控计数。
3. **疑似风控**（拦截页 URL 特征、验证关键词、页面异常空白）：才走
   上面「先休息后修复」的三级流程。

**goto 超时要先探活再定性**：`Page.goto: Timeout` 既可能是拦截页挂起
（浏览器活着），也可能是浏览器已死的症状。先查
`browser.is_connected()` + `page.is_closed()`，死了按第 1 类处理；
活着再记录当前停留 URL 辅助鉴别（拦截页挂起时 URL 停留在目标页，
真风控跳转时 URL 已变）。

## CloakBrowser 会话席位管理（多实例并发的前提）

- **席位是服务端租约，不是本地进程数**。实证：本地只剩 2 个浏览器
  进程时服务端仍显示 5/5 占用——上次异常退出（kill、直接关终端）
  的租约要 ~10 分钟才过期，期间新 launch 会被拒绝（Pro 二进制退出码
  76）或启动后被服务端关闭（不透明的 TargetClosedError）。
- **launch 前主动等席位**：`wait_for_license_seat()` 轮询
  `get_active_session_count()`，满员就等残留租约释放（free=1 席，
  solo=5 席），比 launch 失败再处理干净得多。已内置在 launch_browser。
- **优雅退出是义务**：SIGINT（Ctrl+C）/SIGTERM/SIGHUP（关终端窗口）
  都要走到浏览器 close，租约立即释放。`kill -9` 无法捕获，尽量避免；
  否则等 ~10 分钟租约自然过期。
- **账号切换用 CLI**：`python -m cloakbrowser login <key>` 保存到
  `~/.cloakbrowser/license.key`（曾踩坑：本地登录着旧 free key，
  脚本却按 solo 5 并发设计）。代码内优先级：launch 参数 >
  环境变量 `CLOAKBROWSER_LICENSE_KEY` > 默认 key 文件 >
  `.cache/config.json`（项目自定义兜底）。`python -m cloakbrowser info`
  可诊断当前登录的套餐。

## 青果住宅代理的特性与纪律

- 出口 IP 每 30 分钟自动轮换（产品特性）：意味着任何「IP ↔ Cookie」
  绑定都是短命的，不要试图长期维护；每次轮换 = 预热重建一次即可。
- 每轮/每店采集前检查出口 IP（经通道查 ipinfo.io）：与 identity
  不一致即重启浏览器重绑，不要等到请求失败才发现。
- 通道入口（tunpool-*.qg.net:port）缓存于 .cache/qingguo_tunnel.json，
  池解析顺序：缓存 → /query 在用通道 → /get 补齐。

## 设备指纹与 UA（1688）

- 不要硬编码 UA：CloakBrowser 二进制按自身 Chromium 版本自报 UA 与 UA-CH（sec-ch-ua），硬编码不一致的版本号（如二进制 145 报 Chrome/150）会造成 UA / UA-CH / JS 特征错配，是"UA 被篡改"的典型信号，抬高每个会话的基础风险分。
- 设备指纹按出口 IP 稳定生成（--fingerprint 种子取 identity 哈希）：同一 IP 重启浏览器指纹不变，与该 IP 名下按设备签发的 Cookie（cna 等）配套；不同 IP 指纹不同，避免跨 IP 设备关联。默认的每次随机种子会造成"同 IP 设备突变"。

## 风控分级（1688）

- 滑块（x5sec/punish 页）：低级风控，原地休息或 headed 手动拖动可恢复，过后保存新 x5sec。
- 强制跳登录（login.1688.com）：高级风控，该 IP/会话已被高风险标记，原地休息无意义，直接换 IP；遭遇记录在 1688.db 的 ip_events 表（launch / block_slider / block_login），可用于评估代理 IP 质量和发现重复发放的 IP。

## 工程经验（多 worker 终端脚本）

- 固定 N 行状态板（每 worker 一行）+ 重要事件滚动日志，比满屏 print
  好用得多；共享库（common.py）内部 print 经线程标签路由到对应
  worker 的状态行/日志。
- **状态行按终端显示宽度截断，中文（CJK）按 2 列算**；按 Python 字符
  数截断会超宽换行，ANSI 光标定位全部错位（表现为多行内容挤一行）。
- 所有长等待用可中断的倒计时（stop.wait + 每秒刷新），Ctrl+C 随时
  打断；不要 time.sleep 长睡。
- 进度全部落库（shops.status / category_progress），任何中断都能
  断点续爬；中断残留的 in_progress 下次启动自动放回 pending。
