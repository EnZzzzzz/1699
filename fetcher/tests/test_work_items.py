# -*- coding: utf-8 -*-
"""work_items 存储层测试：topup / claim / finish / reset 四方法（临时 sqlite）。
仿 test_contact_task.py 基建，不起浏览器/网络。"""

import json
import tempfile
import unittest
from pathlib import Path

from fetcher.db import ShopDB

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
                   "requires", "status", "claimed_by", "claimed_at",
                   "finished_at", "result_json", "created_at"})
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


if __name__ == "__main__":
    unittest.main()
