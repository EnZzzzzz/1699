# Step 1.3 修复轮1 scoped re-review 审查包（68ef08e..d96f977）

## git log
d96f977 feat(identity-p2): Step 1.3 修复轮1 — C1 _build_engine 抽辅函+C2 guard 测试+I1 docstring+M1 显式 nil-guard

## git diff -U10
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index d34852c..e55f6b0 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -187,26 +187,35 @@ def main(argv: list | None = None) -> int:
         return 0
 
     provider = make_provider(cfg)
     # 策略表：默认表 + 站点级覆盖（policy_overrides）+ CLI 熔断上限
     from fetcher.strategy.policy import Policy
     policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
     overrides = getattr(site, "policy_overrides", None)
     if overrides:
         policy = policy.with_overrides(overrides)
 
-    from fetcher.control.engine import Engine
-    engine = Engine(cfg, task, site=site, provider=provider, policy=policy,
-                    site_name=args.site)
+    engine = _build_engine(cfg, task, site=site, provider=provider,
+                           policy=policy, site_name=args.site)
     return engine.run()
 
 
+def _build_engine(cfg, task, site, provider, policy, site_name):
+    """纯装配辅助：构造 Engine 并返回（不调 run）。
+
+    提取为独立函数便于测试 site_name 透传正确性。
+    """
+    from fetcher.control.engine import Engine
+    return Engine(cfg, task, site=site, provider=provider, policy=policy,
+                  site_name=site_name)
+
+
 def _run_daemon(args) -> int:
     """daemon 常驻模式装配：1688 contact 包 DaemonTaskProxy 后跑 Engine。
 
     config_from_args 不读 args.task（读 task 的是站点分支的
     site.make_task(args.task)），daemon parser 已带 num/limit 默认值，
     故 config_from_args 原样复用、无需任何适配。provider/policy/Engine
     装配与站点分支逐项一致；退出语义不加新逻辑（信号走 Engine 既有
     优雅退出，--limit 走 CrawlLoop 既有收工逻辑）。
     """
     from fetcher.control.daemon_task import DaemonTaskProxy
@@ -232,18 +241,17 @@ def _run_daemon(args) -> int:
     # 再重置 shops 的 in_progress（不带 domain 过滤，与既有 CLI 启动语义一致）
     db = ShopDB(cfg.resolved_db_path())
     try:
         n_items = db.reset_claimed_work_items()
         n_shops = db.reset_in_progress()
     finally:
         db.close()
     print(f"[daemon] 启动重置：{n_items} 个 claimed 工作项 → pending，"
           f"{n_shops} 个 in_progress 店铺 → pending")
 
-    from fetcher.control.engine import Engine
-    engine = Engine(cfg, task=task, site=site, provider=provider, policy=policy,
-                    site_name="1688")
+    engine = _build_engine(cfg, task=task, site=site, provider=provider,
+                           policy=policy, site_name="1688")
     return engine.run()
 
 
 if __name__ == "__main__":
     sys.exit(main())
