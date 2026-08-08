# -*- coding: utf-8 -*-
"""P4-2 Step 2.1: 平台批次任务类型 + sweeper 测试。

覆盖：平台侧批次入队（contact/feeder/wa，batch_id 全链路）、sweeper
状态派生/stopped 兜底/progress 聚合、start/stop 端点批次语义、
TASK_TYPES/TaskParams/preview 适配。全部用临时 sqlite（patch DB_PATH），
绝不碰生产库。
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ---- 测试基座：临时库 + DB_PATH patch ----

import app.db as app_db
import app.runner as app_runner
from app import db as db_module


def _schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tasks (
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
    CREATE TABLE IF NOT EXISTS task_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        ts TEXT NOT NULL,
        level TEXT NOT NULL,
        message TEXT,
        data_json TEXT
    );
    CREATE TABLE IF NOT EXISTS shops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL UNIQUE, name TEXT, url TEXT NOT NULL,
        category_keyword TEXT, run_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_id INTEGER NOT NULL UNIQUE REFERENCES shops(id),
        contact_person TEXT, gender TEXT, phone TEXT, mobile TEXT,
        fax TEXT, address TEXT, source_url TEXT,
        scraped_at TEXT NOT NULL, raw_text TEXT,
        wa_registered INTEGER, wa_checked_at TEXT
    );
    CREATE TABLE IF NOT EXISTS category_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL UNIQUE, name TEXT,
        next_page INTEGER NOT NULL DEFAULT 1,
        pages_crawled INTEGER NOT NULL DEFAULT 0,
        shops_found INTEGER NOT NULL DEFAULT 0,
        exhausted INTEGER NOT NULL DEFAULT 0,
        last_crawled_at TEXT
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
    """)


