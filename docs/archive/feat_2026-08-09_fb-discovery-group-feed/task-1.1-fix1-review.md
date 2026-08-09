# Step 1.1 fix round 1 review
96129f8 fix(fb): Step 1.1 review——upsert_fb_groups source 缺省语义收窄 + schema 契约固化测试
 .../task-1.1-report.md                             | 48 ++++++++++++++++++++++
 fetcher/fetcher/db.py                              | 10 ++---
 fetcher/tests/test_db_fb_groups.py                 | 17 ++++++++
 3 files changed, 70 insertions(+), 5 deletions(-)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md
index 50297b2..cbec314 100644
--- a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md
@@ -64,10 +64,58 @@ DDG 分页行「依据」列追加：
 - **纪律**：未做 brief 之外的事（mark_fb_group_done/failed/reset 属 Step 2.1，未动）；
   未改 db.py 其他区域；未动 PLAN.md checkbox（commit 约束文件清单未含 PLAN.md，勾选留给协调者/后续 Step）。
 - **测试**：真实 SQLite 文件 + 真实 INSERT，无 mock；每个测试都先看过 RED。
 
 ## 问题或疑虑（concern）
 
 1. db.py 是既有大文件（>1100 行），本次只在指定两处做增量，未重构任务范围外内容——
    后续 Step 若继续在其上加代码，建议考虑按域拆分模块，但非本 Step 职责。
 2. `upsert_fb_groups` 的 source 缺省用了 `g.get("source") or "ddg"`（空串也归 ddg），
    与协调者裁定「缺省 'ddg'」一致；若未来需要区分「显式空串」语义需另行约定，目前无此需求（YAGNI 不处理）。
