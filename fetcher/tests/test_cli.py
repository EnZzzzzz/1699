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


if __name__ == "__main__":
    unittest.main()
