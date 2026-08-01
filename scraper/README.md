# 一些爬虫反爬经验

一般来说，这种校验 cookies 里面的 x5sec 参数（成功绕过阿里滑块，即可获取），与 ip 质量无关
业务侧保持合法会话链路一致，Cookie、x5sec、UA、Referer、访问节奏和出口 IP 不要频繁错配，降低并发和频率。

## 代理与 Cookie 管理（1688）

- 直连模式的 Cookie 是本机浏览器种下的，出口 IP = 本机 IP；一旦换住宅代理出口，Cookie 与 IP 错配容易触发 x5sec 风控。
- 因此 Cookie 统一存 SQLite（.cache/1688.db 的 cookies 表），按出口 IP（identity）隔离：直连记 `direct`，代理模式记实际出口 IP，并记录每个 Cookie 的过期时间 `expires`，加载时自动剔除已过期的。
- 首次在代理下运行加 `--proxy --headed`，在代理出口下登录/过滑块；脚本退出时自动把浏览器里的最新 Cookie（含新 x5sec）写回该 IP 名下，之后同一出口 IP 直接复用。
- `.cache/cookies_1688.json` 只作为直连模式首次启动的种子导入一次；代理模式的新出口 IP 不播种（见下条）。
- 匿名 ≠ 无身份：1688 会给未登录访客签发 `cookie2` / `t` / `cna` / `_tb_token_` 等匿名身份标识。把它们跨 IP 复制，就是「同一访客同时从多个 IP 出现」的 Cookie 重放特征，多 worker 并发时成倍放大，比访问频率更容易触发风控。因此代理模式下新出口 IP 以空会话启动，由 warmup 访问首页时让站点为当前出口现场签发一套全新的匿名身份；同一出口 IP 复访才复用其名下的 Cookie（含 x5sec）。
- 青果动态长效代理的出口 IP 每 30 分钟自动轮换：换 IP 后库里没有该 IP 的 Cookie，需重新过一次验证，这是产品特性，不要强行复用旧 IP 的 Cookie。
