# Re-review Package — Step 4.1 fix round 1

## Commits
8daf5a1 fix(multiqueue-p3): C1 validate discover pass-through + I2/M3/M4/M5

## Stat
 .../task-4.1-report.md                             | 61 ++++++++++++++++++++++
 fetcher/fetcher/sites/madeinchina/shop.py          | 57 +++++++++++++-------
 fetcher/tests/test_mic_shop_feeder.py              | 33 ++++++++++++
 3 files changed, 132 insertions(+), 19 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md
index 157115a..e325649 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md
@@ -79,10 +79,71 @@
 | mic contact prepare 带域过滤 | ✅ `contact.py:178`：`db.reset_in_progress(SHOWROOM_DOMAIN_SUFFIX)` |
 
 ## 自查
 
 - ✅ brief 所有裁定均落实（payload 形态、page_no 运行时读、discover 走 on_success、streak 内存计数、refill_item 基类默认空、冷启动纯浏览）
 - ✅ 未碰 db.py、platform/、scraper/、util/、vendor/wa-check/
 - ✅ CLI 与 daemon 同一代码路径（acquire_item 用 claim_next_eligible）
 - ✅ ZERO_NEW_LIMIT=2 保持不变；SEED_CATEGORIES 保持不变；_JS_EXTRACT_SHOWROOMS 保持不变
 - ✅ `make_stats` 保持 `{"shops","new","pages"}` 三键
 - ⚠️ 工作区有他人未提交改动，已确认不碰（scoped add 严格按 brief 列出文件）
+
+---
+
+## Fix Round 1（task-4.1-fix1.md）
+
+> Commit: `(待提交)` | 修复条目: C1 / I2 / M3 / M4 / M5
+
+### C1（Critical）— validate 拒绝 discover，生产路径封死
+
+**问题**：`validate` 检查 `isinstance(result.data.get("shops"), list)`，
+discover item 的 fetch 返回 `{"discover": True}`（无 shops 键）→ validate
+返回 False → CrawlLoop 判 EMPTY → on_giveup → _finish("failed")。
+`on_success` 永不执行，类目发现封死。
+
+**修复**：`validate` 对 discover item 放行：
+```python
+def validate(self, ctx, item, result):
+    if item.get("kind") == "discover":
+        return isinstance((result.data or {}).get("discover"), bool)
+    return isinstance((result.data or {}).get("shops"), list)
+```
+
+### I2（Important）— discover 测试绕过 validate
+
+**问题**：DiscoverOutputTest 全部 4 个测试直接调 `on_success`，未走
+fetch→validate→on_success 三段式，导致 C1 漏检。
+
+**修复**：新增 `test_discover_full_pipeline_fetch_validate_on_success`：
+fetch → 断言 validate True → on_success → 断言 category item 被产出。
+
+### M3（Minor）— _seed_category_items fmt 硬编码 "x2"
+
+**问题**：`get_active_categories` 不含 fmt 字段，播种一律 "x2"；plain 体系
+类目（如 jgdbj）首次 fetch 会拼错 URL → 失败 → refill 继续错。
+
+**修复**：在 `_seed_category_items` 与 report 中记录已知局限注释；discover
+从页面提取时带正确 fmt 可覆盖纠正；refill 补插时若连续失败可考虑放弃（本次
+未加防护，等生产观察后另议）。
+
+### M4（Minor）— _seed_discover_item 内联 SQL 与 _count_pending_category 风格不一致
+
+**修复**：抽取 `_count_pending_by_kind(db, kind, keyword=None)` 统一方法，
+`_seed_discover_item` 与 `_count_pending_category` 均委托之。
+
+### M5（Minor）— _insert_work_item 导入私有符号 _now
+
+**修复**：改为 SQLite 内联 `datetime('now','localtime')`，移除 `from fetcher.db import _now`。
+
+### 测试
+
+- 聚焦：`tests/test_mic_shop_feeder.py tests/test_madeinchina.py` → **60 passed**
+- 全量：`cd fetcher && python -m pytest tests -q` → **463 passed, 2 subtests passed**
+- 新增 I2 回归测试：`test_discover_full_pipeline_fetch_validate_on_success`
+
+### 改动文件
+
+| 文件 | 改动 |
+|---|---|
+| `fetcher/fetcher/sites/madeinchina/shop.py` | C1: validate discover 放行; M3: fmt 局限注释; M4: 抽取 _count_pending_by_kind; M5: 移除 _now 导入 |
+| `fetcher/tests/test_mic_shop_feeder.py` | I2: 新增 discover 完整三段式测试 |
+| `docs/.../task-4.1-report.md` | 本修复记录追加 |
diff --git a/fetcher/fetcher/sites/madeinchina/shop.py b/fetcher/fetcher/sites/madeinchina/shop.py
index 02de25a..eb2750c 100644
--- a/fetcher/fetcher/sites/madeinchina/shop.py
+++ b/fetcher/fetcher/sites/madeinchina/shop.py
@@ -263,43 +263,45 @@ class MadeInChinaShopTask(Task):
               f"done {st['done']} / no_contact {st['no_contact']} / "
               f"failed {st['failed']}），每个 worker 每批 "
               f"{config.batch_num} 个店铺"
               f"（{'最多 ' + str(config.max_batches) + ' 批'
                  if config.max_batches else '不限批数'}），"
               f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
         db.close()
         return True
 
     def _seed_category_items(self, db) -> int:
