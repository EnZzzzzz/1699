# -*- coding: utf-8 -*-
"""wa_check 空账号拦截测试。

覆盖：wa_check 任务 accounts 为空时必须拒绝启动（防止静默落到
default 主号导致封号），而不是继续取数运行。
"""

import os
import sqlite3
import tempfile
import threading
import unittest

from app import db, runner, wa_tasks


def _make_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            params_json TEXT NOT NULL,
            celery_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            progress_json TEXT,
            stop_requested INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            flow_id INTEGER
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT
        );
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY,
            mobile TEXT,
            phone TEXT,
            wa_registered INTEGER,
            wa_checked_at TEXT
        );
        INSERT INTO tasks (id, type, params_json, status, created_at)
        VALUES (1, 'wa_check', '{"accounts": []}',
                'pending', '2026-08-05 12:00:00');
        """
    )
    conn.commit()
    conn.close()


class WaaCheckEmptyAccountsGuardTest(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        _make_db(self.db)
        self.old_db = db.DB_PATH
        self.old_runner_db = runner.DB_PATH
        self.old_wa_db = wa_tasks.DB_PATH
        db.DB_PATH = self.db
        runner.DB_PATH = self.db
        wa_tasks.DB_PATH = self.db

    def tearDown(self):
        db.DB_PATH = self.old_db
        runner.DB_PATH = self.old_runner_db
        wa_tasks.DB_PATH = self.old_wa_db
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_empty_accounts_refuses_to_run(self):
        # 若守卫失效，会走到 _fetch_pending_rows → 抛异常使测试失败
        def _boom():
            raise AssertionError("守卫失效：空账号仍然尝试取数运行")
        wa_tasks._fetch_pending_rows = _boom

        stop = threading.Event()
        wa_tasks.run(1, {"accounts": []}, stop)

        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT status, error FROM tasks WHERE id=1").fetchone()
        ev = conn.execute(
            "SELECT level, message FROM task_events "
            "WHERE task_id=1 ORDER BY id LIMIT 1").fetchone()
        conn.close()

        self.assertEqual(row[0], "failed")
        self.assertIn("拒绝启动", row[1])
        self.assertEqual(ev[0], "error")
        self.assertIn("拒绝启动", ev[1])


if __name__ == "__main__":
    unittest.main()
