# Review Package — Step 1.1 (work_items 扩展)

## Commits
c87c616 feat(multiqueue-p3): work_items 扩展——attempts 幂等迁移 + release_work_item + claim_next_eligible（TDD 全绿 318 passed）

## Stat
 fetcher/fetcher/db.py            |  78 +++++++++++++++
 fetcher/tests/test_work_items.py | 211 ++++++++++++++++++++++++++++++++++++++-
 2 files changed, 284 insertions(+), 5 deletions(-)

## Diff
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 7af8033..351a570 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -241,20 +241,26 @@ class ShopDB:
                WHERE status='done' AND id IN (
                    SELECT shop_id FROM contacts
                    WHERE contact_person IS NULL AND phone IS NULL
                      AND mobile IS NULL AND fax IS NULL AND address IS NULL)""")
         # ip_events 补 req_since_block 列（tmd 触发阈值样本：
         # 本次触发时距该 IP 上次触发已爬多少个页面请求）
         evt_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(ip_events)")}
         if "req_since_block" not in evt_cols:
             self.conn.execute(
                 "ALTER TABLE ip_events ADD COLUMN req_since_block INTEGER")
+        # work_items 补 attempts 列（P3 多队列：release 重试计数，达上限熔断置 failed）
+        wi_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(work_items)")}
+        if "attempts" not in wi_cols:
+            self.conn.execute(
+                "ALTER TABLE work_items ADD COLUMN attempts"
+                " INTEGER NOT NULL DEFAULT 0")
         # cookies 表裸键按 domain→site 映射加前缀（P2 identity 升级：
         # identity 键从裸 IP 升级为 site:ip）。部署窗口：旧进程裸键读不到
         # 新前缀 Cookie → 白板重启一次（SPEC §3.4 运维注意）。
         # 映射清单（先长后短，SPEC §3.4 回填）：
         self.conn.execute(
             "UPDATE cookies SET identity = 'madeinchina:' || identity"
             " WHERE identity NOT LIKE '%:%'"
             " AND domain LIKE '%made-in-china.com%'")
         self.conn.execute(
             "UPDATE cookies SET identity = '1688:' || identity"
@@ -506,20 +512,92 @@ class ShopDB:
 
     def reset_claimed_work_items(self) -> int:
         """全部 claimed 工作项重置回 pending（进程中断残留的认领，
         daemon 启动时调用），清空 claimed_by/claimed_at，返回重置行数。"""
         cur = self.conn.execute(
             "UPDATE work_items SET status='pending', claimed_by=NULL,"
             " claimed_at=NULL WHERE status='claimed'")
         self.conn.commit()
         return cur.rowcount
 
+    def release_work_item(self, item_id: int, max_attempts: int = 3) -> str:
+        """工作项释放回 pending（attempts+1）；attempts 达上限置 failed。
+
+        单事务（BEGIN IMMEDIATE）：attempts = attempts + 1，清空
+        claimed_by/claimed_at；attempts >= max_attempts 时置 failed
+        （写 finished_at、result_json="attempts exhausted"），否则置
+        pending。返回终态字符串："pending" / "failed"。
+
+        只对 claimed 状态的行生效；rowcount=0（非 claimed/不存在）时
+        返回 "failed"（调用方视为不可恢复，防御性兜底）。
+        """
+        try:
+            self.conn.execute("BEGIN IMMEDIATE")
+            cur = self.conn.execute(
+                "UPDATE work_items SET attempts = attempts + 1,"
+                " claimed_by = NULL, claimed_at = NULL"
+                " WHERE id=? AND status='claimed'", (item_id,))
+            if cur.rowcount == 0:
+                self.conn.commit()
+                return "failed"
+            attempts = self.conn.execute(
+                "SELECT attempts FROM work_items WHERE id=?",
+                (item_id,)).fetchone()[0]
+            if attempts >= max_attempts:
+                self.conn.execute(
+                    "UPDATE work_items SET status='failed', finished_at=?,"
+                    " result_json=? WHERE id=?",
+                    (_now(), json.dumps("attempts exhausted"), item_id))
+                self.conn.commit()
+                return "failed"
+            self.conn.execute(
+                "UPDATE work_items SET status='pending' WHERE id=?",
+                (item_id,))
+            self.conn.commit()
+            return "pending"
+        except Exception:
+            self.conn.rollback()
+            raise
+
+    def claim_next_eligible(self, queues: list[str],
+                            consumer_id: str) -> dict | None:
+        """跨队列原子认领最老 pending 工作项（FIFO 按 id，无优先级）。
+
+        单事务（BEGIN IMMEDIATE）：WHERE status='pending' AND queue IN (...)
+        ORDER BY id LIMIT 1 → 置 claimed（claimed_by/claimed_at）。返回
+        {"id", "queue", "site", "payload"}（payload 为 json.loads 解码后
+        的字典）；无货（含空 queues）返回 None。
+        """
+        if not queues:
+            return None
+        placeholders = ",".join("?" * len(queues))
+        try:
+            self.conn.execute("BEGIN IMMEDIATE")
+            row = self.conn.execute(
+                f"SELECT * FROM work_items WHERE status='pending'"
+                f" AND queue IN ({placeholders})"
+                " ORDER BY id LIMIT 1", queues).fetchone()
+            if not row:
+                self.conn.commit()
+                return None
+            self.conn.execute(
+                "UPDATE work_items SET status='claimed', claimed_by=?,"
+                " claimed_at=? WHERE id=?",
+                (consumer_id, _now(), row["id"]))
+            self.conn.commit()
+        except Exception:
+            self.conn.rollback()
+            raise
+        return {"id": row["id"], "queue": row["queue"],
+                "site": row["site"],
+                "payload": json.loads(row["payload_json"])}
+
     # ---------- category_progress ----------
     def get_category_progress(self, keyword: str) -> dict | None:
         """取类目分页进度（无记录返回 None）。"""
         row = self.conn.execute(
             "SELECT * FROM category_progress WHERE keyword=?",
             (keyword,)).fetchone()
         return dict(row) if row else None
 
     def advance_category_page(self, keyword: str, name: str = None,
                               shops_found: int = 0) -> int:
diff --git a/fetcher/tests/test_work_items.py b/fetcher/tests/test_work_items.py
index cce84b9..f329c62 100644
--- a/fetcher/tests/test_work_items.py
+++ b/fetcher/tests/test_work_items.py
@@ -1,20 +1,21 @@
 # -*- coding: utf-8 -*-
-"""work_items 存储层测试：topup / claim / finish / reset 四方法（临时 sqlite）。
-仿 test_contact_task.py 基建，不起浏览器/网络。"""
+"""work_items 存储层测试：topup / claim / finish / reset / release / claim_next_eligible
+（临时 sqlite）。仿 test_contact_task.py 基建，不起浏览器/网络。"""
 
 import json
+import sqlite3
 import tempfile
 import unittest
 from pathlib import Path
 
-from fetcher.db import ShopDB
+from fetcher.db import SCHEMA, ShopDB
 
 QUEUE = "crawl_1688_contact"
 
 
 def _shop(i, suffix=".1688.com"):
     return {"domain": f"shop{i}{suffix}", "name": f"店铺{i}",
             "url": f"https://shop{i}{suffix}"}
 
 
 class WorkItemsTest(unittest.TestCase):
@@ -36,22 +37,23 @@ class WorkItemsTest(unittest.TestCase):
             (domain,)).fetchone()[0]
 
     # 用例 1：top-up 生成 work_items 且 shops 标 in_progress；
     # 重复 top-up 只补剩余 pending，不产生重复行
     def test_topup_marks_shops_and_no_duplicates(self):
         # DDL 前置断言：表与索引存在、列齐全
         cols = {r[1] for r in self.db.conn.execute(
             "PRAGMA table_info(work_items)")}
         self.assertEqual(
             cols, {"id", "queue", "site", "batch_id", "payload_json",
-                   "requires", "status", "claimed_by", "claimed_at",
-                   "finished_at", "result_json", "created_at"})
+                   "requires", "status", "attempts", "claimed_by",
+                   "claimed_at", "finished_at", "result_json",
+                   "created_at"})
         idx = {r[1] for r in self.db.conn.execute(
             "PRAGMA index_list(work_items)")}
         self.assertIn("idx_work_items_claim", idx)
 
         # 3 家 1688 店铺 + 1 家 madeinchina（suffix 不匹配，不应入队）
         self.db.upsert_shops([_shop(1), _shop(2), _shop(3),
                               _shop(9, ".cn.made-in-china.com")])
         n = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
         self.assertEqual(n, 2)
 
@@ -155,12 +157,211 @@ class WorkItemsTest(unittest.TestCase):
             self.assertIsNone(rows[item_id]["claimed_by"])
             self.assertIsNone(rows[item_id]["claimed_at"])
         others = [r for r in self._items()
                   if r["id"] not in (a["id"], b["id"])]
         self.assertEqual(len(others), 1)
         self.assertEqual(others[0]["status"], "pending")
         # 无 claimed 行时返回 0
         self.assertEqual(self.db.reset_claimed_work_items(), 0)
 
 
+    # ---------- P3 Step 1.1: attempts / release_work_item / claim_next_eligible ----------
+    def _insert_item(self, queue, payload, site="1688"):
+        """直接向 work_items 插 pending 行（绕过 topup，便于多队列交叉构造）。"""
+        cur = self.db.conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, created_at)"
+            " VALUES (?, ?, ?, ?)",
+            (queue, site, json.dumps(payload, ensure_ascii=False),
+             "2025-08-08 00:00:00"))
+        self.db.conn.commit()
+        return cur.lastrowid
+
+    # 用例 1：release 回 pending，可重领且 attempts 保留
+    def test_release_returns_to_pending(self):
+        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
+        got = self.db.claim_next_eligible(["q1"], "w0")
+        self.assertEqual(got["id"], iid)
+
+        ret = self.db.release_work_item(iid)
+        self.assertEqual(ret, "pending")
+        row = self.db.conn.execute(
+            "SELECT * FROM work_items WHERE id=?", (iid,)).fetchone()
+        self.assertEqual(row["status"], "pending")
+        self.assertEqual(row["attempts"], 1)
+        self.assertIsNone(row["claimed_by"])
+        self.assertIsNone(row["claimed_at"])
+        self.assertIsNone(row["finished_at"])
+
+        # 重领：attempts 保留（claim 不重置 attempts）
+        got2 = self.db.claim_next_eligible(["q1"], "w1")
+        self.assertEqual(got2["id"], iid)
+        row = self.db.conn.execute(
+            "SELECT status, attempts FROM work_items WHERE id=?",
+            (iid,)).fetchone()
+        self.assertEqual(row["status"], "claimed")
+        self.assertEqual(row["attempts"], 1)
+
+    # 用例 2：attempts 耗尽置 failed
+    def test_release_exhausts_attempts_to_failed(self):
+        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
+        results = []
+        for _ in range(3):
+            self.db.claim_next_eligible(["q1"], "w0")
+            results.append(self.db.release_work_item(iid))
+        self.assertEqual(results, ["pending", "pending", "failed"])
+        row = self.db.conn.execute(
+            "SELECT * FROM work_items WHERE id=?", (iid,)).fetchone()
+        self.assertEqual(row["status"], "failed")
+        self.assertEqual(row["attempts"], 3)
+        self.assertEqual(json.loads(row["result_json"]), "attempts exhausted")
+        self.assertIsNotNone(row["finished_at"])
+
+    # 用例 3：release 终态返回值（不足上限 pending，达上限 failed）
+    def test_release_terminal_return_with_custom_max_attempts(self):
+        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
+        self.db.claim_next_eligible(["q1"], "w0")
+        self.assertEqual(self.db.release_work_item(iid, max_attempts=2),
+                         "pending")
+        self.db.claim_next_eligible(["q1"], "w0")
+        self.assertEqual(self.db.release_work_item(iid, max_attempts=2),
+                         "failed")
+        row = self.db.conn.execute(
+            "SELECT status, attempts FROM work_items WHERE id=?",
+            (iid,)).fetchone()
+        self.assertEqual(row["status"], "failed")
+        self.assertEqual(row["attempts"], 2)
+
+    # 用例 4：release 非 claimed 防御（返回 failed 且行内容不变）
+    def test_release_on_non_claimed_is_defensive_failed(self):
+        # pending 行
+        pid = self._insert_item("q1", {"domain": "shop1.1688.com"})
+        self.assertEqual(self.db.release_work_item(pid), "failed")
+        row = self.db.conn.execute(
+            "SELECT * FROM work_items WHERE id=?", (pid,)).fetchone()
+        self.assertEqual(row["status"], "pending")
+        self.assertEqual(row["attempts"], 0)
+        self.assertIsNone(row["claimed_by"])
+        self.assertIsNone(row["finished_at"])
+        self.assertIsNone(row["result_json"])
+
+        # done 行
+        did = self._insert_item("q1", {"domain": "shop2.1688.com"})
+        self.db.claim_next_eligible(["q1"], "w0")
+        self.db.finish_work_item(did, "done", {"ok": True})
+        self.assertEqual(self.db.release_work_item(did), "failed")
+        row = self.db.conn.execute(
+            "SELECT * FROM work_items WHERE id=?", (did,)).fetchone()
+        self.assertEqual(row["status"], "done")
+        self.assertEqual(row["attempts"], 0)
+        self.assertEqual(json.loads(row["result_json"]), {"ok": True})
+
+        # 不存在的 id
+        self.assertEqual(self.db.release_work_item(99999), "failed")
+
+    # 用例 5：claim_next_eligible 队列集合过滤
+    def test_claim_next_eligible_filters_queues(self):
+        a = self._insert_item("queue_a", {"domain": "a1.1688.com"})
+        b = self._insert_item("queue_b", {"domain": "b1.1688.com"})
+        c = self._insert_item("queue_c", {"domain": "c1.1688.com"})
+
+        got = self.db.claim_next_eligible(["queue_a"], "w0")
+        self.assertEqual(got["id"], a)
+        self.assertEqual(got["queue"], "queue_a")
+        self.assertEqual(got["site"], "1688")
+        self.assertEqual(got["payload"], {"domain": "a1.1688.com"})
+        for iid in (b, c):
+            row = self.db.conn.execute(
+                "SELECT status FROM work_items WHERE id=?",
+                (iid,)).fetchone()
+            self.assertEqual(row["status"], "pending")
+
+        got2 = self.db.claim_next_eligible(["queue_a", "queue_b"], "w1")
+        self.assertEqual(got2["id"], b)
+        row_c = self.db.conn.execute(
+            "SELECT status FROM work_items WHERE id=?", (c,)).fetchone()
+        self.assertEqual(row_c["status"], "pending")
+
+    # 用例 6：FIFO（多队混排按 id 最老先领，无优先级）
+    def test_claim_next_eligible_fifo_by_id_across_queues(self):
+        ids = [self._insert_item(q, {"domain": f"{q}-{i}.1688.com"})
+               for i, q in enumerate(["A", "B", "A", "B"])]
+        claimed = []
+        for _ in range(4):
+            got = self.db.claim_next_eligible(["A", "B"], "w0")
+            self.assertIsNotNone(got)
+            claimed.append(got["id"])
+        self.assertEqual(claimed, ids)  # 严格按 id 升序
+        self.assertIsNone(self.db.claim_next_eligible(["A", "B"], "w0"))
+
+    # 用例 7：并发不重复认领（顺序模拟两个消费者）
+    def test_claim_next_eligible_no_double_claim(self):
+        i1 = self._insert_item("q1", {"domain": "shop1.1688.com"})
+        i2 = self._insert_item("q1", {"domain": "shop2.1688.com"})
+        a = self.db.claim_next_eligible(["q1"], "w0")
+        b = self.db.claim_next_eligible(["q1"], "w1")
+        self.assertIsNotNone(a)
+        self.assertIsNotNone(b)
+        self.assertNotEqual(a["id"], b["id"])
+        self.assertEqual(sorted([a["id"], b["id"]]), [i1, i2])
+        rows = {r["id"]: r for r in self._items()}
+        self.assertEqual(rows[a["id"]]["claimed_by"], "w0")
+        self.assertEqual(rows[b["id"]]["claimed_by"], "w1")
+        self.assertIsNone(self.db.claim_next_eligible(["q1"], "w2"))
+
+    # 用例 8：attempts 列存在性 + 旧库迁移（存量行默认 0）
+    def test_attempts_column_present_and_legacy_migration(self):
+        cols = {r[1] for r in self.db.conn.execute(
+            "PRAGMA table_info(work_items)")}
+        self.assertIn("attempts", cols)
+
+        # 手工构造无 attempts 列的旧库（模拟 P3 前 schema）
+        legacy_path = str(Path(self._tmp.name) / "legacy.db")
+        conn = sqlite3.connect(legacy_path)
+        conn.execute("PRAGMA journal_mode=WAL")
+        conn.executescript(SCHEMA)
+        conn.execute("DROP TABLE work_items")
+        conn.execute(
+            """CREATE TABLE work_items (
+                id          INTEGER PRIMARY KEY AUTOINCREMENT,
+                queue       TEXT NOT NULL,
+                site        TEXT,
+                batch_id    INTEGER,
+                payload_json TEXT NOT NULL,
+                requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
+                status      TEXT NOT NULL DEFAULT 'pending',
+                claimed_by  TEXT,
+                claimed_at  TEXT,
+                finished_at TEXT,
+                result_json TEXT,
+                created_at  TEXT NOT NULL)""")
+        conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, created_at)"
+            " VALUES ('q1', 's1', '{}', '2025-08-08 00:00:00')")
+        conn.commit()
+        conn.close()
+
+        db2 = ShopDB(legacy_path)
+        cols2 = {r[1] for r in db2.conn.execute(
+            "PRAGMA table_info(work_items)")}
+        self.assertIn("attempts", cols2)
+        row = db2.conn.execute(
+            "SELECT attempts FROM work_items WHERE queue='q1'").fetchone()
+        self.assertEqual(row["attempts"], 0)
+        # 幂等：重开再迁移不报错、列仍存在
+        db2.close()
+        db3 = ShopDB(legacy_path)
+        cols3 = {r[1] for r in db3.conn.execute(
+            "PRAGMA table_info(work_items)")}
+        self.assertIn("attempts", cols3)
+        db3.close()
+
+    # 用例 9：空队列返回 None
+    def test_claim_next_eligible_empty_queues_returns_none(self):
+        self._insert_item("q1", {"domain": "shop1.1688.com"})
+        self.assertIsNone(self.db.claim_next_eligible([], "w0"))
+        row = self.db.conn.execute(
+            "SELECT status FROM work_items").fetchone()
+        self.assertEqual(row["status"], "pending")  # 不碰任何行
+
+
 if __name__ == "__main__":
     unittest.main()
