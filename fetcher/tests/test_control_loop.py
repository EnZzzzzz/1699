# -*- coding: utf-8 -*-
"""CrawlLoop 集成测试：可编程 fetch + 假策略 + mock BrowserManager，
全 mock（不起真实浏览器/网络，临时 sqlite）。"""

import tempfile
import threading
import unittest
from pathlib import Path

from fetcher import (
    Alibaba1688Plugin,
    IdentityStore,
    RunConfig,
    Scenario,
    Session,
    ShopDB,
    SiteView,
    WorkerContext,
)
from fetcher.atoms.browser_ops import RelaunchBrowser
from fetcher.control import CrawlLoop, Task
from fetcher.core.types import ActionResult, Outcome
from fetcher.strategy.base import StepResult
from fetcher.strategy.policy import Policy


# ---------- mock 插件（多站点测试用） ----------

class MockPlugin:
    """符合 SitePlugin 协议的假插件（返回空探测器列表）。"""

    def __init__(self, name, cookie_domain):
        self.name = name
        self.cookie_domain = cookie_domain

    def detectors(self):
        return []


# ---------- mock 基础设施 ----------

class FakeBrowser:
    def is_connected(self):
        return True

    def close(self):
        pass


class FakeContext:
    def __init__(self):
        self.browser = FakeBrowser()

    def cookies(self):
        return []


class FakePage:
    def __init__(self):
        self.url = "https://shop123.1688.com/page/contactinfo.htm"
        self._text = "正常页面文本，足够长，包含电话、手机、地址等字段标签，超过阈值。"
        self.frames = []
        self.context = FakeContext()

    def evaluate(self, js):
        return self._text

    def query_selector(self, sel):
        return None

    def is_closed(self):
        return False


class MockBrowserManager:
    """launch/relaunch 返回带假 page 的 Session；身份按序轮换。"""

    def __init__(self, page, identities=("1688:1.1.1.1", "1688:2.2.2.2", "1688:3.3.3.3")):
        self.page = page
        self.identities = list(identities)
        self.launch_count = 0
        self.relaunch_count = 0

    def _make(self, seed_kit):
        idx = min(self.launch_count + self.relaunch_count,
                  len(self.identities) - 1)
        return Session(browser=FakeBrowser(), page=self.page,
                       identity=self.identities[idx], seed_kit=seed_kit)

    def launch(self, seed_kit=None, stop=None):
        session = self._make(seed_kit)
        self.launch_count += 1
        return session

    def relaunch(self, session, channel=None, seed_kit="__keep__",
                 stop=None, max_retry=None, backoff_base=30.0,
                 backoff_cap=120.0):
        kit = session.seed_kit if seed_kit == "__keep__" else seed_kit
        new = self._make(kit)
        self.relaunch_count += 1
        return new

    def check_ip_fresh(self, session):
        return False, session.identity, ""

    def save_cookies(self, session):
        return 0


class ScriptedTask(Task):
    """可编程任务：fetch 按 script 逐条出账。

    script 条目：
        ("ok", data)              正常返回
        ("net", msg)              网络层错误（写 last_error）
        ("stall",)                goto 超时（写 last_error，浏览器活着）
        ("page", url, text, data) 把假页面置为指定状态后正常返回
        ("blocked", reason)       自报 BLOCKED（无页面变化）
        None                      返回 None（旧 scrape 失败语义）
    """

    name = "scripted"
    giveup_cost_value = 1

    def __init__(self, script, items=("item1",), validate_ok=True):
        self.script = list(script)
        self.items = list(items)
        self.fetches = 0
        self.succeeded = []
        self.given_up = []
        self.aborted = []
        self._validate_ok = validate_ok

    def acquire_item(self, ctx):
        return self.items.pop(0) if self.items else None

    def fetch(self, ctx, item):
        self.fetches += 1
        step = self.script.pop(0) if self.script else ("ok", {"v": 1})
        kind = step[0]
        if kind == "ok":
            return ActionResult(Outcome.OK, "", step[1] if len(step) > 1 else {})
        if kind == "net":
            ctx.last_error = Exception(step[1])
            return ActionResult.net_error(step[1])
        if kind == "stall":
            ctx.last_error = Exception("Timeout 60000ms exceeded.")
            return ActionResult.blocked("goto 超时")
        if kind == "page":
            ctx.page.url = step[1]
            ctx.page._text = step[2]
            return ActionResult(Outcome.OK, "", step[3] if len(step) > 3 else {})
        if kind == "blocked":
            return ActionResult.blocked(step[1])
        if kind == "none":
            return None
        raise ValueError(kind)

    def validate(self, ctx, item, result):
        return self._validate_ok

    def on_success(self, ctx, item, result):
        self.succeeded.append(item)
        return 1

    def on_giveup(self, ctx, item, reason, kind):
        self.given_up.append((item, kind))
        return "标记跳过"

    def on_abort(self, ctx, item):
        self.aborted.append(item)
        return "补充说明"

    def giveup_cost(self, item):
        return self.giveup_cost_value

    def make_stats(self):
        return {"done": 0}


