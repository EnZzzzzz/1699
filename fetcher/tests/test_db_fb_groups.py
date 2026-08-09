# -*- coding: utf-8 -*-
"""Step 1.1: fb_groups 建表 + save_fb_posts / upsert_fb_groups 数据面测试。

覆盖：建表幂等（fb_groups 表 + idx_fb_groups_status 索引）、save_fb_posts
URL 去重与 keyword/source/group_id/group_name 溯源落库、upsert_fb_groups URL
去重与不动既有行 status、source 缺省 ddg / 显式 source 落库。
"""

import tempfile
import unittest
from pathlib import Path

from fetcher import ShopDB

GROUP_URL_1 = "https://www.facebook.com/groups/185879310028412"
GROUP_URL_2 = "https://www.facebook.com/groups/1305282597018167"
POST_URL_1 = "https://www.facebook.com/groups/185879310028412/posts/1437583168191347/"
POST_URL_2 = "https://www.facebook.com/groups/1305282597018167/posts/1796051251274630/"


class FbGroupsDataTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    # ---- 建表幂等 ----

    def test_tables_created_and_idempotent(self):
        """重复初始化不报错，fb_groups 表与 (status, id) 索引存在。"""
        ShopDB(Path(self._tmp.name) / "t.db")  # 二次初始化
        tables = {r[0] for r in self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("fb_groups", tables)
        idx = {r[0] for r in self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("idx_fb_groups_status", idx)
        # schema 契约固化：save_fb_posts 依赖 fb_posts.status 默认 pending，
        # 防未来改 DEFAULT 静默破坏（status 列 dflt_value 须为 'pending'）。
        cols = {r["name"]: r for r in self.db.conn.execute(
            "PRAGMA table_info('fb_posts')").fetchall()}
        self.assertEqual(cols["status"]["dflt_value"], "'pending'")

    # ---- save_fb_posts ----

    def test_save_posts_traceability_and_count(self):
        posts = [
            {"url": POST_URL_1, "group_id": "185879310028412",
             "group_name": "Shenzhen Expats 2026"},
            {"url": POST_URL_2, "group_id": "1305282597018167",
             "group_name": "Group B"},
        ]
        n = self.db.save_fb_posts("外贸 whatsapp", "ddg", posts)
        self.assertEqual(n, 2)
        rows = {r["url"]: r for r in self.db.conn.execute(
            "SELECT * FROM fb_posts").fetchall()}
        self.assertEqual(rows[POST_URL_1]["keyword"], "外贸 whatsapp")
        self.assertEqual(rows[POST_URL_1]["source"], "ddg")
        self.assertEqual(rows[POST_URL_1]["group_id"], "185879310028412")
        self.assertEqual(rows[POST_URL_1]["group_name"], "Shenzhen Expats 2026")
        self.assertEqual(rows[POST_URL_1]["status"], "pending")
        self.assertIsNotNone(rows[POST_URL_1]["first_seen_at"])

    def test_save_posts_explicit_source(self):
        posts = [{"url": POST_URL_1, "group_id": "g1", "group_name": "G1"}]
        n = self.db.save_fb_posts("kw", "fb_post", posts)
        self.assertEqual(n, 1)
        row = self.db.conn.execute(
            "SELECT source FROM fb_posts WHERE url=?", (POST_URL_1,)).fetchone()
        self.assertEqual(row[0], "fb_post")

    def test_save_posts_dedup_same_url_returns_zero(self):
        posts = [{"url": POST_URL_1, "group_id": "g1", "group_name": "G1"}]
        n1 = self.db.save_fb_posts("kw", "ddg", posts)
        n2 = self.db.save_fb_posts("kw2", "ddg", posts)  # 同 url 二次插入
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)  # url UNIQUE IGNORE
        rows = self.db.conn.execute(
            "SELECT * FROM fb_posts WHERE url=?", (POST_URL_1,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["keyword"], "kw")  # 首见不覆盖

    # ---- upsert_fb_groups ----

    def test_upsert_groups_default_source_and_count(self):
        groups = [
            {"url": GROUP_URL_1, "group_id": "185879310028412",
             "name": "Shenzhen Expats 2026"},
            {"url": GROUP_URL_2, "group_id": "1305282597018167",
             "name": "Group B"},
        ]
        n = self.db.upsert_fb_groups(groups)
        self.assertEqual(n, 2)
        rows = {r["url"]: r for r in self.db.conn.execute(
            "SELECT * FROM fb_groups").fetchall()}
        self.assertEqual(rows[GROUP_URL_1]["source"], "ddg")  # 缺省 ddg
        self.assertEqual(rows[GROUP_URL_1]["status"], "pending")
        self.assertEqual(rows[GROUP_URL_1]["name"], "Shenzhen Expats 2026")
        self.assertEqual(rows[GROUP_URL_1]["group_id"], "185879310028412")
        self.assertIsNotNone(rows[GROUP_URL_1]["first_seen_at"])

    def test_upsert_groups_explicit_source(self):
        groups = [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1",
                   "source": "fb_post"}]
        n = self.db.upsert_fb_groups(groups)
        self.assertEqual(n, 1)
        row = self.db.conn.execute(
            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchone()
        self.assertEqual(row["source"], "fb_post")

    def test_upsert_groups_explicit_empty_source_kept(self):
        """协调者裁定：source 仅在 key 不存在或 None 时缺省 'ddg'；
        显式传空字符串 '' 是合法显式值，必须原样落库不被吞成 'ddg'。"""
        groups = [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1",
                   "source": ""}]
        n = self.db.upsert_fb_groups(groups)
        self.assertEqual(n, 1)
        row = self.db.conn.execute(
            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchone()
        self.assertEqual(row["source"], "")

    def test_upsert_groups_dedup_keeps_status_and_name(self):
        """先落 pending 行并置 in_progress（模拟采集进行中），再同 url
        不同 name/source 的 upsert → 0 行且 status/name 保持原值。"""
        self.db.upsert_fb_groups(
            [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1"}])
        self.db.conn.execute(
            "UPDATE fb_groups SET status='in_progress' WHERE url=?",
            (GROUP_URL_1,))
        self.db.conn.commit()
        n = self.db.upsert_fb_groups(
            [{"url": GROUP_URL_1, "group_id": "g1",
              "name": "改名后的群", "source": "fb_post"}])
        self.assertEqual(n, 0)  # 同 url IGNORE
        rows = self.db.conn.execute(
            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "in_progress")  # 不动 status
        self.assertEqual(rows[0]["name"], "G1")  # 不覆盖 name
        self.assertEqual(rows[0]["source"], "ddg")  # 二次 upsert 带 fb_post 也不覆盖 source


if __name__ == "__main__":
    unittest.main()
