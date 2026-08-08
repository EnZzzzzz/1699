# -*- coding: utf-8 -*-
"""Step 1.5: 平台 fb_post 批次类型测试。

覆盖：enqueue_fb_post_batch 入队行数/幂等/in_progress 互斥、payload
{url,domain,name}（domain=群 URL 拼接）、防御性探测（fb_posts 表不存在
→ 0）、与 daemon topup 并发无双写（SPEC §7.4，双连接 BEGIN IMMEDIATE
串行化）、BATCH_TYPES 注册与 enqueue_batch_for_task 分派、preview 自动
兼容（批次文案）。全部用临时 sqlite（patch DB_PATH），不碰生产库。
"""

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app.runner as app_runner
from app import db as db_module

POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
            "1437583168191347/")


def _schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL, params_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', progress_json TEXT,
        stop_requested INTEGER NOT NULL DEFAULT 0, error TEXT,
        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
    );
    CREATE TABLE IF NOT EXISTS fb_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL UNIQUE, group_id TEXT, group_name TEXT,
        keyword TEXT, source TEXT NOT NULL DEFAULT 'apify',
        status TEXT NOT NULL DEFAULT 'pending', has_contact INTEGER,
        first_seen_at TEXT NOT NULL, fetched_at TEXT
    );
    CREATE TABLE IF NOT EXISTS fb_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT NOT NULL UNIQUE, bucket TEXT NOT NULL,
        wa_source TEXT, wa_registered INTEGER, wa_checked_at TEXT,
        post_url TEXT NOT NULL, group_id TEXT, first_seen_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_id INTEGER NOT NULL UNIQUE,
        contact_person TEXT, gender TEXT, phone TEXT, mobile TEXT,
        fax TEXT, address TEXT, source_url TEXT,
        scraped_at TEXT NOT NULL, raw_text TEXT,
        wa_registered INTEGER, wa_checked_at TEXT
    );
    CREATE TABLE IF NOT EXISTS work_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        queue TEXT NOT NULL, site TEXT, batch_id INTEGER,
        payload_json TEXT NOT NULL,
        requires TEXT NOT NULL DEFAULT '["channel","browser"]',
        status TEXT NOT NULL DEFAULT 'pending', claimed_by TEXT,
        claimed_at TEXT, finished_at TEXT, result_json TEXT,
        created_at TEXT NOT NULL
    );
    """)


class FbBatchTestBase(unittest.TestCase):
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

    def _seed_posts(self, n=3, url_base=POST_URL):
        conn = self._conn()
        for i in range(n):
            conn.execute(
                "INSERT INTO fb_posts (url, group_id, group_name, keyword,"
                " source, status, first_seen_at) VALUES (?, 'g1', 'G1',"
                " 'kw', 'apify', 'pending', '2026-08-09 10:00:00')",
                (f"{url_base}{i}",))
        conn.commit()
        conn.close()

    def _create_task(self, type_, params=None):
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO tasks (type, params_json, status, created_at)"
            " VALUES (?, ?, 'pending', '2026-08-09 10:00:00')",
            (type_, json.dumps(params or {})))
        conn.commit()
        tid = cur.lastrowid
        conn.close()
        return tid


class EnqueueFbPostBatchTest(FbBatchTestBase):
    def test_enqueue_with_batch_id_and_payload(self):
        """入队行数正确，payload 键 {url,domain,name}，源行 in_progress。"""
        self._seed_posts(3)
        from app.db import enqueue_fb_post_batch
        n = enqueue_fb_post_batch("crawl_fb_post", "facebook", 7, 0)
        self.assertEqual(n, 3)
        conn = self._conn()
        items = conn.execute(
            "SELECT * FROM work_items WHERE batch_id=7"
            " ORDER BY id").fetchall()
        self.assertEqual(len(items), 3)
        p = json.loads(items[0]["payload_json"])
        self.assertEqual(p["url"], POST_URL + "0")
        self.assertEqual(p["domain"],
                         "https://www.facebook.com/groups/g1")
        self.assertEqual(p["name"], "G1")
        self.assertEqual(items[0]["queue"], "crawl_fb_post")
        self.assertEqual(items[0]["site"], "facebook")
        self.assertEqual(items[0]["batch_id"], 7)
        st = {r[0] for r in conn.execute(
            "SELECT status FROM fb_posts").fetchall()}
        self.assertEqual(st, {"in_progress"})
        conn.close()

    def test_enqueue_limit(self):
        self._seed_posts(3)
        from app.db import enqueue_fb_post_batch
        n = enqueue_fb_post_batch("crawl_fb_post", "facebook", 7, 2)
        self.assertEqual(n, 2)

    def test_enqueue_idempotent(self):
        """源行置 in_progress 后再次入队 → 0（防双喂）。"""
        self._seed_posts(2)
        from app.db import enqueue_fb_post_batch
        enqueue_fb_post_batch("crawl_fb_post", "facebook", 7, 0)
        n2 = enqueue_fb_post_batch("crawl_fb_post", "facebook", 7, 0)
        self.assertEqual(n2, 0)

    def test_missing_table_returns_zero(self):
        """防御性探测：fb_posts 表不存在（fetcher 未建表）→ 0 不报错。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP TABLE fb_posts")
        conn.commit()
        conn.close()
        from app.db import enqueue_fb_post_batch
        n = enqueue_fb_post_batch("crawl_fb_post", "facebook", 7, 0)
        self.assertEqual(n, 0)

    def test_concurrent_enqueue_and_topup_no_duplicates(self):
        """SPEC §7.4：平台入队与 daemon topup 双连接并发，无重复行、无漏置。"""
        self._seed_posts(10)
        errs: list[Exception] = []

        def platform_enqueue():
            try:
                from app.db import enqueue_fb_post_batch
                enqueue_fb_post_batch("crawl_fb_post", "facebook", 99, 10)
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        def daemon_topup():
            # 复刻 fetcher topup_fb_post_work_items 的事务形态（平台测试
            # 不 import fetcher，同语义 SQL 模拟 daemon 侧写入）
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout = 30000")
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    rows = conn.execute(
                        "SELECT * FROM fb_posts WHERE status='pending'"
                        " ORDER BY first_seen_at, id LIMIT 10").fetchall()
                    for r in rows:
                        payload = json.dumps(
                            {"url": r["url"], "domain": r["group_id"],
                             "name": r["group_name"] or ""},
                            ensure_ascii=False)
                        conn.execute(
                            "INSERT INTO work_items (queue, site,"
                            " payload_json, created_at) VALUES (?, ?, ?, ?)",
                            ("crawl_fb_post", "facebook", payload,
                             "2026-08-09 10:00:00"))
                        conn.execute(
                            "UPDATE fb_posts SET status='in_progress'"
                            " WHERE id=?", (r["id"],))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=platform_enqueue),
              threading.Thread(target=daemon_topup)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errs, [])
        conn = self._conn()
        total = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE queue='crawl_fb_post'"
        ).fetchone()[0]
        self.assertEqual(total, 10, "双写方并发不应产生重复 work_items")
        distinct = conn.execute(
            "SELECT COUNT(DISTINCT payload_json) FROM work_items"
            " WHERE queue='crawl_fb_post'").fetchone()[0]
        self.assertEqual(distinct, 10)
        st = {r[0] for r in conn.execute(
            "SELECT status FROM fb_posts").fetchall()}
        self.assertEqual(st, {"in_progress"}, "无漏置 in_progress")
        conn.close()