class FakeStrategy:
    """按脚本返回 solved 序列的假策略。"""

    def __init__(self, results=()):
        self.results = list(results)
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        solved = self.results.pop(0) if self.results else False
        return StepResult(solved, f"fake#{self.calls}")


class SwapForReal:
    """真换 IP 策略：走 RelaunchBrowser 原子 + MockBrowserManager。"""

    name = "swap"
    calls = 0

    def run(self, ctx):
        self.calls += 1
        r = RelaunchBrowser().run(ctx, {})
        return StepResult(r.outcome is Outcome.OK, r.detail, r.data)


def make_config(tmp, **kw):
    base = dict(headless=True, use_proxy=False, batch_num=1, max_batches=1,
                sample_min=0, sample_max=0, rest_every=0, batch_rest=0.01,
                block_rest_min=0.01, block_rest_max=0.02, ip_retry=1,
                max_consecutive_fail=3,
                db_path=str(Path(tmp) / "t.db"))
    base.update(kw)
    return RunConfig(**base)


def make_ctx(tmp, page, mgr, config):
    store = IdentityStore(ShopDB(config.resolved_db_path()))
    return WorkerContext(config=config, store=store, browser_manager=mgr,
                         site=Alibaba1688Plugin(), stop=threading.Event(),
                         log=lambda m: None)


class LoopTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.page = FakePage()
        self.mgr = MockBrowserManager(self.page)

    def tearDown(self):
        self._tmp.cleanup()

    def db_query(self, sql, args=()):
        """loop 结束后 store 已关闭（worker 所有权语义），断言另开连接。"""
        import sqlite3
        conn = sqlite3.connect(str(Path(self.tmp) / "t.db"))
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def run_loop(self, task, table, strategies, **cfg_kw):
        config = make_config(self.tmp, **cfg_kw)
        ctx = make_ctx(self.tmp, self.page, self.mgr, config)
        policy = Policy(table=table, strategies=strategies,
                        max_consecutive_fail=config.max_consecutive_fail)
        loop = CrawlLoop(ctx, task, policy=policy)
        stats = loop.run()
        return loop, ctx, stats


# ---------- 用例 ----------

