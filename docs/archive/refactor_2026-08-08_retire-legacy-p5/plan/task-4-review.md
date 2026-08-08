# Review package — Step 3.1 (BASE 2fdb1334b96a78c35b4a67e78a0531216be82403..HEAD)

## git log
61d6758 refactor(p5): tasks 表重建迁移——删 celery_id/flow_id 死列与 flows 表（方案 B 交换式）

## git diff --stat
 platform/server/app/db.py                         |  38 +++
 platform/server/tests/test_batch_tasks.py         |   4 +-
 platform/server/tests/test_dispatcher_api.py      |   5 +-
 platform/server/tests/test_loop_restart.py        |   4 +-
 platform/server/tests/test_task_waiting_status.py |   2 -
 platform/server/tests/test_tasks_table_rebuild.py | 345 ++++++++++++++++++++++
 6 files changed, 387 insertions(+), 11 deletions(-)

## git diff -U10
diff --git a/platform/server/app/db.py b/platform/server/app/db.py
index e441abb..ee6d11d 100644
--- a/platform/server/app/db.py
+++ b/platform/server/app/db.py
@@ -90,20 +90,58 @@ def migrate() -> None:
             "CREATE INDEX IF NOT EXISTS idx_channels_task"
             " ON proxy_channels(used_by_task)")
         # P4：work_items 批次索引（生产库表由 fetcher 建，平台只补索引不建表；
         # 探测式——表不存在则跳过，防御性）
         tables = {r[0] for r in conn.execute(
             "SELECT name FROM sqlite_master WHERE type='table'")}
         if "work_items" in tables:
             conn.execute(
                 "CREATE INDEX IF NOT EXISTS idx_work_items_batch"
                 " ON work_items(batch_id, status)")
+        # P5：tasks 表重建——删除 celery_id/flow_id 死列与 flows 表（方案 B 交换式）
+        # 守卫：旧 schema 才重建；已迁移库重跑 migrate() 零变化（幂等）。
+        # 交换顺序（建 tasks_new → INSERT SELECT → DROP tasks → RENAME）保证
+        # task_events/proxy_channels 的 REFERENCES tasks(id) 不被 SQLite RENAME
+        # 重写成指向被删表名（RENAME-first 会让外键悬空）。
+        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
+        if "celery_id" in cols:
+            conn.execute("BEGIN IMMEDIATE")
+            try:
+                conn.execute("""
+                    CREATE TABLE tasks_new (
+                        id INTEGER PRIMARY KEY AUTOINCREMENT,
+                        type TEXT NOT NULL,
+                        params_json TEXT NOT NULL,
+                        status TEXT NOT NULL DEFAULT 'pending',
+                        progress_json TEXT,
+                        stop_requested INTEGER NOT NULL DEFAULT 0,
+                        error TEXT,
+                        created_at TEXT NOT NULL,
+                        started_at TEXT,
+                        finished_at TEXT
+                    )""")
+                conn.execute("""
+                    INSERT INTO tasks_new (id, type, params_json, status,
+                                           progress_json, stop_requested, error,
+                                           created_at, started_at, finished_at)
+                    SELECT id, type, params_json, status, progress_json,
+                           stop_requested, error, created_at, started_at,
+                           finished_at
+                    FROM tasks""")
+                conn.execute("DROP TABLE tasks")
+                conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
+                conn.execute("DROP TABLE IF EXISTS flows")
+                conn.execute("CREATE INDEX idx_tasks_status ON tasks(status)")
+                conn.execute("COMMIT")
+            except Exception:
+                conn.execute("ROLLBACK")  # 失败留原表（tasks 未动）
+                raise
         conn.commit()
     finally:
         conn.close()
 
 
 # ==================== P4 批次入队（平台侧 SQL，与 fetcher 同事务语义） ====================
 # SPEC §3.1 裁定：平台不 import fetcher，批次 SQL 平台侧重写；两边重复
 # 是有意为之的边界，语义由同一 SPEC + 测试锚定。
 
 
