# -*- coding: utf-8 -*-
"""P4 Step 0.2: feeder 批次继承与限量收束测试。

discover 产出 / 链式续喂 / 失败补插必须继承父 item 的 batch_id 与
batch_limit；续喂/补插前 done 计数 ≥ batch_limit 则收束；batch_id NULL
的 daemon 自喂路径逐字不变（行为零变化）。
全 mock，不起浏览器/网络。仿 test_1688_feeder 基建。
"""

import json
import tempfile
import unittest
from pathlib import Path

from fetcher import RunConfig, Session, ShopDB, WorkerContext
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.alibaba1688.shop import Alibaba1688ShopTask
from fetcher.sites.alibaba1688.company import Alibaba1688CompanyTask
from fetcher.sites.madeinchina.shop import MadeInChinaShopTask

SHOP_QUEUE = "crawl_1688_shop"
COMPANY_QUEUE = "crawl_1688_company"
MIC_QUEUE = "crawl_mic_shop"
SITE = "1688"
MIC_SITE = "madeinchina"


def ok_result(data=None):
    return ActionResult(Outcome.OK, "", data or {})


def make_ctx(db=None):
    ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
    ctx.session = Session(page=None)
    if db is not None:
        from fetcher import IdentityStore
        ctx.store = IdentityStore(db)
    return ctx


def _insert_item(db: ShopDB, payload: dict, queue=SHOP_QUEUE, site=SITE,
                 batch_id=None) -> int:
    """直接向 work_items 插 pending 行（可带 batch_id），返回 id。"""
    cur = db.conn.execute(
        "INSERT INTO work_items (queue, site, batch_id, payload_json,"
        " created_at) VALUES (?, ?, ?, ?, datetime('now', 'localtime'))",
        (queue, site, batch_id, json.dumps(payload, ensure_ascii=False)))
    db.conn.commit()
    return cur.lastrowid


def _cat_payload(keyword="女装", name="女装", batch_limit=None,
                 batch_id=None):
    p = {"kind": "category", "keyword": keyword, "name": name}
    if batch_limit is not None:
        p["batch_limit"] = batch_limit
    if batch_id is not None:
        p["batch_id"] = batch_id
    return p


def _discover_payload(batch_limit=None, batch_id=None):
    p = {"kind": "discover"}
    if batch_limit is not None:
        p["batch_limit"] = batch_limit
    if batch_id is not None:
        p["batch_id"] = batch_id
    return p


def _pending_items(db, queue=SHOP_QUEUE):
    rows = db.conn.execute(
        "SELECT id, batch_id, payload_json FROM work_items WHERE queue=?"
        " AND status='pending' ORDER BY id", (queue,)).fetchall()
    return [(r["id"], r["batch_id"], json.loads(r["payload_json"]))
            for r in rows]


def _mark_done(db, item_id: int, batch_id: int = None) -> None:
    """把 item 置 done（batch 收束计数用）。"""
    db.conn.execute(
        "UPDATE work_items SET status='done', finished_at="
        " datetime('now', 'localtime') WHERE id=?", (item_id,))
    db.conn.commit()


