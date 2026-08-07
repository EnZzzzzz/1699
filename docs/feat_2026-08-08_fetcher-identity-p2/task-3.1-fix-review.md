# Step 3.1-fix review 审查包（BASE 38296b5..HEAD 5fc0dbd）

## git log
5fc0dbd fix(identity-p2): summary 透传 db_path（临时库运行不再触碰生产库）

## git diff --stat
 fetcher/fetcher/control/engine.py            |   2 +-
 fetcher/fetcher/control/task.py              |   8 +-
 fetcher/fetcher/sites/alibaba1688/company.py |   4 +-
 fetcher/fetcher/sites/alibaba1688/contact.py |   4 +-
 fetcher/fetcher/sites/alibaba1688/shop.py    |   4 +-
 fetcher/fetcher/sites/madeinchina/contact.py |   4 +-
 fetcher/fetcher/sites/madeinchina/shop.py    |   4 +-
 fetcher/fetcher/sites/taobao/search.py       |   2 +-
 fetcher/fetcher/sites/yiwugo/contact.py      |   2 +-
 fetcher/fetcher/sites/yiwugo/search.py       |   2 +-
 fetcher/tests/test_engine.py                 |  19 +++-
 fetcher/tests/test_summary_db_path.py        | 129 +++++++++++++++++++++++++++
 12 files changed, 165 insertions(+), 19 deletions(-)

## git diff -U10
diff --git a/fetcher/fetcher/control/engine.py b/fetcher/fetcher/control/engine.py
index 1eedfab..f4bbed9 100644
--- a/fetcher/fetcher/control/engine.py
+++ b/fetcher/fetcher/control/engine.py
@@ -213,12 +213,12 @@ class Engine:
             for t in threads:
                 t.join()
         except KeyboardInterrupt:
             (board.log if board else print)(
                 "[!] 用户中断，等待各 worker 完成当前任务后退出...")
             self.stop.set()
             for t in threads:
                 t.join(timeout=90)
             (board.log if board else print)("[!] 进度已保存，下次运行自动续爬")
 
-        print(f"[OK] {self.task.summary(self.state['stats'])}")
+        print(f"[OK] {self.task.summary(self.state['stats'], self.config.resolved_db_path())}")
         return 0
diff --git a/fetcher/fetcher/control/task.py b/fetcher/fetcher/control/task.py
index bd26669..827cbe2 100644
--- a/fetcher/fetcher/control/task.py
+++ b/fetcher/fetcher/control/task.py
@@ -31,22 +31,26 @@ class Task:
     batch_unit = ""
     cold_start_before_acquire = False
     ip_request_budget: int | None = None
 
     # ---- main 阶段 ----
 
     def prepare(self, config) -> bool:
         """启动前准备（重置状态/打印计划）；返回 False 直接退出。"""
         return True
 
-    def summary(self, all_stats: dict) -> str:
-        """全部 worker 结束后的汇总行。"""
+    def summary(self, all_stats: dict, db_path=None) -> str:
+        """全部 worker 结束后的汇总行。
+
+        db_path: 数据库路径（str | Path），基类实现不读它；
+        子类可据此构造 ShopDB(db_path) 避免默认开生产库。
+        """
         return str(all_stats)
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         """状态行格式（StatusBoard compose 回调）。"""
         return str(f.get("line", ""))
 
     def make_stats(self) -> dict:
         """每个 worker 的统计字典（结构任务自定）。"""
diff --git a/fetcher/fetcher/sites/alibaba1688/company.py b/fetcher/fetcher/sites/alibaba1688/company.py
index 69379fa..e713367 100644
--- a/fetcher/fetcher/sites/alibaba1688/company.py
+++ b/fetcher/fetcher/sites/alibaba1688/company.py
@@ -197,26 +197,26 @@ class CompanyTask(Task):
         print(f"[1] 数据库现有店铺 {st['shops']} 个（pending {st['pending']} / "
               f"done {st['done']} / no_contact {st['no_contact']} / "
               f"failed {st['failed']}），每个 worker 每批 "
               f"{config.batch_num} 个店铺"
               f"（{'最多 ' + str(config.max_batches) + ' 批'
                  if config.max_batches else '不限批数'}），"
               f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
         db.close()
         return True
 
-    def summary(self, all_stats: dict) -> str:
+    def summary(self, all_stats: dict, db_path=None) -> str:
         from fetcher.db import ShopDB  # 延迟导入
         shops = sum(s.get("shops", 0) for s in all_stats.values())
         new = sum(s.get("new", 0) for s in all_stats.values())
         pages = sum(s.get("pages", 0) for s in all_stats.values())