class BatchTasksTestBase(unittest.TestCase):
    """临时库基座：patch app.db.DB_PATH 与 runner 的 DB 访问。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "t.db")
        conn = sqlite3.connect(self.db_path)
        _schema(conn)
        conn.commit()
        conn.close()
        # patch 三个模块的 DB_PATH 与 runner 的 _db_write 相关路径。
        # 注意：api.tasks 的 _write 用的是它自己模块的 DB_PATH 属性
        # （导入时拷贝引用，patch db_module 不影响它），必须单独 patch。
        import app.api.tasks as api_tasks_module
        patchers = [
            patch.object(db_module, "DB_PATH", self.db_path),
            patch.object(app_runner, "DB_PATH", self.db_path),
            patch.object(api_tasks_module, "DB_PATH", self.db_path),
            patch.object(app_runner, "PROJECT_ROOT", str(Path(self._tmp.name))),
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

    def _seed_shops(self, n=3, suffix=".1688.com"):
        conn = self._conn()
        for i in range(n):
            conn.execute(
                "INSERT INTO shops (domain, name, url, status,"
                " first_seen_at, last_seen_at) VALUES (?, ?, ?, 'pending',"
                " '2026-08-08 10:00:00', '2026-08-08 10:00:00')",
                (f"shop{i}{suffix}", f"店{i}", f"https://shop{i}{suffix}"))
        conn.commit()
        conn.close()

    def _create_task(self, type_, params=None, status="pending"):
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO tasks (type, params_json, status, created_at)"
            " VALUES (?, ?, ?, '2026-08-08 10:00:00')",
            (type_, json.dumps(params or {}), status))
        conn.commit()
        tid = cur.lastrowid
        conn.close()
        return tid

    def _wi(self, batch_id=None):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM work_items WHERE batch_id=?"
            " ORDER BY id", (batch_id,)).fetchall()
        conn.close()
        return rows


# =====================================================================
# 1. 平台侧批次入队
# =====================================================================


class PlatformBatchEnqueueTest(BatchTasksTestBase):
    """平台 app/db 层批次入队（与 fetcher 同事务语义，batch_id 全链路）。"""

    def test_enqueue_contact_batch(self):
        from app.db import enqueue_contact_batch
        self._seed_shops(3)
        n = enqueue_contact_batch(
            "crawl_1688_contact", "1688", ".1688.com", batch_id=42, limit=2)
        self.assertEqual(n, 2)
        items = self._wi(42)
        self.assertEqual(len(items), 2)
        for r in items:
            self.assertEqual(r["queue"], "crawl_1688_contact")
            self.assertEqual(r["batch_id"], 42)
            self.assertEqual(r["status"], "pending")
            payload = json.loads(r["payload_json"])
            self.assertEqual(set(payload), {"domain", "name", "url"})
        # shops 置 in_progress
        conn = self._conn()
        st = conn.execute(
            "SELECT status FROM shops WHERE domain='shop0.1688.com'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(st, "in_progress")

    def test_enqueue_contact_batch_limit_zero(self):
        from app.db import enqueue_contact_batch
        self._seed_shops(3)
        n = enqueue_contact_batch(
            "crawl_1688_contact", "1688", ".1688.com", batch_id=1, limit=0)
        self.assertEqual(n, 3)

    def test_enqueue_feeder_batch(self):
        from app.db import enqueue_feeder_batch
        conn = self._conn()
        conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page,"
            " pages_crawled, shops_found, exhausted, last_crawled_at)"
            " VALUES ('女装', '女装', 1, 0, 0, 0, '2026-08-08 10:00:00'),"
            "        ('男装', '男装', 1, 0, 0, 0, '2026-08-08 10:00:00')")
        conn.commit()
        conn.close()
        n_cat, n_disc = enqueue_feeder_batch(
            "crawl_1688_shop", "1688", batch_id=5, limit=3)
        self.assertEqual(n_cat, 2)
        self.assertEqual(n_disc, 1)
        items = self._wi(5)
        self.assertEqual(len(items), 3)
        kinds = [json.loads(r["payload_json"])["kind"] for r in items]
        self.assertEqual(sorted(kinds), ["category", "category", "discover"])

    def test_enqueue_wa_batch(self):
        from app.db import enqueue_wa_batch
        conn = self._conn()
        conn.execute(
            "INSERT INTO shops (domain, name, url, status, first_seen_at,"
            " last_seen_at) VALUES ('wa.1688.com', 'wa', 'https://wa.1688.com',"
            " 'done', '2026-08-08 10:00:00', '2026-08-08 10:00:00'),"
            " ('wa2.1688.com', 'wa2', 'https://wa2.1688.com', 'done',"
            " '2026-08-08 10:00:00', '2026-08-08 10:00:00')")
        conn.execute(
            "INSERT INTO contacts (shop_id, mobile, scraped_at) VALUES"
            " (1, '13800138000', '2026-08-08 10:00:00'),"
            " (2, '13900139000', '2026-08-08 10:00:00')")
        conn.commit()
        conn.close()
        n = enqueue_wa_batch(9, ["xiaohao-4"], limit=0)
        self.assertEqual(n, 1)  # 2 个号码 → 1 块（50 以内）
        items = self._wi(9)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["queue"], "wa_check")
        self.assertEqual(json.loads(items[0]["requires"]), ["local"])
        payload = json.loads(items[0]["payload_json"])
        self.assertEqual(payload["account"], "xiaohao-4")
        self.assertEqual(len(payload["numbers"]), 2)

    def test_enqueue_wa_batch_empty_accounts_refused(self):
        from app.db import enqueue_wa_batch
        conn = self._conn()
        conn.execute(
            "INSERT INTO shops (domain, name, url, status, first_seen_at,"
            " last_seen_at) VALUES ('wa.1688.com', 'wa', 'https://wa.1688.com',"
            " 'done', '2026-08-08 10:00:00', '2026-08-08 10:00:00')")
        conn.execute(
            "INSERT INTO contacts (shop_id, mobile, scraped_at) VALUES"
            " (1, '13800138000', '2026-08-08 10:00:00')")
        conn.commit()
        conn.close()
        n = enqueue_wa_batch(9, [], limit=0)
        self.assertEqual(n, 0)  # 空账号拒绝


# =====================================================================
# 2. sweeper
# =====================================================================


class SweeperTest(BatchTasksTestBase):
    """sweeper 状态派生 / progress 聚合 / stopped 兜底。"""

    def setUp(self):
        super().setUp()
        self._seed_shops(3)
        from app.db import enqueue_contact_batch
        self.tid = self._create_task("1688_contact",
                                     {"limit": 2, "repeat_interval": 0})
        enqueue_contact_batch("crawl_1688_contact", "1688", ".1688.com",
                              batch_id=self.tid, limit=2)

    def _finish_items(self, batch_id, statuses):
        """按序把 batch 的 item 置终态。"""
        conn = self._conn()
        items = conn.execute(
            "SELECT id FROM work_items WHERE batch_id=? ORDER BY id",
            (batch_id,)).fetchall()
        for iid, st in zip([r["id"] for r in items], statuses):
            conn.execute(
                "UPDATE work_items SET status=?, finished_at="
                " '2026-08-08 11:00:00' WHERE id=?", (st, iid))
        conn.commit()
        conn.close()

    def test_sweeper_derives_running_from_pending(self):
        from app.runner import sweep_batch_tasks
        sweep_batch_tasks()
        conn = self._conn()
        row = conn.execute("SELECT status FROM tasks WHERE id=?",
                           (self.tid,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "running")

    def test_sweeper_derives_done_when_all_terminal(self):
        from app.runner import sweep_batch_tasks
        self._finish_items(self.tid, ["done", "done"])
        sweep_batch_tasks()
        conn = self._conn()
        row = conn.execute(
            "SELECT status, progress_json FROM tasks WHERE id=?",
            (self.tid,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "done")
        prog = json.loads(row["progress_json"])
        self.assertEqual(prog["total"], 2)
        self.assertEqual(prog["done"], 2)
        self.assertEqual(prog["failed"], 0)

    def test_sweeper_done_with_failed_counts_failed(self):
        """部分 failed 也算 done（failed 计数进 progress）。"""
        from app.runner import sweep_batch_tasks
        self._finish_items(self.tid, ["done", "failed"])
        sweep_batch_tasks()
        conn = self._conn()
        row = conn.execute(
            "SELECT status, progress_json FROM tasks WHERE id=?",
            (self.tid,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "done")
        prog = json.loads(row["progress_json"])
        self.assertEqual(prog["failed"], 1)

    def test_sweeper_stopped_override(self):
        """stop_requested + pending 清空 → stopped。"""
        from app.runner import sweep_batch_tasks
        self._finish_items(self.tid, ["done", "failed"])
        conn = self._conn()
        conn.execute("UPDATE tasks SET stop_requested=1 WHERE id=?",
                     (self.tid,))
        conn.commit()
        conn.close()
        sweep_batch_tasks()
        conn = self._conn()
        row = conn.execute("SELECT status FROM tasks WHERE id=?",
                           (self.tid,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "stopped")

    def test_sweeper_stopped_pending_flat(self):
        """stopped 批次的 pending 项每 tick 压平为 stopped。"""
        from app.runner import sweep_batch_tasks
        self._finish_items(self.tid, ["done"])
        conn = self._conn()
        conn.execute("UPDATE tasks SET stop_requested=1 WHERE id=?",
                     (self.tid,))
        conn.commit()
        conn.close()
        sweep_batch_tasks()
        conn = self._conn()
        items = conn.execute(
            "SELECT status FROM work_items WHERE batch_id=?", (self.tid,)
        ).fetchall()
        conn.close()
        self.assertEqual([r["status"] for r in items], ["done", "stopped"])


# =====================================================================
# 3. start/stop 端点批次语义
# =====================================================================


class BatchStartStopTest(BatchTasksTestBase):
    """start → 入队；stop → pending 置 stopped。"""

    def test_start_enqueues_and_sets_running(self):
        from app.api.tasks import start_task
        self._seed_shops(2)
        tid = self._create_task("1688_contact", {"limit": 2})
        with patch.object(app_runner, "runner") as mock_runner:
            mock_runner.is_running.return_value = False
            result = start_task(tid)
        self.assertTrue(result["ok"])
        items = self._wi(tid)
        self.assertEqual(len(items), 2)
        conn = self._conn()
        row = conn.execute("SELECT status FROM tasks WHERE id=?",
                           (tid,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "running")

    def test_stop_marks_pending_items_stopped(self):
        from app.api.tasks import stop_task
        from app.db import enqueue_contact_batch
        self._seed_shops(2)
        tid = self._create_task("1688_contact", {"limit": 2})
        enqueue_contact_batch("crawl_1688_contact", "1688", ".1688.com",
                              batch_id=tid, limit=2)
        # 模拟 start 后 sweeper 已派生 running
        conn = self._conn()
        conn.execute("UPDATE tasks SET status='running' WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        # runner 是真实单例（DB_PATH 已 patch）：批次任务不在 _runs，
        # stop 走 stop_batch_task 真实落库
        stop_task(tid)
        conn = self._conn()
        items = conn.execute(
            "SELECT status FROM work_items WHERE batch_id=? ORDER BY id",
            (tid,)).fetchall()
        row = conn.execute("SELECT stop_requested FROM tasks WHERE id=?",
                           (tid,)).fetchone()
        conn.close()
        self.assertEqual([r["status"] for r in items], ["stopped", "stopped"])
        self.assertEqual(row["stop_requested"], 1)


# =====================================================================
# 4. TASK_TYPES / TaskParams / preview
# =====================================================================


class TaskTypesTest(BatchTasksTestBase):
    def test_task_types_include_batch_and_yiwugo(self):
        from app.api.tasks import TASK_TYPES
        for t in ("1688_contact", "madeinchina_contact", "1688_shop",
                  "1688_company", "madeinchina_shop", "wa_check",
                  "yiwugo_search"):
            self.assertIn(t, TASK_TYPES)

    def test_preview_batch_type_returns_description(self):
        from app.api.tasks import preview_task
        body = type("Body", (), {"type": "1688_contact",
                                 "params": type("P", (), {
                                     "model_dump": lambda self: {
                                         "limit": 50}})()})()
        result = preview_task(body)
        self.assertIn("批次", result["cmdline"])

    def test_runner_startup_skips_batch_orphan_cleanup(self):
        """uvicorn 重启：批次类型 running 任务不被孤儿清理标 failed
        （SPEC §3.3：由 daemon 服务，重启不影响）。"""
        from app.db import enqueue_contact_batch
        self._seed_shops(1)
        tid = self._create_task("1688_contact", {"limit": 1})
        enqueue_contact_batch("crawl_1688_contact", "1688", ".1688.com",
                              batch_id=tid, limit=1)
        conn = self._conn()
        conn.execute("UPDATE tasks SET status='running' WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        # 模拟重启：真实 TaskRunner.startup（孤儿清理 + sweeper 重建）
        tr = app_runner.TaskRunner()
        tr.startup()
        tr.shutdown()
        conn = self._conn()
        row = conn.execute("SELECT status FROM tasks WHERE id=?",
                           (tid,)).fetchone()
        conn.close()
        # 批次 running 不被标 failed（孤儿清理跳过）；sweeper 重建为 running
        # （有 pending item）——若清理误标会变 failed
        self.assertEqual(row["status"], "running")


if __name__ == "__main__":
    unittest.main()
