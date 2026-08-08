# -*- coding: utf-8 -*-
"""P3 Step 5.1: 1688 shop/company feeder 任务拆分（work_items 驱动）测试。

TDD 覆盖：链式续喂、discover 产出（含 mtop 握手）、company: 前缀隔离、
失败补插、幂等播种、CLI acquire、validate discover 放行。
全 mock，不起浏览器/网络。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fetcher import RunConfig, Session, ShopDB, WorkerContext
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.alibaba1688.shop import (
    Alibaba1688ShopTask,
    build_search_url,
    fetch_homepage_categories,
    SEED_CATEGORIES,
)
from fetcher.sites.alibaba1688.company import (
    Alibaba1688CompanyTask,
    PROGRESS_PREFIX,
    SEED_KEYWORDS,
)

from tests.test_control_loop import FakePage

SHOP_QUEUE = "crawl_1688_shop"
COMPANY_QUEUE = "crawl_1688_company"
SITE = "1688"


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
    return ctx


def _insert_work_item(db: ShopDB, payload: dict, queue=SHOP_QUEUE) -> int:
    """直接向 work_items 插 pending 行，返回 id。"""
    cur = db.conn.execute(
        "INSERT INTO work_items (queue, site, payload_json, created_at)"
        " VALUES (?, ?, ?, datetime('now', 'localtime'))",
        (queue, SITE, json.dumps(payload, ensure_ascii=False)))
    db.conn.commit()
    return cur.lastrowid


def _cat_payload(keyword="女装", name="女装"):
    return {"kind": "category", "keyword": keyword, "name": name}


def _company_cat_payload(keyword="company:女装", name="女装"):
    return {"kind": "category", "keyword": keyword, "name": name}


def _discover_payload():
    return {"kind": "discover"}


def _pending_items(db, queue=SHOP_QUEUE):
    """返回 queue 的 pending 工作项列表。"""
    rows = db.conn.execute(
        "SELECT id, payload_json FROM work_items WHERE queue=? "
        "AND status='pending' ORDER BY id", (queue,)).fetchall()
    return [(r["id"], json.loads(r["payload_json"])) for r in rows]


def _pending_kind_count(db, kind, queue=SHOP_QUEUE, keyword=None):
    """统计特定 kind 的 pending 数量。"""
    if keyword is not None:
        return db.conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE queue=?"
            " AND status='pending'"
            " AND json_extract(payload_json, '$.kind')=?"
            " AND json_extract(payload_json, '$.keyword')=?",
            (queue, kind, keyword)).fetchone()[0]
    return db.conn.execute(
        "SELECT COUNT(*) FROM work_items WHERE queue=?"
        " AND status='pending'"
        " AND json_extract(payload_json, '$.kind')=?",
        (queue, kind)).fetchone()[0]


class Shop1688Page(FakePage):
    """1688 搜索页假页面（shop fetch 用）。"""

    def __init__(self, shops=None, has_more=False, url=None):
        super().__init__()
        self.url = url or build_search_url("女装", 1)
        self._shops = shops or []
        self._has_more = has_more
        self.goto_calls = []
        self._evaluate_js_calls = []

    def evaluate(self, js):
        self._evaluate_js_calls.append(js[:80])
        if "window.data" in js and "offerV2" in js:
            items = []
            for s in self._shops:
                domain = s.get("domain", "")
                items.append({
                    "shopUrl": f"https://{domain}" if domain else "",
                    "name": s.get("name", ""),
                    "loginId": domain.split(".")[0] if domain else "",
                })
            return {
                "hasMore": "true" if self._has_more else "false",
                "found": str(len(items)),
                "items": items,
            }
        return ""

    def goto(self, url, **kw):
        self.goto_calls.append((url, kw))
        self.url = url


class Company1688Page(FakePage):
    """1688 黄页假页面（company fetch 用）。"""

    def __init__(self, shops=None, has_more=False, cards_count=None, url=None):
        super().__init__()
        self.url = url or "https://s.1688.com/company/company_search.htm"
        self._shops = shops or []
        self._has_more = has_more
        self._cards_count = cards_count if cards_count is not None else len(shops or [])
        self.goto_calls = []
        self._evaluate_js_calls = []

    def evaluate(self, js):
        self._evaluate_js_calls.append(js[:80])
        # _JS_CARDS_READY: single expression, no "SKIP" / "const"
        if "length > 0" in js and "SKIP" not in js:
            return self._cards_count > 0
        # _JS_EXTRACT_COMPANIES: contains "SKIP" declaration + querySelectorAll
        if "SKIP" in js:
            items = [{"domain": s.get("domain", ""), "name": s.get("name", "")}
                     for s in self._shops]
            return {"items": items, "hasMore": self._has_more,
                    "cards": self._cards_count}
        return ""

    def goto(self, url, **kw):
        self.goto_calls.append((url, kw))
        self.url = url


# =====================================================================
# 1. 链式续喂（1688 shop）
# =====================================================================

class ChainFeedShopTest(unittest.TestCase):
    """category on_success → advance + INSERT 下一页 item 或 exhausted。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "c.db")
        self.task = Alibaba1688ShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_chain_feed_inserts_next_page_item(self):
        """有新增店铺 + hasMore → advance + 新 work_item。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        item = _cat_payload("女装", "女装")
        result = ok_result({
            "shops": [{"domain": "newshop.1688.com", "name": "新店", "url": "https://newshop.1688.com"}],
            "has_more": True,
        })

        count = self.task.on_success(ctx, item, result)
        self.assertEqual(count, 1)

        # 页码前进
        prog = self.db.get_category_progress("女装")
        self.assertIsNotNone(prog)
        self.assertEqual(prog["next_page"], 2)
        self.assertEqual(prog["pages_crawled"], 1)

        # 新 work_item 插入（同 payload，attempts=0）
        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], _cat_payload("女装", "女装"))

    def test_chain_feed_exhausted_when_no_shops(self):
        """空页 → mark_category_exhausted → 不插下一页 item。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        item = _cat_payload("女装", "女装")
        result = ok_result({"shops": [], "has_more": False})

        self.task.on_success(ctx, item, result)

        # exhausted
        self.assertIn("女装", self.db.get_exhausted_keywords())
        # 无新 work_item
        self.assertEqual(len(_pending_items(self.db)), 0)

    def test_chain_feed_exhausted_when_no_has_more(self):
        """hasMore=false → mark_category_exhausted → 不插下一页 item。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        item = _cat_payload("女装", "女装")
        result = ok_result({
            "shops": [{"domain": "shop1.1688.com", "name": "店1", "url": "https://shop1.1688.com"}],
            "has_more": False,
        })

        self.task.on_success(ctx, item, result)

        self.assertIn("女装", self.db.get_exhausted_keywords())
        self.assertEqual(len(_pending_items(self.db)), 0)

    def test_chain_feed_continues_when_has_more_and_shops(self):
        """有店铺 + hasMore=true → 不标记 exhausted，链式续喂。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        item = _cat_payload("女装", "女装")
        result = ok_result({
            "shops": [{"domain": "shop1.1688.com", "name": "店1", "url": "https://shop1.1688.com"}],
            "has_more": True,
        })

        self.task.on_success(ctx, item, result)

        self.assertNotIn("女装", self.db.get_exhausted_keywords())
        self.assertEqual(len(_pending_items(self.db)), 1)  # 链式续喂 1 条


