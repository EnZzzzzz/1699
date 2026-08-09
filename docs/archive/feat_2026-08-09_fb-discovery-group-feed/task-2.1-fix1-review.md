# Step 2.1 fix round 1 review
40e3de9 fix(fb): Step 2.1 review 修复——提取共享 group_id 解析（urls.py）+ on_success 逐帖口径 stats
 .../task-2.1-report.md                             | 85 ++++++++++++++++++++++
 fetcher/fetcher/sites/facebook/group_task.py       | 20 ++---
 fetcher/fetcher/sites/facebook/post_task.py        | 14 +---
 fetcher/fetcher/sites/facebook/urls.py             | 19 +++++
 fetcher/tests/test_fb_group_task.py                | 46 ++++++++++--
 fetcher/tests/test_fb_post_task.py                 | 11 +--
 6 files changed, 159 insertions(+), 36 deletions(-)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md
index 03e74db..47b5007 100644
--- a/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md
@@ -123,10 +123,95 @@ OK
   批次配额上游逻辑（Step 2.2/2.4 范围）。
 - **测试**：真实落库断言（临时 ShopDB）；mock 仅限原子层；13 覆盖 + 全量回归。
 
 ## 疑虑
 
 1. `test_fetch_defaults_provider_limit` 断言 fetch 把 `provider=None` 透传给原子——
    原子内部 `params.get("provider") or "brightdata"` 兜底，行为正确；若后续要
    严格只传三个键的意图不同，可再议（当前与裁定「透传 url/provider/limit」一致）。
 2. prepare/on_success 的 print 会在测试输出尾部出现（与 test_fb_post_task.py
    行为一致），非失败输出；如需测试输出零噪音可后续统一加 stdout 捕获。
