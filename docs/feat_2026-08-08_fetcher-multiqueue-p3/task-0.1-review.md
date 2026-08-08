# Review Package — Step 0.1 (P3-0 spike)

## Commits
bdef641 P3-0 Step 0.1: CloakBrowser 多 context 席位计数实测 — C1 已验证

## Stat
 .../spike-cloakbrowser-multicontext.md             | 77 ++++++++++++++++++++++
 .../task-0.1-brief.md                              | 58 ++++++++++++++++
 2 files changed, 135 insertions(+)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md
new file mode 100644
index 0000000..8cd2ab6
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md
@@ -0,0 +1,77 @@
+# Spike Report — CloakBrowser 多 context 席位计数实测
+
+> P3-0 Step 0.1 | 执行时间: 2026-08-13
+> 来源: SPEC §4 C1 / PLAN.md P3-0 Step 0.1
+
+## 目标
+
+实测 CloakBrowser 会话席位按「浏览器二进制进程」还是按「BrowserContext」计数。
+结论直接决定 P3-2 浏览器层「一进程多 context 只占 1 席」方案是否成立。
+
+## 方法
+
+脚本 `/tmp/spike_cloak_multicontext.py`，严格按以下序列执行：
+
+1. **n0** — baseline：读取当前 `get_active_session_count(key)`
+2. **n1** — headless 直连 launch CloakBrowser（无代理），读计数
+3. **n2** — `browser.new_context(locale="zh-CN")`，读计数
+4. **n3** — `ctx2.new_page()` → `page.goto("about:blank")`，读计数
+5. **n4** — `browser.close()`，读计数
+
+每次计数之间等待 3 秒（服务端租约注册/释放有延迟）。
+
+Launch 参数：`headless=True, license_key=<key>, humanize=True, locale="zh-CN", timezone="Asia/Shanghai", stealth_args=False`（无代理、无 geoip）。
+
+## 原始结果
+
+| 步骤 | 操作 | 实测值 | 预期值 | 判定 |
+|------|------|--------|--------|------|
+| n0 | baseline | **0** | — | — |
+| n1 | launch | **1** | n0 + 1 = 1 | ✓ |
+| n2 | new_context | **1** | n1 = 1 | ✓ |
+| n3 | ctx2.new_page() + goto("about:blank") | **1** | n2 = 1 | ✓ |
+| n4 | browser.close() | **0** | n0 = 0 | ✓ |
+
+### 第二个 context 可用性
+
+- `ctx2.new_page()` — 成功
+- `page.goto("about:blank")` — 成功
+- context 完全可用，不受席位计数影响
+
+## 预期 vs 实测（逐条）
+
+| 断言 | 实测 | 预期 | 结果 |
+|------|------|------|------|
+| n1 = n0 + 1 | 1 | 1 | ✓ |
+| n2 = n1（多 context 不占新席位） | 1 | 1 | ✓ |
+| n3 = n2（goto 不占新席位） | 1 | 1 | ✓ |
+| n4 = n0（关闭释放席位） | 0 | 0 | ✓ |
+
+## 结论
+
+**C1「一进程多 context 只占 1 席位」= 已验证。**
+
+证据：launch 后席位 +1（n0→n1），创建第二个 BrowserContext 并实际使用（new_page + goto）后计数未变（n2=n3=n1=1），关闭浏览器后席位释放回基线（n4=n0=0）。CloakBrowser 会话席位以浏览器二进制进程为粒度计数，同一进程内的多个 BrowserContext 不额外占用席位。
+
+## 环境说明
+
+- 时间：2026-08-13（北京时间）
+- Python：系统 python3
+- 活爬虫占席情况：n0=0（本次执行时无活爬虫运行）
+- 套餐类型：solo（5 席上限）
+- 本次占用：最多 1 席（已确认释放）
+
+## 复现命令
+
+```bash
+cd /Volumes/DataDrive/proj/public/1699
+python3 /tmp/spike_cloak_multicontext.py
+```
+
+脚本内容见 `/tmp/spike_cloak_multicontext.py`（不入库）。
+
+## 对后续的影响
+
+P3-2 浏览器层「一进程多 context 只占 1 席」方案可安全推进。方案核心逻辑：
+一个 CloakBrowser 进程内可创建多个 BrowserContext，各自绑定不同的 site+identity，
+只占用 1 个会话席位，从而在有限席位下实现多队列跨站填充。
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-brief.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-brief.md
new file mode 100644
index 0000000..5bdd3d1
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-0.1-brief.md
@@ -0,0 +1,58 @@
+# Task 0.1 Brief — CloakBrowser 多 context 席位计数实测（P3-0 spike）
+
+> 来源：PLAN.md P3-0 Step 0.1 全文 + SPEC §4 C1。本文件是本次任务的唯一需求来源。
+
+## 目标
+
+实测 CloakBrowser 会话席位按「浏览器二进制进程」还是按「BrowserContext」计数（SPEC §4 C1 假设）。
+结论直接决定 P3-2 浏览器层「一进程多 context 只占 1 席」方案是否成立，也是 P3-2 动工的硬准入。
+
+## 步骤（严格按顺序）
+
+写脚本 `/tmp/spike_cloak_multicontext.py`，完成以下序列，每次计数后打印一行原始值：
+
+1. **baseline**：`get_active_session_count(key)` 读当前会话数（记为 n0）
+2. **launch**：headless 直连 launch 一个 CloakBrowser（**不加 proxy**），记计数 n1 —— 预期 n1 = n0 + 1
+3. **第二个 context**：`browser.new_context(locale="zh-CN")`，记计数 n2 —— 预期 n2 = n1（多 context 不占新席位）
+4. **第二个 context 可用性**：`ctx2.new_page()` 然后 `page.goto("about:blank")` 成功，记计数 n3 —— 预期 n3 = n2
+5. **close**：`browser.close()`，记计数 n4 —— 预期 n4 = n0
+
+若任意预期不符：把实测值与预期逐条记录（这是证伪 C1 的证据，同样写进报告，不要隐瞒）。
+
+## 技术要点
+
+- license key：环境变量 `CLOAKBROWSER_LICENSE_KEY` 优先，兜底读 `/Volumes/DataDrive/proj/public/1699/.cache/config.json` 的 `CLOAKBROWSER_LICENSE_KEY` 字段（可参考 `fetcher/fetcher/net/browser.py` 的 `load_license_key`）
+- API（已读码确认的用法，见 `fetcher/fetcher/net/browser.py:210-260`）：
+  - `from cloakbrowser import launch as cloak_launch`
+  - `from cloakbrowser.license import get_active_session_count, validate_license`
+  - launch 参数：`headless=True, license_key=<key>, humanize=True, locale="zh-CN", timezone="Asia/Shanghai", stealth_args=False`（**不要传 proxy/geoip**）
+  - launch 可能抛 `SystemExit`（退出码 76 = session limit）——捕获并打印后退出
+- 每次 `get_active_session_count` 之间 sleep 2~3 秒（服务端租约注册/释放有延迟）
+
+## 环境纪律（铁律，违反即失败）
+
+- **全程 headless**（本机有活爬虫在跑，不得弹窗干扰）
+- **不开代理**（不占用青果隧道）；直连 launch
+- **只 +1 席**：本机活爬虫约占 2 席，solo 套餐共 5 席，本次最多占用 1 席；跑完必须 close，并确认计数回落（n4≈n0）
+- 不 import fetcher 包内需要浏览器装配的模块（避免副作用）；不修改任何产品代码
+
+## 产出
+
+报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md`，内容：
+
+1. 每次计数的原始值（n0..n4）+ 预期 vs 实测逐条
+2. 第二个 context 的 goto 结果
+3. 结论：C1「一进程多 context 只占 1 席位」= **已验证** / **证伪**（带证据）
+4. 环境说明（时间、如可观察的活爬虫占席情况）
+5. 复现命令（脚本内容或路径）
+
+## Git
+
+- 分支 `feat/multiqueue-p3` 已就绪，直接在其上工作
+- commit 范围：**只 add 报告文件** `docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md`（可连同本 brief 一起 add，它们同属 plan 目录）；工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），**绝不碰绝不带**，不要用 `git add -A`
+- 脚本放 /tmp 不入库
+- 若 commit 遇到 `.git/index.lock` 竞态（可能有另一个 Step 并行提交），sleep 几秒重试一次，仍失败就只保留文件不 commit，并在报告里注明
+
+## 验收
+
+报告含：① 每次计数原始值 ② 预期 vs 实测逐条 ③ 明确结论（已验证/证伪）④ 复现命令。
