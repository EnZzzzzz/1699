# Step 1.2 fix round 1 review
83c75e2 fix(fb): Step 1.2 review——参数缺省改显式 None 判断（or 反模式吞掉显式 0）
 .../task-1.2-report.md                             | 85 ++++++++++++++++++++++
 fetcher/fetcher/atoms/facebook_discover.py         | 22 ++++--
 fetcher/tests/test_facebook_discover.py            | 29 ++++++++
 3 files changed, 128 insertions(+), 8 deletions(-)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md
index 31cab56..7046554 100644
--- a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md
@@ -67,10 +67,95 @@ OK
 - **解释性裁定（非阻塞）**：OK 的 `results` 保留非 FB 条目（kind=None）。依据：SPEC「parse 返回全部有机结果（不过滤）、FB 过滤在下一级纯函数」+ OK data 每结果含 kind 字段；Step 1.3 按 kind 分流时自然跳过 None（SPEC §5.2「帖 permalink 类」「全部 FB 群 URL」两类都不命中 None 行）。若评审倾向过滤，改动点集中在 run 的 results 组装一处。
 - **防御性补充（超出字面规格，已注释）**：`sample_max` 低于 60s 地板时抬到地板——SPEC §5.2 规定 task 透传 `ctx.config.sample_min/max`（缺省 13-20s），若不抬，`uniform(60, 20)` 抛 ValueError → 每个查询 NET_ERROR，真实链路必炸。已在代码注释说明。
 - **`sample_max` 缺省**：未传时取 `sample_min' + 20`（即 uniform(60,80)），SPEC 未定义缺省值，取了留余量的宽松上界。
 - classify 的 group_id = 群 id（URL 解析），与 fb_posts/fb_groups 表 group_id 列语义核对一致（db.py 建表注释「群 id（数字或 slug，URL 解析）」）。
 - 未注册 `atoms/__init__.py`（brief 未要求，Step 1.3 直接 `from fetcher.atoms.facebook_discover import FetchDdgSerp` 即可）。
 
 ## 问题或疑虑
 
 - 无阻塞问题。上述 3 处解释/防御性细节请评审确认。
 - 真实 DDG 抓取未在本次验证（spike 已证 2026-08-09 端点可用；本 Step 全 mock HTTP，符合 brief「不依赖真实网络」）。
