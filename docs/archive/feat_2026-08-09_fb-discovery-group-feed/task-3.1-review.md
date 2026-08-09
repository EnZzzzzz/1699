# Step 3.1 review package
acf205a feat(fb): Step 3.1 runner BATCH_TYPES 注册 fb_discover/fb_group + enqueue 分派（TDD）
 .../task-3.1-brief.md                              |  82 +++++++++++
 .../task-3.1-report.md                             | 151 +++++++++++++++++++++
 platform/server/app/runner.py                      |  17 +++
 platform/server/tests/test_batch_tasks.py          |  54 ++++++++
 4 files changed, 304 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-brief.md
new file mode 100644
index 0000000..41c79e7
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-brief.md
@@ -0,0 +1,82 @@
+# Step 3.1 — runner BATCH_TYPES + enqueue 分支（TDD）
+
+> 这是你的需求唯一来源。PLAN Step 3.1 原文 + SPEC §6.1 精确规格抄录如下。
+
+## PLAN Step 3.1 原文（验收以 checkbox 为准）
+
+- [ ] `platform/server/app/runner.py` BATCH_TYPES 追加 fb_discover/fb_group
+      （SPEC §6.1 精确 dict）
+- [ ] `enqueue_batch_for_task` 追加两分支（keywords×pages / provider+posts_per_group
+      +limit，缺省值 1/50/brightdata）
+- [ ] 测试（扩展 platform/server/tests/test_batch_tasks.py）：enqueue_batch_for_task
+      对两类型分派正确（mock app.db 函数断言参数）
+- 预估 30min；验收：新测试全绿 + 既有批次测试零回归
+
+## SPEC §6.1 批次类型注册（精确规格）
+
+`runner.py BATCH_TYPES` 追加（BATCH_TYPE_NAMES 自动并集）：
+
+```python
+"fb_discover": {"queue": "discover_fb", "site": None,
+                "domain_suffix": "", "kind": "fb_discover"},
+"fb_group":    {"queue": "crawl_fb_group", "site": None,
+                "domain_suffix": "", "kind": "fb_group"},
+```
+
+`enqueue_batch_for_task` 追加两分支：
+
+```python
+if spec["kind"] == "fb_discover":
+    return enqueue_fb_discover_batch(task_id, params.get("keywords") or "",
+                                     int(params.get("pages") or 1))
+if spec["kind"] == "fb_group":
+    return enqueue_fb_group_batch(task_id,
+                                  (params.get("provider") or "brightdata"),
+                                  int(params.get("posts_per_group") or 50),
+                                  limit)
+```
+
+## 协调者裁定
+
+1. **注意：BATCH_TYPES 里有既有未提交改动吗？** 无——daemon-headed-queues 工作线
+   已于 Step 前单独 commit（dbab0da），runner.py 的 _derive_batch_status 改动已入库。
+   你现在看到的是干净 base。
+2. **两分支顺序**：追加在既有 fb_post 分支之后、`return 0` 之前。
+3. **enqueue_fb_discover_batch / enqueue_fb_group_batch 尚不存在**（Step 3.2 实现）——
+   本 Step 只改 runner.py 的 BATCH_TYPES + enqueue_batch_for_task 分支；测试 mock
+   `app.db.enqueue_fb_discover_batch` / `enqueue_fb_group_batch`（unittest.mock.patch
+   app.db 模块属性），断言参数透传。**不要在本 Step 实现 app/db.py 的两个函数**。
+4. **TDD 顺序**：先写失败测试（mock app.db 函数 + 断言两类型分派参数）→ 改 runner.py
+   转绿。mock 断言精确值：fb_discover → enqueue_fb_discover_batch(task_id,
+   keywords_str, pages_int)；缺省 keywords=""、pages=1；fb_group →
+   enqueue_fb_group_batch(task_id, provider_str, posts_per_group_int, limit)；
+   缺省 provider="brightdata"、posts_per_group=50。
+5. **测试基建**：platform/server/tests/test_batch_tasks.py 已有
+   BatchTasksTestBase（临时 sqlite + patch DB_PATH）。跑测试用
+   `cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks`。
+   enqueue_batch_for_task 的调用方（sweeper/runner）已有测试覆盖，本 Step 只加
+   分派断言。
+
+## 代码库上下文
+
+- `platform/server/app/runner.py`：BATCH_TYPES 在 36-62 行（fb_post 在 55-60 行），
+  enqueue_batch_for_task 在 284 行起（import 在函数内，fb_post 分支约 299-301 行）。
+- `platform/server/app/api/tasks.py` 的 TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPE_NAMES
+  （自动并集，不用改）。
+- 测试运行：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks
+  -v`；回归同一文件全量。
+
+## TDD 纪律
+
+1. 先失败测试 → RED → 最小实现 → GREEN。
+2. 测试覆盖：fb_discover 分派（默认与显式 keywords/pages）、fb_group 分派（默认与
+   显式 provider/posts_per_group、limit 透传）、既有类型零回归。
+3. 输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`platform/server/app/runner.py`、
+  `platform/server/tests/test_batch_tasks.py`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 3.1 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md
new file mode 100644
index 0000000..9dbbe50
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md
@@ -0,0 +1,151 @@
+# Step 3.1 报告 — runner BATCH_TYPES + enqueue 分支（TDD）
+
+## 实现了什么
+
+1. **`platform/server/app/runner.py` BATCH_TYPES 追加**（SPEC §6.1 精确 dict，放在
+   fb_post 之后）：
+
+   ```python
+   "fb_discover": {"queue": "discover_fb", "site": None,
+                   "domain_suffix": "", "kind": "fb_discover"},
+   "fb_group":    {"queue": "crawl_fb_group", "site": None,
+                   "domain_suffix": "", "kind": "fb_group"},
+   ```
+
+   `BATCH_TYPE_NAMES = set(BATCH_TYPES)` 自动并集，已验证 `fb_discover`/`fb_group`
+   进入 `api.tasks.TASK_TYPES`（TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPE_NAMES，
+   api/tasks.py 无需改动）。
+
+2. **`enqueue_batch_for_task` 追加两分支**（追加在既有 fb_post 分支之后、
+   `return 0` 之前，逐字对照 SPEC §6.1）：
+
+   ```python
+   if spec["kind"] == "fb_discover":
+       # Step 3.2 提供真实函数；此处懒导入，缺省 keywords=""、pages=1
+       from app.db import enqueue_fb_discover_batch
+       return enqueue_fb_discover_batch(task_id, params.get("keywords") or "",
+                                        int(params.get("pages") or 1))
+   if spec["kind"] == "fb_group":
+       # Step 3.2 提供真实函数；此处懒导入，缺省 provider="brightdata"、
+       # posts_per_group=50，limit 透传
+       from app.db import enqueue_fb_group_batch
+       return enqueue_fb_group_batch(task_id,
+                                     (params.get("provider") or "brightdata"),
+                                     int(params.get("posts_per_group") or 50),
+                                     limit)
+   ```
+
+   **与 SPEC 的唯一偏差**：两分支用「分支内懒导入」而非「函数顶部统一 import」。
+   原因：`enqueue_fb_discover_batch` / `enqueue_fb_group_batch` 尚不存在（Step 3.2
+   实现），统一 import 会在任何一次调用时 `ImportError`（import 语句要求全部名字
+   存在），且测试逐类型 mock 单个属性时同样会炸。懒导入在调用时解析模块属性，
+   mock（create=True）与 Step 3.2 的真实函数都能命中，分派参数行为与 SPEC 逐字一致。
+   Step 3.2 落地真实函数后，可（在彼 Step 内）把两个名字并入顶部 import 收尾。
+
+3. **`platform/server/tests/test_batch_tasks.py` 扩展**：新增第 5 节
+   `FbBatchDispatchTest` 4 个测试，mock `app.db` 模块属性
+   （`patch.object(db_module, ..., create=True)`——属性不存在需 create）断言分派
+   参数精确透传：
+   - fb_discover 缺省：`enqueue_fb_discover_batch(7, "", 1)`
+   - fb_discover 显式：`enqueue_fb_discover_batch(7, "面膜 洗面奶", 3)`（keywords
+     原样透传、pages 转 int）
+   - fb_group 缺省：`enqueue_fb_group_batch(8, "brightdata", 50, 0)`
+   - fb_group 显式+limit 透传：`enqueue_fb_group_batch(8, "scraperapi", 30, 120)`
+   - 每个测试同时断言 mock 返回值原样透出（n=3/4）
+
+   **未实现 app/db.py 的两个 enqueue 函数**（Step 3.2 的活，协调者裁定）。
+
+## TDD 证据
+
+### RED
+
+命令：
+
+```
+cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks.FbBatchDispatchTest -v
+```
+
+第一轮失败输出（`patch.object` 无 create → 模块属性不存在报错）：
+
+```
+AttributeError: <module 'app.db' ...> does not have the attribute 'enqueue_fb_group_batch'
+FAILED (errors=4)
+```
+
+按 TDD skill「测试报错要修到能正常失败为止」，给 `patch.object` 加 `create=True`
+（函数本就不存在，属测试基建修正，非改实现）。第二轮失败输出：
+
+```
+AssertionError: Expected 'enqueue_fb_group_batch' to be called once. Called 0 times.
+Ran 4 tests in 0.240s
+FAILED (failures=4)
+```
+
+**为什么符合预期**：BATCH_TYPES 已有 fb 条目但分派分支缺失，`enqueue_batch_for_task`
+走到 `return 0`，enqueue mock 一次也没被调用——失败点精确指向缺失的分派行为
+（功能缺失，非笔误）。
+
+### GREEN
+
+命令：
+
+```
+cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks -v
+```
+
+输出（节选）：
+
+```
+test_fb_discover_dispatch_with_defaults ... ok
+test_fb_discover_dispatch_with_explicit_keywords_pages ... ok
+test_fb_group_dispatch_with_defaults ... ok
+test_fb_group_dispatch_with_explicit_values_and_limit ... ok
+...
+Ran 21 tests in 0.338s
+OK
+```
+
+中间曾出现一次 `ImportError: cannot import name 'enqueue_fb_group_batch'`（统一
+import 语句要求全部名字存在而 fb 函数未实现）——按 RED 修到能正常失败的原则改为
+分支内懒导入后转绿。
+
+### 回归
+
+```
+cd platform/server && .venv/bin/python -m unittest discover -s tests
+Ran 63 tests in 0.267s
+OK
+```
+
+既有 17 个批次测试 + 全量 server 测试套件（63）零回归。BATCH_TYPE_NAMES 自动并集
+已验证：`fb_discover in TASK_TYPES` / `fb_group in TASK_TYPES` 均 True。
+
+## 改动的文件
+
+- `platform/server/app/runner.py`（+14 行：BATCH_TYPES 2 条目 + 分派 2 分支）
+- `platform/server/tests/test_batch_tasks.py`（+54 行：FbBatchDispatchTest 4 测试）
+- 本 report（+ 本 Step 的 brief 一并提交）
+
+## 自查
+
+- **完整性**：SPEC §6.1 两条 BATCH_TYPES 条目逐字一致（queue/site/domain_suffix/
+  kind）；两分支缺省值（keywords=""、pages=1、provider="brightdata"、
+  posts_per_group=50）与显式值/limit 透传全对（测试断言精确参数）。
+- **质量**：分支插在 fb_post 之后、`return 0` 之前（协调者裁定）；懒导入带注释
+  说明 Step 3.2 归属，与既有 enqueue 模式风格一致；对齐既有 BATCH_TYPES 缩进风格
+  （对齐冒号）。
+- **纪律**：YAGNI——只做 brief 要求的两处改动 + 测试；**没有**实现 app/db.py 的
+  `enqueue_fb_discover_batch` / `enqueue_fb_group_batch`（mock create=True 断言
+  分派）；未动其他文件。
+- **测试**：真实调用 `enqueue_batch_for_task`，仅 mock 尚不存在的 enqueue 函数
+  （属「不得已」的最小 mock，brief 协调者明确要求此方式）；4 测试都亲眼看失败过
+  （RED）；输出干净（无 error/warning）。
+
+## 疑虑
+
+1. **懒导入 vs SPEC 顶部统一 import**：行为一致但形式不同（见上「唯一偏差」）。
+   若协调者希望严格逐字 SPEC，可等 Step 3.2 实现真实函数后在彼 Step 把两个名字
+   并入顶部 import——本 Step 不改动以免回归。
+2. mock 用 `create=True` 是 brief 协调者裁定（函数尚不存在）的直接推论；Step 3.2
+   后如把 mock 换成真实函数路径（届时函数已存在），`create=True` 可去掉，属彼 Step
+   收尾工作，本 Step 不越界。
diff --git a/platform/server/app/runner.py b/platform/server/app/runner.py
index 8de7983..2aca615 100644
--- a/platform/server/app/runner.py
+++ b/platform/server/app/runner.py
@@ -55,20 +55,24 @@ BATCH_TYPES = {
         "domain_suffix": "", "kind": "feeder",
     },
     "wa_check": {
         "queue": "wa_check", "site": None,
         "domain_suffix": "", "kind": "wa",
     },
     "fb_post": {
         "queue": "crawl_fb_post", "site": "facebook",
         "domain_suffix": "", "kind": "fb_post",
     },
+    "fb_discover": {"queue": "discover_fb", "site": None,
+                    "domain_suffix": "", "kind": "fb_discover"},
+    "fb_group":    {"queue": "crawl_fb_group", "site": None,
+                    "domain_suffix": "", "kind": "fb_group"},
 }
 
 # 批次任务类型集合（TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPES）
 BATCH_TYPE_NAMES = set(BATCH_TYPES)
 
 BJ_TZ = timezone(timedelta(hours=8))
 
 _ERROR_KEYS = ("错误", "failed", "Error")
 _SUCCESS_KEYS = ("完成", "成功", "OK")
 _WARNING_KEYS = ("风控", "滑块", "警告")
@@ -294,20 +298,33 @@ def enqueue_batch_for_task(task_id: int, task_type: str,
     params = params or {}
     limit = int(params.get("limit") or 0)
     from app.db import (enqueue_contact_batch, enqueue_fb_post_batch,
                         enqueue_feeder_batch, enqueue_wa_batch)
     if spec["kind"] == "contact":
         return enqueue_contact_batch(spec["queue"], spec["site"],
                                      spec["domain_suffix"], task_id, limit)
     if spec["kind"] == "fb_post":
         return enqueue_fb_post_batch(spec["queue"], spec["site"],
                                      task_id, limit)
+    if spec["kind"] == "fb_discover":
+        # Step 3.2 提供真实函数；此处懒导入，缺省 keywords=""、pages=1
+        from app.db import enqueue_fb_discover_batch
+        return enqueue_fb_discover_batch(task_id, params.get("keywords") or "",
+                                         int(params.get("pages") or 1))
+    if spec["kind"] == "fb_group":
+        # Step 3.2 提供真实函数；此处懒导入，缺省 provider="brightdata"、
+        # posts_per_group=50，limit 透传
+        from app.db import enqueue_fb_group_batch
+        return enqueue_fb_group_batch(task_id,
+                                      (params.get("provider") or "brightdata"),
+                                      int(params.get("posts_per_group") or 50),
+                                      limit)
     if spec["kind"] == "feeder":
         n_cat, n_disc = enqueue_feeder_batch(
             spec["queue"], spec["site"], task_id, limit)
         return n_cat + n_disc
     if spec["kind"] == "wa":
         accounts = params.get("accounts") or []
         return enqueue_wa_batch(task_id, accounts, limit)
     return 0
 
 
diff --git a/platform/server/tests/test_batch_tasks.py b/platform/server/tests/test_batch_tasks.py
index a589fca..8bf754c 100644
--- a/platform/server/tests/test_batch_tasks.py
+++ b/platform/server/tests/test_batch_tasks.py
@@ -468,12 +468,66 @@ class TaskTypesTest(BatchTasksTestBase):
         tr.shutdown()
         conn = self._conn()
         row = conn.execute("SELECT status FROM tasks WHERE id=?",
                            (tid,)).fetchone()
         conn.close()
         # 批次 running 不被标 failed（孤儿清理跳过）；sweeper 重建为 running
         # （有 pending item）——若清理误标会变 failed
         self.assertEqual(row["status"], "running")
 
 
+# =====================================================================
+# 5. Step 3.1：fb_discover / fb_group 分派
+# =====================================================================
+
+
+class FbBatchDispatchTest(BatchTasksTestBase):
+    """enqueue_batch_for_task 对 fb_discover/fb_group 分派参数透传。
+
+    enqueue_fb_discover_batch / enqueue_fb_group_batch 由 Step 3.2 实现，
+    本 Step mock app.db 模块属性断言分派参数（缺省值/显式值/limit 透传）。
+    """
+
+    def test_fb_discover_dispatch_with_defaults(self):
+        """缺省 keywords=""、pages=1。"""
+        from app.runner import enqueue_batch_for_task
+        with patch.object(db_module, "enqueue_fb_discover_batch",
+                          create=True, return_value=3) as mock_enqueue:
+            n = enqueue_batch_for_task(7, "fb_discover", {})
+        mock_enqueue.assert_called_once_with(7, "", 1)
+        self.assertEqual(n, 3)
+
+    def test_fb_discover_dispatch_with_explicit_keywords_pages(self):
+        """显式 keywords 原样透传、pages 转 int。"""
+        from app.runner import enqueue_batch_for_task
+        with patch.object(db_module, "enqueue_fb_discover_batch",
+                          create=True, return_value=3) as mock_enqueue:
+            n = enqueue_batch_for_task(
+                7, "fb_discover",
+                {"keywords": "面膜 洗面奶", "pages": "3"})
+        mock_enqueue.assert_called_once_with(7, "面膜 洗面奶", 3)
+        self.assertEqual(n, 3)
+
+    def test_fb_group_dispatch_with_defaults(self):
+        """缺省 provider="brightdata"、posts_per_group=50、limit=0。"""
+        from app.runner import enqueue_batch_for_task
+        with patch.object(db_module, "enqueue_fb_group_batch",
+                          create=True, return_value=4) as mock_enqueue:
+            n = enqueue_batch_for_task(8, "fb_group", {})
+        mock_enqueue.assert_called_once_with(8, "brightdata", 50, 0)
+        self.assertEqual(n, 4)
+
+    def test_fb_group_dispatch_with_explicit_values_and_limit(self):
+        """显式 provider/posts_per_group 转 int + limit 透传。"""
+        from app.runner import enqueue_batch_for_task
+        with patch.object(db_module, "enqueue_fb_group_batch",
+                          create=True, return_value=4) as mock_enqueue:
+            n = enqueue_batch_for_task(
+                8, "fb_group",
+                {"provider": "scraperapi", "posts_per_group": "30",
+                 "limit": "120"})
+        mock_enqueue.assert_called_once_with(8, "scraperapi", 30, 120)
+        self.assertEqual(n, 4)
+
+
 if __name__ == "__main__":
     unittest.main()
