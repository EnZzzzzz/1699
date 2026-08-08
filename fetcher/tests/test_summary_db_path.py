# -*- coding: utf-8 -*-
"""测试 summary 透传 db_path（Step 3.1 修复验证）。
证明 summary 不再默认开生产库，而是使用 Engine 传入的 db_path。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class SummaryDbPathTest(unittest.TestCase):
    """验证各站点 summary 将 db_path 透传给 ShopDB。"""

    # ---- 1688 contact（含 format_tmd_report 分支） ----

    def test_1688_contact_summary_passes_db_path(self):
        """1688 contact summary 将 db_path 传给 ShopDB 构造器。"""
        recorded_path = []

        def fake_shopdb(path=None):
            recorded_path.append(path)
            db = MagicMock()
            db.stats.return_value = "stats"
            db.format_tmd_report.return_value = "tmd"
            return db

        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
            from fetcher.sites.alibaba1688.contact import ContactTask
            task = ContactTask()
            result = task.summary(
                {0: {"ok": 1, "empty": 2, "failed": 0}},
                "/tmp/target.db",
            )
        self.assertEqual(recorded_path, ["/tmp/target.db"],
                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")
        self.assertIn("有联系方式 1", result)

    # ---- madeinchina contact ----

    def test_madeinchina_contact_summary_passes_db_path(self):
        """madeinchina contact summary 将 db_path 传给 ShopDB 构造器。"""
        recorded_path = []

        def fake_shopdb(path=None):
            recorded_path.append(path)
            db = MagicMock()
            db.stats.return_value = "stats"
            return db

        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
            from fetcher.sites.madeinchina.contact import MadeInChinaContactTask
            task = MadeInChinaContactTask()
            task.summary(
                {0: {"ok": 0, "empty": 0, "failed": 1}},
                "/tmp/mic.db",
            )
        self.assertEqual(recorded_path, ["/tmp/mic.db"],
                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")

    # ---- 1688 shop ----

    def test_1688_shop_summary_passes_db_path(self):
        """1688 shop summary 将 db_path 传给 ShopDB 构造器。"""
        recorded_path = []

        def fake_shopdb(path=None):
            recorded_path.append(path)
            db = MagicMock()
            db.stats.return_value = "stats"
            return db

        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
            from fetcher.sites.alibaba1688.shop import ShopTask
            task = ShopTask()
            task.summary(
                {0: {"shops": 1, "new": 0, "pages": 2}},
                "/tmp/shop.db",
            )
        self.assertEqual(recorded_path, ["/tmp/shop.db"],
                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")

    # ---- 1688 company ----

    def test_1688_company_summary_passes_db_path(self):
        """1688 company summary 将 db_path 传给 ShopDB 构造器。"""
        recorded_path = []

        def fake_shopdb(path=None):
            recorded_path.append(path)
            db = MagicMock()
            db.stats.return_value = "stats"
            return db

        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
            from fetcher.sites.alibaba1688.company import CompanyTask
            task = CompanyTask()
            task.summary(
                {0: {"shops": 1, "new": 0, "pages": 1}},
                "/tmp/company.db",
            )
        self.assertEqual(recorded_path, ["/tmp/company.db"],
                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")

    # ---- madeinchina shop ----

    def test_madeinchina_shop_summary_passes_db_path(self):
        """madeinchina shop summary 将 db_path 传给 ShopDB 构造器。"""
        recorded_path = []

        def fake_shopdb(path=None):
            recorded_path.append(path)
            db = MagicMock()
            db.stats.return_value = "stats"
            return db

        with patch("fetcher.db.ShopDB", side_effect=fake_shopdb):
            from fetcher.sites.madeinchina.shop import MadeInChinaShopTask
            task = MadeInChinaShopTask()
            task.summary(
                {0: {"shops": 0, "new": 0, "pages": 0}},
                "/tmp/micshop.db",
            )
        self.assertEqual(recorded_path, ["/tmp/micshop.db"],
                          "summary 未将 db_path 传给 ShopDB（仍默认开生产库）")


if __name__ == "__main__":
    unittest.main()