-        """活跃拼音类目逐条插 category item（已有同 keyword pending 跳过）。"""
+        """活跃拼音类目逐条插 category item（已有同 keyword pending 跳过）。
+
+        ⚠️ 已知局限：get_active_categories 不含 fmt 字段，播种一律 "x2"；
+        plain 体系类目（如 jgdbj）首次 fetch 会拼错 URL 而失败；
+        discover 从页面提取时带正确 fmt 后纠正。Step 4.2 若 category_progress
+        加 fmt 列可根除。
+        """
         active = db.get_active_categories()
         n = 0
         for cat in active:
             slug = cat["slug"]
             name = cat.get("name", slug)
-            # 已有同 keyword pending category item 跳过
-            existing = self._count_pending_category(db, slug)
+            existing = self._count_pending_by_kind(db, "category", slug)
             if existing > 0:
                 continue
-            # fmt 从 category_progress 推断（默认 x2）
+            # fmt 默认 x2（局限见上），discover 提取时带正确 fmt 覆盖
             payload = {"kind": "category", "keyword": slug,
                        "name": name, "fmt": "x2"}
             self._insert_work_item(db, payload)
             n += 1
         return n
 
     def _seed_discover_item(self, db) -> int:
         """插一条 discover item（已有 pending discover 跳过）。"""
-        existing = db.conn.execute(
-            "SELECT COUNT(*) FROM work_items WHERE queue=? AND status='pending'"
-            " AND json_extract(payload_json, '$.kind')='discover'",
-            (self.QUEUE,)).fetchone()[0]
+        existing = self._count_pending_by_kind(db, "discover")
         if existing > 0:
             return 0
         self._insert_work_item(db, {"kind": "discover"})
         return 1
 
     def summary(self, all_stats: dict, db_path=None) -> str:
         from fetcher.db import ShopDB  # 延迟导入
         shops = sum(s.get("shops", 0) for s in all_stats.values())
         new = sum(s.get("new", 0) for s in all_stats.values())
         pages = sum(s.get("pages", 0) for s in all_stats.values())
@@ -414,21 +416,23 @@ class MadeInChinaShopTask(Task):
             kind = classify_error(e, page)
             reason = str(e).splitlines()[0][:200]
             if kind == "fatal":
                 return ActionResult.fatal(reason)
             if kind == "net_error":
                 return ActionResult.net_error(reason)
             return ActionResult.blocked(
                 f"页面加载失败（疑似风控拦截）: {reason}")
 
     def validate(self, ctx, item, result: ActionResult) -> bool:
-        """结构化校验：结果必须含 shops 列表（空列表 = 采到末页，合法）。"""
+        """结构化校验：discover → 检查 discover 标记；category → shops 列表。"""
+        if item.get("kind") == "discover":
+            return isinstance((result.data or {}).get("discover"), bool)
         return isinstance((result.data or {}).get("shops"), list)
 
     def on_success(self, ctx, item, result: ActionResult) -> int:
         """按 kind 分派入库与链式续喂。"""
         kind = item.get("kind", "")
         if kind == "discover":
             return self._on_discover_success(ctx, item, result)
         if kind == "category":
             return self._on_category_success(ctx, item, result)
         return 0
@@ -446,21 +450,21 @@ class MadeInChinaShopTask(Task):
             ctx.log(f"[!] 首页与市场导航页类目提取均失败，"
                     f"使用内置种子类目（{len(cats)} 个）")
         n = 0
         for c in cats:
             slug = c["slug"]
             # 跳过已 exhausted
             prog = db.get_category_progress(slug)
             if prog and prog.get("exhausted"):
                 continue
             # 跳过已有同 keyword pending category item
-            if self._count_pending_category(db, slug) > 0:
+            if self._count_pending_by_kind(db, "category", slug) > 0:
                 continue
             payload = {"kind": "category", "keyword": slug,
                        "name": c.get("name", slug),
                        "fmt": c.get("fmt", "x2")}
             self._insert_work_item(db, payload)
             n += 1
         if n:
             ctx.log(f"discover 产出 {n} 个新类目 category item")
         return 0  # discover 不计入页数
 
