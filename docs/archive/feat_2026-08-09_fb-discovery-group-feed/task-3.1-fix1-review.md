# Step 3.1 fix round 1 review
61f36e2 style(fb): Step 3.1 fix1 BATCH_TYPES 新条目改为多行 dict 格式（纯格式）
 .../task-3.1-report.md                             | 53 ++++++++++++++++++++++
 platform/server/app/runner.py                      | 12 +++--
 2 files changed, 61 insertions(+), 4 deletions(-)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md
index 9dbbe50..84e8041 100644
--- a/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md
@@ -142,10 +142,63 @@ OK
   （RED）；输出干净（无 error/warning）。
 
 ## 疑虑
 
 1. **懒导入 vs SPEC 顶部统一 import**：行为一致但形式不同（见上「唯一偏差」）。
    若协调者希望严格逐字 SPEC，可等 Step 3.2 实现真实函数后在彼 Step 把两个名字
    并入顶部 import——本 Step 不改动以免回归。
 2. mock 用 `create=True` 是 brief 协调者裁定（函数尚不存在）的直接推论；Step 3.2
    后如把 mock 换成真实函数路径（届时函数已存在），`create=True` 可去掉，属彼 Step
    收尾工作，本 Step 不越界。
+
+---
+
+## 修复 1（review 第 1 轮发现 #1）— BATCH_TYPES 新条目格式对齐既有风格
+
+### 改了什么
+
+`platform/server/app/runner.py` BATCH_TYPES 中 fb_discover/fb_group 两条目由
+「行内紧凑 dict」改为与既有 7 条一致的多行 dict 格式（`{` 独占首行、每行 k-v、
+`},` 收尾），与 wa_check/fb_post 风格逐字对齐：
+
+```python
+"fb_discover": {
+    "queue": "discover_fb", "site": None,
+    "domain_suffix": "", "kind": "fb_discover",
+},
+"fb_group": {
+    "queue": "crawl_fb_group", "site": None,
+    "domain_suffix": "", "kind": "fb_group",
+},
+```
+
+键值（queue/site/domain_suffix/kind）、顺序、语义零变化——纯格式改动，行为不变。
+enqueue 分派分支与测试文件本修复未触碰。
+
+### 覆盖测试
+
+```
+cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks -v
+Ran 21 tests in 0.336s
+OK
+```
+
+全绿（含 FbBatchDispatchTest 4 测试 + 既有 17 批次测试）。
+
+### 全量回归
+
+```
+cd platform/server && .venv/bin/python -m unittest discover -s tests
+Ran 63 tests in 0.252s
+OK
+```
+
+零回归。
+
+### Commit
+
+`git add platform/server/app/runner.py docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md`
+（仅两文件，未 add -A）。
+
+### 疑虑
+
+无——格式与既有条目一致，行为零变化，测试全绿。
diff --git a/platform/server/app/runner.py b/platform/server/app/runner.py
index 2aca615..c3614e6 100644
--- a/platform/server/app/runner.py
+++ b/platform/server/app/runner.py
@@ -55,24 +55,28 @@ BATCH_TYPES = {
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
-    "fb_discover": {"queue": "discover_fb", "site": None,
-                    "domain_suffix": "", "kind": "fb_discover"},
-    "fb_group":    {"queue": "crawl_fb_group", "site": None,
-                    "domain_suffix": "", "kind": "fb_group"},
+    "fb_discover": {
+        "queue": "discover_fb", "site": None,
+        "domain_suffix": "", "kind": "fb_discover",
+    },
+    "fb_group": {
+        "queue": "crawl_fb_group", "site": None,
+        "domain_suffix": "", "kind": "fb_group",
+    },
 }
 
 # 批次任务类型集合（TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPES）
 BATCH_TYPE_NAMES = set(BATCH_TYPES)
 
 BJ_TZ = timezone(timedelta(hours=8))
 
 _ERROR_KEYS = ("错误", "failed", "Error")
 _SUCCESS_KEYS = ("完成", "成功", "OK")
 _WARNING_KEYS = ("风控", "滑块", "警告")
