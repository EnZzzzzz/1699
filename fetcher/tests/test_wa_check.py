# -*- coding: utf-8 -*-
"""CheckWhatsApp 原子单测：纯逻辑路径，不依赖 node / wa-check 真跑。"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from fetcher.atoms.wa_check import CheckWhatsApp, normalize_numbers, resolve_wa_dir
from fetcher.core.types import Outcome


class FakeCtx:
    def __init__(self, stopped=False):
        self.stop = threading.Event()
        if stopped:
            self.stop.set()
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)

    def wait(self, seconds):
        return self.stop.wait(seconds)

    def stopped(self):
        return self.stop.is_set()


class TestNormalize(unittest.TestCase):
    def test_strip_non_digits(self):
        self.assertEqual(normalize_numbers(["+86 151-5666-7272"]), ["8615156667272"])

    def test_default_cc_for_cn_mobile(self):
        self.assertEqual(
            normalize_numbers(["15156667272"], default_cc="86"), ["8615156667272"])

    def test_no_default_cc_keeps_bare_mobile(self):
        self.assertEqual(normalize_numbers(["15156667272"]), ["15156667272"])

    def test_filter_invalid_and_dedup(self):
        self.assertEqual(
            normalize_numbers(["123", "8615156667272", "8615156667272", "9" * 20]),
            ["8615156667272"])

    def test_empty(self):
        self.assertEqual(normalize_numbers([]), [])
        self.assertEqual(normalize_numbers(None), [])


class TestResolveDir(unittest.TestCase):
    def test_params_win(self):
        self.assertEqual(resolve_wa_dir({"wa_check_dir": "/tmp/x"}), Path("/tmp/x"))

    def test_default_under_vendor(self):
        d = resolve_wa_dir({})
        self.assertEqual(d.name, "wa-check")
        self.assertEqual(d.parent.name, "vendor")


class TestAtomOutcomes(unittest.TestCase):
    def setUp(self):
        self.atom = CheckWhatsApp()

    def test_stopped(self):
        r = self.atom.run(FakeCtx(stopped=True), {"numbers": ["8615156667272"]})
        self.assertIs(r.outcome, Outcome.SKIPPED)

    def test_empty_numbers(self):
        r = self.atom.run(FakeCtx(), {"numbers": ["abc", "123"]})
        self.assertIs(r.outcome, Outcome.EMPTY)

    def test_missing_cli(self):
        r = self.atom.run(FakeCtx(), {
            "numbers": ["8615156667272"], "wa_check_dir": tempfile.gettempdir()})
        self.assertIs(r.outcome, Outcome.FATAL)
        self.assertIn("check.js", r.detail)

    def _fake_wa_dir(self, with_auth=True):
        d = Path(tempfile.mkdtemp(prefix="wa_fake_"))
        (d / "check.js").write_text("// stub", encoding="utf-8")
        (d / "node_modules").mkdir()
        if with_auth:
            (d / "auth_info").mkdir()
        return d

    def test_missing_auth(self):
        d = self._fake_wa_dir(with_auth=False)
        r = self.atom.run(FakeCtx(), {"numbers": ["8615156667272"], "wa_check_dir": d})
        self.assertIs(r.outcome, Outcome.FATAL)
        self.assertIn("未登录", r.detail)

    def test_success_path_with_stubbed_node(self):
        d = self._fake_wa_dir()
        results = [
            {"number": "8615156667272", "registered": False, "jid": None},
            {"number": "8613404221971", "registered": True,
             "jid": "8613404221971@s.whatsapp.net"},
        ]

        def fake_run(cmd, ctx, timeout, *, cwd, results_path, auth_dir=None, extra_env=None):
            Path(results_path).write_text(
                '{"checkedAt": "t", "results": ' +
                '[{"number": "8615156667272", "registered": false, "jid": null},'
                ' {"number": "8613404221971", "registered": true,'
                ' "jid": "8613404221971@s.whatsapp.net"}]}',
                encoding="utf-8")
            return 0, ""

        self.atom._run_node = fake_run  # type: ignore[assignment]
        r = self.atom.run(FakeCtx(), {
            "numbers": ["15156667272", "13404221971"],
            "default_cc": "86", "wa_check_dir": d})
        self.assertIs(r.outcome, Outcome.OK)
        self.assertEqual(r.data["checked"], 2)
        self.assertEqual(r.data["registered"], 1)
        self.assertEqual(r.data["results"], results)

    def test_net_error_on_retry_exhausted(self):
        d = self._fake_wa_dir()
        self.atom._run_node = lambda *a, **k: (1, "错误: 多次重连失败，请稍后重试。")  # type: ignore[assignment]
        r = self.atom.run(FakeCtx(), {"numbers": ["8615156667272"], "wa_check_dir": d})
        self.assertIs(r.outcome, Outcome.NET_ERROR)

    def test_logged_out_is_fatal(self):
        d = self._fake_wa_dir()
        self.atom._run_node = lambda *a, **k: (1, "错误: 已登出。请删除 auth_info 目录")  # type: ignore[assignment]
        r = self.atom.run(FakeCtx(), {"numbers": ["8615156667272"], "wa_check_dir": d})
        self.assertIs(r.outcome, Outcome.FATAL)
        self.assertIn("已登出", r.detail)

    def test_timeout_is_net_error(self):
        d = self._fake_wa_dir()
        self.atom._run_node = lambda *a, **k: (-1, "")  # type: ignore[assignment]
        r = self.atom.run(FakeCtx(), {"numbers": ["8615156667272"], "wa_check_dir": d})
        self.assertIs(r.outcome, Outcome.NET_ERROR)

    def test_interrupted_is_skipped(self):
        d = self._fake_wa_dir()
        self.atom._run_node = lambda *a, **k: (None, "")  # type: ignore[assignment]
        r = self.atom.run(FakeCtx(), {"numbers": ["8615156667272"], "wa_check_dir": d})
        self.assertIs(r.outcome, Outcome.SKIPPED)

    def test_named_account_auth_dir(self):
        """account 参数：会话目录切换为 auth_info-<account>/ 并经 WA_AUTH_DIR 传递。"""
        d = self._fake_wa_dir()
        (d / "auth_info-b").mkdir()
        seen = {}

        def fake_run(cmd, ctx, timeout, *, cwd, results_path, auth_dir=None, extra_env=None):
            seen["auth_dir"] = auth_dir
            Path(results_path).write_text('{"results": []}', encoding="utf-8")
            return 0, ""

        self.atom._run_node = fake_run  # type: ignore[assignment]
        r = self.atom.run(FakeCtx(), {
            "numbers": ["8615156667272"], "wa_check_dir": d, "account": "b"})
        self.assertIs(r.outcome, Outcome.OK)
        self.assertEqual(seen["auth_dir"], d / "auth_info-b")

    def test_named_account_missing_auth(self):
        """account 未登录：FATAL 且提示带 --auth 的登录命令。"""
        d = self._fake_wa_dir()
        r = self.atom.run(FakeCtx(), {
            "numbers": ["8615156667272"], "wa_check_dir": d, "account": "b"})
        self.assertIs(r.outcome, Outcome.FATAL)
        self.assertIn("--auth=b", r.detail)

    def test_timeout_includes_retry_budget(self):
        """超时公式含 +360s 重试预算（重试会拉长单批时长，须计入原子超时）。"""
        d = self._fake_wa_dir()
        seen = {}

        def fake_run(cmd, ctx, timeout, *, cwd, results_path, auth_dir=None, extra_env=None):
            seen["timeout"] = timeout
            Path(results_path).write_text('{"results": []}', encoding="utf-8")
            return 0, ""

        self.atom._run_node = fake_run  # type: ignore[assignment]
        self.atom.run(FakeCtx(), {
            "numbers": ["8615156667272"], "wa_check_dir": d, "sample_max": 1.0})
        base = (60 + 1 * (1.0 + 5)) * 1.2
        self.assertGreaterEqual(seen["timeout"], base + 360)


if __name__ == "__main__":
    unittest.main()
