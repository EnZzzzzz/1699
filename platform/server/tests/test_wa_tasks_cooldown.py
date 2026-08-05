# -*- coding: utf-8 -*-
"""wa_tasks 分段等待助手与风控冷却测试。"""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from fetcher.core.types import ActionResult
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


class ThrottleCooldownTest(_Base):
    def _ok(self, results):
        done = sum(1 for r in results if r.get("registered") is not None)
        hits = sum(1 for r in results if r.get("registered"))
        return ActionResult.success("ok", results=results,
                                    checked=done, registered=hits)

    def _rows(self, n=50):
        return [(i, f"86130000000{i:02d}") for i in range(1, n + 1)]

    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
    @patch("app.wa_tasks._fetch_pending_rows")
    @patch("app.wa_tasks.CheckWhatsApp")
    def test_high_error_ratio_triggers_cooldown(self, mock_cls, mock_rows, mock_apply):
        # 100 个号码 = 2 批，冷却在批 1 之后触发（需 bi < len(batches)）
        mock_rows.return_value = self._rows(100)
        # 40 个出错 + 60 个正常 → 错误率 40% ≥ 30%
        results = [{"number": f"8613{i:07d}", "registered": None, "error": "x"}
                   for i in range(40)]
        results += [{"number": f"8614{i:07d}", "registered": False}
                    for i in range(60)]
        mock_cls.return_value.run.return_value = self._ok(results)

        with patch("app.wa_tasks.THROTTLE_COOLDOWN_MIN", 0.01), \
             patch("app.wa_tasks.THROTTLE_COOLDOWN_MAX", 0.02):
            wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())

        conn = sqlite3.connect(self.db)
        warnings = conn.execute(
            "SELECT message FROM task_events WHERE task_id=1 "
            "AND level='warning' AND message LIKE '%风控%'").fetchall()
        conn.close()
        self.assertTrue(any("疑似风控" in w[0] for w in warnings))
        self.assertTrue(any("额外冷却" in w[0] for w in warnings))

    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
    @patch("app.wa_tasks._fetch_pending_rows")
    @patch("app.wa_tasks.CheckWhatsApp")
    def test_low_error_ratio_no_cooldown(self, mock_cls, mock_rows, mock_apply):
        mock_rows.return_value = self._rows()
        results = [{"number": f"8613{i:07d}", "registered": False}
                   for i in range(50)]  # 0 出错
        mock_cls.return_value.run.return_value = self._ok(results)

        wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())

        conn = sqlite3.connect(self.db)
        cools = conn.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id=1 "
            "AND message LIKE '%额外冷却%'").fetchone()
        conn.close()
        self.assertEqual(cools[0], 0)

    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
    @patch("app.wa_tasks._fetch_pending_rows")
    @patch("app.wa_tasks.CheckWhatsApp")
    def test_checked_counts_done_not_batch(self, mock_cls, mock_rows, mock_apply):
        # 2 个号码，1 个出错（registered:null）→ checked 应计 1 而非 2
        mock_rows.return_value = self._rows(2)
        results = [
            {"number": "8613000000001", "registered": False},
            {"number": "8613000000002", "registered": None, "error": "x"},
        ]
        mock_cls.return_value.run.return_value = self._ok(results)

        wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())

        conn = sqlite3.connect(self.db)
        prog = conn.execute(
            "SELECT progress_json FROM tasks WHERE id=1").fetchone()
        conn.close()
        self.assertEqual(json.loads(prog[0])["checked"], 1)


if __name__ == "__main__":
    unittest.main()
