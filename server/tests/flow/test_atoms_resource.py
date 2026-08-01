# -*- coding: utf-8 -*-
"""资源类原子单测（acquire_channel / launch_browser / swap_ip / ensure_fresh_ip）。

隔离手段：FakePoolClient / FakeBrowser / FakePage + monkeypatch
browser_mod.launch_browser / get_exit_ip / save_cookies；
不触碰真实浏览器、代理、网络、Redis、SQLite。
退避与探测睡眠统一经 mock.patch.object(Context, "wait") 短路。
"""
from __future__ import annotations

import threading
import unittest
from unittest import mock

from app.services.crawl import browser as browser_mod
from app.services.flow.base import (
    Context,
    OUTCOME_EMPTY, OUTCOME_NET_ERROR, OUTCOME_OK, OUTCOME_STOPPED,
)
from app.services.flow.atoms.acquire_channel import AcquireChannelAtom
from app.services.flow.atoms.launch_browser import LaunchBrowserAtom
from app.services.flow.atoms.swap_ip import SwapIpAtom
from app.services.flow.atoms.ensure_fresh_ip import EnsureFreshIpAtom
from app.services.pool_client import PoolAcquireTimeout

# ---------------------------------------------------------------- fakes

CH1 = {"id": 1, "tunnel": "t1:1000", "exit_ip": "1.1.1.1", "provider_id": 1}
CH2 = {"id": 2, "tunnel": "t2:1000", "exit_ip": "2.2.2.2", "provider_id": 1}


class FakeBrowserContext:
    def cookies(self):
        return []


class FakePage:
    def __init__(self):
        self.context = FakeBrowserContext()


class FakeBrowser:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakePoolClient:
    def __init__(self, channels=None, swap_result=None, acquire_error=None):
        self._channels = channels if channels is not None else [CH1]
        self._swap_result = swap_result or (CH2, False)
        self._acquire_error = acquire_error
        self.acquire_calls = []
        self.swap_calls = []

    def acquire(self, n, use_proxy=True, should_stop=None, **kw):
        self.acquire_calls.append({"n": n, "use_proxy": use_proxy})
        if self._acquire_error:
            raise self._acquire_error
        return self._channels

    def channel_proxy(self, channel):
        if channel.get("is_direct") or not channel.get("tunnel"):
            return None, None
        return channel["tunnel"], ("user", "pwd")

    def swap_channel(self, channel):
        self.swap_calls.append(channel)
        return self._swap_result


def make_launch(identity="2.2.2.2", fail_times=0, error=None):
    """构造假的 browser_mod.launch_browser；fail_times 次失败后成功。"""
    calls = {"n": 0}

    def fake_launch(db, headless=True, proxy_server=None, proxy_auth=None):
        calls["n"] += 1
        if error is not None:
            raise error
        if calls["n"] <= fail_times:
            raise RuntimeError(f"launch fail #{calls['n']}")
        return (FakeBrowser(), FakePage(), identity,
                {"http": "http://x", "https": "http://x"}, proxy_server)

    fake_launch.calls = calls
    return fake_launch


def make_ctx(stop=False, **resources):
    return Context(task_id=1, rt=None, resources=resources,
                   stop_event=threading.Event() if not stop else _set_event())


def _set_event():
    ev = threading.Event()
    ev.set()
    return ev


def swap_resources(**over):
    res = {
        "pool_client": FakePoolClient(),
        "channel": dict(CH1),
        "db": object(),
        "browser": FakeBrowser(),
        "page": FakePage(),
        "identity": "1.1.1.1",
        "req_proxies": {"http": "http://old", "https": "http://old"},
    }
    res.update(over)
    return res


# ---------------------------------------------------------------- acquire

