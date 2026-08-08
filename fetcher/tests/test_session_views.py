# -*- coding: utf-8 -*-
"""Task 2.1: Session/SiteView 重构 TDD 测试。

覆盖：路由规则、C2 隔离、ensure_site 懒建、close_site 回写过滤、
close 两层、relaunch 全 view 回写、单站点等价。
"""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

from fetcher.core.session import Session, SiteView, bare_identity, is_direct
from fetcher.net.identity import IdentityStore
from fetcher.db import ShopDB


NOW = 1690000000  # 固定时间戳，避免时区差异


def ck(name, value="v", domain=".1688.com", expires=None):
    c = {"name": name, "value": value, "domain": domain, "path": "/",
         "secure": False, "httpOnly": False}
    if expires is not None:
        c["expires"] = expires
    return c


class FakeBrowserContext:
    """模拟 Playwright BrowserContext（独立 cookies 存储）。"""

    def __init__(self, cookies=None):
        self._cookies = list(cookies) if cookies else []

    def cookies(self):
        return list(self._cookies)

    def add_cookies(self, cookies):
        for c in cookies:
            # 去重覆盖
            existing = [i for i, ec in enumerate(self._cookies)
                        if ec["name"] == c["name"] and ec.get("domain") == c.get("domain")]
            for idx in reversed(existing):
                self._cookies.pop(idx)
            self._cookies.append(dict(c))

    def new_page(self):
        return MagicMock()


class FakeBrowser:
    """模拟 Playwright Browser。"""

    def __init__(self):
        self._contexts = []
        self._closed = False

    def new_context(self, **kwargs):
        ctx = FakeBrowserContext()
        self._contexts.append(ctx)
        return ctx

    def close(self):
        self._closed = True


# ============================================================
# 1. 路由规则
# ============================================================

class SessionRoutingTest(unittest.TestCase):
    """page / ctx / identity 按 _active_site 路由。"""

    def setUp(self):
        self.ctx1 = FakeBrowserContext([ck("cna", "v1")])
        self.ctx2 = FakeBrowserContext([ck("cna", "v2")])
        self.view_1688 = SiteView(
            context=self.ctx1,
            page=MagicMock(),
            identity="1688:1.2.3.4",
            domain="1688.com",
        )
        self.view_yiwugo = SiteView(
            context=self.ctx2,
            page=MagicMock(),
            identity="yiwugo:5.5.5.5",
            domain="yiwugo.com",
        )
        self.session = Session(
            browser=MagicMock(),
            views={"1688": self.view_1688, "yiwugo": self.view_yiwugo},
            _active_site="1688",
        )

    def test_active_site_routes_page(self):
        """_active_site='1688' → page 返回 views['1688'].page"""
        self.assertIs(self.session.page, self.view_1688.page)

    def test_active_site_routes_ctx(self):
        """_active_site='1688' → ctx 返回 views['1688'].context"""
        self.assertIs(self.session.ctx, self.view_1688.context)

    def test_active_site_routes_identity(self):
        """_active_site='1688' → identity 返回 views['1688'].identity"""
        self.assertEqual(self.session.identity, "1688:1.2.3.4")

    def test_set_active_site_changes_routing(self):
        """set_active_site('yiwugo') → page/ctx/identity 切到 yiwugo"""
        self.session.set_active_site("yiwugo")
        self.assertIs(self.session.page, self.view_yiwugo.page)
        self.assertIs(self.session.ctx, self.view_yiwugo.context)
        self.assertEqual(self.session.identity, "yiwugo:5.5.5.5")

    def test_no_active_site_falls_back_to_sole_view(self):
        """未设 _active_site 但仅一个 view → 回落该 view"""
        session = Session(
            browser=MagicMock(),
            views={"1688": self.view_1688},
        )
        self.assertIs(session.page, self.view_1688.page)
        self.assertIs(session.ctx, self.view_1688.context)
        self.assertEqual(session.identity, "1688:1.2.3.4")

    def test_two_views_no_active_returns_none_page(self):
        """两 view 无 active → page 返回 None"""
        session = Session(
            browser=MagicMock(),
            views={"1688": self.view_1688, "yiwugo": self.view_yiwugo},
        )
        self.assertIsNone(session.page)
        self.assertIsNone(session.ctx)
        self.assertEqual(session.identity, "")

    def test_active_site_not_in_views_returns_none(self):
        """_active_site 指向不存在的 site → 回退 None（不抛异常）"""
        session = Session(
            browser=MagicMock(),
            views={"1688": self.view_1688},
            _active_site="nonexistent",
        )
        self.assertIsNone(session.page)

    def test_empty_views_returns_none(self):
        """无任何 view → 所有路由返回 None/空"""
        session = Session(browser=MagicMock())
        self.assertIsNone(session.page)
        self.assertIsNone(session.ctx)
        self.assertEqual(session.identity, "")

    def test_set_active_site_nonexistent_raises(self):
        """set_active_site 到不在 views 中的 site → ValueError"""
        session = Session(
            browser=MagicMock(),
            views={"1688": self.view_1688},
        )
        with self.assertRaises(ValueError):
            session.set_active_site("nonexistent")


