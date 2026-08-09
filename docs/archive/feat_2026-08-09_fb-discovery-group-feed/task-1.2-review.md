# Step 1.2 review package
274a409 feat(fb): Step 1.2 FetchDdgSerp 原子 + parse/classify 纯函数（TDD）

 .../task-1.2-brief.md                              | 117 +++++++
 .../task-1.2-report.md                             |  76 ++++
 fetcher/fetcher/atoms/facebook_discover.py         | 196 +++++++++++
 fetcher/tests/test_facebook_discover.py            | 389 +++++++++++++++++++++
 4 files changed, 778 insertions(+)

diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-brief.md
new file mode 100644
index 0000000..deca415
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-brief.md
@@ -0,0 +1,117 @@
+# Step 1.2 — FetchDdgSerp 原子 + 纯函数（TDD）
+
+> 这是你的需求唯一来源。PLAN Step 1.2 原文 + SPEC §5.1 精确规格抄录如下。
+
+## PLAN Step 1.2 原文（验收以 checkbox 为准）
+
+- [ ] `fetcher/fetcher/atoms/facebook_discover.py`：
+      `_http_get(url, timeout) -> (status, html)`（urllib + UA + gzip 解压，模块级
+      便于 mock）
+- [ ] `parse_serp_results(html) -> list[{"url","title"}]`（抽 result__a → uddg 解码
+      → 标题净化；真实样本 spike/ddg_sample_1.html 截取 fixture）
+- [ ] `classify_fb_url(url) -> ("post"|"group", group_id, group_url) | None`
+      （POST_RE / GROUP_RE 双正则，SPEC §5.1）
+- [ ] `FetchDdgSerp` 原子 run：params 校验、节奏（sample floor 60 + 202 退避
+      uniform(180,240)）、Outcome 映射（OK/EMPTY/BLOCKED/NET_ERROR/SKIPPED/FATAL）
+- [ ] 测试（`fetcher/tests/test_facebook_discover.py`）：parse 样本结构/标题实体、
+      classify 各形态（帖/群主页/slug 群/视频/非 FB）、mock HTTP 全 outcome 路径、
+      202→BLOCKED、停止→SKIPPED、节奏 wait 次数
+- 预估 60min；验收：新测试全绿 + `test_facebook.py`/`test_facebook_group.py` 回归
+  不动（跑全 fb 测试组）
+
+## SPEC §5.1 FetchDdgSerp 原子（精确规格）
+
+新文件 `fetcher/fetcher/atoms/facebook_discover.py`：
+
+```python
+class FetchDdgSerp:
+    name = "fetch_ddg_serp"
+    title = "DDG抓FB群帖SERP"
+
+    params = {
+        "query":      str   必填，查询词（默认矩阵带 site:facebook.com/groups 前缀）
+        "page":       int   可选，页码（1 起，offset=(page-1)*10，缺省 1）
+        "sample_min": float 可选，查询间节奏下限秒（task 从 ctx.config 透传；
+                             原子强制下限 60，spike 依据见 §8.1）
+        "sample_max": float 可选，查询间节奏上限秒
+        "timeout":    int   可选，HTTP 超时（缺省 30）
+    }
+```
+
+- **HTTP**：urllib 裸 GET `https://html.duckduckgo.com/html/?q=<quote(query)>&s=<offset>`，
+  浏览器 UA（Chrome 125 同款）+ `Accept-Language: zh-CN` + `Accept-Encoding: gzip`
+  （响应 gzip 解压）。模块级 `_http_get(url, timeout) -> (status, html)` 独立成函数，
+  单测 monkeypatch 即可覆盖全部 HTTP 路径（对齐 facebook_group.py 的 `_http_json` 模式）。
+- **纯函数 `parse_serp_results(html) -> list[{"url","title"}]`**：正则抽
+  `<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=<enc>&amp;rut=...">`
+  锚点 → `uddg=` 参数 URL 解码 → 标题去标签/HTML 实体（&amp; 等）。返回**全部**有机
+  结果（不过滤），FB 过滤在下一级纯函数。真实样本：spike/ddg_sample_1.html。
+- **纯函数 `classify_fb_url(url) -> ("post"|"group", group_id, group_url) | None`**：
+  - `POST_RE = facebook\.com/groups/[^/]+/(?:posts|permalink)/(\d+)` → kind="post"，
+    group_url = 派生的群主页 `https://www.facebook.com/groups/{gid}`；
+  - `GROUP_RE = facebook\.com/groups/([^/]+)` → kind="group"，group_url = URL 自身
+    （归一化到 `https://www.facebook.com/groups/{gid}`，去尾部斜杠）；
+  - 其余 URL（FB 视频/用户主页/广告页/非 FB）→ None。
+- **节奏**：无论 outcome，请求后 `ctx.wait(random.uniform(sample_min', sample_max))`
+  （`sample_min' = max(sample_min, 60)`，模块常量 MIN_SAMPLE_FLOOR 注释写明 spike
+  依据）；**HTTP 202（anomaly 限流）时先 `ctx.wait(uniform(180, 240))` 再返回
+  BLOCKED**（覆盖 spike 实测封禁窗口，§8.1）。
+- **Outcome 口径**（对齐 FetchFbGroupPosts）：
+  - 200 + results → **OK**，`data={"engine":"ddg","query","page","results":[
+    {"url","title","kind","group_id","group_url"}...]}`
+  - 200 + 0 结果 → **EMPTY**
+  - 202（anomaly）/ 403 / 429 → **BLOCKED**
+  - 传输错误 / 5xx / 超时 → **NET_ERROR**
+  - 被停止信号中断 → **SKIPPED**
+
+## 协调者裁定（覆盖 SPEC 未定细节）
+
+1. **FATAL 口径**：params 校验失败（query 缺失/非 str、page < 1）→ FATAL（对齐
+   FetchFbGroupPosts 的缺参数 FATAL）。缺 API key 的 FATAL 与 SERP 无关（本原子无
+   key），不适用。
+2. **节奏的 wait 次数断言**：单测里 mock `ctx.wait` 计数——正常路径 1 次（请求后
+   节奏）、202 路径 2 次（退避 + 节奏）。SKIPPED 判定在 HTTP 前还是后：先检查
+   `ctx.stopped()` 再发请求 → 返回 SKIPPED 且 wait 0 次。
+3. **`_http_get` 的传输错误**：`urllib.error.URLError` / `HTTPError` / `socket.timeout`
+   原样上抛（由原子 run 捕获映射 NET_ERROR）；HTTP 5xx 状态码直接返回
+   (status, "") 由 run 映射 NET_ERROR——参考 facebook_group.py 的 _http_json 模式
+   （它上抛传输异常，由原子 catch）。具体实现以 facebook_group.py 原子为准：
+   读 `fetcher/fetcher/atoms/facebook_group.py` 的 FetchFbGroupPosts.run 与
+   `_http_json`，Outcome 映射与 catch 结构对齐它。
+4. **gzip 解压**：`Content-Encoding: gzip` 时解压（urllib 不自动解压）。
+5. **quote**：`urllib.parse.quote(query)`（默认 safe='/'，查询词含空格会编码为 %20，
+   符合 DDG 端点）。
+6. **标题净化**：strip + html.unescape（&amp; → & 等）；不处理 `| Facebook` 后缀
+   （那是 FbDiscoverTask 的职责，见 Step 1.3 brief）。
+7. **fixture**：从 `docs/feat_2026-08-09_fb-discovery-group-feed/spike/ddg_sample_1.html`
+   截取（或直接引用该文件路径读入测试，避免复制大文件；若复制进 fetcher/tests/
+   则保持小样本 <20KB）。
+
+## 代码库上下文
+
+- `fetcher/fetcher/atoms/facebook_group.py`：`_http_json` 模块级函数 + `FetchFbGroupPosts`
+  原子 run 的 Outcome 映射/异常 catch/节奏 wait 模式——本原子对齐它。
+- `fetcher/fetcher/core/context.py`：WorkerContext（`ctx.wait(seconds) -> bool` 返回
+  True=被停止/中止中断；`ctx.stopped()`）。
+- `fetcher/fetcher/core/types.py`：`ActionResult`（outcome/data）与 `Outcome` 枚举
+  （OK/EMPTY/BLOCKED/NET_ERROR/FATAL/SKIPPED 等）——读它确认枚举名与构造方式。
+- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
+  -s tests -p "test_facebook_discover.py"`；回归：`-p "test_facebook*.py"`（含
+  test_facebook.py、test_facebook_group.py、test_fb_plugin.py 等）。
+
+## TDD 纪律
+
+1. 先写失败测试 → RED（记录输出）→ 最小实现 → GREEN。mock 只在 HTTP 层
+   （monkeypatch `_http_get`），parse/classify 用真实 fixture/真实 URL。
+2. 测试覆盖（brief 已列）：parse 样本结构/标题实体、classify 各形态
+   （帖/群主页/slug 群/视频/非 FB）、mock HTTP 全 outcome 路径、202→BLOCKED、
+   停止→SKIPPED、节奏 wait 次数（含 202 双 wait）、params 校验 FATAL、gzip 解压。
+3. 测试输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`fetcher/fetcher/atoms/facebook_discover.py`、
+  `fetcher/tests/test_facebook_discover.py`（+可选 fixture 文件）、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 1.2 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md
new file mode 100644
index 0000000..31cab56
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md
@@ -0,0 +1,76 @@
+# Step 1.2 报告 — FetchDdgSerp 原子 + 纯函数（TDD）
+
+> 日期：2026-08-09 · implementer：subagent · 依据：task-1.2-brief.md（PLAN Step 1.2 + SPEC §5.1 + 协调者裁定）
+
+## 实现了什么
+
+新建 `fetcher/fetcher/atoms/facebook_discover.py`（对齐 facebook_group.py 模式）：
+
+- **`_http_get(url, timeout) -> (status, html)`**（模块级，便于 mock）：
+  urllib 裸 GET `https://html.duckduckgo.com/html/`，浏览器 UA（Chrome 125）+ `Accept-Language: zh-CN` + `Accept-Encoding: gzip`；`Content-Encoding: gzip` 时解压。
+  传输层异常（`URLError` / `socket.timeout`）原样上抛；`HTTPError`（403/429/5xx 等）返回 `(code, "")` 由原子映射——对齐 `_http_json` 的 catch 模式（裁定 3）。
+- **`parse_serp_results(html) -> list[{"url","title"}]`**：正则抽 `<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=...&amp;rut=...">` 锚点 → `uddg=` 参数 `unquote` 解码 → 标题去标签 + `html.unescape` + strip。返回全部有机结果不过滤；无锚点/坏 HTML → `[]`。
+- **`classify_fb_url(url) -> (kind, group_id, group_url) | None`**：`POST_RE = facebook\.com/groups/([^/]+)/(?:posts|permalink)/(\d+)` → `("post", gid, 派生群主页)`；`GROUP_RE = facebook\.com/groups/([^/]+)` → `("group", gid, 归一化群主页 https://www.facebook.com/groups/{gid})`；视频/用户主页/非 FB → None。group_id 语义 = 群 id（数字或 slug，URL 解析），与 fb_posts/fb_groups 表 `group_id` 列一致。
+- **`FetchDdgSerp` 原子 run**：
+  - params 校验（裁定 1）：query 缺失/非 str/空白 → FATAL；page < 1（含 0、负数、"0"）→ FATAL；FATAL 不发请求。
+  - 节奏：请求后统一 `ctx.wait(uniform(sample_min', sample_max))`，`sample_min' = max(sample_min, MIN_SAMPLE_FLOOR=60)`（模块常量注释写明 spike §8.1 依据）；**202 路径先 `ctx.wait(uniform(180,240))` 再节奏 wait**（2 次 wait，裁定 2）；`ctx.wait` 被中断（返回 True）→ SKIPPED。
+  - Outcome 映射：200+结果 → OK（data=`{"engine":"ddg","query","page","results":[{"url","title","kind","group_id","group_url"}...]}`）；200+0 结果 → EMPTY；202/403/429 → BLOCKED；传输错误/5xx/其他非 200 → NET_ERROR；请求前 `ctx.stopped()` → SKIPPED（wait 0 次、不发请求，裁定 2）。
+  - 请求 URL：`?q=<urllib.parse.quote(query)>（safe='/'，裁定 5）&s=(page-1)*10`。
+  - 非 FB 结果保留在 results 中（kind/group_id/group_url=None），不过滤——对应 SPEC「parse 返回全部有机结果、FB 过滤在下一级纯函数」的语义，分流交给 Step 1.3 任务（SPEC §5.2）。
+
+**fixture（裁定 7）**：不复制大文件，测试直接引用真实 spike 样本 `docs/feat_2026-08-09_fb-discovery-group-feed/spike/ddg_sample_1.html`（33KB > 20KB 复制上限，改为按路径读入）。
+
+## 测了什么、测试结果
+
+新建 `fetcher/tests/test_facebook_discover.py`，35 个测试，全部通过：
+
+| 测试组 | 覆盖 |
+|---|---|
+| TestParseSerpResults (5) | 真实样本：10 条结果、url 全解码为 https FB 群 URL、键只有 url/title；首条与样本逐字核对；标题 `&amp;/&lt;` 实体还原；标题去 `<b>` 标签；坏 HTML/空 → [] |
+| TestClassifyFbUrl (7) | 帖 permalink（数字群 id）、permalink 变体（slug 群 id）、群主页（数字/slug、去尾部斜杠归一化）、视频 → None、用户主页 → None、非 FB → None |
+| TestAtomParams (4) | query 缺失/非 str/空白 → FATAL 且不发请求；page 0/-1/"0" → FATAL |
+| TestAtomHttpOutcomes (15) | OK（数据形状/engine/query/page/results、请求 URL 的 q=quote 与 s=offset、wait=1 次且 ≥60）、page 2 → s=10、混合 kind（post/group/None 全保留）、EMPTY（仍 wait 1 次）、202→BLOCKED（wait 2 次，退避 ∈[180,240]+节奏 ≥60）、403/429→BLOCKED、5xx→NET_ERROR、传输异常→NET_ERROR（不 wait）、超时→NET_ERROR、请求前停止→SKIPPED（wait 0、不发请求）、等待中中断→SKIPPED、节奏地板（10/20 → 60.0）、节奏区间（90-120） |
+| TestHttpGet (5) | 请求头（UA/Accept-Language/Accept-Encoding/timeout）、gzip 解压、HTTPError→(429,"")、URLError 上抛、socket.timeout 上抛 |
+
+**验收命令**：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook_discover.py"` → 35 通过；回归 `-p "test_facebook*.py"` → 72 通过（37 旧 + 35 新，旧测试不动）；全量 `-p "*.py"` → 697 通过。输出干净（无 error/warning）。
+
+## TDD 证据
+
+**RED**：
+```
+$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook_discover.py"
+ImportError: cannot import name 'facebook_discover' from 'fetcher.atoms'
+    (…/fetcher/fetcher/atoms/__init__.py)
+FAILED (errors=1)
+```
+失败原因 = 模块不存在（功能缺失），符合预期——测试先行，实现后补。
+
+**GREEN**：
+```
+$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook_discover.py"
+Ran 35 tests in 0.003s
+OK
+```
+
+**TDD 驱动的 2 处实现修正**（测试先失败、改实现转绿）：
+1. `page=0`：初版用 `int(params.get("page") or 1)`，`0 or 1` 把显式 0 当成缺省 → OK 而非 FATAL。测试 `test_page_lt_1_is_fatal` 失败暴露 → 改为 `int(raw_page) if raw_page is not None else 1`。
+2. 请求头断言：本 Python 版本 `Request.get_header` 大小写敏感直查 dict，而 `add_header` 把 key 首字母大写 → `get_header("Accept-Language")` 返回 None。测试 `test_request_headers` 失败 → 测试改为对 `req.headers` 转小写做不区分大小写断言（实现本身无问题，头确实发出）。
+
+## 改动的文件
+
+- `fetcher/fetcher/atoms/facebook_discover.py`（新建：原子 + 3 个模块级函数 + 常量）
+- `fetcher/tests/test_facebook_discover.py`（新建：35 测试）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-brief.md`、`task-1.2-report.md`（本 Step 文档）
+
+## 自查发现
+
+- **解释性裁定（非阻塞）**：OK 的 `results` 保留非 FB 条目（kind=None）。依据：SPEC「parse 返回全部有机结果（不过滤）、FB 过滤在下一级纯函数」+ OK data 每结果含 kind 字段；Step 1.3 按 kind 分流时自然跳过 None（SPEC §5.2「帖 permalink 类」「全部 FB 群 URL」两类都不命中 None 行）。若评审倾向过滤，改动点集中在 run 的 results 组装一处。
+- **防御性补充（超出字面规格，已注释）**：`sample_max` 低于 60s 地板时抬到地板——SPEC §5.2 规定 task 透传 `ctx.config.sample_min/max`（缺省 13-20s），若不抬，`uniform(60, 20)` 抛 ValueError → 每个查询 NET_ERROR，真实链路必炸。已在代码注释说明。
+- **`sample_max` 缺省**：未传时取 `sample_min' + 20`（即 uniform(60,80)），SPEC 未定义缺省值，取了留余量的宽松上界。
+- classify 的 group_id = 群 id（URL 解析），与 fb_posts/fb_groups 表 group_id 列语义核对一致（db.py 建表注释「群 id（数字或 slug，URL 解析）」）。
+- 未注册 `atoms/__init__.py`（brief 未要求，Step 1.3 直接 `from fetcher.atoms.facebook_discover import FetchDdgSerp` 即可）。
+
+## 问题或疑虑
+
+- 无阻塞问题。上述 3 处解释/防御性细节请评审确认。
+- 真实 DDG 抓取未在本次验证（spike 已证 2026-08-09 端点可用；本 Step 全 mock HTTP，符合 brief「不依赖真实网络」）。
diff --git a/fetcher/fetcher/atoms/facebook_discover.py b/fetcher/fetcher/atoms/facebook_discover.py
new file mode 100644
index 0000000..40a7155
--- /dev/null
+++ b/fetcher/fetcher/atoms/facebook_discover.py
@@ -0,0 +1,196 @@
+# -*- coding: utf-8 -*-
+"""FetchDdgSerp 原子：DDG html 端点裸抓 FB 群帖 SERP + parse/classify 纯函数。
+
+背景（docs/feat_2026-08-09_fb-discovery-group-feed/SPEC.md §8.1）：DDG
+html 端点 GET + 浏览器 UA + gzip 可裸抓、无验证码；Bing 恒 challenge 不可用。
+限流形态为约 2 连查后第 3 次 HTTP 202（anomaly 页），恢复窗口约 4 分钟——
+本原子据此强制查询间节奏 ≥ 60s、202 退避 uniform(180,240)s。spike 实测样本
+存 docs/feat_2026-08-09_fb-discovery-group-feed/spike/ddg_sample_1.html。
+
+契约：
+    params = {
+        "query":      str   必填，查询词（默认矩阵带 site:facebook.com/groups 前缀）
+        "page":       int   可选，页码（1 起，offset=(page-1)*10，缺省 1）
+        "sample_min": float 可选，查询间节奏下限秒（task 从 ctx.config 透传；
+                             原子强制下限 MIN_SAMPLE_FLOOR=60，spike 依据见上）
+        "sample_max": float 可选，查询间节奏上限秒
+        "timeout":    int   可选，HTTP 超时（缺省 30）
+    }
+
+返回：
+    OK        data = {"engine":"ddg","query","page","results":[{"url","title",
+              "kind","group_id","group_url"}...]}——全部有机结果不过滤，非 FB 的
+              kind/group_id/group_url 为 None，分流交给上层任务（SPEC §5.2）
+    EMPTY     200 但 0 条有机结果
+    BLOCKED   HTTP 202（anomaly 限流，先退避 uniform(180,240)）/ 403 / 429
+    NET_ERROR 传输错误 / 5xx / 超时
+    FATAL     参数校验失败（query 缺失/非 str、page < 1）
+    SKIPPED   被停止信号中断（请求前检查或等待期间置位）
+
+依赖说明：只用标准库 urllib（符合包分层不引重依赖的约束）。
+"""
+
+from __future__ import annotations
+
+import gzip
+import html as html_mod
+import random
+import re
+import urllib.error
+import urllib.parse
+import urllib.request
+
+from fetcher.core.types import ActionResult
+
+DDG_HTML = "https://html.duckduckgo.com/html/"
+UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
+      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
+
+# DDG 突发限流 spike 实测（SPEC §8.1）：约 2 连查后第 3 次即 202（anomaly 页），
+# 202 触发到恢复的窗口实测约 4 分钟。查询间节奏下限 60s（~1 查询/分钟，低于
+# 2 连查即封的突发阈值，留安全余量）。
+MIN_SAMPLE_FLOOR = 60.0
+# 202（anomaly 限流）退避：uniform(180, 240) 覆盖实测 ~4 分钟封禁窗口。
+BLOCK_BACKOFF_MIN = 180.0
+BLOCK_BACKOFF_MAX = 240.0
+
+# SERP 有机结果锚点（spike 样本核实）：<a rel="nofollow" class="result__a"
+# href="//duckduckgo.com/l/?uddg=<enc>&amp;rut=...">标题</a>
+RESULT_A_RE = re.compile(
+    r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', re.S)
+UDDG_RE = re.compile(r"[?&]uddg=([^&]+)")
+TAG_RE = re.compile(r"<[^>]+>")
+
+# FB 帖 permalink：groups/<群id>/posts|permalink/<帖id（数字）>
+POST_RE = re.compile(r"facebook\.com/groups/([^/]+)/(?:posts|permalink)/(\d+)")
+# FB 群主页：groups/<群id>
+GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")
+
+
+def _http_get(url: str, timeout: float = 30) -> tuple[int, str]:
+    """裸 GET，返回 (status, html)。传输层异常（URLError/socket.timeout）
+    原样上抛；HTTPError（403/429/5xx 等）返回 (code, "") 由原子映射。
+    独立成模块级函数：单测 monkeypatch 即可覆盖全部 HTTP 路径。"""
+    req = urllib.request.Request(url, headers={
+        "User-Agent": UA,
+        "Accept-Language": "zh-CN",
+        "Accept-Encoding": "gzip",
+    })
+    try:
+        with urllib.request.urlopen(req, timeout=timeout) as resp:
+            body = resp.read()
+            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
+                body = gzip.decompress(body)
+            return resp.status, body.decode("utf-8", "replace")
+    except urllib.error.HTTPError as e:
+        # 4xx/5xx 状态码 → (code, "") 由原子映射（对齐 _http_json 模式）；
+        # 其余传输异常不在此 catch，原样上抛。
+        return e.code, ""
+
+
+def parse_serp_results(html: str) -> list[dict]:
+    """抽全部有机结果锚点 → uddg 参数 URL 解码 → 标题净化（去标签 + HTML 实体）。
+
+    返回 [{"url","title"}...]，不过滤（FB 判定在 classify_fb_url）；
+    无锚点/坏 HTML → []。
+    """
+    results = []
+    for href, title in RESULT_A_RE.findall(html):
+        href = html_mod.unescape(href)          # &amp; → &
+        m = UDDG_RE.search(href)
+        if not m:
+            continue                            # 非 redirect 形态，跳过
+        url = urllib.parse.unquote(m.group(1))
+        title = html_mod.unescape(TAG_RE.sub("", title)).strip()
+        results.append({"url": url, "title": title})
+    return results
+
+
+def classify_fb_url(url: str) -> tuple[str, str, str] | None:
+    """分类 FB 群帖 URL：(kind, group_id, group_url) | None。
+
+    kind="post"（帖 permalink）→ group_url 为派生的群主页；
+    kind="group"（群主页）→ group_url 归一化到
+    https://www.facebook.com/groups/{gid}（去尾部斜杠/协议差异）；
+    其余（FB 视频/用户主页/广告页/非 FB）→ None。
+    """
+    m = POST_RE.search(url)
+    if m:
+        gid = m.group(1)
+        return "post", gid, f"https://www.facebook.com/groups/{gid}"
+    m = GROUP_RE.search(url)
+    if m:
+        gid = m.group(1)
+        return "group", gid, f"https://www.facebook.com/groups/{gid}"
+    return None
+
+
+class FetchDdgSerp:
+    """DDG html 端点裸抓 FB 群帖 SERP（查询 → 解析 → 分类）。"""
+
+    name = "fetch_ddg_serp"
+    title = "DDG抓FB群帖SERP"
+
+    def run(self, ctx, params: dict) -> ActionResult:
+        if ctx.stopped():
+            return ActionResult.skipped("被停止信号中断")
+        params = params or {}
+        query = params.get("query")
+        if not isinstance(query, str) or not query.strip():
+            return ActionResult.fatal("缺少必填参数 query（查询词，str）")
+        query = query.strip()
+        raw_page = params.get("page")
+        try:
+            page = int(raw_page) if raw_page is not None else 1
+        except (TypeError, ValueError):
+            return ActionResult.fatal(f"page 参数无效: {raw_page!r}")
+        if page < 1:
+            return ActionResult.fatal(f"page 必须 ≥ 1（收到 {page}）")
+        timeout = int(params.get("timeout") or 30)
+        # 查询间节奏：task 从 ctx.config 透传 sample_min/max（缺省 13-20s），
+        # 原子强制下限 MIN_SAMPLE_FLOOR；上限低于地板时同样抬到地板，避免
+        # uniform(a>b) ValueError（对齐 §8.1 设计数字）。
+        sample_min = max(
+            float(params.get("sample_min") or MIN_SAMPLE_FLOOR),
+            MIN_SAMPLE_FLOOR)
+        sample_max = max(
+            float(params.get("sample_max") or (sample_min + 20.0)),
+            sample_min)
+
+        url = f"{DDG_HTML}?q={urllib.parse.quote(query)}&s={(page - 1) * 10}"
+        ctx.log(f"    ...DDG 查询「{query}」第 {page} 页")
+        try:
+            status, html = _http_get(url, timeout=timeout)
+        except (OSError, TimeoutError, ValueError) as e:
+            return ActionResult.net_error(f"DDG 请求失败: {e}")
+
+        # 202（anomaly 限流）：先退避覆盖实测 ~4 分钟封禁窗口，再返回 BLOCKED。
+        if status == 202:
+            if ctx.wait(random.uniform(BLOCK_BACKOFF_MIN, BLOCK_BACKOFF_MAX)):
+                return ActionResult.skipped("202 退避等待被停止信号中断")
+        # 请求后统一节奏等待（无论 outcome）。
+        if ctx.wait(random.uniform(sample_min, sample_max)):
+            return ActionResult.skipped("节奏等待被停止信号中断")
+
+        if status in (202, 403, 429):
+            return ActionResult.blocked(f"DDG 限流/拒绝（HTTP {status}）")
+        if status != 200:
+            return ActionResult.net_error(f"DDG 返回异常状态 HTTP {status}")
+
+        results = []
+        for r in parse_serp_results(html):
+            cls = classify_fb_url(r["url"])
+            if cls is None:
+                results.append({**r, "kind": None,
+                                "group_id": None, "group_url": None})
+            else:
+                kind, group_id, group_url = cls
+                results.append({"url": r["url"], "title": r["title"],
+                                "kind": kind, "group_id": group_id,
+                                "group_url": group_url})
+        if not results:
+            return ActionResult.empty("DDG 返回 0 条有机结果")
+
+        return ActionResult.success(
+            f"DDG 抓到 {len(results)} 条结果",
+            engine="ddg", query=query, page=page, results=results)
diff --git a/fetcher/tests/test_facebook_discover.py b/fetcher/tests/test_facebook_discover.py
new file mode 100644
index 0000000..94c7688
--- /dev/null
+++ b/fetcher/tests/test_facebook_discover.py
@@ -0,0 +1,389 @@
+# -*- coding: utf-8 -*-
+"""FetchDdgSerp 原子 + parse/classify 纯函数单测。
+
+parse/classify 用真实 spike 样本（docs/feat_2026-08-09_fb-discovery-group-feed/
+spike/ddg_sample_1.html，2026-08-09 实测 10 条有机结果全为 FB 群主页）与真实
+URL；HTTP 层全部 mock（_http_get / urlopen），不依赖真实网络。
+"""
+
+from __future__ import annotations
+
+import gzip
+import socket
+import threading
+import unittest
+import urllib.error
+import urllib.parse
+from pathlib import Path
+from unittest import mock
+
+from fetcher.atoms import facebook_discover as fd
+from fetcher.atoms.facebook_discover import (
+    FetchDdgSerp,
+    classify_fb_url,
+    parse_serp_results,
+)
+from fetcher.core.types import Outcome
+
+# 真实 spike 样本：<root>/docs/feat_2026-08-09_fb-discovery-group-feed/spike/
+SPIKE_HTML = (Path(__file__).resolve().parents[2]
+              / "docs" / "feat_2026-08-09_fb-discovery-group-feed"
+              / "spike" / "ddg_sample_1.html")
+
+SAMPLE_QUERY = "site:facebook.com/groups 跨境电商 whatsapp"
+
+
+class _Ctx:
+    """最小 WorkerContext 替身：记录 wait 次数/时长，可模拟停止信号。"""
+
+    def __init__(self, stopped: bool = False):
+        self.stop = threading.Event()
+        if stopped:
+            self.stop.set()
+        self.waits: list[float] = []
+        self.logs: list[str] = []
+
+    def stopped(self) -> bool:
+        return self.stop.is_set()
+
+    def wait(self, seconds: float) -> bool:
+        self.waits.append(seconds)
+        return self.stop.is_set()
+
+    def log(self, msg: str) -> None:
+        self.logs.append(msg)
+
+
+class _StopAfterRequest(_Ctx):
+    """请求发出后才置位 stop：验证节奏 wait 被中断 → SKIPPED。"""
+
+    def stopped(self) -> bool:
+        return False   # 请求前不停止
+
+    def wait(self, seconds: float) -> bool:
+        self.waits.append(seconds)
+        return True    # 等待期间 stop 置位
+
+
+def _run(params, ctx=None):
+    return FetchDdgSerp().run(ctx or _Ctx(), params)
+
+
+def _sample_html() -> str:
+    return SPIKE_HTML.read_text(encoding="utf-8")
+
+
+class TestParseSerpResults(unittest.TestCase):
+    def test_sample_structure(self):
+        """真实样本：10 条结果，全部解码为 https FB 群 URL，键只有 url/title。"""
+        results = parse_serp_results(_sample_html())
+        self.assertEqual(len(results), 10)
+        for r in results:
+            self.assertEqual(set(r), {"url", "title"})
+            self.assertTrue(
+                r["url"].startswith("https://www.facebook.com/groups/"))
+            self.assertNotIn("%", r["url"])            # uddg 已 URL 解码
+            self.assertNotIn("&amp;", r["url"])        # HTML 实体已还原
+            self.assertTrue(r["title"].strip())
+
+    def test_first_result_matches_sample(self):
+        results = parse_serp_results(_sample_html())
+        self.assertEqual(
+            results[0]["url"],
+            "https://www.facebook.com/groups/crossborderelectroniccommerce/")
+        self.assertEqual(results[0]["title"], "跨境电商交流群 | Facebook")
+
+    def test_title_html_entities_unescaped(self):
+        html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+                '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2F&amp;rut=x">'
+                'A &amp; B &lt;测试&gt;</a>')
+        results = parse_serp_results(html)
+        self.assertEqual(results[0]["title"], "A & B <测试>")
+
+    def test_title_tags_stripped(self):
+        html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+                '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2F&amp;rut=x">'
+                '<b>跨境</b> 交流群</a>')
+        results = parse_serp_results(html)
+        self.assertEqual(results[0]["title"], "跨境 交流群")
+
+    def test_no_results_returns_empty(self):
+        self.assertEqual(parse_serp_results("<html><body>无结果</body></html>"), [])
+        self.assertEqual(parse_serp_results(""), [])
+
+
+class TestClassifyFbUrl(unittest.TestCase):
+    def test_post_permalink(self):
+        url = ("https://www.facebook.com/groups/185879310028412/"
+               "posts/1437583168191347/")
+        self.assertEqual(
+            classify_fb_url(url),
+            ("post", "185879310028412",
+             "https://www.facebook.com/groups/185879310028412"))
+
+    def test_post_permalink_variant(self):
+        """permalink 变体 + slug 群 id。"""
+        url = ("https://www.facebook.com/groups/crossborderelectroniccommerce/"
+               "permalink/123456789/")
+        self.assertEqual(
+            classify_fb_url(url),
+            ("post", "crossborderelectroniccommerce",
+             "https://www.facebook.com/groups/crossborderelectroniccommerce"))
+
+    def test_group_numeric(self):
+        url = "https://www.facebook.com/groups/2245859412418547/"
+        self.assertEqual(
+            classify_fb_url(url),
+            ("group", "2245859412418547",
+             "https://www.facebook.com/groups/2245859412418547"))
+
+    def test_group_slug_without_trailing_slash(self):
+        url = "https://www.facebook.com/groups/yiliukescrm"
+        self.assertEqual(
+            classify_fb_url(url),
+            ("group", "yiliukescrm",
+             "https://www.facebook.com/groups/yiliukescrm"))
+
+    def test_video_is_none(self):
+        self.assertIsNone(
+            classify_fb_url("https://www.facebook.com/watch/?v=123456789"))
+
+    def test_user_profile_is_none(self):
+        self.assertIsNone(classify_fb_url("https://www.facebook.com/someuser"))
+
+    def test_non_facebook_is_none(self):
+        self.assertIsNone(
+            classify_fb_url("https://www.youtube.com/watch?v=abc"))
+
+
+class TestAtomParams(unittest.TestCase):
+    def test_missing_query_is_fatal(self):
+        with mock.patch.object(fd, "_http_get") as m:
+            r = _run({})
+        self.assertIs(r.outcome, Outcome.FATAL)
+        m.assert_not_called()          # FATAL 不发请求
+
+    def test_non_str_query_is_fatal(self):
+        r = _run({"query": 123})
+        self.assertIs(r.outcome, Outcome.FATAL)
+
+    def test_blank_query_is_fatal(self):
+        r = _run({"query": "   "})
+        self.assertIs(r.outcome, Outcome.FATAL)
+
+    def test_page_lt_1_is_fatal(self):
+        for page in (0, -1, "0"):
+            r = _run({"query": "x", "page": page})
+            self.assertIs(r.outcome, Outcome.FATAL, f"page={page!r}")
+
+
+class TestAtomHttpOutcomes(unittest.TestCase):
+    def test_ok_with_results(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())) as m:
+            ctx = _Ctx()
+            r = _run({"query": SAMPLE_QUERY}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.OK)
+        self.assertEqual(r.data["engine"], "ddg")
+        self.assertEqual(r.data["query"], SAMPLE_QUERY)
+        self.assertEqual(r.data["page"], 1)
+        results = r.data["results"]
+        self.assertEqual(len(results), 10)
+        first = results[0]
+        self.assertEqual(set(first), {"url", "title", "kind",
+                                      "group_id", "group_url"})
+        self.assertEqual(first["kind"], "group")
+        self.assertEqual(
+            first["group_url"],
+            "https://www.facebook.com/groups/crossborderelectroniccommerce")
+        # 请求 URL：q=quote(query)（safe='/'）、s=offset=0
+        url_called = m.call_args[0][0]
+        self.assertIn(f"q={urllib.parse.quote(SAMPLE_QUERY)}", url_called)
+        self.assertIn("&s=0", url_called)
+        # 正常路径：请求后节奏 wait 恰好 1 次，且 ≥ 60s 地板
+        self.assertEqual(len(ctx.waits), 1)
+        self.assertGreaterEqual(ctx.waits[0], 60)
+
+    def test_page_2_offset(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())) as m:
+            _run({"query": "x", "page": 2})
+        self.assertIn("&s=10", m.call_args[0][0])
+
+    def test_ok_mixed_kinds(self):
+        """帖 + 群主页 + 非 FB 混合：全部保留，非 FB 的 kind 为 None。"""
+        html = (
+            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+            '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2Fposts%2F456%2F'
+            '&amp;rut=a">Post A</a>'
+            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+            '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2Fslugg%2F&amp;rut=b">'
+            'Group B</a>'
+            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+            '?uddg=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc&amp;rut=c">'
+            'Video C</a>')
+        with mock.patch.object(fd, "_http_get", return_value=(200, html)):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.OK)
+        results = r.data["results"]
+        self.assertEqual(len(results), 3)
+        self.assertEqual(results[0]["kind"], "post")
+        self.assertEqual(results[0]["group_id"], "123")
+        self.assertEqual(results[0]["group_url"],
+                         "https://www.facebook.com/groups/123")
+        self.assertEqual(results[1]["kind"], "group")
+        self.assertIsNone(results[2]["kind"])
+        self.assertIsNone(results[2]["group_id"])
+
+    def test_empty_serp_is_empty(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, "<html>nothing</html>")):
+            ctx = _Ctx()
+            r = _run({"query": "x"}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.EMPTY)
+        self.assertEqual(len(ctx.waits), 1)   # 空结果也走请求后节奏
+
+    def test_202_is_blocked_with_backoff_wait(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(202, "anomaly")):
+            ctx = _Ctx()
+            r = _run({"query": "x"}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.BLOCKED)
+        # 202 路径：退避 uniform(180,240) + 请求后节奏 = 2 次 wait
+        self.assertEqual(len(ctx.waits), 2)
+        self.assertGreaterEqual(ctx.waits[0], 180)
+        self.assertLessEqual(ctx.waits[0], 240)
+        self.assertGreaterEqual(ctx.waits[1], 60)
+
+    def test_403_is_blocked(self):
+        with mock.patch.object(fd, "_http_get", return_value=(403, "")):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.BLOCKED)
+
+    def test_429_is_blocked(self):
+        with mock.patch.object(fd, "_http_get", return_value=(429, "")):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.BLOCKED)
+
+    def test_5xx_is_net_error(self):
+        with mock.patch.object(fd, "_http_get", return_value=(500, "")):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.NET_ERROR)
+
+    def test_transport_error_is_net_error_no_wait(self):
+        with mock.patch.object(fd, "_http_get",
+                               side_effect=OSError("connection reset")):
+            ctx = _Ctx()
+            r = _run({"query": "x"}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.NET_ERROR)
+        self.assertEqual(ctx.waits, [])   # 传输异常无响应，不节奏 wait
+
+    def test_timeout_is_net_error(self):
+        with mock.patch.object(fd, "_http_get",
+                               side_effect=TimeoutError("timed out")):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.NET_ERROR)
+
+    def test_stopped_is_skipped_no_wait_no_http(self):
+        with mock.patch.object(fd, "_http_get") as m:
+            ctx = _Ctx(stopped=True)
+            r = _run({"query": "x"}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.SKIPPED)
+        self.assertEqual(ctx.waits, [])
+        m.assert_not_called()
+
+    def test_interrupted_during_wait_is_skipped(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())):
+            r = _run({"query": "x"}, ctx=_StopAfterRequest())
+        self.assertIs(r.outcome, Outcome.SKIPPED)
+
+    def test_rhythm_floor_enforced(self):
+        """task 透传的 config 节奏（13-20s）低于 60s 地板 → 强制 60s。"""
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())):
+            ctx = _Ctx()
+            _run({"query": "x", "sample_min": 10, "sample_max": 20}, ctx=ctx)
+        self.assertEqual(ctx.waits, [60.0])
+
+    def test_rhythm_range_respected(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())):
+            ctx = _Ctx()
+            _run({"query": "x", "sample_min": 90, "sample_max": 120}, ctx=ctx)
+        self.assertEqual(len(ctx.waits), 1)
+        self.assertGreaterEqual(ctx.waits[0], 90)
+        self.assertLessEqual(ctx.waits[0], 120)
+
+
+class _FakeResp:
+    """最小 urllib 响应替身：可带 gzip 头。"""
+
+    def __init__(self, body: bytes, encoding: str | None = None):
+        self._body = body
+        self.headers = {}
+        if encoding:
+            self.headers["Content-Encoding"] = encoding
+        self.status = 200
+
+    def read(self) -> bytes:
+        return self._body
+
+    def __enter__(self):
+        return self
+
+    def __exit__(self, *exc):
+        return False
+
+
+class TestHttpGet(unittest.TestCase):
+    def test_request_headers(self):
+        with mock.patch("urllib.request.urlopen",
+                        return_value=_FakeResp(b"<html>ok</html>")) as m:
+            status, html = fd._http_get(
+                "https://html.duckduckgo.com/html/?q=x", timeout=5)
+        self.assertEqual(status, 200)
+        self.assertEqual(html, "<html>ok</html>")
+        req = m.call_args[0][0]
+        # Request 的 add_header 会把 key 首字母大写、其余小写，get_header 在此
+        # Python 版本是大小写敏感直接查 dict——统一转小写做不区分大小写断言。
+        sent = {k.lower(): v for k, v in req.headers.items()}
+        self.assertTrue(sent["user-agent"].startswith("Mozilla/"))
+        self.assertEqual(sent["accept-language"], "zh-CN")
+        self.assertEqual(sent["accept-encoding"], "gzip")
+        self.assertEqual(m.call_args[1]["timeout"], 5)
+
+    def test_gzip_decompress(self):
+        raw = "<html>gzipped</html>".encode("utf-8")
+        with mock.patch("urllib.request.urlopen",
+                        return_value=_FakeResp(gzip.compress(raw),
+                                               encoding="gzip")):
+            status, html = fd._http_get(
+                "https://html.duckduckgo.com/html/?q=x")
+        self.assertEqual(status, 200)
+        self.assertEqual(html, "<html>gzipped</html>")
+
+    def test_http_error_returns_status(self):
+        err = urllib.error.HTTPError("https://x", 429, "rate limited",
+                                     hdrs={}, fp=None)
+        with mock.patch("urllib.request.urlopen", side_effect=err):
+            status, html = fd._http_get(
+                "https://html.duckduckgo.com/html/?q=x")
+        self.assertEqual(status, 429)
+        self.assertEqual(html, "")
+
+    def test_urlerror_raised(self):
+        with mock.patch("urllib.request.urlopen",
+                        side_effect=urllib.error.URLError("dns fail")):
+            with self.assertRaises(urllib.error.URLError):
+                fd._http_get("https://html.duckduckgo.com/html/?q=x")
+
+    def test_socket_timeout_raised(self):
+        with mock.patch("urllib.request.urlopen",
+                        side_effect=socket.timeout("timed out")):
+            with self.assertRaises(socket.timeout):
+                fd._http_get("https://html.duckduckgo.com/html/?q=x")
+
+
+if __name__ == "__main__":
+    unittest.main()
