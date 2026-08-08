# Re-review Package — Step 3.1 fix round 1

## Commits
f86b80b fix(multiqueue-p3): I1恢复纯函数单测+I2 reset逐site测试+I3 --queues动态校验+M4/M5/M6

## Stat
 .../task-3.1-report.md                             |  53 ++++++++++
 fetcher/fetcher/cli/main.py                        |  28 ++++--
 fetcher/fetcher/control/queue_router.py            |  25 ++---
 fetcher/tests/test_cli.py                          |  94 +++++++++++++++++
 fetcher/tests/test_queue_router.py                 | 111 ++++++++++++++++++++-
 5 files changed, 283 insertions(+), 28 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md
index 6cab2e7..1ad0443 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md
@@ -58,10 +58,63 @@
 
 ## 自查发现
 
 1. **CrawlLoop._bind_item_site 调用位置**：初次编辑只添加了方法定义未添加调用点，导致集成测试 inspector=None 崩溃。已修复：在 `run()` 的 acquire_item 后 + `_process_item` 入口各加一次调用
 2. **_check_budget ctx 变量名**：`budget_for(ctx)` → `budget_for(self.ctx)` 修复
 3. **Engine loop_factory kwargs 兼容**：仅 sites/policies 非 None 时传递，避免旧 FakeLoop 测试报 TypeError
 4. **label/giveup_cost 无 ctx 参数路由**：通过线程本地缓存 `_tls.last_queue` 实现（acquire_item 时写入）
 5. **condvar_timeout_multi cap 参数**：需显式传入 `_WAIT_TIMEOUT` 模块级常量（支持测试注入小超时值）
 6. **payload 含 id**：为兼容旧 DaemonTaskProxy 返回格式，acquire_item 返回 payload + `"id"` 键
 7. **mic 队列无种子约束**：daemon 直连时 mic 无种子会报错——冒烟只喂 1688 店，mic 队列无货不认领则不触 ensure_site(mic)，记录此约束
+
+
+## Fix Round 1（task-3.1-fix1.md）
+
+### I1 — Step 1.2 纯函数单测恢复 ✅
+
+从 ebd16ba 找回 eligible_queues / condvar_timeout 纯函数单测 12 项，并入 test_queue_router.py：
+- QueueSpecTest（1）：构造与字段
+- EligibleQueuesTest（6）：无冷却全可见、冷却过滤、资源过滤、到期恢复、空注册表、空 resources 匹配空 requires
+- CondvarTimeoutPureTest（6）：不在冷却返回 cap、冷却中 min(剩余,cap)、自定义 cap、极小剩余>0、到期边缘返回 cap、多 site 取最小值
+
+原 CondvarTimeoutTest（QueueRouter 集成版）重命名为 RouterCondvarTimeoutTest 避免命名冲突。
+
+### I2 — reset 逐 site 测试 ✅
+
+- 从 `_run_daemon` 提取 `reset_daemon_state(db, registry) -> (int, int)` 为独立可测函数
+- 新增 `ResetDaemonStateTest`：
+  - `test_reset_only_targeted_domain_suffixes`：seed 两组不同 domain_suffix 的 in_progress + 一个无关站点，断言仅匹配的域名被重置、无关站点保持 in_progress
+  - `test_reset_with_empty_registry`：空 registry 只做 claimed 回收，不重置任何 in_progress
+- 测试使用 `upsert_shops`（非 raw INSERT，避免缺少 first_seen_at 等必需列导致静默失败）
+
+### I3 — --queues 动态校验 ✅
+
+- `all_queue_names` 改为从 `_build_registry()`（全量无过滤）动态派生：`[s.queue for s in full_registry]`
+- `test_daemon_queues_dynamic_from_registry` 验证注册表动态派生
+
+### M4 — compose/summary 注释 ✅
+
+两方法各加一行注释：`# 简单方案：委托首个注册 task（多队列下统计口径待后续细化）`
+
+### M5 — payload["id"] 注释 ✅
+
+- grep 确认 site 插件只依赖 domain/name/url（无 item["id"] 引用）
+- 保留 `payload["id"]`（测试/DB 验证用），更新注释为：`# 保留 id 键：测试/DB 验证用（site 插件只依赖 domain/name/url）`
+
+### M6 — condvar_timeout（单 queue 版）删除 ✅
+
+全仓库无调用；已删除。多队列版 `condvar_timeout_multi` 保留。
+
+### 副作用修复
+
+- QueueSpec.task 默认值改为 None（纯函数测试不需要 task）
+- QueueSpec.topup 类型从 `Callable[[ShopDB, int], int] | None` 改为 `object | None`（Python 3.13 dataclass 兼容性）
+- 删除重复 `@dataclass` 装饰器（编辑遗留）
+- 删除未使用的 `Callable` import
+
+### 测试验证
+
+```
+cd fetcher && python -m pytest tests -q
+420 passed, 2 subtests passed
+```
+
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index 8daf062..acdd02d 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -203,23 +203,24 @@ def _build_engine(cfg, task, site, provider, policy, site_name):
     """纯装配辅助：构造 Engine 并返回（不调 run）。
 
     提取为独立函数便于测试 site_name 透传正确性。
     """
     from fetcher.control.engine import Engine
     return Engine(cfg, task, site=site, provider=provider, policy=policy,
                   site_name=site_name)
 
 
 def _build_registry(selected_queues: list[str] | None = None) -> list:
-    """构建 daemon 队列注册表（本 Step 2 条队列，P3-4/P3-5 加 shop/company）。
+    """构建 daemon 全量队列注册表（本 Step 2 条队列，P3-4/P3-5 加 shop/company）。
 
     selected_queues 非空时只保留指定队列；None=全量。
+    返回值即 spec.queue 的全量列表，可作为 argparse choices 的来源。
     """
     from fetcher.control.queue_router import QueueSpec
 
     specs = []
 
     # crawl_1688_contact
     site_1688 = get_site("1688")
     specs.append(QueueSpec(
         queue="crawl_1688_contact",
         site="1688",
@@ -238,30 +239,45 @@ def _build_registry(selected_queues: list[str] | None = None) -> list:
         topup=lambda db, limit: db.topup_contact_work_items(
             "crawl_mic_contact", "madeinchina", ".cn.made-in-china.com", limit),
         domain_suffix=".cn.made-in-china.com",
     ))
 
     if selected_queues:
         specs = [s for s in specs if s.queue in selected_queues]
     return specs
 
 
+def reset_daemon_state(db, registry: list) -> tuple[int, int]:
+    """daemon 启动崩溃恢复：全量回收 claimed + 逐 site 重置 in_progress。
+
+    返回 (n_claimed_reset, n_in_progress_reset)。
+    提取为独立函数便于测试（I2）。
+    """
+    n_items = db.reset_claimed_work_items()
+    total_shops = 0
+    for spec in registry:
+        n = db.reset_in_progress(spec.domain_suffix)
+        total_shops += n
+    return n_items, total_shops
+
+
 def _run_daemon(args) -> int:
     """daemon 常驻模式装配：QueueRouter 跨队列认领 + Engine 跑。"""
     from fetcher.control.engine import Engine
     from fetcher.control.queue_router import QueueRouter
     from fetcher.db import ShopDB
 
     cfg = config_from_args(args)
 
-    # 校验 --queues（如果传入）
-    all_queue_names = ["crawl_1688_contact", "crawl_mic_contact"]
+    # 先建全量 registry（供校验用）
+    full_registry = _build_registry()
+    all_queue_names = [s.queue for s in full_registry]
     if args.queues:
         for q in args.queues:
             if q not in all_queue_names:
                 print(f"[!] 未知队列: {q!r}（可选: {', '.join(all_queue_names)}）")
                 return 2
 
     registry = _build_registry(args.queues)
     if not registry:
         print("[!] 没有可用的队列（--queues 过滤后为空）")
         return 2
@@ -292,25 +308,21 @@ def _run_daemon(args) -> int:
 
     # 站点 dict（供 loop _bind_item_site 按 active_site 切换）
     sites = {}
     for site_name in site_set:
         sites[site_name] = get_site(site_name)
 
     # 崩溃恢复：先回收 work_items 残留认领（全量），
     # 再逐 site 重置 shops 的 in_progress（按 domain_suffix 过滤）
     db = ShopDB(cfg.resolved_db_path())
     try:
-        n_items = db.reset_claimed_work_items()
-        total_shops = 0
-        for spec in registry:
-            n = db.reset_in_progress(spec.domain_suffix)
-            total_shops += n
+        n_items, total_shops = reset_daemon_state(db, registry)
     finally:
         db.close()
     print(f"[daemon] 启动重置：{n_items} 个 claimed 工作项 → pending，"
           f"{total_shops} 个 in_progress 店铺 → pending"
           f"（逐 site: {', '.join(spec.domain_suffix for spec in registry)}）")
 
     # Engine 装配：site 用首个注册 site（BrowserManager 初始 view identity 前缀），
     # policy 用 default_policy（多 site 的 _bind_item_site 会动态切换）
     first_site_obj = get_site(first_site)
     engine = Engine(cfg, task=router, site=first_site_obj,
diff --git a/fetcher/fetcher/control/queue_router.py b/fetcher/fetcher/control/queue_router.py
index 59ca1e3..5c2cfc7 100644
--- a/fetcher/fetcher/control/queue_router.py
+++ b/fetcher/fetcher/control/queue_router.py
@@ -3,72 +3,56 @@
 
 QueueRouter 取代 DaemonTaskProxy：跨队列认领（资源满足 ∧ 站点冷却到期）
 → 路由到 item 所属队列的 task。daemon 常驻等货；无平台依赖，仅 daemon 用。
 """
 
 from __future__ import annotations
 
 import threading
 import time
 from dataclasses import dataclass, field