# ============================================================
# 2. C2 隔离：同 browser 两 context Cookie 互不可见
# ============================================================

class C2ContextIsolationTest(unittest.TestCase):
    """SPEC C2: 同一 browser 进程下两个 BrowserContext 的 Cookie 隔离。"""

    def test_two_contexts_cookie_isolation(self):
        """context A set cookie → context B 读不到。

        使用 FakeBrowser + FakeBrowserContext 模拟隔离语义：
        每个 context 有独立的 cookies 存储，add_cookies 只影响本 context。
        """
        browser = FakeBrowser()
        ctx_a = browser.new_context()
        ctx_b = browser.new_context()

        ctx_a.add_cookies([ck("cna", "from_a", domain=".1688.com")])
        ctx_b.add_cookies([ck("cna", "from_b", domain=".1688.com")])

        # A 只能看到自己的
        a_names = {c["value"] for c in ctx_a.cookies()}
        self.assertEqual(a_names, {"from_a"})

        # B 只能看到自己的
        b_names = {c["value"] for c in ctx_b.cookies()}
        self.assertEqual(b_names, {"from_b"})

    def test_two_contexts_share_no_state(self):
        """context A 的操作不影响 B 的 cookies 列表。"""
        browser = FakeBrowser()
        ctx_a = browser.new_context()
        ctx_b = browser.new_context()

        self.assertEqual(len(ctx_a.cookies()), 0)
        self.assertEqual(len(ctx_b.cookies()), 0)

        ctx_a.add_cookies([ck("x", "1"), ck("y", "2")])
        self.assertEqual(len(ctx_a.cookies()), 2)
        self.assertEqual(len(ctx_b.cookies()), 0,
                         "context B 不应受 context A 的 add_cookies 影响")


# ============================================================
# 3. ensure_site 懒建
# ============================================================

