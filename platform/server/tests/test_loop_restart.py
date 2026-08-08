# -*- coding: utf-8 -*-
"""循环重启恢复逻辑测试。

覆盖 bug：任务 done 后按 repeat_interval 等待自动重启，期间服务重启，
内存 Timer 丢失且无恢复 → 任务永远停在 done（任务 #72 实测）。
修复后 startup() 会把 done/failed + stop_requested=0 + 带 repeat_interval
的任务重新安排自动重启定时器。
"""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app import runner
from app.runner import TaskRunner

BJ_TZ = timezone(timedelta(hours=8))


def _make_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            params_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            progress_json TEXT,
            stop_requested INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _ts(delta: timedelta) -> str:
    return (datetime.now(BJ_TZ) - delta).strftime("%Y-%m-%d %H:%M:%S")


class LoopRestartRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = f"{self.tmp.name}/test.db"
        _make_db(self.db)
        # 把 runner 的 DB / migrate 指向测试库，避免触碰生产库
        self.old_db_path = runner.DB_PATH
        self.old_migrate = runner.migrate
        runner.DB_PATH = self.db
        runner.migrate = lambda: None
        self.task_runner = TaskRunner()

    def tearDown(self):
        self.task_runner.shutdown()
        runner.DB_PATH = self.old_db_path
        runner.migrate = self.old_migrate
        self.tmp.cleanup()

    def _insert_task(self, task_id, status, params, stop_requested=0,
                     finished_delta=None):
        finished_at = _ts(finished_delta) if finished_delta is not None else None
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "INSERT INTO tasks (id, type, params_json, status, "
                "stop_requested, created_at, started_at, finished_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (task_id, "1688_contact", json.dumps(params), status,
                 stop_requested, _ts(timedelta(0)), _ts(timedelta(0)),
                 finished_at))
            conn.commit()
        finally:
            conn.close()

    def test_startup_restores_loop_restart_after_done(self):
        """回归：done + repeat_interval 的任务，服务重启后要重新安排自动重启。"""
        self._insert_task(1, "done", {"repeat_interval": 1800},
                          finished_delta=timedelta(seconds=10))
        self.task_runner.startup()
        self.assertTrue(self.task_runner.has_pending_timer(1))

    def test_startup_skips_task_without_repeat_interval(self):
        """非循环任务不恢复。"""
        self._insert_task(1, "done", {"workers": 4},
                          finished_delta=timedelta(seconds=10))
        self.task_runner.startup()
        self.assertFalse(self.task_runner.has_pending_timer(1))

    def test_startup_skips_manually_stopped_task(self):
        """手动停止（stop_requested=1）的循环任务不恢复。"""
        self._insert_task(1, "done", {"repeat_interval": 1800},
                          stop_requested=1, finished_delta=timedelta(seconds=10))
        self.task_runner.startup()
        self.assertFalse(self.task_runner.has_pending_timer(1))

    def test_startup_overdue_loop_restarts_immediately(self):
        """宕机时长已超过间隔：剩余等待为 0，立即重启。"""
        self._insert_task(1, "done", {"repeat_interval": 1800},
                          finished_delta=timedelta(seconds=1800 + 100))
        # stub 掉真实 Timer，避免 0 秒定时器在 teardown 时后台触发
        scheduled = []
        self.task_runner._schedule_restart = (
            lambda task_id, delay: scheduled.append((task_id, delay)))
        self.task_runner._recover_loop_restarts()
        self.assertEqual(scheduled, [(1, 0)])

    def test_startup_keeps_remaining_wait_when_not_yet_due(self):
        """服务只重启了几秒：仍按原节奏补足剩余等待，不提前重启。"""
        self._insert_task(1, "done", {"repeat_interval": 1800},
                          finished_delta=timedelta(seconds=10))
        scheduled = []
        self.task_runner._schedule_restart = (
            lambda task_id, delay: scheduled.append((task_id, delay)))
        self.task_runner._recover_loop_restarts()
        self.assertEqual(len(scheduled), 1)
        task_id, delay = scheduled[0]
        self.assertEqual(task_id, 1)
        self.assertGreater(delay, 0)
        self.assertLessEqual(delay, 1800)


if __name__ == "__main__":
    unittest.main()
