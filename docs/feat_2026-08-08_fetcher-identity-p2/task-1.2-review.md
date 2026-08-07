# Step 1.2 review 审查包（BASE 446effa..HEAD bfd97d3）

## git log
bfd97d3 feat(identity-p2): Step 1.2 辅助函数 + 隐藏点修正（SPEC §3.3 #1-#6）

## git diff --stat
 fetcher/fetcher/atoms/identity_ops.py |   3 +-
 fetcher/fetcher/control/loop.py       |   4 +-
 fetcher/fetcher/core/session.py       |  16 +++++
 fetcher/fetcher/db.py                 |   6 +-
 fetcher/fetcher/net/browser.py        |   6 +-
 fetcher/tests/test_browser_fresh.py   | 129 +++++++++++++++++++++++++++++++++
 fetcher/tests/test_control_loop.py    |  26 +++++++
 fetcher/tests/test_identity.py        | 130 +++++++++++++++++++++++++++++++++-
 fetcher/tests/test_session_helpers.py |  53 ++++++++++++++
 9 files changed, 363 insertions(+), 10 deletions(-)

## git diff -U10
diff --git a/fetcher/fetcher/atoms/identity_ops.py b/fetcher/fetcher/atoms/identity_ops.py
index d1659ab..c60334c 100644
--- a/fetcher/fetcher/atoms/identity_ops.py
+++ b/fetcher/fetcher/atoms/identity_ops.py
@@ -1,33 +1,34 @@
 # -*- coding: utf-8 -*-
 """身份操作原子：ClearIdentity（登录墙烧毁清空 Cookie）。"""
 
 from __future__ import annotations
 
+from fetcher.core.session import is_direct
 from fetcher.core.types import ActionResult
 
 
 class ClearIdentity:
     """清空当前 identity 名下的全部 Cookie。
 
     登录墙 = 会话身份被最高级标记：清空该 IP 名下的 Cookie，避免代理
     把此 IP 轮换回来时复活已烧毁的会话（迁移自引擎的登录墙处理段）。
     直连身份（direct）不清空 —— 直连 Cookie 是本机签发的，登录墙
     时应由人工处理而不是烧毁本机身份。
     """
 
     name = "clear_identity"
     title = "清空身份 Cookie"
 
     def run(self, ctx, params: dict) -> ActionResult:
         if ctx.store is None:
             return ActionResult.fatal("未装配 identity store")
         identity = ctx.identity
-        if identity == "direct":
+        if is_direct(identity):
             return ActionResult.skipped("直连身份不清空（由人工处理）")
         try:
             n = ctx.store.burn(identity)
             ctx.log(f"    🧹 登录墙标记：已清空 {identity} 名下的 {n} 条 Cookie"
                     f"（会话身份已烧毁，此 IP 轮换回来时按全新身份重建）")
             return ActionResult.success(f"已清空 {n} 条 Cookie", count=n)
         except Exception as e:  # noqa: BLE001
             return ActionResult.blocked(f"清空登录墙 IP Cookie 失败: {e}")
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index a214e94..724af46 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -23,21 +23,21 @@ item 级重试循环 → 收尾清理），但风控状态机不再写死在控
 from __future__ import annotations
 
 import random
 import time
 
 from fetcher.atoms.browser_ops import RelaunchBrowser
 from fetcher.control.board import wait_countdown
 from fetcher.control.circuit import CircuitBreaker
 from fetcher.control.task import Task
 from fetcher.core.errors import UserInterrupted