class EnsureSiteTest(unittest.TestCase):
    """BrowserManager.ensure_site 懒建逻辑。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = ShopDB(self.db_path)
        self.store = IdentityStore(self.db, domain="1688.com")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _make_mgr(self, config=None, site_name="1688"):
        from fetcher.core.context import RunConfig
        from fetcher.net.browser import BrowserManager
        if config is None:
            config = RunConfig(headless=True, use_proxy=False,
                               db_path=str(self.db_path))
        return BrowserManager(
            config=config, store=self.store, log=lambda m: None,
            site_name=site_name)

    def test_ensure_site_creates_new_view(self):
        """ensure_site 对不存在的 site 懒建 view。"""
        mgr = self._make_mgr()
        browser = FakeBrowser()
        session = Session(browser=browser)

        view = mgr.ensure_site(session, "1688", "1688.com")
        self.assertIsInstance(view, SiteView)
        self.assertIn("1688", session.views)
        self.assertEqual(view.identity, "1688:direct")
        self.assertEqual(view.domain, "1688.com")

    def test_ensure_site_no_recreate_for_existing(self):
        """已存在 view 不重建（不调用 browser.new_context）。"""
        mgr = self._make_mgr()
        browser = MagicMock()
        # 让 browser.new_context 可追踪调用次数
        ctx = FakeBrowserContext()
        browser.new_context.return_value = ctx

        session = Session(browser=browser)
        v1 = mgr.ensure_site(session, "1688", "1688.com")

        # 第二次调用：不应再调 new_context
        v2 = mgr.ensure_site(session, "1688", "1688.com")
        self.assertIs(v1, v2, "同一 site 应返回同一 view")
        # new_context 只应调用一次
        self.assertEqual(browser.new_context.call_count, 1,
                         f"已存在 view 不应重建，实际调用了 {browser.new_context.call_count} 次")

    def test_ensure_site_multi_site_creates_separate_views(self):
        """两个不同 site 各建独立 view，互不干扰。"""
        mgr = self._make_mgr()
        browser = FakeBrowser()
        session = Session(browser=browser)

        v_1688 = mgr.ensure_site(session, "1688", "1688.com")
        v_yiwugo = mgr.ensure_site(session, "yiwugo", "yiwugo.com")

        self.assertIsNot(v_1688, v_yiwugo)
        self.assertEqual(len(session.views), 2)
        self.assertEqual(v_1688.identity, "1688:direct")
        self.assertEqual(v_yiwugo.identity, "yiwugo:direct")
        self.assertEqual(v_1688.domain, "1688.com")
        self.assertEqual(v_yiwugo.domain, "yiwugo.com")

    def test_ensure_site_uses_store_domain(self):
        """ensure_site 传入的 site_domain 写入 view.domain。"""
        mgr = self._make_mgr()
        browser = FakeBrowser()
        session = Session(browser=browser)

        view = mgr.ensure_site(session, "1688", "1688.com")
        self.assertEqual(view.domain, "1688.com")


# ============================================================
# 4. close_site 回写过滤
# ============================================================

class CloseSiteFilterTest(unittest.TestCase):
    """Session.close_site: 按 view.domain 过滤回写。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = ShopDB(self.db_path)
        self.store = IdentityStore(self.db, domain="1688.com")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_close_site_filters_by_view_domain(self):
        """view.domain='1688.com' → 只存 1688 域 Cookie，排除 taobao.com。"""
        ctx = FakeBrowserContext([
            ck("cna", domain=".1688.com"),
            ck("_tb_", domain=".taobao.com"),
        ])
        view = SiteView(
            context=ctx,
            page=MagicMock(),
            identity="1688:1.2.3.4",
            domain="1688.com",
        )
        session = Session(
            browser=MagicMock(),
            views={"1688": view},
        )
        session.close_site("1688", store=self.store)
        loaded = self.store.load("1688:1.2.3.4")
        self.assertEqual(len(loaded), 1,
                         f"应只存 1688 域 Cookie，实际={loaded}")
        self.assertEqual(loaded[0]["name"], "cna")

    def test_close_site_multi_view_each_filters_own_domain(self):
        """两 view 各回写各域，不串站。"""
        ctx_1688 = FakeBrowserContext([
            ck("cna", domain=".1688.com"),
            ck("_tb_", domain=".taobao.com"),
        ])
        ctx_mic = FakeBrowserContext([
            ck("q", domain=".made-in-china.com"),
            ck("cna", domain=".mmstat.com"),
        ])
        store_mic = IdentityStore(self.db, domain="made-in-china.com")

        session = Session(
            browser=MagicMock(),
            views={
                "1688": SiteView(context=ctx_1688, page=MagicMock(),
                                 identity="1688:1.2.3.4", domain="1688.com"),
                "madeinchina": SiteView(context=ctx_mic, page=MagicMock(),
                                        identity="madeinchina:5.5.5.5",
                                        domain="made-in-china.com"),
            },
        )
        session.close_site("1688", store=self.store)
        session.close_site("madeinchina", store=store_mic)

        loaded_1688 = self.store.load("1688:1.2.3.4")
        loaded_mic = store_mic.load("madeinchina:5.5.5.5")
        self.assertEqual(len(loaded_1688), 1)
        self.assertEqual(len(loaded_mic), 1)
        self.assertEqual(loaded_1688[0]["name"], "cna")
        self.assertEqual(loaded_mic[0]["name"], "q")

    def test_close_site_removes_view_from_session(self):
        """close_site 后 view 从 session.views 中移除。"""
        ctx = FakeBrowserContext([ck("cna")])
        view = SiteView(context=ctx, page=MagicMock(),
                        identity="1688:direct", domain="1688.com")
        session = Session(
            browser=MagicMock(),
            views={"1688": view},
            _active_site="1688",
        )
        session.close_site("1688", store=self.store)
        self.assertNotIn("1688", session.views)

    def test_close_site_clears_active_site_if_it_was_closed(self):
        """关闭的 site 恰是 active → _active_site 清空。"""
        ctx = FakeBrowserContext([ck("cna")])
        view = SiteView(context=ctx, page=MagicMock(),
                        identity="1688:direct", domain="1688.com")
        session = Session(
            browser=MagicMock(),
            views={"1688": view},
            _active_site="1688",
        )
        session.close_site("1688", store=self.store)
        self.assertIsNone(session._active_site)

    def test_close_site_nonexistent_noop(self):
        """close_site 不存在的 site 不抛异常。"""
        session = Session(browser=MagicMock())
        session.close_site("nonexistent")  # 不抛异常


