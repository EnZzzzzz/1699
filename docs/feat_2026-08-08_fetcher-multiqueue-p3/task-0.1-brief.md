# Task 0.1 Brief — CloakBrowser 多 context 席位计数实测（P3-0 spike）

> 来源：PLAN.md P3-0 Step 0.1 全文 + SPEC §4 C1。本文件是本次任务的唯一需求来源。

## 目标

实测 CloakBrowser 会话席位按「浏览器二进制进程」还是按「BrowserContext」计数（SPEC §4 C1 假设）。
结论直接决定 P3-2 浏览器层「一进程多 context 只占 1 席」方案是否成立，也是 P3-2 动工的硬准入。

## 步骤（严格按顺序）

写脚本 `/tmp/spike_cloak_multicontext.py`，完成以下序列，每次计数后打印一行原始值：

1. **baseline**：`get_active_session_count(key)` 读当前会话数（记为 n0）
2. **launch**：headless 直连 launch 一个 CloakBrowser（**不加 proxy**），记计数 n1 —— 预期 n1 = n0 + 1
3. **第二个 context**：`browser.new_context(locale="zh-CN")`，记计数 n2 —— 预期 n2 = n1（多 context 不占新席位）
4. **第二个 context 可用性**：`ctx2.new_page()` 然后 `page.goto("about:blank")` 成功，记计数 n3 —— 预期 n3 = n2
5. **close**：`browser.close()`，记计数 n4 —— 预期 n4 = n0

若任意预期不符：把实测值与预期逐条记录（这是证伪 C1 的证据，同样写进报告，不要隐瞒）。

## 技术要点

- license key：环境变量 `CLOAKBROWSER_LICENSE_KEY` 优先，兜底读 `/Volumes/DataDrive/proj/public/1699/.cache/config.json` 的 `CLOAKBROWSER_LICENSE_KEY` 字段（可参考 `fetcher/fetcher/net/browser.py` 的 `load_license_key`）
- API（已读码确认的用法，见 `fetcher/fetcher/net/browser.py:210-260`）：
  - `from cloakbrowser import launch as cloak_launch`
  - `from cloakbrowser.license import get_active_session_count, validate_license`
  - launch 参数：`headless=True, license_key=<key>, humanize=True, locale="zh-CN", timezone="Asia/Shanghai", stealth_args=False`（**不要传 proxy/geoip**）
  - launch 可能抛 `SystemExit`（退出码 76 = session limit）——捕获并打印后退出
- 每次 `get_active_session_count` 之间 sleep 2~3 秒（服务端租约注册/释放有延迟）

## 环境纪律（铁律，违反即失败）

- **全程 headless**（本机有活爬虫在跑，不得弹窗干扰）
- **不开代理**（不占用青果隧道）；直连 launch
- **只 +1 席**：本机活爬虫约占 2 席，solo 套餐共 5 席，本次最多占用 1 席；跑完必须 close，并确认计数回落（n4≈n0）
- 不 import fetcher 包内需要浏览器装配的模块（避免副作用）；不修改任何产品代码

## 产出

报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md`，内容：

1. 每次计数的原始值（n0..n4）+ 预期 vs 实测逐条
2. 第二个 context 的 goto 结果
3. 结论：C1「一进程多 context 只占 1 席位」= **已验证** / **证伪**（带证据）
4. 环境说明（时间、如可观察的活爬虫占席情况）
5. 复现命令（脚本内容或路径）

## Git

- 分支 `feat/multiqueue-p3` 已就绪，直接在其上工作
- commit 范围：**只 add 报告文件** `docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md`（可连同本 brief 一起 add，它们同属 plan 目录）；工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），**绝不碰绝不带**，不要用 `git add -A`
- 脚本放 /tmp 不入库
- 若 commit 遇到 `.git/index.lock` 竞态（可能有另一个 Step 并行提交），sleep 几秒重试一次，仍失败就只保留文件不 commit，并在报告里注明

## 验收

报告含：① 每次计数原始值 ② 预期 vs 实测逐条 ③ 明确结论（已验证/证伪）④ 复现命令。
