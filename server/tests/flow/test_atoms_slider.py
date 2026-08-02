# -*- coding: utf-8 -*-
"""refresh_page / solve_slider / slider_repair / net_repair 原子单测
（stdlib unittest）。

不触碰真实浏览器 / CloakBrowser / 轨迹库 / 网络：
- refresh_page 用本地 FakePage（reload/evaluate 打桩）
- solve_slider mock _load_slider_mod 返回假 slider_track 模块
- slider_repair / net_repair mock 被委托的原子类，验证分阶段路由
"""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from app.services.flow import registry
from app.services.flow.base import (
    Context,
    OUTCOME_BLOCKED, OUTCOME_NET_ERROR, OUTCOME_OK, OUTCOME_STOPPED,
)
from app.services.flow.atoms.net_repair import NetRepairAtom
from app.services.flow.atoms.refresh_page import RefreshPageAtom
from app.services.flow.atoms.slider_repair import SliderRepairAtom
from app.services.flow.atoms.solve_slider import SolveSliderAtom
from app.services.flow.atoms.swap_ip import SwapIpAtom


class FakeRT:
    def __init__(self):
        self.events = []

    def emit(self, level, message, data=None):
        self.events.append({"level": level, "message": message,
                            "data": data or {}})

    def stop_requested(self):
        return False


def make_ctx(stop=False, rt=None, **resources):
    ev = threading.Event()
    if stop:
        ev.set()
    return Context(task_id=1, rt=rt, resources=resources, stop_event=ev)


class FakePage:
    """refresh_page 用：reload / evaluate / url 打桩。"""

    def __init__(self, text_len=500, reload_error=None):
        self.text_len = text_len
        self.reload_error = reload_error
        self.reload_calls = 0
        self.url = "https://shop1.1688.com/page/contactinfo.htm"

    def reload(self, wait_until=None, timeout=None):
        self.reload_calls += 1
        if self.reload_error is not None:
            raise self.reload_error

    def evaluate(self, js):
        return self.text_len


# ---------------------------------------------------------------- refresh_page

class TestRefreshPage(unittest.TestCase):
    def test_no_page_net_error(self):
        r = RefreshPageAtom().run(make_ctx(), {})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)

    def test_reload_and_render_ok(self):
        ctx = make_ctx(rt=FakeRT(), page=FakePage(text_len=800))
        r = RefreshPageAtom().run(ctx, {"render_wait": 0.5})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertIn("url", r.data)

    def test_reload_raises_net_error(self):
        ctx = make_ctx(rt=FakeRT(),
                       page=FakePage(reload_error=RuntimeError(
                           "net::ERR_CONNECTION_RESET")))
        r = RefreshPageAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)
        self.assertIn("ERR_CONNECTION_RESET", r.detail)

    def test_render_timeout_still_ok(self):
        """刷新成功但页面空白：不算网络故障，如实标记 render_timeout。"""
        ctx = make_ctx(rt=FakeRT(), page=FakePage(text_len=0))
        r = RefreshPageAtom().run(ctx, {"render_wait": 0.02})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertTrue(r.data.get("render_timeout"))

    def test_stopped(self):
        ctx = make_ctx(stop=True, page=FakePage())
        r = RefreshPageAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_STOPPED)


# ---------------------------------------------------------------- solve_slider

def fake_slider_mod(present=True, tracks=(((0, 0, 0),) * 12,), solved=True):
    """构造假 slider_track 模块。"""
    return SimpleNamespace(
        _slider_present=lambda page, sels: present,
        load_tracks=lambda: list(tracks),
        solve_all_sliders=lambda page, max_rounds=3, max_attempts=8: solved,
    )


class TestSolveSlider(unittest.TestCase):
    def _run(self, ctx, params=None, mod=None):
        with mock.patch.object(SolveSliderAtom, "_load_slider_mod",
                               return_value=mod):
            return SolveSliderAtom().run(ctx, params or {})

    def test_no_page_net_error(self):
        r = SolveSliderAtom().run(make_ctx(), {})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)

    def test_no_slider_ok(self):
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        r = self._run(ctx, mod=fake_slider_mod(present=False))
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertFalse(r.data["slider"])

    def test_solved_ok(self):
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        r = self._run(ctx, {"max_attempts": 5},
                      mod=fake_slider_mod(solved=True))
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertTrue(r.data["solved"])

    def test_unsolved_blocked(self):
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        r = self._run(ctx, mod=fake_slider_mod(solved=False))
        self.assertEqual(r.outcome, OUTCOME_BLOCKED)
        self.assertIn("滑块未通过", r.detail)

    def test_tracks_missing_blocked(self):
        mod = fake_slider_mod()
        mod.load_tracks = mock.Mock(
            side_effect=FileNotFoundError("轨迹库不存在"))
        r = self._run(make_ctx(rt=FakeRT(), page=FakePage()), mod=mod)
        self.assertEqual(r.outcome, OUTCOME_BLOCKED)
        self.assertIn("轨迹库不可用", r.detail)

    def test_mod_load_failure_blocked(self):
        with mock.patch.object(SolveSliderAtom, "_load_slider_mod",
                               side_effect=RuntimeError("boom")):
            r = SolveSliderAtom().run(make_ctx(rt=FakeRT(), page=FakePage()), {})
        self.assertEqual(r.outcome, OUTCOME_BLOCKED)
        self.assertIn("模块加载失败", r.detail)


# -------------------------------------------------------------- slider_repair