diff --git a/platform/server/tests/test_batch_tasks.py b/platform/server/tests/test_batch_tasks.py
index 752dbf7..22df547 100644
--- a/platform/server/tests/test_batch_tasks.py
+++ b/platform/server/tests/test_batch_tasks.py
@@ -20,29 +20,27 @@ import app.db as app_db
 import app.runner as app_runner
 from app import db as db_module
 
 
 def _schema(conn):
     conn.executescript("""
     CREATE TABLE IF NOT EXISTS tasks (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         type TEXT NOT NULL,
         params_json TEXT NOT NULL,
-        celery_id TEXT,
         status TEXT NOT NULL DEFAULT 'pending',
         progress_json TEXT,
         stop_requested INTEGER NOT NULL DEFAULT 0,
         error TEXT,
         created_at TEXT NOT NULL,
         started_at TEXT,
-        finished_at TEXT,
-        flow_id INTEGER
+        finished_at TEXT
     );
     CREATE TABLE IF NOT EXISTS task_events (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         task_id INTEGER NOT NULL,
         ts TEXT NOT NULL,
         level TEXT NOT NULL,
         message TEXT,
         data_json TEXT
     );
     CREATE TABLE IF NOT EXISTS shops (
diff --git a/platform/server/tests/test_dispatcher_api.py b/platform/server/tests/test_dispatcher_api.py
index c30b441..eb7c696 100644
--- a/platform/server/tests/test_dispatcher_api.py
+++ b/platform/server/tests/test_dispatcher_api.py
@@ -20,25 +20,24 @@ import app.api.dispatcher as dispatcher_module
 BATCH_QUEUES = {
     "crawl_1688_contact", "crawl_mic_contact", "crawl_1688_shop",
     "crawl_1688_company", "crawl_mic_shop", "wa_check",
 }
 
 
 def _schema(conn):
     conn.executescript("""
     CREATE TABLE IF NOT EXISTS tasks (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
-        type TEXT NOT NULL, params_json TEXT NOT NULL, celery_id TEXT,
+        type TEXT NOT NULL, params_json TEXT NOT NULL,
         status TEXT NOT NULL DEFAULT 'pending', progress_json TEXT,
         stop_requested INTEGER NOT NULL DEFAULT 0, error TEXT,
-        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
-        flow_id INTEGER
+        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
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
diff --git a/platform/server/tests/test_loop_restart.py b/platform/server/tests/test_loop_restart.py
index a2de2e2..29bee03 100644
--- a/platform/server/tests/test_loop_restart.py
+++ b/platform/server/tests/test_loop_restart.py
@@ -20,29 +20,27 @@ BJ_TZ = timezone(timedelta(hours=8))
 
 
 def _make_db(path: str) -> None:
     conn = sqlite3.connect(path)
     conn.executescript(
         """
         CREATE TABLE tasks (
             id INTEGER PRIMARY KEY,
             type TEXT NOT NULL,
             params_json TEXT NOT NULL,
-            celery_id TEXT,
             status TEXT NOT NULL DEFAULT 'pending',
             progress_json TEXT,
             stop_requested INTEGER NOT NULL DEFAULT 0,
             error TEXT,
             created_at TEXT NOT NULL,
             started_at TEXT,
-            finished_at TEXT,
-            flow_id INTEGER
+            finished_at TEXT
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
diff --git a/platform/server/tests/test_task_waiting_status.py b/platform/server/tests/test_task_waiting_status.py
index 0fb3cdf..93ef0c5 100644
--- a/platform/server/tests/test_task_waiting_status.py
+++ b/platform/server/tests/test_task_waiting_status.py
@@ -18,22 +18,20 @@ def _row(status, params=None, stop_requested=0,
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
-        "celery_id": None,
-        "flow_id": None,
     }
 
 
 class LoopWaitStatusTest(unittest.TestCase):
     def test_done_with_repeat_interval_is_waiting(self):
         """done + repeat_interval → waiting，next_restart_at = finished + interval。"""
         eff, next_at = _loop_wait(_row("done", {"repeat_interval": 1800}))
         self.assertEqual(eff, "waiting")
         self.assertEqual(next_at, "2026-08-05 10:51:47")
 
diff --git a/platform/server/tests/test_tasks_table_rebuild.py b/platform/server/tests/test_tasks_table_rebuild.py
new file mode 100644
index 0000000..f36cc72
--- /dev/null
+++ b/platform/server/tests/test_tasks_table_rebuild.py
@@ -0,0 +1,345 @@
+# -*- coding: utf-8 -*-
+"""P5 Step 3.1: tasks 表重建迁移测试（方案 B 交换式）。
+
+覆盖：旧 schema（tasks 带 celery_id/flow_id + flows 表 + task_events/
+proxy_channels 子表）跑 migrate() 后——死列删除、flows 表删除、数据无损、
+idx_tasks_status 重建、子表外键路径保活；重跑幂等零变化；已迁移库 no-op。
+全部用临时 sqlite（patch DB_PATH），绝不碰生产库。
+"""
+
+import sqlite3
+import tempfile
+import unittest
+from pathlib import Path
+from unittest.mock import patch
+
+from app import db as db_module
+
+# 旧 schema（tasks 带 celery_id/flow_id，flows 表，子表外键指向 tasks）
+_OLD_SCHEMA = """
+CREATE TABLE tasks (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    type TEXT NOT NULL,
+    params_json TEXT NOT NULL,
+    celery_id TEXT,
+    status TEXT NOT NULL DEFAULT 'pending',
+    progress_json TEXT,
+    stop_requested INTEGER NOT NULL DEFAULT 0,
+    error TEXT,
+    created_at TEXT NOT NULL,
+    started_at TEXT,
+    finished_at TEXT,
+    flow_id INTEGER REFERENCES flows(id)
+);
+CREATE TABLE task_events (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    task_id INTEGER NOT NULL REFERENCES tasks(id),
+    ts TEXT NOT NULL,
+    level TEXT NOT NULL,
+    message TEXT NOT NULL,
+    data_json TEXT
+);
+CREATE TABLE proxy_channels (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    provider_id INTEGER REFERENCES providers(id),
+    tunnel TEXT,
+    exit_ip TEXT,
+    status TEXT NOT NULL DEFAULT 'idle',
+    used_by_task INTEGER REFERENCES tasks(id),
+    ip_expires_at TEXT,
+    last_probe_at TEXT,
+    UNIQUE(provider_id, tunnel)
+);
+CREATE TABLE flows (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    name TEXT NOT NULL,
+    description TEXT,
+    dag_json TEXT NOT NULL,
+    builtin INTEGER NOT NULL DEFAULT 0,
+    created_at TEXT NOT NULL,
+    updated_at TEXT NOT NULL
+);
+CREATE TABLE providers (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    kind TEXT NOT NULL,
+    name TEXT NOT NULL,
+    config_json TEXT NOT NULL,
+    enabled INTEGER NOT NULL DEFAULT 1,
+    created_at TEXT NOT NULL,
+    updated_at TEXT NOT NULL
+);
+CREATE TABLE contacts (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    mobile TEXT,
+    wa_registered INTEGER,
+    wa_checked_at TEXT
+);
+"""
+
+_NEW_SCHEMA = """
+CREATE TABLE contacts (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    mobile TEXT,
+    wa_registered INTEGER,
+    wa_checked_at TEXT
+);
+CREATE TABLE tasks (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    type TEXT NOT NULL,
+    params_json TEXT NOT NULL,
+    status TEXT NOT NULL DEFAULT 'pending',
+    progress_json TEXT,
+    stop_requested INTEGER NOT NULL DEFAULT 0,
+    error TEXT,
+    created_at TEXT NOT NULL,
+    started_at TEXT,
+    finished_at TEXT
+);
+CREATE INDEX idx_tasks_status ON tasks(status);
+CREATE TABLE task_events (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    task_id INTEGER NOT NULL REFERENCES tasks(id),
+    ts TEXT NOT NULL,
+    level TEXT NOT NULL,
+    message TEXT NOT NULL,
+    data_json TEXT
+);
+"""
+
+
+class TasksTableRebuildTest(unittest.TestCase):
+    """临时库基座：patch app.db.DB_PATH 指向临时库。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = str(Path(self._tmp.name) / "t.db")
+        patcher = patch.object(db_module, "DB_PATH", self.db_path)
+        patcher.start()
+        self.addCleanup(patcher.stop)
+
+    def tearDown(self):
+        self._tmp.cleanup()
+
+    def _conn(self):
+        conn = sqlite3.connect(self.db_path)
+        conn.row_factory = sqlite3.Row
+        conn.execute("PRAGMA busy_timeout = 30000")
+        return conn
+
+    def _cols(self, conn, table):
+        return {r[1] for r in conn.execute(
+            f"PRAGMA table_info({table})")}
+
+    def _tables(self, conn):
+        return {r[0] for r in conn.execute(
+            "SELECT name FROM sqlite_master WHERE type='table'")}
+
+    def _seed_old(self, conn):
+        """建旧 schema + 造数：3 任务（含死列值）、2 事件、1 通道、2 flows。"""
+        conn.executescript(_OLD_SCHEMA)
+        rows = [
+            ("wa_check", '{"numbers":["8613800138000"]}', "done",
+             "2026-08-05 02:18:05", "2026-08-05 02:19:00",
+             "2026-08-05 02:20:00", "celery-1", 1),
+            ("crawl_1688_contact", '{"batch_id":7}', "running",
+             "2026-08-05 02:30:00", "2026-08-05 02:31:00", None,
+             "celery-2", 2),
+            ("crawl_mic_shop", "{}", "failed", "2026-08-05 03:00:00",
+             "2026-08-05 03:01:00", "2026-08-05 03:02:00", None, 3),
+        ]
+        for i, (typ, params, status, created, started, finished,
+                celery, flow) in enumerate(rows, start=1):
+            conn.execute(
+                "INSERT INTO tasks (id, type, params_json, status,"
+                " created_at, started_at, finished_at, celery_id, flow_id)"
+                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
+                (i, typ, params, status, created, started, finished,
+                 celery, flow))
+        conn.executescript("""
+        INSERT INTO task_events (task_id, ts, level, message)
+            VALUES (1, '2026-08-05 02:19:00', 'info', 'e1'),
+                   (1, '2026-08-05 02:19:30', 'success', 'e2');
+        INSERT INTO proxy_channels (provider_id, tunnel, status, used_by_task)
+            VALUES (1, 't1', 'in_use', 1);
+        INSERT INTO flows (name, dag_json, created_at, updated_at)
+            VALUES ('f1', '{}', '2026-08-01 00:00:00', '2026-08-01 00:00:00'),
+                   ('f2', '{}', '2026-08-02 00:00:00', '2026-08-02 00:00:00');
+        """)
+        conn.commit()
+
+
+class MigrateOldSchemaTest(TasksTableRebuildTest):
+    """RED→GREEN 主线：旧 schema 迁移后死列删除、数据无损、外键保活。"""
+
+    def test_migrate_drops_dead_columns_and_flows(self):
+        conn = self._conn()
+        self._seed_old(conn)
+        conn.close()
+
+        db_module.migrate()
+
+        conn = self._conn()
+        try:
+            cols = self._cols(conn, "tasks")
+            self.assertNotIn("celery_id", cols)
+            self.assertNotIn("flow_id", cols)
+            self.assertNotIn("flows", self._tables(conn))
+        finally:
+            conn.close()
+
+    def test_migrate_preserves_data_and_index(self):
+        conn = self._conn()
+        self._seed_old(conn)
+        before = conn.execute(
+            "SELECT id, type, params_json, status, progress_json,"
+            " stop_requested, error, created_at, started_at, finished_at"
+            " FROM tasks ORDER BY id").fetchall()
+        conn.close()
+
+        db_module.migrate()
+
+        conn = self._conn()
+        try:
+            after = conn.execute(
+                "SELECT id, type, params_json, status, progress_json,"
+                " stop_requested, error, created_at, started_at, finished_at"
+                " FROM tasks ORDER BY id").fetchall()
+            self.assertEqual([tuple(r) for r in before],
+                             [tuple(r) for r in after])
+            idx = {r[0] for r in conn.execute(
+                "SELECT name FROM sqlite_master WHERE type='index'"
+                " AND tbl_name='tasks'")}
+            self.assertIn("idx_tasks_status", idx)
+        finally:
+            conn.close()
+
+    def test_migrate_keeps_child_fk_paths_alive(self):
+        conn = self._conn()
+        self._seed_old(conn)
+        conn.close()
+
+        db_module.migrate()
+
+        conn = self._conn()
+        try:
+            # 子表 DDL 仍指向表名 tasks（方案 B 不重写子表定义）
+            master = " ".join(
+                r[0] for r in conn.execute(
+                    "SELECT sql FROM sqlite_master WHERE type='table'"
+                    " AND name IN ('task_events','proxy_channels')"))
+            self.assertIn("REFERENCES tasks", master)
+            # 外键路径实际可用：向子表插入新行成功
+            conn.execute("INSERT INTO task_events (task_id, ts, level,"
+                         " message) VALUES (1, '2026-08-06 00:00:00',"
+                         " 'info', 'after-migrate')")
+            conn.execute("INSERT INTO proxy_channels (provider_id, tunnel,"
+                         " status, used_by_task) VALUES (1, 't2', 'idle', 2)")
+            conn.commit()
+            self.assertEqual(conn.execute(
+                "SELECT COUNT(*) FROM task_events").fetchone()[0], 3)
+            self.assertEqual(conn.execute(
+                "SELECT COUNT(*) FROM proxy_channels").fetchone()[0], 2)
+        finally:
+            conn.close()
+
+
+class IdempotentTest(TasksTableRebuildTest):
+    """对已迁移库重跑 migrate() 零变化。"""
+
+    def test_rerun_migrate_is_noop(self):
+        conn = self._conn()
+        self._seed_old(conn)
+        conn.close()
+
+        db_module.migrate()
+        conn = self._conn()
+        snapshot = conn.execute(
+            "SELECT id, type, params_json, status, progress_json,"
+            " stop_requested, error, created_at, started_at, finished_at"
+            " FROM tasks ORDER BY id").fetchall()
+        conn.close()
+
+        db_module.migrate()  # 重跑
+
+        conn = self._conn()
+        try:
+            self.assertNotIn("celery_id", self._cols(conn, "tasks"))
+            self.assertNotIn("flow_id", self._cols(conn, "tasks"))
+            self.assertNotIn("flows", self._tables(conn))
+            after = conn.execute(
+                "SELECT id, type, params_json, status, progress_json,"
+                " stop_requested, error, created_at, started_at, finished_at"
+                " FROM tasks ORDER BY id").fetchall()
+            self.assertEqual([tuple(r) for r in snapshot],
+                             [tuple(r) for r in after])
+        finally:
+            conn.close()
+
+
+class NewSchemaNoopTest(TasksTableRebuildTest):
+    """已迁移库（新 schema 无死列）跑 migrate() 零变化。"""
+
+    def test_migrate_on_new_schema_is_noop(self):
+        conn = self._conn()
+        conn.executescript(_NEW_SCHEMA)
+        conn.execute(
+            "INSERT INTO tasks (type, params_json, status, created_at)"
+            " VALUES ('wa_check', '{}', 'pending', '2026-08-05 02:00:00')")
+        conn.commit()
+        before_cols = self._cols(conn, "tasks")
+        before_rows = conn.execute("SELECT * FROM tasks").fetchall()
+        conn.close()
+
+        db_module.migrate()
+
+        conn = self._conn()
+        try:
+            self.assertEqual(self._cols(conn, "tasks"), before_cols)
+            self.assertEqual(conn.execute("SELECT * FROM tasks").fetchall(),
+                             before_rows)
+        finally:
+            conn.close()
+
+
+class RollbackTest(TasksTableRebuildTest):
+    """失败回滚：DROP 处抛异常 → ROLLBACK 后原表（含死列与数据）保留。"""
+
+    def test_migrate_rollback_keeps_original_tasks(self):
+        conn = self._conn()
+        self._seed_old(conn)
+        conn.close()
+
+        class FlakyConn(sqlite3.Connection):
+            """在 DROP TABLE tasks 处抛异常的连接（模拟中途失败）。"""
+            def execute(self, sql, parameters=()):
+                if isinstance(sql, str) and sql.strip().upper().startswith(
+                        "DROP TABLE TASKS"):
+                    raise RuntimeError("simulated drop failure")
+                return super().execute(sql, parameters)
+
+        real_connect = sqlite3.connect
+
+        def flaky_connect(path, timeout=30, **kw):
+            return real_connect(path, timeout=timeout, factory=FlakyConn)
+
+        with patch("sqlite3.connect", side_effect=flaky_connect):
+            with self.assertRaises(RuntimeError):
+                db_module.migrate()
+
+        conn = self._conn()
+        try:
+            # 原表保留：死列仍在、数据未丢、flows 未删
+            cols = self._cols(conn, "tasks")
+            self.assertIn("celery_id", cols)
+            self.assertIn("flow_id", cols)
+            self.assertIn("flows", self._tables(conn))
+            self.assertEqual(conn.execute(
+                "SELECT COUNT(*) FROM tasks").fetchone()[0], 3)
+            self.assertEqual(conn.execute(
+                "SELECT COUNT(*) FROM task_events").fetchone()[0], 2)
+        finally:
+            conn.close()
+
+
+if __name__ == "__main__":
+    unittest.main()