class TestAcquireChannel(unittest.TestCase):
    def test_success(self):
        pool = FakePoolClient(channels=[CH1, CH2])
        ctx = make_ctx(pool_client=pool)
        r = AcquireChannelAtom().run(ctx, {"n": 2, "proxy": True})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertTrue(r.ok)
        self.assertEqual(pool.acquire_calls, [{"n": 2, "use_proxy": True}])
        self.assertEqual(ctx.vars["channels"], [CH1, CH2])
        self.assertIs(ctx.resources["channel"], CH1)
        self.assertEqual(r.data["channels"], [CH1, CH2])

    def test_defaults(self):
        pool = FakePoolClient()
        ctx = make_ctx(pool_client=pool)
        r = AcquireChannelAtom().run(ctx, {})
        self.assertTrue(r.ok)
        self.assertEqual(pool.acquire_calls, [{"n": 1, "use_proxy": True}])

    def test_timeout_empty(self):
        pool = FakePoolClient(
            acquire_error=PoolAcquireTimeout("等待 600s 仍未分配到通道"))
        ctx = make_ctx(pool_client=pool)
        r = AcquireChannelAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_EMPTY)
        self.assertIn("仍未分配到通道", r.detail)
        self.assertNotIn("channels", ctx.vars)
        self.assertNotIn("channel", ctx.resources)

    def test_stopped(self):
        pool = FakePoolClient(
            acquire_error=PoolAcquireTimeout("等待通道期间收到停止请求"))
        ctx = make_ctx(stop=True, pool_client=pool)
        r = AcquireChannelAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_STOPPED)
        self.assertIn("停止", r.detail)


# ---------------------------------------------------------------- launch

class TestLaunchBrowser(unittest.TestCase):
    def test_success_with_proxy_channel(self):
        pool = FakePoolClient()
        ctx = make_ctx(pool_client=pool, channel=dict(CH1), db=object())
        with mock.patch.object(browser_mod, "launch_browser",
                               make_launch(identity="1.1.1.1")):
            r = LaunchBrowserAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertEqual(r.data["identity"], "1.1.1.1")
        self.assertIsInstance(ctx.resources["browser"], FakeBrowser)
        self.assertIsInstance(ctx.resources["page"], FakePage)
        self.assertEqual(ctx.resources["identity"], "1.1.1.1")
        self.assertIsNotNone(ctx.resources["req_proxies"])

    def test_success_direct_channel(self):
        pool = FakePoolClient()
        direct = {"id": 9, "is_direct": True}
        ctx = make_ctx(pool_client=pool, channel=direct, db=object())
        fake = make_launch(identity="direct")
        with mock.patch.object(browser_mod, "launch_browser", fake):
            r = LaunchBrowserAtom().run(ctx, {"headed": True})
        self.assertTrue(r.ok)
        self.assertEqual(ctx.resources["identity"], "direct")

    def test_browser_unavailable(self):
        ctx = make_ctx(pool_client=FakePoolClient(), channel=dict(CH1),
                       db=object())
        err = browser_mod.BrowserUnavailable("cloakbrowser 未安装")
        with mock.patch.object(browser_mod, "launch_browser",
                               make_launch(error=err)):
            r = LaunchBrowserAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)
        self.assertIn("cloakbrowser 未安装", r.detail)
        self.assertNotIn("browser", ctx.resources)

    def test_generic_error(self):
        ctx = make_ctx(pool_client=FakePoolClient(), channel=dict(CH1),
                       db=object())
        with mock.patch.object(browser_mod, "launch_browser",
                               make_launch(error=RuntimeError("boom"))):
            r = LaunchBrowserAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)
        self.assertIn("boom", r.detail)


# ---------------------------------------------------------------- swap_ip