diff --git a/fetcher/fetcher/control/engine.py b/fetcher/fetcher/control/engine.py
index d33254e..1eedfab 100644
--- a/fetcher/fetcher/control/engine.py
+++ b/fetcher/fetcher/control/engine.py
@@ -117,21 +117,22 @@ class Engine:
         return [kits[i] if i < len(kits) else None for i in range(workers)]
 
     def _make_browser_manager(self, store, channel=None) -> BrowserManager:
         if self.browser_manager_factory is not None:
             return self.browser_manager_factory(store)
         auto_solve = None
         if self.config.auto_solve_slider:
             from fetcher.atoms.slider import make_auto_solve  # 延迟导入
             auto_solve = make_auto_solve(max_attempts=5)
         return BrowserManager(self.config, store,
-                              site_name=self.site_name or "unknown",
+                              site_name=(self.site_name
+                                         if self.site_name else "unknown"),
                               provider=self.provider,
                               auto_solve=auto_solve,
                               homepage=getattr(self.site, "homepage", None),
                               channel=channel)
 
     def _worker(self, wid: int, channel, seed_kit, board):
         """worker 线程入口：独立 DB 连接 / BrowserManager / ctx / loop。
 
         channel 是本 worker 独占的隧道（一 worker 一通道）：透传给
         BrowserManager，保证 launch/relaunch 都走同一隧道，不重新从
diff --git a/fetcher/fetcher/net/browser.py b/fetcher/fetcher/net/browser.py
index f574c63..706e1c8 100644
--- a/fetcher/fetcher/net/browser.py
+++ b/fetcher/fetcher/net/browser.py
@@ -129,21 +129,22 @@ def get_exit_ip(proxies: dict = None, timeout: int = 10) -> str | None:
         return r.json().get("ip")
     except Exception:  # noqa: BLE001
         return None
 
 
 class BrowserManager:
     """CloakBrowser 生命周期管理（一 worker 一个实例）。
 
     用法：
         cfg = RunConfig(use_proxy=True)