-        db = ShopDB()
+        db = ShopDB(db_path)
         stats = db.stats()
         db.close()
         return (f"本次黄页采集: {pages} 页, 店铺 {shops} 个（新增 {new}）"
                 f"\n    数据库统计: {stats}")
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                 f"采 {f.get('n', 0)} 店（新 {f.get('new', 0)} 页 "
diff --git a/fetcher/fetcher/sites/alibaba1688/contact.py b/fetcher/fetcher/sites/alibaba1688/contact.py
index 10555be..3dc6796 100644
--- a/fetcher/fetcher/sites/alibaba1688/contact.py
+++ b/fetcher/fetcher/sites/alibaba1688/contact.py
@@ -117,26 +117,26 @@ class ContactTask(Task):
             db.close()
             return False
         print(f"[1] 待抓取 {total_pending} 个，每个 worker 每批 "
               f"{config.batch_num} 个"
               f"（{'最多 ' + str(config.max_batches) + ' 批'
                  if config.max_batches else '不限批数，抓完 pending 为止'}），"
               f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
         db.close()
         return True
 
-    def summary(self, all_stats: dict) -> str:
+    def summary(self, all_stats: dict, db_path=None) -> str:
         from fetcher.db import ShopDB  # 延迟导入
         ok = sum(s.get("ok", 0) for s in all_stats.values())
         empty = sum(s.get("empty", 0) for s in all_stats.values())
         failed = sum(s.get("failed", 0) for s in all_stats.values())
-        db = ShopDB()
+        db = ShopDB(db_path)
         stats = db.stats()
         tmd = db.format_tmd_report()
         db.close()
         return (f"本次完成: 有联系方式 {ok}, 无联系方式 {empty}, "
                 f"失败 {failed}\n    数据库统计: {stats}\n{tmd}")
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
diff --git a/fetcher/fetcher/sites/alibaba1688/shop.py b/fetcher/fetcher/sites/alibaba1688/shop.py
index d93746f..54cf09a 100644
--- a/fetcher/fetcher/sites/alibaba1688/shop.py
+++ b/fetcher/fetcher/sites/alibaba1688/shop.py
@@ -202,26 +202,26 @@ class ShopTask(Task):
         print(f"[1] 数据库现有店铺 {st['shops']} 个（pending {st['pending']} / "
               f"done {st['done']} / no_contact {st['no_contact']} / "
               f"failed {st['failed']}），每个 worker 每批 "
               f"{config.batch_num} 个店铺"
               f"（{'最多 ' + str(config.max_batches) + ' 批'
                  if config.max_batches else '不限批数'}），"
               f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
         db.close()
         return True
 
-    def summary(self, all_stats: dict) -> str:
+    def summary(self, all_stats: dict, db_path=None) -> str:
         from fetcher.db import ShopDB  # 延迟导入
         shops = sum(s.get("shops", 0) for s in all_stats.values())
         new = sum(s.get("new", 0) for s in all_stats.values())
         pages = sum(s.get("pages", 0) for s in all_stats.values())
-        db = ShopDB()
+        db = ShopDB(db_path)
         stats = db.stats()
         db.close()
         return (f"本次采集: {pages} 页, 店铺 {shops} 个（新增 {new}）"
                 f"\n    数据库统计: {stats}")
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                 f"采 {f.get('n', 0)} 店（新 {f.get('new', 0)} 页 "
diff --git a/fetcher/fetcher/sites/madeinchina/contact.py b/fetcher/fetcher/sites/madeinchina/contact.py
index 7239afc..d880d03 100644
--- a/fetcher/fetcher/sites/madeinchina/contact.py
+++ b/fetcher/fetcher/sites/madeinchina/contact.py
@@ -191,26 +191,26 @@ class MadeInChinaContactTask(Task):
             db.close()
             return False
         print(f"[1] 待抓取 {total_pending} 个，每个 worker 每批 "
               f"{config.batch_num} 个"
               f"（{'最多 ' + str(config.max_batches) + ' 批'
                  if config.max_batches else '不限批数，抓完 pending 为止'}），"
               f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
         db.close()
         return True
 
-    def summary(self, all_stats: dict) -> str:
+    def summary(self, all_stats: dict, db_path=None) -> str:
         from fetcher.db import ShopDB  # 延迟导入
         ok = sum(s.get("ok", 0) for s in all_stats.values())
         empty = sum(s.get("empty", 0) for s in all_stats.values())
         failed = sum(s.get("failed", 0) for s in all_stats.values())