class ClaimBatchIdTest(unittest.TestCase):
    """claim_next_eligible 必须把 batch_id 透传给上层（feeder 继承用）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_claim_returns_batch_id(self):
        self.db.upsert_shops(
            [{"domain": "shop1.1688.com", "name": "店1",
              "url": "https://shop1.1688.com"}])
        self.db.enqueue_contact_batch(SHOP_QUEUE, SITE, ".1688.com",
                                      batch_id=99, limit=0)
        item = self.db.claim_next_eligible([SHOP_QUEUE], "w0")
        self.assertIsNotNone(item)
        self.assertEqual(item["batch_id"], 99)
        self.assertIn("batch_id", item)

    def test_claim_batch_id_none_for_self_feed(self):
        """daemon 自喂（topup）item 的 batch_id 为 None。"""
        self.db.upsert_shops(
            [{"domain": "shop1.1688.com", "name": "店1",
              "url": "https://shop1.1688.com"}])
        self.db.topup_contact_work_items(SHOP_QUEUE, SITE, ".1688.com", 1)
        item = self.db.claim_next_eligible([SHOP_QUEUE], "w0")
        self.assertIsNotNone(item)
        self.assertIsNone(item["batch_id"])


class ShopBatchInheritTest(unittest.TestCase):
    """1688 shop：discover 产出 / 链式续喂 / refill 继承 batch_id。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = Alibaba1688ShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _ctx(self):
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}
        return ctx

    # ---- discover 产出继承 ----

    def test_discover_produced_items_inherit_batch(self):
        """discover（batch_id=7, batch_limit=5）产出的 category item
        必须带同一 batch_id 与 batch_limit。"""
        ctx = self._ctx()
        # 模拟真实链路：claim 返回 batch_id → acquire 注入 payload
        item = _discover_payload(batch_limit=5, batch_id=7)
        item["id"] = _insert_item(self.db, item, batch_id=7)
        # mock 首页类目提取：两条新类目
        from unittest.mock import patch
        cats = [{"name": "新类目A", "keyword": "新类目A"},
                {"name": "新类目B", "keyword": "新类目B"}]
        with patch("fetcher.sites.alibaba1688.shop."
                   "fetch_homepage_categories", return_value=cats):
            self.task._on_discover_success(ctx, item, ok_result())

        items = _pending_items(self.db)
        # 1 个 discover（原 item 已被认领不算 pending 了）→ 2 个 category
        cats_pending = [r for r in items
                        if r[2]["kind"] == "category"]
        self.assertEqual(len(cats_pending), 2)
        for _id, bid, payload in cats_pending:
            self.assertEqual(bid, 7)
            self.assertEqual(payload["batch_limit"], 5)

    # ---- 链式续喂继承 + 收束 ----

    def test_chain_feed_inherits_batch_id(self):
        """category item（batch_id=3, batch_limit=0）续喂的下一页 item
        继承 batch_id；batch_limit=0 不收束。"""
        ctx = self._ctx()
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page,"
            " pages_crawled, shops_found, exhausted, last_crawled_at)"
            " VALUES ('女装', '女装', 1, 0, 0, 0, '2026-08-08 10:00:00')")
        self.db.conn.commit()
        item = _cat_payload("女装", "女装", batch_limit=0, batch_id=3)
        # 当前 item 已被 claim（不在 pending 中），仅造批次 done 计数项
        result = ok_result({
            "shops": [{"domain": "shop1.1688.com", "name": "店1",
                       "url": "https://shop1.1688.com"}],
            "has_more": True,
        })
        self.task._on_category_success(ctx, item, result)

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        _id, bid, payload = items[0]
        self.assertEqual(bid, 3)
        self.assertEqual(payload["batch_limit"], 0)

    def test_chain_feed_stops_at_batch_limit(self):
        """batch_limit=2 且已 done 2 个 → 收束，不再续喂。"""
        ctx = self._ctx()
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page,"
            " pages_crawled, shops_found, exhausted, last_crawled_at)"
            " VALUES ('女装', '女装', 1, 0, 0, 0, '2026-08-08 10:00:00')")
        self.db.conn.commit()
        item = _cat_payload("女装", "女装", batch_limit=2, batch_id=3)
        # 批次已有 2 个 done（其他类目页）
        for i in range(2):
            _mark_done(self.db, _insert_item(
                self.db, _cat_payload(f"其他{i}", f"其他{i}", 2), batch_id=3))
        result = ok_result({
            "shops": [{"domain": "shop1.1688.com", "name": "店1",
                       "url": "https://shop1.1688.com"}],
            "has_more": True,
        })
        self.task._on_category_success(ctx, item, result)

        items = _pending_items(self.db)
        # 当前 item 也被认领了，不在此列；收束 → 无续喂
        self.assertEqual(len(items), 0)

    def test_chain_feed_continues_below_batch_limit(self):
        """batch_limit=5 且已 done 2 个 → 未到上限，继续续喂。"""
        ctx = self._ctx()
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page,"
            " pages_crawled, shops_found, exhausted, last_crawled_at)"
            " VALUES ('女装', '女装', 1, 0, 0, 0, '2026-08-08 10:00:00')")
        self.db.conn.commit()
        item = _cat_payload("女装", "女装", batch_limit=5, batch_id=3)
        for i in range(2):
            _mark_done(self.db, _insert_item(
                self.db, _cat_payload(f"其他{i}", f"其他{i}", 5), batch_id=3))
        result = ok_result({
            "shops": [{"domain": "shop1.1688.com", "name": "店1",
                       "url": "https://shop1.1688.com"}],
            "has_more": True,
        })
        self.task._on_category_success(ctx, item, result)

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], 3)

    # ---- refill 继承 + 收束 ----

    def test_refill_inherits_batch_and_respects_limit(self):
        """refill 补插继承 batch_id；批次已收束时不补插。"""
        ctx = self._ctx()
        item = _cat_payload("女装", "女装", batch_limit=1, batch_id=3)
        _mark_done(self.db, _insert_item(
            self.db, _cat_payload("其他", "其他", 1), batch_id=3))
        # 已 done 1 个 == batch_limit → 收束，refill 不补插
        self.task.refill_item(ctx, item)
        self.assertEqual(len(_pending_items(self.db)), 0)

        # batch_limit=3，未达上限 → 补插且继承 batch_id
        item2 = _cat_payload("男装", "男装", batch_limit=3, batch_id=4)
        self.task.refill_item(ctx, item2)
        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], 4)

    # ---- daemon 自喂路径零变化 ----

    def test_self_feed_path_no_batch_no_limit(self):
        """batch_id NULL 的 daemon 自喂：续喂 item batch_id 仍为 NULL，
        payload 不含 batch_limit（现状行为逐字不变）。"""
        ctx = self._ctx()
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page,"
            " pages_crawled, shops_found, exhausted, last_crawled_at)"
            " VALUES ('女装', '女装', 1, 0, 0, 0, '2026-08-08 10:00:00')")
        self.db.conn.commit()
        item = _cat_payload("女装", "女装")  # 无 batch_limit
        result = ok_result({
            "shops": [{"domain": "shop1.1688.com", "name": "店1",
                       "url": "https://shop1.1688.com"}],
            "has_more": True,
        })
        self.task._on_category_success(ctx, item, result)

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        _id, bid, payload = items[0]
        self.assertIsNone(bid)
        self.assertNotIn("batch_limit", payload)