# ============================================================
# 5. close 两层
# ============================================================

class CloseTwoLayerTest(unittest.TestCase):
    """Session.close: 全部 view 回写 + browser.close()。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = ShopDB(self.db_path)
        self.store_1688 = IdentityStore(self.db, domain="1688.com")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_close_calls_close_site_for_all_views(self):
        """close() 遍历所有 view 回写 Cookie。"""
        ctx_a = FakeBrowserContext([ck("cna", "a", domain=".1688.com")])
        ctx_b = FakeBrowserContext([ck("q", "b", domain=".yiwugo.com")])
        browser = MagicMock()
        session = Session(
            browser=browser,
            views={
                "1688": SiteView(context=ctx_a, page=MagicMock(),
                                 identity="1688:1.1.1.1", domain="1688.com"),
                "yiwugo": SiteView(context=ctx_b, page=MagicMock(),
                                   identity="yiwugo:2.2.2.2", domain="yiwugo.com"),
            },
        )
        session.close(store=self.store_1688)
        # 两个 view 的 Cookie 都应回写（按各自 domain 过滤）
        loaded_a = self.store_1688.load("1688:1.1.1.1")
        loaded_b = self.store_1688.load("yiwugo:2.2.2.2")
        self.assertEqual(len(loaded_a), 1)
        self.assertEqual(len(loaded_b), 1)
        self.assertEqual(loaded_a[0]["value"], "a")
        self.assertEqual(loaded_b[0]["value"], "b")

    def test_close_calls_browser_close(self):
        """close() 调用 browser.close()。"""
        browser = MagicMock()
        session = Session(
            browser=browser,
            views={
                "1688": SiteView(context=FakeBrowserContext([ck("cna")]),
                                 page=MagicMock(), identity="1688:direct",
                                 domain="1688.com"),
            },
        )
        session.close(store=self.store_1688)
        browser.close.assert_called_once()

    def test_close_preserves_views_for_inspection(self):
        """close() 后 views 保留（与旧版 close 语义一致，供调用方事后检查）。"""
        browser = MagicMock()
        session = Session(
            browser=browser,
            views={
                "1688": SiteView(context=FakeBrowserContext([ck("cna")]),
                                 page=MagicMock(), identity="1688:direct",
                                 domain="1688.com"),
            },
        )
        session.close(store=self.store_1688)
        self.assertEqual(len(session.views), 1,
                         "close() 后 views 应保留供事后检查")

    def test_close_without_store_no_cookie_write(self):
        """close(store=None) 关浏览器但不回写。"""
        browser = MagicMock()
        session = Session(
            browser=browser,
            views={
                "1688": SiteView(context=FakeBrowserContext([ck("cna")]),
                                 page=MagicMock(), identity="1688:direct",
                                 domain="1688.com"),
            },
        )
        session.close()  # store=None
        browser.close.assert_called_once()
        self.assertEqual(self.store_1688.load("1688:direct"), [])

    def test_close_no_browser_no_error(self):
        """browser=None 时 close 不抛异常。"""
        session = Session(browser=None)
        session.close()  # 不抛异常


# ============================================================
# 6. relaunch 全 view 回写
# ============================================================

class RelaunchViewsTest(unittest.TestCase):
    """BrowserManager.relaunch: 所有 view Cookie 回写后新进程。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = ShopDB(self.db_path)
        self.store = IdentityStore(self.db, domain="1688.com")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_relaunch_saves_all_view_cookies_before_new_launch(self):
        """relaunch: 两 view 的 Cookie 都回写，然后 launch 新进程。

        用 mock 验证调用顺序：先 close（回写全部 view Cookie），再 launch。
        """
        from fetcher.core.context import RunConfig
        from fetcher.net.browser import BrowserManager

        config = RunConfig(headless=True, use_proxy=False,
                           db_path=str(self.db_path),
                           ip_retry=1)
        mgr = BrowserManager(
            config=config, store=self.store, log=lambda m: None,
            site_name="1688")

        ctx_a = FakeBrowserContext([ck("cna", "a", domain=".1688.com")])
        ctx_b = FakeBrowserContext([ck("other", "b", domain=".yiwugo.com")])
        browser = MagicMock()
        session = Session(
            browser=browser,
            channel=None,
            req_proxies=None,
            seed_kit=None,
            views={
                "1688": SiteView(context=ctx_a, page=MagicMock(),
                                 identity="1688:1.1.1.1", domain="1688.com"),
                "yiwugo": SiteView(context=ctx_b, page=MagicMock(),
                                   identity="yiwugo:2.2.2.2", domain="yiwugo.com"),
            },
        )

        # mock launch to avoid actual browser startup
        new_browser = MagicMock()
        new_ctx = FakeBrowserContext()
        new_browser.new_context.return_value = new_ctx
        new_view = SiteView(context=new_ctx, page=MagicMock(),
                            identity="1688:direct", domain="1688.com")

        with patch.object(mgr, 'launch', return_value=Session(
            browser=new_browser,
            views={"1688": new_view},
        )) as mock_launch:
            new_session = mgr.relaunch(session)

        # 验证：两个 view 的 Cookie 都已回写
        loaded_a = self.store.load("1688:1.1.1.1")
        loaded_b = self.store.load("yiwugo:2.2.2.2")
        self.assertEqual(len(loaded_a), 1,
                         f"view 1688 Cookie 应已回写，实际={loaded_a}")
        self.assertEqual(len(loaded_b), 1,
                         f"view yiwugo Cookie 应已回写，实际={loaded_b}")
        self.assertEqual(loaded_a[0]["value"], "a")
        self.assertEqual(loaded_b[0]["value"], "b")
        # 验证旧 browser 已 close
        browser.close.assert_called_once()
        # 验证 launch 被调用
        mock_launch.assert_called_once()