class TestSliderRepair(unittest.TestCase):
    def test_attempt1_solve_slider(self):
        """阶段 1：前 slider_attempts 次委托 solve_slider。"""
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        with mock.patch.object(SolveSliderAtom, "run",
                               return_value=mock.Mock(
                                   outcome=OUTCOME_OK, ok=True,
                                   detail="滑块验证已通过", data={})) as m, \
             mock.patch.object(RefreshPageAtom, "run") as m_refresh, \
             mock.patch.object(SwapIpAtom, "run") as m_swap:
            r = SliderRepairAtom().run(ctx, {"_attempt": 1})
        self.assertEqual(r.outcome, OUTCOME_OK)
        m.assert_called_once()
        self.assertEqual(r.data["stage"], "slider")
        m_refresh.assert_not_called()
        m_swap.assert_not_called()

    def test_attempt3_wait_then_refresh(self):
        """阶段 2：等待数分钟 + 刷新页面（进度含 {total, elapsed}）。"""
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        with mock.patch.object(SolveSliderAtom, "run") as m_slider, \
             mock.patch.object(RefreshPageAtom, "run",
                               return_value=mock.Mock(
                                   outcome=OUTCOME_OK, ok=True,
                                   detail="页面已刷新", data={})) as m_refresh:
            r = SliderRepairAtom().run(ctx, {
                "_attempt": 3, "wait_min": 0.01, "wait_max": 0.01})
        self.assertEqual(r.outcome, OUTCOME_OK)
        m_slider.assert_not_called()
        m_refresh.assert_called_once()
        self.assertAlmostEqual(ctx.progress["total"], 0.01, places=3)
        # 事件里说明是「等待后刷新」阶段
        warn = [e for e in ctx.rt.events if e["level"] == "warning"]
        self.assertTrue(any("等待" in e["message"] and "刷新" in e["message"]
                            for e in warn))

    def test_attempt4_retry_slider_after_refresh(self):
        """阶段 3：刷新后再过一次滑块（stage=slider_retry）。"""
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        with mock.patch.object(SolveSliderAtom, "run",
                               return_value=mock.Mock(
                                   outcome=OUTCOME_BLOCKED, ok=False,
                                   detail="滑块未通过", data={})) as m:
            r = SliderRepairAtom().run(ctx, {"_attempt": 4})
        m.assert_called_once()
        self.assertEqual(r.data["stage"], "slider_retry")

    def test_attempt5_swap_ip(self):
        """阶段 4：滑块与等待刷新都救不回来 → 委托 swap_ip。"""
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        with mock.patch.object(SwapIpAtom, "run",
                               return_value=mock.Mock(
                                   outcome=OUTCOME_OK, ok=True,
                                   detail="", data={"new_ip": "2.2.2.2"})) as m:
            r = SliderRepairAtom().run(ctx, {"_attempt": 5, "ip_retry": 4})
        self.assertEqual(r.outcome, OUTCOME_OK)
        m.assert_called_once()
        self.assertEqual(m.call_args.args[1]["ip_retry"], 4)

    def test_wait_stage_stopped(self):
        """等待阶段被停止 → OUTCOME_STOPPED（不睡满）。"""
        ctx = make_ctx(stop=True, rt=FakeRT(), page=FakePage())
        r = SliderRepairAtom().run(ctx, {
            "_attempt": 3, "wait_min": 600, "wait_max": 600})
        self.assertEqual(r.outcome, OUTCOME_STOPPED)


# ----------------------------------------------------------------- net_repair

class TestNetRepair(unittest.TestCase):
    def test_attempt1_refresh(self):
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        with mock.patch.object(RefreshPageAtom, "run",
                               return_value=mock.Mock(
                                   outcome=OUTCOME_OK, ok=True,
                                   detail="页面已刷新", data={})) as m_refresh, \
             mock.patch.object(SwapIpAtom, "run") as m_swap:
            r = NetRepairAtom().run(ctx, {"_attempt": 1})
        self.assertEqual(r.outcome, OUTCOME_OK)
        m_refresh.assert_called_once()
        m_swap.assert_not_called()
        self.assertEqual(r.data["stage"], "refresh")

    def test_attempt3_swap_ip(self):
        ctx = make_ctx(rt=FakeRT(), page=FakePage())
        with mock.patch.object(RefreshPageAtom, "run") as m_refresh, \
             mock.patch.object(SwapIpAtom, "run",
                               return_value=mock.Mock(
                                   outcome=OUTCOME_OK, ok=True,
                                   detail="", data={})) as m_swap:
            NetRepairAtom().run(ctx, {"_attempt": 3})
        m_refresh.assert_not_called()
        m_swap.assert_called_once()


# ----------------------------------------------------------- 模板与注册

class TestSliderFlowTemplate(unittest.TestCase):
    def test_new_atoms_registered(self):
        cat = {a["name"]: a for a in registry.catalog()}
        for name in ("refresh_page", "solve_slider", "slider_repair",
                     "net_repair"):
            self.assertIn(name, cat)

    def test_slider_template_valid(self):
        """「联系人提取·滑块自愈」DAG 通过校验，策略接线正确。"""
        from app.services.flow import builtin
        from app.services.flow.dag import validate_or_raise

        dag = builtin.build_contact_fetch_slider_dag()
        validate_or_raise(dag)  # 不抛即通过
        loop = next(n for n in dag["nodes"] if n["id"] == "loop")
        fetch = next(c for c in loop["body"] if c["id"] == "fetch")
        self.assertEqual(fetch["on_blocked"]["do"], "slider_repair")
        self.assertEqual(fetch["on_net_error"]["do"], "net_repair")
        self.assertEqual(fetch["circuit_breaker"]["consecutive_fail"], 6)


if __name__ == "__main__":
    unittest.main()