+
+---
+
+## 修复报告（第 1 轮 review 发现，Fix 1）
+
+> 状态：DONE。依据 task-1.1-review.md 三条发现逐条修复，TDD 流程（先 RED 后 GREEN）。
+
+### 修复内容
+
+1. **`fetcher/fetcher/db.py` upsert_fb_groups source 缺省语义收窄**（review 发现 1）：
+   `g.get("source") or "ddg"` → `g.get("source") if g.get("source") is not None else "ddg"`。
+   现在仅 key 不存在或值为 None 时缺省 'ddg'；显式空字符串 `""` 是合法显式值，原样落库
+   （与协调者裁定「缺省」= key 不存在时默认一致）。
+2. **`fetcher/tests/test_db_fb_groups.py` 新增 schema 契约固化断言**（review 发现 2）：
+   `test_tables_created_and_idempotent` 内补 `PRAGMA table_info('fb_posts')` 断言
+   `status` 列 `dflt_value == "'pending'"`——固化 save_fb_posts 依赖的 schema 契约，
+   防未来改 DEFAULT 静默破坏。
+3. **`fetcher/tests/test_db_fb_groups.py` 补 source 不覆盖断言**（review 发现 3）：
+   `test_upsert_groups_dedup_keeps_status_and_name` 补一行
+   `assertEqual(rows[0]["source"], "ddg")`——二次 upsert（带 source='fb_post'）后
+   该行 source 仍保持首次 'ddg'（INSERT OR IGNORE：已存在行全字段不动）。
+4. **新增测试**：`test_upsert_groups_explicit_empty_source_kept`——显式传 `{"source": ""}`
+   期望原样落库为 `""`（review 发现 1 的失败测试）。
+
+### TDD 证据
+
+- **RED**（仅改测试后、改代码前）：`cd fetcher && ../platform/server/.venv/bin/python
+  -m unittest discover -s tests -p "test_db_fb_groups.py"` → `Ran 8 tests ... FAILED (failures=1)`：
+  ```
+  FAIL: test_upsert_groups_explicit_empty_source_kept
+  AssertionError: 'ddg' != ''
+  ```
+  正是 review 发现 1 的 bug（空串被吞成 ddg）。发现 2/3 为 schema 契约固化断言，
+  首次运行即绿（schema 本已正确），属守护而非修复。
+- **GREEN**（改代码后）：同一命令 → `Ran 8 tests in 0.037s OK`。
+- **回归**：`-p "test_db_fb*.py"`（test_db_fb.py 10 例 + test_db_fb_groups.py 8 例）
+  → `Ran 18 tests in 0.106s OK`，输出干净。
+
+### 改动的文件
+
+- `fetcher/fetcher/db.py`（upsert_fb_groups 内 1 行语义修正 + docstring 措辞对齐，仅增量）
+- `fetcher/tests/test_db_fb_groups.py`（+3 断言、+1 新测试用例，共 8 用例）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md`（本报告）
+
+### 遗留疑虑
+
+- 显式空串 `source=""` 现在落库为空串；若未来数据面要求空串也归一 'ddg'，需在调用方
+  （FbDiscoverTask/FbPostTask）显式不传 key 或传 None，db 层语义已按裁定收窄，不再吞空串。
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 9d6ba67..7dd0842 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -877,35 +877,35 @@ class ShopDB:
                 (url, p.get("group_id"), p.get("group_name"),
                  keyword, source, now))
             inserted += cur.rowcount
         self.conn.commit()
         return inserted
 
     def upsert_fb_groups(self, groups: list[dict]) -> int:
         """发现/帖派生的群条目落 fb_groups（INSERT OR IGNORE，url UNIQUE
         去重；已存在行不动 status/name，保持采集进度）。
 
-        groups: [{"url", "group_id", "name", "source"?}, ...]，source 缺省
-        'ddg'（FbDiscoverTask 不带 source 键；FbPostTask 传 'fb_post'）。
-        返回本次实际新增行数。
+        groups: [{"url", "group_id", "name", "source"?}, ...]，source 仅在
+        key 不存在或 None 时缺省 'ddg'（FbDiscoverTask 不带 source 键；
+        FbPostTask 传 'fb_post'）。返回本次实际新增行数。
         """
         now = _now()
         inserted = 0
         for g in groups:
             url = (g.get("url") or "").strip()
             if not url:
                 continue
+            source = g.get("source") if g.get("source") is not None else "ddg"
             cur = self.conn.execute(
                 "INSERT OR IGNORE INTO fb_groups (url, group_id, name,"
                 " source, first_seen_at) VALUES (?, ?, ?, ?, ?)",
-                (url, g.get("group_id"), g.get("name"),
-                 g.get("source") or "ddg", now))
+                (url, g.get("group_id"), g.get("name"), source, now))
             inserted += cur.rowcount
         self.conn.commit()
         return inserted
 
     # ---------- category_progress ----------
     def get_category_progress(self, keyword: str) -> dict | None:
         """取类目分页进度（无记录返回 None）。"""
         row = self.conn.execute(
             "SELECT * FROM category_progress WHERE keyword=?",
             (keyword,)).fetchone()
diff --git a/fetcher/tests/test_db_fb_groups.py b/fetcher/tests/test_db_fb_groups.py
index 7f0e594..cf11dbe 100644
--- a/fetcher/tests/test_db_fb_groups.py
+++ b/fetcher/tests/test_db_fb_groups.py
@@ -31,20 +31,25 @@ class FbGroupsDataTest(unittest.TestCase):
 
     def test_tables_created_and_idempotent(self):
         """重复初始化不报错，fb_groups 表与 (status, id) 索引存在。"""
         ShopDB(Path(self._tmp.name) / "t.db")  # 二次初始化
         tables = {r[0] for r in self.db.conn.execute(
             "SELECT name FROM sqlite_master WHERE type='table'")}
         self.assertIn("fb_groups", tables)
         idx = {r[0] for r in self.db.conn.execute(
             "SELECT name FROM sqlite_master WHERE type='index'")}
         self.assertIn("idx_fb_groups_status", idx)
+        # schema 契约固化：save_fb_posts 依赖 fb_posts.status 默认 pending，
+        # 防未来改 DEFAULT 静默破坏（status 列 dflt_value 须为 'pending'）。
+        cols = {r["name"]: r for r in self.db.conn.execute(
+            "PRAGMA table_info('fb_posts')").fetchall()}
+        self.assertEqual(cols["status"]["dflt_value"], "'pending'")
 
     # ---- save_fb_posts ----
 
     def test_save_posts_traceability_and_count(self):
         posts = [
             {"url": POST_URL_1, "group_id": "185879310028412",
              "group_name": "Shenzhen Expats 2026"},
             {"url": POST_URL_2, "group_id": "1305282597018167",
              "group_name": "Group B"},
         ]
@@ -99,32 +104,44 @@ class FbGroupsDataTest(unittest.TestCase):
 
     def test_upsert_groups_explicit_source(self):
         groups = [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1",
                    "source": "fb_post"}]
         n = self.db.upsert_fb_groups(groups)
         self.assertEqual(n, 1)
         row = self.db.conn.execute(
             "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchone()
         self.assertEqual(row["source"], "fb_post")
 
+    def test_upsert_groups_explicit_empty_source_kept(self):
+        """协调者裁定：source 仅在 key 不存在或 None 时缺省 'ddg'；
+        显式传空字符串 '' 是合法显式值，必须原样落库不被吞成 'ddg'。"""
+        groups = [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1",
+                   "source": ""}]
+        n = self.db.upsert_fb_groups(groups)
+        self.assertEqual(n, 1)
+        row = self.db.conn.execute(
+            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchone()
+        self.assertEqual(row["source"], "")
+
     def test_upsert_groups_dedup_keeps_status_and_name(self):
         """先落 pending 行并置 in_progress（模拟采集进行中），再同 url
         不同 name/source 的 upsert → 0 行且 status/name 保持原值。"""
         self.db.upsert_fb_groups(
             [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1"}])
         self.db.conn.execute(
             "UPDATE fb_groups SET status='in_progress' WHERE url=?",
             (GROUP_URL_1,))
         self.db.conn.commit()
         n = self.db.upsert_fb_groups(
             [{"url": GROUP_URL_1, "group_id": "g1",
               "name": "改名后的群", "source": "fb_post"}])
         self.assertEqual(n, 0)  # 同 url IGNORE
         rows = self.db.conn.execute(
             "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchall()
         self.assertEqual(len(rows), 1)
         self.assertEqual(rows[0]["status"], "in_progress")  # 不动 status
         self.assertEqual(rows[0]["name"], "G1")  # 不覆盖 name
+        self.assertEqual(rows[0]["source"], "ddg")  # 二次 upsert 带 fb_post 也不覆盖 source
 
 
 if __name__ == "__main__":
     unittest.main()
