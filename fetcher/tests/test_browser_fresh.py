# -*- coding: utf-8 -*-
"""BrowserManager 单测：check_ip_fresh + fingerprint_args（Step 1.2 #1, #6）。"""

import unittest
from unittest.mock import patch, MagicMock

from fetcher import RunConfig
from fetcher.core.session import Session, bare_identity, is_direct
from fetcher.net.browser import BrowserManager, fingerprint_args


class CheckIPFreshP2Test(unittest.TestCase):
    """#1: check_ip_fresh 使用 bare_identity 比较（避免误判 IP 轮换）。"""

    def setUp(self):
        config = RunConfig(headless=True, use_proxy=False)
        self.mgr = BrowserManager(
            config=config, store=MagicMock(), log=lambda m: None,
            site_name="1688")

    def _session(self, identity, req_proxies=None):
        return Session(identity=identity, req_proxies=req_proxies)

    def test_prefixed_identity_same_ip_no_relaunch(self):
        """identity='1688:1.2.3.4' 出口 IP 同为 1.2.3.4 → 不触发 relaunch。

        RED 预期（修正前）：cur_ip('1.2.3.4') != session.identity('1688:1.2.3.4')
        → True → (True, ...) → 误判轮换。
        """
        session = self._session(identity="1688:1.2.3.4")
        with patch.object(self.mgr, "_query_exit_ip_with_retry",
                          return_value="1.2.3.4"):
            need, cur, reason = self.mgr.check_ip_fresh(session)
        self.assertFalse(need, f"不应触发 relaunch，reason={reason}")
        self.assertEqual(cur, "1.2.3.4")

    def test_bare_identity_same_ip_no_relaunch(self):
        """identity='1.2.3.4'（旧键）出口 IP 同为 1.2.3.4 → 不触发 relaunch。

        回归验证：旧键行为不变。
        """
        session = self._session(identity="1.2.3.4")
        with patch.object(self.mgr, "_query_exit_ip_with_retry",
                          return_value="1.2.3.4"):
            need, cur, reason = self.mgr.check_ip_fresh(session)
        self.assertFalse(need)

    def test_prefixed_identity_changed_ip_triggers_relaunch(self):
        """identity='1688:1.2.3.4' 出口 IP 变为 5.5.5.5 → 触发 relaunch。"""
        session = self._session(identity="1688:1.2.3.4")
        with patch.object(self.mgr, "_query_exit_ip_with_retry",
                          return_value="5.5.5.5"):
            need, cur, reason = self.mgr.check_ip_fresh(session)
        self.assertTrue(need)
        self.assertEqual(cur, "5.5.5.5")

    def test_bare_identity_changed_ip_triggers_relaunch(self):
        """identity='1.2.3.4'（旧键）出口 IP 变为 5.5.5.5 → 触发 relaunch。"""
        session = self._session(identity="1.2.3.4")
        with patch.object(self.mgr, "_query_exit_ip_with_retry",
                          return_value="5.5.5.5"):
            need, cur, reason = self.mgr.check_ip_fresh(session)
        self.assertTrue(need)
        self.assertEqual(cur, "5.5.5.5")


class FingerprintArgsP2Test(unittest.TestCase):
    """#6: fingerprint_args 接收裸 IP（非种子分支）。"""

    def test_prefixed_ip_same_fingerprint_as_bare_ip(self):
        """fingerprint_args 对 prefixed identity 与裸 IP 返回相同指纹。

        修正后的调用形态：fingerprint_args(bare_identity("1688:1.2.3.4"))
        应等于 fingerprint_args("1.2.3.4")。
        """
        self.assertEqual(
            fingerprint_args(bare_identity("1688:1.2.3.4")),
            fingerprint_args("1.2.3.4"),
            "带前缀 identity 经 bare_identity 剥取后，指纹应与裸 IP 一致")

    def test_prefixed_direct_same_fingerprint_as_direct(self):
        """fingerprint_args 对 '1688:direct' 与 'direct' 返回相同指纹。"""
        self.assertEqual(
            fingerprint_args(bare_identity("1688:direct")),
            fingerprint_args("direct"),
            "prefixed direct 经 bare_identity 剥取后，指纹应与 'direct' 一致")

    def test_launch_passes_bare_identity_to_fingerprint_args(self):
        """launch 非种子分支传 bare_identity(identity) 给 fingerprint_args。

        因当前代码 identity 尚未拼前缀（Step 1.3），这里验证修正后的
        调用点：seed_kit=None 时传 bare_identity(identity)。
        直连模式 identity='direct' → bare_identity 后仍为 'direct'，
        与修正前行为逐字等价。

        通过 monkeypatch fingerprint_args 捕获入参进行验证。
        """
        import fetcher.net.browser as browser_mod

        captured_fp_args = []

        def _capture_fp(identity):
            captured_fp_args.append(identity)
            return ["--no-sandbox", "--fingerprint=12345",
                    "--fingerprint-platform=macos"]

        config = RunConfig(
            headless=True, use_proxy=False,
            db_path="/nonexistent/test_1688.db")
        mgr = BrowserManager(
            config=config, store=MagicMock(), log=lambda m: None,
            site_name="1688")

        with patch.object(browser_mod, "fingerprint_args", _capture_fp):
            try:
                mgr.launch()
            except Exception:
                pass  # 预期后续步骤失败（无 cookies / cloakbrowser）

        self.assertTrue(len(captured_fp_args) > 0,
                        "fingerprint_args 应被调用过")
        # 直连模式：identity='direct'，bare_identity 后仍为 'direct'
        # 修正前传 'direct'，修正后传 bare_identity('direct')='direct' ——
        # 行为等价（回归验证）
        self.assertEqual(captured_fp_args[0], "direct",
                         f"直连模式指纹入参应为 'direct'，"
                         f"实际={captured_fp_args[0]!r}")


