# -*- coding: utf-8 -*-
"""
P0 抓取类原子单元测试（stdlib unittest，无浏览器/代理/网络/Redis/SQLite）。

隔离手段：
- FakeShopDB / FakePage / FakePoolClient 内存假对象；
- unittest.mock.patch 替换 app.services.crawl.pages 的 scrape_contact /
  extract_shops / page_blocked / human_pause；
- FakeContext 覆盖 wait() 为即时返回（不真睡），停止用 threading.Event；
- for_each_shop 的 body 用本文件内注册的假原子（test_* 前缀），不依赖
  其他组的原子实现。
"""
from __future__ import annotations

import threading
import unittest
from unittest import mock

from app.services.crawl import pages as pg
from app.services.flow.base import Atom, AtomResult, Context
from app.services.flow.registry import register
from app.services.flow.atoms.claim_shops import ClaimShopsAtom
from app.services.flow.atoms.fetch_contact import FetchContactAtom
from app.services.flow.atoms.crawl_category import CrawlCategoryAtom
from app.services.flow.atoms.for_each_shop import ForEachShopAtom


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------

class FakeShopDB:
    def __init__(self, pending=None):
        self.pending = list(pending or [])
        self.claim_calls = []
        self.saved_contacts = []
        self.no_contact_marks = []
        self.failed_marks = []
        self.progress = {}       # keyword -> {"exhausted":0/1,"next_page":n}
        self.exhausted_marks = []
        self.runs = []
        self.advanced = []

    # claim_shops
    def claim_pending_shops(self, limit=1):
        self.claim_calls.append(limit)
        out = self.pending[:limit]
        self.pending = self.pending[limit:]
        return out

    def count_pending(self):
        return len(self.pending)

    # fetch_contact
    def save_contact(self, domain, contact, source_url=None, raw_text=None):
        self.saved_contacts.append(
            {"domain": domain, "contact": dict(contact),
             "source_url": source_url, "raw_text": raw_text})

    def mark_shop_no_contact(self, domain, bump_attempts=True):
        self.no_contact_marks.append(
            {"domain": domain, "bump_attempts": bump_attempts})

    def mark_shop_failed(self, domain):
        self.failed_marks.append(domain)

    # crawl_category
    def get_category_progress(self, keyword):
        return self.progress.get(keyword)

    def mark_category_exhausted(self, keyword, name=None):
        self.exhausted_marks.append(keyword)
        p = self.progress.setdefault(keyword, {"next_page": 1})
        p["exhausted"] = 1

    def start_run(self, category_name=None, category_keyword=None):
        self.runs.append({"name": category_name, "keyword": category_keyword})
        return len(self.runs)

    def finish_run(self, run_id, shops_found=0, shops_picked=0, note=None):
        self.runs[run_id - 1]["finished"] = True
        self.runs[run_id - 1]["note"] = note

    # 测试可注入的 upsert 返回值（默认全部为新店铺）
    upsert_return = None

    def upsert_shops(self, shops, run_id=None, category_keyword=None):
        if self.upsert_return is not None:
            return self.upsert_return
        return len(shops)

    def advance_category_page(self, keyword, name=None, shops_found=0):
        self.advanced.append(keyword)
        p = self.progress.setdefault(keyword, {"exhausted": 0})
        p["next_page"] = p.get("next_page", 1) + 1
        return p["next_page"]


class _FakeMouse:
    def __init__(self):
        self.wheels = []

    def wheel(self, x, y):
        self.wheels.append((x, y))


class FakePage:
    def __init__(self, goto_error=None):
        self.goto_calls = []
        self.goto_error = goto_error
        self.mouse = _FakeMouse()
        self.url = "https://example.test/"

    def goto(self, url, **kw):
        self.goto_calls.append({"url": url, **kw})
        if self.goto_error is not None:
            raise self.goto_error


class FakePoolClient:
    def __init__(self):
        self.reports = []

    def report(self, channel, **kw):
        self.reports.append(kw)


