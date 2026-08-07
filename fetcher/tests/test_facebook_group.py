# -*- coding: utf-8 -*-
"""FetchFbGroupPosts 原子单测：第三方 API（Bright Data / Apify）采公开群帖子。

HTTP 层全部 mock，样本取自 2026-08-06 两家实测返回
（docs/channel-research/facebook-groups.md §11 验证记录），
不依赖真实网络与 API key。
"""

from __future__ import annotations

import threading
import unittest
from unittest import mock

from fetcher.atoms import facebook_group as fg
from fetcher.atoms.facebook_group import FetchFbGroupPosts
from fetcher.core.types import Outcome

# ---- 实测样本（2026-08-06 小额验证，同一群同 10 帖） ----

# Bright Data /datasets/v3/snapshot 返回的单条记录（字段节选）
BD_RECORD = {
    "url": "https://www.facebook.com/groups/185879310028412/posts/1437583168191347/",
    "post_id": "1437583168191347",
    "user_url": "https://www.facebook.com/people/User/61557299394534/",
    "user_username_raw": "Some Agent",
    "content": "Shenzhen apartment for rent|Nanshan apartment| 125sqm 3BR/2BA "
               "| Fully Furnished WhatsApp: +8618588244213",
    "date_posted": "2026-08-05T01:23:00.000Z",
    "num_comments": 0,
    "num_shares": 0,
    "group_name": "Shenzhen Expats 2026",
    "group_id": "185879310028412",
    "group_members": 226500,
    "likes": 3,
}

# Apify run-sync-get-dataset-items 返回的单条记录（字段节选）
APIFY_RECORD = {
    "facebookUrl": "https://www.facebook.com/groups/185879310028412",
    "url": "https://www.facebook.com/groups/185879310028412/posts/1437583168191347/",
    "time": "2026-08-05T01:23:00.000Z",
    "user": {"id": "61557299394534", "name": "Some Agent"},
    "text": "Shenzhen apartment for rent|Nanshan apartment| 125sqm 3BR/2BA "
            "| Fully Furnished WhatsApp: +8618588244213",
    "likesCount": 3,
    "sharesCount": 0,
    "commentsCount": 0,
    "groupTitle": "Shenzhen Expats 2026",
}

GROUP_URL = "https://www.facebook.com/groups/185879310028412"


class _Ctx:
    """最小 WorkerContext 替身（鸭子类型）。"""

    def __init__(self, stopped: bool = False):
        self.stop = threading.Event()
        if stopped:
            self.stop.set()
        self.logs: list[str] = []

    def stopped(self) -> bool:
        return self.stop.is_set()

    def wait(self, seconds: float) -> bool:
        return self.stop.is_set()  # 单测里不真睡

    def log(self, msg: str) -> None:
        self.logs.append(msg)


def _run(params, ctx=None):
    return FetchFbGroupPosts().run(ctx or _Ctx(), params)


class TestNormalize(unittest.TestCase):
    def test_norm_brightdata(self):
        p = fg.norm_brightdata_post(BD_RECORD)
        self.assertEqual(p["url"], BD_RECORD["url"])
        self.assertIn("18588244213", p["text"])
        self.assertEqual(p["author"], "Some Agent")
        self.assertEqual(p["comments"], 0)
        self.assertEqual(p["group"], "Shenzhen Expats 2026")
        self.assertEqual(p["provider"], "brightdata")

    def test_norm_apify(self):
        p = fg.norm_apify_post(APIFY_RECORD)
        self.assertEqual(p["url"], APIFY_RECORD["url"])
        self.assertIn("18588244213", p["text"])
        self.assertEqual(p["author"], "Some Agent")
        self.assertEqual(p["likes"], 3)
        self.assertEqual(p["provider"], "apify")

    def test_norm_handles_missing_fields(self):
        p = fg.norm_apify_post({"url": "x"})
        self.assertEqual(p["text"], "")
        self.assertEqual(p["author"], "")