+
+---
+
+# Step 1.2 Fix1 报告 — review 发现修复（or 反模式）
+
+> 日期：2026-08-09 · fixer：subagent · 依据：task-1.2-fix1-dispatch.md（review 发现 1）
+> 状态：已修复并验证（TDD：RED → GREEN → 回归）
+
+## 改了什么
+
+**`fetcher/fetcher/atoms/facebook_discover.py`（FetchDdgSerp.run 参数解析，原 L149-158）**：
+删除三处 Python falsy-or-default 反模式，统一改为显式 None 判断（对齐同函数 L147
+page 的处理方式）：
+
+```python
+# 改前（or 吞掉显式 0）
+timeout = int(params.get("timeout") or 30)
+sample_min = max(float(params.get("sample_min") or MIN_SAMPLE_FLOOR), MIN_SAMPLE_FLOOR)
+sample_max = max(float(params.get("sample_max") or (sample_min + 20.0)), sample_min)
+
+# 改后（显式 None 判断）
+raw_timeout = params.get("timeout")
+timeout = int(raw_timeout) if raw_timeout is not None else 30
+raw_min = params.get("sample_min")
+sample_min = float(raw_min) if raw_min is not None else MIN_SAMPLE_FLOOR
+sample_min = max(sample_min, MIN_SAMPLE_FLOOR)
+raw_max = params.get("sample_max")
+sample_max = float(raw_max) if raw_max is not None else (sample_min + 20.0)
+sample_max = max(sample_max, sample_min)
+```
+
+改后语义（按 dispatch 裁定「以不改行为为准，仅修 or 反模式」）：
+- `sample_min=0`：显式 0 被保留后由地板 `max(…, 60)` 抬到 60 —— 行为不变（floor 掩盖）。
+- `sample_max=0`：显式 0 不再走 `0 or (sample_min+20)` 缺省；由
+  `max(sample_max, sample_min)` 抬到地板 60 —— 行为修正（原会拿到 80）。
+- `timeout=0`：显式 0 原样传给 `_http_get`（不再被吞成缺省 30）。真实 urllib 下
+  timeout=0 可能无意义，但按裁定「0 无意义可加 max(1,…) 属可选，以不改行为准」，
+  未加保护——语义即「显式 0 就是 0」。
+
+## 覆盖测试（TDD RED → GREEN）
+
+`fetcher/tests/test_facebook_discover.py` 新增 2 个测试（`TestAtomHttpOutcomes`）：
+1. `test_timeout_zero_passed_through`：`{"timeout": 0}` → 断言 `_http_get` 收到的
+   `timeout == 0`（经 mock 调用参数直接区分 or 与 None 判断）。
+2. `test_sample_zero_not_swallowed_by_or_default`：`{"sample_min": 0, "sample_max": 0}`
+   → 断言传给 `random.uniform` 的区间恰为 `(60.0, 60.0)`（mock `fd.random.uniform`
+   确定性断言参数解析层；or 反模式下 sample_max 走缺省会得到 `(60.0, 80.0)`）。
+
+**RED 依据（说明）**：纯 `{"sample_min": 0}`（sample_max 缺省）在 run 层不可区分——
+floor 把 or 反模式与 None 判断的结果都纠正到 uniform(60,80)，故测试 2 采用
+「sample_min 与 sample_max 同时显式 0 + 直接断言 uniform 区间」的设计，通过
+sample_max 缺省分支暴露 or 反模式，属 dispatch 允许的「补一个直接测参数解析的断言」。
+
+**RED 输出（修复前，2 失败均为功能缺失，非笔误）**：
+```
+FAIL: test_timeout_zero_passed_through — AssertionError: 30 != 0
+      （or 把显式 0 吞成缺省 30）
+FAIL: test_sample_zero_not_swallowed_by_or_default — (60.0, 80.0) != (60.0, 60.0)
+      （or 把显式 sample_max=0 吞成缺省 80）
+Ran 37 tests in 0.005s — FAILED (failures=2)
+```
+
+**GREEN 输出（修复后）**：
+```
+$ cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook_discover.py"
+Ran 37 tests in 0.004s
+OK
+```
+
+## 回归
+
+```
+$ cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook*.py"
+Ran 74 tests in 4.362s
+OK
+```
+72 旧测试不动，+2 新测试 = 74 全绿；输出干净（无 error/warning）。
+
+## 疑虑
+
+- `sample_min`/`sample_max` 传非数值（如 `""`）时，None 判断会走 `float("")` 抛
+  ValueError（改前 `"" or 缺省` 静默回落缺省）。dispatch 指定了精确改法且实际参数
+  来自 task 的 ctx.config 浮点值，未加防御——若评审希望，可仿 page 加
+  try/except → FATAL，属超出本 review 范围的行为变更，未做。
+- `timeout=0` 真实 urllib 语义未验证（测试全 mock），裁定允许。
diff --git a/fetcher/fetcher/atoms/facebook_discover.py b/fetcher/fetcher/atoms/facebook_discover.py
index 40a7155..5c58ed0 100644
--- a/fetcher/fetcher/atoms/facebook_discover.py
+++ b/fetcher/fetcher/atoms/facebook_discover.py
@@ -139,30 +139,36 @@ class FetchDdgSerp:
         if not isinstance(query, str) or not query.strip():
             return ActionResult.fatal("缺少必填参数 query（查询词，str）")
         query = query.strip()
         raw_page = params.get("page")
         try:
             page = int(raw_page) if raw_page is not None else 1
         except (TypeError, ValueError):
             return ActionResult.fatal(f"page 参数无效: {raw_page!r}")
         if page < 1:
             return ActionResult.fatal(f"page 必须 ≥ 1（收到 {page}）")
-        timeout = int(params.get("timeout") or 30)
+        raw_timeout = params.get("timeout")
+        timeout = int(raw_timeout) if raw_timeout is not None else 30
         # 查询间节奏：task 从 ctx.config 透传 sample_min/max（缺省 13-20s），
         # 原子强制下限 MIN_SAMPLE_FLOOR；上限低于地板时同样抬到地板，避免
