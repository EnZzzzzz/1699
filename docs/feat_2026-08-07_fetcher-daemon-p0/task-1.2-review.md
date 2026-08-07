=== git log ===
8fcfe91 feat(fetcher): work_items 存储层（daemon 工作队列 DDL + topup/claim/finish/reset 四方法）

=== diff --stat ===
 fetcher/fetcher/db.py            | 107 +++++++++++++++++++++++++
 fetcher/tests/test_work_items.py | 166 +++++++++++++++++++++++++++++++++++++++
 2 files changed, 273 insertions(+)

=== diff -U10 ===
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 61b8bb8..43e98d8 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -47,20 +47,21 @@
     db.finish_run(run_id, shops_found=35)
 
     # Cookie（按出口 IP 隔离）
     db.save_cookies(identity, playwright_cookies)
     cookies = db.load_cookies(identity)   # 自动剔除已过期的
     db.close()
 """
 
 from __future__ import annotations  # 兼容 Python < 3.10 的 X | None 注解
 
+import json
 import os
 import re
 import sqlite3
 import time
 from pathlib import Path
 
 # 拼音类目 slug（madeinchina market 页）：纯 ASCII 字母数字下划线。
 # 中文关键词 / company: 前缀行属 1688 等其他任务，不当作 market slug。
 _IS_PINYIN_RE = re.compile(r"^[a-zA-Z0-9_]+$")
 
@@ -161,20 +162,38 @@ CREATE TABLE IF NOT EXISTS ip_stats (
 CREATE TABLE IF NOT EXISTS category_progress (
     id              INTEGER PRIMARY KEY AUTOINCREMENT,
     keyword         TEXT NOT NULL UNIQUE,           -- 类目关键词
     name            TEXT,                           -- 类目显示名
     next_page       INTEGER NOT NULL DEFAULT 1,     -- 下次应采集的页码（1 起）
     pages_crawled   INTEGER NOT NULL DEFAULT 0,     -- 已采页数
     shops_found     INTEGER NOT NULL DEFAULT 0,     -- 累计提取到的店铺数（含重复）
     exhausted       INTEGER NOT NULL DEFAULT 0,     -- 1 = 已采到末页，之后跳过
     last_crawled_at TEXT
 );
+
+-- daemon 工作队列（fetcher daemon 模式）：shops 的 pending 店铺经
+-- topup_contact_work_items 入队，消费者线程用 claim_work_item 认领执行
+CREATE TABLE IF NOT EXISTS work_items (
+    id          INTEGER PRIMARY KEY AUTOINCREMENT,
+    queue       TEXT NOT NULL,             -- P0 固定 "crawl_1688_contact"
+    site        TEXT,                      -- "1688"
+    batch_id    INTEGER,                   -- P0 恒 NULL（平台批次 P4 接入）
+    payload_json TEXT NOT NULL,            -- contact: {"domain","name","url"}
+    requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
+    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/claimed/done/failed
+    claimed_by  TEXT,                      -- "w0".."wN"
+    claimed_at  TEXT,
+    finished_at TEXT,
+    result_json  TEXT,
+    created_at  TEXT NOT NULL
+);
+CREATE INDEX IF NOT EXISTS idx_work_items_claim ON work_items(queue, status, id);
 """
 
 # 依赖迁移后列（status）的索引，单独在 _migrate 之后创建
 INDEXES_AFTER_MIGRATE = """
 CREATE INDEX IF NOT EXISTS idx_shops_status ON shops(status);
 """
 
 
 def _now() -> str:
     return time.strftime("%Y-%m-%d %H:%M:%S")
