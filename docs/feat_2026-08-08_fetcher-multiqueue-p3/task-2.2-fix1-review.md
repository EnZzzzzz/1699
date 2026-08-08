# Re-review Package — Step 2.2 fix round 1

## Commits
c13f564 fix(multiqueue-p3): task-2.2 fix1 — C1/I2/I3/M4/M5

## Stat
 .../task-2.2-report.md                             | 49 ++++++++++++++++++++++
 fetcher/fetcher/control/engine.py                  |  4 +-
 fetcher/fetcher/core/session.py                    | 18 ++++++++
 fetcher/fetcher/net/browser.py                     | 17 ++++----
 fetcher/tests/test_engine.py                       | 46 ++++++++++++++------
 fetcher/tests/test_needs_relaunch.py               | 12 +++---
 6 files changed, 118 insertions(+), 28 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.2-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.2-report.md
index 7a7182a..96624ae 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.2-report.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.2-report.md
@@ -80,10 +80,59 @@ cd fetcher && python -m pytest tests -q
 
 引用 Step 2.1 冒烟证据 `smoke-step2.1/smoke-fix1-raw.txt`：旧 CLI `1688 contact` 直连路径（`--workers 1`、临时库 `/tmp`、+1 席内）正常运行（launch → Cookie 装载 → warmup → 滑块过证）。本 Step 的 `sites=None` 路径返回 list 行为逐字不变，CLI 路径不受影响。无需复跑。
 
 ## 5. 自查发现
 
 - **无遗漏**：brief 列出的所有验收项均已覆盖（needs_relaunch 置位/清除/懒建消费、种子池映射与 CLI 等价、cookie_domain 过滤、seed_x5sec、relaunch 复核、冒烟等价）
 - **无越界**：未动 db.py、control/loop.py、daemon_task.py、queue_router.py、strategies.py（SwapIP 两阶段留给 P3-3）
 - **engine.run 未改动**：`_alloc_seed_kits(workers)` 调用点保持 sites=None 默认，返回 list，消费逻辑不变
 - **ensure_site 防递归**：清除 needs_relaunch 在 relaunch/launch 之前，避免 ensure_site → relaunch → launch → ensure_site 的递归触发
 - **session 引用保持**：ensure_site 触发的 relaunch 将新 session 状态迁回旧对象，调用方持有的 session 引用不变
+
+---
+
+## Fix Round 1（2026-08-08）
+
+来源：`task-2.2-fix1.md`（C1/I2/I3/M4/M5）
+
+### C1 — seed_x5sec 多站点路径 0 测试覆盖
+
+**问题**：`test_sites_nonempty_seed_x5sec` 实际调 `_alloc_seed_kits(2)` 不带 sites，走 CLI 路径，从未覆盖 sites 非空 + seed_x5sec=True 的多站点分支。
+
+**修复**：重写测试，传入两站点（1688 + yiwugo，各有独立域的种子），断言返回 `dict[site][worker]` 结构、每 site 内偶数 worker A 组（含 x5sec）、奇数 worker B 组。
+
+**测试**：`tests/test_engine.py::SeedPoolMultiSiteTest::test_sites_nonempty_seed_x5sec` — PASSED
+
+### I2 — Session 状态迁移脆弱（字段逐一拷贝）
+
+**问题**：`ensure_site` 里 relaunch 后将 new_session 的 browser/channel/req_proxies/views/seed_kit/extra 逐一拷回旧 session，未来 Session 新增字段极易遗漏。
+
+**修复**：给 `Session` 加 `copy_state_from(other: Session)` 集中迁移方法（迁移 browser / channel / req_proxies / views / seed_kit / extra / _active_site）；`ensure_site` 改为调用 `session.copy_state_from(new_session)`。
+
+**测试**：现有 `test_ensure_site_triggers_relaunch_when_needs_relaunch_set` / `test_ensure_site_relaunch_clears_all_site_flags` / `test_ensure_site_relaunch_preserves_session_object_identity` 均 PASSED（覆盖迁移后 session 对象引用不变且状态正确）。
+
+### I3 — 缺 clear_needs_relaunch(site) 精确清除 API
+
+**问题**：实现只有全清（`session.extra["needs_relaunch"] = {}`），P3-3 可能需要在进程内单独清除某 site 标记。
+
+**修复**：`BrowserManager` 加 `clear_needs_relaunch(session, site)` 方法（内调 `extra["needs_relaunch"].pop(site, None)`），与 `mark_needs_relaunch` 成对；`ensure_site` 的懒建消费保持全清（进程级 relaunch）。
+
+**测试**：`tests/test_needs_relaunch.py::MarkNeedsRelaunchTest::test_clear_needs_relaunch_removes_single_site_flag` — 置位两 site → 清除单个 → 验证该 site 清除、另一 site 保留 — PASSED
+
+### M4 — test_relaunch_complete_clears_flag 不测生产代码
+
+**问题**：旧测试只做 `session.extra["needs_relaunch"].pop(...)` 纯 dict 操作，无生产代码触达。
+
+**修复**：替换为 `test_clear_needs_relaunch_removes_single_site_flag`，调用 `mgr.clear_needs_relaunch(session, "1688")` 生产 API 并验证行为。
+
+### M5 — _alloc_seed_kits_single 参数无类型注解
+
+**修复**：补 `seeds_dir: str`、`cfg: "RunConfig"` 类型注解（与同文件其他方法一致）。
+
+### 回归验证
+
+```
+$ cd fetcher && python -m pytest tests -q
+395 passed, 2 subtests passed in 30.65s
+```
+
+0 回归，全部修复项覆盖通过。
diff --git a/fetcher/fetcher/control/engine.py b/fetcher/fetcher/control/engine.py
index 4507776..0bf6484 100644
--- a/fetcher/fetcher/control/engine.py
+++ b/fetcher/fetcher/control/engine.py
@@ -110,22 +110,22 @@ class Engine:
                 getattr(self.site, "cookie_domain", "1688.com"))
         else:
             # Daemon 多站点路径：每 (worker, site) 一份
             result = {}
             for site in sites:
                 domain = getattr(site, "cookie_domain", "1688.com")
                 result[site.name] = self._alloc_seed_kits_single(
                     workers, seeds_dir, cfg, domain)
             return result
 