-from fetcher.core.session import Session
+from fetcher.core.session import Session, is_direct
 from fetcher.core.types import Outcome, Scenario
 from fetcher.detect.base import SceneInspector
 from fetcher.net.seeds import SeedBurnTracker
 from fetcher.strategy.base import PolicyAction
 from fetcher.strategy.policy import AttemptTracker, Policy
 
 # fetch 自报 outcome 到 Scenario 的兜底映射（探测器判 OK 但 fetch
 # 显式报告异常时，信 fetch —— 对应旧 scrape 返回 _blocked/_fatal/
 # _net_error 标记的契约）
 _OUTCOME_FALLBACK = {
@@ -441,21 +441,21 @@ class CrawlLoop:
             ctx.store.record_event(identity,
                                    _EVENT_NAMES.get(scenario, "block_other"),
                                    reason, req_since_block=since)
             ctx.store.stat_block(identity)
         ctr["since"] = 0
         self.log(f"  [tmd] 出口 {identity} 在 {since} 次请求后"
                  f"触发反爬（本 IP 累计 {ctr['n']} 次请求）")
 
         # 登录墙 = 会话身份最高级标记：判定当下立即烧毁该 IP 名下的
         # Cookie（避免轮换回来复活已烧毁会话）——与旧引擎同点位
-        if login_wall and identity != "direct" and ctx.store is not None:
+        if login_wall and not is_direct(identity) and ctx.store is not None:
             try:
                 n = ctx.store.burn(identity)
                 self.log(f"  🧹 登录墙标记：已清空 {identity} 名下的 {n} 条"
                          f" Cookie（此 IP 轮换回来时按全新身份重建）")
             except Exception as e:  # noqa: BLE001
                 self.log(f"  [!] 清空登录墙 IP Cookie 失败: {e}")
 
         # 种子烧毁判定：首请求秒拦/登录墙记到种子头上
         if self.seed_tracker.note_block(identity, since, login_wall,
                                         log=self.log):
diff --git a/fetcher/fetcher/core/session.py b/fetcher/fetcher/core/session.py
index ce67860..2c2f477 100644
--- a/fetcher/fetcher/core/session.py
+++ b/fetcher/fetcher/core/session.py
@@ -9,20 +9,36 @@
 
 from __future__ import annotations
 
 from dataclasses import dataclass, field
 from typing import TYPE_CHECKING, Any
 
 if TYPE_CHECKING:  # 避免 core -> net 的反向依赖
     from fetcher.net.proxy.base import Channel
 
 
+# ---------- identity 辅助函数 ----------
+
+def bare_identity(identity: str) -> str:
+    """剥掉站点前缀：'1688:1.2.3.4' → '1.2.3.4'；无前缀原样返回。
+
+    指纹/保鲜检查等需要裸 IP 的场合用此函数从 identity 键中提取裸 IP。
+    兼容旧键（无前缀直存 IP 或 'direct'）。
+    """
+    return identity.split(":", 1)[1] if ":" in identity else identity
+
+
+def is_direct(identity: str) -> bool:
+    """identity 是否代表直连模式（含 'direct' 与 'site:direct' 两种形态）。"""
+    return bare_identity(identity) == "direct"
+
+
 @dataclass
 class Session:
     """一次浏览器启动的产物。
 
     browser/page 为 Playwright 对象（Any 以保持本包可独立 import，
     不依赖 playwright 安装）。
     """
 
     browser: Any = None
     page: Any = None
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 43e98d8..6f1f978 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -674,21 +674,21 @@ class ShopDB:
             pass  # 事件流水不影响主流程
 
     def ip_event_summary(self) -> list[dict]:
         """按 IP 汇总事件次数（评估 IP 质量用）。"""
         rows = self.conn.execute(
             """SELECT identity,
                       SUM(event='launch')       AS launches,
                       SUM(event='block_slider') AS sliders,
                       SUM(event='block_login')  AS login_walls,
                       MAX(created_at)           AS last_seen
-               FROM ip_events WHERE identity != 'direct'
+               FROM ip_events WHERE identity NOT LIKE '%:direct' AND identity != 'direct'
                GROUP BY identity ORDER BY last_seen DESC""").fetchall()
         return [dict(r) for r in rows]
 
     # ---------- tmd（反爬验证）触发统计 ----------
 
     def ip_stat_request(self, identity: str, ok: bool = False) -> None:
         """累计该出口 IP 的一次页面请求（ok=True 表示成功解析）。
 
         每次 scrape 调用 = 一次页面请求；网络/代理层错误（请求没到目标站）
         由调用方跳过不计。tmd 率 = blocks / requests。
@@ -755,28 +755,28 @@ class ShopDB:
         回答三个问题：
             - tmd 率是多少：触发次数 / 页面请求数
             - 每爬多少个会触发一次反爬：触发间隔的平均/最少/最多
             - 一个 IP 爬多少个以内算安全：最少触发间隔 × 0.8
         """
         rep = self.tmd_report()
         rows, gaps = rep["rows"], rep["gaps"]
         if not rows:
             return "暂无 tmd 统计（还没有带统计的抓取记录）"
         lines = ["tmd（反爬验证）触发统计 —— 每个出口 IP 的安全性:",
-                 f"    {'出口IP':<17}{'请求':>6}{'成功':>6}{'触发':>5}"
+                 f"    {'出口IP':<22}{'请求':>6}{'成功':>6}{'触发':>5}"
                  f"{'tmd率':>8}{'平均间隔':>9}{'最少':>6}{'最多':>6}  最近触发"]
         for r in rows:
             rate = (f"{r['blocks'] / r['requests'] * 100:.1f}%"
                     if r["requests"] else "—")
             fmt = lambda v: f"{v:.0f}" if v is not None else "—"
             lines.append(
-                f"    {r['identity']:<17}{r['requests']:>6}{r['ok']:>6}"
+                f"    {r['identity']:<22}{r['requests']:>6}{r['ok']:>6}"
                 f"{r['blocks']:>5}{rate:>8}{fmt(r['avg_gap']):>9}"
                 f"{fmt(r['min_gap']):>6}{fmt(r['max_gap']):>6}  "
                 f"{r['last_block_at'] or '—'}")
         tot_req = sum(r["requests"] for r in rows)
         tot_blk = sum(r["blocks"] for r in rows)
         if tot_req:
             lines.append(f"    整体: {tot_req} 次页面请求，触发 {tot_blk} 次，"
                          f"tmd率 {tot_blk / tot_req * 100:.2f}%")
         if gaps:
             avg = sum(gaps) / len(gaps)
diff --git a/fetcher/fetcher/net/browser.py b/fetcher/fetcher/net/browser.py
index 39e224b..e987cb9 100644
--- a/fetcher/fetcher/net/browser.py
+++ b/fetcher/fetcher/net/browser.py
@@ -29,21 +29,21 @@ import threading
 import time
 from pathlib import Path
 
 from fetcher.core.context import RunConfig
 from fetcher.core.errors import (
     BrowserLaunchError,
     ExitIPError,
     LicenseSeatTimeout,
     UserInterrupted,
 )
-from fetcher.core.session import Session
+from fetcher.core.session import Session, bare_identity
 from fetcher.net.identity import IdentityStore
 
 # ---------- 配置加载 ----------
 
 # 各套餐的并发会话席位上限（服务端强制，超限的 launch 会以退出码 76
 # 拒绝；此处仅用于启动前主动等待，上限未知的套餐不阻塞直接放行）
 PLAN_SEATS = {"free": 1, "solo": 5}
 
 
 def load_license_key(config_json: Path | None = None) -> str | None:
@@ -186,21 +186,21 @@ class BrowserManager:
 
         青果出口 IP 每 30 分钟轮换一次：查询到的 IP 与 identity 不一致
         即视为已过期；查询失败先短重试 3 次确认隧道是否真的失效。
         查询仍失败时不强制 relaunch —— 重启同样依赖该查询，查询挂时重启
         大概率也失败；跳过本轮检查，交给 fetch 的 BROWSER_DEAD/NET_ERROR
         处置兜底，避免一个瞬时查询故障打死整个 worker。
         """
         cur_ip = self._query_exit_ip_with_retry(session.req_proxies)
         if cur_ip is None:
             return False, None, "出口 IP 查询失败（跳过本轮保鲜检查）"
-        if cur_ip != session.identity:
+        if cur_ip != bare_identity(session.identity):
             return True, cur_ip, f"出口 IP 已轮换（{session.identity} -> {cur_ip}）"
         return False, cur_ip, ""
 
     # ---- 启动 ----
 
     def launch(self, channel=None, seed_kit: dict = None,
                stop: threading.Event | None = None) -> Session:
         """启动 CloakBrowser 并注入 Cookie，返回 Session。
 
         channel: Channel 实例，或旧版兼容的 "host:port" 字符串
@@ -289,21 +289,21 @@ class BrowserManager:
         threading.Thread(target=_watchdog, daemon=True,
                          name=f"launch-watchdog-{identity}").start()
         try:
             browser = cloak_launch(
                 headless=cfg.headless,
                 license_key=load_license_key(),
                 humanize=True,
                 locale="zh-CN",
                 timezone="Asia/Shanghai",
                 stealth_args=False,
-                args=fingerprint_args(seed_kit["name"] if seed_kit else identity),
+                args=fingerprint_args(seed_kit["name"] if seed_kit else bare_identity(identity)),
                 **({"proxy": proxy_conf, "geoip": True} if proxy_conf else {}),
             )
         except SystemExit as e:
             raise BrowserLaunchError(
                 f"CloakBrowser 二进制退出（code={e.code}，"
                 f"多为会话席位被占或 License 校验失败）") from e
         finally:
             launch_done.set()
 
         self.log(f"    [launch] 浏览器进程已启动，创建上下文并注入 Cookie…")
diff --git a/fetcher/tests/test_browser_fresh.py b/fetcher/tests/test_browser_fresh.py
new file mode 100644
index 0000000..3ed6eb4
--- /dev/null
+++ b/fetcher/tests/test_browser_fresh.py
@@ -0,0 +1,129 @@
+# -*- coding: utf-8 -*-
+"""BrowserManager 单测：check_ip_fresh + fingerprint_args（Step 1.2 #1, #6）。"""
+
+import unittest
+from unittest.mock import patch, MagicMock
+
+from fetcher import RunConfig
+from fetcher.core.session import Session, bare_identity, is_direct
+from fetcher.net.browser import BrowserManager, fingerprint_args
+
+
+class CheckIPFreshP2Test(unittest.TestCase):
+    """#1: check_ip_fresh 使用 bare_identity 比较（避免误判 IP 轮换）。"""
+
+    def setUp(self):
+        config = RunConfig(headless=True, use_proxy=False)
+        self.mgr = BrowserManager(
+            config=config, store=MagicMock(), log=lambda m: None)
+
+    def _session(self, identity, req_proxies=None):
+        return Session(identity=identity, req_proxies=req_proxies)
+
+    def test_prefixed_identity_same_ip_no_relaunch(self):
+        """identity='1688:1.2.3.4' 出口 IP 同为 1.2.3.4 → 不触发 relaunch。
+
+        RED 预期（修正前）：cur_ip('1.2.3.4') != session.identity('1688:1.2.3.4')
+        → True → (True, ...) → 误判轮换。
+        """
+        session = self._session(identity="1688:1.2.3.4")
+        with patch.object(self.mgr, "_query_exit_ip_with_retry",
+                          return_value="1.2.3.4"):
+            need, cur, reason = self.mgr.check_ip_fresh(session)
+        self.assertFalse(need, f"不应触发 relaunch，reason={reason}")
+        self.assertEqual(cur, "1.2.3.4")
+
+    def test_bare_identity_same_ip_no_relaunch(self):
+        """identity='1.2.3.4'（旧键）出口 IP 同为 1.2.3.4 → 不触发 relaunch。
+
+        回归验证：旧键行为不变。
+        """
+        session = self._session(identity="1.2.3.4")
+        with patch.object(self.mgr, "_query_exit_ip_with_retry",
+                          return_value="1.2.3.4"):
+            need, cur, reason = self.mgr.check_ip_fresh(session)
+        self.assertFalse(need)
+
+    def test_prefixed_identity_changed_ip_triggers_relaunch(self):
+        """identity='1688:1.2.3.4' 出口 IP 变为 5.5.5.5 → 触发 relaunch。"""
+        session = self._session(identity="1688:1.2.3.4")
+        with patch.object(self.mgr, "_query_exit_ip_with_retry",
+                          return_value="5.5.5.5"):
+            need, cur, reason = self.mgr.check_ip_fresh(session)
+        self.assertTrue(need)
+        self.assertEqual(cur, "5.5.5.5")
+
+    def test_bare_identity_changed_ip_triggers_relaunch(self):
+        """identity='1.2.3.4'（旧键）出口 IP 变为 5.5.5.5 → 触发 relaunch。"""
+        session = self._session(identity="1.2.3.4")
+        with patch.object(self.mgr, "_query_exit_ip_with_retry",
+                          return_value="5.5.5.5"):
+            need, cur, reason = self.mgr.check_ip_fresh(session)
+        self.assertTrue(need)
+        self.assertEqual(cur, "5.5.5.5")
+
+
+class FingerprintArgsP2Test(unittest.TestCase):
+    """#6: fingerprint_args 接收裸 IP（非种子分支）。"""
+
+    def test_prefixed_ip_same_fingerprint_as_bare_ip(self):
+        """fingerprint_args 对 prefixed identity 与裸 IP 返回相同指纹。
+
+        修正后的调用形态：fingerprint_args(bare_identity("1688:1.2.3.4"))
+        应等于 fingerprint_args("1.2.3.4")。
+        """
+        self.assertEqual(
+            fingerprint_args(bare_identity("1688:1.2.3.4")),
+            fingerprint_args("1.2.3.4"),
+            "带前缀 identity 经 bare_identity 剥取后，指纹应与裸 IP 一致")
+
+    def test_prefixed_direct_same_fingerprint_as_direct(self):
+        """fingerprint_args 对 '1688:direct' 与 'direct' 返回相同指纹。"""
+        self.assertEqual(
+            fingerprint_args(bare_identity("1688:direct")),
+            fingerprint_args("direct"),
+            "prefixed direct 经 bare_identity 剥取后，指纹应与 'direct' 一致")
+
+    def test_launch_passes_bare_identity_to_fingerprint_args(self):
+        """launch 非种子分支传 bare_identity(identity) 给 fingerprint_args。
+
+        因当前代码 identity 尚未拼前缀（Step 1.3），这里验证修正后的
+        调用点：seed_kit=None 时传 bare_identity(identity)。
+        直连模式 identity='direct' → bare_identity 后仍为 'direct'，
+        与修正前行为逐字等价。
+
+        通过 monkeypatch fingerprint_args 捕获入参进行验证。
+        """
+        import fetcher.net.browser as browser_mod
+
+        captured_fp_args = []
+
+        def _capture_fp(identity):
+            captured_fp_args.append(identity)
+            return ["--no-sandbox", "--fingerprint=12345",
+                    "--fingerprint-platform=macos"]
+
+        config = RunConfig(
+            headless=True, use_proxy=False,
+            db_path="/nonexistent/test_1688.db")
+        mgr = BrowserManager(
+            config=config, store=MagicMock(), log=lambda m: None)
+
+        with patch.object(browser_mod, "fingerprint_args", _capture_fp):
+            try:
+                mgr.launch()
+            except Exception:
+                pass  # 预期后续步骤失败（无 cookies / cloakbrowser）
+
+        self.assertTrue(len(captured_fp_args) > 0,
+                        "fingerprint_args 应被调用过")
+        # 直连模式：identity='direct'，bare_identity 后仍为 'direct'
+        # 修正前传 'direct'，修正后传 bare_identity('direct')='direct' ——
+        # 行为等价（回归验证）
+        self.assertEqual(captured_fp_args[0], "direct",
+                         f"直连模式指纹入参应为 'direct'，"
+                         f"实际={captured_fp_args[0]!r}")
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/fetcher/tests/test_control_loop.py b/fetcher/tests/test_control_loop.py
index e7a9524..2430599 100644
--- a/fetcher/tests/test_control_loop.py
+++ b/fetcher/tests/test_control_loop.py
@@ -309,20 +309,46 @@ class CrawlLoopTest(LoopTestBase):
             [("page", "https://login.1688.com/member/signin.htm", "请登录", {})])
         table = {Scenario.RISK_LOGIN: [("wait_login", 1),
                                        ("give_up", None)]}
         policy = Policy(table=table, strategies={"wait_login": wait})
         CrawlLoop(ctx, task, policy=policy).run()
         # 判定当下即烧毁身份（与旧引擎同点位），不等策略链
         rows = self.db_query("SELECT COUNT(*) AS c FROM cookies"
                              " WHERE identity='1.1.1.1'")
         self.assertEqual(rows[0]["c"], 0)
 