class TestSwapIp(unittest.TestCase):
    def test_success_first_try(self):
        old_browser = FakeBrowser()
        ctx = make_ctx(**swap_resources(browser=old_browser))
        saved = []
        fake = make_launch(identity="2.2.2.2")
        with mock.patch.object(browser_mod, "launch_browser", fake), \
             mock.patch.object(browser_mod, "save_cookies",
                               lambda db, ident, bctx: saved.append(ident) or 0):
            r = SwapIpAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertEqual(saved, ["1.1.1.1"])          # 旧 Cookie 已回写
        self.assertTrue(old_browser.closed)           # 旧浏览器已关闭
        pool = ctx.resources["pool_client"]
        self.assertEqual(len(pool.swap_calls), 1)     # 换通道发生
        self.assertEqual(ctx.resources["channel"]["id"], CH2["id"])
        self.assertEqual(ctx.resources["identity"], "2.2.2.2")
        self.assertEqual(r.data["old_ip"], "1.1.1.1")
        self.assertEqual(r.data["new_ip"], "2.2.2.2")
        self.assertEqual(r.data["channel_id"], CH2["id"])
        self.assertEqual(fake.calls["n"], 1)

    def test_retry_then_success(self):
        ctx = make_ctx(**swap_resources())
        fake = make_launch(identity="2.2.2.2", fail_times=2)
        with mock.patch.object(browser_mod, "launch_browser", fake), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0), \
             mock.patch.object(Context, "wait", return_value=False):
            r = SwapIpAtom().run(ctx, {"ip_retry": 3})
        self.assertTrue(r.ok)
        self.assertEqual(fake.calls["n"], 3)          # 第 3 次才成功
        self.assertEqual(ctx.progress["retry"], 2)

    def test_retry_exhausted(self):
        ctx = make_ctx(**swap_resources())
        with mock.patch.object(browser_mod, "launch_browser",
                               make_launch(error=RuntimeError("dead"))), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0), \
             mock.patch.object(Context, "wait", return_value=False):
            r = SwapIpAtom().run(ctx, {"ip_retry": 2})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)
        self.assertIn("重试 2 次", r.detail)
        self.assertIn("dead", r.detail)
        # identity 未被更新
        self.assertEqual(ctx.resources["identity"], "1.1.1.1")

    def test_stopped(self):
        ctx = make_ctx(stop=True, **swap_resources())
        fake = make_launch()
        with mock.patch.object(browser_mod, "launch_browser", fake), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0):
            r = SwapIpAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_STOPPED)
        self.assertEqual(fake.calls["n"], 0)

    def test_swap_channel_failure(self):
        pool = FakePoolClient()
        pool.swap_channel = mock.Mock(side_effect=RuntimeError("api down"))
        ctx = make_ctx(**swap_resources(pool_client=pool))
        with mock.patch.object(browser_mod, "save_cookies", lambda *a: 0):
            r = SwapIpAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)
        self.assertIn("换通道失败", r.detail)

    # ---- 直连通道：退化为停止感知退避（对齐 contact_fetch.py L319-323）----

    def test_direct_channel_degrades_to_backoff(self):
        """直连通道（is_direct）：不换通道/不动浏览器，按 _attempt 退避。"""
        pool = FakePoolClient()
        ctx = make_ctx(**swap_resources(
            channel={"id": 9, "is_direct": True}))
        with mock.patch.object(Context, "wait", return_value=False) as wait, \
             mock.patch.object(browser_mod, "save_cookies") as save, \
             mock.patch.object(browser_mod, "launch_browser") as launch:
            r = SwapIpAtom().run(ctx, {"_attempt": 2})
        self.assertEqual(r.outcome, OUTCOME_OK)
        wait.assert_called_once_with(120)        # min(60*2, 300)
        self.assertEqual(pool.swap_calls, [])    # 不换通道
        save.assert_not_called()                 # 不回写 Cookie
        launch.assert_not_called()               # 不重启浏览器
        self.assertTrue(r.data["direct"])
        self.assertEqual(r.data["backoff"], 120)

    def test_direct_channel_backoff_cap_and_default_attempt(self):
        """无 tunnel 的通道同样算直连；退避 300s 封顶；_attempt 缺省 1。"""
        ctx = make_ctx(**swap_resources(channel={"id": 9}))  # 无 tunnel
        with mock.patch.object(Context, "wait", return_value=False) as wait:
            r = SwapIpAtom().run(ctx, {"_attempt": 10})
        self.assertEqual(r.outcome, OUTCOME_OK)
        wait.assert_called_once_with(300)        # min(600, 300) 封顶
        ctx2 = make_ctx(**swap_resources(channel={"id": 9}))
        with mock.patch.object(Context, "wait", return_value=False) as wait2:
            SwapIpAtom().run(ctx2, {})
        wait2.assert_called_once_with(60)        # 缺省 attempt=1

    def test_direct_channel_stopped_during_backoff(self):
        """退避期间收到停止 → OUTCOME_STOPPED。"""
        ctx = make_ctx(**swap_resources(channel={"id": 9, "is_direct": True}))
        with mock.patch.object(Context, "wait", return_value=True):
            r = SwapIpAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_STOPPED)


