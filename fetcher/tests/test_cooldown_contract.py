# -*- coding: utf-8 -*-
"""冷却契约（P1）单测：StepResult.cooldown 与 WorkerContext.cooldown_until
是纯加法字段——默认值、关键字构造生效、既有三参数位置构造兼容、
default_factory 语义（两实例不共享同一份 dict）。"""

import unittest

from fetcher.core.context import WorkerContext
from fetcher.strategy.base import StepResult


class StepResultCooldownTest(unittest.TestCase):
    def test_cooldown_default_none(self):
        r = StepResult(True)
        self.assertIsNone(r.cooldown)

    def test_cooldown_keyword_construction(self):
        r = StepResult(True, "x", cooldown=12.5)
        self.assertTrue(r.solved)
        self.assertEqual(r.detail, "x")
        self.assertEqual(r.cooldown, 12.5)

    def test_positional_three_args_still_works(self):
        """既有三参数位置构造 StepResult(True, "x", {"k": 1}) 不破坏，
        cooldown 落默认 None（锁定兼容性）。"""
        r = StepResult(True, "x", {"k": 1})
        self.assertTrue(r.solved)
        self.assertEqual(r.detail, "x")
        self.assertEqual(r.data, {"k": 1})
        self.assertIsNone(r.cooldown)


class WorkerContextCooldownUntilTest(unittest.TestCase):
    def test_cooldown_until_default_empty_dict(self):
        ctx = WorkerContext(log=lambda m: None)
        self.assertEqual(ctx.cooldown_until, {})

    def test_cooldown_until_not_shared_between_instances(self):
        a = WorkerContext(log=lambda m: None)
        b = WorkerContext(log=lambda m: None)
        a.cooldown_until["block"] = 123.0
        self.assertEqual(b.cooldown_until, {})
        self.assertIsNot(a.cooldown_until, b.cooldown_until)


if __name__ == "__main__":
    unittest.main()