-        # uniform(a>b) ValueError（对齐 §8.1 设计数字）。
-        sample_min = max(
-            float(params.get("sample_min") or MIN_SAMPLE_FLOOR),
-            MIN_SAMPLE_FLOOR)
-        sample_max = max(
-            float(params.get("sample_max") or (sample_min + 20.0)),
-            sample_min)
+        # uniform(a>b) ValueError（对齐 §8.1 设计数字）。用显式 None 判断而非
+        # `or` 缺省（or 会吞掉显式 0）：sample_min=0 由地板抬到 60、
+        # sample_max=0 由 max(sample_max, sample_min) 抬到 60；timeout=0 原样
+        # 传给 _http_get（合法显式值，不转缺省 30）。
+        raw_min = params.get("sample_min")
+        sample_min = (float(raw_min) if raw_min is not None
+                      else MIN_SAMPLE_FLOOR)
+        sample_min = max(sample_min, MIN_SAMPLE_FLOOR)
+        raw_max = params.get("sample_max")
+        sample_max = (float(raw_max) if raw_max is not None
+                      else (sample_min + 20.0))
+        sample_max = max(sample_max, sample_min)
 
         url = f"{DDG_HTML}?q={urllib.parse.quote(query)}&s={(page - 1) * 10}"
         ctx.log(f"    ...DDG 查询「{query}」第 {page} 页")
         try:
             status, html = _http_get(url, timeout=timeout)
         except (OSError, TimeoutError, ValueError) as e:
             return ActionResult.net_error(f"DDG 请求失败: {e}")
 
         # 202（anomaly 限流）：先退避覆盖实测 ~4 分钟封禁窗口，再返回 BLOCKED。
         if status == 202:
diff --git a/fetcher/tests/test_facebook_discover.py b/fetcher/tests/test_facebook_discover.py
index 94c7688..bb60706 100644
--- a/fetcher/tests/test_facebook_discover.py
+++ b/fetcher/tests/test_facebook_discover.py
@@ -308,20 +308,49 @@ class TestAtomHttpOutcomes(unittest.TestCase):
 
     def test_rhythm_range_respected(self):
         with mock.patch.object(fd, "_http_get",
                                return_value=(200, _sample_html())):
             ctx = _Ctx()
             _run({"query": "x", "sample_min": 90, "sample_max": 120}, ctx=ctx)
         self.assertEqual(len(ctx.waits), 1)
         self.assertGreaterEqual(ctx.waits[0], 90)
         self.assertLessEqual(ctx.waits[0], 120)
 
+    def test_timeout_zero_passed_through(self):
+        """显式 timeout=0 不被 or 缺省吞掉（0 or 30 → 30 是反模式）。
+
+        None 判断语义：显式 0 是合法输入，原样传给 _http_get。
+        """
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())) as m:
+            ctx = _Ctx()
+            r = _run({"query": "x", "timeout": 0}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.OK)
+        self.assertEqual(m.call_args[1]["timeout"], 0)
+
+    def test_sample_zero_not_swallowed_by_or_default(self):
+        """显式 sample_min=0/sample_max=0 不被 or 缺省吞掉。
+
+        直接断言传给 random.uniform 的区间（参数解析层，确定性）：
+        None 判断语义下 sample_min=0 被 floor 抬到 60、sample_max=0 被
+        max(sample_max, sample_min) 抬到 60 → uniform(60.0, 60.0)；
+        or 反模式下 sample_max 走 `0 or (60+20)` → uniform(60.0, 80.0)。
+        """
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())):
+            with mock.patch.object(fd.random, "uniform") as uni:
+                uni.return_value = 61.0
+                ctx = _Ctx()
+                _run({"query": "x", "sample_min": 0, "sample_max": 0},
+                     ctx=ctx)
+        self.assertEqual(uni.call_args[0], (60.0, 60.0))
+
 
 class _FakeResp:
     """最小 urllib 响应替身：可带 gzip 头。"""
 
     def __init__(self, body: bytes, encoding: str | None = None):
         self._body = body
         self.headers = {}
         if encoding:
             self.headers["Content-Encoding"] = encoding
         self.status = 200