# =====================================================================
# 2. 链式续喂（1688 company）
# =====================================================================

class ChainFeedCompanyTest(unittest.TestCase):
    """company category on_success → advance + INSERT 下一页 item
    （使用 company: 前缀进度键）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "cc.db")
        self.task = Alibaba1688CompanyTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_company_chain_feed_inserts_next_page(self):
        """有新增店铺 + hasMore → advance（company: 前缀）+ 新 work_item。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        item = _company_cat_payload("company:女装", "女装")
        result = ok_result({
            "shops": [{"domain": "newshop.1688.com", "name": "新店", "url": "https://newshop.1688.com"}],
            "has_more": True,
        })

        count = self.task.on_success(ctx, item, result)
        self.assertEqual(count, 1)

        # 页码前进（company: 前缀进度键）
        prog = self.db.get_category_progress("company:女装")
        self.assertIsNotNone(prog)
        self.assertEqual(prog["next_page"], 2)

        # 新 work_item（crawl_1688_company 队列）
        items = _pending_items(self.db, queue=COMPANY_QUEUE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], _company_cat_payload("company:女装", "女装"))

    def test_company_chain_feed_exhausted_when_empty(self):
        """空页 → 标记 exhausted（company: 前缀进度键）→ 不插。"""
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        item = _company_cat_payload("company:女装", "女装")
        result = ok_result({"shops": [], "has_more": False})

        self.task.on_success(ctx, item, result)

        self.assertIn("company:女装", self.db.get_exhausted_keywords())
        self.assertEqual(len(_pending_items(self.db, queue=COMPANY_QUEUE)), 0)