class MicShopBatchInheritTest(unittest.TestCase):
    """madeinchina shop：discover/续喂/refill 继承 batch_id（与 1688 同构）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = MadeInChinaShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_mic_chain_feed_inherits_batch_id(self):
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page,"
            " pages_crawled, shops_found, exhausted, last_crawled_at)"
            " VALUES ('wujingj', '五金工具', 1, 0, 0, 0,"
            " '2026-08-08 10:00:00')")
        self.db.conn.commit()
        item = _cat_payload("wujingj", "五金工具", batch_limit=4, batch_id=8)
        result = ok_result({
            "shops": [{"domain": "cnshop.cn.made-in-china.com", "name": "店1",
                       "url": "https://cnshop.cn.made-in-china.com"}],
            "has_more": True,
        })
        self.task._on_category_success(ctx, item, result)

        items = _pending_items(self.db, queue=MIC_QUEUE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], 8)
        self.assertEqual(items[0][2]["batch_limit"], 4)

    def test_mic_chain_feed_stops_at_limit(self):
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page,"
            " pages_crawled, shops_found, exhausted, last_crawled_at)"
            " VALUES ('wujingj', '五金工具', 1, 0, 0, 0,"
            " '2026-08-08 10:00:00')")
        self.db.conn.commit()
        item = _cat_payload("wujingj", "五金工具", batch_limit=1, batch_id=8)
        _mark_done(self.db, _insert_item(
            self.db, _cat_payload("其他", "其他", 1), batch_id=8,
            queue=MIC_QUEUE, site=MIC_SITE))
        result = ok_result({
            "shops": [{"domain": "cnshop.cn.made-in-china.com", "name": "店1",
                       "url": "https://cnshop.cn.made-in-china.com"}],
            "has_more": True,
        })
        self.task._on_category_success(ctx, item, result)

        items = _pending_items(self.db, queue=MIC_QUEUE)
        self.assertEqual(len(items), 0)


if __name__ == "__main__":
    unittest.main()