+
+---
+
+## Fix 1 报告（review 发现修复，第 1 轮）
+
+## 状态
+
+**DONE** — 2 条 review 发现全部修复；group/post 任务测试 + 全量回归 735 测试通过。
+
+## 修复内容
+
+### 发现 1：`_group_id_from_url` / `_GROUP_RE` 逐字重复 → 提取共享
+
+- 新建 `fetcher/fetcher/sites/facebook/urls.py`（零依赖，仅 `re`）：
+  `group_id_from_url(url)` + `_GROUP_RE` 唯一来源（公共名，跨模块共享不再用
+  下划线私有名）。
+- `group_task.py` / `post_task.py`：删除各自的 `import re` + `_GROUP_RE` +
+  `_group_id_from_url` 定义，改为 `from fetcher.sites.facebook.urls import
+  group_id_from_url`，调用点 `_group_id_from_url(...)` → `group_id_from_url(...)`。
+  选 `urls.py` 而非 `__init__.py` 的理由：`__init__.py` 含 `FacebookPlugin` 与
+  `register_site` 副作用（import 即注册站点），放进去会让纯 URL 工具耦合站点
+  注册；`urls.py` 职责清晰且无循环依赖（task 模块 import 它时，包 `__init__`
+  已先加载，无新环）。
+- 行为零变更：正则与函数体逐字符一致；既有 `test_fb_post_task.py` /
+  `test_fb_group_task.py` 的 `test_group_id_from_url` 断言全部保持（仅 import
+  与调用名随共享位置更新）。
+
+### 发现 2：stats 依赖顶级 `data["phones"]` 聚合 → 改逐帖口径
+
+- `group_task.py on_success`：`has_contact` 与 stats ok/empty 判定改由逐帖
+  `post["phones"]` 推导——`phones = [ph for post in posts for ph in
+  ((post or {}).get("phones") or [])]`，`has_contact = bool(phones)`，
+  `phones` 非空 → ok+1（state 显示逐帖号码数），否则 empty+1。
+- 同时 `mark_fb_group_done` 的 `has_contact` 参数也走同一逐帖口径，彻底消除对
+  原子顶级 `phones`/`has_contact` 聚合字段的隐含依赖（原子结构变化不再影响
+  判定与回写）。
+
+## TDD 证据
+
+### RED
+
+新增测试 `test_on_success_stats_judged_per_post_phones`（场景 1：逐帖有号码但
+顶级聚合缺失 → 应 ok=1；场景 2：逐帖无号码但顶级聚合有值 → 应 empty=1）。
+
+命令：
+```
+cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_fb_group_task.py"
+```
+输出（失败）：
+```
+AssertionError: 0 != 1
+Ran 14 tests in 0.084s
+FAILED (failures=1)
+```
+符合预期：旧代码用顶级 `data.get("phones")`（缺失 → 判 empty），逐帖口径未生效。
+
+### GREEN
+
+实现 urls.py 提取 + on_success 逐帖口径后，同命令输出：
+```
+Ran 14 tests in 0.076s
+OK
+```
+
+## 回归
+
+- `-p "test_fb_post_task.py"`：OK（post_task 改动行为零回归，既有测试全绿）
+- `-p "test_fb_*.py"`：**56 测试 OK**（原 55 + 新增 1）
+- 全量 `-s tests`：**735 测试 OK**（原 734 + 新增 1，28.3s）
+
+## 改动的文件
+
+- `fetcher/fetcher/sites/facebook/urls.py`（新建，共享位置）
+- `fetcher/fetcher/sites/facebook/group_task.py`（去重 + 逐帖口径）
+- `fetcher/fetcher/sites/facebook/post_task.py`（去重，行为不变）
+- `fetcher/tests/test_fb_group_task.py`（新增逐帖口径测试 + import/调用名随共享）
+- `fetcher/tests/test_fb_post_task.py`（import/调用名随共享，断言不变）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md`（本文件）
+
+## 疑虑
+
+- Step 2.3 会再改 post_task.py：共享函数已就位，届时 `from
+  fetcher.sites.facebook.urls import group_id_from_url` 直接复用，无需再搬。
+- `len(phones)` 为逐帖号码总数（跨帖同号会重复计数，仅作 state 展示用，
+  不影响 ok/empty 判定与落库去重——`save_fb_contacts` 侧自有幂等）。
diff --git a/fetcher/fetcher/sites/facebook/group_task.py b/fetcher/fetcher/sites/facebook/group_task.py
index 5173020..75fd889 100644
--- a/fetcher/fetcher/sites/facebook/group_task.py
+++ b/fetcher/fetcher/sites/facebook/group_task.py
@@ -7,36 +7,26 @@
 done/failed 回写（post_count/has_contact/last_crawled_at）。
 
 FATAL 处置：缺 API key / 未知 provider → 原子返回 FATAL，Task 框架对
 FATAL 直接停止（on_giveup 不会被调），本 Task 不额外处理（SPEC §5.3）。
 
 分层：原子只做「拉 + 提取」，本 Task 做编排与落库（对齐 FbPostTask 模式）。
 """
 
 from __future__ import annotations
 
-import re
-
 from fetcher.control.task import Task
 from fetcher.core.types import ActionResult
+from fetcher.sites.facebook.urls import group_id_from_url
 
 QUEUE = "crawl_fb_group"
 
-# 从群 URL 解析 group_id：facebook.com/groups/{gid}（payload.url 是群 URL）
-_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")
-
-
-def _group_id_from_url(url: str) -> str | None:
-    """群 URL → 群 id；无/非法返回 None。"""
-    m = _GROUP_RE.search(url or "")
-    return m.group(1) if m else None
-
 
 class FbGroupTask(Task):
     """FB 群全量采集任务：认领 crawl_fb_group 队列的群工作项。"""
 
     name = "fb_group"
     unit = "群"
     batch_unit = ""
 
     QUEUE = QUEUE
 
@@ -118,34 +108,36 @@ class FbGroupTask(Task):
         return atom.run(ctx, {
             "url": item["url"],
             "provider": item.get("provider"),
             "limit": int(item.get("limit") or 10),
         })
 
     def on_success(self, ctx, item, result: ActionResult) -> int:
         """逐帖号码落 fb_contacts + 群置 done 回写三字段 + stats。"""
         data = result.data or {}
         posts = data.get("posts") or []
-        group_id = _group_id_from_url(item.get("url") or "")
+        group_id = group_id_from_url(item.get("url") or "")
         db = ctx.store.db
         # 逐帖落号：正文全文已在手，直接落库（无需再走 crawl_fb_post）
         n_new = 0
         for post in posts:
             post_url = (post or {}).get("url") or ""
             if not post_url:
                 continue
             n_new += db.save_fb_contacts(post_url, group_id,
                                          (post or {}).get("phones") or [])
-        has_contact = bool(data.get("has_contact") or data.get("phones"))
+        # 逐帖口径：任一帖有号码 → has_contact / ok（不依赖原子顶级聚合字段）
+        phones = [ph for post in posts
+                  for ph in ((post or {}).get("phones") or [])]
+        has_contact = bool(phones)
         db.mark_fb_group_done(item["url"], len(posts), has_contact)
         stats = self.wctx_stats(ctx)
-        phones = data.get("phones") or []
         if phones:
             stats["ok"] += 1
             state = f"✓ {len(phones)} 个号码（新增 {n_new}）"
         else:
             stats["empty"] += 1
             state = "○ 无联系方式"
         ctx.set_status(state=state, n=sum(stats.values()),
                        ok=stats["ok"], empty=stats["empty"],
                        failed=stats["failed"])
         return len(posts)  # 返回帖数（计入批次配额）
diff --git a/fetcher/fetcher/sites/facebook/post_task.py b/fetcher/fetcher/sites/facebook/post_task.py
index ae31395..fcea777 100644
--- a/fetcher/fetcher/sites/facebook/post_task.py
+++ b/fetcher/fetcher/sites/facebook/post_task.py
@@ -7,36 +7,26 @@ FetchFbPost 原子（匿名渲染抓 permalink + parse_post 四桶提取）→
 状态机 done/failed + has_contact 回写；微信/TG/邀请链接侧车随
 work_items.result_json 留存（观测用）。
 
 分层：原子只做「抓 + 提取」，本 Task 做编排与落库（SPEC §5.1 裁定：
 fetch 调 FetchFbPost 原子，不内联 page 操作）。匿名白板会话无需
 软着陆（cold_start 空实现）；warmup homepage 偏差接受（SPEC §7.3）。
 """
 
 from __future__ import annotations
 
-import re
-
 from fetcher.control.task import Task
 from fetcher.core.types import ActionResult
+from fetcher.sites.facebook.urls import group_id_from_url
 
 QUEUE = "crawl_fb_post"
 
-# 从群 URL 解析 group_id：facebook.com/groups/{gid}（payload.domain 是群 URL）
-_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")
-
-
-def _group_id_from_url(url: str) -> str | None:
-    """群 URL → 群 id；无/非法返回 None。"""
-    m = _GROUP_RE.search(url or "")
-    return m.group(1) if m else None
-
 
 class FbPostTask(Task):
     """FB 群帖采集任务：认领 crawl_fb_post 队列的帖子工作项。"""
 
     name = "post"
     unit = "帖"
     batch_unit = ""
 
     # 匿名 permalink 抓取：参照 1688 contact 的保守预算
     ip_request_budget = 60
@@ -129,21 +119,21 @@ class FbPostTask(Task):
         """有效帖页判据：DOM 正文非空且长度 ≥ 100（FB 帖页含遮罩文案，
         纯遮罩约 200 字符，有效帖页远超此值——阈值按 SPEC §5.1）。"""
         data = result.data or {}
         text = data.get("text") or ""
         return bool(text.strip()) and len(text) >= 100
 
     def on_success(self, ctx, item, result: ActionResult) -> int:
         """号码落 fb_contacts + fb_posts 置 done + 侧车副产物留 result_json。"""
         data = result.data or {}
         phones = data.get("phones") or []
-        group_id = _group_id_from_url(item.get("domain") or "")
+        group_id = group_id_from_url(item.get("domain") or "")
         db = ctx.store.db
         n_new = db.save_fb_contacts(item["url"], group_id, phones)
         has_contact = bool(data.get("has_contact"))
         db.mark_fb_post_done(item["url"], has_contact)
         # 侧车副产物（微信/TG/邀请链接）：非空才设，QueueRouter._finish
         # 经 ctx.state["result_json"] 落 work_items.result_json（SPEC §8）
         sidecar = {}
         for key in ("wechat_ids", "tg_handles", "wa_group_invites"):
             vals = data.get(key) or []
             if vals:
diff --git a/fetcher/fetcher/sites/facebook/urls.py b/fetcher/fetcher/sites/facebook/urls.py
new file mode 100644
index 0000000..915eda4
--- /dev/null
+++ b/fetcher/fetcher/sites/facebook/urls.py
@@ -0,0 +1,19 @@
+# -*- coding: utf-8 -*-
+"""Facebook URL 工具（group_task / post_task 共享）：群 URL → group_id 解析。
+
+单一来源：group_task.py（payload.url 是群 URL）与 post_task.py
+（payload.domain 是群 URL）都从这里取，改正则只需改一处。
+"""
+
+from __future__ import annotations
+
+import re
+
+# 从群 URL 解析 group_id：facebook.com/groups/{gid}
+_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")
+
+
+def group_id_from_url(url: str) -> str | None:
+    """群 URL → 群 id；无/非法返回 None。"""
+    m = _GROUP_RE.search(url or "")
+    return m.group(1) if m else None
diff --git a/fetcher/tests/test_fb_group_task.py b/fetcher/tests/test_fb_group_task.py
index b2c6d0a..f8bb15e 100644
--- a/fetcher/tests/test_fb_group_task.py
+++ b/fetcher/tests/test_fb_group_task.py
@@ -10,21 +10,22 @@ make_stats、on_abort 短语。全 mock 原子，不起真实网络/API；落库
 """
 
 import json
 import tempfile
 import unittest
 from pathlib import Path
 from unittest.mock import MagicMock
 
 from fetcher import RunConfig, ShopDB
 from fetcher.core.types import ActionResult, Outcome
-from fetcher.sites.facebook.group_task import FbGroupTask, _group_id_from_url
+from fetcher.sites.facebook.group_task import FbGroupTask
+from fetcher.sites.facebook.urls import group_id_from_url
 
 GROUP_URL = "https://www.facebook.com/groups/185879310028412"
 POST_URL_1 = GROUP_URL + "/posts/1111111111111/"
 POST_URL_2 = GROUP_URL + "/posts/2222222222222/"
 
 
 def _seed_group(db, url=GROUP_URL, status="pending"):
     db.conn.execute(
         "INSERT INTO fb_groups (url, group_id, name, source, status,"
         " first_seen_at) VALUES (?, '185879310028412',"
@@ -132,20 +133,55 @@ class FbGroupTaskTest(unittest.TestCase):
         # 群 done 回写三字段
         group = self.db.conn.execute(
             "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL,)).fetchone()
         self.assertEqual(group["status"], "done")
         self.assertEqual(group["post_count"], 2)
         self.assertEqual(group["has_contact"], 1)
         self.assertIsNotNone(group["last_crawled_at"])
         self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
         self.assertEqual(ctx.state["task"]["stats"]["empty"], 0)
 
+    def test_on_success_stats_judged_per_post_phones(self):
+        """stats ok/empty 判定基于逐帖 post['phones']，不依赖原子顶级
+        phones/has_contact 聚合（原子结构变化不影响判定）。"""
+        # 场景 1：逐帖有号码但顶级聚合缺失 → ok + has_contact=1
+        _seed_group(self.db)
+        ctx = self._ctx()
+        posts = [{"url": POST_URL_1, "text": "x" * 200,
+                  "phones": [{"number": "13812345678",
+                               "bucket": "cn_uncertain",
+                               "source": "text"}]}]
+        data = {"provider": "brightdata", "group_url": GROUP_URL,
+                "post_count": 1, "posts": posts}  # 顶级 phones/has_contact 缺失
+        self.task.on_success(ctx, {"url": GROUP_URL},
+                             ActionResult(Outcome.OK, "ok", data))
+        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
+        self.assertEqual(ctx.state["task"]["stats"]["empty"], 0)
+        self.assertEqual(self.db.conn.execute(
+            "SELECT has_contact FROM fb_groups WHERE url=?",
+            (GROUP_URL,)).fetchone()[0], 1)
+        # 场景 2：逐帖全无号码但顶级聚合有值 → empty + has_contact=0
+        url2 = GROUP_URL + "2"
+        _seed_group(self.db, url=url2)
+        ctx2 = self._ctx()
+        posts2 = [{"url": POST_URL_2, "text": "x" * 200, "phones": []}]
+        data2 = {"provider": "brightdata", "group_url": url2,
+                 "post_count": 1, "posts": posts2,
+                 "phones": [{"number": "1"}], "has_contact": True}
+        self.task.on_success(ctx2, {"url": url2},
+                             ActionResult(Outcome.OK, "ok", data2))
+        self.assertEqual(ctx2.state["task"]["stats"]["ok"], 0)
+        self.assertEqual(ctx2.state["task"]["stats"]["empty"], 1)
+        self.assertEqual(self.db.conn.execute(
+            "SELECT has_contact FROM fb_groups WHERE url=?",
+            (url2,)).fetchone()[0], 0)
+
     def test_on_success_no_phones_counts_empty_and_has_contact_0(self):
         _seed_group(self.db)
         ctx = self._ctx()
         r = _result(posts=[{"url": POST_URL_1, "text": "x" * 200,
                             "phones": []}])
         self.task.on_success(ctx, {"url": GROUP_URL}, r)
         group = self.db.conn.execute(
             "SELECT status, post_count, has_contact FROM fb_groups"
             " WHERE url=?", (GROUP_URL,)).fetchone()
         self.assertEqual(group["status"], "done")
@@ -215,20 +251,20 @@ class FbGroupTaskTest(unittest.TestCase):
                          {"ok": 0, "empty": 0, "failed": 0})
 
     def test_on_abort_phrase(self):
         phrase = self.task.on_abort(self._ctx(), {"url": GROUP_URL})
         self.assertIn("in_progress", phrase)
         self.assertIn(GROUP_URL, phrase)
 
     # ---- group_id 解析 ----
 
     def test_group_id_from_url(self):
-        self.assertEqual(_group_id_from_url(GROUP_URL),
+        self.assertEqual(group_id_from_url(GROUP_URL),
                          "185879310028412")
-        self.assertEqual(_group_id_from_url(GROUP_URL + "/"),
+        self.assertEqual(group_id_from_url(GROUP_URL + "/"),
                          "185879310028412")
-        self.assertIsNone(_group_id_from_url(""))
-        self.assertIsNone(_group_id_from_url("https://www.1688.com/"))
+        self.assertIsNone(group_id_from_url(""))
+        self.assertIsNone(group_id_from_url("https://www.1688.com/"))
 
 
 if __name__ == "__main__":
     unittest.main()
diff --git a/fetcher/tests/test_fb_post_task.py b/fetcher/tests/test_fb_post_task.py
index 58e6d19..21a9423 100644
--- a/fetcher/tests/test_fb_post_task.py
+++ b/fetcher/tests/test_fb_post_task.py
@@ -8,21 +8,22 @@ group_id 解析。全 mock 原子，不起真实浏览器/网络。
 """
 
 import json
 import tempfile
 import unittest
 from pathlib import Path
 from unittest.mock import MagicMock
 
 from fetcher import RunConfig, ShopDB, WorkerContext
 from fetcher.core.types import ActionResult, Outcome
-from fetcher.sites.facebook.post_task import FbPostTask, _group_id_from_url
+from fetcher.sites.facebook.post_task import FbPostTask
+from fetcher.sites.facebook.urls import group_id_from_url
 
 POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
             "1437583168191347/")
 GROUP_URL = "https://www.facebook.com/groups/185879310028412"
 
 
 def _seed_post(db, url=POST_URL, status="pending"):
     db.conn.execute(
         "INSERT INTO fb_posts (url, group_id, group_name, keyword, source,"
         " status, first_seen_at) VALUES (?, '185879310028412',"
@@ -235,19 +236,19 @@ class FbPostTaskTest(unittest.TestCase):
         self.assertEqual(item["url"], POST_URL)
         self.assertIn("id", item)
 
     def test_acquire_item_empty_queue_returns_none(self):
         ctx = self._ctx()
         self.assertIsNone(self.task.acquire_item(ctx))
 
     # ---- group_id 解析 ----
 
     def test_group_id_from_url(self):
-        self.assertEqual(_group_id_from_url(GROUP_URL),
+        self.assertEqual(group_id_from_url(GROUP_URL),
                          "185879310028412")
-        self.assertEqual(_group_id_from_url(GROUP_URL + "/"), "185879310028412")
-        self.assertIsNone(_group_id_from_url(""))
-        self.assertIsNone(_group_id_from_url("https://www.1688.com/"))
+        self.assertEqual(group_id_from_url(GROUP_URL + "/"), "185879310028412")
+        self.assertIsNone(group_id_from_url(""))
+        self.assertIsNone(group_id_from_url("https://www.1688.com/"))
 
 
 if __name__ == "__main__":
     unittest.main()
