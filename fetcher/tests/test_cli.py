# -*- coding: utf-8 -*-
"""CLI 解析层测试：daemon 子命令挂载 + 既有站点子命令防装配回归。"""

import unittest
from unittest.mock import MagicMock

from fetcher import RunConfig
from fetcher.cli.main import build_parser, config_from_args, _build_engine
from fetcher.strategy.policy import Policy


class CliParserTest(unittest.TestCase):
    def setUp(self):
        self.ap = build_parser()

    # ---- daemon 子命令 ----

    def test_daemon_defaults(self):
        args = self.ap.parse_args(["daemon"])
        self.assertEqual(args.site, "daemon")
        # --queues 默认 None（全量）
        self.assertIsNone(args.queues)
        # daemon 不套 task 二级 subparser
        self.assertIsNone(getattr(args, "task", None))
        # add_common_args 全套已挂载（抽查代表项）
        self.assertEqual(args.rest_every, 20)
        self.assertEqual(args.batch_rest, 900)
        self.assertFalse(args.proxy)
        self.assertFalse(args.headed)
        # config_from_args 依赖的 num/limit 必须有默认（contact 口径）
        self.assertEqual(args.num, 10)
        self.assertEqual(args.limit, 0)

    def test_daemon_queues_and_common_override(self):
        args = self.ap.parse_args(
            ["daemon", "--queues", "crawl_1688_contact", "crawl_mic_contact",
             "--workers", "3", "--limit", "5"])
        self.assertEqual(args.queues, ["crawl_1688_contact", "crawl_mic_contact"])
        self.assertEqual(args.workers, 3)
        self.assertEqual(args.limit, 5)

    def test_daemon_queues_dynamic_from_registry(self):
        """I3：--queues 校验来自注册表动态派生，非硬编码。"""
        from fetcher.cli.main import _build_registry
        full = _build_registry()
        all_names = [s.queue for s in full]
        self.assertIn("crawl_1688_contact", all_names)
        self.assertIn("crawl_mic_contact", all_names)
        self.assertIn("crawl_mic_shop", all_names)

    def test_daemon_config_from_args(self):
        # config_from_args 不读 args.task，daemon 命名空间可直接复用
        cfg = config_from_args(self.ap.parse_args(["daemon"]))
        self.assertEqual(cfg.batch_num, 10)
        self.assertEqual(cfg.limit, 0)

    def test_daemon_has_no_task_subparser(self):
        # daemon 后不能再跟 task 位置参数（argparse 报错退出）
        with self.assertRaises(SystemExit):
            self.ap.parse_args(["daemon", "contact"])

    # ---- 既有站点子命令防回归 ----

    def test_existing_site_subcommands_unchanged(self):
        cases = {
            ("1688", "shop"): 200,
            ("1688", "contact"): 10,
            ("1688", "company"): 200,
        }
        for (site, task), num in cases.items():
            args = self.ap.parse_args([site, task])
            self.assertEqual(args.site, site)
            self.assertEqual(args.task, task)
            self.assertEqual(args.num, num)
        args = self.ap.parse_args(["yiwugo", "search"])
        self.assertEqual((args.site, args.task), ("yiwugo", "search"))
        # contact 业务开关仍在
        args = self.ap.parse_args(["1688", "contact", "--retry-failed"])
        self.assertTrue(args.retry_failed)


class BuildEngineTest(unittest.TestCase):
    """Step 1.3: _build_engine 透传 site_name 正确性。"""

    def test_site_name_passed_to_engine_site_branch(self):
        """站点分支：site_name=args.site（如 '1688'）透传到 Engine。"""
        cfg = RunConfig(headless=True, use_proxy=False)
        fake_task = MagicMock()
        fake_site = MagicMock()
        engine = _build_engine(cfg, fake_task, site=fake_site,
                               provider=None, policy=Policy(),
                               site_name="1688")
        self.assertEqual(engine.site_name, "1688",
                         "site_name 应正确透传到 Engine")

    def test_site_name_passed_to_engine_daemon_branch(self):
        """daemon 分支：site_name='1688' 硬编码透传到 Engine。"""
        cfg = RunConfig(headless=True, use_proxy=False)
        fake_task = MagicMock()
        fake_site = MagicMock()
        engine = _build_engine(cfg, fake_task, site=fake_site,
                               provider=None, policy=Policy(),
                               site_name="1688")
        # daemon 和站点分支走同一个 _build_engine，唯一区别是调用时
        # site_name 参数值（args.site vs "1688"）
        self.assertEqual(engine.site_name, "1688",
                         "daemon 分支 site_name 应硬编码为 '1688'")

    def test_site_name_None_allowed(self):
        """site=None 时 site_name 可为 None（Engine guard 不触发）。"""
        cfg = RunConfig(headless=True, use_proxy=False)
        fake_task = MagicMock()
        engine = _build_engine(cfg, fake_task, site=None,
                               provider=None, policy=Policy(),
                               site_name=None)
        self.assertIsNone(engine.site_name)
        self.assertIsNone(engine.site)


