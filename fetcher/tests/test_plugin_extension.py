# -*- coding: utf-8 -*-
"""P4 扩展性测试：
1. 模拟第三方加站点——测试内临时定义最小 SitePlugin 并注册，
   用 mock session 跑通 CrawlLoop 全流程（不改框架任何文件）；
2. 淘宝插件探测器单测（域隔离：login.taobao.com 命中、1688 特征不互相污染）；
3. 淘宝任务解析器 / validate 单测。
全 mock，不起真实浏览器/网络。"""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fetcher import (
    IdentityStore,
    RunConfig,
    Scenario,
    SceneInspector,
    Session,
    ShopDB,
    WorkerContext,
)
from fetcher.control import CrawlLoop, Task
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites import get_site, register_site, site_names
from fetcher.sites.taobao.search import TaobaoSearchTask, parse_search_items
from fetcher.strategy.policy import Policy

from tests.test_control_loop import FakePage, MockBrowserManager, make_config


# ---------- 1. 第三方最小站点插件（测试内定义，框架零改动） ----------

class MiniPlugin:
    """最小站点实现：只有特征表 + 一个内存任务。"""

    name = "mini"
    cookie_domain = "mini.example.com"
    homepage = "https://mini.example.com/"

    def detectors(self) -> list:
        from fetcher.detect.generic import EmptyPageDetector, LoginWallDetector
        return [LoginWallDetector(("login.mini.example.com",),
                                  name="mini_login"),
                EmptyPageDetector(30, name="mini_empty")]

    def block_reason(self, page) -> str | None:
        from fetcher.detect.generic import make_block_reason
        return make_block_reason(("login.mini.example.com",), (), (),
                                 (), ())(page)

    def task_names(self):
        return ["echo"]

    def make_task(self, name):
        if name != "echo":
            raise KeyError(name)
        return MiniTask()


class MiniTask(Task):
    """最小任务：队列里两个 item，fetch 直接成功。"""

    name = "echo"

    def __init__(self):
        self.items = ["a", "b"]
        self.done = []

    def acquire_item(self, ctx):
        return self.items.pop(0) if self.items else None

    def fetch(self, ctx, item):
        return ActionResult(Outcome.OK, "", {"echo": item})

    def validate(self, ctx, item, result):
        return "echo" in (result.data or {})

    def on_success(self, ctx, item, result):
        self.done.append(result.data["echo"])
        return 1

    def make_stats(self):
        return {"done": 0}


class ThirdPartySiteTest(unittest.TestCase):
    """证明「加目录即接入」：注册 → CLI 可见 → CrawlLoop 全流程跑通。"""

    @classmethod
    def setUpClass(cls):
        register_site("mini", MiniPlugin)

    def test_registered_and_discoverable(self):
        self.assertIn("mini", site_names())
        site = get_site("mini")
        self.assertEqual(site.task_names(), ["echo"])

    def test_crawl_loop_full_flow_with_mini_site(self):
        tmp = tempfile.TemporaryDirectory()
        page = FakePage()
        page.url = "https://mini.example.com/list"
        mgr = MockBrowserManager(page)
        config = make_config(tmp.name, batch_num=2, max_batches=1)
        store = IdentityStore(ShopDB(config.resolved_db_path()))
        ctx = WorkerContext(config=config, store=store, browser_manager=mgr,
                            site=MiniPlugin(), stop=threading.Event(),
                            log=lambda m: None)
        task = MiniTask()
        # 第三方站点的探测器经标准装配链生效
        inspector = SceneInspector.for_site(ctx.site)
        self.assertEqual([d.name for d in inspector.detectors],
                         ["fatal_error", "network", "mini_login", "mini_empty"])
        loop = CrawlLoop(ctx, task, policy=Policy(), inspector=inspector)
        loop.run()
        self.assertEqual(task.done, ["a", "b"])  # 两个 item 全部采完
        self.assertEqual(loop.circuit.count, 0)
        tmp.cleanup()

    def test_mini_login_wall_detected(self):
        inspector = SceneInspector.for_site(MiniPlugin())
        page = FakePage()
        page.url = "https://login.mini.example.com/signin"
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        self.assertIs(inspector.inspect(ctx), Scenario.RISK_LOGIN)