class LaunchPrefixedIdentityTest(unittest.TestCase):
    """Step 1.3: launch 产出带 site 前缀的 identity。"""

    def test_launch_produces_prefixed_identity_proxy_mode(self):
        """代理模式：launch 产出 '1688:1.2.3.4' 而非 '1.2.3.4'。

        RED 预期（修正前）：identity = exit_ip = '1.2.3.4'，没有前缀。
        """
        import fetcher.net.browser as browser_mod

        config = RunConfig(
            headless=True, use_proxy=True,
            db_path="/nonexistent/test_prefixed.db")
        mgr = BrowserManager(
            config=config, store=MagicMock(), log=lambda m: None,
            site_name="1688")

        # mock 出口 IP 查询
        with patch.object(mgr, "_query_exit_ip_with_retry",
                          return_value="1.2.3.4"):
            mock_ch = MagicMock()
            mock_ch.playwright_proxy.return_value = {"server": "fake"}
            mock_ch.requests_proxies.return_value = {}
            mock_ch.server = "10.0.0.1:8080"
            mock_browser = MagicMock()
            mock_ctx = MagicMock()
            mock_page = MagicMock()
            mock_browser.new_context.return_value = mock_ctx
            mock_ctx.new_page.return_value = mock_page
            with patch.object(mgr, "_resolve_channel",
                              return_value=mock_ch):
                with patch.object(browser_mod, "fingerprint_args",
                                  return_value=["--no-sandbox"]):
                    with patch.object(browser_mod, "load_license_key",
                                      return_value="fake-key"):
                        with patch.object(
                            browser_mod, "wait_for_license_seat",
                            return_value=True):
                            with patch("cloakbrowser.launch",
                                       return_value=mock_browser):
                                session = mgr.launch()

        self.assertEqual(session.identity, "1688:1.2.3.4",
                         f"代理模式 identity 应带 site 前缀，"
                         f"实际={session.identity!r}")

    def test_launch_produces_prefixed_direct_direct_mode(self):
        """直连模式：launch 产出 '1688:direct' 而非 'direct'。

        RED 预期（修正前）：identity = 'direct'，没有前缀。
        """
        import fetcher.net.browser as browser_mod

        config = RunConfig(
            headless=True, use_proxy=False,
            db_path="/nonexistent/test_prefixed.db")
        mgr = BrowserManager(
            config=config, store=MagicMock(), log=lambda m: None,
            site_name="1688")

        mock_browser = MagicMock()
        mock_ctx = MagicMock()
        mock_page = MagicMock()
        mock_browser.new_context.return_value = mock_ctx
        mock_ctx.new_page.return_value = mock_page
        with patch.object(browser_mod, "fingerprint_args",
                          return_value=["--no-sandbox"]):
            with patch.object(browser_mod, "load_license_key",
                              return_value="fake-key"):
                with patch.object(
                    browser_mod, "wait_for_license_seat",
                    return_value=True):
                    with patch("cloakbrowser.launch",
                               return_value=mock_browser):
                        session = mgr.launch()

        self.assertEqual(session.identity, "1688:direct",
                         f"直连模式 identity 应带 site 前缀，"
                         f"实际={session.identity!r}")


if __name__ == "__main__":
    unittest.main()