class FakeContext(Context):
    """wait() 即时返回并记录时长；stop 用外部 threading.Event 控制。"""

    def __init__(self, *, stop_event=None, **kw):
        super().__init__(stop_event=stop_event, **kw)
        self.waits = []

    def wait(self, seconds):
        self.waits.append(seconds)
        return self._stop_event.is_set()


# ---- for_each_shop body 用的假原子（本文件内注册，不依赖其他组）----

@register
class _TestOkAtom(Atom):
    name = "test_ok"
    title = "测试·恒成功"
    call_log = []

    def run(self, ctx, params):
        type(self).call_log.append("ok")
        ctx.vars["n_ok"] = ctx.vars.get("n_ok", 0) + 1
        return AtomResult(outcome="ok")


@register
class _TestFailAtom(Atom):
    name = "test_fail"
    title = "测试·恒失败"
    call_log = []

    def run(self, ctx, params):
        type(self).call_log.append("fail")
        return AtomResult(outcome="net_error", detail="模拟网络故障")


@register
class _TestClaimEmptyAtom(Atom):
    name = "test_claim_empty"
    title = "测试·认领枯竭"

    def run(self, ctx, params):
        ctx.vars["shops"] = []
        return AtomResult(outcome="empty", detail="没有待认领店铺")


@register
class _TestStopAfterAtom(Atom):
    name = "test_stop_after"
    title = "测试·第 N 次调用后触发停止"
    calls = 0
    stop_after = 0
    event = None

    def run(self, ctx, params):
        type(self).calls += 1
        if type(self).calls >= type(self).stop_after:
            type(self).event.set()
        return AtomResult(outcome="ok")


# ----------------------------------------------------------------------
# claim_shops
# ----------------------------------------------------------------------

class TestClaimShops(unittest.TestCase):
    def test_empty_list_outcome_empty(self):
        db = FakeShopDB(pending=[])
        ctx = Context(resources={"db": db})
        res = ClaimShopsAtom().run(ctx, {"n": 3})
        self.assertEqual(res.outcome, "empty")
        self.assertEqual(ctx.vars["shops"], [])
        self.assertEqual(db.claim_calls, [3])

    def test_claims_and_writes_vars(self):
        pending = [{"id": 1, "domain": "shop1.1688.com", "url": "https://shop1.1688.com"},
                   {"id": 2, "domain": "shop2.1688.com", "url": "https://shop2.1688.com"}]
        db = FakeShopDB(pending=pending)
        ctx = Context(resources={"db": db})
        res = ClaimShopsAtom().run(ctx, {"n": 1})
        self.assertEqual(res.outcome, "ok")
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(ctx.vars["shops"][0]["domain"], "shop1.1688.com")
        self.assertEqual(db.claim_calls, [1])

    def test_default_n_is_1(self):
        db = FakeShopDB(pending=[])
        ctx = Context(resources={"db": db})
        ClaimShopsAtom().run(ctx, {})
        self.assertEqual(db.claim_calls, [1])


# ----------------------------------------------------------------------
# fetch_contact
# ----------------------------------------------------------------------

SHOP = {"id": 7, "domain": "shop7.1688.com", "name": "测试商行",
        "url": "https://shop7.1688.com"}


