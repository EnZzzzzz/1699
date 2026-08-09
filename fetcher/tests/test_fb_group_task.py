# -*- coding: utf-8 -*-
"""Step 2.1: FbGroupTask 测试。

覆盖：fetch 透传（url/provider/limit 断言）、on_success 逐帖落号
（post_url 溯源 + group_id）+ 群 done 回写（post_count/has_contact/
last_crawled_at）、on_giveup 群 failed、prepare 崩溃恢复（in_progress
→ pending）、acquire_item 认领 + id 注入、label 格式、giveup_cost、
make_stats、on_abort 短语。全 mock 原子，不起真实网络/API；落库断言
用真实 ShopDB 临时库。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fetcher import RunConfig, ShopDB
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.facebook.group_task import FbGroupTask, _group_id_from_url

GROUP_URL = "https://www.facebook.com/groups/185879310028412"
POST_URL_1 = GROUP_URL + "/posts/1111111111111/"
POST_URL_2 = GROUP_URL + "/posts/2222222222222/"


def _seed_group(db, url=GROUP_URL, status="pending"):
    db.conn.execute(
        "INSERT INTO fb_groups (url, group_id, name, source, status,"
        " first_seen_at) VALUES (?, '185879310028412',"
        " 'Shenzhen Expats 2026', 'ddg', ?, '2026-08-08 10:00:00')",
        (url, status))
    db.conn.commit()


class _Ctx:
    """最小 WorkerContext 替身（store/state/set_status/consumer_kind）。"""

    def __init__(self, db):
        self.store = MagicMock()
        self.store.db = db
        self.state = {"task": {"stats": {"ok": 0, "empty": 0, "failed": 0}}}
        self.status_calls = []
        self.consumer_kind = "local"
        self.wid = 0
        self.logs = []

    def set_status(self, **kw):
        self.status_calls.append(kw)

    def log(self, msg):
        self.logs.append(msg)


def _result(posts=None, has_contact=None):
    """原子 OK 结果：posts 逐帖含 phones（模拟 parse_post 分桶）。"""
    posts = posts if posts is not None else [
        {"url": POST_URL_1, "text": "x" * 200,
         "phones": [{"number": "13812345678", "bucket": "cn_uncertain",
                     "source": "text"}]},
        {"url": POST_URL_2, "text": "y" * 200, "phones": []},
    ]
    phones = []
    seen = set()
    for p in posts:
        for ph in p.get("phones") or []:
            if ph["number"] not in seen:
                seen.add(ph["number"])
                phones.append(ph)
    data = {"provider": "brightdata", "group_url": GROUP_URL,
            "post_count": len(posts), "posts": posts, "phones": phones,
            "has_contact": has_contact if has_contact is not None
            else bool(phones)}
    return ActionResult(Outcome.OK, "ok", data)


class FbGroupTaskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = FbGroupTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _ctx(self):
        return _Ctx(self.db)

    # ---- fetch 透传 ----

    def test_fetch_passes_url_provider_limit_to_atom(self):
        mock_atom = MagicMock()
        sentinel = ActionResult(Outcome.OK, "ok", {})
        mock_atom.run.return_value = sentinel
        self.task._make_atom = lambda: mock_atom
        ctx = self._ctx()
        item = {"url": GROUP_URL, "provider": "apify", "limit": 20}
        r = self.task.fetch(ctx, item)
        self.assertIs(r, sentinel)
        mock_atom.run.assert_called_once()
        params = mock_atom.run.call_args[0][1]
        self.assertEqual(params, {"url": GROUP_URL, "provider": "apify",
                                  "limit": 20})

    def test_fetch_defaults_provider_limit(self):
        """payload 缺 provider/limit：provider=None 透传（原子缺省
        brightdata）、limit 取原子缺省 10。"""
        mock_atom = MagicMock()
        mock_atom.run.return_value = ActionResult(Outcome.OK, "ok", {})
        self.task._make_atom = lambda: mock_atom
        self.task.fetch(self._ctx(), {"url": GROUP_URL})
        params = mock_atom.run.call_args[0][1]
        self.assertEqual(params["provider"], None)
        self.assertEqual(params["limit"], 10)

    # ---- on_success 落库 ----

    def test_on_success_saves_contacts_per_post_and_marks_done(self):
        _seed_group(self.db)
        ctx = self._ctx()
        r = _result()
        n = self.task.on_success(ctx, {"url": GROUP_URL}, r)
        self.assertEqual(n, 2)  # 返回帖数（计入批次配额）
        rows = {row["post_url"]: row for row in self.db.conn.execute(
            "SELECT * FROM fb_contacts").fetchall()}
        # 逐帖落号：post_url 溯源 + group_id 从群 URL 解析
        self.assertEqual(rows[POST_URL_1]["number"], "13812345678")
        self.assertEqual(rows[POST_URL_1]["group_id"], "185879310028412")
        # 第二帖无号码 → 无对应 fb_contacts 行
        self.assertEqual(len(rows), 1)
        # 群 done 回写三字段
        group = self.db.conn.execute(
            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL,)).fetchone()
        self.assertEqual(group["status"], "done")
        self.assertEqual(group["post_count"], 2)
        self.assertEqual(group["has_contact"], 1)
        self.assertIsNotNone(group["last_crawled_at"])
        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
        self.assertEqual(ctx.state["task"]["stats"]["empty"], 0)

    def test_on_success_no_phones_counts_empty_and_has_contact_0(self):
        _seed_group(self.db)
        ctx = self._ctx()
        r = _result(posts=[{"url": POST_URL_1, "text": "x" * 200,
                            "phones": []}])
        self.task.on_success(ctx, {"url": GROUP_URL}, r)
        group = self.db.conn.execute(
            "SELECT status, post_count, has_contact FROM fb_groups"
            " WHERE url=?", (GROUP_URL,)).fetchone()
        self.assertEqual(group["status"], "done")
        self.assertEqual(group["post_count"], 1)
        self.assertEqual(group["has_contact"], 0)
        self.assertEqual(ctx.state["task"]["stats"]["ok"], 0)
        self.assertEqual(ctx.state["task"]["stats"]["empty"], 1)

    # ---- on_giveup ----

    def test_on_giveup_marks_failed(self):
        _seed_group(self.db)
        ctx = self._ctx()
        phrase = self.task.on_giveup(ctx, {"url": GROUP_URL}, "block",
                                     "block")
        self.assertIsInstance(phrase, str)
        row = self.db.conn.execute(
            "SELECT status FROM fb_groups WHERE url=?", (GROUP_URL,)).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertEqual(ctx.state["task"]["stats"]["failed"], 1)

    # ---- prepare 崩溃恢复 ----

    def test_prepare_resets_in_progress(self):
        _seed_group(self.db, status="in_progress")
        _seed_group(self.db, url=GROUP_URL + "2", status="pending")
        cfg = RunConfig(db_path=Path(self._tmp.name) / "t.db")
        ok = self.task.prepare(cfg)
        self.assertTrue(ok)
        statuses = [r[0] for r in self.db.conn.execute(
            "SELECT status FROM fb_groups ORDER BY id").fetchall()]
        self.assertEqual(statuses, ["pending", "pending"])

    # ---- acquire_item ----

    def test_acquire_item_claims_from_queue_with_id(self):
        ctx = self._ctx()
        self.db.conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, requires,"
            " created_at) VALUES ('crawl_fb_group', 'facebook', ?,"
            " '[\"local\"]', '2026-08-08 10:00:00')",
            (json.dumps({"url": GROUP_URL, "provider": "brightdata",
                         "limit": 10}),))
        self.db.conn.commit()
        item = self.task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["url"], GROUP_URL)
        self.assertIn("id", item)

    def test_acquire_item_empty_queue_returns_none(self):
        ctx = self._ctx()
        self.assertIsNone(self.task.acquire_item(ctx))

    # ---- label / 配额 / stats / abort ----

    def test_label_format(self):
        self.assertEqual(
            self.task.label({"url": GROUP_URL, "provider": "apify",
                             "limit": 20}),
            f"{GROUP_URL}（apify，≤20帖）")

    def test_giveup_cost(self):
        self.assertEqual(self.task.giveup_cost({}), 1)

    def test_make_stats(self):
        self.assertEqual(self.task.make_stats(),
                         {"ok": 0, "empty": 0, "failed": 0})

    def test_on_abort_phrase(self):
        phrase = self.task.on_abort(self._ctx(), {"url": GROUP_URL})
        self.assertIn("in_progress", phrase)
        self.assertIn(GROUP_URL, phrase)

    # ---- group_id 解析 ----

    def test_group_id_from_url(self):
        self.assertEqual(_group_id_from_url(GROUP_URL),
                         "185879310028412")
        self.assertEqual(_group_id_from_url(GROUP_URL + "/"),
                         "185879310028412")
        self.assertIsNone(_group_id_from_url(""))
        self.assertIsNone(_group_id_from_url("https://www.1688.com/"))


if __name__ == "__main__":
    unittest.main()