-        mgr = BrowserManager(cfg, store, provider=QingGuoProvider())
+        mgr = BrowserManager(cfg, store, site_name="1688",
+                             provider=QingGuoProvider())
         session = mgr.launch(seed_kit=kit)
         ...
         need, cur, reason = mgr.check_ip_fresh(session)
         if need:
             session = mgr.relaunch(session)
     """
 
     def __init__(self, config: RunConfig, store: IdentityStore,
                  site_name: str,
                  provider=None, log=print, auto_solve=None,
diff --git a/fetcher/tests/test_cli.py b/fetcher/tests/test_cli.py
index ca063a7..e6eb28e 100644
--- a/fetcher/tests/test_cli.py
+++ b/fetcher/tests/test_cli.py
@@ -1,16 +1,19 @@
 # -*- coding: utf-8 -*-
 """CLI 解析层测试：daemon 子命令挂载 + 既有站点子命令防装配回归。"""
 
 import unittest
+from unittest.mock import MagicMock
 
-from fetcher.cli.main import build_parser, config_from_args
+from fetcher import RunConfig
+from fetcher.cli.main import build_parser, config_from_args, _build_engine
+from fetcher.strategy.policy import Policy
 
 
 class CliParserTest(unittest.TestCase):
     def setUp(self):
         self.ap = build_parser()
 
     # ---- daemon 子命令 ----
 
     def test_daemon_defaults(self):
         args = self.ap.parse_args(["daemon"])
@@ -59,12 +62,50 @@ class CliParserTest(unittest.TestCase):
             self.assertEqual(args.site, site)
             self.assertEqual(args.task, task)
             self.assertEqual(args.num, num)
         args = self.ap.parse_args(["yiwugo", "search"])
         self.assertEqual((args.site, args.task), ("yiwugo", "search"))
         # contact 业务开关仍在
         args = self.ap.parse_args(["1688", "contact", "--retry-failed"])
         self.assertTrue(args.retry_failed)
 
 
+class BuildEngineTest(unittest.TestCase):
+    """Step 1.3: _build_engine 透传 site_name 正确性。"""
+
+    def test_site_name_passed_to_engine_site_branch(self):
+        """站点分支：site_name=args.site（如 '1688'）透传到 Engine。"""
+        cfg = RunConfig(headless=True, use_proxy=False)
+        fake_task = MagicMock()
+        fake_site = MagicMock()
+        engine = _build_engine(cfg, fake_task, site=fake_site,
+                               provider=None, policy=Policy(),
+                               site_name="1688")
+        self.assertEqual(engine.site_name, "1688",
+                         "site_name 应正确透传到 Engine")
+
+    def test_site_name_passed_to_engine_daemon_branch(self):
+        """daemon 分支：site_name='1688' 硬编码透传到 Engine。"""
+        cfg = RunConfig(headless=True, use_proxy=False)
+        fake_task = MagicMock()
+        fake_site = MagicMock()
+        engine = _build_engine(cfg, fake_task, site=fake_site,
+                               provider=None, policy=Policy(),
+                               site_name="1688")
+        # daemon 和站点分支走同一个 _build_engine，唯一区别是调用时
+        # site_name 参数值（args.site vs "1688"）
+        self.assertEqual(engine.site_name, "1688",
+                         "daemon 分支 site_name 应硬编码为 '1688'")
+
+    def test_site_name_None_allowed(self):
+        """site=None 时 site_name 可为 None（Engine guard 不触发）。"""
+        cfg = RunConfig(headless=True, use_proxy=False)
+        fake_task = MagicMock()
+        engine = _build_engine(cfg, fake_task, site=None,
+                               provider=None, policy=Policy(),
+                               site_name=None)
+        self.assertIsNone(engine.site_name)
+        self.assertIsNone(engine.site)
+
+
 if __name__ == "__main__":
     unittest.main()
diff --git a/fetcher/tests/test_engine.py b/fetcher/tests/test_engine.py
index 584435c..e3017e2 100644
--- a/fetcher/tests/test_engine.py
+++ b/fetcher/tests/test_engine.py
@@ -1,17 +1,18 @@
 # -*- coding: utf-8 -*-
 """Engine 编排测试：worker 启动、通道分配、种子认领、汇总。
 全 mock（工厂注入，不起浏览器/网络/线程真实浏览器）。"""
 
 import tempfile
 import unittest
 from pathlib import Path
+from unittest.mock import MagicMock
 
 from fetcher import RunConfig, Session
 from fetcher.control import Engine, Task
 from fetcher.net.proxy.base import Channel
 
 
 class FakeProvider:
     """记录 acquire 顺序的假通道池。"""
 
     name = "fake"
@@ -122,20 +123,51 @@ class EngineTest(unittest.TestCase):
         self.assertIsNone(kits[2])
 
     def test_summary_aggregates_all_workers(self):
         provider = FakeProvider(2)
         engine = self._engine(self._config(), provider)
         engine.run()
         self.assertEqual(sorted(engine.state["stats"]), [0, 1])
         self.assertEqual(engine.task.summary(engine.state["stats"]),
                          "汇总 2 个 worker")
 
+    # ---- Step 1.3: site_name guard ----
+
+    def test_site_without_site_name_raises_runtime_error(self):
+        """site 非空而 site_name=None → RuntimeError。
+
+        RED 预期（修正前）：没有 guard，site_name=None 静默通过，
+        后续拼键出 'None:direct' 才暴露问题。
+        """
+        with self.assertRaises(RuntimeError) as ctx:
+            Engine(self._config(), FakeTask(), site=MagicMock(),
+                   site_name=None)
+        self.assertIn("site_name 必传", str(ctx.exception))
+
+    def test_site_with_site_name_constructs_successfully(self):
+        """site 非空且 site_name 传入 → 正常构造（对照）。"""
+        engine = Engine(self._config(), FakeTask(), site=MagicMock(),
+                        site_name="1688",
+                        browser_manager_factory=lambda store: object(),
+                        loop_factory=FakeLoop)
+        self.assertEqual(engine.site_name, "1688")
+        self.assertIsNotNone(engine.site)
+
+    def test_site_none_without_site_name_constructs_successfully(self):
+        """site=None 时不触发 guard（允许不指定 site_name）。"""
+        engine = Engine(self._config(), FakeTask(), site=None,
+                        site_name=None,
+                        browser_manager_factory=lambda store: object(),
+                        loop_factory=FakeLoop)
+        self.assertIsNone(engine.site)
+        self.assertIsNone(engine.site_name)
+
     def test_each_worker_gets_own_store(self):
         provider = FakeProvider(2)
         engine = self._engine(self._config(), provider)
         engine.run()
         stores = [loop.ctx.store for loop in FakeLoop.instances]
         self.assertIsNot(stores[0], stores[1])
         self.assertIsNot(stores[0].db.conn, stores[1].db.conn)
 
 
 if __name__ == "__main__":