class TestFetchContact(unittest.TestCase):
    def _ctx(self, db, pool=None):
        return Context(resources={
            "db": db, "page": FakePage(),
            "channel": {"id": 1}, "identity": "1.2.3.4",
            "pool_client": pool,
        }, vars={"shops": [SHOP]})

    def test_net_error(self):
        db = FakeShopDB()
        pool = FakePoolClient()
        with mock.patch.object(pg, "scrape_contact",
                               return_value={"_net_error": "net::ERR_TIMED_OUT"}):
            res = FetchContactAtom().run(self._ctx(db, pool), {})
        self.assertEqual(res.outcome, "net_error")
        self.assertIn("ERR_TIMED_OUT", res.detail)
        self.assertEqual([r["result"] for r in pool.reports], ["error"])
        self.assertEqual(db.saved_contacts, [])

    def test_blocked_flag(self):
        db = FakeShopDB()
        pool = FakePoolClient()
        info = {"contact_person": "张三", "phone": "123", "_raw": "raw",
                "_source_url": "u", "_blocked": "URL 命中风控特征 'punish'"}
        with mock.patch.object(pg, "scrape_contact", return_value=info):
            res = FetchContactAtom().run(self._ctx(db, pool), {})
        self.assertEqual(res.outcome, "blocked")
        self.assertIn("风控", res.detail)
        self.assertEqual([r["result"] for r in pool.reports], ["blocked"])
        self.assertEqual(db.saved_contacts, [])

    def test_none_result_maps_to_blocked(self):
        """scrape_contact 返回 None → 疑似风控（contact_fetch.py L284 语义）。"""
        db = FakeShopDB()
        pool = FakePoolClient()
        with mock.patch.object(pg, "scrape_contact", return_value=None):
            res = FetchContactAtom().run(self._ctx(db, pool), {})
        self.assertEqual(res.outcome, "blocked")
        self.assertEqual(res.detail, "页面加载失败（疑似风控拦截）")
        self.assertEqual([r["result"] for r in pool.reports], ["blocked"])

    def test_ok_with_phone(self):
        db = FakeShopDB()
        pool = FakePoolClient()
        info = {"contact_person": "李四", "gender": "男", "phone": "0571-1234567",
                "mobile": None, "fax": None, "address": "杭州",
                "_raw": "原始文本", "_source_url": "https://shop7.1688.com/page/contactinfo.htm",
                "_blocked": None}
        with mock.patch.object(pg, "scrape_contact", return_value=info) as m:
            res = FetchContactAtom().run(self._ctx(db, pool), {})
        self.assertEqual(res.outcome, "ok")
        self.assertEqual(res.data["contact_person"], "李四")
        self.assertEqual(res.data["phone"], "0571-1234567")
        self.assertEqual([r["result"] for r in pool.reports], ["ok"])
        self.assertEqual(pool.reports[0]["task_type"], "contact_fetch")
        self.assertEqual(pool.reports[0]["exit_ip"], "1.2.3.4")
        # 入库：内部字段已剥离，raw/source_url 透传
        self.assertEqual(len(db.saved_contacts), 1)
        saved = db.saved_contacts[0]
        self.assertEqual(saved["raw_text"], "原始文本")
        self.assertNotIn("_raw", saved["contact"])
        self.assertNotIn("_blocked", saved["contact"])
        self.assertEqual(db.no_contact_marks, [])
        # referer 来自 shop["url"]
        _, args, kwargs = m.mock_calls[0]
        self.assertEqual(args[1], "shop7.1688.com")
        self.assertEqual(kwargs.get("referer"), "https://shop7.1688.com")

    def test_empty_no_phone_marks_no_contact(self):
        db = FakeShopDB()
        pool = FakePoolClient()
        info = {"contact_person": None, "gender": None, "phone": None,
                "mobile": None, "fax": None, "address": "广州",
                "_raw": "raw", "_source_url": "u", "_blocked": None}
        with mock.patch.object(pg, "scrape_contact", return_value=info):
            res = FetchContactAtom().run(self._ctx(db, pool), {})
        self.assertEqual(res.outcome, "empty")
        self.assertEqual(len(db.saved_contacts), 1)  # 仍入库
        self.assertEqual(db.no_contact_marks,
                         [{"domain": "shop7.1688.com", "bump_attempts": False}])

    def test_pool_client_none_skips_report(self):
        db = FakeShopDB()
        with mock.patch.object(pg, "scrape_contact", return_value=None):
            res = FetchContactAtom().run(self._ctx(db, pool=None), {})
        self.assertEqual(res.outcome, "blocked")  # 不抛异常

    def test_shop_from_params(self):
        db = FakeShopDB()
        explicit = {"domain": "other.1688.com", "url": "https://other.1688.com"}
        with mock.patch.object(pg, "scrape_contact", return_value=None) as m:
            res = FetchContactAtom().run(self._ctx(db), {"shop": explicit})
        self.assertEqual(res.data["domain"], "other.1688.com")
        self.assertEqual(m.call_args[0][1], "other.1688.com")

    def test_no_shop_empty(self):
        db = FakeShopDB()
        ctx = self._ctx(db)
        ctx.vars["shops"] = []
        res = FetchContactAtom().run(ctx, {})
        self.assertEqual(res.outcome, "empty")


