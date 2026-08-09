# -*- coding: utf-8 -*-
"""Step 1.3: FbPostTask 测试。

覆盖：fetch 原子透传、validate 阈值边界、on_success 落库（fb_contacts
分桶 + fb_posts done + stats）、侧车副产物落 work_items.result_json、
prepare 崩溃恢复重置 in_progress、on_giveup 标记 failed、acquire_item、
group_id 解析。全 mock 原子，不起真实浏览器/网络。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fetcher import RunConfig, ShopDB, WorkerContext
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.facebook.post_task import FbPostTask
from fetcher.sites.facebook.urls import group_id_from_url

POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
            "1437583168191347/")
GROUP_URL = "https://www.facebook.com/groups/185879310028412"


def _seed_post(db, url=POST_URL, status="pending"):
    db.conn.execute(
        "INSERT INTO fb_posts (url, group_id, group_name, keyword, source,"
        " status, first_seen_at) VALUES (?, '185879310028412',"
        " 'Shenzhen Expats 2026', 'kw', 'apify', ?,"
        " '2026-08-08 10:00:00')",
        (url, status))
    db.conn.commit()


class _Ctx:
    """最小 WorkerContext 替身（store/state/set_status/consumer_kind）。"""

    def __init__(self, db):
        self.store = MagicMock()
        self.store.db = db
        self.state = {"task": {"stats": {"ok": 0, "empty": 0, "failed": 0}}}
        self.status_calls = []
        self.consumer_kind = "browser"
        self.wid = 0
        self.logs = []

    def set_status(self, **kw):
        self.status_calls.append(kw)

    def log(self, msg):
        self.logs.append(msg)


def _result(phones=None, has_contact=None, text="x" * 200):
    data = {"url": POST_URL, "text": text,
            "phones": phones or [], "has_contact": has_contact if
            has_contact is not None else bool(phones),
            "wechat_ids": [], "tg_handles": [], "wa_group_invites": []}
    return ActionResult(Outcome.OK, "ok", data)


class FbPostTaskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = FbPostTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _ctx(self):
        return _Ctx(self.db)

    # ---- fetch 透传原子 ----

    def test_fetch_passes_url_to_atom_and_returns_result(self):
        mock_atom = MagicMock()
        sentinel = ActionResult(Outcome.OK, "ok", {})
        mock_atom.run.return_value = sentinel
        self.task._make_atom = lambda: mock_atom
        ctx = self._ctx()
        item = {"url": POST_URL, "domain": GROUP_URL, "name": "G"}
        r = self.task.fetch(ctx, item)
        self.assertIs(r, sentinel)
        mock_atom.run.assert_called_once()
        params = mock_atom.run.call_args[0][1]
        self.assertEqual(params, {"url": POST_URL})

    # ---- validate 阈值 ----

    def test_validate_empty_data_false(self):
        r = ActionResult(Outcome.OK, "ok", None)
        self.assertFalse(self.task.validate(None, None, r))

    def test_validate_short_text_false(self):
        r = _result(text="x" * 99)
        self.assertFalse(self.task.validate(None, None, r))

    def test_validate_blank_text_false(self):
        r = _result(text="   ")
        self.assertFalse(self.task.validate(None, None, r))

    def test_validate_at_threshold_true(self):
        r = _result(text="x" * 100)
        self.assertTrue(self.task.validate(None, None, r))

    # ---- on_success 落库 ----

    def test_on_success_saves_contacts_and_marks_done(self):
        _seed_post(self.db)
        ctx = self._ctx()
        phones = [
            {"number": "13812345678", "bucket": "cn_uncertain",
             "source": "text"},
            {"number": "8618588244213", "bucket": "declared_wa",
             "source": "wa.me"},
        ]
        r = _result(phones=phones, has_contact=True)
        n = self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL},
                                 r)
        self.assertEqual(n, 1)
        rows = {row["number"]: row for row in self.db.conn.execute(
            "SELECT * FROM fb_contacts").fetchall()}
        self.assertEqual(rows["13812345678"]["wa_source"], None)
        self.assertEqual(rows["8618588244213"]["wa_source"], "declared")
        self.assertEqual(rows["13812345678"]["group_id"], "185879310028412")
        post = self.db.conn.execute(
            "SELECT * FROM fb_posts WHERE url=?", (POST_URL,)).fetchone()
        self.assertEqual(post["status"], "done")
        self.assertEqual(post["has_contact"], 1)
        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
        self.assertEqual(ctx.state["task"]["stats"]["empty"], 0)

    def test_on_success_no_phones_counts_empty(self):
        _seed_post(self.db)
        ctx = self._ctx()
        r = _result(phones=[], has_contact=False)
        self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL}, r)
        post = self.db.conn.execute(
            "SELECT status, has_contact FROM fb_posts WHERE url=?",
            (POST_URL,)).fetchone()
        self.assertEqual(post["status"], "done")
        self.assertEqual(post["has_contact"], 0)
        self.assertEqual(ctx.state["task"]["stats"]["empty"], 1)
        self.assertEqual(ctx.state["task"]["stats"]["ok"], 0)

    def test_on_success_sets_result_json_sidecar(self):
        """微信/TG/邀请链接侧车 → ctx.state['result_json']（QueueRouter 落库）。"""
        _seed_post(self.db)
        ctx = self._ctx()
        data = {"url": POST_URL, "text": "x" * 200, "phones": [],
                "has_contact": False, "wechat_ids": ["wx12345"],
                "tg_handles": ["tgbot1"],
                "wa_group_invites": ["AbCdEf123456"]}
        r = ActionResult(Outcome.OK, "ok", data)
        self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL}, r)
        self.assertEqual(ctx.state["result_json"],
                         {"wechat_ids": ["wx12345"], "tg_handles": ["tgbot1"],
                          "wa_group_invites": ["AbCdEf123456"]})

    def test_on_success_empty_sidecar_not_set(self):
        _seed_post(self.db)
        ctx = self._ctx()
        self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL},
                             _result())
        self.assertNotIn("result_json", ctx.state)

    def test_queue_router_finish_writes_sidecar_to_result_json(self):
        """侧车经 QueueRouter._finish 真正落 work_items.result_json
        （SPEC §8 观测副产物机制，触达 router 钩子代码）。"""
        from fetcher.control.queue_router import QueueRouter, QueueSpec
        spec = QueueSpec(queue="crawl_fb_post", site="facebook",
                         task=self.task)
        router = QueueRouter([spec])
        self.db.conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, requires,"
            " created_at) VALUES ('crawl_fb_post', 'facebook', ?, ?, "
            "'2026-08-08 10:00:00')",
            (json.dumps({"url": POST_URL, "domain": GROUP_URL,
                         "name": "G"}), '["channel","browser"]'))
        self.db.conn.commit()
        item_id = self.db.conn.execute(
            "SELECT id FROM work_items ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        ctx = self._ctx()
        ctx.state["daemon_work_item_id"] = item_id
        ctx.state["queue"] = "crawl_fb_post"
        ctx.state["result_json"] = {"wechat_ids": ["wx12345"]}
        router._finish(ctx, "done")
        row = self.db.conn.execute(
            "SELECT status, result_json FROM work_items WHERE id=?",
            (item_id,)).fetchone()
        self.assertEqual(row[0], "done")
        self.assertEqual(json.loads(row[1]), {"wechat_ids": ["wx12345"]})

    # ---- prepare 崩溃恢复 ----

    def test_prepare_resets_in_progress(self):
        _seed_post(self.db, status="in_progress")
        _seed_post(self.db, url=POST_URL + "2", status="pending")
        cfg = RunConfig(db_path=Path(self._tmp.name) / "t.db")
        ok = self.task.prepare(cfg)
        self.assertTrue(ok)
        statuses = [r[0] for r in self.db.conn.execute(
            "SELECT status FROM fb_posts").fetchall()]
        self.assertEqual(sorted(statuses), ["pending", "pending"])

    # ---- on_giveup ----

    def test_on_giveup_marks_failed(self):
        _seed_post(self.db)
        ctx = self._ctx()
        phrase = self.task.on_giveup(ctx, {"url": POST_URL}, "block", "block")
        self.assertIsInstance(phrase, str)
        row = self.db.conn.execute(
            "SELECT status FROM fb_posts WHERE url=?", (POST_URL,)).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertEqual(ctx.state["task"]["stats"]["failed"], 1)

    # ---- acquire_item ----

    def test_acquire_item_claims_from_queue(self):
        ctx = self._ctx()
        # 入队一条 crawl_fb_post 工作项
        self.db.conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, requires,"
            " created_at) VALUES ('crawl_fb_post', 'facebook', ?,"
            " '[\"channel\",\"browser\"]', '2026-08-08 10:00:00')",
            (json.dumps({"url": POST_URL, "domain": GROUP_URL,
                         "name": "G"}),))
        self.db.conn.commit()
        item = self.task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["url"], POST_URL)
        self.assertIn("id", item)

    def test_acquire_item_empty_queue_returns_none(self):
        ctx = self._ctx()
        self.assertIsNone(self.task.acquire_item(ctx))

    # ---- group_id 解析 ----

    def test_group_id_from_url(self):
        self.assertEqual(group_id_from_url(GROUP_URL),
                         "185879310028412")
        self.assertEqual(group_id_from_url(GROUP_URL + "/"), "185879310028412")
        self.assertIsNone(group_id_from_url(""))
        self.assertIsNone(group_id_from_url("https://www.1688.com/"))


if __name__ == "__main__":
    unittest.main()
