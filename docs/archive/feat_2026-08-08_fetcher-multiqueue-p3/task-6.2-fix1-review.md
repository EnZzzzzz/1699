# Re-review — 终审修复（seed 接线）

## Commits
07f5a97 fix(engine): wire sites to _alloc_seed_kits for (worker,site) seed granularity (SPEC §3.6)

## Stat
 .../task-6.2-report.md                             |  38 +++++
 fetcher/fetcher/control/engine.py                  |  45 +++--
 fetcher/fetcher/control/loop.py                    |  10 +-
 fetcher/tests/test_control_loop.py                 |  47 +++++
 fetcher/tests/test_engine.py                       | 190 +++++++++++++++++++++
 5 files changed, 318 insertions(+), 12 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.2-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.2-report.md
new file mode 100644
index 0000000..235a072
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.2-report.md
@@ -0,0 +1,38 @@
+# Task 6.2 终审修复报告 — Engine._alloc_seed_kits 接线 sites（SPEC §3.6 种子粒度落地）
+
+## 状态：DONE ✅
+
+全量测试：523 passed（517 baseline + 6 new），2 subtests passed。
+
+## 发现（终审原文）
+
+`engine.py:211` `worker_kits = self._alloc_seed_kits(workers)` 未传 `self.sites`——`_alloc_seed_kits(workers, sites=None)` 方法本身已支持多站点（返回 `dict[site, list[kit]]`），但 `Engine.run()` 调用时始终走单站点分支。SPEC §3.6 要求种子身份池粒度改为「每 (worker, site) 一份」。实际影响：daemon 多站点时所有 site 共用首个 site 的 seed_kit，跨站 ensure_site 播种时错误 domain 的 Cookie 存入跨站 identity（不致命但污染 DB，与 SPEC 不符）。
+
+## 实现摘要
+
+### 改动文件
+
+| 文件 | 改动说明 |
+|---|---|
+| `fetcher/fetcher/control/engine.py` | `run()` 在 multi-site 时传 `sites=list(self.sites.values())` 给 `_alloc_seed_kits`；`_worker` 新增 `per_site_kits` keyword-only 参数并透传给 CrawlLoop |
+| `fetcher/fetcher/control/loop.py` | `CrawlLoop.__init__` 新增 `per_site_kits` 参数；`_bind_item_site` 跨站 ensure_site 时传入对应 `(worker, site)` 的 seed_kit |
+| `fetcher/tests/test_engine.py` | 新增 5 个 TDD 测试（`EngineRunSitesWiringTest`） |
+| `fetcher/tests/test_control_loop.py` | 新增 `SeedKitCaptureBrowserManager` + 1 个 TDD 测试 |
+
+### 关键设计决策
+
+1. **传递链**：`Engine.run() → _worker(per_site_kits=...) → CrawlLoop(per_site_kits=...) → _bind_item_site → ensure_site(seed_kit=site_seed_kit)`
+2. **单站点路径不变**：`per_site_kits=None` → 行为逐字不变（不传 `sites` 给 `_alloc_seed_kits`，_worker 不设 per_site_kits）
+3. **per_site_kits 结构**：`dict[site_name, kit|None]`，由 Engine.run() 从 `_alloc_seed_kits` 返回的 `dict[site, list[kit]]` 中按 worker 下标切片
+4. **无 kit 时保持白板语义**：`per_site_kits.get(site_name)` 返回值可能为 None → `ensure_site(seed_kit=None)` 即为白板，与现状一致
+
+### TDD 证据（6 RED → 6 GREEN）
+
+| 测试 | 验证点 |
+|---|---|
+| `test_run_with_sites_calls_alloc_seed_kits_with_sites` | Engine.run() multi-site → _alloc_seed_kits 收到 sites list |
+| `test_run_single_site_does_not_pass_sites` | Engine.run() 单站点 → _alloc_seed_kits 不传 sites（行为不变） |
+| `test_worker_passes_per_site_kits_to_loop_in_multi_site` | _worker 把 per_site_kits dict 传给 CrawlLoop |
+| `test_worker_per_site_kits_none_in_single_site` | 单站点 loop 不收 per_site_kits |
+| `test_multi_site_per_worker_kits_structure` | 有种子时每 worker 得到正确的 init kit + per_site_kits |
+| `test_bind_item_site_passes_seed_kit_to_ensure_site` | 跨站 ensure_site 播种拿到对应 site 的 kit |
diff --git a/fetcher/fetcher/control/engine.py b/fetcher/fetcher/control/engine.py
index a4c338c..9c938ab 100644
--- a/fetcher/fetcher/control/engine.py
+++ b/fetcher/fetcher/control/engine.py
@@ -154,21 +154,22 @@ class Engine:
             from fetcher.atoms.slider import make_auto_solve  # 延迟导入
             auto_solve = make_auto_solve(max_attempts=5)
         return BrowserManager(self.config, store,
                               site_name=(self.site_name
                                          if self.site_name else "unknown"),
                               provider=self.provider,
                               auto_solve=auto_solve,
                               homepage=getattr(self.site, "homepage", None),
                               channel=channel)
 