-    def _alloc_seed_kits_single(self, workers: int, seeds_dir, cfg,
-                                domain: str) -> list:
+    def _alloc_seed_kits_single(self, workers: int, seeds_dir: str,
+                                cfg: "RunConfig", domain: str) -> list:
         """单站点的种子分配逻辑（CLI 与 daemon 共用核心）。"""
         kits = load_seed_kits(seeds_dir, domain=domain)
         kits_x5 = (load_seed_kits(seeds_dir, keep_x5sec=True, domain=domain)
                    if cfg.seed_x5sec else [])
         if kits:
             print(f"[seed] 种子身份池 {len(kits)} 份: "
                   f"{', '.join(k['name'] for k in kits)}")
             if workers > len(kits):
                 print(f"[!] worker 数({workers}) > 种子数({len(kits)})，"
                       f"超出部分按白板会话启动（建议种子数 ≥ worker 数）")
diff --git a/fetcher/fetcher/core/session.py b/fetcher/fetcher/core/session.py
index a9830cf..4278e61 100644
--- a/fetcher/fetcher/core/session.py
+++ b/fetcher/fetcher/core/session.py
@@ -141,20 +141,38 @@ class Session:
         确保多站共存时各站 Cookie 入各桶（与 save_from_context 同语义）。
         """
         if store is None or view.context is None:
             return
         domain_filter = view.domain or getattr(store, "domain", "")
         cookies = [c for c in view.context.cookies()
                    if domain_filter in c.get("domain", "")]
         if cookies:
             store.save(view.identity, cookies)
 
+    # ---- 状态迁移（relaunch 后迁回旧对象，保持引用不变）----
+
+    def copy_state_from(self, other: "Session") -> None:
+        """将 other Session 的运行时状态迁入本 Session（原地更新，引用不变）。
+
+        用于 relaunch 场景：relaunch 返回新 Session 对象，调用方持有的
+        旧 Session 引用通过本方法迁入新状态，避免散弹式字段逐一拷贝。
+        迁移字段：browser / channel / req_proxies / views / seed_kit /
+        extra / _active_site。
+        """
+        self.browser = other.browser
+        self.channel = other.channel
+        self.req_proxies = other.req_proxies
+        self.views = other.views
+        self.seed_kit = other.seed_kit
+        self.extra = other.extra
+        self._active_site = other._active_site
+
     # ---- 两层关闭 ----
 
     def close_site(self, site: str, store=None, log=None):
         """关闭单个站点的 view：回写该 view Cookie（按 view.domain 过滤）→
         关 context → 从 views 移除。供 P3-3 SwapIP 两阶段用。
         """
         view = self.views.get(site)
         if view is None:
             return
         # 回写 Cookie（按 view.domain 过滤）
diff --git a/fetcher/fetcher/net/browser.py b/fetcher/fetcher/net/browser.py
index 6f06a90..979d855 100644
--- a/fetcher/fetcher/net/browser.py
+++ b/fetcher/fetcher/net/browser.py
@@ -366,20 +366,28 @@ class BrowserManager:
         置位 → 当前任务继续完成 → 第二阶段在下次认领时由 ensure_site 的
         懒建路径消费（完整 relaunch）。
 
         存储位置：session.extra["needs_relaunch"]（session.extra 是现成
         状态暂存区；SPEC 写作 session.state，实现落 extra 并注释对应）。
         """
         if "needs_relaunch" not in session.extra:
             session.extra["needs_relaunch"] = {}
         session.extra["needs_relaunch"][site] = True
 
