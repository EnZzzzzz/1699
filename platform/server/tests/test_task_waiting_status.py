# -*- coding: utf-8 -*-
"""循环等待状态（waiting）派生逻辑测试。

覆盖：任务 done/failed 但带 repeat_interval、未手动停止时，API 层应把
状态派生为 "waiting" 并给出 next_restart_at。前端据此显示「等待重启」，
SSE 也不把它当终态关流（waiting 不在 done/failed/stopped 终态集合内）。
"""

import json
import unittest

from app.api.tasks import _loop_wait, _row_to_task


def _row(status, params=None, stop_requested=0,
         finished_at="2026-08-05 10:21:47"):
    return {
        "id": 72,
        "type": "1688_contact",
        "params_json": json.dumps(params or {}),
        "progress_json": None,
        "status": status,
        "stop_requested": stop_requested,
        "finished_at": finished_at,
        "started_at": "2026-08-05 10:19:43",
        "created_at": "2026-08-05 02:18:05",
        "error": None,
    }


class LoopWaitStatusTest(unittest.TestCase):
    def test_done_with_repeat_interval_is_waiting(self):
        """done + repeat_interval → waiting，next_restart_at = finished + interval。"""
        eff, next_at = _loop_wait(_row("done", {"repeat_interval": 1800}))
        self.assertEqual(eff, "waiting")
        self.assertEqual(next_at, "2026-08-05 10:51:47")

    def test_done_without_repeat_interval_not_waiting(self):
        """非循环任务不进入等待态。"""
        self.assertEqual(_loop_wait(_row("done", {"workers": 4})),
                         (None, None))

    def test_failed_with_repeat_interval_is_waiting(self):
        """failed + repeat_interval 也进入等待态（会自动重跑）。"""
        eff, _ = _loop_wait(_row("failed", {"repeat_interval": 60}))
        self.assertEqual(eff, "waiting")

    def test_stopped_or_stop_requested_not_waiting(self):
        """手动停止（stop_requested=1）或已 stopped 的不进入等待态。"""
        self.assertEqual(
            _loop_wait(_row("done", {"repeat_interval": 1800},
                            stop_requested=1)), (None, None))
        self.assertEqual(
            _loop_wait(_row("stopped", {"repeat_interval": 1800})),
            (None, None))

    def test_running_not_waiting(self):
        self.assertEqual(
            _loop_wait(_row("running", {"repeat_interval": 1800})),
            (None, None))

    def test_loop_wait_accepts_sqlite3_row(self):
        """回归：生产传入的是 sqlite3.Row（无 .get 方法），须能兼容。"""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT 'done' AS status, 0 AS stop_requested, "
            "'{\"repeat_interval\": 1800}' AS params_json, "
            "'2026-08-05 10:21:47' AS finished_at"
        ).fetchone()
        eff, next_at = _loop_wait(row)
        self.assertEqual(eff, "waiting")
        self.assertEqual(next_at, "2026-08-05 10:51:47")

    def test_row_to_task_sets_waiting_status(self):
        """列表/详情接口：循环等待任务报告为 waiting + next_restart_at。"""
        t = _row_to_task(_row("done", {"repeat_interval": 1800}))
        self.assertEqual(t["status"], "waiting")
        self.assertEqual(t["next_restart_at"], "2026-08-05 10:51:47")

    def test_row_to_task_non_loop_keeps_status(self):
        """非循环任务保持原状态，next_restart_at 为 None。"""
        t = _row_to_task(_row("done", {"workers": 4}))
        self.assertEqual(t["status"], "done")
        self.assertIsNone(t["next_restart_at"])


if __name__ == "__main__":
    unittest.main()
