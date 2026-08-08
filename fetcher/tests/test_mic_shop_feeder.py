# -*- coding: utf-8 -*-
"""P3 Step 4.1: mic shop feeder 任务拆分（work_items 驱动）测试。

TDD 覆盖：链式续喂、ZERO_NEW_LIMIT 保护、失败补插、discover 产出、
幂等播种、CLI acquire、page_no 运行时读、refill_item 基类默认空。
全 mock，不起浏览器/网络。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fetcher import RunConfig, Session, ShopDB, WorkerContext
from fetcher.control.task import Task
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.madeinchina.shop import (
    ZERO_NEW_LIMIT,
    MadeInChinaShopTask,
    build_market_url,
    fetch_market_categories,
)
from fetcher.sites.madeinchina.features import HOMEPAGE, MARKET_DIR

from tests.test_control_loop import FakePage

QUEUE = "crawl_mic_shop"
SITE = "madeinchina"


# ---- helpers ----

def ok_result(data=None):
    return ActionResult(Outcome.OK, "", data or {})


def make_ctx(page=None, db=None):
    """构造 WorkerContext（带 session + db）。"""
    if page is None:
        page = FakePage()
    ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
    ctx.session = Session(page=page)
    if db is not None:
        from fetcher import IdentityStore
        ctx.store = IdentityStore(db)
    ctx.state["task"] = {"stats": MadeInChinaShopTask().make_stats()}
    return ctx


def _insert_work_item(db: ShopDB, payload: dict, queue=QUEUE,
                      site=SITE) -> int:
    """直接向 work_items 插 pending 行，返回 id。"""
    cur = db.conn.execute(
        "INSERT INTO work_items (queue, site, payload_json, created_at)"
        " VALUES (?, ?, ?, datetime('now', 'localtime'))",
        (queue, site, json.dumps(payload, ensure_ascii=False)))
    db.conn.commit()
    return cur.lastrowid


def _cat_payload(keyword="bxgyxg", name="不锈钢异型管", fmt="x2"):
    return {"kind": "category", "keyword": keyword, "name": name, "fmt": fmt}


def _discover_payload():
    return {"kind": "discover"}


def _pending_items(db, queue=QUEUE):
    """返回 queue 的 pending 工作项列表。"""
    rows = db.conn.execute(
        "SELECT id, payload_json FROM work_items WHERE queue=? "
        "AND status='pending' ORDER BY id", (queue,)).fetchall()
    return [(r["id"], json.loads(r["payload_json"])) for r in rows]


class MICShopPage(FakePage):
    """madeinchina market 分页页假页面。"""

    def __init__(self, shops=None, has_next=False, url=None):
        super().__init__()
        self.url = url or build_market_url("bxgyxg", 1)
        self._shops = shops or []
        self._next = has_next
        self.goto_calls = []
        self._exceptions = []

    def evaluate(self, js):
        if "location.pathname" in js:
            return {"shops": self._shops, "next": self._next,
                    "found": str(len(self._shops))}
        return ""  # category extraction JS returns empty

    def goto(self, url, **kw):
        self.goto_calls.append((url, kw))
        self.url = url


# ---- 1. 链式续喂 ----

class ChainFeedTest(unittest.TestCase):
    """category item on_success → advance + INSERT 下一页 item。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "c.db")
        self.task = MadeInChinaShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_chain_feed_inserts_next_page_item(self):
        """有新增店铺 → category_progress next_page+1 + 新 work_item。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
        result = ok_result({
            "shops": [{"domain": "newshop.cn.made-in-china.com",
                       "name": "新店"}],
            "has_more": True,
        })

        count = self.task.on_success(ctx, item, result)
        self.assertEqual(count, 1)

        # 页码前进
        prog = self.db.get_category_progress("bxgyxg")
        self.assertIsNotNone(prog)
        self.assertEqual(prog["next_page"], 2)
        self.assertEqual(prog["pages_crawled"], 1)

        # 新 work_item 插入（同 payload，attempts=0）
        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], _cat_payload("bxgyxg", "不锈钢异型管", "x2"))

    def test_chain_feed_skips_when_exhausted(self):
        """空页 → mark_category_exhausted → 不插下一页 item。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
        result = ok_result({"shops": [], "has_more": False})

        self.task.on_success(ctx, item, result)

        # exhausted
        self.assertIn("bxgyxg", self.db.get_exhausted_keywords())
        # 无新 work_item
        self.assertEqual(len(_pending_items(self.db)), 0)