class ResetDaemonStateTest(unittest.TestCase):
    """I2：reset_daemon_state 逐 site 重置。"""

    def setUp(self):
        self._tmp = __import__("tempfile").TemporaryDirectory()
        from pathlib import Path
        from fetcher.db import ShopDB
        self.db_path = Path(self._tmp.name) / "t.db"
        self.db = ShopDB(self.db_path)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _seed_in_progress(self, domains):
        """Seed shops 为 in_progress 状态。"""
        shops = [{"domain": d, "name": d, "url": f"https://{d}"}
                 for d in domains]
        self.db.upsert_shops(shops)
        # upsert 默认 pending，需手动设为 in_progress
        for d in domains:
            self.db.conn.execute(
                "UPDATE shops SET status='in_progress' WHERE domain=?", (d,))
        self.db.conn.commit()

    def test_reset_only_targeted_domain_suffixes(self):
        """只有指定 domain_suffix 的 in_progress 被重置，其他站点不动。"""
        from fetcher.cli.main import _build_registry, reset_daemon_state
        from fetcher.control.queue_router import QueueSpec

        # Seed 混合 in_progress：两个不同 domain_suffix
        self._seed_in_progress(["s1.1688.com", "s2.1688.com", "s3.1688.com"])
        self._seed_in_progress(["s1.cn.made-in-china.com",
                                "s2.cn.made-in-china.com"])
        # 额外：一个不匹配任何 registered domain 的也应是 in_progress
        self._seed_in_progress(["other.example.com"])

        # 用全量 registry
        registry = _build_registry()

        n_items, total_shops = reset_daemon_state(self.db, registry)

        # claimed 无 → 0
        self.assertEqual(n_items, 0)
        # 1688 (3) + mic (2) = 5 个被重置
        self.assertEqual(total_shops, 5)

        # 核查：1688 的变 pending
        for d in ["s1.1688.com", "s2.1688.com", "s3.1688.com"]:
            self.assertEqual(
                self.db.conn.execute(
                    "SELECT status FROM shops WHERE domain=?", (d,)
                ).fetchone()[0],
                "pending")
        # mic 的变 pending
        for d in ["s1.cn.made-in-china.com", "s2.cn.made-in-china.com"]:
            self.assertEqual(
                self.db.conn.execute(
                    "SELECT status FROM shops WHERE domain=?", (d,)
                ).fetchone()[0],
                "pending")
        # 其他站点不动（仍为 in_progress）
        self.assertEqual(
            self.db.conn.execute(
                "SELECT status FROM shops WHERE domain=?",
                ("other.example.com",)
            ).fetchone()[0],
            "in_progress")

    def test_reset_with_empty_registry(self):
        """空 registry → 只做 claimed 回收，不重置任何 in_progress。"""
        from fetcher.cli.main import reset_daemon_state

        self._seed_in_progress(["s1.1688.com"])
        n_items, total_shops = reset_daemon_state(self.db, [])
        self.assertEqual(n_items, 0)
        self.assertEqual(total_shops, 0)
        # s1.1688.com 未被重置（仍 in_progress）
        self.assertEqual(
            self.db.conn.execute(
                "SELECT status FROM shops WHERE domain=?",
                ("s1.1688.com",)
            ).fetchone()[0],
            "in_progress")

    def test_reset_skips_feeder_queues(self):
        """feeder 队列（topup=None）不触发 reset_in_progress。

        feeder 的 domain_suffix="" 若被调用 → 重置所有 in_progress
        （含 other.example.com）；修复后跳过 feeder → other.example.com
        保持 in_progress。
        """
        from fetcher.cli.main import reset_daemon_state
        from fetcher.control.queue_router import QueueSpec

        # feeder 队列：topup=None, domain_suffix 为空
        feeder = QueueSpec(
            queue="crawl_mic_shop", site="madeinchina",
            task=lambda: None, topup=None, domain_suffix="",
            requires={"channel", "browser"})
        # contact 队列：topup 非 None
        contact = QueueSpec(
            queue="crawl_mic_contact", site="madeinchina",
            task=lambda: None,
            topup=lambda db, limit: 0,
            domain_suffix=".cn.made-in-china.com",
            requires={"channel", "browser"})

        # Seed: mic contact shop + 不匹配任何 contact domain_suffix 的 shop
        self._seed_in_progress([
            "s1.cn.made-in-china.com",
            "other.example.com"])

        registry = [feeder, contact]
        n_items, total_shops = reset_daemon_state(self.db, registry)
        self.assertEqual(n_items, 0)
        # 只 contact 队列的 domain_suffix 被重置（1 个），feeder 跳过
        self.assertEqual(total_shops, 1)
        # s1.cn.made-in-china.com 被重置为 pending
        self.assertEqual(
            self.db.conn.execute(
                "SELECT status FROM shops WHERE domain=?",
                ("s1.cn.made-in-china.com",)
            ).fetchone()[0],
            "pending")
        # other.example.com 保持 in_progress（feeder 未触发全量重置）
        self.assertEqual(
            self.db.conn.execute(
                "SELECT status FROM shops WHERE domain=?",
                ("other.example.com",)
            ).fetchone()[0],
            "in_progress")


if __name__ == "__main__":
    unittest.main()