+    def clear_needs_relaunch(self, session: Session, site: str):
+        """清除单个 site 的 needs_relaunch 标记。
+
+        与 mark_needs_relaunch 成对，供 P3-3 SwapIP 两阶段在进程内
+        单独清除某 site 标记时使用。
+        """
+        session.extra.get("needs_relaunch", {}).pop(site, None)
+
     # ---- view 管理 ----
 
     def ensure_site(self, session: Session, site_name: str,
                     site_domain: str, seed_kit: dict | None = None,
                     stop: threading.Event | None = None) -> SiteView:
         """确保 session 有 site_name 的 view；无则懒建。
 
         懒建：browser.new_context(locale="zh-CN") → 按 f"{site_name}:{bare}"
         装载 Cookie（库优先；直连无库时 JSON 种子兜底；代理新 IP 播种
         seed_kit——复用 launch 的 Cookie 装载段逻辑）→ new_page →
@@ -398,28 +406,21 @@ class BrowserManager:
             # 清除全部 site 标记（relaunch 是进程级，一次即可；
             # 在 launch 前清除以避免 ensure_site → relaunch →
             # launch → ensure_site 的递归触发）
             session.extra["needs_relaunch"] = {}
             # 复用现有 relaunch 逻辑：全 view 回写 + 新进程
             new_session = self.relaunch(session, channel=session.channel,
                                         seed_kit=session.seed_kit,
                                         stop=stop)
             # 将新 session 状态迁回旧 session 对象（调用方持有旧引用，
             # 以此保证 session 对象身份不变但内部已刷新）
-            session.browser = new_session.browser
-            session.channel = new_session.channel
-            session.req_proxies = new_session.req_proxies
-            session.views = new_session.views
-            session.seed_kit = new_session.seed_kit
-            for k, v in new_session.extra.items():
-                if k != "needs_relaunch":
-                    session.extra[k] = v
+            session.copy_state_from(new_session)
             if site_name in session.views:
                 return session.views[site_name]
             # launch 未建该 site 的初始 view 时，走下面正常懒建路径
 
         cfg = self.config
         # 确定 identity
         if cfg.use_proxy:
             # F3: 边界防御——use_proxy=True 但 req_proxies 未注入不应静默直连
             if session.req_proxies is None:
                 raise ExitIPError(
diff --git a/fetcher/tests/test_engine.py b/fetcher/tests/test_engine.py
index a30b575..fc35686 100644
--- a/fetcher/tests/test_engine.py
+++ b/fetcher/tests/test_engine.py
@@ -351,50 +351,70 @@ class SeedPoolMultiSiteTest(unittest.TestCase):
             # 每个 site 调用一次
             self.assertEqual(mock_load.call_count, 2)
             # 验证 domain 参数不同
             calls = mock_load.call_args_list
             domains = {c[1].get('domain') for c in calls}
             self.assertEqual(domains, {"1688.com", "made-in-china.com"})
 
     # ---- seed_x5sec 分支 ----
 
     def test_sites_nonempty_seed_x5sec(self):
-        """seed_x5sec 实验在多站点路径下同样适用。"""
+        """seed_x5sec 实验：sites 非空 + seed_x5sec=True →
+        dict[site][worker] 结构，偶数 worker A 组（含 x5sec），
+        奇数 worker B 组对照。两站点各有独立域的种子。"""
         import json
+        from types import SimpleNamespace
         seeds = Path(self._tmp.name) / "seeds"
         seeds.mkdir()
-        for name, has_x5sec in (("kitA", True), ("kitB", False)):
+        # 1688 域种子：kitA 含 x5sec，kitB 不含
+        for name, has_x5sec, domain in (
+            ("kitA", True, ".1688.com"),
+            ("kitB", False, ".1688.com"),
+            ("kitY", True, ".yiwugo.com"),
+            ("kitZ", False, ".yiwugo.com"),
+        ):
             cookies = [
-                {"name": "cna", "value": "v", "domain": ".1688.com"},
-                {"name": "cookie2", "value": "v", "domain": ".1688.com"},
+                {"name": "cna", "value": "v", "domain": domain},
+                {"name": "cookie2", "value": "v", "domain": domain},
             ]
             if has_x5sec:
                 cookies.append({"name": "x5sec", "value": "xv",
-                                "domain": ".1688.com",
-                                "expires": 9999999999})
+                                "domain": domain, "expires": 9999999999})
             (seeds / f"{name}.json").write_text(json.dumps(cookies),
                                                 encoding="utf-8")
 
         cfg = self._config(workers=2, seeds_dir=str(seeds), seed_x5sec=True)
         engine = Engine(
             cfg, FakeTask(),
             site=MagicMock(cookie_domain="1688.com"),
             site_name="1688",
             browser_manager_factory=lambda store: object(),
             loop_factory=FakeLoop)
-        result = engine._alloc_seed_kits(2)
-        # worker 0 (偶数): x5sec 组（A 组）
-        self.assertTrue(result[0].get("x5sec"),
-                        f"偶数 worker 应为 A 组（含 x5sec），实际={result[0]}")
-        # worker 1 (奇数): 对照组（B 组）
-        self.assertFalse(result[1].get("x5sec"),
-                         f"奇数 worker 应为 B 组（不含 x5sec），实际={result[1]}")
+        # sites 非空 → 多站点路径
+        sites = [
+            SimpleNamespace(name="1688", cookie_domain="1688.com"),
+            SimpleNamespace(name="yiwugo", cookie_domain="yiwugo.com"),
+        ]
+        result = engine._alloc_seed_kits(2, sites=sites)
+        # 验证 dict 结构
+        self.assertIsInstance(result, dict)
+        self.assertEqual(set(result.keys()), {"1688", "yiwugo"})
+        for site_name in ("1688", "yiwugo"):
+            self.assertIsInstance(result[site_name], list)
+            self.assertEqual(len(result[site_name]), 2)
+            # 每个 site 内：worker 0 (偶数) A 组，worker 1 (奇数) B 组
+            self.assertTrue(result[site_name][0].get("x5sec"),
+                            f"{site_name} worker 0 应为 A 组（含 x5sec），"
+                            f"实际={result[site_name][0]}")
+            self.assertFalse(result[site_name][1].get("x5sec"),
+                             f"{site_name} worker 1 应为 B 组（不含 x5sec），"
+                             f"实际={result[site_name][1]}")
 
     def test_sites_none_seed_x5sec_unchanged(self):
         """sites=None 时 seed_x5sec 行为与现状一致。"""
         import json
         seeds = Path(self._tmp.name) / "seeds"
         seeds.mkdir()
         for name, has_x5sec in (("kitA", True), ("kitB", False)):
             cookies = [
                 {"name": "cna", "value": "v", "domain": ".1688.com"},
                 {"name": "cookie2", "value": "v", "domain": ".1688.com"},
diff --git a/fetcher/tests/test_needs_relaunch.py b/fetcher/tests/test_needs_relaunch.py
index 06245e1..2841333 100644
--- a/fetcher/tests/test_needs_relaunch.py
+++ b/fetcher/tests/test_needs_relaunch.py
@@ -98,27 +98,29 @@ class MarkNeedsRelaunchTest(unittest.TestCase):
 
     def test_mark_needs_relaunch_multiple_sites(self):
         """多个 site 各自独立置位。"""
         mgr = self._make_mgr()
         session = Session(browser=MagicMock())
         mgr.mark_needs_relaunch(session, "1688")
         mgr.mark_needs_relaunch(session, "yiwugo")
         self.assertTrue(session.extra["needs_relaunch"].get("1688"))
         self.assertTrue(session.extra["needs_relaunch"].get("yiwugo"))
 
-    def test_relaunch_complete_clears_flag(self):
-        """relaunch 完成后 needs_relaunch 清除（手动 pop 模拟完成路径）。"""
+    def test_clear_needs_relaunch_removes_single_site_flag(self):
+        """clear_needs_relaunch(session, site) 精确清除单个 site 标记。"""
+        mgr = self._make_mgr()
         session = Session(browser=MagicMock(),
-                          extra={"needs_relaunch": {"1688": True}})
-        # 模拟 relaunch 完成路径：pop 清除该 site 标记
-        session.extra["needs_relaunch"].pop("1688", None)
+                          extra={"needs_relaunch": {"1688": True, "yiwugo": True}})
+        mgr.clear_needs_relaunch(session, "1688")
         self.assertNotIn("1688", session.extra.get("needs_relaunch", {}))
+        # 其他 site 标记保留
+        self.assertIn("yiwugo", session.extra.get("needs_relaunch", {}))
 
 
 # ============================================================
 # 2. ensure_site 懒建消费：needs_relaunch 触发完整 relaunch
 # ============================================================
 
 class EnsureSiteRelaunchConsumeTest(unittest.TestCase):
     """ensure_site 检测到 needs_relaunch → 触发完整 relaunch。"""
 
     def setUp(self):