# =====================================================================
# 3. discover 产出（1688 shop）——含 mtop 握手
# =====================================================================

class DiscoverShopTest(unittest.TestCase):
    """discover on_success → 首页类目提取 + mtop 握手 → 新类目逐条
    INSERT category item。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "d.db")
        self.task = Alibaba1688ShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
           return_value=True)
    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
    def test_discover_inserts_new_categories(self, mock_fetch, _mock_mtop):
        """新类目逐条 INSERT category item。"""
        mock_fetch.return_value = [
            {"keyword": "女装", "name": "女装"},
            {"keyword": "男装", "name": "男装"},
            {"keyword": "女装", "name": "女装"},  # dup keyword
        ]

        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        item = _discover_payload()
        result = ok_result({"discover": True})

        count = self.task.on_success(ctx, item, result)
        # discover 不计入页数
        self.assertEqual(count, 0)

        items = _pending_items(self.db)
        # 2 个唯一 keyword（女装 + 男装）
        self.assertEqual(len(items), 2)
        keywords = {p["keyword"] for _, p in items}
        self.assertEqual(keywords, {"女装", "男装"})

    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
           return_value=True)
    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
    def test_discover_skips_exhausted_categories(self, mock_fetch, _mock_mtop):
        """已在 category_progress 且 exhausted 的类目不插。"""
        self.db.mark_category_exhausted("女装", "女装")

        mock_fetch.return_value = [
            {"keyword": "女装", "name": "女装"},  # exhausted → skip
            {"keyword": "男装", "name": "男装"},
        ]

        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        self.task.on_success(ctx, _discover_payload(),
                             ok_result({"discover": True}))

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)  # 只有男装
        self.assertEqual(items[0][1]["keyword"], "男装")

    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
           return_value=True)
    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
    def test_discover_skips_existing_pending_category(self, mock_fetch,
                                                       _mock_mtop):
        """已有同 keyword pending category item 时跳过不重复插。"""
        _insert_work_item(self.db, _cat_payload("女装", "女装"))

        mock_fetch.return_value = [
            {"keyword": "女装", "name": "女装"},
            {"keyword": "男装", "name": "男装"},
        ]

        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        self.task.on_success(ctx, _discover_payload(),
                             ok_result({"discover": True}))

        items = _pending_items(self.db)
        self.assertEqual(len(items), 2)  # 原女装 + 新男装
        keywords = {p["keyword"] for _, p in items if p.get("keyword")}
        self.assertEqual(keywords, {"女装", "男装"})

    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
           return_value=True)
    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
    def test_discover_fallback_seeds(self, mock_fetch, _mock_mtop):
        """首页类目提取失败 → 兜底种子类目。"""
        mock_fetch.return_value = []

        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        self.task.on_success(ctx, _discover_payload(),
                             ok_result({"discover": True}))

        items = _pending_items(self.db)
        self.assertGreater(len(items), 0)
        keywords = {p["keyword"] for _, p in items if p.get("keyword")}
        # SEED_CATEGORIES 第一项
        self.assertIn(SEED_CATEGORIES[0][0], keywords)

    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
           return_value=True)
    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
    def test_discover_calls_mtop_handshake(self, mock_fetch, mock_mtop):
        """discover 执行时调用 ensure_mtop_token。"""
        mock_fetch.return_value = [
            {"keyword": "女装", "name": "女装"},
        ]
        mock_mtop.return_value = True

        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        self.task.on_success(ctx, _discover_payload(),
                             ok_result({"discover": True}))

        mock_mtop.assert_called_once()


# =====================================================================
# 4. discover 产出（1688 company）
# =====================================================================

class DiscoverCompanyTest(unittest.TestCase):
    """company discover on_success → 提取类目 → company: 前缀 category item。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "dc.db")
        self.task = Alibaba1688CompanyTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    @patch("fetcher.sites.alibaba1688.company.ensure_mtop_token",
           return_value=True)
    @patch("fetcher.sites.alibaba1688.company.fetch_homepage_categories")
    def test_company_discover_inserts_prefixed_categories(self, mock_fetch,
                                                           _mock_mtop):
        """discover 产出带 company: 前缀 keyword 的 category item。"""
        mock_fetch.return_value = [
            {"keyword": "女装", "name": "女装"},
            {"keyword": "男装", "name": "男装"},
        ]

        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        item = _discover_payload()
        result = ok_result({"discover": True})

        self.task.on_success(ctx, item, result)

        items = _pending_items(self.db, queue=COMPANY_QUEUE)
        self.assertEqual(len(items), 2)
        keywords = {p["keyword"] for _, p in items}
        self.assertEqual(keywords, {"company:女装", "company:男装"})

    @patch("fetcher.sites.alibaba1688.company.ensure_mtop_token",
           return_value=True)
    @patch("fetcher.sites.alibaba1688.company.fetch_homepage_categories")
    def test_company_discover_skips_exhausted(self, mock_fetch, _mock_mtop):
        """company discover 跳过已 exhausted 的 company: 前缀进度键。"""
        self.db.mark_category_exhausted("company:女装", "女装")

        mock_fetch.return_value = [
            {"keyword": "女装", "name": "女装"},
            {"keyword": "男装", "name": "男装"},
        ]

        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        self.task.on_success(ctx, _discover_payload(),
                             ok_result({"discover": True}))

        items = _pending_items(self.db, queue=COMPANY_QUEUE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1]["keyword"], "company:男装")

    @patch("fetcher.sites.alibaba1688.company.ensure_mtop_token",
           return_value=True)
    @patch("fetcher.sites.alibaba1688.company.fetch_homepage_categories")
    def test_company_discover_fallback_seeds(self, mock_fetch, _mock_mtop):
        """company discover 失败 → 兜底种子关键词（company: 前缀）。"""
        mock_fetch.return_value = []

        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}

        self.task.on_success(ctx, _discover_payload(),
                             ok_result({"discover": True}))

        items = _pending_items(self.db, queue=COMPANY_QUEUE)
        self.assertGreater(len(items), 0)
        keywords = {p["keyword"] for _, p in items if p.get("keyword")}
        # SEED_KEYWORDS 第一项 → company:女装
        self.assertIn("company:" + SEED_KEYWORDS[0][0], keywords)