-        db = ShopDB()
+        db = ShopDB(db_path)
         stats = db.stats()
         db.close()
         return (f"本次完成: 有联系方式 {ok}, 无联系方式 {empty}, "
                 f"失败 {failed}\n    数据库统计: {stats}")
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                 f"采 {f.get('n', 0)}（✓{f.get('ok', 0)} ○{f.get('empty', 0)} "
diff --git a/fetcher/fetcher/sites/madeinchina/shop.py b/fetcher/fetcher/sites/madeinchina/shop.py
index 8b129a9..7924dc7 100644
--- a/fetcher/fetcher/sites/madeinchina/shop.py
+++ b/fetcher/fetcher/sites/madeinchina/shop.py
@@ -259,26 +259,26 @@ class MadeInChinaShopTask(Task):
         print(f"[1] 数据库现有店铺 {st['shops']} 个（pending {st['pending']} / "
               f"done {st['done']} / no_contact {st['no_contact']} / "
               f"failed {st['failed']}），每个 worker 每批 "
               f"{config.batch_num} 个店铺"
               f"（{'最多 ' + str(config.max_batches) + ' 批'
                  if config.max_batches else '不限批数'}），"
               f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
         db.close()
         return True
 
-    def summary(self, all_stats: dict) -> str:
+    def summary(self, all_stats: dict, db_path=None) -> str:
         from fetcher.db import ShopDB  # 延迟导入
         shops = sum(s.get("shops", 0) for s in all_stats.values())
         new = sum(s.get("new", 0) for s in all_stats.values())
         pages = sum(s.get("pages", 0) for s in all_stats.values())
-        db = ShopDB()
+        db = ShopDB(db_path)
         stats = db.stats()
         db.close()
         return (f"本次采集: {pages} 页, 店铺 {shops} 个（新增 {new}）"
                 f"\n    数据库统计: {stats}")
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                 f"采 {f.get('n', 0)} 店（新 {f.get('new', 0)} 页 "
diff --git a/fetcher/fetcher/sites/taobao/search.py b/fetcher/fetcher/sites/taobao/search.py
index 3beabb6..12f627f 100644
--- a/fetcher/fetcher/sites/taobao/search.py
+++ b/fetcher/fetcher/sites/taobao/search.py
@@ -153,21 +153,21 @@ class TaobaoSearchTask(Task):
 
     # ---- main 阶段 ----
 
     def prepare(self, config) -> bool:
         print(f"[1] 关键词队列 {self.queue.remaining()} 个任务项"
               f"（每关键词 {self.queue.pages_per_keyword} 页），"
               f"每 worker 每批 {config.batch_num} 页，"
               f"产出 → {self._out_path(config)}")
         return True
 
-    def summary(self, all_stats: dict) -> str:
+    def summary(self, all_stats: dict, db_path=None) -> str:
         items = sum(s.get("items", 0) for s in all_stats.values())
         pages = sum(s.get("pages", 0) for s in all_stats.values())
         return f"本次淘宝搜索采集: {pages} 页, 商品 {items} 个"
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                 f"采 {f.get('items', 0)} 品（页 {f.get('pages', 0)}）| "
                 f"{f.get('shop', '-')} | {f.get('state', '初始化')}")
diff --git a/fetcher/fetcher/sites/yiwugo/contact.py b/fetcher/fetcher/sites/yiwugo/contact.py
index f5e20ac..c326986 100644
--- a/fetcher/fetcher/sites/yiwugo/contact.py
+++ b/fetcher/fetcher/sites/yiwugo/contact.py
@@ -149,21 +149,21 @@ class YiwugoContactTask(Task):
         self.queue = ProductIdQueue(rows)
         if not self.queue.remaining():
             print(f"[X] 没有待采的商品 ID（输入 {self._in_path(config)} "
                   "不存在或为空；请先跑 yiwugo search）")
             return False
         print(f"[1] 商品 ID 队列 {self.queue.remaining()} 个，"
               f"每 worker 每批 {config.batch_num} 个，"
               f"产出 → {self._out_path(config)}")
         return True
 