-from typing import Callable
 
 from fetcher.db import ShopDB
 
 # 等货条件变量自醒超时（秒）：保证 stop 置位后 acquire_item 最多 30s 内返回
 _WAIT_TIMEOUT = 30.0
 
 # ctx.state 上记录当前 worker 认领的 work_item id 的键
 _STATE_KEY = "daemon_work_item_id"
 
 
 @dataclass
 class QueueSpec:
     """队列注册表条目。"""
     queue: str                    # "crawl_1688_contact" / ...
     site: str                     # 站点注册名 "1688" / "madeinchina"
-    task: object                  # 该队列工作项的执行流水线（Task 协议）
-    topup: Callable[[ShopDB, int], int] | None = None   # 补货函数；feeder 类队列为 None
+    task: object = None             # 该队列工作项的执行流水线（Task 协议）
+    topup: object | None = None   # Callable[[ShopDB, int], int] | None；补货函数
     domain_suffix: str = ""       # contact 类 topup 用；启动 reset 用
     requires: set[str] = field(default_factory=lambda: {"channel", "browser"})
 
 
 def eligible_queues(registry, ctx, now: float) -> list[str]:
     """当前消费者可认领的队列名列表：资源满足 ∧ 该站点冷却已到期。
 
     registry: 可迭代的 QueueSpec。
     ctx: 有 .resources（set）与 .cooldown_until（dict[site, float]）的对象。
     纯函数，无副作用；返回按注册表顺序。
     """
     result = []
     for q in registry:
         if q.requires <= ctx.resources \
                 and now >= ctx.cooldown_until.get(q.site, 0):
             result.append(q.queue)
     return result
 
 