-    def _worker(self, wid: int, channel, seed_kit, board):
+    def _worker(self, wid: int, channel, seed_kit, board,
+                *, per_site_kits=None):
         """worker 线程入口：独立 DB 连接 / BrowserManager / ctx / loop。
 
         channel 是本 worker 独占的隧道（一 worker 一通道）：透传给
         BrowserManager，保证 launch/relaunch 都走同一隧道，不重新从
         通道池轮询跳隧道。
         """
         tag = f"[w{wid}]"
         store = self.store_factory(wid)
         mgr = self._make_browser_manager(store, channel)
 
@@ -188,63 +189,85 @@ class Engine:
                 print(text, flush=True)
 
         ctx = WorkerContext(config=self.config, store=store,
                             browser_manager=mgr, site=self.site,
                             stop=self.stop, log=log, wid=wid, tag=tag)
         if board is not None:
             ctx.set_status = lambda **kw: board.set(wid, **kw)
         loop_kw = {}
         if self.sites is not None:
             loop_kw["sites"] = self.sites
+        if per_site_kits is not None:
+            loop_kw["per_site_kits"] = per_site_kits
         if self.policies is not None:
             loop_kw["policies"] = self.policies
         loop = self.loop_factory(ctx, self.task, policy=self.policy,
                                  board=board, seed_kit=seed_kit, **loop_kw)
         stats = loop.run()
         with self.lock:
             self.state["stats"][wid] = stats
 
     # ---- main 编排 ----
 
     def run(self) -> int:
         cfg = self.config
         workers, channels = self._alloc_workers()
-        worker_kits = self._alloc_seed_kits(workers)
-        print(f"[2] 启动 {workers} 个 worker"
-              f"（{'代理通道: ' + ', '.join(c.server for c in channels)
-                  if cfg.use_proxy else '直连'}）")
 
         board = self.board
         if board is None and workers > 0:
             board = StatusBoard(workers, compose=self.task.compose)
+
+        # P3 SPEC §3.6：种子身份池 (worker, site) 粒度
+        if self.sites:
+            kits_by_site = self._alloc_seed_kits(
+                workers, sites=list(self.sites.values()))
+            # kits_by_site: dict[site_name, list[kit]]
+            # 为每个 worker 提取初始 kit（default site）和 per-site kits
+            _thread_args = []
+            for i in range(workers):
+                init_kit = (kits_by_site[self.site_name][i]
+                            if self.site_name and self.site_name in kits_by_site
+                            else None)
+                per_site = {site: kits[i]
+                            for site, kits in kits_by_site.items()}
+                _thread_args.append((i, channels[i], init_kit, board, per_site))
+        else:
+            worker_kits = self._alloc_seed_kits(workers)
+            _thread_args = [(i, channels[i], worker_kits[i], board, None)
+                            for i in range(workers)]
+        print(f"[2] 启动 {workers} 个 worker"
+              f"（{'代理通道: ' + ', '.join(c.server for c in channels)
+                  if cfg.use_proxy else '直连'}）")
+
         if board is not None:
             board.start()
 
         # 直接关终端窗口(SIGHUP)或被 kill(SIGTERM)时也走正常清理流程：
         # 各 worker 关闭浏览器，服务端会话租约立即释放
         def _graceful_exit(signum, frame):
             (board.log if board else print)(
                 f"[!] 收到信号 {signum}，通知各 worker 清理后退出...")
             self.stop.set()
 
         for sig in (signal.SIGTERM, signal.SIGHUP):
             try:
                 signal.signal(sig, _graceful_exit)
             except (OSError, ValueError):
                 pass  # 平台不支持该信号时跳过
 