+    def test_login_wall_does_not_burn_prefixed_direct(self):
+        """登录墙对 identity='1688:direct' 不烧毁（视为直连）。
+
+        RED 预期（修正前）：identity != "direct" → "1688:direct" != "direct"
+        → True → 触发 burn → Cookie 被清空 → 断言 cookies 仍存在失败。
+        """
+        # 构造返回 identity='1688:direct' 的 MockBrowserManager
+        mgr = MockBrowserManager(self.page, identities=("1688:direct",))
+        config = make_config(self.tmp)
+        ctx = make_ctx(self.tmp, self.page, mgr, config)
+        # 预置 Cookie 到 "1688:direct" 名下
+        ctx.store.save("1688:direct", [{"name": "cna", "value": "v",
+                                        "domain": ".1688.com", "path": "/"}])
+        wait = FakeStrategy()
+        task = ScriptedTask(
+            [("page", "https://login.1688.com/member/signin.htm", "请登录", {})])
+        table = {Scenario.RISK_LOGIN: [("wait_login", 1),
+                                       ("give_up", None)]}
+        policy = Policy(table=table, strategies={"wait_login": wait})
+        CrawlLoop(ctx, task, policy=policy).run()
+        # 修正后：is_direct("1688:direct") → True → 不清空
+        rows = self.db_query("SELECT COUNT(*) AS c FROM cookies"
+                             " WHERE identity='1688:direct'")
+        self.assertEqual(rows[0]["c"], 1,
+                         "prefixed direct 身份应保留 Cookie，不应被烧毁")
+
     def test_swap_ip_replaces_session_and_restarts_warm(self):
         swap = SwapForReal()
         task = ScriptedTask(
             [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {}),
              ("page", "https://shop123.1688.com/page/contactinfo.htm",
               "正常页面文本，足够长，包含电话、手机、地址字段标签内容，"
               "再补充一些文字确保超过空白页判定阈值。", {"v": 1})])
         table = {Scenario.RISK_SLIDER_PAGE: [("swap", 2), ("give_up", None)]}
         loop, ctx, _ = self.run_loop(task, table, {"swap": swap})
         self.assertEqual(task.succeeded, ["item1"])