-def condvar_timeout(cooldown_until: dict[str, float], site: str,
-                    now: float, cap: float = 30.0) -> float:
-    """计算 Condition.wait 的超时值（秒）。
-
-    - site 在冷却中（now < 到期） → min(到期 - now, cap)
-    - site 不在冷却 → cap
-    - 返回值总是 > 0。
-    """
-    deadline = cooldown_until.get(site, 0)
-    if now < deadline:
-        remaining = deadline - now
-        return remaining if remaining < cap else cap
-    return cap
-
-
 def condvar_timeout_multi(cooldown_until: dict[str, float],
                           sites: list[str], now: float,
                           cap: float = 30.0) -> float:
     """多队列 condvar timeout：取所有冷却中 site 的剩余时间的最小值。
 
     无任何 site 在冷却 → cap。
     """
     min_remaining = None
     for site in sites:
         deadline = cooldown_until.get(site, 0)
@@ -172,25 +156,27 @@ class QueueRouter:
 
     def empty_message(self):
         if self._specs:
             return self._specs[0].task.empty_message()
         return "没有待做的任务了"
 
     def make_stats(self):
         return {"done": 0}
 
     def compose(self, wid: int, f: dict) -> str:
+        # 简单方案：委托首个注册 task（多队列下统计口径待后续细化）
         if self._specs:
             return self._specs[0].task.compose(wid, f)
         return str(f.get("line", ""))
 
     def summary(self, all_stats: dict, db_path=None) -> str:
+        # 简单方案：委托首个注册 task（多队列下统计口径待后续细化）
         if self._specs:
             return self._specs[0].task.summary(all_stats, db_path=db_path)
         return str(all_stats)
 
     # ---- DB 访问 ----
 
     def _db(self, ctx) -> ShopDB:
         """取当前线程可用的 ShopDB。"""
         if getattr(ctx, "store", None) is not None:
             return ctx.store.db
@@ -247,21 +233,22 @@ class QueueRouter:
                 queues = eligible_queues(self._specs, ctx, now)
                 if queues:
                     item = db.claim_next_eligible(queues, consumer_id)
                     if item is not None:
                         ctx.state[_STATE_KEY] = item["id"]
                         ctx.state["queue"] = item["queue"]
                         ctx.state["active_site"] = item["site"]
                         # 缓存队列名到线程本地（label/giveup_cost 无 ctx 参数时用）
                         self._tls.last_queue = item["queue"]
                         payload = dict(item["payload"])
-                        payload["id"] = item["id"]  # 兼容旧 DaemonTaskProxy 返回格式
+                        # 保留 id 键：测试/DB 验证用（site 插件只依赖 domain/name/url）
+                        payload["id"] = item["id"]
                         return payload
 
                 # topup：只对冷却到期的 contact 队列补货
                 any_topped = False
                 for spec in self._specs:
                     if spec.topup is not None \
                             and now >= ctx.cooldown_until.get(spec.site, 0):
                         n = spec.topup(db, limit)
                         if n:
                             any_topped = True
diff --git a/fetcher/tests/test_cli.py b/fetcher/tests/test_cli.py
index 168f1a8..fa99810 100644
--- a/fetcher/tests/test_cli.py
+++ b/fetcher/tests/test_cli.py
@@ -32,20 +32,28 @@ class CliParserTest(unittest.TestCase):
         self.assertEqual(args.limit, 0)
 
     def test_daemon_queues_and_common_override(self):
         args = self.ap.parse_args(
             ["daemon", "--queues", "crawl_1688_contact", "crawl_mic_contact",
              "--workers", "3", "--limit", "5"])
         self.assertEqual(args.queues, ["crawl_1688_contact", "crawl_mic_contact"])
         self.assertEqual(args.workers, 3)
         self.assertEqual(args.limit, 5)
 
