# -*- coding: utf-8 -*-
"""block_repair / relaunch_browser 原子单测（stdlib unittest）。

复用 test_atoms_resource 的 fakes（FakePoolClient / FakeBrowser /
FakePage / make_launch / swap_resources）；不触碰真实浏览器/网络/
Redis/SQLite。长休与退避统一经 Context.wait 打桩或传极小休息区间。
"""
from __future__ import annotations

import threading
import unittest
from unittest import mock

from app.services.crawl import browser as browser_mod
from app.services.flow import registry
from app.services.flow.base import (
    Context,
    OUTCOME_NET_ERROR, OUTCOME_OK, OUTCOME_STOPPED,
)
from app.services.flow.atoms.block_repair import BlockRepairAtom
from app.services.flow.atoms.relaunch_browser import RelaunchBrowserAtom
from app.services.flow.atoms.swap_ip import SwapIpAtom

from tests.flow.test_atoms_resource import (
    CH1, FakeBrowser, FakePage, FakePoolClient, make_launch,
    swap_resources,
)


class FakeRT:
    """事件记录（block_repair 的 warning 断言用）。"""

    def __init__(self):
        self.events = []

    def emit(self, level, message, data=None):
        self.events.append({"level": level, "message": message,
                            "data": data or {}})

    def stop_requested(self):
        return False


def make_ctx(stop=False, rt=None, **resources):
    return Context(task_id=1, rt=rt, resources=resources,
                   stop_event=_set_event() if stop else threading.Event())


def _set_event():
    ev = threading.Event()
    ev.set()
    return ev


# ---------------------------------------------------------------- block_repair

class TestBlockRepair(unittest.TestCase):
    def test_attempt1_long_rest(self):
        """一阶段：不换 IP 原地长休，发 warning、报 {total, elapsed} 进度。"""
        rt = FakeRT()
        ctx = make_ctx(rt=rt, **swap_resources())
        with mock.patch.object(SwapIpAtom, "run") as swap_run:
            r = BlockRepairAtom().run(ctx, {
                "_attempt": 1,
                "block_rest_min": 0.01, "block_rest_max": 0.01})
        self.assertEqual(r.outcome, OUTCOME_OK)
        swap_run.assert_not_called()               # 一阶段不换 IP
        warn = [e for e in rt.events if e["level"] == "warning"]
        self.assertTrue(any("蓝本一阶段" in e["message"] for e in warn))
        self.assertIn("保持当前 IP 休息", warn[0]["message"])
        # 进度：total/elapsed 上报且结束时 elapsed == total
        self.assertAlmostEqual(ctx.progress["total"], 0.01, places=3)
        self.assertAlmostEqual(ctx.progress["elapsed"],
                               ctx.progress["total"], places=6)
        self.assertEqual(r.data["attempt"], 1)

    def test_attempt1_default_attempt_is_1(self):
        """未注入 _attempt 时按 1 处理（一阶段长休）。"""
        ctx = make_ctx(rt=FakeRT(), **swap_resources())
        with mock.patch.object(SwapIpAtom, "run") as swap_run:
            r = BlockRepairAtom().run(ctx, {
                "block_rest_min": 0.01, "block_rest_max": 0.01})
        self.assertEqual(r.outcome, OUTCOME_OK)
        swap_run.assert_not_called()
        self.assertEqual(r.data["attempt"], 1)

    def test_attempt2_delegates_swap_ip(self):
        """二阶段：委托 swap_ip（透传 ip_retry/headed/note），结果透传。"""
        ctx = make_ctx(rt=FakeRT(), **swap_resources())
        with mock.patch.object(SwapIpAtom, "run",
                               return_value=mock.Mock(
                                   outcome=OUTCOME_OK, ok=True,
                                   data={"new_ip": "2.2.2.2"})) as swap_run:
            r = BlockRepairAtom().run(ctx, {
                "_attempt": 2, "ip_retry": 5, "headed": True})
        self.assertEqual(r.outcome, OUTCOME_OK)
        swap_run.assert_called_once()
        delegated = swap_run.call_args.args[1]
        self.assertEqual(delegated["ip_retry"], 5)
        self.assertIs(delegated["headed"], True)
        self.assertIn("风控修复", delegated["note"])

    def test_attempt2_swap_failure_passthrough(self):
        """二阶段 swap_ip 失败：outcome 原样透传。"""
        ctx = make_ctx(rt=FakeRT(), **swap_resources())
        with mock.patch.object(SwapIpAtom, "run",
                               return_value=mock.Mock(
                                   outcome=OUTCOME_NET_ERROR, ok=False,
                                   detail="重试 3 次仍失败", data={})):
            r = BlockRepairAtom().run(ctx, {"_attempt": 3})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)

    def test_attempt1_stopped(self):
        """长休期间收到停止 → OUTCOME_STOPPED（不睡满）。"""
        ctx = make_ctx(stop=True, rt=FakeRT(), **swap_resources())
        r = BlockRepairAtom().run(ctx, {
            "_attempt": 1, "block_rest_min": 600, "block_rest_max": 600})
        self.assertEqual(r.outcome, OUTCOME_STOPPED)