@@ -379,20 +398,108 @@ class ShopDB:
 
         空联系方式现在也会入 contacts 表备查；此时 save_contact 已计过一次
         attempts，调用方应传 bump_attempts=False 避免重复计数。
         """
         sql = "UPDATE shops SET status='no_contact'"
         if bump_attempts:
             sql += ", attempts=attempts+1"
         self.conn.execute(sql + " WHERE domain=?", (domain,))
         self.conn.commit()
 
+    # ---------- work_items ----------
+    def topup_contact_work_items(self, queue: str, site: str,
+                                 domain_suffix: str, limit: int) -> int:
+        """从 shops 补货 work_items：最老的 pending 店铺入队并置 in_progress。
+
+        单事务内 SELECT + INSERT + UPDATE（BEGIN IMMEDIATE 立即取写锁）。
+        shops 状态语义与 claim_pending_shops 严格一致（pending → in_progress，
+        排序口径 first_seen_at, id），只是把「返回给调用方」改成「写入
+        work_items 表」；已入队店铺已非 pending，重复补货不会产生重复行。
+        """
+        try:
+            self.conn.execute("BEGIN IMMEDIATE")
+            rows = self.conn.execute(
+                "SELECT * FROM shops WHERE status='pending'"
+                " AND substr(domain, -?, ?) = ?"
+                " ORDER BY first_seen_at, id LIMIT ?",
+                (len(domain_suffix), len(domain_suffix), domain_suffix,
+                 limit)).fetchall()
+            now = _now()
+            for r in rows:
+                payload = json.dumps(
+                    {"domain": r["domain"], "name": r["name"],
+                     "url": r["url"]},
+                    ensure_ascii=False)
+                self.conn.execute(
+                    "INSERT INTO work_items (queue, site, payload_json,"
+                    " created_at) VALUES (?, ?, ?, ?)",
+                    (queue, site, payload, now))
+                self.conn.execute(
+                    "UPDATE shops SET status='in_progress' WHERE id=?",
+                    (r["id"],))
+            self.conn.commit()
+            return len(rows)
+        except Exception:
+            self.conn.rollback()
+            raise
+
+    def claim_work_item(self, queue: str, consumer_id: str) -> dict | None:
+        """原子认领该队列最老的 pending 工作项；无货返回 None。
+
+        SELECT + UPDATE 在同一 BEGIN IMMEDIATE 事务内，多消费者并发安全，
+        同一行只会被一个消费者领到。返回 {"id", "domain", "name", "url"}
+        （domain/name/url 解析自 payload_json）。
+        """
+        try:
+            self.conn.execute("BEGIN IMMEDIATE")
+            row = self.conn.execute(
+                "SELECT * FROM work_items WHERE queue=? AND status='pending'"
+                " ORDER BY id LIMIT 1", (queue,)).fetchone()
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
+        payload = json.loads(row["payload_json"])
+        return {"id": row["id"], "domain": payload.get("domain"),
+                "name": payload.get("name"), "url": payload.get("url")}
+
+    def finish_work_item(self, item_id: int, status: str,
+                         result: dict | None = None) -> None:
+        """工作项落终态（done/failed）+ finished_at + result_json。
+
+        result 为 None 时 result_json 存 NULL。
+        """
+        self.conn.execute(
+            "UPDATE work_items SET status=?, finished_at=?, result_json=?"
+            " WHERE id=?",
+            (status, _now(),
+             json.dumps(result, ensure_ascii=False)
+             if result is not None else None,
+             item_id))
+        self.conn.commit()
+
+    def reset_claimed_work_items(self) -> int:
+        """全部 claimed 工作项重置回 pending（进程中断残留的认领，
+        daemon 启动时调用），清空 claimed_by/claimed_at，返回重置行数。"""
+        cur = self.conn.execute(
+            "UPDATE work_items SET status='pending', claimed_by=NULL,"
+            " claimed_at=NULL WHERE status='claimed'")
+        self.conn.commit()
+        return cur.rowcount
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
new file mode 100644
index 0000000..cce84b9
--- /dev/null
+++ b/fetcher/tests/test_work_items.py
@@ -0,0 +1,166 @@
+# -*- coding: utf-8 -*-
+"""work_items 存储层测试：topup / claim / finish / reset 四方法（临时 sqlite）。
+仿 test_contact_task.py 基建，不起浏览器/网络。"""
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+
+from fetcher.db import ShopDB
+
+QUEUE = "crawl_1688_contact"
+
+
+def _shop(i, suffix=".1688.com"):
+    return {"domain": f"shop{i}{suffix}", "name": f"店铺{i}",
+            "url": f"https://shop{i}{suffix}"}
+
+
+class WorkItemsTest(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "t.db")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def _items(self, where="", params=()):
+        return self.db.conn.execute(
+            f"SELECT * FROM work_items {where}", params).fetchall()
+
+    def _shop_status(self, domain):
+        return self.db.conn.execute(
+            "SELECT status FROM shops WHERE domain=?",
+            (domain,)).fetchone()[0]
+
+    # 用例 1：top-up 生成 work_items 且 shops 标 in_progress；
+    # 重复 top-up 只补剩余 pending，不产生重复行
+    def test_topup_marks_shops_and_no_duplicates(self):
+        # DDL 前置断言：表与索引存在、列齐全
+        cols = {r[1] for r in self.db.conn.execute(
+            "PRAGMA table_info(work_items)")}
+        self.assertEqual(
+            cols, {"id", "queue", "site", "batch_id", "payload_json",
+                   "requires", "status", "claimed_by", "claimed_at",
+                   "finished_at", "result_json", "created_at"})
+        idx = {r[1] for r in self.db.conn.execute(
+            "PRAGMA index_list(work_items)")}
+        self.assertIn("idx_work_items_claim", idx)
+
+        # 3 家 1688 店铺 + 1 家 madeinchina（suffix 不匹配，不应入队）
+        self.db.upsert_shops([_shop(1), _shop(2), _shop(3),
+                              _shop(9, ".cn.made-in-china.com")])
+        n = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+        self.assertEqual(n, 2)
+
+        items = self._items("ORDER BY id")
+        self.assertEqual(len(items), 2)
+        # 排序口径与 claim_pending_shops 一致：first_seen_at, id（最老优先）
+        self.assertEqual([json.loads(r["payload_json"])["domain"]
+                          for r in items],
+                         ["shop1.1688.com", "shop2.1688.com"])
+        for r in items:
+            self.assertEqual(r["queue"], QUEUE)
+            self.assertEqual(r["site"], "1688")
+            self.assertEqual(r["status"], "pending")
+            self.assertEqual(r["requires"], '["channel","browser"]')
+            self.assertIsNone(r["batch_id"])
+            self.assertIsNotNone(r["created_at"])
+            payload = json.loads(r["payload_json"])
+            self.assertEqual(set(payload), {"domain", "name", "url"})
+        # shops 侧状态语义：被补货的标 in_progress，其余不动
+        self.assertEqual(self._shop_status("shop1.1688.com"), "in_progress")
+        self.assertEqual(self._shop_status("shop2.1688.com"), "in_progress")
+        self.assertEqual(self._shop_status("shop3.1688.com"), "pending")
+        self.assertEqual(self._shop_status("shop9.cn.made-in-china.com"),
+                         "pending")
+
+        # 重复 top-up：已入队的店铺已是 in_progress，只补剩余 pending
+        n2 = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+        self.assertEqual(n2, 1)
+        domains = [json.loads(r["payload_json"])["domain"]
+                   for r in self._items()]
+        self.assertEqual(sorted(domains), ["shop1.1688.com", "shop2.1688.com",
+                                           "shop3.1688.com"])
+        self.assertEqual(len(domains), len(set(domains)))  # 无重复行
+
+    # 用例 5：空 shops 时 top-up 返回 0
+    def test_topup_empty_returns_zero(self):
+        n = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 5)
+        self.assertEqual(n, 0)
+        self.assertEqual(self._items(), [])
+
+    # 用例 2：两个消费者认领不到同一行（顺序模拟并发）
+    def test_claim_no_double_claim(self):
+        self.db.upsert_shops([_shop(1), _shop(2)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+
+        a = self.db.claim_work_item(QUEUE, "w0")
+        b = self.db.claim_work_item(QUEUE, "w1")
+        self.assertIsNotNone(a)
+        self.assertIsNotNone(b)
+        self.assertNotEqual(a["id"], b["id"])  # 不撞单
+        # 返回 dict 含 id + payload 解析后的 domain/name/url
+        self.assertEqual(a["domain"], "shop1.1688.com")  # 最老 pending 先领
+        self.assertEqual(a["name"], "店铺1")
+        self.assertEqual(a["url"], "https://shop1.1688.com")
+        self.assertEqual(b["domain"], "shop2.1688.com")
+        # 库内状态：claimed + claimed_by + claimed_at
+        rows = {r["id"]: r for r in self._items()}
+        self.assertEqual(rows[a["id"]]["status"], "claimed")
+        self.assertEqual(rows[a["id"]]["claimed_by"], "w0")
+        self.assertIsNotNone(rows[a["id"]]["claimed_at"])
+        self.assertEqual(rows[b["id"]]["claimed_by"], "w1")
+        # 队列领空后返回 None
+        self.assertIsNone(self.db.claim_work_item(QUEUE, "w2"))
+
+    # 用例 3：finish 落终态 + finished_at + result_json
+    def test_finish_work_item(self):
+        self.db.upsert_shops([_shop(1), _shop(2)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
+        a = self.db.claim_work_item(QUEUE, "w0")
+        b = self.db.claim_work_item(QUEUE, "w1")
+
+        self.db.finish_work_item(a["id"], "done", {"mobile": "13800138000"})
+        row = self.db.conn.execute(
+            "SELECT * FROM work_items WHERE id=?", (a["id"],)).fetchone()
+        self.assertEqual(row["status"], "done")
+        self.assertIsNotNone(row["finished_at"])
+        self.assertEqual(json.loads(row["result_json"]),
+                         {"mobile": "13800138000"})
+
+        # result=None 时 result_json 存 NULL
+        self.db.finish_work_item(b["id"], "failed")
+        row = self.db.conn.execute(
+            "SELECT * FROM work_items WHERE id=?", (b["id"],)).fetchone()
+        self.assertEqual(row["status"], "failed")
+        self.assertIsNotNone(row["finished_at"])
+        self.assertIsNone(row["result_json"])
+
+    # 用例 4：reset_claimed 把 claimed 重置为 pending（清空认领信息）
+    def test_reset_claimed_work_items(self):
+        self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
+        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 3)
+        a = self.db.claim_work_item(QUEUE, "w0")
+        b = self.db.claim_work_item(QUEUE, "w1")
+        # shop3 的工作项仍是 pending，不应受影响
+
+        n = self.db.reset_claimed_work_items()
+        self.assertEqual(n, 2)
+        rows = {r["id"]: r for r in self._items()}
+        for item_id in (a["id"], b["id"]):
+            self.assertEqual(rows[item_id]["status"], "pending")
+            self.assertIsNone(rows[item_id]["claimed_by"])
+            self.assertIsNone(rows[item_id]["claimed_at"])
+        others = [r for r in self._items()
+                  if r["id"] not in (a["id"], b["id"])]
+        self.assertEqual(len(others), 1)
+        self.assertEqual(others[0]["status"], "pending")
+        # 无 claimed 行时返回 0
+        self.assertEqual(self.db.reset_claimed_work_items(), 0)
+
+
+if __name__ == "__main__":
+    unittest.main()