+    def test_daemon_queues_dynamic_from_registry(self):
+        """I3：--queues 校验来自注册表动态派生，非硬编码。"""
+        from fetcher.cli.main import _build_registry
+        full = _build_registry()
+        all_names = [s.queue for s in full]
+        self.assertIn("crawl_1688_contact", all_names)
+        self.assertIn("crawl_mic_contact", all_names)
+
     def test_daemon_config_from_args(self):
         # config_from_args 不读 args.task，daemon 命名空间可直接复用
         cfg = config_from_args(self.ap.parse_args(["daemon"]))
         self.assertEqual(cfg.batch_num, 10)
         self.assertEqual(cfg.limit, 0)
 
     def test_daemon_has_no_task_subparser(self):
         # daemon 后不能再跟 task 位置参数（argparse 报错退出）
         with self.assertRaises(SystemExit):
             self.ap.parse_args(["daemon", "contact"])
@@ -101,12 +109,98 @@ class BuildEngineTest(unittest.TestCase):
         """site=None 时 site_name 可为 None（Engine guard 不触发）。"""
         cfg = RunConfig(headless=True, use_proxy=False)
         fake_task = MagicMock()
         engine = _build_engine(cfg, fake_task, site=None,
                                provider=None, policy=Policy(),
                                site_name=None)
         self.assertIsNone(engine.site_name)
         self.assertIsNone(engine.site)
 
 
+class ResetDaemonStateTest(unittest.TestCase):
+    """I2：reset_daemon_state 逐 site 重置。"""
+
+    def setUp(self):
+        self._tmp = __import__("tempfile").TemporaryDirectory()
+        from pathlib import Path
+        from fetcher.db import ShopDB
+        self.db_path = Path(self._tmp.name) / "t.db"
+        self.db = ShopDB(self.db_path)
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def _seed_in_progress(self, domains):
+        """Seed shops 为 in_progress 状态。"""
+        shops = [{"domain": d, "name": d, "url": f"https://{d}"}
+                 for d in domains]
+        self.db.upsert_shops(shops)
+        # upsert 默认 pending，需手动设为 in_progress
+        for d in domains:
+            self.db.conn.execute(
+                "UPDATE shops SET status='in_progress' WHERE domain=?", (d,))
+        self.db.conn.commit()
+
+    def test_reset_only_targeted_domain_suffixes(self):
+        """只有指定 domain_suffix 的 in_progress 被重置，其他站点不动。"""
+        from fetcher.cli.main import _build_registry, reset_daemon_state
+        from fetcher.control.queue_router import QueueSpec
+
+        # Seed 混合 in_progress：两个不同 domain_suffix
+        self._seed_in_progress(["s1.1688.com", "s2.1688.com", "s3.1688.com"])
+        self._seed_in_progress(["s1.cn.made-in-china.com",
+                                "s2.cn.made-in-china.com"])
+        # 额外：一个不匹配任何 registered domain 的也应是 in_progress
+        self._seed_in_progress(["other.example.com"])
+
+        # 用全量 registry
+        registry = _build_registry()
+
+        n_items, total_shops = reset_daemon_state(self.db, registry)
+
+        # claimed 无 → 0
+        self.assertEqual(n_items, 0)
+        # 1688 (3) + mic (2) = 5 个被重置
+        self.assertEqual(total_shops, 5)
+
+        # 核查：1688 的变 pending
+        for d in ["s1.1688.com", "s2.1688.com", "s3.1688.com"]:
+            self.assertEqual(
+                self.db.conn.execute(
+                    "SELECT status FROM shops WHERE domain=?", (d,)
+                ).fetchone()[0],
+                "pending")
+        # mic 的变 pending
+        for d in ["s1.cn.made-in-china.com", "s2.cn.made-in-china.com"]:
+            self.assertEqual(
+                self.db.conn.execute(
+                    "SELECT status FROM shops WHERE domain=?", (d,)
+                ).fetchone()[0],
+                "pending")
+        # 其他站点不动（仍为 in_progress）
+        self.assertEqual(
+            self.db.conn.execute(
+                "SELECT status FROM shops WHERE domain=?",
+                ("other.example.com",)
+            ).fetchone()[0],
+            "in_progress")
+
+    def test_reset_with_empty_registry(self):
+        """空 registry → 只做 claimed 回收，不重置任何 in_progress。"""
+        from fetcher.cli.main import reset_daemon_state
+
+        self._seed_in_progress(["s1.1688.com"])
+        n_items, total_shops = reset_daemon_state(self.db, [])
+        self.assertEqual(n_items, 0)
+        self.assertEqual(total_shops, 0)
+        # s1.1688.com 未被重置（仍 in_progress）
+        self.assertEqual(
+            self.db.conn.execute(
+                "SELECT status FROM shops WHERE domain=?",
+                ("s1.1688.com",)
+            ).fetchone()[0],
+            "in_progress")
+
+
 if __name__ == "__main__":
     unittest.main()