# ---- 2. ZERO_NEW_LIMIT 保护 ----

class ZeroNewLimitTest(unittest.TestCase):
    """连续 N 页零新增 → mark_category_exhausted + 不插下一页。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "z.db")
        self.task = MadeInChinaShopTask()
        # 预插一个重复店铺
        self.db.upsert_shops([
            {"domain": "dup.cn.made-in-china.com", "name": "重复店"}])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_zero_new_exhausts_after_limit(self):
        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        dup_result = ok_result({
            "shops": [{"domain": "dup.cn.made-in-china.com", "name": "重复店"}],
            "has_more": True,
        })

        # 前 ZERO_NEW_LIMIT-1 页：页码前进，不 exhausted
        for i in range(1, ZERO_NEW_LIMIT):
            item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
            self.task.on_success(ctx, item, dup_result)
            self.assertNotIn("bxgyxg", self.db.get_exhausted_keywords())

        # 第 ZERO_NEW_LIMIT 页零新增：标 exhausted
        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
        self.task.on_success(ctx, item, dup_result)
        self.assertIn("bxgyxg", self.db.get_exhausted_keywords())

    def test_zero_new_resets_after_fresh(self):
        """零新增后出现新店：计数清零不误杀。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        dup_result = ok_result({
            "shops": [{"domain": "dup.cn.made-in-china.com", "name": "重复店"}],
            "has_more": True,
        })
        fresh_result = ok_result({
            "shops": [{"domain": "fresh.cn.made-in-china.com", "name": "新店"}],
            "has_more": True,
        })

        item = _cat_payload("wujingj", "五金工具", "x2")
        # 1 页零新增 → 1 页有新增（清计数）→ 再 1 页零新增：不应 exhausted
        self.task.on_success(ctx, item, dup_result)
        self.task.on_success(ctx, item, fresh_result)
        self.task.on_success(ctx, item, dup_result)
        self.assertNotIn("wujingj", self.db.get_exhausted_keywords())

    def test_zero_new_no_chain_feed_when_exhausted(self):
        """ZERO_NEW_LIMIT 耗尽后不插下一页 item。

        前 ZERO_NEW_LIMIT-1 次链式续喂产 work_item，最后一次不产。
        """
        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        dup_result = ok_result({
            "shops": [{"domain": "dup.cn.made-in-china.com", "name": "重复店"}],
            "has_more": True,
        })

        for _ in range(ZERO_NEW_LIMIT):
            self.task.on_success(ctx, _cat_payload(), dup_result)

        # 第 1 次非 exhausted 产 1 条链式续喂；第 2 次 exhausted 不产
        # 总共 1 条 pending
        self.assertEqual(len(_pending_items(self.db)), 1)


# ---- 3. 失败补插 ----

