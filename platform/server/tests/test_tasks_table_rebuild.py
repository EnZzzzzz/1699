# -*- coding: utf-8 -*-
"""P5 Step 3.1: tasks 表重建迁移测试（方案 B 交换式）。

覆盖：旧 schema（tasks 带 celery_id/flow_id + flows 表 + task_events/
proxy_channels 子表）跑 migrate() 后——死列删除、flows 表删除、数据无损、
idx_tasks_status 重建、子表外键路径保活；重跑幂等零变化；已迁移库 no-op。
全部用临时 sqlite（patch DB_PATH），绝不碰生产库。
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db as db_module

# 旧 schema（tasks 带 celery_id/flow_id，flows 表，子表外键指向 tasks）
_OLD_SCHEMA = """
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    flow_id INTEGER REFERENCES flows(id)
);
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT
);
CREATE TABLE proxy_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER REFERENCES providers(id),
    tunnel TEXT,
    exit_ip TEXT,
    status TEXT NOT NULL DEFAULT 'idle',
    used_by_task INTEGER REFERENCES tasks(id),
    ip_expires_at TEXT,
    last_probe_at TEXT,
    UNIQUE(provider_id, tunnel)
);
CREATE TABLE flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    dag_json TEXT NOT NULL,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mobile TEXT,
    wa_registered INTEGER,
    wa_checked_at TEXT
);
"""

_NEW_SCHEMA = """
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mobile TEXT,
    wa_registered INTEGER,
    wa_checked_at TEXT
);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT
);
"""


class TasksTableRebuildTest(unittest.TestCase):
    """临时库基座：patch app.db.DB_PATH 指向临时库。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "t.db")
        patcher = patch.object(db_module, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _cols(self, conn, table):
        return {r[1] for r in conn.execute(
            f"PRAGMA table_info({table})")}

    def _tables(self, conn):
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

    def _seed_old(self, conn):
        """建旧 schema + 造数：3 任务（含死列值）、2 事件、1 通道、2 flows。"""
        conn.executescript(_OLD_SCHEMA)
        rows = [
            ("wa_check", '{"numbers":["8613800138000"]}', "done",
             "2026-08-05 02:18:05", "2026-08-05 02:19:00",
             "2026-08-05 02:20:00", "celery-1", 1),
            ("crawl_1688_contact", '{"batch_id":7}', "running",
             "2026-08-05 02:30:00", "2026-08-05 02:31:00", None,
             "celery-2", 2),
            ("crawl_mic_shop", "{}", "failed", "2026-08-05 03:00:00",
             "2026-08-05 03:01:00", "2026-08-05 03:02:00", None, 3),
        ]
        for i, (typ, params, status, created, started, finished,
                celery, flow) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO tasks (id, type, params_json, status,"
                " created_at, started_at, finished_at, celery_id, flow_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (i, typ, params, status, created, started, finished,
                 celery, flow))
        conn.executescript("""
        INSERT INTO task_events (task_id, ts, level, message)
            VALUES (1, '2026-08-05 02:19:00', 'info', 'e1'),
                   (1, '2026-08-05 02:19:30', 'success', 'e2');
        INSERT INTO proxy_channels (provider_id, tunnel, status, used_by_task)
            VALUES (1, 't1', 'in_use', 1);
        INSERT INTO flows (name, dag_json, created_at, updated_at)
            VALUES ('f1', '{}', '2026-08-01 00:00:00', '2026-08-01 00:00:00'),
                   ('f2', '{}', '2026-08-02 00:00:00', '2026-08-02 00:00:00');
        """)
        conn.commit()