# ----------------------------------------------------------------------
# crawl_category
# ----------------------------------------------------------------------

CAT = {"name": "女装", "keyword": "nvzhuang",
       "url": "https://s.1688.com/selloffer/offer_search.htm?keywords=nvzhuang"}


class TestCrawlCategory(unittest.TestCase):
    def _ctx(self, db, queue, pool=None, page=None):
        return FakeContext(resources={
            "db": db, "page": page or FakePage(),
            "channel": {"id": 2}, "identity": "5.6.7.8",
            "pool_client": pool,
        }, vars={"category_queue": list(queue)})

    def _run(self, ctx, shops, blocked=False, **params):
        params.setdefault("delay_min", 0)
        params.setdefault("delay_max", 0)
        with mock.patch.object(pg, "extract_shops", return_value=shops), \
             mock.patch.object(pg, "page_blocked", return_value=blocked), \
             mock.patch.object(pg, "human_pause", return_value=None):
            return CrawlCategoryAtom().run(ctx, params)

    def test_empty_queue(self):
        db = FakeShopDB()
        res = self._run(self._ctx(db, []), shops=[])
        self.assertEqual(res.outcome, "empty")
        self.assertIn("队列", res.detail)

    def test_ok_with_new_shops(self):
        db = FakeShopDB()
        pool = FakePoolClient()
        ctx = self._ctx(db, [CAT], pool=pool)
        shops = [{"domain": "a.1688.com", "name": "A"},
                 {"domain": "b.1688.com", "name": "B"}]
        res = self._run(ctx, shops=shops)
        self.assertEqual(res.outcome, "ok")
        self.assertEqual(res.data["new_count"], 2)
        self.assertEqual(res.data["extracted"], 2)
        self.assertEqual([r["result"] for r in pool.reports], ["ok"])
        # 入库 + 分页推进 + 类目回插队首
        self.assertEqual(db.advanced, ["nvzhuang"])
        self.assertEqual(len(db.runs), 1)
        self.assertTrue(db.runs[0]["finished"])
        self.assertEqual(ctx.vars["category_queue"], [CAT])
        self.assertEqual(ctx.vars["crawl_state"]["empty_streak"], 0)
        # 分页 URL 第 1 页 = 原 URL
        self.assertEqual(ctx.resources["page"].goto_calls[0]["url"], CAT["url"])

    def test_extracted_but_no_new_is_empty(self):
        """提取正常但无新增 → empty（类目枯竭信号，shop_crawl.py L231-235）。"""
        db = FakeShopDB()
        db.upsert_return = 0
        ctx = self._ctx(db, [CAT])
        res = self._run(ctx, shops=[{"domain": "a.1688.com", "name": "A"}])
        self.assertEqual(res.outcome, "empty")
        self.assertEqual(res.data["new_count"], 0)
        self.assertEqual(ctx.vars["crawl_state"]["empty_streak"], 1)
        self.assertEqual(db.exhausted_marks, [])  # 不标记采完

    def test_last_page_no_result_marks_exhausted(self):
        """第 >1 页空结果 → 标记类目采完（shop_crawl.py L211-216）。"""
        db = FakeShopDB()
        db.progress["nvzhuang"] = {"exhausted": 0, "next_page": 3}
        pool = FakePoolClient()
        res = self._run(self._ctx(db, [CAT], pool=pool), shops=[], blocked=False)
        self.assertEqual(res.outcome, "empty")
        self.assertEqual(db.exhausted_marks, ["nvzhuang"])
        self.assertEqual([r["result"] for r in pool.reports], ["error"])

    def test_first_page_no_result_is_blocked(self):
        """首页无结果 → 疑似风控 blocked（shop_crawl.py L217-219）。"""
        db = FakeShopDB()
        pool = FakePoolClient()
        ctx = self._ctx(db, [CAT], pool=pool)
        res = self._run(ctx, shops=[], blocked=False)
        self.assertEqual(res.outcome, "blocked")
        self.assertEqual(res.data["empty_streak"], 1)
        self.assertEqual([r["result"] for r in pool.reports], ["error"])
        self.assertEqual(db.exhausted_marks, [])

    def test_blocked_page_flag(self):
        db = FakeShopDB()
        pool = FakePoolClient()
        res = self._run(self._ctx(db, [CAT], pool=pool), shops=[], blocked=True)
        self.assertEqual(res.outcome, "blocked")
        self.assertEqual([r["result"] for r in pool.reports], ["blocked"])

    def test_goto_network_error(self):
        db = FakeShopDB()
        pool = FakePoolClient()
        page = FakePage(goto_error=Exception("net::ERR_CONNECTION_RESET"))
        res = self._run(self._ctx(db, [CAT], pool=pool, page=page), shops=[])
        self.assertEqual(res.outcome, "net_error")
        self.assertEqual([r["result"] for r in pool.reports], ["error"])

    def test_goto_other_error_is_blocked(self):
        db = FakeShopDB()
        page = FakePage(goto_error=Exception("Timeout 60000ms exceeded"))
        res = self._run(self._ctx(db, [CAT], page=page), shops=[])
        self.assertEqual(res.outcome, "blocked")

    def test_exhausted_category_skipped(self):
        db = FakeShopDB()
        db.progress["nvzhuang"] = {"exhausted": 1, "next_page": 5}
        res = self._run(self._ctx(db, [CAT]), shops=[])
        self.assertEqual(res.outcome, "empty")  # 队列里没有可采类目

    def test_round_delay_stop_aware(self):
        db = FakeShopDB()
        stop = threading.Event()
        stop.set()  # 已进入停止状态
        ctx = self._ctx(db, [CAT])
        ctx._stop_event = stop
        res = self._run(ctx, shops=[{"domain": "a.1688.com", "name": "A"}],
                        delay_min=5, delay_max=5)
        self.assertEqual(res.outcome, "stopped")