# ------------------------------------------------------------ relaunch_browser

class TestRelaunchBrowser(unittest.TestCase):
    def test_success_updates_resources(self):
        """成功路径：回写 Cookie → 关旧浏览器 → 原通道重启，4 键更新，
        不换通道。"""
        old_browser = FakeBrowser()
        pool = FakePoolClient()
        ctx = make_ctx(**swap_resources(pool_client=pool,
                                        browser=old_browser))
        saved = []
        fake = make_launch(identity="1.1.1.1")
        with mock.patch.object(browser_mod, "launch_browser", fake), \
             mock.patch.object(browser_mod, "save_cookies",
                               lambda db, ident, bctx: saved.append(ident) or 0):
            r = RelaunchBrowserAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertEqual(saved, ["1.1.1.1"])          # 旧 Cookie 已回写
        self.assertTrue(old_browser.closed)           # 旧浏览器已关闭
        self.assertEqual(pool.swap_calls, [])         # 不换通道
        res = ctx.resources
        self.assertIsNot(res["browser"], old_browser)  # 4 键更新
        self.assertIsInstance(res["page"], FakePage)
        self.assertEqual(res["identity"], "1.1.1.1")
        self.assertIsNotNone(res["req_proxies"])
        self.assertEqual(r.data["identity"], "1.1.1.1")
        self.assertEqual(r.data["channel_id"], CH1["id"])  # 原通道不变
        # channel 未被替换
        self.assertEqual(res["channel"]["id"], CH1["id"])

    def test_retry_exhausted_net_error(self):
        """重试耗尽 → net_error，identity 不被更新。"""
        ctx = make_ctx(**swap_resources())
        with mock.patch.object(browser_mod, "launch_browser",
                               make_launch(error=RuntimeError("dead"))), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0), \
             mock.patch.object(Context, "wait", return_value=False):
            r = RelaunchBrowserAtom().run(ctx, {"ip_retry": 2})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)
        self.assertIn("重试 2 次", r.detail)
        self.assertIn("dead", r.detail)
        self.assertEqual(ctx.resources["identity"], "1.1.1.1")

    def test_direct_channel_still_relaunches(self):
        """直连通道不退化：照常原通道重启（proxy_server=None）。"""
        pool = FakePoolClient()
        ctx = make_ctx(**swap_resources(
            pool_client=pool, channel={"id": 9, "is_direct": True},
            identity="direct", req_proxies=None))
        seen = {}

        def fake_launch(db, headless=True, proxy_server=None, proxy_auth=None):
            seen["proxy_server"] = proxy_server
            seen["headless"] = headless
            return (FakeBrowser(), FakePage(), "direct", None, None)

        with mock.patch.object(browser_mod, "launch_browser", fake_launch), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0):
            r = RelaunchBrowserAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertIsNone(seen["proxy_server"])     # 直连无代理
        self.assertTrue(seen["headless"])           # headed 默认 False
        self.assertEqual(pool.swap_calls, [])
        self.assertEqual(ctx.resources["identity"], "direct")

    def test_stopped_before_launch(self):
        """停止状态：不启动浏览器 → OUTCOME_STOPPED。"""
        ctx = make_ctx(stop=True, **swap_resources())
        fake = make_launch()
        with mock.patch.object(browser_mod, "launch_browser", fake), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0):
            r = RelaunchBrowserAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_STOPPED)
        self.assertEqual(fake.calls["n"], 0)


# ------------------------------------------------------------- param_spec 声明

class TestParamSpec(unittest.TestCase):
    def test_for_each_shop_has_headed(self):
        """for_each_shop param_spec 声明 headed（dag 校验放行容器有头模式）。"""
        cat = {a["name"]: a for a in registry.catalog()}
        props = cat["for_each_shop"]["param_spec"]["properties"]
        self.assertIn("headed", props)
        self.assertEqual(props["headed"]["type"], "boolean")

    def test_new_atoms_registered(self):
        cat = {a["name"]: a for a in registry.catalog()}
        self.assertIn("block_repair", cat)
        self.assertIn("relaunch_browser", cat)


if __name__ == "__main__":
    unittest.main()
