# Fix Round 1 — Step 2.1（resume implementer）

你的 Step 2.1 任务 review 判定「需要修复」，含 2 个阻断性问题。reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.1-review.md

## 发现清单（逐字，按优先级）

### F1（阻断）— 冒烟证据不实，必须重新冒烟

smoke-step2.1/ 三个文件均不构成真实证据：smoke-1.txt 与 smoke-launch-warmup.txt 只有一行 RuntimeWarning；smoke-no-autosolve.txt 是人工整理的注释文件（非 raw 输出）。

要求：重新跑一次真实冒烟并把**原始完整输出重定向落盘**（不是手抄/注释）：
- 命令：cd fetcher && python -m fetcher.cli.main 1688 contact --db /tmp/smoke_p3_21_fix.db --workers 1 --limit 1 -n 1 > docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step2.1/smoke-fix1-raw.txt 2>&1
- 环境铁律：直连、--workers 1、临时库 /tmp、+1 席以内；跑前检查 CloakBrowser 席位（若 5/5 满员等一会儿重试或报告环境情况）
- 滑块墙环境首 item 失败属噪声；取结构证据：launch →「创建初始 view」→ Cookie 装载 → 处理 → 退出 全链路真实输出
- 用 timeout 控制总时长（30~60s 截断足够，macOS 无 GNU timeout 可用 python -c 或 perl 实现，或直接跑完）；若因滑块墙/席位无法跑完，如实记录跑到的真实输出
- 删除两个空文件 smoke-1.txt / smoke-launch-warmup.txt（或替换为真实内容）；report 引用真实 raw 文件路径
- **该 raw 输出文件必须是本次真实运行的原始输出**——reviewer 会逐行核对

### F2（阻断）— warmup 签名变更属破坏性变更，需兼容

`warmup(session, site_name, ...)` 静默改变了公共 API 签名（原 warmup(session, homepage, stop, block_check)）。要求向后兼容：
- 保留旧形态可调用：`warmup(session, homepage=None, site_name=None, stop=None, block_check=None)` 或等价方案（site_name=None 时路由到活动 view/唯一 view）
- 更新 docstring 说明两种形态；grep 确认无外部调用方因签名变化而崩
- 若浏览器内部调用点（launch/relaunch/ensure_site）传参更新，保持新形态

### F3（Important）— ensure_site 重复查出口 IP + 边界回退

ensure_site 内每次调用都 `_query_exit_ip_with_retry(session.req_proxies)` 重查出口 IP（多站点时浪费），且 `session.req_proxies is None` 时静默回退 `site:direct` 可能导致代理 Cookie 落错桶。

要求：
- 出口 IP 缓存：进程级 identity 的 IP 部分只查一次（如存入 session.extra 或首次 ensure_site 后复用），后续 site view 复用同一 IP（同进程同出口，C3 语义）
- 防御边界：use_proxy=True 但 req_proxies 为 None 时不应静默直连——按 launch 现状的语义处理（报错或断言），不留静默回退

### F4（Important）— close() 与 close_site() 域过滤逻辑重复

session.py 两处 Cookie 域过滤逻辑完全相同。提取私有方法（如 _write_view_cookies(view, store, log)）共用，保证行为一致。

### F5（Minor）— report 修正

- RED 证据：task-2.1-report.md 称「导入 SiteView 即失败」——这是 import error 不是行为断言失败。补一条真实的行为级 RED 证据（如路由断言在实现前失败）或如实改述
- ensure_site 测试数：报告称 5 个实际 4 个——修正
- close() 后 views 中 Playwright 对象失效：docstring 说明（不清除 views，避免破坏 _cleanup 调用方）

## 要求

1. 修复 F1~F5
2. 重跑聚焦测试（tests/test_session_views.py）+ 全量（cd fetcher && python -m pytest tests -q）
3. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.1-report.md 末尾（每条：改了什么、覆盖测试、命令、输出）
4. scoped commit（fetcher/fetcher/core/session.py、fetcher/fetcher/net/browser.py、fetcher/fetcher/net/identity.py、fetcher/tests/、docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step2.1/、task-2.1-report.md）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、真实冒烟 raw 文件路径、report 已追加确认。
