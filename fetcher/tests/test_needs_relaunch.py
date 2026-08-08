# -*- coding: utf-8 -*-
"""Task 2.2: needs_relaunch 状态位机制 TDD 测试。

覆盖：mark_needs_relaunch 置位/清除、ensure_site 懒建消费、
多 site 只 relaunch 一次（进程级）、未置位时正常懒建。
"""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

from fetcher.core.session import Session, SiteView
from fetcher.net.identity import IdentityStore
from fetcher.db import ShopDB


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
# 1. mark_needs_relaunch 置位 / relaunch 完成清除
# ============================================================

class MarkNeedsRelaunchTest(unittest.TestCase):
    """mark_needs_relaunch 置位 / relaunch 完成清除。"""

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

    def test_mark_needs_relaunch_sets_flag_in_extra(self):
        """mark_needs_relaunch 在 session.extra['needs_relaunch'] 置位。"""
        mgr = self._make_mgr()
        session = Session(browser=MagicMock())
        mgr.mark_needs_relaunch(session, "1688")
        self.assertIn("needs_relaunch", session.extra)
        self.assertTrue(session.extra["needs_relaunch"].get("1688"))

    def test_mark_needs_relaunch_multiple_sites(self):
        """多个 site 各自独立置位。"""
        mgr = self._make_mgr()
        session = Session(browser=MagicMock())
        mgr.mark_needs_relaunch(session, "1688")
        mgr.mark_needs_relaunch(session, "yiwugo")
        self.assertTrue(session.extra["needs_relaunch"].get("1688"))
        self.assertTrue(session.extra["needs_relaunch"].get("yiwugo"))

    def test_clear_needs_relaunch_removes_single_site_flag(self):
        """clear_needs_relaunch(session, site) 精确清除单个 site 标记。"""
        mgr = self._make_mgr()
        session = Session(browser=MagicMock(),
                          extra={"needs_relaunch": {"1688": True, "yiwugo": True}})
        mgr.clear_needs_relaunch(session, "1688")
        self.assertNotIn("1688", session.extra.get("needs_relaunch", {}))
        # 其他 site 标记保留
        self.assertIn("yiwugo", session.extra.get("needs_relaunch", {}))


# ============================================================
# 2. ensure_site 懒建消费：needs_relaunch 触发完整 relaunch
# ============================================================

