# -*- coding: utf-8 -*-
"""Step 1.4 冒烟前置修复：匿名站点（facebook）直连模式无 Cookie 白板启动。

背景（SPEC §7.2 假设修正）：ensure_site 的「无 Cookie 且无种子 kit →
空 context + warmup 现场签发」白板路径只在 use_proxy=True 分支生效；
直连模式无 Cookie 会硬 raise（browser.py "identity=... 下没有可用
Cookie"）。FB 匿名抓取按设计不带 Cookie（SPEC §7.2），需为匿名站点放行
直连空会话白板。非匿名站点行为零变化。
"""

import unittest
from unittest.mock import MagicMock

from fetcher import RunConfig
from fetcher.core.session import Session
from fetcher.net.browser import BrowserManager, _site_cookie_optional
from fetcher.sites.facebook import FacebookPlugin


class SiteCookieOptionalTest(unittest.TestCase):
    def test_facebook_is_anonymous(self):
        self.assertTrue(FacebookPlugin.anonymous)

    def test_facebook_cookie_optional(self):
        self.assertTrue(_site_cookie_optional("facebook"))

    def test_1688_not_cookie_optional(self):
        self.assertFalse(_site_cookie_optional("1688"))

    def test_unknown_site_not_cookie_optional(self):
        self.assertFalse(_site_cookie_optional("no_such_site"))


class EnsureSiteAnonymousTest(unittest.TestCase):
    """ensure_site 匿名直连白板：无 Cookie 不 raise、不注入 Cookie。"""

    def _mgr(self, site_name):
        mgr = BrowserManager(
            config=RunConfig(headless=True, use_proxy=False),
            store=MagicMock(), log=lambda m: None, site_name=site_name)
        mgr.store.load.return_value = []
        return mgr

    def _session(self):
        session = Session(identity="facebook:direct")
        session.browser = MagicMock()
        ctx = MagicMock()
        page = MagicMock()
        session.browser.new_context.return_value = ctx
        ctx.new_page.return_value = page
        return session, ctx

    def test_anonymous_direct_no_cookies_launches(self):
        """facebook + 直连 + 无 Cookie → 不 raise，白板空会话启动。"""
        mgr = self._mgr("facebook")
        session, ctx = self._session()
        view = mgr.ensure_site(session, "facebook", "facebook.com")
        self.assertIsNotNone(view)
        session.browser.new_context.assert_called_once()
        ctx.add_cookies.assert_not_called()  # 匿名不注入 Cookie

    def test_non_anonymous_direct_no_cookies_raises(self):
        """1688 + 直连 + 无 Cookie → 仍 raise（既有行为不回归）。"""
        from fetcher.core.errors import BrowserLaunchError
        mgr = self._mgr("1688")
        session, _ = self._session()
        with self.assertRaises(BrowserLaunchError):
            mgr.ensure_site(session, "1688", "1688.com")


if __name__ == "__main__":
    unittest.main()