class RefillItemTest(unittest.TestCase):
    """category item attempts 耗尽 → 同 payload 新 item。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "r.db")
        self.task = MadeInChinaShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_refill_inserts_replacement_category_item(self):
        """category 失败 → 插入同 payload 新 item（attempts=0）。"""
        ctx = make_ctx(db=self.db)
        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
        ctx.state["item"] = item

        self.task.refill_item(ctx, item)

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], item)
        # attempts=0（新行默认）
        row = self.db.conn.execute(
            "SELECT attempts FROM work_items WHERE id=?",
            (items[0][0],)).fetchone()
        self.assertEqual(row["attempts"], 0)

    def test_refill_discover_also_replenishes(self):
        """discover 失败也补插一次（幂等由'无同 keyword pending item'保证）。"""
        ctx = make_ctx(db=self.db)
        item = _discover_payload()
        ctx.state["item"] = item

        self.task.refill_item(ctx, item)

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], _discover_payload())


# ---- 4. discover 产出 ----

class DiscoverOutputTest(unittest.TestCase):
    """discover on_success → 提取类目 → 新类目逐条 INSERT category item。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "d.db")
        self.task = MadeInChinaShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _mock_categories(self, page, cats_by_url: dict):
        """Mock fetch_market_categories 按 URL 返回类目。"""
        orig = fetch_market_categories

        def mock_fetch(page_obj, url):
            if url in cats_by_url:
                return cats_by_url[url]
            return orig(page_obj, url)

        return mock_fetch

    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
    def test_discover_inserts_new_categories(self, mock_fetch):
        """新类目（不在 category_progress、无 pending item）逐条 INSERT。"""
        mock_fetch.side_effect = lambda page, url: {
            HOMEPAGE: [{"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"}],
            MARKET_DIR: [
                {"slug": "jgdbj", "name": "激光打标机", "fmt": "plain"},
                {"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"},  # dup
            ],
        }.get(url, [])

        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        item = _discover_payload()
        result = ok_result({"discover": True})

        count = self.task.on_success(ctx, item, result)
        # discover 不计入页数
        self.assertEqual(count, 0)

        items = _pending_items(self.db)
        self.assertEqual(len(items), 2)  # bxgyxg + jgdbj（slug 去重）
        payloads = [p for _, p in items]
        self.assertIn({"kind": "category", "keyword": "bxgyxg",
                       "name": "不锈钢异型管", "fmt": "x2"}, payloads)
        self.assertIn({"kind": "category", "keyword": "jgdbj",
                       "name": "激光打标机", "fmt": "plain"}, payloads)

    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
    def test_discover_skips_exhausted_categories(self, mock_fetch):
        """已在 category_progress 且 exhausted 的类目不插。"""
        # 先标记 bxgyxg 为 exhausted
        self.db.mark_category_exhausted("bxgyxg", "不锈钢异型管")

        mock_fetch.side_effect = lambda page, url: {
            HOMEPAGE: [{"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"},
                       {"slug": "wujingj", "name": "五金工具", "fmt": "x2"}],
        }.get(url, [])

        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        self.task.on_success(ctx, _discover_payload(), ok_result({"discover": True}))

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)  # 只有 wujingj
        self.assertEqual(items[0][1]["keyword"], "wujingj")

    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
    def test_discover_skips_existing_pending_category(self, mock_fetch):
        """已有同 keyword pending category item 时跳过不重复插。"""
        _insert_work_item(self.db, _cat_payload("bxgyxg", "不锈钢异型管", "x2"))

        mock_fetch.side_effect = lambda page, url: {
            HOMEPAGE: [{"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"},
                       {"slug": "wujingj", "name": "五金工具", "fmt": "x2"}],
        }.get(url, [])

        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        self.task.on_success(ctx, _discover_payload(), ok_result({"discover": True}))

        items = _pending_items(self.db)
        self.assertEqual(len(items), 2)  # 原 bxgyxg + 新 wujingj
        keywords = [p["keyword"] for _, p in items if p.get("keyword")]
        self.assertEqual(sorted(keywords), ["bxgyxg", "wujingj"])

    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
    def test_discover_fallback_seeds(self, mock_fetch):
        """首页+导航页都提取失败 → 兜底种子类目。"""
        mock_fetch.return_value = []  # 全部失败

        ctx = make_ctx(db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()

        self.task.on_success(ctx, _discover_payload(), ok_result({"discover": True}))

        items = _pending_items(self.db)
        self.assertGreater(len(items), 0)
        # 至少包含种子类目
        keywords = {p["keyword"] for _, p in items if p.get("keyword")}
        self.assertIn("wujingj", keywords)


# ---- 5. 幂等播种 ----

class IdempotentSeedTest(unittest.TestCase):
    """重复 prepare/播种 → 不产生重复 pending item。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "s.db")
        self.db = ShopDB(self.db_path)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_double_prepare_no_duplicates(self):
        """两次 prepare 不产生重复 pending item。"""
        # 预置 category_progress（未采完拼音类目）
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('bxgyxg', '不锈钢异型管', 2)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "exhausted) VALUES ('xxylsb', '新型游乐设备', 1, 1)")
        self.db.conn.commit()
        self.db.close()

        cfg = RunConfig()
        cfg.db_path = self.db_path

        task1 = MadeInChinaShopTask()
        self.assertTrue(task1.prepare(cfg))
        # 第一次 prepare 后应有 pending items
        db_check = ShopDB(self.db_path)
        items1 = _pending_items(db_check)
        # 至少 bxgyxg（active）+ discover
        keywords1 = {p.get("keyword") for _, p in items1 if p.get("keyword")}
        self.assertIn("bxgyxg", keywords1)
        self.assertNotIn("xxylsb", keywords1)  # exhausted
        # 至少 1 条 discover
        discover_count = sum(1 for _, p in items1 if p.get("kind") == "discover")
        self.assertEqual(discover_count, 1)
        db_check.close()

        # 第二次 prepare：不产生重复
        task2 = MadeInChinaShopTask()
        self.assertTrue(task2.prepare(cfg))
        db_check2 = ShopDB(self.db_path)
        items2 = _pending_items(db_check2)
        self.assertEqual(len(items2), len(items1))  # 无新重复
        db_check2.close()


# ---- 6. CLI acquire ----

class CliAcquireTest(unittest.TestCase):
    """claim_next_eligible(["crawl_mic_shop"]) 认领返回 payload；无货 None。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "a.db")
        self.task = MadeInChinaShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_acquire_returns_payload(self):
        _insert_work_item(self.db, _cat_payload("bxgyxg", "不锈钢异型管", "x2"))
        ctx = make_ctx(db=self.db)
        ctx.wid = 1

        item = self.task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "category")
        self.assertEqual(item["keyword"], "bxgyxg")
        self.assertEqual(item["name"], "不锈钢异型管")
        self.assertEqual(item["fmt"], "x2")
        self.assertIn("id", item)  # work_item id 带在 payload 里

    def test_acquire_returns_none_when_empty(self):
        ctx = make_ctx(db=self.db)
        ctx.wid = 1
        self.assertIsNone(self.task.acquire_item(ctx))

    def test_acquire_returns_discover_payload(self):
        _insert_work_item(self.db, _discover_payload())
        ctx = make_ctx(db=self.db)
        ctx.wid = 1

        item = self.task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "discover")