class EnsureSiteRelaunchConsumeTest(unittest.TestCase):
    """ensure_site 检测到 needs_relaunch → 触发完整 relaunch。"""

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
                               db_path=str(self.db_path), ip_retry=1)
        return BrowserManager(
            config=config, store=self.store, log=lambda m: None,
            site_name=site_name)

    def test_ensure_site_triggers_relaunch_when_needs_relaunch_set(self):
        """ensure_site: needs_relaunch[site] 置位 → 触发完整 relaunch
        （browser.close 一次 + 新 launch 一次）且清除标记。

        注意：测试中 session.views 不含 site_name（模拟懒建入口），
        否则 ensure_site 会走已存在 view 的短路返回。
        """
        mgr = self._make_mgr()
        old_browser = MagicMock()
        # 有一个 other_site 的 view（模拟已有其他站点），但 1688 不在 views 中
        session = Session(
            browser=old_browser,
            views={
                "other_site": SiteView(context=FakeBrowserContext([ck("cna", "old")]),
                                       page=MagicMock(), identity="other:direct",
                                       domain="other.com"),
            },
            extra={"needs_relaunch": {"1688": True}},
        )

        # Mock launch to return a new session with the requested view
        new_browser = MagicMock()
        new_ctx = FakeBrowserContext([ck("cna", "new")])
        new_browser.new_context.return_value = new_ctx
        new_session = Session(
            browser=new_browser,
            views={
                "1688": SiteView(context=new_ctx, page=MagicMock(),
                                 identity="1688:direct", domain="1688.com"),
            },
        )

        with patch.object(mgr, 'launch', return_value=new_session) as mock_launch:
            view = mgr.ensure_site(session, "1688", "1688.com")

        # 验证：旧 browser 已 close
        old_browser.close.assert_called_once()
        # 验证：launch 被调用一次（新进程）
        mock_launch.assert_called_once()
        # 验证：返回新 view
        self.assertIsNotNone(view)
        # 验证：needs_relaunch 已清除
        self.assertNotIn("1688", session.extra.get("needs_relaunch", {}))
        # 验证：新 session 状态已迁移（session 引用不变，但内部更新）
        self.assertIs(session.browser, new_browser)

    def test_ensure_site_no_relaunch_when_flag_not_set(self):
        """未置位 needs_relaunch → 正常懒建，不触发 relaunch。"""
        mgr = self._make_mgr()
        browser = FakeBrowser()
        session = Session(browser=browser)

        # 不设 needs_relaunch 标志
        view = mgr.ensure_site(session, "1688", "1688.com")

        self.assertIsInstance(view, SiteView)
        self.assertIn("1688", session.views)
        # browser 未被 close
        self.assertFalse(browser._closed,
                         "未置位时不应 close browser")

    def test_ensure_site_no_relaunch_when_flag_for_other_site(self):
        """needs_relaunch 只标记了其他 site → 本站正常懒建。"""
        mgr = self._make_mgr()
        browser = FakeBrowser()
        session = Session(
            browser=browser,
            extra={"needs_relaunch": {"yiwugo": True}},
        )

        view = mgr.ensure_site(session, "1688", "1688.com")

        self.assertIsInstance(view, SiteView)
        self.assertIn("1688", session.views)
        self.assertFalse(browser._closed)
        # yiwugo 的标记仍保留（等 yiwugo 被认领时触发自己的 relaunch）
        self.assertTrue(session.extra.get("needs_relaunch", {}).get("yiwugo"))

    def test_ensure_site_relaunch_clears_all_site_flags(self):
        """多 site 场景：relaunch 是进程级，一次 relaunch 清除全部 site 标记。"""
        mgr = self._make_mgr()
        old_browser = MagicMock()
        session = Session(
            browser=old_browser,
            extra={"needs_relaunch": {"1688": True, "yiwugo": True}},
        )

        new_browser = MagicMock()
        new_ctx = FakeBrowserContext([ck("cna", "new")])
        new_browser.new_context.return_value = new_ctx
        new_session = Session(
            browser=new_browser,
            views={
                "1688": SiteView(context=new_ctx, page=MagicMock(),
                                 identity="1688:direct", domain="1688.com"),
            },
        )

        with patch.object(mgr, 'launch', return_value=new_session) as mock_launch:
            mgr.ensure_site(session, "1688", "1688.com")

        # relaunch 一次
        mock_launch.assert_called_once()
        # 全部 site 的 needs_relaunch 都清除
        nr = session.extra.get("needs_relaunch", {})
        self.assertEqual(nr, {}, f"全部 needs_relaunch 应清除，实际={nr}")

    def test_ensure_site_relaunch_writes_back_all_views_before_close(self):
        """ensure_site 触发 relaunch 前：全部现有 view 的 Cookie 回写。

        注意：测试中 session.views 不含 1688（模拟懒建入口），但含
        yiwugo（模拟已有其他站点），验证 relaunch 对所有现有 view 回写。
        """
        mgr = self._make_mgr()
        ctx_yiwugo = FakeBrowserContext([ck("q", "v2", domain=".yiwugo.com")])
        old_browser = MagicMock()
        session = Session(
            browser=old_browser,
            views={
                "yiwugo": SiteView(context=ctx_yiwugo, page=MagicMock(),
                                   identity="yiwugo:direct", domain="yiwugo.com"),
            },
            extra={"needs_relaunch": {"1688": True}},
        )

        new_browser = MagicMock()
        new_ctx = FakeBrowserContext()
        new_browser.new_context.return_value = new_ctx
        new_session = Session(
            browser=new_browser,
            views={
                "1688": SiteView(context=new_ctx, page=MagicMock(),
                                 identity="1688:direct", domain="1688.com"),
            },
        )

        with patch.object(mgr, 'launch', return_value=new_session):
            mgr.ensure_site(session, "1688", "1688.com")

        # yiwugo view 的 Cookie 应已回写
        loaded_yiwugo = self.store.load("yiwugo:direct")
        self.assertEqual(len(loaded_yiwugo), 1, f"yiwugo Cookie 应已回写，实际={loaded_yiwugo}")
        self.assertEqual(loaded_yiwugo[0]["value"], "v2")

    def test_ensure_site_relaunch_preserves_session_object_identity(self):
        """ensure_site 触发 relaunch 后：返回同一 session 对象（引用不变）。"""
        mgr = self._make_mgr()
        old_browser = MagicMock()
        session = Session(
            browser=old_browser,
            extra={"needs_relaunch": {"1688": True}},
        )
        orig_id = id(session)

        new_browser = MagicMock()
        new_ctx = FakeBrowserContext()
        new_browser.new_context.return_value = new_ctx
        new_session = Session(
            browser=new_browser,
            views={
                "1688": SiteView(context=new_ctx, page=MagicMock(),
                                 identity="1688:direct", domain="1688.com"),
            },
        )

        with patch.object(mgr, 'launch', return_value=new_session):
            mgr.ensure_site(session, "1688", "1688.com")

        self.assertEqual(id(session), orig_id,
                         "session 对象引用应保持不变")
        self.assertIn("1688", session.views)


if __name__ == "__main__":
    unittest.main()
