# -*- coding: utf-8 -*-
"""Step 1.3: FbDiscoverTask 测试（SPEC §5.2）。

覆盖：fetch 原子透传（query/page/sample_min/max）、on_success 分流落库
（帖→fb_posts 且 keyword/source='ddg' 溯源、群→fb_groups、帖派生群同时进
两表、名称去 | Facebook / - Facebook 后缀、kind=None 跳过、空 results 防御、
无 group_id 防御）、on_giveup 无落库 + 短语 + failed 计数、acquire_item 认领
+ payload id 注入、prepare/label/make_stats、名称净化边界。mock 只在原子层
（FetchDdgSerp.run），落库用真实 ShopDB 临时库断言。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fetcher import IdentityStore, RunConfig, ShopDB, WorkerContext
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.facebook.discover_task import (
    FbDiscoverTask,
    QUEUE,
    _clean_title,
)

# 帖 permalink 与派生群主页（对齐 FetchDdgSerp OK 输出形态）
POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
            "1437583168191347/")
GROUP_URL = "https://www.facebook.com/groups/185879310028412"
GID = "185879310028412"
QUERY = "site:facebook.com/groups 跨境电商 whatsapp"


def _ctx(db, consumer_kind="local", wid=0):
    """真实 WorkerContext（字段可空装配）+ IdentityStore 包装临时库；
    set_status 记录调用供断言。"""
    ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
    ctx.consumer_kind = consumer_kind
    ctx.wid = wid
    ctx.store = IdentityStore(db)
    ctx.state["task"] = {"stats": {"ok": 0, "empty": 0, "failed": 0}}
    ctx.status_calls = []
    ctx.set_status = lambda **kw: ctx.status_calls.append(kw)
    return ctx


def _result(results):
    return ActionResult(Outcome.OK, "ok", {"results": results})


def _post_result(url=POST_URL, title="深圳跨境电商群 | Facebook"):
    return {"url": url, "title": title, "kind": "post",
            "group_id": GID, "group_url": GROUP_URL}


def _group_result(title="深圳外贸交流 - Facebook"):
    return {"url": GROUP_URL, "title": title, "kind": "group",
            "group_id": GID, "group_url": GROUP_URL}


def _non_fb_result():
    return {"url": "https://www.1688.com/", "title": "1688 首页",
            "kind": None, "group_id": None, "group_url": None}


class FbDiscoverTaskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = FbDiscoverTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _fb_posts(self):
        return self.db.conn.execute(
            "SELECT url, group_id, group_name, keyword, source FROM fb_posts"
        ).fetchall()

    def _fb_groups(self):
        return self.db.conn.execute(
            "SELECT url, group_id, name, source FROM fb_groups"
        ).fetchall()

    def _enqueue(self, query=QUERY, page=1):
        self.db.conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, requires,"
            " created_at) VALUES (?, NULL, ?, ?, '2026-08-09 10:00:00')",
            (QUEUE, json.dumps({"query": query, "page": page},
                               ensure_ascii=False), '["local"]'))
        self.db.conn.commit()

    # ---- fetch 原子透传 ----

    def test_fetch_passes_query_page_and_pacing_to_atom(self):
        """fetch 调 FetchDdgSerp 原子，params 透传 query/page/sample_min/max。"""
        mock_atom = MagicMock()
        sentinel = ActionResult(Outcome.OK, "ok", {})
        mock_atom.run.return_value = sentinel
        self.task._make_atom = lambda: mock_atom
        cfg = RunConfig(sample_min=13.0, sample_max=20.0)
        ctx = WorkerContext(config=cfg, log=lambda m: None)
        item = {"query": QUERY, "page": 2}
        r = self.task.fetch(ctx, item)
        self.assertIs(r, sentinel)
        mock_atom.run.assert_called_once()
        params = mock_atom.run.call_args[0][1]
        self.assertEqual(params, {"query": QUERY, "page": 2,
                                  "sample_min": 13.0, "sample_max": 20.0})

    # ---- on_success 分流落库 ----

    def test_on_success_post_goes_to_fb_posts_and_derived_group_to_groups(self):
        """帖 permalink → fb_posts（keyword/source='ddg' 溯源）；帖派生群同时
        进 fb_groups；名称去 | Facebook 后缀。返回新增帖数。"""
        ctx = _ctx(self.db)
        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
                                 _result([_post_result()]))
        self.assertEqual(n, 1)
        posts = self._fb_posts()
        self.assertEqual(len(posts), 1)
        p = posts[0]
        self.assertEqual(p["url"], POST_URL)
        self.assertEqual(p["group_id"], GID)
        self.assertEqual(p["group_name"], "深圳跨境电商群")
        self.assertEqual(p["keyword"], QUERY)
        self.assertEqual(p["source"], "ddg")
        groups = self._fb_groups()
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g["url"], GROUP_URL)
        self.assertEqual(g["group_id"], GID)
        self.assertEqual(g["name"], "深圳跨境电商群")
        self.assertEqual(g["source"], "ddg")

    def test_on_success_group_goes_to_fb_groups_only(self):
        """群主页 → 仅 fb_groups（url 取 group_url），不落 fb_posts。"""
        ctx = _ctx(self.db)
        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
                                 _result([_group_result()]))
        self.assertEqual(n, 0)
        self.assertEqual(len(self._fb_posts()), 0)
        groups = self._fb_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["url"], GROUP_URL)
        self.assertEqual(groups[0]["name"], "深圳外贸交流")  # 去 - Facebook 后缀

    def test_on_success_mixed_kinds_fan_out(self):
        """混合条目：帖 + 群 + 非 FB → 两表各得其位，非 FB 跳过。"""
        ctx = _ctx(self.db)
        n = self.task.on_success(
            ctx, {"query": QUERY, "page": 1},
            _result([_post_result(), _group_result(), _non_fb_result()]))
        self.assertEqual(n, 1)
        self.assertEqual(len(self._fb_posts()), 1)
        groups = self._fb_groups()
        # 帖派生群 + 群主页同 URL → INSERT OR IGNORE 去重为 1 行
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["url"], GROUP_URL)

    def test_on_success_kind_none_skipped(self):
        """kind=None 的非 FB 条目跳过（不落任何表），stats 仍算 ok。"""
        ctx = _ctx(self.db)
        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
                                 _result([_non_fb_result()]))
        self.assertEqual(n, 0)
        self.assertEqual(len(self._fb_posts()), 0)
        self.assertEqual(len(self._fb_groups()), 0)
        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)

    def test_on_success_cleans_name_suffixes(self):
        """名称去 | Facebook / - Facebook 后缀（strip 后 endswith，去一次）；
        无后缀原样；空标题落空串。"""
        ctx = _ctx(self.db)
        results = [
            _post_result(url=POST_URL + "1", title=" 群A | Facebook "),
            _post_result(url=POST_URL + "2", title="群B - Facebook"),
            _post_result(url=POST_URL + "3", title="群C（无后缀）"),
            _post_result(url=POST_URL + "4", title=""),
        ]
        self.task.on_success(ctx, {"query": QUERY, "page": 1},
                             _result(results))
        names = sorted(r["group_name"] for r in self._fb_posts())
        self.assertEqual(names, ["", "群A", "群B", "群C（无后缀）"])

    def test_on_success_post_without_group_id(self):
        """帖无 group_id/group_url（防御）→ fb_posts 落 group_id NULL，
        不派生群行，不崩。"""
        ctx = _ctx(self.db)
        results = [{"url": POST_URL, "title": "孤儿帖 | Facebook",
                    "kind": "post", "group_id": None, "group_url": None}]
        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
                                 _result(results))
        self.assertEqual(n, 1)
        p = self._fb_posts()[0]
        self.assertIsNone(p["group_id"])
        self.assertEqual(len(self._fb_groups()), 0)

    def test_on_success_counts_ok_and_calls_set_status(self):
        """有 results 且落库 → ok+1；set_status 携带 ok/empty/failed 计数。"""
        ctx = _ctx(self.db)
        self.task.on_success(ctx, {"query": QUERY, "page": 1},
                             _result([_post_result()]))
        self.assertEqual(ctx.state["task"]["stats"],
                         {"ok": 1, "empty": 0, "failed": 0})
        last = ctx.status_calls[-1]
        self.assertEqual(last["ok"], 1)
        self.assertEqual(last["empty"], 0)
        self.assertEqual(last["failed"], 0)
        self.assertEqual(last["n"], 1)

    def test_on_success_empty_results_counts_empty(self):
        """results 空（防御：正常 OK 路径不会出现）→ empty+1，返回 0。"""
        ctx = _ctx(self.db)
        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
                                 _result([]))
        self.assertEqual(n, 0)
        stats = ctx.state["task"]["stats"]
        self.assertEqual(stats, {"ok": 0, "empty": 1, "failed": 0})
        self.assertEqual(len(self._fb_posts()), 0)
        self.assertEqual(len(self._fb_groups()), 0)

    # ---- on_giveup ----

    def test_on_giveup_no_db_write_and_counts_failed(self):
        """BLOCKED/NET_ERROR/EMPTY 均不落库，仅 failed+1 + 返回短语。"""
        ctx = _ctx(self.db)
        phrase = self.task.on_giveup(ctx, {"query": QUERY, "page": 1},
                                     "DDG 限流（HTTP 202）", "block")
        self.assertIsInstance(phrase, str)
        self.assertTrue(phrase)
        self.assertEqual(len(self._fb_posts()), 0)
        self.assertEqual(len(self._fb_groups()), 0)
        self.assertEqual(ctx.state["task"]["stats"]["failed"], 1)

    # ---- acquire_item ----

    def test_acquire_item_claims_discover_fb_and_injects_id(self):
        """认领 discover_fb 最老 pending 项，payload 注入 id；行置 claimed。"""
        self._enqueue()
        self._enqueue(query=QUERY + "2", page=2)
        ctx = _ctx(self.db)
        item = self.task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["query"], QUERY)
        self.assertEqual(item["page"], 1)
        self.assertIn("id", item)
        row = self.db.conn.execute(
            "SELECT status, claimed_by FROM work_items"
            " WHERE payload_json LIKE ?", ("%" + QUERY + "%",)).fetchone()
        self.assertEqual(row[0], "claimed")
        self.assertEqual(row[1], "local0")

    def test_acquire_item_empty_queue_returns_none(self):
        ctx = _ctx(self.db)
        self.assertIsNone(self.task.acquire_item(ctx))

    # ---- 元数据 ----

    def test_class_attrs(self):
        self.assertEqual(FbDiscoverTask.name, "fb_discover")
        self.assertEqual(FbDiscoverTask.unit, "查询")
        self.assertEqual(FbDiscoverTask.QUEUE, "discover_fb")

    def test_make_stats(self):
        self.assertEqual(self.task.make_stats(),
                         {"ok": 0, "empty": 0, "failed": 0})

    def test_label(self):
        item = {"query": QUERY, "page": 3}
        self.assertEqual(self.task.label(item), f"{QUERY} 第3页")

    def test_prepare_returns_true(self):
        self._enqueue()
        cfg = RunConfig(db_path=Path(self._tmp.name) / "t.db")
        self.assertTrue(self.task.prepare(cfg))


class CleanTitleTest(unittest.TestCase):
    def test_strips_pipe_facebook_suffix(self):
        self.assertEqual(_clean_title("深圳跨境电商群 | Facebook"),
                         "深圳跨境电商群")

    def test_strips_dash_facebook_suffix(self):
        self.assertEqual(_clean_title("深圳外贸交流 - Facebook"),
                         "深圳外贸交流")

    def test_no_suffix_unchanged(self):
        self.assertEqual(_clean_title("普通标题"), "普通标题")

    def test_strips_whitespace_before_match(self):
        self.assertEqual(_clean_title("  群A | Facebook  "), "群A")

    def test_blank_or_none(self):
        self.assertEqual(_clean_title(""), "")
        self.assertEqual(_clean_title(None), "")
        self.assertEqual(_clean_title("   "), "")


if __name__ == "__main__":
    unittest.main()
