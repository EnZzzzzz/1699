# -*- coding: utf-8 -*-
"""work_items 存储层测试：topup / claim / finish / reset / release / claim_next_eligible
（临时 sqlite）。仿 test_contact_task.py 基建，不起浏览器/网络。"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fetcher.db import SCHEMA, ShopDB

QUEUE = "crawl_1688_contact"


def _shop(i, suffix=".1688.com"):
    return {"domain": f"shop{i}{suffix}", "name": f"店铺{i}",
            "url": f"https://shop{i}{suffix}"}


class WorkItemsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _items(self, where="", params=()):
        return self.db.conn.execute(
            f"SELECT * FROM work_items {where}", params).fetchall()

    def _shop_status(self, domain):
        return self.db.conn.execute(
            "SELECT status FROM shops WHERE domain=?",
            (domain,)).fetchone()[0]

    # 用例 1：top-up 生成 work_items 且 shops 标 in_progress；
    # 重复 top-up 只补剩余 pending，不产生重复行
    def test_topup_marks_shops_and_no_duplicates(self):
        # DDL 前置断言：表与索引存在、列齐全
        cols = {r[1] for r in self.db.conn.execute(
            "PRAGMA table_info(work_items)")}
        self.assertEqual(
            cols, {"id", "queue", "site", "batch_id", "payload_json",
                   "requires", "status", "attempts", "claimed_by",
                   "claimed_at", "finished_at", "result_json",
                   "created_at"})
        idx = {r[1] for r in self.db.conn.execute(
            "PRAGMA index_list(work_items)")}
        self.assertIn("idx_work_items_claim", idx)

        # 3 家 1688 店铺 + 1 家 madeinchina（suffix 不匹配，不应入队）
        self.db.upsert_shops([_shop(1), _shop(2), _shop(3),
                              _shop(9, ".cn.made-in-china.com")])
        n = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
        self.assertEqual(n, 2)

        items = self._items("ORDER BY id")
        self.assertEqual(len(items), 2)
        # 排序口径与 claim_pending_shops 一致：first_seen_at, id（最老优先）
        self.assertEqual([json.loads(r["payload_json"])["domain"]
                          for r in items],
                         ["shop1.1688.com", "shop2.1688.com"])
        for r in items:
            self.assertEqual(r["queue"], QUEUE)
            self.assertEqual(r["site"], "1688")
            self.assertEqual(r["status"], "pending")
            self.assertEqual(r["requires"], '["channel","browser"]')
            self.assertIsNone(r["batch_id"])
            self.assertIsNotNone(r["created_at"])
            payload = json.loads(r["payload_json"])
            self.assertEqual(set(payload), {"domain", "name", "url"})
        # shops 侧状态语义：被补货的标 in_progress，其余不动
        self.assertEqual(self._shop_status("shop1.1688.com"), "in_progress")
        self.assertEqual(self._shop_status("shop2.1688.com"), "in_progress")
        self.assertEqual(self._shop_status("shop3.1688.com"), "pending")
        self.assertEqual(self._shop_status("shop9.cn.made-in-china.com"),
                         "pending")

        # 重复 top-up：已入队的店铺已是 in_progress，只补剩余 pending
        n2 = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
        self.assertEqual(n2, 1)
        domains = [json.loads(r["payload_json"])["domain"]
                   for r in self._items()]
        self.assertEqual(sorted(domains), ["shop1.1688.com", "shop2.1688.com",
                                           "shop3.1688.com"])
        self.assertEqual(len(domains), len(set(domains)))  # 无重复行

    # 用例 5：空 shops 时 top-up 返回 0
    def test_topup_empty_returns_zero(self):
        n = self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 5)
        self.assertEqual(n, 0)
        self.assertEqual(self._items(), [])

    # 用例 2：两个消费者认领不到同一行（顺序模拟并发）
    def test_claim_no_double_claim(self):
        self.db.upsert_shops([_shop(1), _shop(2)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)

        a = self.db.claim_work_item(QUEUE, "w0")
        b = self.db.claim_work_item(QUEUE, "w1")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a["id"], b["id"])  # 不撞单
        # 返回 dict 含 id + payload 解析后的 domain/name/url
        self.assertEqual(a["domain"], "shop1.1688.com")  # 最老 pending 先领
        self.assertEqual(a["name"], "店铺1")
        self.assertEqual(a["url"], "https://shop1.1688.com")
        self.assertEqual(b["domain"], "shop2.1688.com")
        # 库内状态：claimed + claimed_by + claimed_at
        rows = {r["id"]: r for r in self._items()}
        self.assertEqual(rows[a["id"]]["status"], "claimed")
        self.assertEqual(rows[a["id"]]["claimed_by"], "w0")
        self.assertIsNotNone(rows[a["id"]]["claimed_at"])
        self.assertEqual(rows[b["id"]]["claimed_by"], "w1")
        # 队列领空后返回 None
        self.assertIsNone(self.db.claim_work_item(QUEUE, "w2"))

    # 用例 3：finish 落终态 + finished_at + result_json
    def test_finish_work_item(self):
        self.db.upsert_shops([_shop(1), _shop(2)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
        a = self.db.claim_work_item(QUEUE, "w0")
        b = self.db.claim_work_item(QUEUE, "w1")

        self.db.finish_work_item(a["id"], "done", {"mobile": "13800138000"})
        row = self.db.conn.execute(
            "SELECT * FROM work_items WHERE id=?", (a["id"],)).fetchone()
        self.assertEqual(row["status"], "done")
        self.assertIsNotNone(row["finished_at"])
        self.assertEqual(json.loads(row["result_json"]),
                         {"mobile": "13800138000"})

        # result=None 时 result_json 存 NULL
        self.db.finish_work_item(b["id"], "failed")
        row = self.db.conn.execute(
            "SELECT * FROM work_items WHERE id=?", (b["id"],)).fetchone()
        self.assertEqual(row["status"], "failed")
        self.assertIsNotNone(row["finished_at"])
        self.assertIsNone(row["result_json"])

    # 用例 4：reset_claimed 把 claimed 重置为 pending（清空认领信息）
    def test_reset_claimed_work_items(self):
        self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 3)
        a = self.db.claim_work_item(QUEUE, "w0")
        b = self.db.claim_work_item(QUEUE, "w1")
        # shop3 的工作项仍是 pending，不应受影响

        n = self.db.reset_claimed_work_items()
        self.assertEqual(n, 2)
        rows = {r["id"]: r for r in self._items()}
        for item_id in (a["id"], b["id"]):
            self.assertEqual(rows[item_id]["status"], "pending")
            self.assertIsNone(rows[item_id]["claimed_by"])
            self.assertIsNone(rows[item_id]["claimed_at"])
        others = [r for r in self._items()
                  if r["id"] not in (a["id"], b["id"])]
        self.assertEqual(len(others), 1)
        self.assertEqual(others[0]["status"], "pending")
        # 无 claimed 行时返回 0
        self.assertEqual(self.db.reset_claimed_work_items(), 0)


    # ---------- P3 Step 1.1: attempts / release_work_item / claim_next_eligible ----------
    def _insert_item(self, queue, payload, site="1688"):
        """直接向 work_items 插 pending 行（绕过 topup，便于多队列交叉构造）。"""
        cur = self.db.conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, created_at)"
            " VALUES (?, ?, ?, ?)",
            (queue, site, json.dumps(payload, ensure_ascii=False),
             "2025-08-08 00:00:00"))
        self.db.conn.commit()
        return cur.lastrowid

    # 用例 1：release 回 pending，可重领且 attempts 保留
    def test_release_returns_to_pending(self):
        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
        got = self.db.claim_next_eligible(["q1"], "w0")
        self.assertEqual(got["id"], iid)

        ret = self.db.release_work_item(iid)
        self.assertEqual(ret, "pending")
        row = self.db.conn.execute(
            "SELECT * FROM work_items WHERE id=?", (iid,)).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 1)
        self.assertIsNone(row["claimed_by"])
        self.assertIsNone(row["claimed_at"])
        self.assertIsNone(row["finished_at"])

        # 重领：attempts 保留（claim 不重置 attempts）
        got2 = self.db.claim_next_eligible(["q1"], "w1")
        self.assertEqual(got2["id"], iid)
        row = self.db.conn.execute(
            "SELECT status, attempts FROM work_items WHERE id=?",
            (iid,)).fetchone()
        self.assertEqual(row["status"], "claimed")
        self.assertEqual(row["attempts"], 1)

    # 用例 2：attempts 耗尽置 failed
    def test_release_exhausts_attempts_to_failed(self):
        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
        results = []
        for _ in range(3):
            self.db.claim_next_eligible(["q1"], "w0")
            results.append(self.db.release_work_item(iid))
        self.assertEqual(results, ["pending", "pending", "failed"])
        row = self.db.conn.execute(
            "SELECT * FROM work_items WHERE id=?", (iid,)).fetchone()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(json.loads(row["result_json"]), "attempts exhausted")
        self.assertIsNotNone(row["finished_at"])

    # 用例 3：release 终态返回值（不足上限 pending，达上限 failed）
    def test_release_terminal_return_with_custom_max_attempts(self):
        iid = self._insert_item("q1", {"domain": "shop1.1688.com"})
        self.db.claim_next_eligible(["q1"], "w0")
        self.assertEqual(self.db.release_work_item(iid, max_attempts=2),
                         "pending")
        self.db.claim_next_eligible(["q1"], "w0")
        self.assertEqual(self.db.release_work_item(iid, max_attempts=2),
                         "failed")
        row = self.db.conn.execute(
            "SELECT status, attempts FROM work_items WHERE id=?",
            (iid,)).fetchone()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 2)

    # 用例 4：release 非 claimed 防御（返回 failed 且行内容不变）
    def test_release_on_non_claimed_is_defensive_failed(self):
        # pending 行
        pid = self._insert_item("q1", {"domain": "shop1.1688.com"})
        self.assertEqual(self.db.release_work_item(pid), "failed")
        row = self.db.conn.execute(
            "SELECT * FROM work_items WHERE id=?", (pid,)).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 0)
        self.assertIsNone(row["claimed_by"])
        self.assertIsNone(row["finished_at"])
        self.assertIsNone(row["result_json"])

        # done 行
        did = self._insert_item("q1", {"domain": "shop2.1688.com"})
        self.db.claim_next_eligible(["q1"], "w0")
        self.db.finish_work_item(did, "done", {"ok": True})
        self.assertEqual(self.db.release_work_item(did), "failed")
        row = self.db.conn.execute(
            "SELECT * FROM work_items WHERE id=?", (did,)).fetchone()
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["attempts"], 0)
        self.assertEqual(json.loads(row["result_json"]), {"ok": True})

        # 不存在的 id
        self.assertEqual(self.db.release_work_item(99999), "failed")

    # 用例 5：claim_next_eligible 队列集合过滤
    def test_claim_next_eligible_filters_queues(self):
        a = self._insert_item("queue_a", {"domain": "a1.1688.com"})
        b = self._insert_item("queue_b", {"domain": "b1.1688.com"})
        c = self._insert_item("queue_c", {"domain": "c1.1688.com"})

        got = self.db.claim_next_eligible(["queue_a"], "w0")
        self.assertEqual(got["id"], a)
        self.assertEqual(got["queue"], "queue_a")
        self.assertEqual(got["site"], "1688")
        self.assertEqual(got["payload"], {"domain": "a1.1688.com"})
        for iid in (b, c):
            row = self.db.conn.execute(
                "SELECT status FROM work_items WHERE id=?",
                (iid,)).fetchone()
            self.assertEqual(row["status"], "pending")

        got2 = self.db.claim_next_eligible(["queue_a", "queue_b"], "w1")
        self.assertEqual(got2["id"], b)
        row_c = self.db.conn.execute(
            "SELECT status FROM work_items WHERE id=?", (c,)).fetchone()
        self.assertEqual(row_c["status"], "pending")

    # 用例 6：FIFO（多队混排按 id 最老先领，无优先级）
    def test_claim_next_eligible_fifo_by_id_across_queues(self):
        ids = [self._insert_item(q, {"domain": f"{q}-{i}.1688.com"})
               for i, q in enumerate(["A", "B", "A", "B"])]
        claimed = []
        for _ in range(4):
            got = self.db.claim_next_eligible(["A", "B"], "w0")
            self.assertIsNotNone(got)
            claimed.append(got["id"])
        self.assertEqual(claimed, ids)  # 严格按 id 升序
        self.assertIsNone(self.db.claim_next_eligible(["A", "B"], "w0"))

    # 用例 7：并发不重复认领（顺序模拟两个消费者）
    def test_claim_next_eligible_no_double_claim(self):
        i1 = self._insert_item("q1", {"domain": "shop1.1688.com"})
        i2 = self._insert_item("q1", {"domain": "shop2.1688.com"})
        a = self.db.claim_next_eligible(["q1"], "w0")
        b = self.db.claim_next_eligible(["q1"], "w1")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(sorted([a["id"], b["id"]]), [i1, i2])
        rows = {r["id"]: r for r in self._items()}
        self.assertEqual(rows[a["id"]]["claimed_by"], "w0")
        self.assertEqual(rows[b["id"]]["claimed_by"], "w1")
        self.assertIsNone(self.db.claim_next_eligible(["q1"], "w2"))

    # 用例 8：attempts 列存在性 + 旧库迁移（存量行默认 0）
    def test_attempts_column_present_and_legacy_migration(self):
        cols = {r[1] for r in self.db.conn.execute(
            "PRAGMA table_info(work_items)")}
        self.assertIn("attempts", cols)

        # 手工构造无 attempts 列的旧库（模拟 P3 前 schema）
        legacy_path = str(Path(self._tmp.name) / "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.execute("DROP TABLE work_items")
        conn.execute(
            """CREATE TABLE work_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                queue       TEXT NOT NULL,
                site        TEXT,
                batch_id    INTEGER,
                payload_json TEXT NOT NULL,
                requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
                status      TEXT NOT NULL DEFAULT 'pending',
                claimed_by  TEXT,
                claimed_at  TEXT,
                finished_at TEXT,
                result_json TEXT,
                created_at  TEXT NOT NULL)""")
        conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, created_at)"
            " VALUES ('q1', 's1', '{}', '2025-08-08 00:00:00')")
        conn.commit()
        conn.close()

        db2 = ShopDB(legacy_path)
        cols2 = {r[1] for r in db2.conn.execute(
            "PRAGMA table_info(work_items)")}
        self.assertIn("attempts", cols2)
        row = db2.conn.execute(
            "SELECT attempts FROM work_items WHERE queue='q1'").fetchone()
        self.assertEqual(row["attempts"], 0)
        # 幂等：重开再迁移不报错、列仍存在
        db2.close()
        db3 = ShopDB(legacy_path)
        cols3 = {r[1] for r in db3.conn.execute(
            "PRAGMA table_info(work_items)")}
        self.assertIn("attempts", cols3)
        db3.close()

    # 用例 9：空队列返回 None
    def test_claim_next_eligible_empty_queues_returns_none(self):
        self._insert_item("q1", {"domain": "shop1.1688.com"})
        self.assertIsNone(self.db.claim_next_eligible([], "w0"))
        row = self.db.conn.execute(
            "SELECT status FROM work_items").fetchone()
        self.assertEqual(row["status"], "pending")  # 不碰任何行


if __name__ == "__main__":
    unittest.main()
