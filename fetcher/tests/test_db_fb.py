# -*- coding: utf-8 -*-
"""Step 1.1: fb_posts/fb_contacts 数据面测试。

覆盖：建表幂等、topup_fb_post_work_items 状态流转与防重、并发 topup
无双写（双线程各自独立 ShopDB，模拟 daemon 多消费者）、save_fb_contacts
去重与 wa_source 规则、mark_fb_post_done/failed 流转。
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fetcher import ShopDB

POST_URL_1 = "https://www.facebook.com/groups/185879310028412/posts/1437583168191347/"
POST_URL_2 = "https://www.facebook.com/groups/1305282597018167/posts/1796051251274630/"


def _seed_posts(db, rows):
    """rows: [(url, group_id, group_name, keyword), ...] → pending 行。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for i, (url, gid, gname, kw) in enumerate(rows):
        db.conn.execute(
            "INSERT INTO fb_posts (url, group_id, group_name, keyword,"
            " source, first_seen_at) VALUES (?, ?, ?, ?, 'apify', ?)",
            (url, gid, gname, kw, now))
    db.conn.commit()


class FbPostsDataTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    # ---- 建表幂等 ----

    def test_tables_created_and_idempotent(self):
        """重复初始化不报错，两表存在，fb_posts 有 (status, id) 索引。"""
        ShopDB(Path(self._tmp.name) / "t.db")  # 二次初始化
        tables = {r[0] for r in self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("fb_posts", tables)
        self.assertIn("fb_contacts", tables)
        idx = {r[0] for r in self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("idx_fb_posts_status", idx)

    # ---- topup 状态流转与防重 ----

    def test_topup_enqueues_pending_with_payload(self):
        _seed_posts(self.db, [
            (POST_URL_1, "185879310028412", "Shenzhen Expats 2026", "kw1"),
            (POST_URL_2, "1305282597018167", "Group B", "kw2"),
        ])
        n = self.db.topup_fb_post_work_items("crawl_fb_post", "facebook", 0)
        self.assertEqual(n, 2)
        items = self.db.conn.execute(
            "SELECT * FROM work_items WHERE queue='crawl_fb_post'"
            " ORDER BY id").fetchall()
        self.assertEqual(len(items), 2)
        p1 = json.loads(items[0]["payload_json"])
        self.assertEqual(p1["url"], POST_URL_1)
        self.assertEqual(p1["domain"],
                         "https://www.facebook.com/groups/185879310028412")
        self.assertEqual(p1["name"], "Shenzhen Expats 2026")
        self.assertEqual(items[0]["site"], "facebook")
        # 源行置 in_progress
        rows = self.db.conn.execute(
            "SELECT status FROM fb_posts ORDER BY id").fetchall()
        self.assertEqual([r[0] for r in rows], ["in_progress", "in_progress"])

    def test_topup_limit(self):
        _seed_posts(self.db, [
            (POST_URL_1, "g1", "G1", "kw"), (POST_URL_2, "g2", "G2", "kw"),
        ])
        n = self.db.topup_fb_post_work_items("crawl_fb_post", "facebook", 1)
        self.assertEqual(n, 1)

    def test_topup_no_double_feed(self):
        _seed_posts(self.db, [(POST_URL_1, "g1", "G1", "kw")])
        self.db.topup_fb_post_work_items("crawl_fb_post", "facebook", 0)
        n2 = self.db.topup_fb_post_work_items("crawl_fb_post", "facebook", 0)
        self.assertEqual(n2, 0)
        cnt = self.db.conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE queue='crawl_fb_post'"
        ).fetchone()[0]
        self.assertEqual(cnt, 1)

    def test_topup_group_id_empty_domain_blank(self):
        _seed_posts(self.db, [(POST_URL_1, None, None, "kw")])
        self.db.topup_fb_post_work_items("crawl_fb_post", "facebook", 0)
        item = self.db.conn.execute(
            "SELECT payload_json FROM work_items").fetchone()
        p = json.loads(item[0])
        self.assertEqual(p["domain"], "")
        self.assertEqual(p["name"], "")

    # ---- 并发 topup 无双写 ----

    def test_concurrent_topup_no_duplicates(self):
        """双线程独立 ShopDB 同刻 topup：总数=种子数、无重复、全 in_progress。"""
        rows = [(f"https://www.facebook.com/groups/g{i}/posts/p{i}/",
                 f"g{i}", f"G{i}", "kw") for i in range(20)]
        _seed_posts(self.db, rows)
        errs: list[Exception] = []

        def worker():
            try:
                db2 = ShopDB(Path(self._tmp.name) / "t.db")
                try:
                    for _ in range(3):
                        db2.topup_fb_post_work_items(
                            "crawl_fb_post", "facebook", 10)
                finally:
                    db2.close()
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=worker) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errs, [])
        items = self.db.conn.execute(
            "SELECT DISTINCT payload_json FROM work_items"
            " WHERE queue='crawl_fb_post'").fetchall()
        self.assertEqual(len(items), 20)  # 无重复行
        statuses = [r[0] for r in self.db.conn.execute(
            "SELECT status FROM fb_posts").fetchall()]
        self.assertEqual(statuses, ["in_progress"] * 20)  # 无漏置

    # ---- save_fb_contacts ----

    def test_save_contacts_bucket_wa_source_rules(self):
        phones = [
            {"number": "13812345678", "bucket": "cn_uncertain",
             "source": "text"},
            {"number": "8618588244213", "bucket": "declared_wa",
             "source": "wa.me"},
            {"number": "1562562681", "bucket": "overseas", "source": "text"},
        ]
        n = self.db.save_fb_contacts(POST_URL_1, "g1", phones)
        self.assertEqual(n, 3)
        rows = {r["number"]: r for r in self.db.conn.execute(
            "SELECT * FROM fb_contacts").fetchall()}
        self.assertEqual(rows["13812345678"]["wa_source"], None)
        self.assertEqual(rows["8618588244213"]["wa_source"], "declared")
        self.assertEqual(rows["1562562681"]["wa_source"], None)
        self.assertEqual(rows["13812345678"]["post_url"], POST_URL_1)
        self.assertEqual(rows["13812345678"]["group_id"], "g1")

    def test_save_contacts_dedup_keeps_first_seen(self):
        first = self.db.save_fb_contacts(
            POST_URL_1, "g1",
            [{"number": "13812345678", "bucket": "cn_uncertain",
              "source": "text"}])
        time.sleep(0.01)  # 确保 first_seen_at 可区分
        n2 = self.db.save_fb_contacts(
            POST_URL_2, "g2",
            [{"number": "13812345678", "bucket": "declared_wa",
              "source": "wa.me"}])
        self.assertEqual(first, 1)
        self.assertEqual(n2, 0)  # 同号 IGNORE
        row = self.db.conn.execute(
            "SELECT * FROM fb_contacts WHERE number='13812345678'"
        ).fetchone()
        self.assertEqual(row["post_url"], POST_URL_1)  # 不覆盖
        self.assertEqual(row["group_id"], "g1")
        self.assertEqual(row["bucket"], "cn_uncertain")
        self.assertEqual(row["wa_source"], None)

    # ---- mark_* 流转 ----

    def test_mark_done(self):
        _seed_posts(self.db, [(POST_URL_1, "g1", "G1", "kw")])
        self.db.mark_fb_post_done(POST_URL_1, True)
        row = self.db.conn.execute(
            "SELECT * FROM fb_posts WHERE url=?", (POST_URL_1,)).fetchone()
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["has_contact"], 1)
        self.assertIsNotNone(row["fetched_at"])

    def test_mark_failed(self):
        _seed_posts(self.db, [(POST_URL_1, "g1", "G1", "kw")])
        self.db.mark_fb_post_failed(POST_URL_1)
        row = self.db.conn.execute(
            "SELECT status FROM fb_posts WHERE url=?", (POST_URL_1,)).fetchone()
        self.assertEqual(row[0], "failed")


if __name__ == "__main__":
    unittest.main()