-    def summary(self, all_stats: dict) -> str:
+    def summary(self, all_stats: dict, db_path=None) -> str:
         contacts = sum(s.get("contacts", 0) for s in all_stats.values())
         done = sum(s.get("done", 0) for s in all_stats.values())
         dead = sum(s.get("dead", 0) for s in all_stats.values())
         return (f"本次义乌购联系方式采集: 处理 {done} 个商品, "
                 f"有效联系方式 {contacts} 条, 失效商品 {dead} 个")
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
diff --git a/fetcher/fetcher/sites/yiwugo/search.py b/fetcher/fetcher/sites/yiwugo/search.py
index bdc43bc..362c3c9 100644
--- a/fetcher/fetcher/sites/yiwugo/search.py
+++ b/fetcher/fetcher/sites/yiwugo/search.py
@@ -124,21 +124,21 @@ class YiwugoSearchTask(Task):
 
     # ---- main 阶段 ----
 
     def prepare(self, config) -> bool:
         print(f"[1] 关键词队列 {self.queue.remaining()} 个任务项"
               f"（每关键词 {self.queue.pages_per_keyword} 页 × "
               f"{self.page_size} 条），每 worker 每批 {config.batch_num} 页，"
               f"产出 → {self._out_path(config)}")
         return True
 
-    def summary(self, all_stats: dict) -> str:
+    def summary(self, all_stats: dict, db_path=None) -> str:
         items = sum(s.get("items", 0) for s in all_stats.values())
         pages = sum(s.get("pages", 0) for s in all_stats.values())
         return f"本次义乌购搜索采集: {pages} 页, 商品 {items} 个"
 
     # ---- 状态板 ----
 
     def compose(self, wid: int, f: dict) -> str:
         return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                 f"采 {f.get('items', 0)} 品（页 {f.get('pages', 0)}）| "
                 f"{f.get('shop', '-')} | {f.get('state', '初始化')}")
diff --git a/fetcher/tests/test_engine.py b/fetcher/tests/test_engine.py
index e3017e2..fbc4bec 100644
--- a/fetcher/tests/test_engine.py
+++ b/fetcher/tests/test_engine.py
@@ -44,21 +44,22 @@ class FakeLoop:
         self.seed_kit = seed_kit
         FakeLoop.instances.append(self)
 
     def run(self):
         return {"done": 1, "wid": self.ctx.wid}
 
 
 class FakeTask(Task):
     name = "fake"
 
-    def summary(self, all_stats):
+    def summary(self, all_stats, db_path=None):
+        self._last_summary_db_path = db_path
         return f"汇总 {len(all_stats)} 个 worker"
 
 
 class EngineTest(unittest.TestCase):
     def setUp(self):
         FakeLoop.instances = []
         self._tmp = tempfile.TemporaryDirectory()
 
     def tearDown(self):
         self._tmp.cleanup()
@@ -117,26 +118,38 @@ class EngineTest(unittest.TestCase):
         cfg = self._config(workers=3, seeds_dir=str(seeds))
         engine = self._engine(cfg, FakeProvider(3))
         engine.run()
         kits = {loop.ctx.wid: loop.seed_kit for loop in FakeLoop.instances}
         self.assertEqual(kits[0]["name"], "kitA")
         self.assertEqual(kits[1]["name"], "kitB")
         self.assertIsNone(kits[2])
 
     def test_summary_aggregates_all_workers(self):
         provider = FakeProvider(2)
-        engine = self._engine(self._config(), provider)
+        cfg = self._config()
+        engine = self._engine(cfg, provider)
         engine.run()
         self.assertEqual(sorted(engine.state["stats"]), [0, 1])