# ---------- 2. 淘宝探测器（域隔离） ----------

class TaobaoDetectorTest(unittest.TestCase):
    def setUp(self):
        self.taobao = SceneInspector.for_site(get_site("taobao"))
        self.ali1688 = SceneInspector.for_site(get_site("1688"))

    def inspect(self, inspector, url, text="正常页面文本，足够长，包含商品标题价格店铺销量信息字段。"):
        page = FakePage()
        page.url = url
        page._text = text
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        return inspector.inspect(ctx)

    def test_taobao_login_wall(self):
        s = self.inspect(self.taobao, "https://login.taobao.com/member/login.jhtml")
        self.assertIs(s, Scenario.RISK_LOGIN)

    def test_domain_isolation_taobao_ignores_1688_login(self):
        # 1688 登录墙 URL 在淘宝特征表下不是 RISK_LOGIN（域不互相污染）
        s = self.inspect(self.taobao, "https://login.1688.com/member/signin.htm")
        self.assertIsNot(s, Scenario.RISK_LOGIN)

    def test_domain_isolation_1688_ignores_taobao_login(self):
        s = self.inspect(self.ali1688, "https://login.taobao.com/member/login.jhtml")
        self.assertIsNot(s, Scenario.RISK_LOGIN)

    def test_taobao_slider_page(self):
        s = self.inspect(self.taobao, "https://sec.taobao.com/punish.htm?x5sec=abc")
        self.assertIs(s, Scenario.RISK_SLIDER_PAGE)

    def test_taobao_embedded_slider(self):
        page = FakePage()
        page.frames = [type("F", (), {"url": "https://sec.taobao.com/x5sec/if.htm"})()]
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        self.assertIs(self.taobao.inspect(ctx), Scenario.RISK_SLIDER_EMBED)

    def test_taobao_policy_overrides_applied(self):
        # 站点级策略覆盖：solve_slider 加码到 5 次（1688 默认 3 次）
        site = get_site("taobao")
        policy = Policy().with_overrides(site.policy_overrides)
        chain = policy.table[Scenario.RISK_SLIDER_PAGE]
        self.assertEqual(chain[0], ("solve_slider", 5))
        # 未覆盖的场景保持默认表
        self.assertIn(("clear_identity_swap", 2),
                      [tuple(e) for e in policy.table[Scenario.RISK_LOGIN]])


# ---------- 3. 淘宝任务解析器 / validate / fetch ----------

class TaobaoParserTest(unittest.TestCase):
    def test_parse_basic(self):
        # 夹具使用 JS 归一化后的键名（_JS_EXTRACT_ITEMS 的输出结构）
        raw = {"items": [
            {"title": "夏季<em>连衣裙</em>女", "price": "89.00",
             "shop": "杭州女装店", "url": "//item.taobao.com/item.htm?id=1",
             "sales": "1000人付款"},
            {"title": "", "url": "//item.taobao.com/item.htm?id=2"},  # 无标题丢弃
            {"title": "蓝牙耳机", "price": "199",
             "shop": "数码店", "url": ""},  # 无链接丢弃
        ]}
        items = parse_search_items(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "夏季连衣裙女")  # 高亮标签已剔除
        self.assertEqual(items[0]["url"],
                         "https://item.taobao.com/item.htm?id=1")  # 协议补齐
        self.assertEqual(items[0]["price"], "89.00")
        self.assertEqual(items[0]["shop"], "杭州女装店")

    def test_parse_empty(self):
        self.assertEqual(parse_search_items({}), [])
        self.assertEqual(parse_search_items({"items": None}), [])


class TaobaoValidateTest(unittest.TestCase):
    def setUp(self):
        self.task = TaobaoSearchTask(keywords=["测试词"])

    def _result(self, items, no_result=False):
        return ActionResult(Outcome.OK, "",
                            {"items": items, "no_result": no_result})

    def test_valid_with_items(self):
        self.assertTrue(self.task.validate(None, None, self._result(
            [{"title": "t", "url": "u"}])))

    def test_valid_empty_with_no_result_marker(self):
        # 正常末页：items 空 + 页面明示「没有找到」→ 合法，不走策略链
        self.assertTrue(self.task.validate(None, None, self._result(
            [], no_result=True)))

    def test_invalid_empty_without_marker(self):
        # 软拦截/解析失效：items 空且无「无结果」标记 → EMPTY 进策略链
        self.assertFalse(self.task.validate(None, None, self._result([])))

    def test_invalid_malformed(self):
        r = ActionResult(Outcome.OK, "", {"embedded": True})
        self.assertFalse(self.task.validate(None, None, r))