# =====================================================================
# 5. company: 前缀隔离
# =====================================================================

class PrefixIsolationTest(unittest.TestCase):
    """company 的 keyword 带 company: 前缀，进度/播种互不干扰。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "p.db")
        self.shop_task = Alibaba1688ShopTask()
        self.company_task = Alibaba1688CompanyTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_progress_keys_are_isolated(self):
        """同一 keyword（女装）在 shop 与 company 的进度记录互不干扰。"""
        # shop 侧：keyword="女装"
        self.db.advance_category_page("女装", "女装", shops_found=3)
        # company 侧：keyword="company:女装"
        self.db.advance_category_page("company:女装", "女装", shops_found=5)

        shop_prog = self.db.get_category_progress("女装")
        company_prog = self.db.get_category_progress("company:女装")

        self.assertEqual(shop_prog["pages_crawled"], 1)
        self.assertEqual(company_prog["pages_crawled"], 1)
        self.assertEqual(shop_prog["shops_found"], 3)
        self.assertEqual(company_prog["shops_found"], 5)

    def test_exhausted_keys_filtered_by_prefix(self):
        """iter_active_categories(prefix="company:") 只返回 company: 前缀行。"""
        # 插入混合行
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('女装', '女装', 2)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('company:女装', '女装', 2)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('男装', '男装', 1)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "exhausted) VALUES ('company:男装', '男装', 1, 1)")
        self.db.conn.commit()

        # 无前缀：返回所有未 exhausted
        all_cats = self.db.iter_active_categories()
        all_keywords = {c["keyword"] for c in all_cats}
        self.assertIn("女装", all_keywords)
        self.assertIn("company:女装", all_keywords)
        self.assertIn("男装", all_keywords)
        self.assertNotIn("company:男装", all_keywords)  # exhausted

        # company: 前缀：只返回 company: 开头且未 exhausted
        company_cats = self.db.iter_active_categories(prefix="company:")
        company_keywords = {c["keyword"] for c in company_cats}
        self.assertEqual(company_keywords, {"company:女装"})
        self.assertNotIn("女装", company_keywords)

    def test_company_prepare_seeds_only_prefixed(self):
        """company prepare 播种只产 company: 前缀 keyword 的 category item。"""
        # 预置混合 category_progress
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('女装', '女装', 2)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('company:女装', '女装', 2)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "exhausted) VALUES ('company:男装', '男装', 1, 1)")
        self.db.conn.commit()
        db_path = self.db.conn.execute("PRAGMA database_list").fetchone()[2]
        self.db.close()

        cfg = RunConfig()
        cfg.db_path = db_path
        task = Alibaba1688CompanyTask()
        self.assertTrue(task.prepare(cfg))

        db_check = ShopDB(db_path)
        items = _pending_items(db_check, queue=COMPANY_QUEUE)
        # company:女装（active）+ 1 discover
        keywords = {p.get("keyword") for _, p in items if p.get("keyword")}
        self.assertIn("company:女装", keywords)
        self.assertNotIn("女装", keywords)  # 不带前缀的不应出现
        self.assertNotIn("company:男装", keywords)  # exhausted
        # 应有 1 条 discover
        discover_count = sum(1 for _, p in items if p.get("kind") == "discover")
        self.assertEqual(discover_count, 1)
        db_check.close()


# =====================================================================
# 6. 失败补插
# =====================================================================

class RefillItemTest(unittest.TestCase):
    """category item attempts 耗尽 → 同 payload 新 item。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "r.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_shop_refill_category(self):
        """1688 shop category 失败 → 插入同 payload 新 item。"""
        task = Alibaba1688ShopTask()
        ctx = make_ctx(db=self.db)
        item = _cat_payload("女装", "女装")

        task.refill_item(ctx, item)

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], item)
        row = self.db.conn.execute(
            "SELECT attempts FROM work_items WHERE id=?",
            (items[0][0],)).fetchone()
        self.assertEqual(row["attempts"], 0)

    def test_shop_refill_discover(self):
        """1688 shop discover 失败也补插。"""
        task = Alibaba1688ShopTask()
        ctx = make_ctx(db=self.db)
        item = _discover_payload()

        task.refill_item(ctx, item)

        items = _pending_items(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], _discover_payload())

    def test_company_refill_category(self):
        """1688 company category 失败 → 同 payload（company: 前缀）。"""
        task = Alibaba1688CompanyTask()
        ctx = make_ctx(db=self.db)
        item = _company_cat_payload("company:女装", "女装")

        task.refill_item(ctx, item)

        items = _pending_items(self.db, queue=COMPANY_QUEUE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], item)

    def test_company_refill_discover(self):
        """1688 company discover 失败也补插。"""
        task = Alibaba1688CompanyTask()
        ctx = make_ctx(db=self.db)
        item = _discover_payload()

        task.refill_item(ctx, item)

        items = _pending_items(self.db, queue=COMPANY_QUEUE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], _discover_payload())


