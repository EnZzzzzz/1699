# -*- coding: utf-8 -*-
"""义乌购站点插件测试：
1. 注册与发现（site_names/get_site/CLI 装配链）；
2. 探测器（passport 登录墙 / captcha 整页与内嵌 / 与 1688、淘宝域隔离）；
3. 解析器（搜索 prslist / 详情 shopinfo / 失效商品）纯函数单测；
4. fetch 的 csrf 门控与错误码分级（mock page.request，不发真实请求）；
5. validate / on_success JSONL 落盘；
6. 策略覆盖（自研滑块不用 solve_slider）。
全 mock，不起真实浏览器/网络。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fetcher import RunConfig, Scenario, Session, WorkerContext
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites import get_site, site_names
from fetcher.sites.yiwugo.contact import (
    ProductIdQueue,
    YiwugoContactTask,
    has_any_contact,
    parse_contact,
)
from fetcher.sites.yiwugo.search import (
    YiwugoSearchTask,
    parse_search_products,
)
from fetcher.strategy.policy import Policy

from tests.test_control_loop import FakePage


# ---------- mock 设施 ----------

class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeRequest:
    """page.request：记录调用并返回编程响应。"""

    def __init__(self, data):
        self.data = data
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return FakeResponse(self.data)


def make_page(cookies=(), api_data=None, url="https://www.yiwugo.com/",
              text="义乌购首页正常文本，足够长，包含市场分类导航与商品信息。"):
    page = FakePage()
    page.url = url
    page._text = text
    page.context.cookies = lambda: list(cookies)
    page.request = FakeRequest(api_data or {})
    page.goto_calls = []
    page.goto = lambda *a, **kw: page.goto_calls.append((a, kw))
    return page


CSRF_COOKIE = {"name": "csrfToken", "value": "tok123",
               "domain": ".yiwugo.com"}

SEARCH_FIXTURE = {
    "code": "1",
    "content": {
        "numfound": 19517,
        "isproduct": True,
        "prslist": [
            {"id": 930986264, "shopId": 516312, "title": "苹果手机壳",
             "picture1": "http://img1.yiwugo.com/a.jpg", "metric": "个",
             "shopName": "倚天手机配件", "credit": 2,
             "shopUrlId": "0217603",
             "marketinfo": "义乌国际商贸城二区35门3楼5街17603",
             "marketOrAdress": "义乌国际商贸城二区", "boothNo": "17603",
             "sellPrice": None, "maxPrice": 0, "isAd": False},
            {"id": None, "title": "无 id 丢弃"},
            {"id": 123, "title": ""},  # 无标题丢弃
            {"id": 978772079, "shopId": 550614, "title": "磨砂手机壳",
             "shopName": "某店", "shopUrlId": "", "isAd": True},
        ],
    },
}

DETAIL_FIXTURE = {
    "code": "1",
    "content": {
        "years": 15, "sid": "0217603",
        "shopinfo": {"shop": {
            "shopId": 516312, "shopName": "倚天手机配件",
            "shopUrlId": "0217603", "contacter": "黄倚天",
            "telephone": "057985187604", "mobile": "13958499113",
            "safemobile": "13958499113", "email": "13606899397@163.com",
            "qq": 2813882573, "weixin": "yitian123", "weixinName": "倚天",
            "boothids": "17603,17604", "introduction": "手机壳〃数据线",
            "mainProduct": "手机壳", "factoryAddress": "义乌",
            "credit": 2}},
    },
}

DEAD_FIXTURE = {"code": "1", "content": {"errorInfo": "商品不存在，已被删除"}}


# ---------- 1. 注册与发现 ----------

class YiwugoRegistrationTest(unittest.TestCase):
    def test_registered(self):
        self.assertIn("yiwugo", site_names())
        site = get_site("yiwugo")
        self.assertEqual(site.name, "yiwugo")
        self.assertEqual(site.cookie_domain, "yiwugo.com")
        self.assertEqual(sorted(site.task_names()), ["contact", "search"])

    def test_make_task(self):
        site = get_site("yiwugo")
        self.assertIsInstance(site.make_task("search"), YiwugoSearchTask)
        self.assertIsInstance(site.make_task("contact"), YiwugoContactTask)
        with self.assertRaises(KeyError):
            site.make_task("nope")


# ---------- 2. 探测器 ----------

class YiwugoDetectorTest(unittest.TestCase):
    def setUp(self):
        from fetcher import SceneInspector
        self.inspector = SceneInspector.for_site(get_site("yiwugo"))
        self.ali = SceneInspector.for_site(get_site("1688"))

    def inspect(self, url, text="正常页面文本，足够长，包含商品标题价格店铺信息字段。"):
        page = FakePage()
        page.url = url
        page._text = text
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        return self.inspector.inspect(ctx)

    def test_login_wall(self):
        s = self.inspect("https://passport.yiwugo.com/login?back=x")
        self.assertIs(s, Scenario.RISK_LOGIN)

    def test_captcha_page_by_url(self):
        s = self.inspect("https://captcha.yiwugo.com/gen")
        self.assertIs(s, Scenario.RISK_SLIDER_PAGE)

    def test_captcha_page_by_text(self):
        s = self.inspect("https://www.yiwugo.com/search/s.html",
                         text="请完成安全验证，拖动滑块完成验证")
        self.assertIs(s, Scenario.RISK_SLIDER_PAGE)

    def test_embedded_captcha_iframe(self):
        page = FakePage()
        page.url = "https://www.yiwugo.com/search/s.html"
        page.frames = [type("F", (), {"url": "https://captcha.yiwugo.com/gen?x=1"})()]
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        self.assertIs(self.inspector.inspect(ctx), Scenario.RISK_SLIDER_EMBED)

    def test_domain_isolation_ignores_alibaba_features(self):
        # 1688 的登录墙/风控 URL 在义乌购特征表下不命中（域名无关）
        s = self.inspect("https://login.1688.com/member/signin.htm")
        self.assertIsNot(s, Scenario.RISK_LOGIN)
        s = self.inspect("https://sec.taobao.com/punish.htm?x5sec=abc")
        self.assertIsNot(s, Scenario.RISK_SLIDER_PAGE)

    def test_domain_isolation_1688_ignores_yiwugo(self):
        page = FakePage()
        page.url = "https://passport.yiwugo.com/login"
        page._text = "正常页面文本，足够长，包含商品标题价格店铺信息字段。"
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        self.assertIsNot(self.ali.inspect(ctx), Scenario.RISK_LOGIN)

    def test_policy_overrides_no_solve_slider(self):
        # 自研滑块不吃阿里轨迹回放：策略链里没有 solve_slider
        site = get_site("yiwugo")
        policy = Policy().with_overrides(site.policy_overrides)
        for scenario in (Scenario.RISK_SLIDER_PAGE, Scenario.RISK_SLIDER_EMBED):
            names = [e[0] for e in policy.table[scenario]]
            self.assertNotIn("solve_slider", names)
            self.assertIn("block_rest", names)
            self.assertIn("swap_ip", names)


# ---------- 3. 解析器 ----------

class YiwugoSearchParserTest(unittest.TestCase):
    def test_parse_basic(self):
        items, numfound = parse_search_products(SEARCH_FIXTURE)
        self.assertEqual(numfound, 19517)
        self.assertEqual(len(items), 2)  # 无 id / 无标题各丢弃一条
        p = items[0]
        self.assertEqual(p["id"], 930986264)
        self.assertEqual(p["title"], "苹果手机壳")
        self.assertEqual(p["shop_name"], "倚天手机配件")
        self.assertEqual(p["booth_no"], "17603")
        self.assertIn("义乌国际商贸城二区", p["market_info"])
        self.assertEqual(p["url"],
                         "https://www.yiwugo.com/product/detail/930986264.html")
        self.assertEqual(p["shop_url"], "https://www.yiwugo.com/hu/0217603.html")
        self.assertFalse(p["is_ad"])
        self.assertTrue(items[1]["is_ad"])
        self.assertEqual(items[1]["shop_url"], "")  # 无 shopUrlId 不拼商铺链接

    def test_parse_empty(self):
        self.assertEqual(parse_search_products({}), ([], 0))
        self.assertEqual(parse_search_products({"content": None}), ([], 0))


class YiwugoContactParserTest(unittest.TestCase):
    def test_parse_full_contact(self):
        c = parse_contact(DETAIL_FIXTURE)
        self.assertEqual(c["contacter"], "黄倚天")
        self.assertEqual(c["telephone"], "057985187604")
        self.assertEqual(c["mobile"], "13958499113")
        self.assertEqual(c["email"], "13606899397@163.com")
        self.assertEqual(c["qq"], "2813882573")  # 数字归一成字符串
        self.assertEqual(c["weixin"], "yitian123")
        self.assertEqual(c["shop_name"], "倚天手机配件")
        self.assertEqual(c["years"], 15)
        self.assertTrue(has_any_contact(c))

    def test_dead_product(self):
        self.assertIsNone(parse_contact(DEAD_FIXTURE))

    def test_no_shopinfo(self):
        self.assertIsNone(parse_contact({"code": "1", "content": {}}))
        self.assertIsNone(parse_contact({}))

    def test_empty_contact_invalid(self):
        c = parse_contact({"code": "1", "content": {"shopinfo": {"shop": {
            "shopId": 1, "shopName": "空店"}}}})
        self.assertIsNotNone(c)
        self.assertFalse(has_any_contact(c))


# ---------- 4. fetch（csrf 门控 + 错误码分级） ----------

class YiwugoSearchFetchTest(unittest.TestCase):
    def _ctx(self, page):
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        ctx.site = get_site("yiwugo")
        return ctx

    def test_blocked_without_csrf_token(self):
        # 无 csrfToken 且握手拿不到 → BLOCKED，不触碰 API
        task = YiwugoSearchTask(keywords=["手机壳"])
        page = make_page(cookies=[], api_data=SEARCH_FIXTURE)
        with mock.patch("fetcher.sites.yiwugo.features.time.sleep"), \
             mock.patch("fetcher.sites.yiwugo.features.random.uniform",
                        return_value=0):
            result = task.fetch(self._ctx(page), ("手机壳", 1))
        self.assertIs(result.outcome, Outcome.BLOCKED)
        self.assertIn("csrfToken", result.detail)
        self.assertEqual(page.request.calls, [])  # API 零触碰
        # 握手尝试过首页（goto 过）
        self.assertTrue(page.goto_calls)

    def test_ok_with_token(self):
        task = YiwugoSearchTask(keywords=["手机壳"])
        page = make_page(cookies=[CSRF_COOKIE], api_data=SEARCH_FIXTURE)
        result = task.fetch(self._ctx(page), ("手机壳", 1))
        self.assertIs(result.outcome, Outcome.OK)
        self.assertEqual(len(result.data["items"]), 2)
        self.assertEqual(result.data["numfound"], 19517)
        # 请求头带上了 x-csrf-token
        call = page.request.calls[0]
        self.assertEqual(call["headers"]["x-csrf-token"], "tok123")
        self.assertEqual(call["params"]["q"], "手机壳")
        self.assertEqual(call["params"]["cpage"], 1)
        self.assertEqual(call["params"]["appid"], 6)
        self.assertTrue(task.validate(None, ("手机壳", 1), result))

    def test_illegal_code_blocked(self):
        task = YiwugoSearchTask(keywords=["x"])
        page = make_page(cookies=[CSRF_COOKIE],
                         api_data={"code": -1, "msg": "非法请求"})
        result = task.fetch(self._ctx(page), ("x", 1))
        self.assertIs(result.outcome, Outcome.BLOCKED)
        self.assertIn("-1", result.detail)

    def test_captcha_code_blocked(self):
        task = YiwugoSearchTask(keywords=["x"])
        page = make_page(cookies=[CSRF_COOKIE],
                         api_data={"code": -5, "msg": "验证码错误"})
        result = task.fetch(self._ctx(page), ("x", 1))
        self.assertIs(result.outcome, Outcome.BLOCKED)
        self.assertIn("-5", result.detail)

    def test_no_result_valid(self):
        task = YiwugoSearchTask(keywords=["x"])
        page = make_page(cookies=[CSRF_COOKIE],
                         api_data={"code": "1",
                                   "content": {"numfound": 0, "prslist": []}})
        result = task.fetch(self._ctx(page), ("x", 1))
        self.assertIs(result.outcome, Outcome.OK)
        self.assertTrue(result.data["no_result"])
        self.assertTrue(task.validate(None, ("x", 1), result))


class YiwugoContactFetchTest(unittest.TestCase):
    def _ctx(self, page, config=None):
        ctx = WorkerContext(config=config or RunConfig(),
                            log=lambda m: None)
        ctx.session = Session(page=page)
        ctx.site = get_site("yiwugo")
        ctx.state["task"] = {"stats": {}}
        return ctx

    def test_ok_with_contact(self):
        task = YiwugoContactTask(ids=[930986264])
        task.queue = ProductIdQueue([{"id": 930986264, "title": "苹果手机壳"}])
        page = make_page(cookies=[CSRF_COOKIE], api_data=DETAIL_FIXTURE)
        result = task.fetch(self._ctx(page), {"id": 930986264})
        self.assertIs(result.outcome, Outcome.OK)
        c = result.data["contact"]
        self.assertEqual(c["contacter"], "黄倚天")
        self.assertEqual(c["id"], 930986264)
        self.assertTrue(task.validate(None, {"id": 1}, result))
        # Referer 指向商品详情页
        self.assertIn("/product/detail/930986264.html",
                      page.request.calls[0]["headers"]["Referer"])

    def test_dead_product_ok_not_blocked(self):
        # 失效商品是正常业务态：OK + dead 标记，不进风控策略链
        task = YiwugoContactTask(ids=[1])
        page = make_page(cookies=[CSRF_COOKIE], api_data=DEAD_FIXTURE)
        result = task.fetch(self._ctx(page), {"id": 1})
        self.assertIs(result.outcome, Outcome.OK)
        self.assertTrue(result.data["dead"])
        self.assertTrue(task.validate(None, {"id": 1}, result))

    def test_unauthorized_blocked(self):
        task = YiwugoContactTask(ids=[1])
        page = make_page(cookies=[CSRF_COOKIE], api_data={"code": "-2"})
        result = task.fetch(self._ctx(page), {"id": 1})
        self.assertIs(result.outcome, Outcome.BLOCKED)
        self.assertIn("-2", result.detail)


# ---------- 5. 落盘 ----------

class YiwugoPersistTest(unittest.TestCase):
    def test_search_jsonl(self):
        tmp = tempfile.TemporaryDirectory()
        out = Path(tmp.name) / "items.jsonl"
        task = YiwugoSearchTask(keywords=["手机壳"], out_path=str(out))
        ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
        ctx.state["task"] = {"stats": task.make_stats()}
        items, numfound = parse_search_products(SEARCH_FIXTURE)
        result = ActionResult(Outcome.OK, "",
                              {"items": items, "numfound": numfound})
        n = task.on_success(ctx, ("手机壳", 1), result)
        self.assertEqual(n, 2)
        rows = [json.loads(x) for x in
                out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["keyword"], "手机壳")
        self.assertEqual(rows[0]["title"], "苹果手机壳")
        tmp.cleanup()

    def test_contact_jsonl_and_dead_counter(self):
        tmp = tempfile.TemporaryDirectory()
        out = Path(tmp.name) / "contacts.jsonl"
        task = YiwugoContactTask(ids=[1], out_path=str(out))
        ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
        ctx.state["task"] = {"stats": task.make_stats()}
        contact = parse_contact(DETAIL_FIXTURE)
        contact["id"] = 930986264
        n = task.on_success(ctx, {"id": 930986264},
                            ActionResult(Outcome.OK, "", {"contact": contact}))
        self.assertEqual(n, 1)
        n = task.on_success(ctx, {"id": 2},
                            ActionResult(Outcome.OK, "", {"dead": True}))
        self.assertEqual(n, 1)  # 失效商品也计处理量，但不落盘
        rows = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)  # 只有有效联系方式落盘
        self.assertEqual(ctx.state["task"]["stats"]["dead"], 1)
        self.assertEqual(ctx.state["task"]["stats"]["contacts"], 1)
        tmp.cleanup()

    def test_queue_from_jsonl_dedup(self):
        tmp = tempfile.TemporaryDirectory()
        src = Path(tmp.name) / "items.jsonl"
        src.write_text("\n".join([
            json.dumps({"id": 1, "title": "a"}),
            json.dumps({"id": 1, "title": "a 重复"}),
            json.dumps({"id": 2, "title": "b"}),
            "坏行{",
            json.dumps({"title": "无 id 丢弃"}),
        ]), encoding="utf-8")
        q = ProductIdQueue.from_jsonl(src)
        self.assertEqual(q.remaining(), 2)
        self.assertEqual(q.pick()["id"], 1)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
