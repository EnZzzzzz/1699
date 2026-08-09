# -*- coding: utf-8 -*-
"""Step 1.4: crawl_fb_post / discover_fb 队列注册测试。

覆盖：_build_registry 注册 crawl_fb_post QueueSpec（site/domain_suffix/
requires/task 类型）、topup lambda 从 fb_posts 补货、--queues 动态校验
包含 fb 队列、daemon prepare 经 FbPostTask.prepare 重置 fb_posts
in_progress（reset_daemon_state 不覆盖 fb_posts 的缺口补位）；
FB discovery 的 discover_fb 队列注册（site=None/topup=None/
requires={"local"}，FbDiscoverTask 实例）。
"""

import json
import tempfile
import unittest
from pathlib import Path

from fetcher import ShopDB
from fetcher.sites.facebook.discover_task import FbDiscoverTask
from fetcher.sites.facebook.post_task import FbPostTask

POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
            "1437583168191347/")


def _seed_posts(db, n=3):
    for i in range(n):
        db.conn.execute(
            "INSERT INTO fb_posts (url, group_id, group_name, keyword,"
            " source, status, first_seen_at)"
            " VALUES (?, 'g1', 'G1', 'kw', 'apify', 'pending',"
            " '2026-08-08 10:00:00')",
            (f"{POST_URL}{i}",))
    db.conn.commit()


class FbQueueRegistrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _registry(self):
        from fetcher.cli.main import _build_registry
        return {s.queue: s for s in _build_registry()}

    def test_crawl_fb_post_registered(self):
        reg = self._registry()
        self.assertIn("crawl_fb_post", reg)
        spec = reg["crawl_fb_post"]
        self.assertEqual(spec.site, "facebook")
        self.assertEqual(spec.domain_suffix, "")
        self.assertEqual(spec.requires, {"channel", "browser"})
        self.assertIsInstance(spec.task, FbPostTask)
        self.assertIsNotNone(spec.topup)

    def test_discover_fb_registered(self):
        """discover_fb：local 消费者注册（site=None、topup=None、
        requires={"local"}），task 是 FbDiscoverTask 实例。"""
        reg = self._registry()
        self.assertIn("discover_fb", reg)
        spec = reg["discover_fb"]
        self.assertEqual(spec.queue, "discover_fb")
        self.assertIsNone(spec.site)
        self.assertEqual(spec.domain_suffix, "")
        self.assertEqual(spec.requires, {"local"})
        self.assertIsInstance(spec.task, FbDiscoverTask)
        self.assertIsNone(spec.topup)

    def test_fb_topup_feeds_work_items(self):
        """topup lambda：pending fb_posts → work_items，payload 键 url/domain/name。"""
        _seed_posts(self.db, 3)
        spec = self._registry()["crawl_fb_post"]
        n = spec.topup(self.db, 10)
        self.assertEqual(n, 3)
        items = self.db.conn.execute(
            "SELECT * FROM work_items WHERE queue='crawl_fb_post'"
        ).fetchall()
        self.assertEqual(len(items), 3)
        p = json.loads(items[0]["payload_json"])
        self.assertEqual(p["url"], POST_URL + "0")
        self.assertEqual(p["domain"], "https://www.facebook.com/groups/g1")
        # 源行置 in_progress（双写入方互斥）
        st = {r[0] for r in self.db.conn.execute(
            "SELECT status FROM fb_posts").fetchall()}
        self.assertEqual(st, {"in_progress"})

    def test_queues_choices_accept_fb(self):
        """--queues crawl_fb_post 通过注册表动态校验（非硬编码）。"""
        from fetcher.cli.main import _build_registry
        names = [s.queue for s in _build_registry()]
        self.assertIn("crawl_fb_post", names)

    def test_fb_posts_reset_goes_through_task_prepare(self):
        """reset_daemon_state 不覆盖 fb_posts（domain_suffix=""），
        FbPostTask.prepare 补位重置 in_progress → pending。"""
        from fetcher.cli.main import _build_registry, reset_daemon_state
        _seed_posts(self.db, 2)
        # 模拟中断残留：手工置 in_progress + 一条 claimed 工作项
        self.db.conn.execute(
            "UPDATE fb_posts SET status='in_progress'")
        self.db.conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, requires,"
            " status, claimed_by, created_at) VALUES ('crawl_fb_post',"
            " 'facebook', ?, '[\"channel\",\"browser\"]', 'claimed', 'w0',"
            " '2026-08-08 10:00:00')",
            (json.dumps({"url": POST_URL}),))
        self.db.conn.commit()
        reg = _build_registry()
        n_items, n_shops = reset_daemon_state(self.db, reg)
        # work_items claimed 被全量回收
        self.assertEqual(n_items, 1)
        # fb_posts in_progress 未被 reset_daemon_state 重置（domain_suffix=""）
        st = {r[0] for r in self.db.conn.execute(
            "SELECT status FROM fb_posts").fetchall()}
        self.assertEqual(st, {"in_progress"})
        # FbPostTask.prepare 补位重置
        from fetcher import RunConfig
        task = FbPostTask()
        task.prepare(RunConfig(db_path=Path(self._tmp.name) / "t.db"))
        st2 = {r[0] for r in self.db.conn.execute(
            "SELECT status FROM fb_posts").fetchall()}
        self.assertEqual(st2, {"pending"})


if __name__ == "__main__":
    unittest.main()
