# -*- coding: utf-8 -*-
"""P4-2 Step 2.2: SSE 批次事件合成 + dispatcher API 测试。

临时 sqlite（patch DB_PATH 四处），验证 finished 项合成事件、
增量游标、daemon 存活判定、queue_depth 聚合、consumers offline 标记。
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.db as db_module
import app.runner as app_runner
import app.api.tasks as api_tasks
import app.api.dispatcher as dispatcher_module

BATCH_QUEUES = {
    "crawl_1688_contact", "crawl_mic_contact", "crawl_1688_shop",
    "crawl_1688_company", "crawl_mic_shop", "wa_check",
}


def _schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL, params_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', progress_json TEXT,
        stop_requested INTEGER NOT NULL DEFAULT 0, error TEXT,
        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
    );
    CREATE TABLE IF NOT EXISTS task_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL, ts TEXT NOT NULL, level TEXT NOT NULL,
        message TEXT, data_json TEXT
    );
    CREATE TABLE IF NOT EXISTS work_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        queue TEXT NOT NULL, site TEXT, batch_id INTEGER,
        payload_json TEXT NOT NULL,
        requires TEXT NOT NULL DEFAULT '["channel","browser"]',
        status TEXT NOT NULL DEFAULT 'pending',
        claimed_by TEXT, claimed_at TEXT, finished_at TEXT,
        result_json TEXT, created_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS consumer_status (
        consumer_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL, tunnel TEXT, exit_ip TEXT,
        current_queue TEXT, current_item_id INTEGER, current_batch_id INTEGER,
        cooldowns_json TEXT, updated_at TEXT NOT NULL
    );
    """)


class DispatcherTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "t.db")
        conn = sqlite3.connect(self.db_path)
        _schema(conn)
        conn.commit()
        conn.close()
        patchers = [
            patch.object(db_module, "DB_PATH", self.db_path),
            patch.object(app_runner, "DB_PATH", self.db_path),
            patch.object(api_tasks, "DB_PATH", self.db_path),
            patch.object(dispatcher_module, "DB_PATH", self.db_path),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _insert_item(self, batch_id, queue="crawl_1688_contact",
                     payload=None, status="done", finished_at=None,
                     result=None, item_id=None):
        conn = self._conn()
        if item_id is not None:
            cur = conn.execute(
                "INSERT INTO work_items (id, queue, site, batch_id,"
                " payload_json, status, finished_at, result_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-08-08 10:00:00')",
                (item_id, queue, "1688", batch_id,
                 json.dumps(payload or {"domain": f"shop{batch_id}.1688.com"}),
                 status, finished_at, result))
        else:
            cur = conn.execute(
                "INSERT INTO work_items (queue, site, batch_id,"
                " payload_json, status, finished_at, result_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, '2026-08-08 10:00:00')",
                (queue, "1688", batch_id,
                 json.dumps(payload or {"domain": f"shop{batch_id}.1688.com"}),
                 status, finished_at, result))
        conn.commit()
        iid = cur.lastrowid
        conn.close()
        return iid

    def _insert_consumer(self, consumer_id, kind="browser", updated_at=None,
                         cooldowns=None):
        conn = self._conn()
        conn.execute(
            "INSERT INTO consumer_status (consumer_id, kind, updated_at,"
            " cooldowns_json) VALUES (?, ?, ?, ?)",
            (consumer_id, kind,
             updated_at or "2026-08-08 10:00:00",
             json.dumps(cooldowns or {})))
        conn.commit()
        conn.close()


# =====================================================================
# 1. SSE 批次事件合成
# =====================================================================


class BatchSSEComposeTest(DispatcherTestBase):
    @staticmethod
    def _row(**kw):
        """构造 sqlite3.Row 风格的合成行（模拟 work_items SELECT）。"""
        base = {"id": 1, "queue": "crawl_1688_contact",
                "status": "done", "payload_json": "{}",
                "result_json": None}
        base.update(kw)
        return base

    def test_compose_finished_item(self):
        """finished 项合成 (message, level)。"""
        from app.api.tasks import _compose_batch_event
        # done：✓ domain
        msg, level = _compose_batch_event(self._row(
            status="done",
            payload_json=json.dumps({"domain": "shop1.1688.com"})))
        self.assertEqual(msg, "✓ shop1.1688.com")
        self.assertEqual(level, "success")
        # failed：✗ domain ... reason
        msg2, level2 = _compose_batch_event(self._row(
            status="failed",
            payload_json=json.dumps({"domain": "shop2.1688.com"}),
            result_json=json.dumps({"reason": "滑块拦截"})))
        self.assertEqual(msg2, "✗ shop2.1688.com ... 滑块拦截")
        self.assertEqual(level2, "error")
        # stopped：⏹ 标识
        msg3, level3 = _compose_batch_event(self._row(
            status="stopped",
            payload_json=json.dumps({"domain": "shop3.1688.com"})))
        self.assertEqual(msg3, "⏹ shop3.1688.com")
        self.assertEqual(level3, "warning")

    def test_fetch_batch_events_replay_and_incremental(self):
        """回放最近 finished + 增量（id > last_id）。"""
        from app.api.tasks import _fetch_batch_events
        self._insert_item(1, finished_at="2026-08-08 10:00:01", item_id=10)
        self._insert_item(1, finished_at="2026-08-08 10:00:02", item_id=11)
        self._insert_item(1, status="pending", item_id=12)  # 非 finished 不含
        events = _fetch_batch_events(1, last_id=0)
        self.assertEqual(len(events), 2)
        self.assertEqual([e["id"] for e in events], [10, 11])
        # 增量：last_id=10 → 只取 11
        inc = _fetch_batch_events(1, last_id=10)
        self.assertEqual([e["id"] for e in inc], [11])

    def test_fetch_batch_events_empty(self):
        from app.api.tasks import _fetch_batch_events
        self.assertEqual(_fetch_batch_events(99, last_id=0), [])


# =====================================================================
# 2. dispatcher/status
# =====================================================================


class DispatcherStatusTest(DispatcherTestBase):
    def _now(self):
        import time
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def test_daemon_alive_when_heartbeat_fresh(self):
        from app.api.dispatcher import daemon_alive
        self._insert_consumer("w0", updated_at=self._now())
        self.assertTrue(daemon_alive())

    def test_daemon_alive_false_when_no_heartbeat(self):
        from app.api.dispatcher import daemon_alive
        self.assertFalse(daemon_alive())  # 无 consumer_status 行
        # 30s 前的心跳视为离线
        import time
        old = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 60))
        self._insert_consumer("w0", updated_at=old)
        self.assertFalse(daemon_alive())

    def test_queue_depth_aggregates(self):
        from app.api.dispatcher import queue_depth
        self._insert_item(1, queue="crawl_1688_contact", status="done",
                          finished_at="2026-08-08 10:00:00")
        self._insert_item(1, queue="crawl_1688_contact", status="pending")
        self._insert_item(1, queue="crawl_mic_shop", status="claimed")
        depth = queue_depth()
        self.assertEqual(depth["crawl_1688_contact"]["done"], 1)
        self.assertEqual(depth["crawl_1688_contact"]["pending"], 1)
        self.assertEqual(depth["crawl_mic_shop"]["claimed"], 1)

    def test_today_done_count(self):
        from app.api.dispatcher import today_done
        import time
        today = time.strftime("%Y-%m-%d")
        self._insert_item(1, status="done",
                          finished_at=f"{today} 10:00:00")
        self._insert_item(1, status="done",
                          finished_at=f"{today} 11:00:00")
        self._insert_item(1, status="done",
                          finished_at="2020-01-01 10:00:00")  # 旧日期不计
        self.assertEqual(today_done(), 2)


# =====================================================================
# 3. dispatcher/consumers
# =====================================================================


class DispatcherConsumersTest(DispatcherTestBase):
    def test_consumers_with_offline_flag(self):
        from app.api.dispatcher import list_consumers
        import time
        fresh = time.strftime("%Y-%m-%d %H:%M:%S")
        old = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 60))
        self._insert_consumer("w0", updated_at=fresh,
                              cooldowns={"1688": 1234.5})
        self._insert_consumer("local0", kind="local", updated_at=old)
        rows = list_consumers()
        by_id = {r["consumer_id"]: r for r in rows}
        self.assertFalse(by_id["w0"]["offline"])
        self.assertTrue(by_id["local0"]["offline"])
        self.assertEqual(by_id["w0"]["cooldowns"], {"1688": 1234.5})


# =====================================================================
# 4. 路由注册
# =====================================================================


class DispatcherRouterTest(unittest.TestCase):
    def test_dispatcher_endpoints_reachable(self):
        """dispatcher 端点经 TestClient 可达（路由注册验证）。"""
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            r = client.get("/api/dispatcher/status")
            self.assertEqual(r.status_code, 200)
            self.assertIn("daemon_alive", r.json())
            r2 = client.get("/api/dispatcher/consumers")
            self.assertEqual(r2.status_code, 200)


if __name__ == "__main__":
    unittest.main()