@@ -558,27 +562,42 @@ class MadeInChinaShopTask(Task):
 
     def empty_message(self) -> str:
         return "没有待认领的 work_item 了"
 
     # ---- work_items 辅助 ----
 
     @staticmethod
     def _insert_work_item(db, payload: dict) -> int:
         """向 work_items 插 pending 行，返回 id。"""
         import json as _json
-        from fetcher.db import _now
         cur = db.conn.execute(
             "INSERT INTO work_items (queue, site, payload_json, created_at)"
-            " VALUES (?, ?, ?, ?)",
+            " VALUES (?, ?, ?, datetime('now','localtime'))",
             (MadeInChinaShopTask.QUEUE, MadeInChinaShopTask.SITE,
-             _json.dumps(payload, ensure_ascii=False), _now()))
+             _json.dumps(payload, ensure_ascii=False)))
         db.conn.commit()
         return cur.lastrowid
 
     @staticmethod
-    def _count_pending_category(db, keyword: str) -> int:
-        """统计同 keyword 的 pending category item 数量。"""
+    def _count_pending_by_kind(db, kind: str, keyword: str = None) -> int:
+        """统计同 kind（+可选 keyword）的 pending item 数量。"""
+        if keyword is not None:
+            return db.conn.execute(
+                "SELECT COUNT(*) FROM work_items WHERE queue=?"
+                " AND status='pending'"
+                " AND json_extract(payload_json, '$.kind')=?"
+                " AND json_extract(payload_json, '$.keyword')=?",
+                (MadeInChinaShopTask.QUEUE, kind, keyword)).fetchone()[0]
         return db.conn.execute(
-            "SELECT COUNT(*) FROM work_items WHERE queue=? AND status='pending'"
-            " AND json_extract(payload_json, '$.kind')='category'"
-            " AND json_extract(payload_json, '$.keyword')=?",
-            (MadeInChinaShopTask.QUEUE, keyword)).fetchone()[0]
+            "SELECT COUNT(*) FROM work_items WHERE queue=?"
+            " AND status='pending'"
+            " AND json_extract(payload_json, '$.kind')=?",
+            (MadeInChinaShopTask.QUEUE, kind)).fetchone()[0]
+
+    @staticmethod
+    def _count_pending_category(db, keyword: str) -> int:
+        """统计同 keyword 的 pending category item 数量。
+
+        委托 _count_pending_by_kind（保留为向后兼容别名）。
+        """
+        return MadeInChinaShopTask._count_pending_by_kind(
+            db, "category", keyword)
diff --git a/fetcher/tests/test_mic_shop_feeder.py b/fetcher/tests/test_mic_shop_feeder.py
index 269a8f2..840659c 100644
--- a/fetcher/tests/test_mic_shop_feeder.py
+++ b/fetcher/tests/test_mic_shop_feeder.py
@@ -379,20 +379,53 @@ class DiscoverOutputTest(unittest.TestCase):
         ctx.state["task"]["stats"] = self.task.make_stats()
 
         self.task.on_success(ctx, _discover_payload(), ok_result({"discover": True}))
 
         items = _pending_items(self.db)
         self.assertGreater(len(items), 0)
         # 至少包含种子类目
         keywords = {p["keyword"] for _, p in items if p.get("keyword")}
         self.assertIn("wujingj", keywords)
 
+    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
+    def test_discover_full_pipeline_fetch_validate_on_success(self, mock_fetch):
+        """discover 走完整三段式 fetch→validate→on_success，产出类目 item。
+
+        这是 C1 的回归测试：修复前 validate 拒绝 discover（检查 shops 键），
+        on_success 永远不会被调用，类目发现封死。
+        """
+        mock_fetch.side_effect = lambda page, url: {
+            HOMEPAGE: [{"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"}],
+        }.get(url, [])
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        item = _discover_payload()
+        # 1. fetch → discover 标记
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+        self.assertTrue(result.data.get("discover"))
+
+        # 2. validate → 放行（C1 修复：不再拒绝 discover）
+        self.assertTrue(self.task.validate(ctx, item, result))
+
+        # 3. on_success → 提取类目 → INSERT category item
+        count = self.task.on_success(ctx, item, result)
+        self.assertEqual(count, 0)  # discover 不计入页数
+
+        items = _pending_items(self.db)
+        self.assertGreaterEqual(len(items), 1)
+        self.assertTrue(any(
+            p.get("kind") == "category" and p.get("keyword") == "bxgyxg"
+            for _, p in items))
+
 
 # ---- 5. 幂等播种 ----
 
 class IdempotentSeedTest(unittest.TestCase):
     """重复 prepare/播种 → 不产生重复 pending item。"""
 
     def setUp(self):
         self._tmp = tempfile.TemporaryDirectory()
         self.db_path = str(Path(self._tmp.name) / "s.db")
         self.db = ShopDB(self.db_path)
