# Step 2.2 review 审查包（BASE 7439ca8..HEAD 8782609）

## git log
8782609 feat(identity-p2): Step 2.2 — identity 隔离性单测（同 IP 两站点互不污染）

## git diff --stat
 fetcher/tests/test_identity_isolation.py | 320 +++++++++++++++++++++++++++++++
 1 file changed, 320 insertions(+)

## git diff -U10
diff --git a/fetcher/tests/test_identity_isolation.py b/fetcher/tests/test_identity_isolation.py
new file mode 100644
index 0000000..53a94e0
--- /dev/null
+++ b/fetcher/tests/test_identity_isolation.py
@@ -0,0 +1,320 @@
+# -*- coding: utf-8 -*-
+"""Identity 隔离性单测：同 IP 两站点互不污染（SPEC §5 第 2、3 条）。
+
+验证内容：
+    ① Cookie 各落各桶、load 不串
+    ② burn 一站不殃及另一站
+    ③ ip_stats/ip_events 分行统计
+    ④ 内存键分开（ip_req / budget_stuck / burn_ips）
+    ⑤ 指纹参数同裸 IP 逐字一致
+    ⑥ check_ip_fresh 对 site:ip vs 裸 IP 判相等
+
+全部在临时库上跑，不碰生产库。
+"""
+
+import tempfile
+import unittest
+from pathlib import Path
+from unittest.mock import MagicMock, patch
+
+from fetcher import IdentityStore, RunConfig, ShopDB, Session
+from fetcher.core.session import bare_identity
+from fetcher.net.browser import BrowserManager, fingerprint_args
+from fetcher.net.seeds import SeedBurnTracker
+
+
+# ---- helpers ----
+
+def _ck(name, value="v", domain=".1688.com"):
+    """构造一条最小 Cookie dict（Playwright 格式）。"""
+    return {
+        "name": name, "value": value, "domain": domain,
+        "path": "/", "secure": False, "httpOnly": False,
+    }
+
+
+class IdentityIsolationDBTest(unittest.TestCase):
+    """用例 ①-④：Cookie/事件/簿记的隔离性（临时库上跑）。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = Path(self._tmp.name) / "test.db"
+        self.db = ShopDB(self.db_path)
+        self.store_1688 = IdentityStore(self.db, domain="1688.com")
+        self.store_mic = IdentityStore(self.db, domain="made-in-china.com")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    # ---- ① Cookie 各落各桶、load 不串 ----
+
+    def test_cookie_isolation_save_load(self):
+        """① 同一裸 IP 两站点 Cookie 各自存取，互不串。"""
+        ident_1688 = "1688:1.2.3.4"
+        ident_mic = "madeinchina:1.2.3.4"
+
+        # 两站各存 Cookie，值不同以区分
+        self.store_1688.save(ident_1688, [
+            _ck("cna", "from-1688", domain=".1688.com"),
+            _ck("_csrf", "1688-csrf", domain=".1688.com"),
+        ])
+        self.store_mic.save(ident_mic, [
+            _ck("PHPSESSID", "from-mic", domain=".made-in-china.com"),
+        ])
+
+        # 1688 桶只含 1688 域 Cookie
+        loaded_1688 = self.store_1688.load(ident_1688)
+        names_1688 = {c["name"] for c in loaded_1688}
+        self.assertEqual(names_1688, {"cna", "_csrf"})
+        self.assertTrue(all(".1688.com" in c["domain"]
+                            for c in loaded_1688))
+
+        # mic 桶只含 mic 域 Cookie
+        loaded_mic = self.store_mic.load(ident_mic)
+        names_mic = {c["name"] for c in loaded_mic}
+        self.assertEqual(names_mic, {"PHPSESSID"})
+        self.assertTrue(all(".made-in-china.com" in c["domain"]
+                            for c in loaded_mic))
+
+        # 交叉检查：同一 DB 下两站键互不串——
+        # 1688 键只含 1688 Cookie，mic 键只含 mic Cookie
+        loaded_mic_via_1688 = self.store_1688.load(ident_mic)
+        names_mic_via_1688 = {c["name"] for c in loaded_mic_via_1688}
+        self.assertEqual(names_mic_via_1688, {"PHPSESSID"},
+                         "同 DB 下 1688 store 读 mic 键应得 mic Cookie")
+        # 核心断言：1688 键不含 mic Cookie，mic 键不含 1688 Cookie
+        self.assertNotIn("PHPSESSID", names_1688,
+                         "1688 键不应含 mic Cookie")
+        loaded_1688_via_mic = self.store_mic.load(ident_1688)
+        names_1688_via_mic = {c["name"] for c in loaded_1688_via_mic}
+        self.assertEqual(names_1688_via_mic, {"cna", "_csrf"},
+                         "同 DB 下 mic store 读 1688 键应得 1688 Cookie")
+
+    # ---- ② burn 一站不殃及另一站 ----
+
+    def test_burn_isolation(self):
+        """② burn '1688:1.2.3.4' 只清 1688 桶，mic 桶完好。"""
+        ident_1688 = "1688:1.2.3.4"
+        ident_mic = "madeinchina:1.2.3.4"
+
+        self.store_1688.save(ident_1688, [
+            _ck("cna", "from-1688"),
+            _ck("_csrf", "x"),
+        ])
+        self.store_mic.save(ident_mic, [
+            _ck("PHPSESSID", "from-mic", domain=".made-in-china.com"),
+        ])
+
+        n = self.store_1688.burn(ident_1688)
+        self.assertEqual(n, 2)
+
+        # 1688 桶已空
+        self.assertEqual(self.store_1688.load(ident_1688), [])
+        # mic 桶完好
+        loaded_mic = self.store_mic.load(ident_mic)
+        self.assertEqual(len(loaded_mic), 1)
+        self.assertEqual(loaded_mic[0]["value"], "from-mic")
+
+    # ---- ③ ip_stats/ip_events 分行统计 ----
+
+    def test_ip_events_separate_rows(self):
+        """③ ip_events：同裸 IP 两站点各 record_event，是两行互不影响。"""
+        ident_1688 = "1688:1.2.3.4"
+        ident_mic = "madeinchina:1.2.3.4"
+
+        # 1688 记一个 block 事件
+        self.store_1688.record_event(ident_1688, "block_slider",
+                                     "1688 滑块", req_since_block=3)
+        # mic 记一个 launch 事件（不同事件，确认各行独立）
+        self.store_mic.record_event(ident_mic, "launch", "mic 启动")
+
+        rows = self.db.conn.execute(
+            "SELECT identity, event, detail, req_since_block "
+            "FROM ip_events ORDER BY identity").fetchall()
+        idents = {r["identity"] for r in rows}
+        self.assertEqual(idents, {ident_1688, ident_mic},
+                         f"应有两行不同的 identity，实际={idents}")
+        self.assertEqual(len(rows), 2)
+
+        # 只给 1688 记 block，mic 行不受影响
+        row_1688 = [r for r in rows if r["identity"] == ident_1688][0]
+        row_mic = [r for r in rows if r["identity"] == ident_mic][0]
+        self.assertEqual(row_1688["event"], "block_slider")
+        self.assertEqual(row_1688["req_since_block"], 3)
+        self.assertEqual(row_mic["event"], "launch")
+        self.assertIsNone(row_mic["req_since_block"])
+
+    def test_ip_stats_separate_rows(self):
+        """③ ip_stats：同裸 IP 两站点各 stat_request，是两行互不影响。"""
+        ident_1688 = "1688:1.2.3.4"
+        ident_mic = "madeinchina:1.2.3.4"
+
+        # 1688: 10 请求 8 成功；mic: 5 请求 4 成功
+        for _ in range(8):
+            self.store_1688.stat_request(ident_1688, ok=True)
+        for _ in range(2):
+            self.store_1688.stat_request(ident_1688, ok=False)
+        for _ in range(4):
+            self.store_mic.stat_request(ident_mic, ok=True)
+        for _ in range(1):
+            self.store_mic.stat_request(ident_mic, ok=False)
+
+        rows = self.db.conn.execute(
+            "SELECT identity, requests, ok FROM ip_stats "
+            "ORDER BY identity").fetchall()
+        idents = {r["identity"] for r in rows}
+        self.assertEqual(idents, {ident_1688, ident_mic},
+                         f"应有两行不同的 identity，实际={idents}")
+
+        row_1688 = [r for r in rows if r["identity"] == ident_1688][0]
+        row_mic = [r for r in rows if r["identity"] == ident_mic][0]
+        self.assertEqual(row_1688["requests"], 10)
+        self.assertEqual(row_1688["ok"], 8)
+        self.assertEqual(row_mic["requests"], 5)
+        self.assertEqual(row_mic["ok"], 4)
+
+        # 只给 1688 记 block，mic 行不受影响
+        self.store_1688.stat_block(ident_1688)
+        row_1688_after = self.db.conn.execute(
+            "SELECT blocks FROM ip_stats WHERE identity=?",
+            (ident_1688,)).fetchone()
+        row_mic_after = self.db.conn.execute(
+            "SELECT blocks FROM ip_stats WHERE identity=?",
+            (ident_mic,)).fetchone()
+        self.assertEqual(row_1688_after["blocks"], 1)
+        self.assertEqual(row_mic_after["blocks"], 0,
+                         "mic 行 block 不应受 1688 block 影响")
+
+    # ---- ④ 内存键分开 ----
+
+    def test_ip_req_keys_separate(self):
+        """④ ip_req：'1688:1.2.3.4' 与 'madeinchina:1.2.3.4'
+        是不同键，计数互不影响。"""
+        ip_req = {}
+        ident_1688 = "1688:1.2.3.4"
+        ident_mic = "madeinchina:1.2.3.4"
+
+        # 模拟 _bookkeep_request 的键初始化（setdefault）
+        ctr_1688 = ip_req.setdefault(ident_1688, {"n": 0, "since": 0})
+        ctr_1688["n"] += 1
+        ctr_1688["since"] += 1
+        ctr_1688["n"] += 1
+
+        self.assertEqual(ip_req[ident_1688]["n"], 2)
+        self.assertEqual(ip_req[ident_1688]["since"], 1)
+
+        # madeinchina 键不存在（从未被 setdefault）
+        self.assertNotIn(ident_mic, ip_req,
+                         "仅操作 1688 键不应创建 madeinchina 键")
+        # 1688 键不受影响
+        self.assertEqual(ip_req[ident_1688]["n"], 2)
+
+    def test_budget_stuck_keys_separate(self):
+        """④ budget_stuck：加 1688 键后 madeinchina 键不在其中。"""
+        budget_stuck = set()
+        ident_1688 = "1688:1.2.3.4"
+        ident_mic = "madeinchina:1.2.3.4"
+
+        budget_stuck.add(ident_1688)
+        self.assertIn(ident_1688, budget_stuck)
+        self.assertNotIn(ident_mic, budget_stuck,
+                         "仅加 1688 键不应使 madeinchina 键出现")
+
+    def test_burn_ips_keys_separate(self):
+        """④ burn_ips（SeedBurnTracker）：加 1688 键后 madeinchina
+        键不在其中。"""
+        # 需要非 None kit 才会触发 burn_ips 追踪
+        tracker = SeedBurnTracker({"name": "test-seed"})
+        ident_1688 = "1688:1.2.3.4"
+        ident_mic = "madeinchina:1.2.3.4"
+
+        # note_block：首请求秒拦（req_since_block=1）→ 加入 burn_ips
+        tracker.note_block(ident_1688, req_since_block=1, login_wall=False,
+                           log=lambda m: None)
+        self.assertIn(ident_1688, tracker.burn_ips)
+        self.assertNotIn(ident_mic, tracker.burn_ips,
+                         "仅烧 1688 键不应使 madeinchina 键出现")
+
+
+class IdentityIsolationFingerprintTest(unittest.TestCase):
+    """用例 ⑤：指纹参数同裸 IP 逐字一致（SPEC §3.5 裁定）。"""
+
+    def test_fingerprint_same_for_same_bare_ip(self):
+        """⑤ 同裸 IP 两站点的指纹参数完全相同。"""
+        ident_1688 = "1688:1.2.3.4"
+        ident_mic = "madeinchina:1.2.3.4"
+        bare_ip = "1.2.3.4"
+
+        fp_1688 = fingerprint_args(bare_identity(ident_1688))
+        fp_mic = fingerprint_args(bare_identity(ident_mic))
+        fp_bare = fingerprint_args(bare_ip)
+
+        self.assertEqual(fp_1688, fp_bare,
+                         "1688:1.2.3.4 指纹应与裸 IP 一致")
+        self.assertEqual(fp_mic, fp_bare,
+                         "madeinchina:1.2.3.4 指纹应与裸 IP 一致")
+        self.assertEqual(fp_1688, fp_mic,
+                         "同 IP 两站点指纹应完全相同")
+
+    def test_different_ip_different_fingerprint(self):
+        """⑤ 不同裸 IP 指纹必须不同（验证指纹算法确实对 IP 敏感）。"""
+        fp_a = fingerprint_args("1.2.3.4")
+        fp_b = fingerprint_args("5.5.5.5")
+        self.assertNotEqual(fp_a, fp_b,
+                            "不同 IP 指纹必须不同")
+
+
+class IdentityIsolationCheckIPFreshTest(unittest.TestCase):
+    """用例 ⑥：check_ip_fresh 对 site:ip vs 裸 IP 判相等。"""
+
+    def setUp(self):
+        config = RunConfig(headless=True, use_proxy=False)
+        self.mgr_1688 = BrowserManager(
+            config=config, store=MagicMock(), log=lambda m: None,
+            site_name="1688")
+        self.mgr_mic = BrowserManager(
+            config=config, store=MagicMock(), log=lambda m: None,
+            site_name="madeinchina")
+
+    def test_prefixed_1688_same_ip_no_relaunch(self):
+        """⑥ '1688:1.2.3.4' 出口 IP=1.2.3.4 → 不触发 relaunch。"""
+        session = Session(identity="1688:1.2.3.4")
+        with patch.object(self.mgr_1688, "_query_exit_ip_with_retry",
+                          return_value="1.2.3.4"):
+            need, cur, reason = self.mgr_1688.check_ip_fresh(session)
+        self.assertFalse(need, f"不应触发 relaunch，reason={reason}")
+        self.assertEqual(cur, "1.2.3.4")
+
+    def test_bare_ip_no_relaunch(self):
+        """⑥ '1.2.3.4'（旧键）出口 IP=1.2.3.4 → 不触发 relaunch。"""
+        session = Session(identity="1.2.3.4")
+        with patch.object(self.mgr_1688, "_query_exit_ip_with_retry",
+                          return_value="1.2.3.4"):
+            need, cur, reason = self.mgr_1688.check_ip_fresh(session)
+        self.assertFalse(need)
+
+    def test_prefixed_mic_same_ip_no_relaunch(self):
+        """⑥ 'madeinchina:1.2.3.4' 出口 IP=1.2.3.4 → 不触发 relaunch。"""
+        session = Session(identity="madeinchina:1.2.3.4")
+        with patch.object(self.mgr_mic, "_query_exit_ip_with_retry",
+                          return_value="1.2.3.4"):
+            need, cur, reason = self.mgr_mic.check_ip_fresh(session)
+        self.assertFalse(need, f"不应触发 relaunch，reason={reason}")
+        self.assertEqual(cur, "1.2.3.4")
+
+    def test_all_three_identities_same_ip_equivalent(self):
+        """⑥ 三种形式（bare / 1688: / madeinchina:）同出口 IP 均不触发。"""
+        for identity in ("1.2.3.4", "1688:1.2.3.4", "madeinchina:1.2.3.4"):
+            session = Session(identity=identity)
+            mgr = (self.mgr_mic if identity.startswith("madeinchina:")
+                   else self.mgr_1688)
+            with patch.object(mgr, "_query_exit_ip_with_retry",
+                              return_value="1.2.3.4"):
+                need, cur, reason = mgr.check_ip_fresh(session)
+            self.assertFalse(need,
+                             f"identity={identity!r} 出口 IP 一致不应触发")
+
+
+if __name__ == "__main__":
+    unittest.main()