# =====================================================================
# 7. 幂等播种
# =====================================================================

class IdempotentSeedTest(unittest.TestCase):
    """重复 prepare/播种 → 不产生重复 pending item。"""

    def _setup_db(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "s.db")
        self.db = ShopDB(self.db_path)

    def _teardown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_shop_double_prepare_no_duplicates(self):
        """shop 两次 prepare 不产生重复 pending。"""
        self._setup_db()
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('女装', '女装', 2)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "exhausted) VALUES ('男装', '男装', 1, 1)")
        self.db.conn.commit()
        self.db.close()

        cfg = RunConfig()
        cfg.db_path = self.db_path

        task1 = Alibaba1688ShopTask()
        self.assertTrue(task1.prepare(cfg))
        db_check = ShopDB(self.db_path)
        items1 = _pending_items(db_check)
        keywords1 = {p.get("keyword") for _, p in items1 if p.get("keyword")}
        self.assertIn("女装", keywords1)
        self.assertNotIn("男装", keywords1)  # exhausted
        discover_count1 = sum(1 for _, p in items1 if p.get("kind") == "discover")
        self.assertEqual(discover_count1, 1)
        db_check.close()

        # 第二次 prepare 不产生重复
        task2 = Alibaba1688ShopTask()
        self.assertTrue(task2.prepare(cfg))
        db_check2 = ShopDB(self.db_path)
        items2 = _pending_items(db_check2)
        self.assertEqual(len(items2), len(items1))
        db_check2.close()
        self._teardown()

    def test_company_double_prepare_no_duplicates(self):
        """company 两次 prepare 不产生重复 pending。"""
        self._setup_db()
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('company:女装', '女装', 2)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "exhausted) VALUES ('company:男装', '男装', 1, 1)")
        self.db.conn.commit()
        self.db.close()

        cfg = RunConfig()
        cfg.db_path = self.db_path

        task1 = Alibaba1688CompanyTask()
        self.assertTrue(task1.prepare(cfg))
        db_check = ShopDB(self.db_path)
        items1 = _pending_items(db_check, queue=COMPANY_QUEUE)
        keywords1 = {p.get("keyword") for _, p in items1 if p.get("keyword")}
        self.assertIn("company:女装", keywords1)
        self.assertNotIn("company:男装", keywords1)
        db_check.close()

        task2 = Alibaba1688CompanyTask()
        self.assertTrue(task2.prepare(cfg))
        db_check2 = ShopDB(self.db_path)
        items2 = _pending_items(db_check2, queue=COMPANY_QUEUE)
        self.assertEqual(len(items2), len(items1))
        db_check2.close()
        self._teardown()


