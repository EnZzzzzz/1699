# -*- coding: utf-8 -*-
"""CLI 解析层测试：daemon 子命令挂载 + 既有站点子命令防装配回归。"""

import unittest

from fetcher.cli.main import build_parser, config_from_args


class CliParserTest(unittest.TestCase):
    def setUp(self):
        self.ap = build_parser()

    # ---- daemon 子命令 ----

    def test_daemon_defaults(self):
        args = self.ap.parse_args(["daemon"])
        self.assertEqual(args.site, "daemon")
        # --queue 默认值（P0 不开放其他选择）
        self.assertEqual(args.queue, "crawl_1688_contact")
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

    def test_daemon_queue_and_common_override(self):
        args = self.ap.parse_args(
            ["daemon", "--queue", "q2", "--workers", "3", "--limit", "5"])
        self.assertEqual(args.queue, "q2")
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


if __name__ == "__main__":
    unittest.main()
