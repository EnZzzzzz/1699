# -*- coding: utf-8 -*-
"""批次入队存储层测试：enqueue_contact_batch / enqueue_feeder_batch /
stopped 态排除 / batch 索引（临时 sqlite）。

仿 test_work_items.py 基建，不起浏览器/网络。
"""

import json
import tempfile
import unittest
from pathlib import Path

from fetcher.db import ShopDB

QUEUE = "crawl_1688_contact"
FEEDER_QUEUE = "crawl_1688_shop"
SITE = "1688"


def _shop(i, suffix=".1688.com"):
    return {"domain": f"shop{i}{suffix}", "name": f"店铺{i}",
            "url": f"https://shop{i}{suffix}"}


class BatchEnqueueTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _items(self, where="", params=()):
        return self.db.conn.execute(
            f"SELECT * FROM work_items {where}", params).fetchall()

    def _pending_batch_items(self, batch_id):
        return self.db.conn.execute(
            "SELECT * FROM work_items WHERE batch_id=? AND status='pending'"
            " ORDER BY id", (batch_id,)).fetchall()

    # ---- 用例 1：enqueue_contact_batch 入队带 batch_id + 限量 ----

    def test_contact_batch_enqueues_with_batch_id_and_limit(self):
        self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
        n = self.db.enqueue_contact_batch(
            QUEUE, SITE, ".1688.com", batch_id=42, limit=2)
        self.assertEqual(n, 2)

        items = self._pending_batch_items(42)
        self.assertEqual(len(items), 2)
        for r in items:
            self.assertEqual(r["queue"], QUEUE)
            self.assertEqual(r["batch_id"], 42)
            self.assertEqual(r["status"], "pending")
            payload = json.loads(r["payload_json"])
            self.assertEqual(set(payload), {"domain", "name", "url"})
        # 排序与 topup 同口径：first_seen_at, id
        self.assertEqual([json.loads(r["payload_json"])["domain"]
                          for r in items],
                         ["shop1.1688.com", "shop2.1688.com"])
        # shops 置 in_progress（与 topup 同事务语义）
        self.assertEqual(self.db.conn.execute(
            "SELECT status FROM shops WHERE domain='shop1.1688.com'"
        ).fetchone()[0], "in_progress")

    def test_contact_batch_limit_zero_is_unlimited(self):
        self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
        n = self.db.enqueue_contact_batch(
            QUEUE, SITE, ".1688.com", batch_id=7, limit=0)
        self.assertEqual(n, 3)

    # ---- 用例 2：幂等 + 与 topup 不双喂 ----

    def test_contact_batch_idempotent_and_no_double_feed_with_topup(self):
        self.db.upsert_shops([_shop(1), _shop(2)])
        self.db.enqueue_contact_batch(
            QUEUE, SITE, ".1688.com", batch_id=1, limit=0)
        # 重复 enqueue 同一批次：已 in_progress 不再选，0 新增
        n2 = self.db.enqueue_contact_batch(
            QUEUE, SITE, ".1688.com", batch_id=1, limit=0)
        self.assertEqual(n2, 0)
        # daemon 自喂 topup：同一批店铺已被批次占用，topup 补不到
        n3 = self.db.topup_contact_work_items(QUEUE, SITE, ".1688.com", 5)
        self.assertEqual(n3, 0)
        # 总行数 = 2，且全部 batch_id=1（无 batch_id NULL 混入）
        items = self._items()
        self.assertEqual(len(items), 2)
        self.assertEqual({r["batch_id"] for r in items}, {1})

    def test_contact_batch_and_topup_no_double_claim(self):
        """先 topup 后 enqueue：topup 已占的店 enqueue 不再选（反向验证）。"""
        self.db.upsert_shops([_shop(1), _shop(2)])
        self.db.topup_contact_work_items(QUEUE, SITE, ".1688.com", 2)
        n = self.db.enqueue_contact_batch(
            QUEUE, SITE, ".1688.com", batch_id=9, limit=0)
        self.assertEqual(n, 0)
        items = self._items()
        self.assertEqual(len(items), 2)
        self.assertEqual({r["batch_id"] for r in items}, {None})

    # ---- 用例 3：enqueue_feeder_batch discover + category 种子 ----

    def _seed_category_progress(self):
        # 手工插两条未采完类目
        for kw, name in [("女装", "女装类目"), ("男装", "男装类目")]:
            self.db.conn.execute(
                "INSERT INTO category_progress"
                " (keyword, name, next_page, pages_crawled, shops_found,"
                "  exhausted, last_crawled_at)"
                " VALUES (?, ?, 1, 0, 0, 0, '2026-08-08 10:00:00')",
                (kw, name))
        self.db.conn.commit()

    def test_feeder_batch_seeds_discover_and_categories(self):
        self._seed_category_progress()
        n_cat, n_disc = self.db.enqueue_feeder_batch(
            FEEDER_QUEUE, SITE, batch_id=5, limit=3)

        self.assertEqual(n_cat, 2)
        self.assertEqual(n_disc, 1)
        items = self._pending_batch_items(5)
        self.assertEqual(len(items), 3)
        # discover 一条 + category 两条，全部带 batch_id 与 batch_limit
        disc = [r for r in items
                if json.loads(r["payload_json"])["kind"] == "discover"]
        cats = [r for r in items
                if json.loads(r["payload_json"])["kind"] == "category"]
        self.assertEqual(len(disc), 1)
        self.assertEqual(len(cats), 2)
        self.assertEqual(json.loads(disc[0]["payload_json"])["batch_limit"], 3)
        for r in cats:
            payload = json.loads(r["payload_json"])
            self.assertEqual(payload["batch_limit"], 3)
            self.assertIn(payload["keyword"], {"女装", "男装"})

    def test_feeder_batch_idempotent(self):
        self._seed_category_progress()
        self.db.enqueue_feeder_batch(FEEDER_QUEUE, SITE, batch_id=5, limit=3)
        # 重复 enqueue：已有同 keyword pending category / pending discover 跳过
        n_cat, n_disc = self.db.enqueue_feeder_batch(
            FEEDER_QUEUE, SITE, batch_id=5, limit=3)
        self.assertEqual(n_cat, 0)
        self.assertEqual(n_disc, 0)
        self.assertEqual(len(self._items()), 3)

    def test_feeder_batch_empty_categories_still_discover(self):
        # 无未采完类目：仍插 1 条 discover
        n_cat, n_disc = self.db.enqueue_feeder_batch(
            FEEDER_QUEUE, SITE, batch_id=6, limit=0)
        self.assertEqual(n_cat, 0)
        self.assertEqual(n_disc, 1)
        items = self._pending_batch_items(6)
        self.assertEqual(len(items), 1)
        self.assertEqual(json.loads(items[0]["payload_json"])["kind"],
                         "discover")
        self.assertEqual(json.loads(items[0]["payload_json"])["batch_limit"], 0)

    # ---- 用例 4：stopped 不被 claim ----

    def test_stopped_items_not_claimed(self):
        self.db.upsert_shops([_shop(1), _shop(2)])
        self.db.enqueue_contact_batch(
            QUEUE, SITE, ".1688.com", batch_id=3, limit=0)
        # 手动把第一条置 stopped（平台 stop 端点行为）
        self.db.conn.execute(
            "UPDATE work_items SET status='stopped' WHERE id=?",
            (self._items()[0]["id"],))
        self.db.conn.commit()
        # claim 只认 pending：stopped 的不会被领到
        item = self.db.claim_next_eligible([QUEUE], "w0")
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], self._items()[1]["id"])
        self.assertIsNone(self.db.claim_next_eligible([QUEUE], "w1"))

    # ---- 用例 5：batch 索引存在 ----

    def test_batch_index_exists(self):
        idx = {r[1] for r in self.db.conn.execute(
            "PRAGMA index_list(work_items)")}
        self.assertIn("idx_work_items_batch", idx)


if __name__ == "__main__":
    unittest.main()
