# -*- coding: utf-8 -*-
"""FetchDdgSerp 原子 + parse/classify 纯函数单测。

parse/classify 用真实 spike 样本（docs/feat_2026-08-09_fb-discovery-group-feed/
spike/ddg_sample_1.html，2026-08-09 实测 10 条有机结果全为 FB 群主页）与真实
URL；HTTP 层全部 mock（_http_get / urlopen），不依赖真实网络。
"""

from __future__ import annotations

import gzip
import socket
import threading
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

from fetcher.atoms import facebook_discover as fd
from fetcher.atoms.facebook_discover import (
    FetchDdgSerp,
    classify_fb_url,
    parse_serp_results,
)
from fetcher.core.types import Outcome

# 真实 spike 样本：<root>/docs/feat_2026-08-09_fb-discovery-group-feed/spike/
SPIKE_HTML = (Path(__file__).resolve().parents[2]
              / "docs" / "feat_2026-08-09_fb-discovery-group-feed"
              / "spike" / "ddg_sample_1.html")

SAMPLE_QUERY = "site:facebook.com/groups 跨境电商 whatsapp"


class _Ctx:
    """最小 WorkerContext 替身：记录 wait 次数/时长，可模拟停止信号。"""

    def __init__(self, stopped: bool = False):
        self.stop = threading.Event()
        if stopped:
            self.stop.set()
        self.waits: list[float] = []
        self.logs: list[str] = []

    def stopped(self) -> bool:
        return self.stop.is_set()

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        return self.stop.is_set()

    def log(self, msg: str) -> None:
        self.logs.append(msg)


class _StopAfterRequest(_Ctx):
    """请求发出后才置位 stop：验证节奏 wait 被中断 → SKIPPED。"""

    def stopped(self) -> bool:
        return False   # 请求前不停止

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        return True    # 等待期间 stop 置位


def _run(params, ctx=None):
    return FetchDdgSerp().run(ctx or _Ctx(), params)


def _sample_html() -> str:
    return SPIKE_HTML.read_text(encoding="utf-8")


class TestParseSerpResults(unittest.TestCase):
    def test_sample_structure(self):
        """真实样本：10 条结果，全部解码为 https FB 群 URL，键只有 url/title。"""
        results = parse_serp_results(_sample_html())
        self.assertEqual(len(results), 10)
        for r in results:
            self.assertEqual(set(r), {"url", "title"})
            self.assertTrue(
                r["url"].startswith("https://www.facebook.com/groups/"))
            self.assertNotIn("%", r["url"])            # uddg 已 URL 解码
            self.assertNotIn("&amp;", r["url"])        # HTML 实体已还原
            self.assertTrue(r["title"].strip())

    def test_first_result_matches_sample(self):
        results = parse_serp_results(_sample_html())
        self.assertEqual(
            results[0]["url"],
            "https://www.facebook.com/groups/crossborderelectroniccommerce/")
        self.assertEqual(results[0]["title"], "跨境电商交流群 | Facebook")

    def test_title_html_entities_unescaped(self):
        html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
                '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2F&amp;rut=x">'
                'A &amp; B &lt;测试&gt;</a>')
        results = parse_serp_results(html)
        self.assertEqual(results[0]["title"], "A & B <测试>")

    def test_title_tags_stripped(self):
        html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
                '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2F&amp;rut=x">'
                '<b>跨境</b> 交流群</a>')
        results = parse_serp_results(html)
        self.assertEqual(results[0]["title"], "跨境 交流群")

    def test_no_results_returns_empty(self):
        self.assertEqual(parse_serp_results("<html><body>无结果</body></html>"), [])
        self.assertEqual(parse_serp_results(""), [])


class TestClassifyFbUrl(unittest.TestCase):
    def test_post_permalink(self):
        url = ("https://www.facebook.com/groups/185879310028412/"
               "posts/1437583168191347/")
        self.assertEqual(
            classify_fb_url(url),
            ("post", "185879310028412",
             "https://www.facebook.com/groups/185879310028412"))

    def test_post_permalink_variant(self):
        """permalink 变体 + slug 群 id。"""
        url = ("https://www.facebook.com/groups/crossborderelectroniccommerce/"
               "permalink/123456789/")
        self.assertEqual(
            classify_fb_url(url),
            ("post", "crossborderelectroniccommerce",
             "https://www.facebook.com/groups/crossborderelectroniccommerce"))

    def test_group_numeric(self):
        url = "https://www.facebook.com/groups/2245859412418547/"
        self.assertEqual(
            classify_fb_url(url),
            ("group", "2245859412418547",
             "https://www.facebook.com/groups/2245859412418547"))

    def test_group_slug_without_trailing_slash(self):
        url = "https://www.facebook.com/groups/yiliukescrm"
        self.assertEqual(
            classify_fb_url(url),
            ("group", "yiliukescrm",
             "https://www.facebook.com/groups/yiliukescrm"))

    def test_video_is_none(self):
        self.assertIsNone(
            classify_fb_url("https://www.facebook.com/watch/?v=123456789"))

    def test_user_profile_is_none(self):
        self.assertIsNone(classify_fb_url("https://www.facebook.com/someuser"))

    def test_non_facebook_is_none(self):
        self.assertIsNone(
            classify_fb_url("https://www.youtube.com/watch?v=abc"))