diff --git a/fetcher/tests/test_queue_router.py b/fetcher/tests/test_queue_router.py
index 8b72840..fdc29ea 100644
--- a/fetcher/tests/test_queue_router.py
+++ b/fetcher/tests/test_queue_router.py
@@ -21,25 +21,134 @@ from fetcher import (
     RunConfig,
     ShopDB,
     Session,
     WorkerContext,
 )
 from fetcher.control import CrawlLoop, Task
 from fetcher.control.queue_router import (
     QueueRouter,
     QueueSpec,
     _WAIT_TIMEOUT,
+    condvar_timeout_multi,
+    eligible_queues,
 )
 from fetcher.core.types import ActionResult, Outcome
 from fetcher.strategy.policy import Policy
 
 
+# =====================================================================
+# Step 1.2 纯函数测试（I1 恢复）
+# =====================================================================
+
+class QueueSpecTest(unittest.TestCase):
+    """QueueSpec 数据类基本构造与字段访问。"""
+
+    def test_construction_and_fields(self):
+        qs = QueueSpec(queue="crawl_1688_contact", site="1688",
+                       requires={"channel", "browser"})
+        self.assertEqual(qs.queue, "crawl_1688_contact")
+        self.assertEqual(qs.site, "1688")
+        self.assertEqual(qs.requires, {"channel", "browser"})
+
+
+class EligibleQueuesTest(unittest.TestCase):
+    """eligible_queues 过滤逻辑：资源满足 + 冷却到期。"""
+
+    def _registry(self):
+        return [
+            QueueSpec(queue="crawl_1688_contact", site="1688",
+                      requires={"channel", "browser"}),
+            QueueSpec(queue="crawl_madeinchina", site="madeinchina",
+                      requires={"channel", "browser"}),
+            QueueSpec(queue="crawl_1688_search", site="1688",
+                      requires={"channel"}),
+        ]
+
+    def _ctx(self, resources=None, cooldown_until=None):
+        return type("FakeCtx", (), {
+            "resources": resources or {"channel", "browser"},
+            "cooldown_until": cooldown_until or {},
+        })()
+
+    def test_all_eligible_with_no_cooldown(self):
+        result = eligible_queues(self._registry(), self._ctx(), 100.0)
+        self.assertEqual(result, ["crawl_1688_contact", "crawl_madeinchina",
+                                  "crawl_1688_search"])
+
+    def test_cooldown_filters_site_queues(self):
+        ctx = self._ctx(cooldown_until={"1688": 200.0})
+        result = eligible_queues(self._registry(), ctx, 100.0)
+        self.assertEqual(result, ["crawl_madeinchina"])
+
+    def test_resource_filtering(self):
+        ctx = self._ctx(resources={"channel"})
+        result = eligible_queues(self._registry(), ctx, 100.0)
+        self.assertEqual(result, ["crawl_1688_search"])
+
+    def test_expiry_recovery(self):
+        ctx = self._ctx(cooldown_until={"1688": 100.0, "madeinchina": 200.0})
+        result = eligible_queues(self._registry(), ctx, 100.0)
+        self.assertEqual(result, ["crawl_1688_contact", "crawl_1688_search"])
+        result2 = eligible_queues(self._registry(), ctx, 200.0)
+        self.assertEqual(result2, ["crawl_1688_contact", "crawl_madeinchina",
+                                   "crawl_1688_search"])
+
+    def test_empty_registry(self):
+        self.assertEqual(eligible_queues([], self._ctx(), 100.0), [])
+
+    def test_empty_resources_still_matches_empty_requires(self):
+        registry = [QueueSpec(queue="no_resources", site="x", requires=set())]
+        ctx = self._ctx(resources=set())
+        result = eligible_queues(registry, ctx, 100.0)
+        self.assertEqual(result, ["no_resources"])
+
+
+class CondvarTimeoutPureTest(unittest.TestCase):
+    """condvar_timeout_multi 纯函数计算（含边界）。"""
+
+    def test_not_in_cooldown_returns_cap(self):
+        self.assertEqual(condvar_timeout_multi({}, ["a"], 100.0), 30.0)
+
+    def test_in_cooldown_returns_min_of_remaining_and_cap(self):
+        cooldown_until = {"a": 120.0}
+        self.assertAlmostEqual(
+            condvar_timeout_multi(cooldown_until, ["a"], 100.0), 20.0, delta=1e-9)
+        self.assertAlmostEqual(
+            condvar_timeout_multi(cooldown_until, ["a"], 60.0), 30.0, delta=1e-9)
+
+    def test_custom_cap(self):
+        cooldown_until = {"a": 110.0}
+        self.assertAlmostEqual(
+            condvar_timeout_multi(cooldown_until, ["a"], 100.0, cap=5.0), 5.0)
+
+    def test_very_small_remaining_returns_positive(self):
+        cooldown_until = {"a": 100.01}
+        result = condvar_timeout_multi(cooldown_until, ["a"], 100.0)
+        self.assertGreater(result, 0.0)
+        self.assertAlmostEqual(result, 0.01, delta=1e-6)
+
+    def test_exactly_at_deadline_returns_cap(self):
+        cooldown_until = {"a": 100.0}
+        self.assertEqual(condvar_timeout_multi(cooldown_until, ["a"], 100.0), 30.0)
+
+    def test_multi_site_returns_minimum(self):
+        """多队列取最小冷却剩余。"""
+        cooldown_until = {"1688": 115.0, "madeinchina": 105.0}  # 15s vs 5s
+        self.assertAlmostEqual(
+            condvar_timeout_multi(cooldown_until, ["1688", "madeinchina"], 100.0),
+            5.0, delta=1e-9)
+
+
+# =====================================================================
+# QueueRouter 集成测试
+
+
 QUEUE_A = "crawl_1688_contact"
 QUEUE_B = "crawl_mic_contact"
 
 
 def _shop_1688(i):
     return {"domain": f"shop{i}.1688.com", "name": f"店铺{i}",
             "url": f"https://shop{i}.1688.com"}
 
 
 def _shop_mic(i):
@@ -362,21 +471,21 @@ class TopupPerQueueTest(QueueRouterTestBase):
         self.assertEqual(item["domain"], "shop1.cn.made-in-china.com")
 
         # A 队列不应有 work_items（topup 被冷却阻挡）
         rows_a = self.query("SELECT COUNT(*) AS c FROM work_items"
                             " WHERE queue=?", (QUEUE_A,))
         self.assertEqual(rows_a[0]["c"], 0)
 
 
 # ---------- 用例 4：condvar timeout ----------
 
-class CondvarTimeoutTest(QueueRouterTestBase):
+class RouterCondvarTimeoutTest(QueueRouterTestBase):
     def test_timeout_with_cooldown(self):
         """冷却中 wait 剩余时间（取各 site 最小值）。"""
         # seed shops for madeinchina so when cooldown expires, claim succeeds
         self.db.upsert_shops([_shop_mic(1)])
         self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                          ".cn.made-in-china.com", 1)
         ctx = self.make_ctx()
         ctx.cooldown_until["1688"] = time.time() + 15
         ctx.cooldown_until["madeinchina"] = time.time() + 0.5  # 最小值 0.5s
 