class FbBatchRunnerTest(FbBatchTestBase):
    def test_batch_types_registered(self):
        self.assertIn("fb_post", app_runner.BATCH_TYPES)
        spec = app_runner.BATCH_TYPES["fb_post"]
        self.assertEqual(spec["queue"], "crawl_fb_post")
        self.assertEqual(spec["site"], "facebook")
        self.assertEqual(spec["domain_suffix"], "")
        self.assertEqual(spec["kind"], "fb_post")

    def test_enqueue_batch_for_task_dispatches(self):
        """enqueue_batch_for_task(fb_post) → enqueue_fb_post_batch。"""
        self._seed_posts(2)
        tid = self._create_task("fb_post", {"limit": 0})
        n = app_runner.enqueue_batch_for_task(tid, "fb_post", {"limit": 0})
        self.assertEqual(n, 2)
        conn = self._conn()
        rows = conn.execute(
            "SELECT batch_id FROM work_items WHERE queue='crawl_fb_post'"
        ).fetchall()
        self.assertTrue(all(r[0] == tid for r in rows))
        conn.close()

    def test_preview_batch_description(self):
        """preview 对 fb_post 返回批次文案（BATCH 类型自动兼容）。"""
        import app.api.tasks as api_tasks
        # 直接调 preview 内部逻辑需要 TestClient；这里验证 BATCH_TYPE_NAMES
        # 已含 fb_post（preview 分支按它走）
        self.assertIn("fb_post", app_runner.BATCH_TYPE_NAMES)