class TestAtomParams(unittest.TestCase):
    def test_missing_query_is_fatal(self):
        with mock.patch.object(fd, "_http_get") as m:
            r = _run({})
        self.assertIs(r.outcome, Outcome.FATAL)
        m.assert_not_called()          # FATAL 不发请求

    def test_non_str_query_is_fatal(self):
        r = _run({"query": 123})
        self.assertIs(r.outcome, Outcome.FATAL)

    def test_blank_query_is_fatal(self):
        r = _run({"query": "   "})
        self.assertIs(r.outcome, Outcome.FATAL)

    def test_page_lt_1_is_fatal(self):
        for page in (0, -1, "0"):
            r = _run({"query": "x", "page": page})
            self.assertIs(r.outcome, Outcome.FATAL, f"page={page!r}")


class TestAtomHttpOutcomes(unittest.TestCase):
    def test_ok_with_results(self):
        with mock.patch.object(fd, "_http_get",
                               return_value=(200, _sample_html())) as m:
            ctx = _Ctx()
            r = _run({"query": SAMPLE_QUERY}, ctx=ctx)
        self.assertIs(r.outcome, Outcome.OK)
        self.assertEqual(r.data["engine"], "ddg")
        self.assertEqual(r.data["query"], SAMPLE_QUERY)
        self.assertEqual(r.data["page"], 1)
        results = r.data["results"]
        self.assertEqual(len(results), 10)
        first = results[0]
        self.assertEqual(set(first), {"url", "title", "kind",
                                      "group_id", "group_url"})
        self.assertEqual(first["kind"], "group")
        self.assertEqual(
            first["group_url"],
            "https://www.facebook.com/groups/crossborderelectroniccommerce")
        # 请求 URL：q=quote(query)（safe='/'）、s=offset=0
        url_called = m.call_args[0][0]
        self.assertIn(f"q={urllib.parse.quote(SAMPLE_QUERY)}", url_called)
        self.assertIn("&s=0", url_called)
        # 正常路径：请求后节奏 wait 恰好 1 次，且 ≥ 60s 地板
        self.assertEqual(len(ctx.waits), 1)
        self.assertGreaterEqual(ctx.waits[0], 60)

    def test_page_2_offset(self):
        with mock.patch.object(fd, "_http_get",
                               return_value=(200, _sample_html())) as m:
            _run({"query": "x", "page": 2})
        self.assertIn("&s=10", m.call_args[0][0])

    def test_ok_mixed_kinds(self):
        """帖 + 群主页 + 非 FB 混合：全部保留，非 FB 的 kind 为 None。"""
        html = (
            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
            '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2Fposts%2F456%2F'
            '&amp;rut=a">Post A</a>'
            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
            '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2Fslugg%2F&amp;rut=b">'
            'Group B</a>'
            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
            '?uddg=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc&amp;rut=c">'
            'Video C</a>')
        with mock.patch.object(fd, "_http_get", return_value=(200, html)):
            r = _run({"query": "x"})
        self.assertIs(r.outcome, Outcome.OK)
        results = r.data["results"]
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["kind"], "post")
        self.assertEqual(results[0]["group_id"], "123")
        self.assertEqual(results[0]["group_url"],
                         "https://www.facebook.com/groups/123")
        self.assertEqual(results[1]["kind"], "group")
        self.assertIsNone(results[2]["kind"])
        self.assertIsNone(results[2]["group_id"])

    def test_empty_serp_is_empty(self):
        with mock.patch.object(fd, "_http_get",
                               return_value=(200, "<html>nothing</html>")):
            ctx = _Ctx()
            r = _run({"query": "x"}, ctx=ctx)
        self.assertIs(r.outcome, Outcome.EMPTY)
        self.assertEqual(len(ctx.waits), 1)   # 空结果也走请求后节奏

    def test_202_is_blocked_with_backoff_wait(self):
        with mock.patch.object(fd, "_http_get",
                               return_value=(202, "anomaly")):
            ctx = _Ctx()
            r = _run({"query": "x"}, ctx=ctx)
        self.assertIs(r.outcome, Outcome.BLOCKED)
        # 202 路径：退避 uniform(180,240) + 请求后节奏 = 2 次 wait
        self.assertEqual(len(ctx.waits), 2)
        self.assertGreaterEqual(ctx.waits[0], 180)
        self.assertLessEqual(ctx.waits[0], 240)
        self.assertGreaterEqual(ctx.waits[1], 60)

    def test_403_is_blocked(self):
        with mock.patch.object(fd, "_http_get", return_value=(403, "")):
            r = _run({"query": "x"})
        self.assertIs(r.outcome, Outcome.BLOCKED)

    def test_429_is_blocked(self):
        with mock.patch.object(fd, "_http_get", return_value=(429, "")):
            r = _run({"query": "x"})
        self.assertIs(r.outcome, Outcome.BLOCKED)

    def test_5xx_is_net_error(self):
        with mock.patch.object(fd, "_http_get", return_value=(500, "")):
            r = _run({"query": "x"})
        self.assertIs(r.outcome, Outcome.NET_ERROR)

    def test_transport_error_is_net_error_no_wait(self):
        with mock.patch.object(fd, "_http_get",
                               side_effect=OSError("connection reset")):
            ctx = _Ctx()
            r = _run({"query": "x"}, ctx=ctx)
        self.assertIs(r.outcome, Outcome.NET_ERROR)
        self.assertEqual(ctx.waits, [])   # 传输异常无响应，不节奏 wait

    def test_timeout_is_net_error(self):
        with mock.patch.object(fd, "_http_get",
                               side_effect=TimeoutError("timed out")):
            r = _run({"query": "x"})
        self.assertIs(r.outcome, Outcome.NET_ERROR)

    def test_stopped_is_skipped_no_wait_no_http(self):
        with mock.patch.object(fd, "_http_get") as m:
            ctx = _Ctx(stopped=True)
            r = _run({"query": "x"}, ctx=ctx)
        self.assertIs(r.outcome, Outcome.SKIPPED)
        self.assertEqual(ctx.waits, [])
        m.assert_not_called()

    def test_interrupted_during_wait_is_skipped(self):
        with mock.patch.object(fd, "_http_get",
                               return_value=(200, _sample_html())):
            r = _run({"query": "x"}, ctx=_StopAfterRequest())
        self.assertIs(r.outcome, Outcome.SKIPPED)

    def test_rhythm_floor_enforced(self):
        """task 透传的 config 节奏（13-20s）低于 60s 地板 → 强制 60s。"""
        with mock.patch.object(fd, "_http_get",
                               return_value=(200, _sample_html())):
            ctx = _Ctx()
            _run({"query": "x", "sample_min": 10, "sample_max": 20}, ctx=ctx)
        self.assertEqual(ctx.waits, [60.0])

    def test_rhythm_range_respected(self):
        with mock.patch.object(fd, "_http_get",
                               return_value=(200, _sample_html())):
            ctx = _Ctx()
            _run({"query": "x", "sample_min": 90, "sample_max": 120}, ctx=ctx)
        self.assertEqual(len(ctx.waits), 1)
        self.assertGreaterEqual(ctx.waits[0], 90)
        self.assertLessEqual(ctx.waits[0], 120)


