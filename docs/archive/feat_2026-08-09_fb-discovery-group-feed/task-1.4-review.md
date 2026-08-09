# Step 1.4 review package
59812e1 feat(fb): Step 1.4 discover_fb 队列注册——_build_registry 追加 local QueueSpec（TDD）
 .../task-1.4-brief.md                              | 63 ++++++++++++++++
 .../task-1.4-report.md                             | 86 ++++++++++++++++++++++
 fetcher/fetcher/cli/main.py                        | 12 +++
 fetcher/tests/test_cli_fb.py                       | 20 ++++-
 4 files changed, 179 insertions(+), 2 deletions(-)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-brief.md
new file mode 100644
index 0000000..6a3537d
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-brief.md
@@ -0,0 +1,63 @@
+# Step 1.4 — discover_fb 队列注册（TDD）
+
+> 这是你的需求唯一来源。PLAN Step 1.4 原文 + SPEC §5.4 精确规格抄录如下。
+
+## PLAN Step 1.4 原文（验收以 checkbox 为准）
+
+- [ ] `fetcher/fetcher/cli/main.py _build_registry` 追加
+      `QueueSpec(queue="discover_fb", site=None, task=FbDiscoverTask(), topup=None,
+      domain_suffix="", requires={"local"})`
+- [ ] 测试（并入 test_fb_discover_task.py 或 test_cli_fb.py）：注册存在 + 字段
+      断言（site=None、requires={"local"}、topup=None）
+- 预估 20min；验收：注册测试全绿 + `--queues discover_fb` 动态校验通过
+
+## SPEC §5.4 队列注册（精确规格）
+
+```python
+specs.append(QueueSpec(
+    queue="discover_fb", site=None,
+    task=FbDiscoverTask(),
+    topup=None,                      # 货源=平台批次参数，无自喂
+    domain_suffix="",
+    requires={"local"},
+))
+```
+
+## 协调者裁定
+
+1. **插入位置**：`fetcher/fetcher/cli/main.py` 的 `_build_registry` 中，wa_check 条件
+   守卫块之后、`if selected_queues:` 过滤之前（与 crawl_fb_post 等既有队列并列；
+   参照现有 crawl_fb_post QueueSpec 的写法）。
+2. **导入**：main.py 顶部或函数内延迟导入 FbDiscoverTask（延迟导入对齐 crawl_fb_post
+   的 site_fb.make_task 模式——但 FbDiscoverTask 是直接实例化，参考 wa_check 的
+   `from fetcher.wa_task import WaCheckTask` 延迟导入方式）。
+3. **测试位置**：并入 `fetcher/tests/test_cli_fb.py`（既有文件，含 crawl_fb_post 注册
+   测试模式）或新建断言。参照 test_cli_fb.py 既有注册测试的写法——先读它，按它的
+   模式加 discover_fb 注册断言（spec.queue/site/task 类型/requires/topup/domain_suffix）。
+4. **`--queues discover_fb` 动态校验**：daemon argparse 的 choices 来自
+   `_build_registry()` 的 queue 列表——新增队列后 `python -m fetcher daemon
+   --queues discover_fb --help` 或注册测试断言 registry 含该队列即可（若既有测试
+   已覆盖 choices 派生，沿用）。
+
+## 代码库上下文
+
+- `fetcher/fetcher/cli/main.py`：`_build_registry(selected_queues)` 函数（约 222 行起），
+  wa_check 块在约 294-303 行，`if selected_queues:` 过滤在约 307 行。QueueSpec 从
+  `fetcher.control.queue_router` 导入。
+- `fetcher/tests/test_cli_fb.py`：既有 crawl_fb_post 注册测试，读它按同模式加断言。
+- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
+  -s tests -p "test_cli_fb.py"`；回归 `-p "test_fb_*.py"`。
+
+## TDD 纪律
+
+1. 先失败测试 → RED → 最小实现 → GREEN。
+2. 测试覆盖：registry 含 discover_fb、字段断言（queue/site=None/task 是
+   FbDiscoverTask 实例/requires=={"local"}/topup is None/domain_suffix==""）。
+3. 输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`fetcher/fetcher/cli/main.py`、`fetcher/tests/test_cli_fb.py`（或新
+  测试文件）、`docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 1.4 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-report.md
new file mode 100644
index 0000000..91ab985
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-report.md
@@ -0,0 +1,86 @@
+# Step 1.4 报告 — discover_fb 队列注册（TDD）
+
+## 实现了什么
+
+`fetcher/fetcher/cli/main.py` 的 `_build_registry`（约 wa_check 条件守卫块之后、
+`if selected_queues:` 过滤之前）追加 discover_fb QueueSpec：
+
+```python
+# discover_fb（FB discovery：本地队列，无 site、无浏览器，LocalLoop 消费；
+# 货源=平台批次参数直接入 work_items，无自喂 → topup=None）
+from fetcher.sites.facebook.discover_task import FbDiscoverTask  # 延迟导入
+specs.append(QueueSpec(
+    queue="discover_fb",
+    site=None,
+    task=FbDiscoverTask(),
+    topup=None,
+    domain_suffix="",
+    requires={"local"},
+))
+```
+
+- 与 wa_check 并列的第二个 local 队列（`requires={"local"}`，LocalLoop 消费）；
+- `site=None`（非站点队列，不占浏览器席位、不进 policies/browser_specs）；
+- `topup=None`（货源=平台批次参数直接入 work_items，无自喂）；
+- 延迟导入对齐协调者裁定（参考 wa_check 直接实例化方式，不改顶部 import）。
+
+## 测了什么（`fetcher/tests/test_cli_fb.py`，新增 1 个测试，共 5 个）
+
+- `test_discover_fb_registered`：registry 含 `discover_fb`，断言
+  `queue=="discover_fb"`、`site is None`、`domain_suffix==""`、
+  `requires=={"local"}`、`task` 是 `FbDiscoverTask` 实例、`topup is None`。
+  参照既有 `test_crawl_fb_post_registered` 的字段断言模式（spec.queue/site/task
+  类型/requires/topup/domain_suffix）。
+- 既有 `test_queues_choices_accept_fb` 已覆盖「registry 即 argparse choices 派生
+  来源」的动态校验模式——discover_fb 入 registry 后 `--queues discover_fb` 自然
+  通过（协调者裁定 4：沿用既有覆盖即可）。
+
+## TDD 证据
+
+**RED**（实现前，测试先写）：
+```
+$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_cli_fb.py"
+AssertionError: 'discover_fb' not found in {'crawl_1688_contact': QueueSpec(...), ...}
+----------------------------------------------------------------------
+Ran 5 tests in 0.028s
+FAILED (failures=1)
+```
+失败原因符合预期：discover_fb 尚未注册进 `_build_registry`（功能缺失，不是断言
+笔误——registry 里 7 条既有队列全在，只缺新队列）。
+
+**GREEN**（最小实现后）：
+```
+$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_cli_fb.py"
+Ran 5 tests in 0.037s
+OK
+```
+
+**验收动态校验**（`--queues discover_fb`）：
+```
+$ python -c "from fetcher.cli.main import _build_registry; print([s.queue for s in _build_registry(['discover_fb'])])"
+['discover_fb']
+$ python -m fetcher daemon --queues discover_fb --help   # argparse 接受（choices 动态派生）
+```
+
+**回归**：
+- `-p "test_fb_*.py"`：Ran 42 tests, OK
+- 全量 `-p ""`：Ran 721 tests, OK（27.5s，输出干净无 error/warning）
+
+## 改动的文件
+
+- `fetcher/fetcher/cli/main.py`（`_build_registry` 追加 discover_fb QueueSpec）
+- `fetcher/tests/test_cli_fb.py`（新增 `test_discover_fb_registered` + docstring/import）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-report.md`（本报告）
+
+## 自查发现
+
+- **完整性**：brief 两项 checkbox 全部落实（注册存在+字段断言、`--queues discover_fb`
+  动态校验）；插入位置/导入方式/测试位置对齐协调者裁定 1-4。
+- **质量**：写法对齐 wa_check（直接实例化 local 队列）与 crawl_fb_post（注释标注
+  队列语义）；`topup=None` 语义与 crawl_mic_shop 等 feeder 队列一致。
+- **纪律**：未改 `if selected_queues:` 过滤、`reset_daemon_state`（discover_fb
+  topup=None 且 domain_suffix=""，天然不参与 in_progress 重置）等范围外代码；
+  测试仅加 1 个断言方法（不重复既有 choices 派生测试）。
+- **疑虑**：无。`reset_daemon_state` 对 discover_fb 无影响（topup=None 跳过），
+  Step 1.5 冒烟时 daemon 启动重置日志的 domain_suffix 列表会多一个空串后缀，
+  与 crawl_fb_post/wa_check 行为一致，属既有格式。
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index 29a53df..f024dce 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -305,20 +305,32 @@ def _build_registry(selected_queues: list[str] | None = None) -> list:
             site=None,
             task=WaCheckTask(),
             topup=wa_check_topup,
             domain_suffix="",
             requires={"local"},
         ))
     else:
         print("[daemon] [!] wa_check 未注册：vendor wa-check/check.js 或"
               " node 不可用（跳过本地队列）")
 
+    # discover_fb（FB discovery：本地队列，无 site、无浏览器，LocalLoop 消费；
+    # 货源=平台批次参数直接入 work_items，无自喂 → topup=None）
+    from fetcher.sites.facebook.discover_task import FbDiscoverTask  # 延迟导入
+    specs.append(QueueSpec(
+        queue="discover_fb",
+        site=None,
+        task=FbDiscoverTask(),
+        topup=None,
+        domain_suffix="",
+        requires={"local"},
+    ))
+
     if selected_queues:
         specs = [s for s in specs if s.queue in selected_queues]
     return specs
 
 
 def reset_daemon_state(db, registry: list) -> tuple[int, int]:
     """daemon 启动崩溃恢复：全量回收 claimed + 逐有 topup 的队列重置
     in_progress（feeder 队列跳过——不产生 in_progress shops）。
 
     返回 (n_claimed_reset, n_in_progress_reset)。
diff --git a/fetcher/tests/test_cli_fb.py b/fetcher/tests/test_cli_fb.py
index 8df159c..2a8fdcc 100644
--- a/fetcher/tests/test_cli_fb.py
+++ b/fetcher/tests/test_cli_fb.py
@@ -1,25 +1,28 @@
 # -*- coding: utf-8 -*-
-"""Step 1.4: crawl_fb_post 队列注册测试。
+"""Step 1.4: crawl_fb_post / discover_fb 队列注册测试。
 
 覆盖：_build_registry 注册 crawl_fb_post QueueSpec（site/domain_suffix/
 requires/task 类型）、topup lambda 从 fb_posts 补货、--queues 动态校验
 包含 fb 队列、daemon prepare 经 FbPostTask.prepare 重置 fb_posts
-in_progress（reset_daemon_state 不覆盖 fb_posts 的缺口补位）。
+in_progress（reset_daemon_state 不覆盖 fb_posts 的缺口补位）；
+FB discovery 的 discover_fb 队列注册（site=None/topup=None/
+requires={"local"}，FbDiscoverTask 实例）。
 """
 
 import json
 import tempfile
 import unittest
 from pathlib import Path
 
 from fetcher import ShopDB
+from fetcher.sites.facebook.discover_task import FbDiscoverTask
 from fetcher.sites.facebook.post_task import FbPostTask
 
 POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
             "1437583168191347/")
 
 
 def _seed_posts(db, n=3):
     for i in range(n):
         db.conn.execute(
             "INSERT INTO fb_posts (url, group_id, group_name, keyword,"
@@ -46,20 +49,33 @@ class FbQueueRegistrationTest(unittest.TestCase):
     def test_crawl_fb_post_registered(self):
         reg = self._registry()
         self.assertIn("crawl_fb_post", reg)
         spec = reg["crawl_fb_post"]
         self.assertEqual(spec.site, "facebook")
         self.assertEqual(spec.domain_suffix, "")
         self.assertEqual(spec.requires, {"channel", "browser"})
         self.assertIsInstance(spec.task, FbPostTask)
         self.assertIsNotNone(spec.topup)
 
+    def test_discover_fb_registered(self):
+        """discover_fb：local 消费者注册（site=None、topup=None、
+        requires={"local"}），task 是 FbDiscoverTask 实例。"""
+        reg = self._registry()
+        self.assertIn("discover_fb", reg)
+        spec = reg["discover_fb"]
+        self.assertEqual(spec.queue, "discover_fb")
+        self.assertIsNone(spec.site)
+        self.assertEqual(spec.domain_suffix, "")
+        self.assertEqual(spec.requires, {"local"})
+        self.assertIsInstance(spec.task, FbDiscoverTask)
+        self.assertIsNone(spec.topup)
+
     def test_fb_topup_feeds_work_items(self):
         """topup lambda：pending fb_posts → work_items，payload 键 url/domain/name。"""
         _seed_posts(self.db, 3)
         spec = self._registry()["crawl_fb_post"]
         n = spec.topup(self.db, 10)
         self.assertEqual(n, 3)
         items = self.db.conn.execute(
             "SELECT * FROM work_items WHERE queue='crawl_fb_post'"
         ).fetchall()
         self.assertEqual(len(items), 3)