# ----------------------------------------------------------------------
# for_each_shop
# ----------------------------------------------------------------------

class TestForEachShop(unittest.TestCase):
    def setUp(self):
        _TestOkAtom.call_log = []
        _TestFailAtom.call_log = []
        _TestStopAfterAtom.calls = 0
        _TestStopAfterAtom.event = None

    def _ctx(self):
        return FakeContext(resources={})

    def test_batch_quota_and_rest(self):
        """num=2 / max_batches=2 → 2 批共 4 次迭代，中间休息一次 ±10%。"""
        ctx = self._ctx()
        res = ForEachShopAtom().run(ctx, {
            "num": 2, "batch_rest": 100, "max_batches": 2,
            "body": [{"id": "s", "atom": "test_ok"}],
        })
        self.assertEqual(res.outcome, "ok")
        self.assertEqual(len(_TestOkAtom.call_log), 4)
        self.assertEqual(res.data["ok"], 4)
        self.assertEqual(res.data["batches"], 2)
        # 一次批间休息，时长在 [90, 110]（±10%）
        rest_waits = [w for w in ctx.waits if w > 1]
        self.assertEqual(len(rest_waits), 1)
        self.assertTrue(90 <= rest_waits[0] <= 110)
        self.assertEqual(ctx.vars["loop_stats"], res.data)

    def test_limit_caps_iterations(self):
        ctx = self._ctx()
        res = ForEachShopAtom().run(ctx, {
            "num": 10, "limit": 3,
            "body": [{"id": "s", "atom": "test_ok"}],
        })
        self.assertEqual(res.outcome, "ok")
        self.assertEqual(len(_TestOkAtom.call_log), 3)
        self.assertEqual(res.data["fetched"], 3)

    def test_child_failure_interrupts_iteration_and_continues(self):
        """子节点非 ok → 中断本迭代（后续子节点不执行），计 failed 后继续。"""
        ctx = self._ctx()
        res = ForEachShopAtom().run(ctx, {
            "num": 3, "max_batches": 1,
            "body": [{"id": "f", "atom": "test_fail"},
                     {"id": "s", "atom": "test_ok"}],
        })
        self.assertEqual(len(_TestFailAtom.call_log), 3)
        self.assertEqual(_TestOkAtom.call_log, [])  # 被中断，未执行
        self.assertEqual(res.data["failed"], 3)
        self.assertEqual(res.data["ok"], 0)
        self.assertEqual(res.data["fetched"], 0)  # failed 不计入 limit 口径

    def test_failed_does_not_count_toward_limit(self):
        """limit 只计 ok+empty：全部失败时靠 max_batches 收尾。"""
        ctx = self._ctx()
        res = ForEachShopAtom().run(ctx, {
            "num": 2, "batch_rest": 10, "max_batches": 2, "limit": 1,
            "body": [{"id": "f", "atom": "test_fail"}],
        })
        self.assertEqual(res.data["failed"], 4)  # 跑满 2 批
        self.assertEqual(res.data["fetched"], 0)

    def test_stop_branch(self):
        """假原子第 2 次调用后置停止标志 → 容器以 stopped 收尾。"""
        stop = threading.Event()
        _TestStopAfterAtom.stop_after = 2
        _TestStopAfterAtom.event = stop
        ctx = FakeContext(resources={}, stop_event=stop)
        res = ForEachShopAtom().run(ctx, {
            "num": 10,
            "body": [{"id": "z", "atom": "test_stop_after"}],
        })
        self.assertEqual(res.outcome, "stopped")
        self.assertLessEqual(_TestStopAfterAtom.calls, 2)
        self.assertIn("loop_stats", ctx.vars)

    def test_stop_during_batch_rest(self):
        """批间休息期间被停止 → stopped（ctx.wait 返回 True）。"""
        stop = threading.Event()

        class StopOnWaitCtx(FakeContext):
            def wait(self, seconds):
                self.waits.append(seconds)
                if seconds > 1:  # 批间休息
                    stop.set()
                return stop.is_set()

        ctx = StopOnWaitCtx(resources={}, stop_event=stop)
        res = ForEachShopAtom().run(ctx, {
            "num": 1, "batch_rest": 100, "max_batches": 0,
            "body": [{"id": "s", "atom": "test_ok"}],
        })
        self.assertEqual(res.outcome, "stopped")
        self.assertEqual(len(_TestOkAtom.call_log), 1)

    def test_claim_empty_breaks_loop(self):
        """认领枯竭（empty + shops==[]）→ 整个循环结束，fetched=0 → empty。"""
        ctx = self._ctx()
        res = ForEachShopAtom().run(ctx, {
            "num": 10,
            "body": [{"id": "c", "atom": "test_claim_empty"},
                     {"id": "s", "atom": "test_ok"}],
        })
        self.assertEqual(res.outcome, "empty")
        self.assertEqual(_TestOkAtom.call_log, [])
        self.assertEqual(res.data["fetched"], 0)

    def test_parallel_validation(self):
        with self.assertRaises(ValueError):
            ForEachShopAtom().run(self._ctx(), {
                "parallel": 0, "body": [{"id": "s", "atom": "test_ok"}]})

    def test_empty_body_rejected(self):
        with self.assertRaises(ValueError):
            ForEachShopAtom().run(self._ctx(), {"body": []})


if __name__ == "__main__":
    unittest.main()