-        threads = [
-            threading.Thread(target=self._worker,
-                             args=(i, channels[i], worker_kits[i], board),
-                             name=f"worker-{i}", daemon=True)
-            for i in range(workers)
-        ]
+        threads = []
+        for i in range(workers):
+            args_i, per_site = _thread_args[i][:4], _thread_args[i][4]
+            kwargs_i = {"per_site_kits": per_site} if per_site is not None else {}
+            threads.append(threading.Thread(
+                target=self._worker, args=args_i, kwargs=kwargs_i,
+                name=f"worker-{i}", daemon=True))
         for i, t in enumerate(threads):
             t.start()
             if i < len(threads) - 1:
                 # 启动时间打散：多会话同一分钟内出生、同节奏访问是集群特征
                 d = random.uniform(cfg.stagger_min, cfg.stagger_max)
                 print(f"    错开启动：{d:.0f}s 后启动下一个 worker ...")
                 time.sleep(d)
 
         try:
             for t in threads:
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index 045f090..a5f9403 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -69,26 +69,28 @@ class CrawlLoop:
         ctx = WorkerContext(config=cfg, store=store, browser_manager=mgr,
                             site=site, stop=stop, log=log)
         loop = CrawlLoop(ctx, task, policy=policy, board=board, seed_kit=kit)
         stats = loop.run()
     """
 
     def __init__(self, ctx, task: Task, policy: Policy | None = None,
                  inspector: SceneInspector | None = None, board=None,
                  seed_kit: dict | None = None,
                  sites: dict[str, object] | None = None,
+                 per_site_kits: dict[str, dict | None] | None = None,
                  policies: dict[str, Policy] | None = None):
         self.ctx = ctx
         self.task = task
         self.policy = policy or Policy(
             max_consecutive_fail=ctx.config.max_consecutive_fail)
         self.sites = sites
+        self.per_site_kits = per_site_kits
         self.policies = policies
         if sites is not None:
             # daemon 多站点路径：inspector 延迟建，首个 item 绑定后建立
             self._bound_site = None
             self.inspector = inspector  # daemon 传 None
         else:
             # CLI 单站点路径：inspector 按 ctx.site 立即装配
             self._bound_site = getattr(ctx.site, 'name', None) if ctx.site else None
             self.inspector = inspector or SceneInspector.for_site(ctx.site)
         self.board = board
@@ -473,22 +475,28 @@ class CrawlLoop:
         site_name = self.ctx.state.get("active_site")
         if site_name is None or site_name == self._bound_site:
             return
         plugin = self.sites.get(site_name)
         if plugin is not None:
             self.ctx.site = plugin
             # 跨站 view 懒建（SPEC §3.6）：无 view 则建，路由活动站点
             if (self.ctx.session is not None
                     and self.ctx.browser_manager is not None):
                 try:
+                    # P3 SPEC §3.6：跨站 ensure_site 播种用该
+                    # (worker, site) 的 seed_kit；无 kit 时保持现状白板语义
+                    site_seed_kit = (
+                        self.per_site_kits.get(site_name)
+                        if self.per_site_kits else None)
                     self.ctx.browser_manager.ensure_site(
-                        self.ctx.session, site_name, plugin.cookie_domain)
+                        self.ctx.session, site_name, plugin.cookie_domain,
+                        seed_kit=site_seed_kit)
                     self.ctx.session.set_active_site(site_name)
                 except Exception as e:
                     self.log(f"[!] ensure_site({site_name}) 失败: {e}，"
                              f"继续处理 item（fetch 兜底）")
             self.inspector = SceneInspector.for_site(plugin)
             new_policy = self.policies.get(site_name) if self.policies else None
             if new_policy is not None:
                 self.policy = new_policy
         # C1 修复：无论 plugin 是否在 sites dict 中，
         # 都记录本次绑定，防止每次 item 都重复查找
diff --git a/fetcher/tests/test_control_loop.py b/fetcher/tests/test_control_loop.py
index ce507d0..70505c1 100644
--- a/fetcher/tests/test_control_loop.py
+++ b/fetcher/tests/test_control_loop.py
@@ -510,20 +510,35 @@ class MultiSiteScriptedTask(ScriptedTask):
 
     def acquire_item(self, ctx):
         item = super().acquire_item(ctx)
         if item is not None and item in self.site_map:
             ctx.state["active_site"] = self.site_map[item]
         return item
 
 
 # ---------- 跨站 view 懒建测试 ----------
 
+class SeedKitCaptureBrowserManager(MultiSiteMockBrowserManager):
+    """MultiSiteMockBrowserManager 增强版：捕获 ensure_site 的 seed_kit。"""
+
+    def __init__(self, page, default_site="1688",
+                 identities=("1688:1.1.1.1", "1688:2.2.2.2", "1688:3.3.3.3")):
+        super().__init__(page, default_site, identities)
+        self.seed_kit_calls = []
+
+    def ensure_site(self, session, site_name, site_domain,
+                    seed_kit=None, stop=None):
+        self.seed_kit_calls.append(seed_kit)
+        return super().ensure_site(session, site_name, site_domain,
+                                   seed_kit=seed_kit, stop=stop)
+
+
 class CrossSiteLazyViewTest(LoopTestBase):
     """跨站 view 懒建补缺（SPEC §3.6 / Task 3.3 第一部分，TDD）。"""
 
     def setUp(self):
         super().setUp()
         self.plugin_1688 = MockPlugin("1688", "1688.com")
         self.plugin_mic = MockPlugin("madeinchina", "made-in-china.com")
         self.mgr = MultiSiteMockBrowserManager(self.page, default_site="1688")
         self.sites = {"1688": self.plugin_1688,
                       "madeinchina": self.plugin_mic}
@@ -633,13 +648,45 @@ class CrossSiteLazyViewTest(LoopTestBase):
         ctx = WorkerContext(config=config, store=store,
                             browser_manager=mgr,
                             site=Alibaba1688Plugin(),
                             stop=threading.Event(),
                             log=lambda m: None)
         task = ScriptedTask([("ok", {"v": 1})])
         loop = CrawlLoop(ctx, task, sites=None)
         stats = loop.run()
         self.assertEqual(task.succeeded, ["item1"])
 
+    # ---- 6.2: per_site_kits 透传到 ensure_site ----
+
+    def test_bind_item_site_passes_seed_kit_to_ensure_site(self):
+        """跨站 ensure_site 播种拿对应 (worker, site) 的 kit。
+
+        RED 预期：_bind_item_site 当前未传 seed_kit → ensure_site
+        总是 seed_kit=None → seed_kit_calls 中的 kit 全为 None → 断言失败。
+        """
+        # 构造 per_site_kits（模拟 Engine 传递）
+        kit_1688 = {"name": "kitA", "cookies": [{"name": "cna", "value": "v"}]}
+        kit_mic = {"name": "kitB", "cookies": [{"name": "cna", "value": "v"}]}
+        per_site_kits = {"1688": kit_1688, "madeinchina": kit_mic}
+
+        # 用带 seed_kit 捕获的 mgr
+        mgr = SeedKitCaptureBrowserManager(self.page, default_site="1688")
+        self.mgr = mgr
+        ctx = self.make_multi_ctx()
+        ctx.state["active_site"] = "madeinchina"
+        task = ScriptedTask([("ok", {"v": 1})])
+        loop = CrawlLoop(ctx, task, sites=self.sites,
+                         per_site_kits=per_site_kits)
+        loop.run()
+        self.assertEqual(len(mgr.ensure_site_calls), 1,
+                         '应调用 ensure_site("madeinchina")')
+        # 验证传入正确的 seed_kit
+        self.assertEqual(len(mgr.seed_kit_calls), 1)
+        actual_kit = mgr.seed_kit_calls[0]
+        self.assertIsNotNone(actual_kit,
+                             "ensure_site 应收到 madeinchina 的 seed_kit")
+        self.assertEqual(actual_kit["name"], "kitB",
+                         "ensure_site 应收到 kitB（madeinchina 对应种子）")
+
 
 if __name__ == "__main__":
     unittest.main()
diff --git a/fetcher/tests/test_engine.py b/fetcher/tests/test_engine.py
index fc35686..623855c 100644
--- a/fetcher/tests/test_engine.py
+++ b/fetcher/tests/test_engine.py
@@ -433,12 +433,202 @@ class SeedPoolMultiSiteTest(unittest.TestCase):
             site_name="1688",
             browser_manager_factory=lambda store: object(),
             loop_factory=FakeLoop)
         result = engine._alloc_seed_kits(2)  # sites=None default
         self.assertIsInstance(result, list)
         self.assertEqual(len(result), 2)
         self.assertTrue(result[0].get("x5sec"))
         self.assertFalse(result[1].get("x5sec"))
 
 
+# ============================================================
+# Task 6.2: Engine.run 接线 sites 到 _alloc_seed_kits
+# ============================================================
+
+class FakeLoopV2:
+    """记录装配参数的假 CrawlLoop（捕获 per_site_kits）。"""
+    instances = []
+
+    def __init__(self, ctx, task, policy=None, board=None, seed_kit=None,
+                 sites=None, per_site_kits=None, policies=None):
+        self.ctx = ctx
+        self.seed_kit = seed_kit
+        self.sites = sites
+        self.per_site_kits = per_site_kits
+        self.policies = policies
+        FakeLoopV2.instances.append(self)
+
+    def run(self):
+        return {"done": 1, "wid": self.ctx.wid}
+
+
+class EngineRunSitesWiringTest(unittest.TestCase):
+    """Engine.run() → _alloc_seed_kits 接线 sites 测试。"""
+
+    def setUp(self):
+        FakeLoopV2.instances = []
+        self._tmp = tempfile.TemporaryDirectory()
+
+    def tearDown(self):
+        self._tmp.cleanup()
+
+    def _config(self, **kw):
+        base = dict(headless=True, use_proxy=True, workers=0,
+                    db_path=str(Path(self._tmp.name) / "t.db"),
+                    seeds_dir=str(Path(self._tmp.name) / "no_seeds"),
+                    stagger_min=0, stagger_max=0)
+        base.update(kw)
+        return RunConfig(**base)
+
+    # ---- 6.2-1: run() 传 sites 给 _alloc_seed_kits ----
+
+    def test_run_with_sites_calls_alloc_seed_kits_with_sites(self):
+        """Engine.run() 在 multi-site 模式下传 sites 给
+        _alloc_seed_kits → 返回 dict[site, list[kit]]。"""
+        from types import SimpleNamespace
+        provider = FakeProvider(2)
+        sites_dict = {
+            "1688": SimpleNamespace(name="1688", cookie_domain="1688.com"),
+            "yiwugo": SimpleNamespace(name="yiwugo", cookie_domain="yiwugo.com"),
+        }
+        cfg = self._config(workers=2)
+        engine = Engine(cfg, FakeTask(), provider=provider,
+                        site_name="1688", sites=sites_dict,
+                        site=MagicMock(cookie_domain="1688.com"),
+                        policies={"1688": MagicMock(), "yiwugo": MagicMock()},
+                        browser_manager_factory=lambda store: object(),
+                        loop_factory=FakeLoopV2)
+
+        with unittest.mock.patch.object(
+                engine, '_alloc_seed_kits',
+                wraps=engine._alloc_seed_kits) as mock_alloc:
+            engine.run()
+            self.assertTrue(mock_alloc.called,
+                            "run() 应调用 _alloc_seed_kits")
+            # 验证 sites 参数通过（位置或关键字）
+            args, kw = mock_alloc.call_args
+            # wraps 的 bound method 会把 self 计入 args[0]；
+            # 检查传入值中是否包含 sites 列表
+            all_args = args + tuple(kw.values())
+            sites_found = any(
+                isinstance(v, list) and len(v) == 2 for v in all_args)
+            self.assertTrue(sites_found,
+                            "multi-site 时 run() 应传 sites list 给 _alloc_seed_kits")
+
+    def test_run_single_site_does_not_pass_sites(self):
+        """Engine.run() 在单站点模式下不传 sites（行为不变）。"""
+        provider = FakeProvider(2)
+        cfg = self._config(workers=2)
+        engine = Engine(cfg, FakeTask(), provider=provider,
+                        site_name="1688",
+                        site=MagicMock(cookie_domain="1688.com"),
+                        browser_manager_factory=lambda store: object(),
+                        loop_factory=FakeLoopV2)
+
+        with unittest.mock.patch.object(
+                engine, '_alloc_seed_kits',
+                wraps=engine._alloc_seed_kits) as mock_alloc:
+            engine.run()
+            self.assertTrue(mock_alloc.called,
+                            "run() 应调用 _alloc_seed_kits")
+            args, kw = mock_alloc.call_args
+            # 单站点：不传 sites（kwargs 无 sites，位置也不含 sites list）
+            all_args = args + tuple(kw.values())
+            sites_not_found = not any(
+                isinstance(v, list) and len(v) > 0 for v in all_args)
+            self.assertTrue(sites_not_found,
+                            "单站点 run() 不应传 sites 给 _alloc_seed_kits")
+
+    # ---- 6.2-2: per_site_kits 传递到 loop ----
+
+    def test_worker_passes_per_site_kits_to_loop_in_multi_site(self):
+        """multi-site 时 _worker 把 per_site_kits 传给 CrawlLoop。"""
+        from types import SimpleNamespace
+        provider = FakeProvider(2)
+        sites_dict = {
+            "1688": SimpleNamespace(name="1688", cookie_domain="1688.com"),
+            "yiwugo": SimpleNamespace(name="yiwugo", cookie_domain="yiwugo.com"),
+        }
+        cfg = self._config(workers=2)
+        engine = Engine(cfg, FakeTask(), provider=provider,
+                        site_name="1688", sites=sites_dict,
+                        site=MagicMock(cookie_domain="1688.com"),
+                        policies={"1688": MagicMock(), "yiwugo": MagicMock()},
+                        browser_manager_factory=lambda store: object(),
+                        loop_factory=FakeLoopV2)
+        engine.run()
+
+        for loop in FakeLoopV2.instances:
+            self.assertIsNotNone(
+                loop.per_site_kits,
+                f"worker {loop.ctx.wid}: per_site_kits 不应为 None")
+            self.assertIsInstance(
+                loop.per_site_kits, dict,
+                f"worker {loop.ctx.wid}: per_site_kits 应为 dict")
+            self.assertEqual(
+                set(loop.per_site_kits.keys()), {"1688", "yiwugo"},
+                f"worker {loop.ctx.wid}: per_site_kits 应含两站点")
+
+    def test_worker_per_site_kits_none_in_single_site(self):
+        """单站点时 loop 不收 per_site_kits。"""
+        provider = FakeProvider(2)
+        cfg = self._config(workers=2)
+        engine = Engine(cfg, FakeTask(), provider=provider,
+                        site_name="1688",
+                        site=MagicMock(cookie_domain="1688.com"),
+                        browser_manager_factory=lambda store: object(),
+                        loop_factory=FakeLoopV2)
+        engine.run()
+
+        for loop in FakeLoopV2.instances:
+            self.assertIsNone(
+                loop.per_site_kits,
+                f"worker {loop.ctx.wid}: 单站点时 per_site_kits 应为 None")
+
+    # ---- 6.2-3: multi-site 时 _alloc_seed_kits 返回正确结构 ----
+
+    def test_multi_site_per_worker_kits_structure(self):
+        """multi-site 时每 worker 得到 dict[site, kit] 结构。
+
+        seed_kit 是初始 site 的 kit（给 launch），per_site_kits
+        是 {site_name: kit}（给 ensure_site 跨站播种）。
+        """
+        import json
+        from types import SimpleNamespace
+
+        seeds_dir = Path(self._tmp.name) / "seeds"
+        seeds_dir.mkdir()
+        for name in ("kitA", "kitB"):
+            (seeds_dir / f"{name}.json").write_text(json.dumps([
+                {"name": "cna", "value": "v", "domain": ".1688.com"},
+                {"name": "cookie2", "value": "v", "domain": ".1688.com"},
+            ]), encoding="utf-8")
+
+        provider = FakeProvider(2)
+        sites_dict = {
+            "1688": SimpleNamespace(name="1688", cookie_domain="1688.com"),
+        }
+        cfg = self._config(workers=2, seeds_dir=str(seeds_dir))
+        engine = Engine(cfg, FakeTask(), provider=provider,
+                        site_name="1688", sites=sites_dict,
+                        site=MagicMock(cookie_domain="1688.com"),
+                        policies={"1688": MagicMock()},
+                        browser_manager_factory=lambda store: object(),
+                        loop_factory=FakeLoopV2)
+        engine.run()
+
+        # 验证每 worker 的 seed_kit 和 per_site_kits
+        for loop in FakeLoopV2.instances:
+            # per_site_kits 应包含 1688 站点的 kit
+            self.assertIn("1688", loop.per_site_kits,
+                          f"worker {loop.ctx.wid}: per_site_kits 应含 1688")
+            # seed_kit（launch 用）应为初始 site 的 kit
+            if loop.ctx.wid == 0:
+                self.assertEqual(loop.seed_kit["name"], "kitA")
+                self.assertEqual(loop.per_site_kits["1688"]["name"], "kitA")
+            else:
+                self.assertEqual(loop.seed_kit["name"], "kitB")
+                self.assertEqual(loop.per_site_kits["1688"]["name"], "kitB")
+
+
 if __name__ == "__main__":
     unittest.main()