diff --git a/fetcher/tests/test_identity.py b/fetcher/tests/test_identity.py
index 1b95cf4..f8a8ee2 100644
--- a/fetcher/tests/test_identity.py
+++ b/fetcher/tests/test_identity.py
@@ -1,20 +1,23 @@
 # -*- coding: utf-8 -*-
 """IdentityStore 单测：Cookie 按 identity 隔离、过期剔除、burn 清空。
 使用临时 sqlite 文件，不碰真实数据库。"""
 
 import tempfile
+import threading
 import time
 import unittest
 from pathlib import Path
 
-from fetcher import IdentityStore, ShopDB
+from fetcher import IdentityStore, RunConfig, Session, ShopDB, WorkerContext
+from fetcher.atoms.identity_ops import ClearIdentity
+from fetcher.core.types import Outcome
 
 NOW = int(time.time())
 
 
 def ck(name, value="v", domain=".1688.com", expires=None):
     c = {"name": name, "value": value, "domain": domain, "path": "/",
          "secure": False, "httpOnly": False}
     if expires is not None:
         c["expires"] = expires
     return c
@@ -114,12 +117,137 @@ class IdentityStoreTest(unittest.TestCase):
     def test_ip_event_recording(self):
         self.store.record_event("1.2.3.4", "block_slider", "测试", req_since_block=7)
         rows = self.db.conn.execute(
             "SELECT event, req_since_block FROM ip_events"
             " WHERE identity='1.2.3.4'").fetchall()
         self.assertEqual(len(rows), 1)
         self.assertEqual(rows[0]["event"], "block_slider")
         self.assertEqual(rows[0]["req_since_block"], 7)
 
 