class _FakeResp:
    """最小 urllib 响应替身：可带 gzip 头。"""

    def __init__(self, body: bytes, encoding: str | None = None):
        self._body = body
        self.headers = {}
        if encoding:
            self.headers["Content-Encoding"] = encoding
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestHttpGet(unittest.TestCase):
    def test_request_headers(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResp(b"<html>ok</html>")) as m:
            status, html = fd._http_get(
                "https://html.duckduckgo.com/html/?q=x", timeout=5)
        self.assertEqual(status, 200)
        self.assertEqual(html, "<html>ok</html>")
        req = m.call_args[0][0]
        # Request 的 add_header 会把 key 首字母大写、其余小写，get_header 在此
        # Python 版本是大小写敏感直接查 dict——统一转小写做不区分大小写断言。
        sent = {k.lower(): v for k, v in req.headers.items()}
        self.assertTrue(sent["user-agent"].startswith("Mozilla/"))
        self.assertEqual(sent["accept-language"], "zh-CN")
        self.assertEqual(sent["accept-encoding"], "gzip")
        self.assertEqual(m.call_args[1]["timeout"], 5)

    def test_gzip_decompress(self):
        raw = "<html>gzipped</html>".encode("utf-8")
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResp(gzip.compress(raw),
                                               encoding="gzip")):
            status, html = fd._http_get(
                "https://html.duckduckgo.com/html/?q=x")
        self.assertEqual(status, 200)
        self.assertEqual(html, "<html>gzipped</html>")

    def test_http_error_returns_status(self):
        err = urllib.error.HTTPError("https://x", 429, "rate limited",
                                     hdrs={}, fp=None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            status, html = fd._http_get(
                "https://html.duckduckgo.com/html/?q=x")
        self.assertEqual(status, 429)
        self.assertEqual(html, "")

    def test_urlerror_raised(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("dns fail")):
            with self.assertRaises(urllib.error.URLError):
                fd._http_get("https://html.duckduckgo.com/html/?q=x")

    def test_socket_timeout_raised(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=socket.timeout("timed out")):
            with self.assertRaises(socket.timeout):
                fd._http_get("https://html.duckduckgo.com/html/?q=x")


if __name__ == "__main__":
    unittest.main()