-        self.assertEqual(engine.task.summary(engine.state["stats"]),
+        self.assertEqual(engine.task.summary(engine.state["stats"],
+                                              cfg.resolved_db_path()),
                          "汇总 2 个 worker")
 
+    def test_summary_receives_db_path_from_config(self):
+        """Engine 调用 summary 时传入 config.resolved_db_path()。"""
+        provider = FakeProvider(1)
+        cfg = self._config(db_path="/tmp/test_engine.db")
+        engine = self._engine(cfg, provider)
+        engine.run()
+        self.assertEqual(engine.task._last_summary_db_path,
+                         cfg.resolved_db_path(),
+                         "Engine 应将 resolved_db_path() 传给 summary")
+
     # ---- Step 1.3: site_name guard ----
 
     def test_site_without_site_name_raises_runtime_error(self):
         """site 非空而 site_name=None → RuntimeError。
 
         RED 预期（修正前）：没有 guard，site_name=None 静默通过，
         后续拼键出 'None:direct' 才暴露问题。
         """
         with self.assertRaises(RuntimeError) as ctx:
             Engine(self._config(), FakeTask(), site=MagicMock(),
diff --git a/fetcher/tests/test_summary_db_path.py b/fetcher/tests/test_summary_db_path.py
new file mode 100644
index 0000000..b899d78
--- /dev/null
+++ b/fetcher/tests/test_summary_db_path.py
@@ -0,0 +1,129 @@
+# -*- coding: utf-8 -*-
+"""测试 summary 透传 db_path（Step 3.1 修复验证）。
+证明 summary 不再默认开生产库，而是使用 Engine 传入的 db_path。
+"""
+
+from __future__ import annotations
+
+import unittest
+from unittest.mock import MagicMock, patch
+
+
+class SummaryDbPathTest(unittest.TestCase):
+    """验证各站点 summary 将 db_path 透传给 ShopDB。"""
+
+    # ---- 1688 contact（含 format_tmd_report 分支） ----
+
+    def test_1688_contact_summary_passes_db_path(self):
+        """1688 contact summary 将 db_path 传给 ShopDB 构造器。"""
+        recorded_path = []
+
+        def fake_shopdb(path=None):
+            recorded_path.append(path)
+            db = MagicMock()
+            db.stats.return_value = "stats"
+            db.format_tmd_report.return_value = "tmd"
+            return db
+
+        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
+            from fetcher.sites.alibaba1688.contact import ContactTask
+            task = ContactTask()
+            result = task.summary(
+                {0: {"ok": 1, "empty": 2, "failed": 0}},
+                "/tmp/target.db",
+            )
+        self.assertEqual(recorded_path, ["/tmp/target.db"],
+                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")
+        self.assertIn("有联系方式 1", result)
+
+    # ---- madeinchina contact ----
+
+    def test_madeinchina_contact_summary_passes_db_path(self):
+        """madeinchina contact summary 将 db_path 传给 ShopDB 构造器。"""
+        recorded_path = []
+
+        def fake_shopdb(path=None):
+            recorded_path.append(path)
+            db = MagicMock()
+            db.stats.return_value = "stats"
+            return db
+
+        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
+            from fetcher.sites.madeinchina.contact import MadeInChinaContactTask
+            task = MadeInChinaContactTask()
+            task.summary(
+                {0: {"ok": 0, "empty": 0, "failed": 1}},
+                "/tmp/mic.db",
+            )
+        self.assertEqual(recorded_path, ["/tmp/mic.db"],
+                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")
+
+    # ---- 1688 shop ----
+
+    def test_1688_shop_summary_passes_db_path(self):
+        """1688 shop summary 将 db_path 传给 ShopDB 构造器。"""
+        recorded_path = []
+
+        def fake_shopdb(path=None):
+            recorded_path.append(path)
+            db = MagicMock()
+            db.stats.return_value = "stats"
+            return db
+
+        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
+            from fetcher.sites.alibaba1688.shop import ShopTask
+            task = ShopTask()
+            task.summary(
+                {0: {"shops": 1, "new": 0, "pages": 2}},
+                "/tmp/shop.db",
+            )
+        self.assertEqual(recorded_path, ["/tmp/shop.db"],
+                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")
+
+    # ---- 1688 company ----
+
+    def test_1688_company_summary_passes_db_path(self):
+        """1688 company summary 将 db_path 传给 ShopDB 构造器。"""
+        recorded_path = []
+
+        def fake_shopdb(path=None):
+            recorded_path.append(path)
+            db = MagicMock()
+            db.stats.return_value = "stats"
+            return db
+
+        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
+            from fetcher.sites.alibaba1688.company import CompanyTask
+            task = CompanyTask()
+            task.summary(
+                {0: {"shops": 1, "new": 0, "pages": 1}},
+                "/tmp/company.db",
+            )
+        self.assertEqual(recorded_path, ["/tmp/company.db"],
+                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")
+
+    # ---- madeinchina shop ----
+
+    def test_madeinchina_shop_summary_passes_db_path(self):
+        """madeinchina shop summary 将 db_path 传给 ShopDB 构造器。"""
+        recorded_path = []
+
+        def fake_shopdb(path=None):
+            recorded_path.append(path)
+            db = MagicMock()
+            db.stats.return_value = "stats"
+            return db
+
+        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
+            from fetcher.sites.madeinchina.shop import MadeInChinaShopTask
+            task = MadeInChinaShopTask()
+            task.summary(
+                {0: {"shops": 0, "new": 0, "pages": 0}},
+                "/tmp/micshop.db",
+            )
+        self.assertEqual(recorded_path, ["/tmp/micshop.db"],
+                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")
+
+
+if __name__ == "__main__":
+    unittest.main()