class MigrateOldSchemaTest(TasksTableRebuildTest):
    """RED→GREEN 主线：旧 schema 迁移后死列删除、数据无损、外键保活。"""

    def test_migrate_drops_dead_columns_and_flows(self):
        conn = self._conn()
        self._seed_old(conn)
        conn.close()

        db_module.migrate()

        conn = self._conn()
        try:
            cols = self._cols(conn, "tasks")
            self.assertNotIn("celery_id", cols)
            self.assertNotIn("flow_id", cols)
            self.assertNotIn("flows", self._tables(conn))
        finally:
            conn.close()

    def test_migrate_preserves_data_and_index(self):
        conn = self._conn()
        self._seed_old(conn)
        before = conn.execute(
            "SELECT id, type, params_json, status, progress_json,"
            " stop_requested, error, created_at, started_at, finished_at"
            " FROM tasks ORDER BY id").fetchall()
        conn.close()

        db_module.migrate()

        conn = self._conn()
        try:
            after = conn.execute(
                "SELECT id, type, params_json, status, progress_json,"
                " stop_requested, error, created_at, started_at, finished_at"
                " FROM tasks ORDER BY id").fetchall()
            self.assertEqual([tuple(r) for r in before],
                             [tuple(r) for r in after])
            idx = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND tbl_name='tasks'")}
            self.assertIn("idx_tasks_status", idx)
        finally:
            conn.close()

    def test_migrate_keeps_child_fk_paths_alive(self):
        conn = self._conn()
        self._seed_old(conn)
        conn.close()

        db_module.migrate()

        conn = self._conn()
        try:
            # 子表 DDL 仍指向表名 tasks（方案 B 不重写子表定义）
            master = " ".join(
                r[0] for r in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table'"
                    " AND name IN ('task_events','proxy_channels')"))
            self.assertIn("REFERENCES tasks", master)
            # 外键路径实际可用：向子表插入新行成功
            conn.execute("INSERT INTO task_events (task_id, ts, level,"
                         " message) VALUES (1, '2026-08-06 00:00:00',"
                         " 'info', 'after-migrate')")
            conn.execute("INSERT INTO proxy_channels (provider_id, tunnel,"
                         " status, used_by_task) VALUES (1, 't2', 'idle', 2)")
            conn.commit()
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM task_events").fetchone()[0], 3)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM proxy_channels").fetchone()[0], 2)
        finally:
            conn.close()


class IdempotentTest(TasksTableRebuildTest):
    """对已迁移库重跑 migrate() 零变化。"""

    def test_rerun_migrate_is_noop(self):
        conn = self._conn()
        self._seed_old(conn)
        conn.close()

        db_module.migrate()
        conn = self._conn()
        snapshot = conn.execute(
            "SELECT id, type, params_json, status, progress_json,"
            " stop_requested, error, created_at, started_at, finished_at"
            " FROM tasks ORDER BY id").fetchall()
        conn.close()

        db_module.migrate()  # 重跑

        conn = self._conn()
        try:
            self.assertNotIn("celery_id", self._cols(conn, "tasks"))
            self.assertNotIn("flow_id", self._cols(conn, "tasks"))
            self.assertNotIn("flows", self._tables(conn))
            after = conn.execute(
                "SELECT id, type, params_json, status, progress_json,"
                " stop_requested, error, created_at, started_at, finished_at"
                " FROM tasks ORDER BY id").fetchall()
            self.assertEqual([tuple(r) for r in snapshot],
                             [tuple(r) for r in after])
        finally:
            conn.close()


class NewSchemaNoopTest(TasksTableRebuildTest):
    """已迁移库（新 schema 无死列）跑 migrate() 零变化。"""

    def test_migrate_on_new_schema_is_noop(self):
        conn = self._conn()
        conn.executescript(_NEW_SCHEMA)
        conn.execute(
            "INSERT INTO tasks (type, params_json, status, created_at)"
            " VALUES ('wa_check', '{}', 'pending', '2026-08-05 02:00:00')")
        conn.commit()
        before_cols = self._cols(conn, "tasks")
        before_rows = conn.execute("SELECT * FROM tasks").fetchall()
        conn.close()

        db_module.migrate()

        conn = self._conn()
        try:
            self.assertEqual(self._cols(conn, "tasks"), before_cols)
            self.assertEqual(conn.execute("SELECT * FROM tasks").fetchall(),
                             before_rows)
        finally:
            conn.close()


class RollbackTest(TasksTableRebuildTest):
    """失败回滚：DROP 处抛异常 → ROLLBACK 后原表（含死列与数据）保留。"""

    def test_migrate_rollback_keeps_original_tasks(self):
        conn = self._conn()
        self._seed_old(conn)
        conn.close()

        class FlakyConn(sqlite3.Connection):
            """在 DROP TABLE tasks 处抛异常的连接（模拟中途失败）。"""
            def execute(self, sql, parameters=()):
                if isinstance(sql, str) and sql.strip().upper().startswith(
                        "DROP TABLE TASKS"):
                    raise RuntimeError("simulated drop failure")
                return super().execute(sql, parameters)

        real_connect = sqlite3.connect

        def flaky_connect(path, timeout=30, **kw):
            return real_connect(path, timeout=timeout, factory=FlakyConn)

        with patch("sqlite3.connect", side_effect=flaky_connect):
            with self.assertRaises(RuntimeError):
                db_module.migrate()

        conn = self._conn()
        try:
            # 原表保留：死列仍在、数据未丢、flows 未删
            cols = self._cols(conn, "tasks")
            self.assertIn("celery_id", cols)
            self.assertIn("flow_id", cols)
            self.assertIn("flows", self._tables(conn))
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM tasks").fetchone()[0], 3)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM task_events").fetchone()[0], 2)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