# ============================================================
# 7. 单站点等价：CLI 路径行为与旧结构一致
# ============================================================

class SingleSiteEquivalenceTest(unittest.TestCase):
    """单站点路径：Session 路由、identity、close 行为与旧结构等价。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = ShopDB(self.db_path)
        self.store = IdentityStore(self.db, domain="1688.com")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_single_view_identity_equals_old_format(self):
        """单 view 的 identity 与旧 Session.identity 格式一致。"""
        ctx = FakeBrowserContext([ck("cna")])
        view = SiteView(context=ctx, page=MagicMock(),
                        identity="1688:1.2.3.4", domain="1688.com")
        session = Session(
            browser=MagicMock(),
            views={"1688": view},
        )
        # 旧代码: session.identity → "1688:1.2.3.4"
        # 新代码: session.identity → 路由到唯一 view 的 identity
        self.assertEqual(session.identity, "1688:1.2.3.4")

    def test_single_view_page_routing(self):
        """单 view page 路由返回该 view 的 page。"""
        page = MagicMock()
        ctx = FakeBrowserContext()
        view = SiteView(context=ctx, page=page,
                        identity="1688:direct", domain="1688.com")
        session = Session(
            browser=MagicMock(),
            views={"1688": view},
        )
        self.assertIs(session.page, page)
        self.assertIs(session.ctx, ctx)

    def test_single_view_close_behavior_equivalent(self):
        """单 view close 行为：回写 Cookie + browser.close()。"""
        ctx = FakeBrowserContext([ck("cna")])
        browser = MagicMock()
        view = SiteView(context=ctx, page=MagicMock(),
                        identity="1688:1.2.3.4", domain="1688.com")
        session = Session(
            browser=browser,
            views={"1688": view},
        )
        session.close(store=self.store)

        loaded = self.store.load("1688:1.2.3.4")
        self.assertEqual(len(loaded), 1)
        browser.close.assert_called_once()

    def test_direct_single_view_identity(self):
        """直连单 view identity 格式 'site:direct'。"""
        ctx = FakeBrowserContext()
        view = SiteView(context=ctx, page=MagicMock(),
                        identity="1688:direct", domain="1688.com")
        session = Session(
            browser=MagicMock(),
            views={"1688": view},
        )
        self.assertEqual(session.identity, "1688:direct")

    def test_set_active_site_on_single_view(self):
        """单 view 下 set_active_site 正常工作。"""
        ctx = FakeBrowserContext()
        view = SiteView(context=ctx, page=MagicMock(),
                        identity="1688:direct", domain="1688.com")
        session = Session(
            browser=MagicMock(),
            views={"1688": view},
        )
        session.set_active_site("1688")
        self.assertEqual(session._active_site, "1688")
        self.assertIs(session.page, view.page)


# ============================================================
# 回归：旧属性/方法保持兼容
# ============================================================

class SessionCompatibilityTest(unittest.TestCase):
    """Session 旧属性/方法保持向后兼容。"""

    def test_use_proxy_property(self):
        """use_proxy property 保持 channel 判断逻辑。"""
        session = Session(browser=MagicMock())
        self.assertFalse(session.use_proxy)

        mock_channel = MagicMock()
        mock_channel.server = "10.0.0.1:8080"
        session2 = Session(browser=MagicMock(), channel=mock_channel)
        self.assertTrue(session2.use_proxy)

    def test_bare_identity_module_functions_unchanged(self):
        """bare_identity / is_direct 模块级函数不变。"""
        self.assertEqual(bare_identity("1688:1.2.3.4"), "1.2.3.4")
        self.assertEqual(bare_identity("direct"), "direct")
        self.assertTrue(is_direct("1688:direct"))
        self.assertTrue(is_direct("direct"))
        self.assertFalse(is_direct("1.2.3.4"))

    def test_seed_kit_process_level_preserved(self):
        """Session.seed_kit 进程级种子保留。"""
        kit = {"name": "test_seed", "cookies": [ck("cna")], "x5sec": None}
        session = Session(browser=MagicMock(), seed_kit=kit)
        self.assertEqual(session.seed_kit, kit)

    def test_extra_field_preserved(self):
        """extra dict 保留。"""
        session = Session(browser=MagicMock(), extra={"foo": "bar"})
        self.assertEqual(session.extra, {"foo": "bar"})


# ============================================================
# IdentityStore.save_from_context domain 参数
# ============================================================

class SaveFromContextDomainTest(unittest.TestCase):
    """save_from_context 新增 domain 参数。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = ShopDB(self.db_path)
        self.store = IdentityStore(self.db, domain="1688.com")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_explicit_domain_filters_per_view(self):
        """传入 domain='yiwugo.com' 时按 yiwugo.com 过滤。"""
        ctx = FakeBrowserContext([
            ck("cna", domain=".1688.com"),
            ck("q", domain=".yiwugo.com"),
        ])
        n = self.store.save_from_context("test:1.2.3.4", ctx, log=lambda m: None,
                                         domain="yiwugo.com")
        self.assertEqual(n, 1)
        loaded = self.store.load("test:1.2.3.4")
        self.assertEqual(loaded[0]["name"], "q")

    def test_no_domain_falls_back_to_store_domain(self):
        """不传 domain → 回落 store.domain（旧行为）。"""
        ctx = FakeBrowserContext([
            ck("cna", domain=".1688.com"),
            ck("_tb_", domain=".taobao.com"),
        ])
        n = self.store.save_from_context("test:1.2.3.4", ctx, log=lambda m: None)
        self.assertEqual(n, 1)
        loaded = self.store.load("test:1.2.3.4")
        self.assertEqual(loaded[0]["name"], "cna")


if __name__ == "__main__":
    unittest.main()
