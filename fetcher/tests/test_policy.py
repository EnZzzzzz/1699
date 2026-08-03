# -*- coding: utf-8 -*-
"""Policy / AttemptTracker 单测：策略链按声明顺序推进、次数用尽后
GIVE_UP、终止条目、熔断 ABORT、覆盖合并。"""

import unittest

from fetcher import AttemptTracker, Policy, PolicyAction, Scenario
from fetcher.strategy.policy import DEFAULT_POLICY_TABLE


def chain_of(policy, scenario, tracker, limit=20):
    """连续 decide（模拟策略全部失败），返回 action 序列。"""
    out = []
    for _ in range(limit):
        d = policy.decide(scenario, tracker)
        out.append((d.action, d.strategy, d.attempt))
        if d.action is not PolicyAction.CONTINUE:
            break
    return out


class PolicyChainTest(unittest.TestCase):
    def setUp(self):
        self.policy = Policy()

    def test_net_stall_chain_order(self):
        t = AttemptTracker()
        seq = chain_of(self.policy, Scenario.NET_STALL, t)
        names = [(a, s) for a, s, _ in seq]
        self.assertEqual(names, [
            (PolicyAction.CONTINUE, "refresh"),
            (PolicyAction.CONTINUE, "refresh"),
            (PolicyAction.CONTINUE, "swap_ip"),
            (PolicyAction.CONTINUE, "swap_ip"),
            (PolicyAction.CONTINUE, "swap_ip"),
            (PolicyAction.GIVE_UP, None),
        ])

    def test_attempt_numbers_increment(self):
        t = AttemptTracker()
        d1 = self.policy.decide(Scenario.NET_ERROR, t)
        d2 = self.policy.decide(Scenario.NET_ERROR, t)
        self.assertEqual((d1.strategy, d1.attempt), ("backoff_sleep", 1))
        self.assertEqual((d2.strategy, d2.attempt), ("backoff_sleep", 2))

    def test_browser_dead_ends_with_abort(self):
        t = AttemptTracker()
        seq = chain_of(self.policy, Scenario.BROWSER_DEAD, t)
        self.assertEqual(len(seq), 4)  # relaunch×3 + abort
        self.assertIs(seq[-1][0], PolicyAction.ABORT)
        self.assertEqual([s for _, s, _ in seq[:3]],
                         ["relaunch_browser"] * 3)

    def test_ip_rotated_ends_with_abort(self):
        t = AttemptTracker()
        seq = chain_of(self.policy, Scenario.IP_ROTATED, t)
        self.assertIs(seq[-1][0], PolicyAction.ABORT)

    def test_risk_login_chain(self):
        t = AttemptTracker()
        seq = chain_of(self.policy, Scenario.RISK_LOGIN, t)
        names = [s for action, s, _att in seq if s is not None]
        self.assertEqual(names, ["wait_human_login",
                                 "clear_identity_swap", "clear_identity_swap"])
        self.assertIs(seq[-1][0], PolicyAction.GIVE_UP)

    def test_scenario_change_resets_chain(self):
        t = AttemptTracker()
        self.policy.decide(Scenario.NET_STALL, t)
        self.policy.decide(Scenario.NET_STALL, t)  # refresh 用尽
        d = self.policy.decide(Scenario.RISK_SLIDER_PAGE, t)
        # 场景切换后从新链的链头开始
        self.assertEqual((d.strategy, d.attempt), ("solve_slider", 1))

    def test_ok_resets_tracker(self):
        t = AttemptTracker()
        self.policy.decide(Scenario.NET_STALL, t)
        t.consecutive_fail = 3
        self.policy.decide(Scenario.OK, t)
        self.assertEqual(t.consecutive_fail, 0)
        self.assertIsNone(t.scenario)
        self.assertEqual(t.used, 0)

    def test_circuit_breaker_aborts(self):
        t = AttemptTracker()
        t.consecutive_fail = self.policy.max_consecutive_fail
        d = self.policy.decide(Scenario.NET_STALL, t)
        self.assertIs(d.action, PolicyAction.ABORT)

    def test_note_failure_counts_and_resets_chain(self):
        t = AttemptTracker()
        self.policy.decide(Scenario.NET_STALL, t)
        t.note_failure()
        self.assertEqual(t.consecutive_fail, 1)
        self.assertIsNone(t.scenario)
        self.assertEqual(t.pos, 0)

    def test_scenario_without_chain_gives_up(self):
        policy = Policy(table={Scenario.NET_STALL: [("refresh", 1)]})
        t = AttemptTracker()
        d = policy.decide(Scenario.RISK_LOGIN, t)
        self.assertIs(d.action, PolicyAction.GIVE_UP)


class PolicyDeclarationTest(unittest.TestCase):
    def test_default_table_covers_all_scenarios_except_ok(self):
        for s in Scenario:
            if s is Scenario.OK:
                continue
            self.assertIn(s, DEFAULT_POLICY_TABLE, f"默认策略表缺少 {s.name}")

    def test_from_dict_string_keys(self):
        policy = Policy.from_dict({"net_stall": [("refresh", 1),
                                                  ("give_up", None)]})
        t = AttemptTracker()
        seq = chain_of(policy, Scenario.NET_STALL, t)
        self.assertEqual([(a, s) for a, s, _ in seq],
                         [(PolicyAction.CONTINUE, "refresh"),
                          (PolicyAction.GIVE_UP, None)])

    def test_unknown_strategy_rejected_at_load(self):
        with self.assertRaises(KeyError):
            Policy(table={Scenario.NET_STALL: [("no_such_strategy", 1)]})

    def test_ok_scenario_rejected(self):
        with self.assertRaises(ValueError):
            Policy(table={Scenario.OK: [("refresh", 1)]})

    def test_with_overrides_replaces_chain_keeps_rest(self):
        base = Policy()
        custom = base.with_overrides({
            Scenario.NET_STALL: [("refresh", 1), ("give_up", None)],
        })
        # 覆盖生效
        t = AttemptTracker()
        seq = chain_of(custom, Scenario.NET_STALL, t)
        self.assertEqual([(a, s) for a, s, _ in seq],
                         [(PolicyAction.CONTINUE, "refresh"),
                          (PolicyAction.GIVE_UP, None)])
        # 未覆盖的场景保持默认
        t2 = AttemptTracker()
        seq2 = chain_of(custom, Scenario.BROWSER_DEAD, t2)
        self.assertIs(seq2[-1][0], PolicyAction.ABORT)
        # 原 Policy 不被修改
        self.assertEqual(len(base.table[Scenario.NET_STALL]), 3)

    def test_give_up_terminal_mid_chain(self):
        policy = Policy(table={Scenario.EMPTY: [("block_rest", 1),
                                                ("give_up", None),
                                                ("swap_ip", 9)]})
        t = AttemptTracker()
        seq = chain_of(policy, Scenario.EMPTY, t)
        # give_up 之后的条目永远不可达
        self.assertEqual(len(seq), 2)
        self.assertIs(seq[-1][0], PolicyAction.GIVE_UP)


if __name__ == "__main__":
    unittest.main()
