# -*- coding: utf-8 -*-
"""时序原子（sleep / human_pause / confirm_human）单元测试。

纯本地：不触浏览器/代理/网络/Redis。confirm_human 通过 monkeypatch
wait_confirmation 注入假实现；sleep / human_pause 用 0~0.2 秒级参数
验证 progress 上报与 stopped 分支。
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from app.services.flow.base import Context, OUTCOME_OK, OUTCOME_STOPPED
from app.services.flow import registry
from app.services.flow.atoms import confirm_human as ch_mod
from app.services.flow.atoms import human_pause as hp_mod
from app.services.flow.atoms import sleep as sleep_mod


class FakeRt:
    """鸭子类型 TaskRuntime：只收集 emit 事件，停止由注入的 Event 决定。"""

    def __init__(self, stop_event: threading.Event | None = None):
        self.events: list[tuple] = []
        self._stop = stop_event

    def emit(self, level, message, data=None):
        self.events.append((level, message, data))

    def stop_requested(self):
        return bool(self._stop and self._stop.is_set())

    def messages(self, level=None):
        return [m for lv, m, _ in self.events if level is None or lv == level]


def make_ctx(stop_event=None):
    rt = FakeRt(stop_event)
    return Context(task_id=42, rt=rt, stop_event=stop_event), rt


class SleepAtomTest(unittest.TestCase):
    def setUp(self):
        self.atom = sleep_mod.SleepAtom()

    def test_fixed_wait_ok_and_progress(self):
        ctx, rt = make_ctx()
        t0 = time.monotonic()
        res = self.atom.run(ctx, {"min": 0.05, "max": 0.05})
        dur = time.monotonic() - t0
        self.assertEqual(res.outcome, OUTCOME_OK)
        self.assertGreaterEqual(dur, 0.04)
        self.assertLess(dur, 1.0)
        # 结束时 progress 定格在 total == elapsed
        self.assertAlmostEqual(ctx.progress["total"], 0.05, places=3)
        self.assertAlmostEqual(ctx.progress["elapsed"], 0.05, places=3)
        self.assertTrue(any("将于" in m for m in rt.messages("info")))

    def test_zero_params_no_wait(self):
        ctx, rt = make_ctx()
        t0 = time.monotonic()
        res = self.atom.run(ctx, {"min": 0, "max": 0})
        self.assertEqual(res.outcome, OUTCOME_OK)
        self.assertLess(time.monotonic() - t0, 0.2)
        self.assertEqual(rt.events, [])  # 与 start_delay_countdown 一致：不等待不发事件

    def test_random_range_uses_uniform_draw(self):
        ctx, _ = make_ctx()
        with mock.patch.object(sleep_mod.random, "uniform", return_value=0.12) as u:
            res = self.atom.run(ctx, {"min": 0.1, "max": 0.2})
        self.assertEqual(res.outcome, OUTCOME_OK)
        u.assert_called_once_with(0.1, 0.2)
        self.assertAlmostEqual(ctx.progress["total"], 0.12, places=3)

    def test_stopped_during_wait(self):
        stop = threading.Event()
        threading.Timer(0.05, stop.set).start()
        ctx, rt = make_ctx(stop)
        t0 = time.monotonic()
        res = self.atom.run(ctx, {"min": 10, "max": 10})
        dur = time.monotonic() - t0
        self.assertEqual(res.outcome, OUTCOME_STOPPED)
        self.assertLess(dur, 2.0)  # 远小于 10s，证明被中断
        self.assertTrue(any("停止" in m for m in rt.messages("warning")))
        # 停止前已上报过 progress
        self.assertEqual(ctx.progress["total"], 10.0)
        self.assertLess(ctx.progress["elapsed"], 5.0)

    def test_min_greater_than_max_swapped(self):
        ctx, rt = make_ctx()
        res = self.atom.run(ctx, {"min": 0.05, "max": 0.02})
        self.assertEqual(res.outcome, OUTCOME_OK)
        self.assertTrue(any("交换" in m for m in rt.messages("warning")))


class HumanPauseAtomTest(unittest.TestCase):
    def setUp(self):
        self.atom = hp_mod.HumanPauseAtom()

    def test_fixed_pause_ok(self):
        ctx, _ = make_ctx()
        t0 = time.monotonic()
        res = self.atom.run(ctx, {"min": 0.05, "max": 0.05})
        self.assertEqual(res.outcome, OUTCOME_OK)
        self.assertGreaterEqual(time.monotonic() - t0, 0.04)
        self.assertAlmostEqual(ctx.progress["total"], 0.05, places=3)
        self.assertAlmostEqual(ctx.progress["elapsed"], 0.05, places=3)

    def test_default_params_draw_from_3_to_7(self):
        ctx, _ = make_ctx()
        with mock.patch.object(hp_mod.random, "uniform", return_value=0.01) as u:
            res = self.atom.run(ctx, {})
        self.assertEqual(res.outcome, OUTCOME_OK)
        u.assert_called_once_with(3.0, 7.0)

    def test_stopped_during_pause(self):
        stop = threading.Event()
        threading.Timer(0.05, stop.set).start()
        ctx, _ = make_ctx(stop)
        t0 = time.monotonic()
        res = self.atom.run(ctx, {"min": 10, "max": 10})
        self.assertEqual(res.outcome, OUTCOME_STOPPED)
        self.assertLess(time.monotonic() - t0, 2.0)


class ConfirmHumanAtomTest(unittest.TestCase):
    def setUp(self):
        self.atom = ch_mod.ConfirmHumanAtom()

    def test_confirmed_ok(self):
        ctx, rt = make_ctx()
        with mock.patch.object(ch_mod, "wait_confirmation",
                               return_value=True) as wc:
            res = self.atom.run(ctx, {"timeout": 5})
        self.assertEqual(res.outcome, OUTCOME_OK)
        wc.assert_called_once()
        args, kwargs = wc.call_args
        self.assertEqual(args[0], 42)          # task_id 透传
        self.assertEqual(kwargs["timeout"], 5.0)
        self.assertEqual(ctx.progress["total"], 5.0)
        self.assertTrue(any("确认通过" in m for m in rt.messages("success")))

    def test_timeout_outcome(self):
        ctx, rt = make_ctx()
        with mock.patch.object(ch_mod, "wait_confirmation", return_value=False):
            res = self.atom.run(ctx, {"timeout": 5})
        self.assertEqual(res.outcome, "timeout")
        self.assertTrue(any("超时" in m for m in rt.messages("warning")))

    def test_stopped_outcome(self):
        stop = threading.Event()
        stop.set()  # 停止先于确认到达
        ctx, _ = make_ctx(stop)
        with mock.patch.object(ch_mod, "wait_confirmation", return_value=False):
            res = self.atom.run(ctx, {"timeout": 5})
        self.assertEqual(res.outcome, OUTCOME_STOPPED)

    def test_default_timeout_600(self):
        ctx, _ = make_ctx()
        with mock.patch.object(ch_mod, "wait_confirmation",
                               return_value=True) as wc:
            self.atom.run(ctx, {})
        self.assertEqual(wc.call_args.kwargs["timeout"], 600.0)


class RegistryTest(unittest.TestCase):
    def test_timing_atoms_registered_with_full_contract(self):
        names = registry.names()
        for n in ("sleep", "human_pause", "confirm_human"):
            self.assertIn(n, names)
        catalog = {c["name"]: c for c in registry.catalog()}
        for n, title in (("sleep", "等待"), ("human_pause", "拟人停顿"),
                         ("confirm_human", "人工确认")):
            c = catalog[n]
            self.assertEqual(c["title"], title)
            self.assertEqual(c["param_spec"]["type"], "object")
            self.assertIsInstance(c["inputs"], dict)
            self.assertIsInstance(c["outputs"], dict)


if __name__ == "__main__":
    unittest.main()
