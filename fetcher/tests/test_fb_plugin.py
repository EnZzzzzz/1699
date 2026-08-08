# -*- coding: utf-8 -*-
"""Step 1.2: FacebookPlugin 任务注册 + policy_overrides 测试。

覆盖：task_names 注册 post、policy_overrides 去 solve_slider 退化链
（参照 madeinchina 同款：RISK_SLIDER_PAGE/EMBED → block_rest → swap_ip
→ give_up）、未知任务名抛 KeyError、既有判断侧（detectors/block_reason）
不回归。
"""

import unittest

from fetcher.core.types import Scenario
from fetcher.sites.facebook import FacebookPlugin
from fetcher.sites.facebook.features import make_detectors, page_block_reason


class FacebookPluginWiringTest(unittest.TestCase):
    def setUp(self):
        self.plugin = FacebookPlugin()

    def test_task_names_registers_post(self):
        self.assertEqual(self.plugin.task_names(), ["post"])

    def test_make_task_unknown_name_raises(self):
        with self.assertRaises(KeyError):
            self.plugin.make_task("bogus")

    def test_policy_overrides_cover_both_slider_scenarios(self):
        ov = self.plugin.policy_overrides
        self.assertIn(Scenario.RISK_SLIDER_PAGE, ov)
        self.assertIn(Scenario.RISK_SLIDER_EMBED, ov)

    def test_policy_overrides_remove_solve_slider(self):
        """FB 无阿里式滑块：两条 slider 链都不得含 solve_slider。"""
        for chain in self.plugin.policy_overrides.values():
            names = [entry[0] for entry in chain]
            self.assertNotIn("solve_slider", names)
            self.assertNotIn("wait_human_verify", names)

    def test_policy_overrides_chain_ends_with_give_up(self):
        """BLOCKED → block_rest → swap_ip → give_up（SPEC §3.2）。"""
        for chain in self.plugin.policy_overrides.values():
            self.assertEqual(chain[0][0], "block_rest")
            self.assertIn("swap_ip", [e[0] for e in chain])
            self.assertEqual(chain[-1][0], "give_up")

    def test_detectors_and_block_reason_unaffected(self):
        """判断侧接线不回归：detectors 非空、block_reason 是 callable。"""
        self.assertTrue(len(make_detectors()) > 0)
        self.assertTrue(callable(page_block_reason))


if __name__ == "__main__":
    unittest.main()