+class IdentityP2CompatibilityTest(unittest.TestCase):
+    """Step 1.2 identity 辅助函数集成测试：验证 6 处修正点的行为。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = Path(self._tmp.name) / "test.db"
+        self.db = ShopDB(self.db_path)
+        self.store = IdentityStore(self.db, domain="1688.com")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    # ---- #3: ClearIdentity 对 prefixed direct 跳过 ----
+
+    def test_clear_identity_skips_prefixed_direct(self):
+        """ClearIdentity: '1688:direct' 视为直连，跳过不清空。
+
+        RED 预期（修正前）：'1688:direct' == 'direct' → False → 尝试
+        burn → 不走 skipped 路径 → 断言 Outcome.SKIPPED 失败。
+        """
+        config = RunConfig(db_path=str(self.db_path))
+        ctx = WorkerContext(config=config, store=self.store,
+                            stop=threading.Event(), log=lambda m: None)
+        ctx.session = Session(identity="1688:direct")
+        result = ClearIdentity().run(ctx, {})
+        self.assertIs(result.outcome, Outcome.SKIPPED,
+                      f"期望跳过直连身份，实际 outcome={result.outcome}")
+
+    def test_clear_identity_burns_non_direct(self):
+        """ClearIdentity: 非直连 IP 正常清空。"""
+        # 预置 Cookie
+        self.store.save("1.2.3.4", [{"name": "cna", "value": "v",
+                                      "domain": ".1688.com", "path": "/"}])
+        config = RunConfig(db_path=str(self.db_path))
+        ctx = WorkerContext(config=config, store=self.store,
+                            stop=threading.Event(), log=lambda m: None)
+        ctx.session = Session(identity="1.2.3.4")
+        result = ClearIdentity().run(ctx, {})
+        self.assertIs(result.outcome, Outcome.OK)
+        self.assertEqual(self.store.load("1.2.3.4"), [])
+
+    def test_clear_identity_skips_bare_direct(self):
+        """ClearIdentity: 旧键 'direct' 行为不变（回归验证）。"""
+        config = RunConfig(db_path=str(self.db_path))
+        ctx = WorkerContext(config=config, store=self.store,
+                            stop=threading.Event(), log=lambda m: None)
+        ctx.session = Session(identity="direct")
+        result = ClearIdentity().run(ctx, {})
+        self.assertIs(result.outcome, Outcome.SKIPPED)
+
+    # ---- #4: ip_event_summary 过滤 site:direct ----
+
+    def _seed_ip_events(self):
+        """插入 4 行 ip_events：'direct', '1688:direct', '1.2.3.4',
+        '1688:1.2.3.4' 各一条 launch 事件。"""
+        for ident in ("direct", "1688:direct", "1.2.3.4", "1688:1.2.3.4"):
+            self.db.conn.execute(
+                "INSERT INTO ip_events (identity, event, detail, "
+                "req_since_block, created_at) VALUES (?, 'launch', '', 0, "
+                "datetime('now', 'localtime'))", (ident,))
+        self.db.conn.commit()
+
+    def test_ip_event_summary_excludes_prefixed_direct(self):
+        """ip_event_summary: '1688:direct' 与 'direct' 都应被排除。
+
+        RED 预期（修正前）：WHERE identity != 'direct' → '1688:direct'
+        满足 != 'direct' → 被包含在结果中 → 断言 len==2 失败（得 3）。
+        """
+        self._seed_ip_events()
+        rows = self.db.ip_event_summary()
+        idents = {r["identity"] for r in rows}
+        # 修正后：只保留不带 :direct 后缀的 IP 身份
+        self.assertEqual(idents, {"1.2.3.4", "1688:1.2.3.4"},
+                         f"期望只含 IP 行，实际={idents}")
+        self.assertEqual(len(rows), 2)
+
+    # ---- #5: format_tmd_report 列宽容纳 site:ip ----
+
+    def _seed_ip_stats(self, identity, requests=10, ok=8, blocks=2):
+        """插入一条 ip_stats 行并记录一次 block 事件。"""
+        self.db.conn.execute(
+            "INSERT INTO ip_stats (identity, requests, ok, updated_at) "
+            "VALUES (?, ?, ?, datetime('now', 'localtime'))",
+            (identity, requests, ok))
+        # 记录一次 block 事件以生成 tmd 统计
+        self.db.conn.execute(
+            "INSERT INTO ip_events (identity, event, detail, "
+            "req_since_block, created_at) VALUES "
+            "(?, 'block_slider', '', ?, datetime('now', 'localtime'))",
+            (identity, 5))
+        self.db.conn.commit()
+
+    def test_format_tmd_report_fits_long_identity(self):
+        """format_tmd_report: 不同长度 identity 的请求列对齐到同一位。
+
+        RED 预期（修正前）：列宽 17 < 21-long identity → 短 identity
+        ("1.2.3.4") 的请求列在 position 21，长 identity
+        ("madeinchina:1.2.3.4") 在 position 25 → 不相等 → 断言失败。
+        """
+        ident_long = "madeinchina:1.2.3.4"
+        ident_short = "1.2.3.4"
+        self._seed_ip_stats(ident_long)
+        self._seed_ip_stats(ident_short)
+        report = self.db.format_tmd_report()
+        # 提取两条数据行，计算「请求」列（第一个数字）的起始位置
+        positions = {}
+        for ident in (ident_long, ident_short):
+            self.assertIn(ident, report,
+                          f"期望报告中包含 identity={ident}")
+            line = [l for l in report.split("\n") if ident in l][0]
+            # identity 在行中的位置
+            idx = line.index(ident)
+            # identity 之后第一个数字的位置
+            after = line[idx + len(ident):]
+            digit_pos = idx + len(ident) + len(after) - len(after.lstrip())
+            positions[ident] = digit_pos
+        # 修正后：两行的请求列应起始于同一列
+        self.assertEqual(
+            positions[ident_long], positions[ident_short],
+            f"不同长度 identity 的请求列应对齐，实际 "
+            f"{ident_short}={positions[ident_short]}, "
+            f"{ident_long}={positions[ident_long]}")
+
+
 if __name__ == "__main__":
     unittest.main()
diff --git a/fetcher/tests/test_session_helpers.py b/fetcher/tests/test_session_helpers.py
new file mode 100644
index 0000000..b2d2344
--- /dev/null
+++ b/fetcher/tests/test_session_helpers.py
@@ -0,0 +1,53 @@
+# -*- coding: utf-8 -*-
+"""bare_identity / is_direct 辅助函数单测（TDD RED→GREEN）。"""
+
+import unittest
+
+
+# 函数尚未实现，导入会失败——这是预期的 RED
+class BareIdentityTest(unittest.TestCase):
+    def test_strips_site_prefix(self):
+        """带站点前缀的 IP：剥掉前缀返回裸 IP。"""
+        from fetcher.core.session import bare_identity
+        self.assertEqual(bare_identity("1688:1.2.3.4"), "1.2.3.4")
+
+    def test_strips_prefix_for_direct(self):
+        """带站点前缀的 direct：剥掉前缀返回 direct。"""
+        from fetcher.core.session import bare_identity
+        self.assertEqual(bare_identity("madeinchina:direct"), "direct")
+
+    def test_passthrough_bare_ip(self):
+        """无前缀 IP：原样返回（兼容旧键）。"""
+        from fetcher.core.session import bare_identity
+        self.assertEqual(bare_identity("1.2.3.4"), "1.2.3.4")
+
+    def test_passthrough_direct(self):
+        """无前缀 direct：原样返回（兼容旧键）。"""
+        from fetcher.core.session import bare_identity
+        self.assertEqual(bare_identity("direct"), "direct")
+
+
+class IsDirectTest(unittest.TestCase):
+    def test_bare_direct_is_direct(self):
+        """无前缀 direct 判定为直连。"""
+        from fetcher.core.session import is_direct
+        self.assertTrue(is_direct("direct"))
+
+    def test_prefixed_direct_is_direct(self):
+        """带站点前缀的 direct 也判定为直连。"""
+        from fetcher.core.session import is_direct
+        self.assertTrue(is_direct("1688:direct"))
+
+    def test_ip_is_not_direct(self):
+        """裸 IP 不是直连。"""
+        from fetcher.core.session import is_direct
+        self.assertFalse(is_direct("1.2.3.4"))
+
+    def test_prefixed_ip_is_not_direct(self):
+        """带站点前缀的 IP 不是直连。"""
+        from fetcher.core.session import is_direct
+        self.assertFalse(is_direct("1688:1.2.3.4"))
+
+
+if __name__ == "__main__":
+    unittest.main()