# =====================================================================
# 8. CLI acquire
# =====================================================================

class CliAcquireTest(unittest.TestCase):
    """claim_next_eligible(["crawl_1688_shop"/"crawl_1688_company"])
    认领返回 payload；无货 None。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "a.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_shop_acquire_returns_payload(self):
        _insert_work_item(self.db, _cat_payload("女装", "女装"))
        task = Alibaba1688ShopTask()
        ctx = make_ctx(db=self.db)
        ctx.wid = 1

        item = task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "category")
        self.assertEqual(item["keyword"], "女装")
        self.assertIn("id", item)

    def test_shop_acquire_returns_none_when_empty(self):
        task = Alibaba1688ShopTask()
        ctx = make_ctx(db=self.db)
        ctx.wid = 1
        self.assertIsNone(task.acquire_item(ctx))

    def test_shop_acquire_returns_discover(self):
        _insert_work_item(self.db, _discover_payload())
        task = Alibaba1688ShopTask()
        ctx = make_ctx(db=self.db)
        ctx.wid = 1

        item = task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "discover")

    def test_company_acquire_returns_payload(self):
        _insert_work_item(self.db, _company_cat_payload("company:女装", "女装"),
                          queue=COMPANY_QUEUE)
        task = Alibaba1688CompanyTask()
        ctx = make_ctx(db=self.db)
        ctx.wid = 1

        item = task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["keyword"], "company:女装")

    def test_company_acquire_returns_none_when_empty(self):
        task = Alibaba1688CompanyTask()
        ctx = make_ctx(db=self.db)
        ctx.wid = 1
        self.assertIsNone(task.acquire_item(ctx))


# =====================================================================
# 9. validate discover 放行（Step 4.1 C1 教训回归）
# =====================================================================

class ValidateDiscoverTest(unittest.TestCase):
    """discover 走完整 fetch → validate → on_success 三段式。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "v.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_shop_validate_discover_passes(self):
        """shop validate 放行 discover（检查 discover 键）。"""
        task = Alibaba1688ShopTask()
        ctx = make_ctx(db=self.db)

        # fetch → discover 标记
        result = task.fetch(ctx, _discover_payload())
        self.assertEqual(result.outcome, Outcome.OK)
        self.assertTrue(result.data.get("discover"))

        # validate → 放行
        self.assertTrue(task.validate(ctx, _discover_payload(), result))

    def test_shop_validate_category_checks_shops(self):
        """shop validate category 检查 shops 列表。"""
        task = Alibaba1688ShopTask()
        ctx = make_ctx(db=self.db)

        self.assertTrue(task.validate(ctx, _cat_payload(),
                                      ok_result({"shops": []})))
        self.assertFalse(task.validate(ctx, _cat_payload(),
                                       ok_result({"wrong_key": 1})))

    def test_company_validate_discover_passes(self):
        """company validate 放行 discover。"""
        task = Alibaba1688CompanyTask()
        ctx = make_ctx(db=self.db)

        result = task.fetch(ctx, _discover_payload())
        self.assertEqual(result.outcome, Outcome.OK)
        self.assertTrue(result.data.get("discover"))

        self.assertTrue(task.validate(ctx, _discover_payload(), result))

    def test_discover_full_pipeline_shop(self):
        """shop discover 三段式（回归 C1 教训）。"""
        task = Alibaba1688ShopTask()
        ctx = make_ctx(db=self.db)
        ctx.state["task"] = {"stats": task.make_stats()}

        with patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
                   return_value=True):
            with patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories",
                       return_value=[{"keyword": "女装", "name": "女装"}]):
                item = _discover_payload()
                # 1. fetch
                result = task.fetch(ctx, item)
                self.assertEqual(result.outcome, Outcome.OK)
                # 2. validate
                self.assertTrue(task.validate(ctx, item, result))
                # 3. on_success
                count = task.on_success(ctx, item, result)
                self.assertEqual(count, 0)
                items = _pending_items(self.db)
                self.assertGreaterEqual(len(items), 1)


