# -*- coding: utf-8 -*-
"""wa_tasks 分段等待助手与风控冷却测试。"""

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
        VALUES (1, 'wa_check', '{"accounts": ["xiaohao-1"]}',
                'pending', '2026-08-05 12:00:00');
        """
    )
    conn.commit()
    conn.close()


class _Base(unittest.TestCase):
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


class RestHeartbeatTest(_Base):
    def test_short_rest_completes_not_interrupted(self):
        stop = threading.Event()
        result = wa_tasks._rest_with_heartbeat(1, 1, "测试", stop)
        self.assertFalse(result)

    def test_interrupted_returns_true(self):
        stop = threading.Event()
        stop.set()
        result = wa_tasks._rest_with_heartbeat(1, 60, "测试", stop)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