class TestAtomParams(unittest.TestCase):
    def test_missing_url_is_fatal(self):
        r = _run({})
        self.assertIs(r.outcome, Outcome.FATAL)

    def test_unknown_provider_is_fatal(self):
        r = _run({"url": GROUP_URL, "provider": "xxx"})
        self.assertIs(r.outcome, Outcome.FATAL)

    def test_missing_api_key_is_fatal(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            r = _run({"url": GROUP_URL, "provider": "apify"})
        self.assertIs(r.outcome, Outcome.FATAL)
        self.assertIn("APIFY_TOKEN", r.detail)


class TestApifyFlow(unittest.TestCase):
    def test_success_extracts_contacts(self):
        with mock.patch.object(fg, "_http_json",
                               return_value=(200, [APIFY_RECORD])) as m:
            r = _run({"url": GROUP_URL, "provider": "apify",
                      "api_key": "t", "limit": 10})
        self.assertIs(r.outcome, Outcome.OK)
        self.assertEqual(r.data["post_count"], 1)
        self.assertEqual(r.data["provider"], "apify")
        # 正文里的 WhatsApp 标签号 → 自声明桶
        phones = r.data["phones"]
        self.assertEqual(len(phones), 1)
        self.assertEqual(phones[0]["number"], "8618588244213")
        self.assertEqual(phones[0]["bucket"], "declared_wa")
        self.assertTrue(r.data["has_contact"])
        # 确认请求打到了 run-sync 端点且带了 token
        url_called = m.call_args[0][1]
        self.assertIn("run-sync-get-dataset-items", url_called)
        self.assertIn("token=t", url_called)

    def test_empty_group(self):
        with mock.patch.object(fg, "_http_json", return_value=(200, [])):
            r = _run({"url": GROUP_URL, "provider": "apify", "api_key": "t"})
        self.assertIs(r.outcome, Outcome.EMPTY)


class TestBrightDataFlow(unittest.TestCase):
    def _http_seq(self, responses):
        it = iter(responses)
        return lambda *a, **kw: next(it)

    def test_success_trigger_poll_download(self):
        seq = [
            (200, {"snapshot_id": "sd_1"}),                 # trigger
            (200, {"status": "ready", "records": 1}),       # progress
            (200, [BD_RECORD]),                             # snapshot 下载
        ]
        with mock.patch.object(fg, "_http_json",
                               side_effect=self._http_seq(seq)) as m:
            r = _run({"url": GROUP_URL, "provider": "brightdata",
                      "api_key": "k", "limit": 10})
        self.assertIs(r.outcome, Outcome.OK)
        self.assertEqual(r.data["post_count"], 1)
        self.assertEqual(r.data["provider"], "brightdata")
        self.assertEqual(r.data["phones"][0]["number"], "8618588244213")
        # 三次调用：trigger 带 dataset_id，progress，snapshot
        urls = [c[0][1] for c in m.call_args_list]
        self.assertIn(f"dataset_id={fg.BD_DATASET_GROUP_POSTS}", urls[0])
        self.assertIn("/progress/sd_1", urls[1])
        self.assertIn("/snapshot/sd_1", urls[2])
        # Bearer 认证头
        self.assertEqual(m.call_args_list[0][1]["headers"]["Authorization"],
                         "Bearer k")

    def test_snapshot_failed_is_net_error(self):
        seq = [
            (200, {"snapshot_id": "sd_1"}),
            (200, {"status": "failed"}),
        ]
        with mock.patch.object(fg, "_http_json",
                               side_effect=self._http_seq(seq)):
            r = _run({"url": GROUP_URL, "provider": "brightdata",
                      "api_key": "k"})
        self.assertIs(r.outcome, Outcome.NET_ERROR)

    def test_poll_interrupted_is_skipped(self):
        """trigger 已发出、轮询等待期间收到停止信号 → SKIPPED。"""
        class StopOnWait(_Ctx):
            def wait(self, seconds: float) -> bool:
                return True   # 模拟轮询间隔中 stop 被置位

        seq = [(200, {"snapshot_id": "sd_1"})]
        with mock.patch.object(fg, "_http_json",
                               side_effect=self._http_seq(seq)):
            r = _run({"url": GROUP_URL, "provider": "brightdata",
                      "api_key": "k"}, ctx=StopOnWait())
        self.assertIs(r.outcome, Outcome.SKIPPED)


class TestErrorMapping(unittest.TestCase):
    def test_401_is_fatal(self):
        with mock.patch.object(fg, "_http_json",
                               return_value=(401, {"error": "bad key"})):
            r = _run({"url": GROUP_URL, "provider": "apify", "api_key": "t"})
        self.assertIs(r.outcome, Outcome.FATAL)

    def test_429_is_blocked(self):
        with mock.patch.object(fg, "_http_json",
                               return_value=(429, "rate limited")):
            r = _run({"url": GROUP_URL, "provider": "apify", "api_key": "t"})
        self.assertIs(r.outcome, Outcome.BLOCKED)

    def test_402_is_blocked(self):
        """额度耗尽：BLOCKED 交策略层（停用该 provider），不算致命。"""
        with mock.patch.object(fg, "_http_json",
                               return_value=(402, "insufficient credits")):
            r = _run({"url": GROUP_URL, "provider": "apify", "api_key": "t"})
        self.assertIs(r.outcome, Outcome.BLOCKED)

    def test_500_is_net_error(self):
        with mock.patch.object(fg, "_http_json",
                               return_value=(500, "server error")):
            r = _run({"url": GROUP_URL, "provider": "apify", "api_key": "t"})
        self.assertIs(r.outcome, Outcome.NET_ERROR)

    def test_transport_error_is_net_error(self):
        with mock.patch.object(fg, "_http_json",
                               side_effect=OSError("timed out")):
            r = _run({"url": GROUP_URL, "provider": "apify", "api_key": "t"})
        self.assertIs(r.outcome, Outcome.NET_ERROR)


class TestAggregation(unittest.TestCase):
    def test_dedup_across_posts(self):
        """同一中介连发多帖（实测形态），跨帖聚合号码要唯一。"""
        posts = [dict(APIFY_RECORD), dict(APIFY_RECORD)]
        with mock.patch.object(fg, "_http_json", return_value=(200, posts)):
            r = _run({"url": GROUP_URL, "provider": "apify", "api_key": "t"})
        self.assertIs(r.outcome, Outcome.OK)
        self.assertEqual(r.data["post_count"], 2)
        self.assertEqual(len(r.data["phones"]), 1)


if __name__ == "__main__":
    unittest.main()