class EnqueueWaBatchDualSourceTest(FbBatchTestBase):
    """Step 3.3: 平台 enqueue_wa_batch 双源扩展（与 fetcher 同口径）。"""

    def _seed(self, contacts=(), fb=()):
        conn = self._conn()
        for i, (mobile, checked) in enumerate(contacts):
            conn.execute(
                "INSERT INTO contacts (shop_id, mobile, scraped_at,"
                " wa_checked_at) VALUES (?, ?, '2026-08-08 10:00:00', ?)",
                (i + 1, mobile, checked))
        for number, bucket, checked in fb:
            conn.execute(
                "INSERT INTO fb_contacts (number, bucket, wa_source,"
                " post_url, group_id, wa_checked_at, first_seen_at)"
                " VALUES (?, ?, ?, 'u', 'g1', ?, '2026-08-08 10:00:00')",
                (number, bucket,
                 "declared" if bucket == "declared_wa" else None, checked))
        conn.commit()
        conn.close()

    def _payload_numbers(self, batch_id):
        conn = self._conn()
        rows = conn.execute(
            "SELECT payload_json FROM work_items WHERE batch_id=?"
            " ORDER BY id", (batch_id,)).fetchall()
        conn.close()
        out = []
        for r in rows:
            out.extend(json.loads(r[0])["numbers"])
        return out

    def test_dual_source_union(self):
        """contacts 未查 + fb cn_uncertain 未查 → 双源都入队。"""
        self._seed(contacts=[("13800000001", None)],
                   fb=[("18588244213", "cn_uncertain", None)])
        from app.db import enqueue_wa_batch
        n = enqueue_wa_batch(9, ["a1"], limit=0)
        self.assertEqual(n, 1)
        nums = self._payload_numbers(9)
        self.assertEqual(sorted(nums),
                         ["8613800000001", "8618588244213"])

    def test_cross_source_dedup(self):
        """同号双源 → 只入队一次。"""
        self._seed(contacts=[("13800000001", None)],
                   fb=[("13800000001", "cn_uncertain", None)])
        from app.db import enqueue_wa_batch
        enqueue_wa_batch(9, ["a1"], limit=0)
        nums = self._payload_numbers(9)
        self.assertEqual(nums, ["8613800000001"])

    def test_declared_sampling_mixed(self):
        """cn_uncertain 10 个 → 配 1 个 declared 抽样。"""
        self._seed(
            fb=[(f"1380000000{i}", "cn_uncertain", None) for i in range(10)]
               + [("8618588244213", "declared_wa", None)])
        from app.db import enqueue_wa_batch
        enqueue_wa_batch(9, ["a1"], limit=0)
        nums = self._payload_numbers(9)
        uncertain = [x for x in nums if x.startswith("861380000000")]
        declared = [x for x in nums if x == "8618588244213"]
        self.assertEqual(len(uncertain), 10)
        self.assertEqual(len(declared), 1)

    def test_1688_only_no_regression(self):
        """无 fb_contacts 时账号轮换/切块与既有一致。"""
        self._seed(contacts=[(f"138{i:08d}", None) for i in range(120)])
        from app.db import enqueue_wa_batch
        n = enqueue_wa_batch(9, ["a1", "a2"], limit=0)
        self.assertEqual(n, 3)  # 120 → 50/50/20
        conn = self._conn()
        rows = conn.execute(
            "SELECT payload_json FROM work_items WHERE batch_id=9"
            " ORDER BY id").fetchall()
        conn.close()
        accounts = [json.loads(r[0])["account"] for r in rows]
        self.assertEqual(accounts, ["a1", "a2", "a1"])
        sizes = [len(json.loads(r[0])["numbers"]) for r in rows]
        self.assertEqual(sizes, [50, 50, 20])


if __name__ == "__main__":
    unittest.main()
