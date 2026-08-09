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

    def test_sweeper_stopped_with_zero_items(self):
        """stop_requested + 批次已无任何 work_items（被清空/删除）→ stopped。

        回归：旧逻辑零项恒派生 pending 且 sweeper 跳过写回，任务永远
        卡在 running 停不掉（线上 wa_check 任务实例）。
        """
        from app.runner import sweep_batch_tasks
        conn = self._conn()
        conn.execute("DELETE FROM work_items WHERE batch_id=?", (self.tid,))
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

    def test_sweeper_zero_items_not_stopped_without_stop_request(self):
        """零项且未请求停止 → pending 保持（未入队语义不变）。"""
        from app.runner import sweep_batch_tasks
        conn = self._conn()
        conn.execute("DELETE FROM work_items WHERE batch_id=?", (self.tid,))
        conn.commit()
        conn.close()
        sweep_batch_tasks()
        conn = self._conn()
        row = conn.execute("SELECT status FROM tasks WHERE id=?",
                           (self.tid,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "pending")


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


# =====================================================================
# 5. Step 3.1：fb_discover / fb_group 分派
# =====================================================================


class FbBatchDispatchTest(BatchTasksTestBase):
    """enqueue_batch_for_task 对 fb_discover/fb_group 分派参数透传。

    enqueue_fb_discover_batch / enqueue_fb_group_batch 由 Step 3.2 实现，
    本 Step mock app.db 模块属性断言分派参数（缺省值/显式值/limit 透传）。
    """

    def test_fb_discover_dispatch_with_defaults(self):
        """缺省 keywords=""、pages=1。"""
        from app.runner import enqueue_batch_for_task
        with patch.object(db_module, "enqueue_fb_discover_batch",
                          create=True, return_value=3) as mock_enqueue:
            n = enqueue_batch_for_task(7, "fb_discover", {})
        mock_enqueue.assert_called_once_with(7, "", 1)
        self.assertEqual(n, 3)

    def test_fb_discover_dispatch_with_explicit_keywords_pages(self):
        """显式 keywords 原样透传、pages 转 int。"""
        from app.runner import enqueue_batch_for_task
        with patch.object(db_module, "enqueue_fb_discover_batch",
                          create=True, return_value=3) as mock_enqueue:
            n = enqueue_batch_for_task(
                7, "fb_discover",
                {"keywords": "面膜 洗面奶", "pages": "3"})
        mock_enqueue.assert_called_once_with(7, "面膜 洗面奶", 3)
        self.assertEqual(n, 3)

    def test_fb_group_dispatch_with_defaults(self):
        """缺省 provider="brightdata"、posts_per_group=50、limit=0。"""
        from app.runner import enqueue_batch_for_task
        with patch.object(db_module, "enqueue_fb_group_batch",
                          create=True, return_value=4) as mock_enqueue:
            n = enqueue_batch_for_task(8, "fb_group", {})
        mock_enqueue.assert_called_once_with(8, "brightdata", 50, 0)
        self.assertEqual(n, 4)

    def test_fb_group_dispatch_with_explicit_values_and_limit(self):
        """显式 provider/posts_per_group 转 int + limit 透传。"""
        from app.runner import enqueue_batch_for_task
        with patch.object(db_module, "enqueue_fb_group_batch",
                          create=True, return_value=4) as mock_enqueue:
            n = enqueue_batch_for_task(
                8, "fb_group",
                {"provider": "scraperapi", "posts_per_group": "30",
                 "limit": "120"})
        mock_enqueue.assert_called_once_with(8, "scraperapi", 30, 120)
        self.assertEqual(n, 4)


# =====================================================================
# 6. Step 3.2：fb_discover / fb_group 真实入队
# =====================================================================


class FbBatchEnqueueTest(BatchTasksTestBase):
    """enqueue_fb_discover_batch / enqueue_fb_group_batch 真实落库。

    临时 sqlite 断言真实行：展开数/幂等/空关键词/限量/表缺失/源行置位/
    payload 全键断言。
    """

    def _seed_fb_groups(self, n=3):
        """建 fb_groups 表（对齐 fetcher 侧 schema）+ 种 n 条 pending 群。"""
        conn = self._conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS fb_groups ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " url TEXT NOT NULL UNIQUE, group_id TEXT, name TEXT,"
            " source TEXT NOT NULL DEFAULT 'ddg',"
            " status TEXT NOT NULL DEFAULT 'pending', post_count INTEGER,"
            " has_contact INTEGER, first_seen_at TEXT NOT NULL,"
            " last_crawled_at TEXT)")
        for i in range(n):
            conn.execute(
                "INSERT INTO fb_groups (url, group_id, name, status,"
                " first_seen_at) VALUES (?, ?, ?, 'pending',"
                " '2026-08-08 10:00:00')",
                (f"https://www.facebook.com/groups/g{i}", f"g{i}",
                 f"群{i}"))
        conn.commit()
        conn.close()

    def test_fb_discover_expands_keywords_times_pages(self):
        """2 词 × 2 页 = 4 条；payload 全键/requires/site/batch_id 断言。"""
        from app.db import enqueue_fb_discover_batch
        n = enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2)
        self.assertEqual(n, 4)
        items = self._wi(7)
        self.assertEqual(len(items), 4)
        for r in items:
            self.assertEqual(r["queue"], "discover_fb")
            self.assertIsNone(r["site"])
            self.assertEqual(r["batch_id"], 7)
            self.assertEqual(json.loads(r["requires"]), ["local"])
            p = json.loads(r["payload_json"])
            self.assertEqual(p["kind"], "serp")
            self.assertEqual(p["engine"], "ddg")
            self.assertIn(p["query"], ("面膜", "洗面奶"))
            self.assertIn(p["page"], (1, 2))
        # 每个词 × 每页组合恰好一条
        combos = {(json.loads(r["payload_json"])["query"],
                   json.loads(r["payload_json"])["page"])
                  for r in items}
        self.assertEqual(combos, {("面膜", 1), ("面膜", 2),
                                  ("洗面奶", 1), ("洗面奶", 2)})

    def test_fb_discover_idempotent_same_query_page(self):
        """同 query+page 已有 pending → 二次调用入队 0（不重复堆栈）。"""
        from app.db import enqueue_fb_discover_batch
        self.assertEqual(enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2), 4)
        self.assertEqual(enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2), 0)
        self.assertEqual(len(self._wi(7)), 4)

    def test_fb_discover_empty_keywords_returns_zero(self):
        """空关键词（空串/纯空白行）→ 0，不产生 item。"""
        from app.db import enqueue_fb_discover_batch
        self.assertEqual(enqueue_fb_discover_batch(7, "", 2), 0)
        self.assertEqual(enqueue_fb_discover_batch(7, "  \n \n", 2), 0)
        self.assertEqual(len(self._wi(7)), 0)

    def test_fb_discover_pages_less_than_one_treated_as_one(self):
        """pages<1 → 按 1 页处理（裁定 2）。"""
        from app.db import enqueue_fb_discover_batch
        self.assertEqual(enqueue_fb_discover_batch(7, "面膜", 0), 1)

    def test_fb_group_enqueues_and_marks_in_progress(self):
        """limit=2 取 2 群；payload {url,provider,limit}；源行置 in_progress。"""
        from app.db import enqueue_fb_group_batch
        self._seed_fb_groups(3)
        n = enqueue_fb_group_batch(8, "brightdata", posts_per_group=50,
                                   limit=2)
        self.assertEqual(n, 2)
        items = self._wi(8)
        self.assertEqual(len(items), 2)
        urls = [json.loads(r["payload_json"])["url"] for r in items]
        self.assertEqual(urls[0], "https://www.facebook.com/groups/g0")
        self.assertEqual(urls[1], "https://www.facebook.com/groups/g1")
        for r in items:
            self.assertEqual(r["queue"], "crawl_fb_group")
            self.assertIsNone(r["site"])
            self.assertEqual(r["batch_id"], 8)
            self.assertEqual(json.loads(r["requires"]), ["local"])
            p = json.loads(r["payload_json"])
            self.assertEqual(set(p), {"url", "provider", "limit"})
            self.assertEqual(p["provider"], "brightdata")
            self.assertEqual(p["limit"], 50)
        # 源行：前 2 群 in_progress，第 3 群保持 pending
        conn = self._conn()
        sts = conn.execute(
            "SELECT status FROM fb_groups ORDER BY id").fetchall()
        conn.close()
        self.assertEqual([r["status"] for r in sts],
                         ["in_progress", "in_progress", "pending"])

    def test_fb_group_limit_zero_unlimited(self):
        """limit=0（不限）→ 全部 pending 群入队。"""
        from app.db import enqueue_fb_group_batch
        self._seed_fb_groups(3)
        self.assertEqual(enqueue_fb_group_batch(8, "brightdata", 50, 0), 3)

    def test_fb_group_missing_table_returns_zero(self):
        """fb_groups 表不存在（fetcher 侧未建）→ 0（防御性探测）。"""
        from app.db import enqueue_fb_group_batch
        self.assertEqual(enqueue_fb_group_batch(8, "brightdata", 50, 2), 0)
        self.assertEqual(len(self._wi(8)), 0)


if __name__ == "__main__":
    unittest.main()