# ---- 7. page_no 运行时读 ----

class PageNoRuntimeTest(unittest.TestCase):
    """fetch 时从 category_progress 读 next_page。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "p.db")
        self.task = MadeInChinaShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    def test_fetch_reads_next_page_from_db(self, _r, _s):
        """category_progress.next_page=3 → fetch 第 3 页。"""
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "pages_crawled) VALUES ('bxgyxg', '不锈钢异型管', 3, 2)")
        self.db.conn.commit()

        page = MICShopPage(
            shops=[{"domain": "shop1.cn.made-in-china.com", "name": "店1"}],
            has_next=False)
        ctx = make_ctx(page=page, db=self.db)
        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)

        # 验证 fetch 了第 3 页
        url, kw = page.goto_calls[0]
        self.assertEqual(url, build_market_url("bxgyxg", 3))
        # referer 是第 2 页
        self.assertEqual(kw.get("referer"),
                         build_market_url("bxgyxg", 2))

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    def test_fetch_defaults_to_page_1_when_no_progress(self, _r, _s):
        """无 category_progress → page_no=1。"""
        page = MICShopPage(has_next=True)
        ctx = make_ctx(page=page, db=self.db)
        item = _cat_payload("newcat", "新类目", "x2")

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)
        url, kw = page.goto_calls[0]
        self.assertEqual(url, build_market_url("newcat", 1))
        self.assertEqual(kw.get("referer"), HOMEPAGE)

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    def test_fetch_discover_returns_success_without_request(self, _r, _s):
        """discover item：fetch 不抓页面，返回 discover 标记。"""
        page = FakePage()
        ctx = make_ctx(page=page, db=self.db)
        item = _discover_payload()

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)
        self.assertTrue(result.data.get("discover"))
        # 不发网络请求
        self.assertEqual(len(getattr(page, "goto_calls", [])), 0)


# ---- 8. refill_item 基类默认空 ----

class BaseRefillItemDefaultTest(unittest.TestCase):
    """Task 基类 refill_item 默认空实现（contact 等不补插）。"""

    def test_base_refill_item_is_noop(self):
        task = Task()
        ctx = make_ctx()
        item = {"kind": "category", "keyword": "test", "name": "test", "fmt": "x2"}
        # 不应抛异常
        task.refill_item(ctx, item)


if __name__ == "__main__":
    unittest.main()
