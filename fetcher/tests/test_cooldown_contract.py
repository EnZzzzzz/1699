# -*- coding: utf-8 -*-
"""冷却契约（P1）单测：StepResult.cooldown 与 WorkerContext.cooldown_until
是纯加法字段——默认值、关键字构造生效、既有三参数位置构造兼容、
default_factory 语义（两实例不共享同一份 dict）。

Step 2.1 起追加策略迁移契约：Sleep / BackoffSleep / BlockRest 三策略
run() 只算时长放进 StepResult.cooldown，自身零等待（不触 ctx.wait）。"""

import unittest
from types import SimpleNamespace

from fetcher.core.context import WorkerContext
from fetcher.strategy.base import StepResult
from fetcher.strategy.strategies import (BackoffSleepStrategy,
                                         BlockRestStrategy, SleepStrategy)


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


def _fake_ctx(**cfg):
    """最小假 ctx：记录 log/wait 调用；config 只带 block_rest_min/max。"""
    base = dict(block_rest_min=60.0, block_rest_max=120.0)
    base.update(cfg)
    ctx = SimpleNamespace(state={}, logs=[], waits=[], identity="1.1.1.1",
                          config=SimpleNamespace(**base))
    ctx.log = ctx.logs.append

    def wait(t):
        ctx.waits.append(t)
        return False

    ctx.wait = wait
    return ctx


class StrategyCooldownMigrationTest(unittest.TestCase):
    """Step 2.1 新契约：三策略输出 cooldown、自身零等待（不触 ctx.wait）。"""

    def test_sleep_outputs_cooldown_and_never_waits(self):
        ctx = _fake_ctx()
        r = SleepStrategy(min=2.0, max=5.0).run(ctx)
        self.assertTrue(r.solved)
        self.assertIsNotNone(r.cooldown)
        # 对数正态截断区间 [lo*0.5, hi*5]
        self.assertGreaterEqual(r.cooldown, 1.0)
        self.assertLessEqual(r.cooldown, 25.0)
        self.assertEqual(ctx.waits, [])

    def test_sleep_fixed_duration_when_min_eq_max(self):
        r = SleepStrategy(min=3.0, max=3.0).run(_fake_ctx())
        self.assertEqual(r.cooldown, 3.0)

    def test_sleep_default_params(self):
        """缺省参数走 2.0/5.0（与旧原子取参路径一致）。"""
        r = SleepStrategy().run(_fake_ctx())
        self.assertGreaterEqual(r.cooldown, 1.0)
        self.assertLessEqual(r.cooldown, 25.0)

    def test_backoff_linear_with_state_attempt(self):
        ctx = _fake_ctx()
        ctx.state["attempt"] = 3
        r = BackoffSleepStrategy().run(ctx)
        self.assertEqual(r.cooldown, 90.0)
        self.assertEqual(ctx.waits, [])

    def test_backoff_capped(self):
        ctx = _fake_ctx()
        ctx.state["attempt"] = 99
        r = BackoffSleepStrategy().run(ctx)
        self.assertEqual(r.cooldown, 180.0)

    def test_backoff_attempt_or_short_circuit(self):
        """params['attempt']=0 经 or 短路回落到 state（逐字保留旧语义）。"""
        ctx = _fake_ctx()
        ctx.state["attempt"] = 2
        r = BackoffSleepStrategy(attempt=0).run(ctx)
        self.assertEqual(r.cooldown, 60.0)
        # params 有有效 attempt 时优先
        r2 = BackoffSleepStrategy(attempt=4).run(ctx)
        self.assertEqual(r2.cooldown, 120.0)

    def test_block_rest_reads_config_and_outputs_cooldown(self):
        ctx = _fake_ctx(block_rest_min=120.0, block_rest_max=240.0)
        r = BlockRestStrategy().run(ctx)
        self.assertTrue(r.solved)
        self.assertGreaterEqual(r.cooldown, 60.0)    # lo*0.5
        self.assertLessEqual(r.cooldown, 1200.0)     # hi*5
        self.assertEqual(ctx.waits, [])
        # 现有 ⚠ 风控休息 log 行保留
        self.assertTrue(any("风控休息" in m for m in ctx.logs))


if __name__ == "__main__":
    unittest.main()