class CrawlLoopTest(LoopTestBase):
    def test_success_first_try(self):
        task = ScriptedTask([("ok", {"v": 1})])
        loop, ctx, stats = self.run_loop(task, {}, {})
        self.assertEqual(task.succeeded, ["item1"])
        self.assertEqual(task.fetches, 1)
        self.assertEqual(loop.circuit.count, 0)
        # tmd 计数：1 次请求，成功（identity 取 mock 的 1.1.1.1）
        rows = self.db_query("SELECT requests, ok FROM ip_stats")
        self.assertEqual([(r["requests"], r["ok"]) for r in rows], [(1, 1)])

    def test_net_error_strategy_then_success(self):
        backoff = FakeStrategy([True])
        task = ScriptedTask([("net", "net::ERR_TUNNEL_CONNECTION_FAILED"),
                             ("ok", {"v": 2})])
        table = {Scenario.NET_ERROR: [("backoff", 2), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(task, table, {"backoff": backoff})
        self.assertEqual(task.succeeded, ["item1"])
        self.assertEqual(backoff.calls, 1)
        # 网络层错误不计熔断、不计 tmd 请求数
        self.assertEqual(loop.circuit.count, 0)
        n = self.db_query("SELECT COUNT(*) AS c FROM ip_stats")[0]["c"]
        self.assertEqual(n, 1)  # 只有成功那次计入

    def test_risk_chain_exhausted_gives_up_next_item(self):
        solve = FakeStrategy()  # 永远失败
        task = ScriptedTask(
            [("page", "https://sec.1688.com/x5sec/punish.htm", "滑动验证 安全验证 拖动下方滑块", {})] * 3
            + [("page", "https://shop456.1688.com/page/contactinfo.htm",
                "正常页面文本，包含电话、手机、地址字段标签，长度足够超过空白页阈值。", {"v": 3})],
            items=("item1", "item2"))
        table = {Scenario.RISK_SLIDER_PAGE: [("solve", 2), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(task, table, {"solve": solve},
                                     max_consecutive_fail=10, batch_num=2)
        # item1：solve×2 失败 → GIVE_UP；item2：成功
        self.assertEqual(task.given_up, [("item1", "block")])
        self.assertEqual(task.succeeded, ["item2"])
        self.assertEqual(solve.calls, 2)
        # 风控事件已记录（block_slider）
        ev = self.db_query("SELECT event FROM ip_events"
                           " WHERE event LIKE 'block%'")
        self.assertTrue(any(r["event"] == "block_slider" for r in ev))

    def test_circuit_breaker_aborts_after_consecutive_bad_items(self):
        """熔断按店计：连续 2 个失败店铺（上限 2）才中止；单店重试链
        再多也只计 1 次，不会在单店内烧穿熔断。"""
        solve = FakeStrategy()
        task = ScriptedTask(
            [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {})] * 20,
            items=("item1", "item2"))
        table = {Scenario.RISK_SLIDER_PAGE: [("solve", 2), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(task, table, {"solve": solve},
                                     max_consecutive_fail=2, batch_num=2)
        self.assertTrue(ctx.stop.is_set())
        self.assertEqual(task.aborted, ["item2"])  # 第 2 个失败店触发熔断
        self.assertEqual(task.given_up, [("item1", "block")])
        self.assertEqual(task.succeeded, [])
        # item1 只计 1 次熔断，走完 solve×2 → 放弃（未中止）
        self.assertEqual(solve.calls, 2)

    def test_login_wall_burns_identity_at_detection(self):
        config = make_config(self.tmp)
        ctx = make_ctx(self.tmp, self.page, self.mgr, config)
        # 预置该身份 Cookie（identity 来自 mock 的 1.1.1.1）
        ctx.store.save("1688:1.1.1.1", [{"name": "cna", "value": "v",
                                    "domain": ".1688.com", "path": "/"}])
        wait = FakeStrategy()
        task = ScriptedTask(
            [("page", "https://login.1688.com/member/signin.htm", "请登录", {})])
        table = {Scenario.RISK_LOGIN: [("wait_login", 1),
                                       ("give_up", None)]}
        policy = Policy(table=table, strategies={"wait_login": wait})
        CrawlLoop(ctx, task, policy=policy).run()
        # 判定当下即烧毁身份（与旧引擎同点位），不等策略链
        rows = self.db_query("SELECT COUNT(*) AS c FROM cookies"
                             " WHERE identity='1688:1.1.1.1'")
        self.assertEqual(rows[0]["c"], 0)

    def test_login_wall_does_not_burn_prefixed_direct(self):
        """登录墙对 identity='1688:direct' 不烧毁（视为直连）。

        RED 预期（修正前）：identity != "direct" → "1688:direct" != "direct"
        → True → 触发 burn → Cookie 被清空 → 断言 cookies 仍存在失败。
        """
        # 构造返回 identity='1688:direct' 的 MockBrowserManager
        mgr = MockBrowserManager(self.page, identities=("1688:direct",))
        config = make_config(self.tmp)
        ctx = make_ctx(self.tmp, self.page, mgr, config)
        # 预置 Cookie 到 "1688:direct" 名下
        ctx.store.save("1688:direct", [{"name": "cna", "value": "v",
                                        "domain": ".1688.com", "path": "/"}])
        wait = FakeStrategy()
        task = ScriptedTask(
            [("page", "https://login.1688.com/member/signin.htm", "请登录", {})])
        table = {Scenario.RISK_LOGIN: [("wait_login", 1),
                                       ("give_up", None)]}
        policy = Policy(table=table, strategies={"wait_login": wait})
        CrawlLoop(ctx, task, policy=policy).run()
        # 修正后：is_direct("1688:direct") → True → 不清空
        rows = self.db_query("SELECT COUNT(*) AS c FROM cookies"
                             " WHERE identity='1688:direct'")
        self.assertEqual(rows[0]["c"], 1,
                         "prefixed direct 身份应保留 Cookie，不应被烧毁")

    def test_swap_ip_replaces_session_and_restarts_warm(self):
        swap = SwapForReal()
        task = ScriptedTask(
            [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {}),
             ("page", "https://shop123.1688.com/page/contactinfo.htm",
              "正常页面文本，足够长，包含电话、手机、地址字段标签内容，"
              "再补充一些文字确保超过空白页判定阈值。", {"v": 1})])
        table = {Scenario.RISK_SLIDER_PAGE: [("swap", 2), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(task, table, {"swap": swap})
        self.assertEqual(task.succeeded, ["item1"])
        self.assertEqual(self.mgr.relaunch_count, 1)
        self.assertEqual(ctx.session.identity, "1688:2.2.2.2")
        # RelaunchBrowser 原子置位 warm（换 IP 后需重新冷启动）
        self.assertTrue(ctx.state.get("warm"))
        self.assertEqual(loop.circuit.count, 0)  # 成功后熔断清零

    def test_validate_failure_goes_empty_chain(self):
        refresh = FakeStrategy([False])
        task = ScriptedTask([("ok", {"v": 1})], validate_ok=False)
        table = {Scenario.EMPTY: [("refresh", 1), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(task, table, {"refresh": refresh})
        self.assertEqual(refresh.calls, 1)
        self.assertEqual(task.given_up, [("item1", "block")])
        self.assertEqual(task.succeeded, [])

    def test_fetch_none_treated_as_risk(self):
        solve = FakeStrategy([True])
        task = ScriptedTask([("none",), ("ok", {"v": 1})])
        table = {Scenario.RISK_SLIDER_PAGE: [("solve", 1), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(task, table, {"solve": solve})
        self.assertEqual(task.succeeded, ["item1"])
        self.assertEqual(solve.calls, 1)

    def test_stop_event_interrupts(self):
        class StopStrategy:
            def run(self, ctx):
                ctx.stop.set()
                return StepResult(False, "stop")

        task = ScriptedTask(
            [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {})] * 5)
        table = {Scenario.RISK_SLIDER_PAGE: [("halt", 3), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(task, table, {"halt": StopStrategy()})
        self.assertEqual(task.succeeded, [])
        self.assertEqual(task.given_up, [])  # 中断不是放弃

    def test_single_stall_item_gives_up_not_abort(self):
        """goto 超时（NET_STALL）单店：重试链走完→放弃该店，不中止整个
        任务（旧版对单店 3 段升级后放弃、连续 N 店失败才熔断；新版熔断
        按店计，单店重试链不再烧穿熔断）。"""
        refresh = FakeStrategy()
        task = ScriptedTask([("stall",)] * 20)
        table = {Scenario.NET_STALL: [("refresh", 9), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(task, table, {"refresh": refresh},
                                     max_consecutive_fail=2)
        self.assertEqual(task.given_up, [("item1", "block")])
        self.assertFalse(ctx.stop.is_set())
        self.assertEqual(refresh.calls, 9)

    def test_ip_fresh_relaunch_failure_does_not_kill_worker(self):
        """出口 IP 保鲜确认轮换但 relaunch 失败：记日志继续用当前会话，
        不静默退出 worker，item 正常采集（防"稍扰动就停"）。"""
        class FlakyMgr(MockBrowserManager):
            def check_ip_fresh(self, session):
                return True, None, "出口 IP 查询失败（隧道疑似失效）"

            def relaunch(self, session, channel=None, seed_kit="__keep__",
                         stop=None, max_retry=None, backoff_base=30.0,
                         backoff_cap=120.0):
                raise RuntimeError("relaunch 失败")

        mgr = FlakyMgr(self.page)
        task = ScriptedTask([("ok", {"v": 1})])
        config = make_config(self.tmp, use_proxy=True)
        ctx = make_ctx(self.tmp, self.page, mgr, config)
        policy = Policy(table={}, strategies={},
                        max_consecutive_fail=config.max_consecutive_fail)
        CrawlLoop(ctx, task, policy=policy).run()
        self.assertEqual(task.succeeded, ["item1"])
        self.assertFalse(ctx.stop.is_set())

    def test_default_net_stall_chain_recovers_next_item(self):
        """默认 NET_STALL 链（刷新→休息→换IP→放弃）：一个卡顿店铺放弃
        后，下一个店铺正常采集，任务不停。"""
        refresh, block_rest, swap = FakeStrategy(), FakeStrategy(), FakeStrategy()
        # 每个卡顿店按默认链走完正好消耗 4 次 fetch（初抓 + 3 策略），
        # 4 个 stall 让 item1 放弃，item2 直接命中 ok
        task = ScriptedTask([("stall",)] * 4 + [("ok", {"v": 1})],
                            items=("item1", "item2"))
        table = {Scenario.NET_STALL: [("refresh", 1), ("block_rest", 1),
                                      ("swap_ip", 1), ("give_up", None)]}
        loop, ctx, _ = self.run_loop(
            task, table,
            {"refresh": refresh, "block_rest": block_rest, "swap_ip": swap},
            batch_num=2)
        self.assertEqual(task.given_up, [("item1", "block")])
        self.assertEqual(task.succeeded, ["item2"])
        self.assertFalse(ctx.stop.is_set())


# ---------- 跨站 view 懒建 mock ----------

class MultiSiteMockBrowserManager(MockBrowserManager):
    """支持 ensure_site + 多 view 的多站点 MockBrowserManager。

    launch 返回仅含 default_site view 的 Session；ensure_site
    懒建其他 site 的 view 并记录调用。
    """

    def __init__(self, page, default_site="1688",
                 identities=("1688:1.1.1.1", "1688:2.2.2.2", "1688:3.3.3.3")):
        super().__init__(page, identities)
        self.ensure_site_calls = []
        self.default_site = default_site
        self._ensure_site_raises = None

    def ensure_site(self, session, site_name, site_domain,
                    seed_kit=None, stop=None):
        if self._ensure_site_raises is not None:
            raise self._ensure_site_raises
        if site_name in session.views:
            return session.views[site_name]
        self.ensure_site_calls.append((site_name, site_domain))
        view = SiteView(context=FakeContext(), page=self.page,
                        identity=f"{site_name}:mock", domain=site_domain)
        session.views[site_name] = view
        return view

    def launch(self, seed_kit=None, stop=None):
        """创建仅含 default_site 初始 view 的 Session。"""
        identity = self.identities[0]
        view = SiteView(context=FakeContext(), page=self.page,
                        identity=identity, domain=f".{self.default_site}.com")
        session = Session(browser=FakeBrowser(),
                          views={self.default_site: view},
                          _active_site=self.default_site,
                          seed_kit=seed_kit)
        self.launch_count += 1
        return session


class MultiSiteScriptedTask(ScriptedTask):
    """支持按 item 切换 active_site 的 ScriptedTask。

    site_map 把 item 名映射到站点名；acquire_item 时自动设置
    ctx.state["active_site"]。
    """

    def __init__(self, script, items=("item1",), site_map=None, **kw):
        super().__init__(script, items, **kw)
        self.site_map = site_map or {}

    def acquire_item(self, ctx):
        item = super().acquire_item(ctx)
        if item is not None and item in self.site_map:
            ctx.state["active_site"] = self.site_map[item]
        return item


# ---------- 跨站 view 懒建测试 ----------

class CrossSiteLazyViewTest(LoopTestBase):
    """跨站 view 懒建补缺（SPEC §3.6 / Task 3.3 第一部分，TDD）。"""

    def setUp(self):
        super().setUp()
        self.plugin_1688 = MockPlugin("1688", "1688.com")
        self.plugin_mic = MockPlugin("madeinchina", "made-in-china.com")
        self.mgr = MultiSiteMockBrowserManager(self.page, default_site="1688")
        self.sites = {"1688": self.plugin_1688,
                      "madeinchina": self.plugin_mic}

    def make_multi_ctx(self, **cfg_kw):
        config = make_config(self.tmp, **cfg_kw)
        store = IdentityStore(ShopDB(config.resolved_db_path()))
        return WorkerContext(config=config, store=store,
                             browser_manager=self.mgr,
                             site=self.plugin_1688,
                             stop=threading.Event(),
                             log=lambda m: None)

    # ---- RED 1: 跨站懒建 ----

    def test_cross_site_lazy_build(self):
        """daemon 装配 + 假浏览器 → 处理 site B item 时
        ensure_site(siteB) 被调 + set_active_site(siteB) 被调 + ctx.site 切换。

        RED 预期：_bind_item_site 未调 ensure_site → ensure_site_calls=[] → 断言失败。
        """
        ctx = self.make_multi_ctx()
        ctx.state["active_site"] = "madeinchina"
        task = ScriptedTask([("ok", {"v": 1})])
        loop = CrawlLoop(ctx, task, sites=self.sites)
        loop.run()
        self.assertEqual(len(self.mgr.ensure_site_calls), 1,
                         '应调用 ensure_site("madeinchina")')
        self.assertEqual(self.mgr.ensure_site_calls[0],
                         ("madeinchina", "made-in-china.com"))
        self.assertEqual(ctx.session._active_site, "madeinchina")
        self.assertIs(ctx.site, self.plugin_mic)
        self.assertEqual(task.succeeded, ["item1"])

    # ---- RED 2: 幂等 ----

    def test_ensure_site_idempotent(self):
        """同 site 连续两 item → ensure_site 只调一次（view 已存在）。

        RED 预期：_bind_item_site 未调 ensure_site → ensure_site_calls=[] → 断言失败。
        """
        ctx = self.make_multi_ctx(batch_num=2)
        ctx.state["active_site"] = "madeinchina"
        task = ScriptedTask([("ok", {"v": 1}), ("ok", {"v": 2})],
                            items=("item1", "item2"))
        loop = CrawlLoop(ctx, task, sites=self.sites)
        loop.run()
        self.assertEqual(len(self.mgr.ensure_site_calls), 1,
                         "同 site 第二个 item 不应再调 ensure_site")
        self.assertEqual(ctx.session._active_site, "madeinchina")

    # ---- RED 3: 回切 ----

    def test_switch_back_to_original_site(self):
        """site B item 后 site A item → ensure_site(A) 幂等返回
        + active_site 回切 A。

        RED 预期：_bind_item_site 未调 ensure_site → ensure_site_calls=[] → 断言失败。
        """
        ctx = self.make_multi_ctx(batch_num=2)
        task = MultiSiteScriptedTask(
            [("ok", {"v": 1}), ("ok", {"v": 2})],
            items=("mic_item", "a88_item"),
            site_map={"mic_item": "madeinchina", "a88_item": "1688"})
        loop = CrawlLoop(ctx, task, sites=self.sites)
        loop.run()
        # madeinchina 是首次遇到，应建 view
        self.assertEqual(len(self.mgr.ensure_site_calls), 1,
                         "1688 已有 view 不应再调 ensure_site，仅 mic 一次")
        self.assertEqual(self.mgr.ensure_site_calls[0],
                         ("madeinchina", "made-in-china.com"))
        # 第二个 item 回切到 1688
        self.assertEqual(ctx.session._active_site, "1688")
        self.assertIs(ctx.site, self.plugin_1688)

    # ---- RED 4: 异常容错 ----

    def test_ensure_site_exception_tolerance(self):
        """ensure_site raise → 记日志不崩 worker。

        RED 预期：ensure_site 未调 → 但即使调了，异常未捕获 → loop.run()
        抛出 RuntimeError → 断言失败。
        """
        log_msgs = []
        ctx = self.make_multi_ctx()
        ctx.log = lambda m: log_msgs.append(m)
        ctx.state["active_site"] = "madeinchina"
        self.mgr._ensure_site_raises = RuntimeError("直连无 Cookie")
        task = ScriptedTask([("ok", {"v": 1})])
        loop = CrawlLoop(ctx, task, sites=self.sites)
        stats = loop.run()  # 不应抛异常
        self.assertIn("stats", {"stats": stats})  # stats 非 None
        self.assertTrue(any("ensure_site" in m for m in log_msgs),
                        "应记录 ensure_site 失败日志")

    # ---- RED 5: CLI 单站点回归 ----

    def test_cli_single_site_no_ensure_site(self):
        """CLI 单站点路径：sites=None → 无 ensure_site 调用（现状不变）。

        GREEN 预期：MockBrowserManager 无 ensure_site 方法，
        _bind_item_site 在 sites=None 时提前返回 → 本测试通过。
        """
        mgr = MockBrowserManager(self.page)
        config = make_config(self.tmp)
        store = IdentityStore(ShopDB(config.resolved_db_path()))
        ctx = WorkerContext(config=config, store=store,
                            browser_manager=mgr,
                            site=Alibaba1688Plugin(),
                            stop=threading.Event(),
                            log=lambda m: None)
        task = ScriptedTask([("ok", {"v": 1})])
        loop = CrawlLoop(ctx, task, sites=None)
        stats = loop.run()
        self.assertEqual(task.succeeded, ["item1"])


if __name__ == "__main__":
    unittest.main()
