# -*- coding: utf-8 -*-
"""IdentityStore 单测：Cookie 按 identity 隔离、过期剔除、burn 清空。
使用临时 sqlite 文件，不碰真实数据库。"""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from fetcher import IdentityStore, RunConfig, Session, ShopDB, WorkerContext
from fetcher.atoms.identity_ops import ClearIdentity
from fetcher.core.types import Outcome

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


class IdentityP2CompatibilityTest(unittest.TestCase):
    """Step 1.2 identity 辅助函数集成测试：验证 6 处修正点的行为。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = ShopDB(self.db_path)
        self.store = IdentityStore(self.db, domain="1688.com")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    # ---- #3: ClearIdentity 对 prefixed direct 跳过 ----

    def test_clear_identity_skips_prefixed_direct(self):
        """ClearIdentity: '1688:direct' 视为直连，跳过不清空。

        RED 预期（修正前）：'1688:direct' == 'direct' → False → 尝试
        burn → 不走 skipped 路径 → 断言 Outcome.SKIPPED 失败。
        """
        config = RunConfig(db_path=str(self.db_path))
        ctx = WorkerContext(config=config, store=self.store,
                            stop=threading.Event(), log=lambda m: None)
        ctx.session = Session(identity="1688:direct")
        result = ClearIdentity().run(ctx, {})
        self.assertIs(result.outcome, Outcome.SKIPPED,
                      f"期望跳过直连身份，实际 outcome={result.outcome}")

    def test_clear_identity_burns_non_direct(self):
        """ClearIdentity: 非直连 IP 正常清空。"""
        # 预置 Cookie
        self.store.save("1.2.3.4", [{"name": "cna", "value": "v",
                                      "domain": ".1688.com", "path": "/"}])
        config = RunConfig(db_path=str(self.db_path))
        ctx = WorkerContext(config=config, store=self.store,
                            stop=threading.Event(), log=lambda m: None)
        ctx.session = Session(identity="1.2.3.4")
        result = ClearIdentity().run(ctx, {})
        self.assertIs(result.outcome, Outcome.OK)
        self.assertEqual(self.store.load("1.2.3.4"), [])

    def test_clear_identity_skips_bare_direct(self):
        """ClearIdentity: 旧键 'direct' 行为不变（回归验证）。"""
        config = RunConfig(db_path=str(self.db_path))
        ctx = WorkerContext(config=config, store=self.store,
                            stop=threading.Event(), log=lambda m: None)
        ctx.session = Session(identity="direct")
        result = ClearIdentity().run(ctx, {})
        self.assertIs(result.outcome, Outcome.SKIPPED)

    # ---- #4: ip_event_summary 过滤 site:direct ----

    def _seed_ip_events(self):
        """插入 4 行 ip_events：'direct', '1688:direct', '1.2.3.4',
        '1688:1.2.3.4' 各一条 launch 事件。"""
        for ident in ("direct", "1688:direct", "1.2.3.4", "1688:1.2.3.4"):
            self.db.conn.execute(
                "INSERT INTO ip_events (identity, event, detail, "
                "req_since_block, created_at) VALUES (?, 'launch', '', 0, "
                "datetime('now', 'localtime'))", (ident,))
        self.db.conn.commit()

    def test_ip_event_summary_excludes_prefixed_direct(self):
        """ip_event_summary: '1688:direct' 与 'direct' 都应被排除。

        RED 预期（修正前）：WHERE identity != 'direct' → '1688:direct'
        满足 != 'direct' → 被包含在结果中 → 断言 len==2 失败（得 3）。
        """
        self._seed_ip_events()
        rows = self.db.ip_event_summary()
        idents = {r["identity"] for r in rows}
        # 修正后：只保留不带 :direct 后缀的 IP 身份
        self.assertEqual(idents, {"1.2.3.4", "1688:1.2.3.4"},
                         f"期望只含 IP 行，实际={idents}")
        self.assertEqual(len(rows), 2)

    # ---- #5: format_tmd_report 列宽容纳 site:ip ----

    def _seed_ip_stats(self, identity, requests=10, ok=8, blocks=2):
        """插入一条 ip_stats 行并记录一次 block 事件。"""
        self.db.conn.execute(
            "INSERT INTO ip_stats (identity, requests, ok, updated_at) "
            "VALUES (?, ?, ?, datetime('now', 'localtime'))",
            (identity, requests, ok))
        # 记录一次 block 事件以生成 tmd 统计
        self.db.conn.execute(
            "INSERT INTO ip_events (identity, event, detail, "
            "req_since_block, created_at) VALUES "
            "(?, 'block_slider', '', ?, datetime('now', 'localtime'))",
            (identity, 5))
        self.db.conn.commit()

    def test_format_tmd_report_fits_long_identity(self):
        """format_tmd_report: 不同长度 identity 的请求列对齐到同一位。

        RED 预期（修正前）：列宽 17 < 21-long identity → 短 identity
        ("1.2.3.4") 的请求列在 position 21，长 identity
        ("madeinchina:1.2.3.4") 在 position 25 → 不相等 → 断言失败。
        """
        ident_long = "madeinchina:1.2.3.4"
        ident_short = "1.2.3.4"
        self._seed_ip_stats(ident_long)
        self._seed_ip_stats(ident_short)
        report = self.db.format_tmd_report()
        # 提取两条数据行，计算「请求」列（第一个数字）的起始位置
        positions = {}
        for ident in (ident_long, ident_short):
            self.assertIn(ident, report,
                          f"期望报告中包含 identity={ident}")
            line = [l for l in report.split("\n") if ident in l][0]
            # identity 在行中的位置
            idx = line.index(ident)
            # identity 之后第一个数字的位置
            after = line[idx + len(ident):]
            digit_pos = idx + len(ident) + len(after) - len(after.lstrip())
            positions[ident] = digit_pos
        # 修正后：两行的请求列应起始于同一列
        self.assertEqual(
            positions[ident_long], positions[ident_short],
            f"不同长度 identity 的请求列应对齐，实际 "
            f"{ident_short}={positions[ident_short]}, "
            f"{ident_long}={positions[ident_long]}")


if __name__ == "__main__":
    unittest.main()
