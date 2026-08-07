# -*- coding: utf-8 -*-
"""bare_identity / is_direct 辅助函数单测。"""

import unittest

from fetcher.core.session import bare_identity, is_direct


class BareIdentityTest(unittest.TestCase):
    def test_strips_site_prefix(self):
        """带站点前缀的 IP：剥掉前缀返回裸 IP。"""
        self.assertEqual(bare_identity("1688:1.2.3.4"), "1.2.3.4")

    def test_strips_prefix_for_direct(self):
        """带站点前缀的 direct：剥掉前缀返回 direct。"""
        self.assertEqual(bare_identity("madeinchina:direct"), "direct")

    def test_passthrough_bare_ip(self):
        """无前缀 IP：原样返回（兼容旧键）。"""
        self.assertEqual(bare_identity("1.2.3.4"), "1.2.3.4")

    def test_passthrough_direct(self):
        """无前缀 direct：原样返回（兼容旧键）。"""
        self.assertEqual(bare_identity("direct"), "direct")

    # ---- 边界 ----

    def test_empty_string_passthrough(self):
        """空字符串无冒号，原样返回。"""
        self.assertEqual(bare_identity(""), "")

    def test_multi_colon_splits_only_first(self):
        """多冒号只切第一个：'a:b:c' → 'b:c'。"""
        self.assertEqual(bare_identity("a:b:c"), "b:c")

    def test_trailing_colon_returns_empty(self):
        """仅前缀无值：'1688:' → ''。"""
        self.assertEqual(bare_identity("1688:"), "")


class IsDirectTest(unittest.TestCase):
    def test_bare_direct_is_direct(self):
        """无前缀 direct 判定为直连。"""
        self.assertTrue(is_direct("direct"))

    def test_prefixed_direct_is_direct(self):
        """带站点前缀的 direct 也判定为直连。"""
        self.assertTrue(is_direct("1688:direct"))

    def test_ip_is_not_direct(self):
        """裸 IP 不是直连。"""
        self.assertFalse(is_direct("1.2.3.4"))

    def test_prefixed_ip_is_not_direct(self):
        """带站点前缀的 IP 不是直连。"""
        self.assertFalse(is_direct("1688:1.2.3.4"))


if __name__ == "__main__":
    unittest.main()