# ------------------------------------------------------- ensure_fresh_ip

class TestEnsureFreshIp(unittest.TestCase):
    def test_not_rotated(self):
        ctx = make_ctx(**swap_resources())
        fake = make_launch()
        with mock.patch.object(browser_mod, "get_exit_ip",
                               return_value="1.1.1.1") as m_ip, \
             mock.patch.object(browser_mod, "launch_browser", fake):
            r = EnsureFreshIpAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertEqual(r.data["exit_ip"], "1.1.1.1")
        self.assertFalse(r.data["rotated"])
        self.assertEqual(m_ip.call_count, 1)          # 一次探测即成功
        self.assertEqual(fake.calls["n"], 0)          # 未发生换 IP

    def test_rotated(self):
        ctx = make_ctx(**swap_resources())
        with mock.patch.object(browser_mod, "get_exit_ip",
                               return_value="9.9.9.9"), \
             mock.patch.object(browser_mod, "launch_browser",
                               make_launch(identity="9.9.9.9")), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0), \
             mock.patch.object(Context, "wait", return_value=False):
            r = EnsureFreshIpAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertTrue(r.data["rotated"])
        self.assertEqual(r.data["old_ip"], "1.1.1.1")
        self.assertEqual(r.data["new_ip"], "9.9.9.9")
        self.assertEqual(ctx.resources["identity"], "9.9.9.9")

    def test_query_failed_triggers_swap(self):
        ctx = make_ctx(**swap_resources())
        with mock.patch.object(browser_mod, "get_exit_ip",
                               return_value=None) as m_ip, \
             mock.patch.object(browser_mod, "launch_browser",
                               make_launch(identity="2.2.2.2")), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0), \
             mock.patch.object(Context, "wait", return_value=False):
            r = EnsureFreshIpAtom().run(ctx, {})
        self.assertEqual(m_ip.call_count, 4)          # 1 + 重试 3 次
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertTrue(r.data["rotated"])
        self.assertEqual(ctx.resources["identity"], "2.2.2.2")

    def test_swap_failure_passthrough(self):
        ctx = make_ctx(**swap_resources())
        with mock.patch.object(browser_mod, "get_exit_ip",
                               return_value=None), \
             mock.patch.object(browser_mod, "launch_browser",
                               make_launch(error=RuntimeError("dead"))), \
             mock.patch.object(browser_mod, "save_cookies", lambda *a: 0), \
             mock.patch.object(Context, "wait", return_value=False):
            r = EnsureFreshIpAtom().run(ctx, {"ip_retry": 2})
        self.assertEqual(r.outcome, OUTCOME_NET_ERROR)  # 透传 swap_ip outcome
        self.assertIn("重试 2 次", r.detail)

    def test_direct_mode_skips(self):
        res = swap_resources(req_proxies=None, identity="direct")
        ctx = make_ctx(**res)
        with mock.patch.object(browser_mod, "get_exit_ip") as m_ip:
            r = EnsureFreshIpAtom().run(ctx, {})
        self.assertEqual(r.outcome, OUTCOME_OK)
        self.assertFalse(r.data["rotated"])
        self.assertEqual(m_ip.call_count, 0)


if __name__ == "__main__":
    unittest.main()
