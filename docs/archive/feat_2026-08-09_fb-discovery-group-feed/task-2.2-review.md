# Step 2.2 review package
b9c6ad5 feat(fb): Step 2.2 crawl_fb_group 队列注册——_build_registry 追加 local QueueSpec（TDD）
 .../task-2.2-brief.md                              | 57 +++++++++++++
 .../task-2.2-report.md                             | 99 ++++++++++++++++++++++
 fetcher/fetcher/cli/main.py                        | 13 +++
 fetcher/tests/test_cli_fb.py                       | 14 +++
 4 files changed, 183 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.2-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.2-brief.md
new file mode 100644
index 0000000..911934f
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.2-brief.md
@@ -0,0 +1,57 @@
+# Step 2.2 — crawl_fb_group 队列注册（TDD）
+
+> 这是你的需求唯一来源。PLAN Step 2.2 原文 + SPEC §5.4 精确规格抄录如下。
+
+## PLAN Step 2.2 原文（验收以 checkbox 为准）
+
+- [ ] `_build_registry` 追加 `QueueSpec(queue="crawl_fb_group", site=None,
+      task=FbGroupTask(), topup=None, domain_suffix="", requires={"local"})`
+- [ ] 测试：注册存在 + 字段断言
+- 预估 15min；验收：注册测试全绿 + `--queues crawl_fb_group` 校验通过
+
+## SPEC §5.4 队列注册（精确规格）
+
+```python
+specs.append(QueueSpec(
+    queue="crawl_fb_group", site=None,
+    task=FbGroupTask(),
+    topup=None,                      # 货源=平台批次参数（fb_groups pending）
+    domain_suffix="",
+    requires={"local"},
+))
+```
+
+## 协调者裁定
+
+1. **插入位置**：`fetcher/fetcher/cli/main.py` 的 `_build_registry` 中，紧随
+   discover_fb 队列之后（Step 1.4 已加的块）、`if selected_queues:` 过滤之前。
+2. **导入**：延迟导入 FbGroupTask（与 discover_fb 的 FbDiscoverTask 延迟导入一致）。
+3. **测试位置**：`fetcher/tests/test_cli_fb.py`，参照 Step 1.4 的
+   `test_discover_fb_registered` 写法加 `test_crawl_fb_group_registered`
+   （queue/site=None/task 是 FbGroupTask 实例/requires=={"local"}/topup is None/
+   domain_suffix==""）。
+4. **`--queues crawl_fb_group` 动态校验**：注册测试断言 registry 含该队列即可
+   （argparse choices 派生自 _build_registry，与 Step 1.4 同机制）。
+5. 不改 selected_queues 过滤 / reset_daemon_state。
+
+## 代码库上下文
+
+- `fetcher/fetcher/cli/main.py`：`_build_registry` 约 222 行起，discover_fb 块在
+  约 316-328 行（Step 1.4 加入），紧随其后插入 crawl_fb_group 块。
+- `fetcher/tests/test_cli_fb.py`：Step 1.4 已加 `test_discover_fb_registered`
+  （63-73 行附近），按同模式加新断言。
+- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
+  -s tests -p "test_cli_fb.py"`；回归 `-p "test_fb_*.py"`。
+
+## TDD 纪律
+
+1. 先失败测试 → RED → 最小实现 → GREEN。
+2. 测试覆盖：registry 含 crawl_fb_group、字段断言全齐。
+3. 输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`fetcher/fetcher/cli/main.py`、`fetcher/tests/test_cli_fb.py`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 2.2 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.2-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.2-report.md
new file mode 100644
index 0000000..07025ed
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.2-report.md
@@ -0,0 +1,99 @@
+# Step 2.2 报告 — crawl_fb_group 队列注册（TDD）
+
+## 实现了什么
+
+按 SPEC §5.4 / PLAN Step 2.2 精确规格，在 `fetcher/fetcher/cli/main.py` 的
+`_build_registry` 中、紧随 discover_fb 块之后（`if selected_queues:` 过滤之前）追加：
+
+```python
+# crawl_fb_group（FB 群全量采集：本地队列，无 site、无浏览器，
+# LocalLoop 消费；货源=平台批次参数（fb_groups pending）直接入
+# work_items，无自喂 → topup=None）
+from fetcher.sites.facebook.group_task import FbGroupTask  # 延迟导入
+specs.append(QueueSpec(
+    queue="crawl_fb_group",
+    site=None,
+    task=FbGroupTask(),
+    topup=None,
+    domain_suffix="",
+    requires={"local"},
+))
+```
+
+与协调者裁定逐条对齐：
+1. 插入位置：discover_fb 块之后、`if selected_queues:` 之前 ✓
+2. 延迟导入 FbGroupTask（与 discover_fb 的 FbDiscoverTask 延迟导入一致）✓
+3. 测试位置 `fetcher/tests/test_cli_fb.py`，仿 `test_discover_fb_registered` 写法 ✓
+4. `--queues crawl_fb_group` 动态校验：argparse choices 派生自 `_build_registry`
+   （与 Step 1.4 同机制）✓
+5. 未改 `if selected_queues:` 过滤、`reset_daemon_state` ✓
+
+## 测了什么
+
+`fetcher/tests/test_cli_fb.py` 新增 `test_crawl_fb_group_registered`，断言全齐：
+
+- registry 含 `crawl_fb_group`
+- `spec.queue == "crawl_fb_group"`
+- `spec.site is None`
+- `spec.domain_suffix == ""`
+- `spec.requires == {"local"}`
+- `spec.task` 是 `FbGroupTask` 实例
+- `spec.topup is None`
+
+## 测试结果
+
+- 单文件：`python -m unittest discover -s tests -p "test_cli_fb.py"` → `Ran 6 tests OK`
+- 回归：`-p "test_fb_*.py"` → `Ran 56 tests OK`
+- 动态校验：`python -m fetcher daemon --queues crawl_fb_group --help` → argparse
+  接受（exit 0）；`--queues bogus_q` 报错列出的可选队列含 `crawl_fb_group`。
+
+## TDD 证据
+
+### RED
+
+先只加测试、不加实现，运行：
+
+```
+$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_cli_fb.py"
+F.....
+FAIL: test_crawl_fb_group_registered ...
+AssertionError: 'crawl_fb_group' not found in {'crawl_1688_contact': ..., 'discover_fb': ...}
+Ran 6 tests in 0.035s
+FAILED (failures=1)
+```
+
+失败输出正是预期：`crawl_fb_group` 不在 registry 里（可选队列列表里也没有它）。
+符合预期——队列尚未注册，测试先行暴露缺口。
+
+### GREEN
+
+加最小实现（main.py 追加一个 QueueSpec 块）后：
+
+```
+$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_cli_fb.py"
+Ran 6 tests in 0.036s
+OK
+```
+
+输出干净（daemon 启动日志行 `[0] ... [1] ...` 是既有 reset 测试的正常 stdout，
+非失败信息）。
+
+## 改动的文件
+
+| 文件 | 改动 |
+|---|---|
+| `fetcher/fetcher/cli/main.py` | `_build_registry` 追加 crawl_fb_group QueueSpec（含延迟导入） |
+| `fetcher/tests/test_cli_fb.py` | 新增 `test_crawl_fb_group_registered` + 顶部导入 FbGroupTask |
+| `docs/feat_2026-08-09_fb-discovery-group-feed/task-2.2-report.md` | 本报告 |
+
+## 自查
+
+- **完整性**：brief 两项 checkbox 全落实（注册存在+字段断言、`--queues crawl_fb_group`
+  校验通过）。
+- **质量**：QueueSpec 字段与既有 discover_fb 块逐字段对齐（site=None/topup=None/
+  domain_suffix=""/requires={"local"}），注释风格一致（中文、说明货源与消费者）。
+- **纪律**：YAGNI——只加注册与测试，未触碰 selected_queues 过滤、reset_daemon_state、
+  消费者装配等无关代码。
+- **测试**：真实断言（registry 内容 + 全部 6 个字段），TDD 先红后绿，输出干净。
+- 疑虑：无。daemon 实跑未做冒烟（本 Step 只注册，消费逻辑在 Step 2.1 已实现
+  并有独立测试；冒烟属于 Phase 末 Step 的范畴，不在本 Step 验收内）。
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index f024dce..dfeb16e 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -317,20 +317,33 @@ def _build_registry(selected_queues: list[str] | None = None) -> list:
     from fetcher.sites.facebook.discover_task import FbDiscoverTask  # 延迟导入
     specs.append(QueueSpec(
         queue="discover_fb",
         site=None,
         task=FbDiscoverTask(),
         topup=None,
         domain_suffix="",
         requires={"local"},
     ))
 
+    # crawl_fb_group（FB 群全量采集：本地队列，无 site、无浏览器，
+    # LocalLoop 消费；货源=平台批次参数（fb_groups pending）直接入
+    # work_items，无自喂 → topup=None）
+    from fetcher.sites.facebook.group_task import FbGroupTask  # 延迟导入
+    specs.append(QueueSpec(
+        queue="crawl_fb_group",
+        site=None,
+        task=FbGroupTask(),
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
index 2a8fdcc..379a282 100644
--- a/fetcher/tests/test_cli_fb.py
+++ b/fetcher/tests/test_cli_fb.py
@@ -9,20 +9,21 @@ FB discovery 的 discover_fb 队列注册（site=None/topup=None/
 requires={"local"}，FbDiscoverTask 实例）。
 """
 
 import json
 import tempfile
 import unittest
 from pathlib import Path
 
 from fetcher import ShopDB
 from fetcher.sites.facebook.discover_task import FbDiscoverTask
+from fetcher.sites.facebook.group_task import FbGroupTask
 from fetcher.sites.facebook.post_task import FbPostTask
 
 POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
             "1437583168191347/")
 
 
 def _seed_posts(db, n=3):
     for i in range(n):
         db.conn.execute(
             "INSERT INTO fb_posts (url, group_id, group_name, keyword,"
@@ -62,20 +63,33 @@ class FbQueueRegistrationTest(unittest.TestCase):
         reg = self._registry()
         self.assertIn("discover_fb", reg)
         spec = reg["discover_fb"]
         self.assertEqual(spec.queue, "discover_fb")
         self.assertIsNone(spec.site)
         self.assertEqual(spec.domain_suffix, "")
         self.assertEqual(spec.requires, {"local"})
         self.assertIsInstance(spec.task, FbDiscoverTask)
         self.assertIsNone(spec.topup)
 
+    def test_crawl_fb_group_registered(self):
+        """crawl_fb_group：local 消费者注册（site=None、topup=None、
+        requires={"local"}），task 是 FbGroupTask 实例。"""
+        reg = self._registry()
+        self.assertIn("crawl_fb_group", reg)
+        spec = reg["crawl_fb_group"]
+        self.assertEqual(spec.queue, "crawl_fb_group")
+        self.assertIsNone(spec.site)
+        self.assertEqual(spec.domain_suffix, "")
+        self.assertEqual(spec.requires, {"local"})
+        self.assertIsInstance(spec.task, FbGroupTask)
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