class TaobaoFetchTest(unittest.TestCase):
    """fetch 的 mtop 门控与解析路径（mock page + 补丁 sleep，不发真实请求）。"""

    def _page(self, cookies, extract_result, text=""):
        page = FakePage()
        page.context.cookies = lambda: cookies
        page._extract = extract_result
        page._raw_text = text
        def evaluate(js):
            if "INIT_DATA" in js or "g_page_config" in js or "itemlist" in js:
                return page._extract
            if "querySelectorAll" in js:
                return {"items": [], "found": 0, "embedded": False}
            return page._raw_text
        page.evaluate = evaluate
        page.goto_calls = []
        page.goto = lambda *a, **kw: page.goto_calls.append((a, kw))
        return page

    def test_fetch_blocked_without_mtop_token(self):
        # 无 _m_h5_tk 且握手拿不到 → BLOCKED，不触碰搜索页
        task = TaobaoSearchTask(keywords=["连衣裙"])
        page = self._page(cookies=[], extract_result={})
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        ctx.site = get_site("taobao")
        with mock.patch("fetcher.sites.taobao.search.time.sleep"), \
             mock.patch("fetcher.sites.mtop.time.sleep"), \
             mock.patch("fetcher.sites.mtop.random.uniform", return_value=0):
            result = task.fetch(ctx, ("连衣裙", 1))
        self.assertIs(result.outcome, Outcome.BLOCKED)
        self.assertIn("mtop", result.detail)
        # goto 只发生在握手尝试上，没有触碰搜索页
        self.assertFalse(any("s.taobao.com/search"
                             in str(c[0][0]) for c in page.goto_calls))

    def test_fetch_parses_with_token(self):
        task = TaobaoSearchTask(keywords=["连衣裙"])
        cookies = [{"name": "_m_h5_tk", "value": "tok",
                    "domain": ".taobao.com"}]
        extract = {"items": [{"title": "连衣裙女夏", "price": "89",
                              "shop": "女装店",
                              "url": "//item.taobao.com/item.htm?id=9",
                              "sales": "500人付款"}],
                   "found": 1, "embedded": True}
        page = self._page(cookies, extract,
                          text="连衣裙女夏 89 女装店 正常搜索结果页文本")
        ctx = WorkerContext(log=lambda m: None)
        ctx.session = Session(page=page)
        ctx.site = get_site("taobao")
        with mock.patch("fetcher.sites.taobao.search.time.sleep"), \
             mock.patch("fetcher.sites.taobao.search.random.uniform",
                        return_value=0):
            result = task.fetch(ctx, ("连衣裙", 1))
        self.assertIs(result.outcome, Outcome.OK)
        self.assertEqual(len(result.data["items"]), 1)
        self.assertEqual(result.data["items"][0]["title"], "连衣裙女夏")
        self.assertTrue(task.validate(ctx, ("连衣裙", 1), result))

    def test_persist_jsonl_not_1688_db(self):
        """on_success 落 JSONL，与 1688 库语义零接触。"""
        tmp = tempfile.TemporaryDirectory()
        out = Path(tmp.name) / "items.jsonl"
        task = TaobaoSearchTask(keywords=["连衣裙"], out_path=str(out))
        ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
        ctx.state["task"] = {"stats": task.make_stats()}
        result = ActionResult(Outcome.OK, "", {
            "items": [{"title": "裙子", "price": "89", "shop": "店",
                       "url": "https://item.taobao.com/item.htm?id=1",
                       "sales": ""}],
            "_source_url": "https://s.taobao.com/search?q=连衣裙"})
        n = task.on_success(ctx, ("连衣裙", 1), result)
        self.assertEqual(n, 1)
        rows = [json.loads(line) for line in
                out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["keyword"], "连衣裙")
        self.assertEqual(rows[0]["title"], "裙子")
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