# =====================================================================
# 10. shop fetch 读 next_page + mtop 检查
# =====================================================================

class ShopFetchTest(unittest.TestCase):
    """shop fetch 从 category_progress 读 next_page，mtop 检查。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "f.db")
        self.task = Alibaba1688ShopTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    @patch("fetcher.sites.alibaba1688.shop.has_mtop_token",
           return_value=True)
    def test_fetch_reads_next_page_from_db(self, _mtop, _r, _s):
        """category_progress.next_page=3 → fetch 第 3 页。"""
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "pages_crawled) VALUES ('女装', '女装', 3, 2)")
        self.db.conn.commit()

        page = Shop1688Page(
            shops=[{"domain": "shop1.1688.com", "name": "店1"}],
            has_more=False)
        ctx = make_ctx(page=page, db=self.db)
        item = _cat_payload("女装", "女装")

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)

        # 验证 fetch 了第 3 页
        url, kw = page.goto_calls[0]
        self.assertIn("beginPage=3", url)
        self.assertIn("keywords=", url)

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    @patch("fetcher.sites.alibaba1688.shop.has_mtop_token",
           return_value=True)
    def test_fetch_defaults_to_page_1(self, _mtop, _r, _s):
        """无 category_progress → page_no=1。"""
        page = Shop1688Page(has_more=True)
        ctx = make_ctx(page=page, db=self.db)
        item = _cat_payload("新类目", "新类目")

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)
        url, kw = page.goto_calls[0]
        self.assertIn("beginPage=1", url)

    @patch("fetcher.sites.alibaba1688.shop.has_mtop_token",
           return_value=False)
    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
           return_value=False)
    def test_fetch_blocked_when_no_mtop(self, _ensure, _has):
        """无 mtop 令牌 → fetch 返回 BLOCKED。"""
        page = FakePage()
        ctx = make_ctx(page=page, db=self.db)
        item = _cat_payload("女装", "女装")

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.BLOCKED)

    def test_fetch_discover_no_request(self):
        """discover item fetch 不发起网络请求。"""
        page = FakePage()
        ctx = make_ctx(page=page, db=self.db)
        item = _discover_payload()

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)
        self.assertTrue(result.data.get("discover"))


# =====================================================================
# 11. company fetch 读 next_page（company: 前缀）
# =====================================================================

class CompanyFetchTest(unittest.TestCase):
    """company fetch 用 company: 前缀读 category_progress。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "cf.db")
        self.task = Alibaba1688CompanyTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    @patch("fetcher.sites.alibaba1688.company.has_mtop_token",
           return_value=True)
    def test_company_fetch_uses_prefixed_progress(self, _mtop, _r, _s):
        """company fetch 从 company:女装 进度读 next_page。"""
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "pages_crawled) VALUES ('company:女装', '女装', 2, 1)")
        self.db.conn.commit()

        page = Company1688Page(
            shops=[{"domain": "shop1.1688.com", "name": "店1"}],
            has_more=False, cards_count=1)
        ctx = make_ctx(page=page, db=self.db)
        item = _company_cat_payload("company:女装", "女装")

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)
        url, kw = page.goto_calls[0]
        self.assertIn("beginPage=2", url)

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    @patch("fetcher.sites.alibaba1688.company.has_mtop_token",
           return_value=True)
    def test_company_fetch_defaults_to_page_1(self, _mtop, _r, _s):
        """无 category_progress → page_no=1。"""
        page = Company1688Page(has_more=True, cards_count=1)
        ctx = make_ctx(page=page, db=self.db)
        item = _company_cat_payload("company:新类目", "新类目")

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)
        url, kw = page.goto_calls[0]
        self.assertIn("beginPage=1", url)

    @patch("fetcher.sites.alibaba1688.company.has_mtop_token",
           return_value=False)
    @patch("fetcher.sites.alibaba1688.company.ensure_mtop_token",
           return_value=False)
    def test_company_fetch_blocked_no_mtop(self, _ensure, _has):
        """无 mtop → company fetch BLOCKED。"""
        page = FakePage()
        ctx = make_ctx(page=page, db=self.db)
        item = _company_cat_payload("company:女装", "女装")

        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.BLOCKED)


# =====================================================================
# 12. 类名兼容（确保 __init__.py 的 make_task 仍可用）
# =====================================================================

class ClassNameCompatibilityTest(unittest.TestCase):
    """重构后类名 Alibaba1688ShopTask / Alibaba1688CompanyTask，
    但 __init__.py 的 make_task 仍能实例化。"""

    def test_shop_task_instantiable(self):
        """通过 make_task("shop") 创建 shop task。"""
        from fetcher.sites.alibaba1688 import Alibaba1688Plugin
        plugin = Alibaba1688Plugin()
        task = plugin.make_task("shop")
        self.assertIsInstance(task, Alibaba1688ShopTask)

    def test_company_task_instantiable(self):
        """通过 make_task("company") 创建 company task。"""
        from fetcher.sites.alibaba1688 import Alibaba1688Plugin
        plugin = Alibaba1688Plugin()
        task = plugin.make_task("company")
        self.assertIsInstance(task, Alibaba1688CompanyTask)


if __name__ == "__main__":
    unittest.main()
