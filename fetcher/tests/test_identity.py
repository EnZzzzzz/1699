# -*- coding: utf-8 -*-
"""IdentityStore 单测：Cookie 按 identity 隔离、过期剔除、burn 清空。
使用临时 sqlite 文件，不碰真实数据库。"""

import tempfile
import time
import unittest
from pathlib import Path

from fetcher import IdentityStore, ShopDB

NOW = int(time.time())


def ck(name, value="v", domain=".1688.com", expires=None):
    c = {"name": name, "value": value, "domain": domain, "path": "/",
         "secure": False, "httpOnly": False}
    if expires is not None:
        c["expires"] = expires
    return c


class FakeBrowserContext:
    """mock playwright BrowserContext（仅 cookies()）。"""

    def __init__(self, cookies):
        self._cookies = cookies

    def cookies(self):
        return list(self._cookies)


class IdentityStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = ShopDB(self.db_path)
        self.store = IdentityStore(self.db, domain="1688.com")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_save_load_roundtrip(self):
        self.store.save("1.2.3.4", [ck("cna", "aaa"), ck("cookie2", "bbb")])
        loaded = self.store.load("1.2.3.4")
        names = {c["name"] for c in loaded}
        self.assertEqual(names, {"cna", "cookie2"})
        # Playwright 格式字段
        one = next(c for c in loaded if c["name"] == "cna")
        self.assertEqual(one["value"], "aaa")
        self.assertIn("httpOnly", one)

    def test_identity_isolation(self):
        self.store.save("1.1.1.1", [ck("cna", "ip1")])
        self.store.save("2.2.2.2", [ck("cna", "ip2")])
        self.assertEqual(self.store.load("1.1.1.1")[0]["value"], "ip1")
        self.assertEqual(self.store.load("2.2.2.2")[0]["value"], "ip2")
        self.assertEqual(self.store.load("3.3.3.3"), [])

    def test_expired_cookies_excluded(self):
        self.store.save("1.2.3.4", [
            ck("fresh", expires=NOW + 3600),
            ck("stale", expires=NOW - 3600),
            ck("session"),  # 无 expires = 会话 Cookie，保留
        ])
        names = {c["name"] for c in self.store.load("1.2.3.4")}
        self.assertEqual(names, {"fresh", "session"})

    def test_upsert_overwrites_same_cookie(self):
        self.store.save("1.2.3.4", [ck("x5sec", "old")])
        self.store.save("1.2.3.4", [ck("x5sec", "new")])
        loaded = self.store.load("1.2.3.4")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["value"], "new")

    def test_burn_clears_only_target_identity(self):
        self.store.save("1.1.1.1", [ck("cna"), ck("cookie2")])
        self.store.save("2.2.2.2", [ck("cna")])
        n = self.store.burn("1.1.1.1")
        self.assertEqual(n, 2)
        self.assertEqual(self.store.load("1.1.1.1"), [])
        self.assertEqual(len(self.store.load("2.2.2.2")), 1)

    def test_info_counts(self):
        self.store.save("1.2.3.4", [
            ck("fresh", expires=NOW + 3600),
            ck("stale", expires=NOW - 3600),
        ])
        info = self.store.info("1.2.3.4")
        self.assertEqual(info["total"], 2)
        self.assertEqual(info["expired"], 1)

    def test_save_from_context_filters_domain(self):
        ctx = FakeBrowserContext([
            ck("cna", domain=".1688.com"),
            ck("other", domain=".taobao.com"),
        ])
        n = self.store.save_from_context("1.2.3.4", ctx, log=lambda m: None)
        self.assertEqual(n, 1)
        self.assertEqual(self.store.load("1.2.3.4")[0]["name"], "cna")

    def test_seed_from_json(self):
        seed_json = Path(self._tmp.name) / "seeds.json"
        seed_json.write_text(
            '[{"name":"cna","value":"s","domain":".1688.com"},'
            ' {"name":"t","value":"x","domain":".taobao.com"}]',
            encoding="utf-8")
        n = self.store.seed_from_json("direct", seed_json)
        self.assertEqual(n, 1)  # 域过滤在播种时生效（taobao.com 被剔除）
        names = {c["name"] for c in self.store.load("direct")}
        self.assertEqual(names, {"cna"})

    def test_ip_event_recording(self):
        self.store.record_event("1.2.3.4", "block_slider", "测试", req_since_block=7)
        rows = self.db.conn.execute(
            "SELECT event, req_since_block FROM ip_events"
            " WHERE identity='1.2.3.4'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "block_slider")
        self.assertEqual(rows[0]["req_since_block"], 7)


if __name__ == "__main__":
    unittest.main()
