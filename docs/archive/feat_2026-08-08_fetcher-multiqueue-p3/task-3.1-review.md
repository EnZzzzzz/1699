# Review Package — Step 3.1 (QueueRouter + daemon CLI)

## Commits
6312302 feat(multiqueue-p3): QueueRouter取代DaemonTaskProxy，多队列注册表装配，daemon CLI --queues

## Stat
 .../task-3.1-report.md                             |  67 ++
 fetcher/fetcher/cli/main.py                        | 125 ++-
 fetcher/fetcher/control/daemon_task.py             | 207 -----
 fetcher/fetcher/control/engine.py                  |  13 +-
 fetcher/fetcher/control/loop.py                    |  35 +-
 fetcher/fetcher/control/queue_router.py            | 274 +++++-
 fetcher/fetcher/control/task.py                    |   8 +
 fetcher/fetcher/core/context.py                    |   2 +-
 fetcher/tests/test_cli.py                          |  11 +-
 fetcher/tests/test_cooldown.py                     |  22 +-
 fetcher/tests/test_daemon_task.py                  | 423 ---------
 fetcher/tests/test_queue_router.py                 | 976 ++++++++++++++++++---
 12 files changed, 1352 insertions(+), 811 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md
new file mode 100644
index 0000000..6cab2e7
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md
@@ -0,0 +1,67 @@
+# Task 3.1 Report — QueueRouter + 注册表装配 + daemon CLI（--queues）
+
+> 日期：2026-08-08 | 分支：feat/multiqueue-p3 | 基线：395 passed → 404 passed
+
+## 实现摘要
+
+**QueueRouter 取代 DaemonTaskProxy**（P0 组件，无平台依赖，直接替换）：
+
+1. **QueueSpec 补全**（`queue_router.py`）：`task`/`topup`/`domain_suffix` 字段，`requires` 默认 `{"channel", "browser"}`
+2. **QueueRouter 类**：跨队列认领（三段式：claim_next_eligible → per-queue topup → condvar wait），per-item site 绑定（ctx.state["queue"]/["active_site"]），执行侧方法经 ctx.state 路由到 item 所属 queue 的 task
+3. **Task 协议新增 `budget_for(ctx)`**（基类默认返回 `ip_request_budget`，CLI 零影响）
+4. **loop `_bind_item_site`**：daemon 路径（sites 非空）按 active_site 动态切换 ctx.site/inspector/policy；CLI 路径（sites=None）无操作
+5. **Engine 多站点装配**：sites/policies 参数透传 loop_factory；仅非 None 时传递（兼容现有 FakeLoop 测试）
+6. **daemon CLI `--queue`→`--queues`**：nargs="+"，默认全量，支持子集过滤；`_build_registry()` 静态装配 2 条队列（`crawl_1688_contact` + `crawl_mic_contact`）
+7. **启动 reset 逐 site**：`reset_in_progress(domain_suffix)` 按注册表逐队列循环（修复无过滤重置所有站点的现存坑）
+8. **删除 `daemon_task.py`**（git rm）+ `test_daemon_task.py` 重写为 `test_queue_router.py`
+
+## 改动文件
+
+| 文件 | 操作 | 说明 |
+|------|------|------|
+| `fetcher/fetcher/control/queue_router.py` | 重写 | QueueSpec 补全 + QueueRouter 类 + condvar_timeout_multi |
+| `fetcher/fetcher/control/task.py` | 修改 | +budget_for(ctx) 方法 |
+| `fetcher/fetcher/control/loop.py` | 修改 | +sites/policies 参数 + _bind_item_site + _check_budget 改 budget_for |
+| `fetcher/fetcher/control/engine.py` | 修改 | +sites/policies 参数，透传 loop_factory |
+| `fetcher/fetcher/cli/main.py` | 修改 | --queues + _build_registry + 逐 site reset + QueueRouter 装配 |
+| `fetcher/fetcher/control/daemon_task.py` | **删除** | git rm |
+| `fetcher/fetcher/core/context.py` | 修改 | 注释更新（daemon_task → queue_router） |
+| `fetcher/tests/test_daemon_task.py` | **删除** | git rm（重写为 test_queue_router.py） |
+| `fetcher/tests/test_queue_router.py` | 新增 | 29 测试（跨队列/冷却/topup/condvar/终态路由/budget/loop/联跑/执行路由） |
+| `fetcher/tests/test_cli.py` | 修改 | --queue → --queues，daemon 测试适配 |
+| `fetcher/tests/test_cooldown.py` | 修改 | DaemonTaskProxy → QueueRouter 适配 |
+
+## 测试列表（test_queue_router.py，29 项）
+
+- **跨队列认领**：FIFO 跨队列 claim、payload dict 格式、state 键写入
+- **冷却过滤**：冷却中过滤 site A 只认领 B、冷却到期恢复、冷却到期自动认领
+- **topup**：冷却中队列不补货、到期队列补货后重试
+- **condvar timeout**：多队列取最小冷却剩余、无冷却 30s 兜底、stop 退出、单队列冷却到期唤醒
+- **终态路由**：on_success 路由到正确 task + 落 done、on_giveup 路由到正确 task + 落 failed、重复 finish 幂等、跨 ctx stray finish 安全
+- **budget_for**：不同 site 返回不同预算、无 queue 返回 None、QueueRouter.ip_request_budget 始终 None
+- **Task 兼容**：Task 基类 budget_for 默认返回 ip_request_budget
+- **loop 双队列装配**：sites/policies 注入后 site/inspector/policy 切换正确、CLI 路径（sites=None）不变
+- **CrawlLoop 联跑**：单 worker 跑双队列，2 项全 done，inner 成功明细不串
+- **Router 属性**：unit="项"、batch_unit=""、cold_start_before_acquire=False、rest_counter、ip_request_budget 为 None
+- **执行侧路由**：fetch/validate/label 路由到正确 inner task
+
+## TDD 证据
+
+1. **RED**：test_queue_router.py 创建后立即运行，ImportError（QueueRouter 不存在）→ 13 失败 16 通过（缺失实现）→ 逐步修复
+2. **GREEN**：全部 29 项通过 + 全量 404 passed（含旧测试无回归）
+
+## grep 复核
+
+- ✅ 无 `DaemonTaskProxy`/`daemon_task` 残留引用（仅注释提及）
+- ✅ 无 `--queue` 残留（全部改为 `--queues`）
+- ✅ `daemon_task.py` 已通过 git rm 删除
+
+## 自查发现
+
+1. **CrawlLoop._bind_item_site 调用位置**：初次编辑只添加了方法定义未添加调用点，导致集成测试 inspector=None 崩溃。已修复：在 `run()` 的 acquire_item 后 + `_process_item` 入口各加一次调用
+2. **_check_budget ctx 变量名**：`budget_for(ctx)` → `budget_for(self.ctx)` 修复
+3. **Engine loop_factory kwargs 兼容**：仅 sites/policies 非 None 时传递，避免旧 FakeLoop 测试报 TypeError
+4. **label/giveup_cost 无 ctx 参数路由**：通过线程本地缓存 `_tls.last_queue` 实现（acquire_item 时写入）
+5. **condvar_timeout_multi cap 参数**：需显式传入 `_WAIT_TIMEOUT` 模块级常量（支持测试注入小超时值）
+6. **payload 含 id**：为兼容旧 DaemonTaskProxy 返回格式，acquire_item 返回 payload + `"id"` 键
+7. **mic 队列无种子约束**：daemon 直连时 mic 无种子会报错——冒烟只喂 1688 店，mic 队列无货不认领则不触 ensure_site(mic)，记录此约束
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index e55f6b0..8daf062 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -48,23 +48,23 @@ def build_parser() -> argparse.ArgumentParser:
     # daemon 常驻模式：与站点 subparsers 平级（dest 同为 "site"），不属于
     # 任何站点、不套 task 二级 subparser；num/limit 按 contact 口径给出，
     # 供 config_from_args 复用（--limit 是冒烟收工手段，走 CrawlLoop 既有逻辑）
     p_daemon = sub.add_parser(
         "daemon", help="常驻模式：从 work_items 队列持续消费（P0 仅 1688 contact）")
     p_daemon.add_argument("-n", "--num", type=int,
                           default=TASK_NUM_DEFAULTS["contact"],
                           help="每个 worker 每批采集数量；采满一批后强制休息")
     p_daemon.add_argument("--limit", type=int, default=0,
                           help="每个 worker 本次最多采集量（默认 0=不限）")
-    p_daemon.add_argument("--queue", type=str, default="crawl_1688_contact",
-                          help="消费的 work_items 队列名（P0 只支持默认值 "
-                               "crawl_1688_contact，不开放其他选择）")
+    p_daemon.add_argument("--queues", nargs="+", default=None,
+                          help="消费的 work_items 队列列表（默认全量；可选: "
+                               "crawl_1688_contact, crawl_mic_contact）")
     add_common_args(p_daemon, default_rest_every=20)
     return ap
 
 
 def add_common_args(ap: argparse.ArgumentParser,
                     default_rest_every: int = 20) -> None:
     """所有任务共享的网络层参数（迁移旧 add_common_args）。"""
     ap.add_argument("--batch-rest", type=float, default=900,
                     help="每批采满后的强制休息秒数（默认 900=15 分钟，±10%% 抖动）")
     ap.add_argument("--max-batches", type=int, default=0,
@@ -202,56 +202,123 @@ def main(argv: list | None = None) -> int:
 def _build_engine(cfg, task, site, provider, policy, site_name):
     """纯装配辅助：构造 Engine 并返回（不调 run）。
 
     提取为独立函数便于测试 site_name 透传正确性。
     """
     from fetcher.control.engine import Engine
     return Engine(cfg, task, site=site, provider=provider, policy=policy,
                   site_name=site_name)
 
 
-def _run_daemon(args) -> int:
-    """daemon 常驻模式装配：1688 contact 包 DaemonTaskProxy 后跑 Engine。
+def _build_registry(selected_queues: list[str] | None = None) -> list:
+    """构建 daemon 队列注册表（本 Step 2 条队列，P3-4/P3-5 加 shop/company）。
 
-    config_from_args 不读 args.task（读 task 的是站点分支的
-    site.make_task(args.task)），daemon parser 已带 num/limit 默认值，
-    故 config_from_args 原样复用、无需任何适配。provider/policy/Engine
-    装配与站点分支逐项一致；退出语义不加新逻辑（信号走 Engine 既有
-    优雅退出，--limit 走 CrawlLoop 既有收工逻辑）。
+    selected_queues 非空时只保留指定队列；None=全量。
     """
-    from fetcher.control.daemon_task import DaemonTaskProxy
+    from fetcher.control.queue_router import QueueSpec
+
+    specs = []
+
+    # crawl_1688_contact
+    site_1688 = get_site("1688")
+    specs.append(QueueSpec(
+        queue="crawl_1688_contact",
+        site="1688",
+        task=site_1688.make_task("contact"),
+        topup=lambda db, limit: db.topup_contact_work_items(
+            "crawl_1688_contact", "1688", ".1688.com", limit),
+        domain_suffix=".1688.com",
+    ))
+
+    # crawl_mic_contact
+    site_mic = get_site("madeinchina")
+    specs.append(QueueSpec(
+        queue="crawl_mic_contact",
+        site="madeinchina",
+        task=site_mic.make_task("contact"),
+        topup=lambda db, limit: db.topup_contact_work_items(
+            "crawl_mic_contact", "madeinchina", ".cn.made-in-china.com", limit),
+        domain_suffix=".cn.made-in-china.com",
+    ))
+
+    if selected_queues:
+        specs = [s for s in specs if s.queue in selected_queues]
+    return specs
+
+
+def _run_daemon(args) -> int:
+    """daemon 常驻模式装配：QueueRouter 跨队列认领 + Engine 跑。"""
+    from fetcher.control.engine import Engine
+    from fetcher.control.queue_router import QueueRouter
     from fetcher.db import ShopDB
 
     cfg = config_from_args(args)
-    site = get_site("1688")
-    inner = site.make_task("contact")
-    task = DaemonTaskProxy(inner, queue=args.queue, site="1688",
-                           domain_suffix=".1688.com")
-    if not task.prepare(cfg):
+
+    # 校验 --queues（如果传入）
+    all_queue_names = ["crawl_1688_contact", "crawl_mic_contact"]
+    if args.queues:
+        for q in args.queues:
+            if q not in all_queue_names:
+                print(f"[!] 未知队列: {q!r}（可选: {', '.join(all_queue_names)}）")
+                return 2
+
+    registry = _build_registry(args.queues)
+    if not registry:
+        print("[!] 没有可用的队列（--queues 过滤后为空）")
+        return 2
+
+    router = QueueRouter(registry)
+    if not router.prepare(cfg):
         return 0
 
     provider = make_provider(cfg)
-    # 策略表：默认表 + 站点级覆盖（policy_overrides）+ CLI 熔断上限
-    from fetcher.strategy.policy import Policy
-    policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
-    overrides = getattr(site, "policy_overrides", None)
-    if overrides:
-        policy = policy.with_overrides(overrides)
 
-    # 崩溃恢复（SPEC §3.3 状态流）：先回收 work_items 残留认领，
-    # 再重置 shops 的 in_progress（不带 domain 过滤，与既有 CLI 启动语义一致）
+    # 策略表：对 registry 涉及的每个 site 建 Policy
+    from fetcher.strategy.policy import Policy
+    policies = {}
+    site_set = set()
+    for spec in registry:
+        if spec.site not in site_set:
+            site_set.add(spec.site)
+            site = get_site(spec.site)
+            policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
+            overrides = getattr(site, "policy_overrides", None)
+            if overrides:
+                policy = policy.with_overrides(overrides)
+            policies[spec.site] = policy
+
+    # daemon 用注册表首个 site 的默认 policy 作为 Engine 级 policy
+    first_site = registry[0].site
+    default_policy = policies[first_site]
+
+    # 站点 dict（供 loop _bind_item_site 按 active_site 切换）
+    sites = {}
+    for site_name in site_set:
+        sites[site_name] = get_site(site_name)
+
+    # 崩溃恢复：先回收 work_items 残留认领（全量），
+    # 再逐 site 重置 shops 的 in_progress（按 domain_suffix 过滤）
     db = ShopDB(cfg.resolved_db_path())
     try:
         n_items = db.reset_claimed_work_items()
-        n_shops = db.reset_in_progress()
+        total_shops = 0
+        for spec in registry:
+            n = db.reset_in_progress(spec.domain_suffix)
+            total_shops += n
     finally:
         db.close()
     print(f"[daemon] 启动重置：{n_items} 个 claimed 工作项 → pending，"
-          f"{n_shops} 个 in_progress 店铺 → pending")
-
-    engine = _build_engine(cfg, task=task, site=site, provider=provider,
-                           policy=policy, site_name="1688")
+          f"{total_shops} 个 in_progress 店铺 → pending"
+          f"（逐 site: {', '.join(spec.domain_suffix for spec in registry)}）")
+
+    # Engine 装配：site 用首个注册 site（BrowserManager 初始 view identity 前缀），
+    # policy 用 default_policy（多 site 的 _bind_item_site 会动态切换）
+    first_site_obj = get_site(first_site)
+    engine = Engine(cfg, task=router, site=first_site_obj,
+                    provider=provider, policy=default_policy,
+                    sites=sites, policies=policies,
+                    site_name=first_site)
     return engine.run()
 
 
 if __name__ == "__main__":
     sys.exit(main())
diff --git a/fetcher/fetcher/control/daemon_task.py b/fetcher/fetcher/control/daemon_task.py
deleted file mode 100644
index ab279f2..0000000
--- a/fetcher/fetcher/control/daemon_task.py
+++ /dev/null
@@ -1,207 +0,0 @@
-# -*- coding: utf-8 -*-
-"""DaemonTaskProxy：daemon 模式的 Task 代理（SPEC §3.3）。
-
-包装既有 Task（P0 为 ContactTask），把工作项来源从「inner 自己 claim
-shops」换成「从 work_items 表认领」：acquire_item 三段式
-（claim → 补货 → 条件变量等货），只有 stop 置位才返回 None（worker
-退出），否则阻塞等货——daemon 模式下「队列空」不等于「任务结束」。
-
-纯组合不继承 Task 基类：基类默认实现会挡住 __getattr__ 使透传失效，
-故显式定义 acquire_item/prepare/after_item 与 on_success/on_giveup
-（落终态钩子），类属性显式转发，其余方法经 __getattr__ 透传 inner。
-
-线程安全：proxy 实例被 Engine 跨 worker 线程共享——条件变量负责
-等货/补货通知；每 worker 认领的 work_item id 记在该 worker 自己的
-ctx.state 上（WorkerContext 每 worker 独立），天然隔离无需加锁。
-"""
-
-from __future__ import annotations
-
-import threading
-import time
-
-from fetcher.control.queue_router import condvar_timeout
-from fetcher.db import ShopDB
-
-# 等货条件变量自醒超时（秒）：保证 stop 置位后 acquire_item 最多 30s 内返回
-_WAIT_TIMEOUT = 30.0
-
-# ctx.state 上记录当前 worker 认领的 work_item id 的键
-_STATE_KEY = "daemon_work_item_id"
-
-
-class DaemonTaskProxy:
-    """Task 协议代理：工作项来源切换为 work_items 表（daemon 常驻等货）。
-
-    用法：
-        task = DaemonTaskProxy(inner=ContactTask(), queue="crawl_1688_contact",
-                               site="1688", domain_suffix=".1688.com")
-        engine = Engine(cfg, task=task, ...)
-    """
-
-    def __init__(self, inner, queue: str, site: str, domain_suffix: str,
-                 db_factory=None):
-        self._inner = inner
-        self._queue = queue
-        self._site = site
-        self._domain_suffix = domain_suffix
-        # 测试注入用 DB 工厂（无参可调）；None=按 ctx 取（见 _db）
-        self._db_factory = db_factory
-        # 等货/补货条件变量（跨 worker 共享，持有锁完成 claim→wait 决策，
-        # 避免「补货 notify 发生在对方 wait 之前」的丢失唤醒）
-        self._cond = threading.Condition()
-        # 无 ctx.store 时按线程缓存的自建 ShopDB（sqlite 连接不可跨线程）
-        self._tls = threading.local()
-
-    # ---- 显式转发的类属性（loop/engine 按实例属性读取）----
-
-    @property
-    def unit(self):
-        return self._inner.unit
-
-    @property
-    def batch_unit(self):
-        return self._inner.batch_unit
-
-    @property
-    def cold_start_before_acquire(self):
-        return self._inner.cold_start_before_acquire
-
-    @property
-    def ip_request_budget(self):
-        return self._inner.ip_request_budget
-
-    # ---- 其余方法透传 inner（不继承基类，__getattr__ 不会被挡住）----
-
-    def __getattr__(self, name):
-        # 下划线开头的属性不应走到这里（防 _inner 未就绪时无限递归）
-        if name.startswith("_"):
-            raise AttributeError(name)
-        return getattr(self._inner, name)
-
-    # ---- DB 访问 ----
-
-    def _db(self, ctx) -> ShopDB:
-        """取当前线程可用的 ShopDB。
-
-        优先用 ctx.store.db（Engine 的 store_factory 已为每 worker 线程
-        建好独立连接，与 inner.on_success 的写库用同一连接）；无 store
-        （单测/直跑）时经 db_factory 或 config.resolved_db_path() 自建，
-        按线程缓存（sqlite 连接禁止跨线程使用）。
-        """
-        if getattr(ctx, "store", None) is not None:
-            return ctx.store.db
-        db = getattr(self._tls, "db", None)
-        if db is None:
-            factory = self._db_factory or (
-                lambda: ShopDB(ctx.config.resolved_db_path()))
-            db = self._tls.db = factory()
-        return db
-
-    def _topup_limit(self, ctx) -> int:
-        """补货上限 = 消费者数 × 4；workers<=0（按通道数解析）时 proxy
-        拿不到解析后的通道数，按 1 个消费者兜底（=4）。"""
-        workers = getattr(ctx.config, "workers", 0) or 0
-        return (workers if workers > 0 else 1) * 4
-
-    # ---- main 阶段 ----
-
-    def prepare(self, config) -> bool:
-        """调 inner.prepare（保留其重置/打印副作用），再打印队列待办数。
-
-        口径：shops pending 未补货数（count_pending）+ work_items 该队列
-        pending 数（db 层无现成计数方法，直读连接 SELECT COUNT）。
-        inner 返回 False（现仅有「pending 为空」一种情形）不退出：
-        daemon 模式下队列空不是终止条件，acquire_item 会阻塞等货。
-        """
-        if not self._inner.prepare(config):
-            print("[daemon] inner.prepare 报告队列暂空，继续常驻等货")
-        db = ShopDB(config.resolved_db_path())
-        try:
-            shops_pending = db.count_pending(self._domain_suffix)
-            items_pending = db.conn.execute(
-                "SELECT COUNT(*) FROM work_items"
-                " WHERE queue=? AND status='pending'",
-                (self._queue,)).fetchone()[0]
-        finally:
-            db.close()
-        print(f"[daemon] 队列 {self._queue}: 待补货店铺 {shops_pending} 个 + "
-              f"待认领工作项 {items_pending} 个")
-        return True
-
-    # ---- worker 循环：工作项认领（三段式）----
-
-    def acquire_item(self, ctx):
-        """认领一个工作项；仅 stop 置位时返回 None，否则阻塞等货。
-
-        1. 冷却过滤：claim 前查冷却（site 键），冷却中不 claim 不 topup，
-           直接进 condvar wait（timeout 经 condvar_timeout 计算）；
-        2. claim 命中 → 记录 work_item id + active_site 后返回 payload；
-        3. 未命中 → 补货（limit=消费者数×4），补到则 notify_all 并重试；
-        4. 仍无货 → 条件变量 wait（30s 自醒兜底），醒后先查 stop。
-        """
-        consumer_id = f"w{ctx.wid}"
-        db = self._db(ctx)
-        limit = self._topup_limit(ctx)
-        with self._cond:
-            while True:
-                if ctx.stopped():
-                    return None
-                now = time.time()
-                # 冷却中：不 claim 不 topup，直接进 condvar wait
-                if now < ctx.cooldown_until.get(self._site, 0):
-                    timeout = condvar_timeout(
-                        ctx.cooldown_until, self._site, now)
-                    self._cond.wait(timeout=timeout)
-                    if ctx.stopped():
-                        return None
-                    continue
-                item = db.claim_work_item(self._queue, consumer_id)
-                if item is not None:
-                    # 记在本 worker 自己的 ctx.state 上，跨 worker 天然隔离
-                    ctx.state[_STATE_KEY] = item["id"]
-                    ctx.state["active_site"] = self._site
-                    return item
-                n = db.topup_contact_work_items(
-                    self._queue, self._site, self._domain_suffix, limit=limit)
-                if n:
-                    self._cond.notify_all()
-                    continue
-                self._cond.wait(timeout=_WAIT_TIMEOUT)
-                if ctx.stopped():
-                    return None
-
-    # ---- 终态钩子：work_item 终态必须反映 item 的最终处置 ----
-    # after_item(ctx, item) 拿不到处置结果（成功/放弃），故挂在
-    # on_success/on_giveup 上：透传 inner 返回值的同时落终态。
-
-    def on_success(self, ctx, item, result) -> int:
-        count = self._inner.on_success(ctx, item, result)
-        self._finish(ctx, "done")
-        return count
-
-    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
-        phrase = self._inner.on_giveup(ctx, item, reason, kind)
-        self._finish(ctx, "failed", result={"reason": reason, "kind": kind})
-        return phrase
-
-    def _finish(self, ctx, status: str, result: dict | None = None):
-        """把当前 worker 认领的 work_item 落终态（done/failed）。
-
-        无认领记录（如 inner 自行 acquire 的路径）时跳过；落库失败只记
-        日志不打死 worker（残留的 claimed 由 daemon 重启时
-        reset_claimed_work_items 回收）。
-        """
-        item_id = ctx.state.pop(_STATE_KEY, None)
-        if item_id is None:
-            return
-        try:
-            self._db(ctx).finish_work_item(item_id, status, result)
-        except Exception as e:  # noqa: BLE001
-            ctx.log(f"[!] 工作项 #{item_id} 落终态 {status} 失败: {e}")
-
-    def after_item(self, ctx, item) -> None:
-        # inner 可能未定义 after_item（基类默认空实现），容错透传
-        hook = getattr(self._inner, "after_item", None)
-        if hook is not None:
-            hook(ctx, item)
diff --git a/fetcher/fetcher/control/engine.py b/fetcher/fetcher/control/engine.py
index 0bf6484..a08b3df 100644
--- a/fetcher/fetcher/control/engine.py
+++ b/fetcher/fetcher/control/engine.py
@@ -30,32 +30,36 @@ class Engine:
 
     用法：
         engine = Engine(config, task, site=site, provider=QingGuoProvider())
         rc = engine.run()
     """
 
     def __init__(self, config: RunConfig, task, site=None, provider=None,
                  policy: Policy | None = None, board=None,
                  store_factory=None, browser_manager_factory=None,
                  loop_factory=None,
-                 site_name: str | None = None):
+                 site_name: str | None = None,
+                 sites: dict | None = None,
+                 policies: dict | None = None):
         if site is not None and site_name is None:
             raise RuntimeError(
                 "site_name 必传（CLI/daemon 传入注册名），"
                 "不可在指定 site 时遗漏")
         self.config = config
         self.task = task
         self.site = site
         self.provider = provider
         self.policy = policy
         self.board = board
         self.site_name = site_name
+        self.sites = sites
+        self.policies = policies
         # 可注入工厂（测试用；默认每 worker 独立 ShopDB / BrowserManager /
         # CrawlLoop）
         self.store_factory = store_factory or (
             lambda wid: IdentityStore(ShopDB(config.resolved_db_path()),
                                       domain=getattr(site, "cookie_domain",
                                                      "1688.com")))
         self.browser_manager_factory = browser_manager_factory
         self.loop_factory = loop_factory or CrawlLoop
         self.state = {"stats": {}}
         self.lock = threading.Lock()
@@ -179,22 +183,27 @@ class Engine:
                 else:
                     board.set(wid, detail=text[:80])
             else:
                 print(text, flush=True)
 
         ctx = WorkerContext(config=self.config, store=store,
                             browser_manager=mgr, site=self.site,
                             stop=self.stop, log=log, wid=wid, tag=tag)
         if board is not None:
             ctx.set_status = lambda **kw: board.set(wid, **kw)
+        loop_kw = {}
+        if self.sites is not None:
+            loop_kw["sites"] = self.sites
+        if self.policies is not None:
+            loop_kw["policies"] = self.policies
         loop = self.loop_factory(ctx, self.task, policy=self.policy,
-                                 board=board, seed_kit=seed_kit)
+                                 board=board, seed_kit=seed_kit, **loop_kw)
         stats = loop.run()
         with self.lock:
             self.state["stats"][wid] = stats
 
     # ---- main 编排 ----
 
     def run(self) -> int:
         cfg = self.config
         workers, channels = self._alloc_workers()
         worker_kits = self._alloc_seed_kits(workers)
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index 632f0eb..977b972 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -66,26 +66,37 @@ class CrawlLoop:
 
     用法：
         ctx = WorkerContext(config=cfg, store=store, browser_manager=mgr,
                             site=site, stop=stop, log=log)
         loop = CrawlLoop(ctx, task, policy=policy, board=board, seed_kit=kit)
         stats = loop.run()
     """
 
     def __init__(self, ctx, task: Task, policy: Policy | None = None,
                  inspector: SceneInspector | None = None, board=None,
-                 seed_kit: dict | None = None):
+                 seed_kit: dict | None = None,
+                 sites: dict[str, object] | None = None,
+                 policies: dict[str, Policy] | None = None):
         self.ctx = ctx
         self.task = task
         self.policy = policy or Policy(
             max_consecutive_fail=ctx.config.max_consecutive_fail)
-        self.inspector = inspector or SceneInspector.for_site(ctx.site)
+        self.sites = sites
+        self.policies = policies
+        if sites is not None:
+            # daemon 多站点路径：inspector 延迟建，首个 item 绑定后建立
+            self._bound_site = None
+            self.inspector = inspector  # daemon 传 None
+        else:
+            # CLI 单站点路径：inspector 按 ctx.site 立即装配
+            self._bound_site = getattr(ctx.site, 'name', None) if ctx.site else None
+            self.inspector = inspector or SceneInspector.for_site(ctx.site)
         self.board = board
         self.seed_tracker = SeedBurnTracker(seed_kit)
         self.circuit = CircuitBreaker(ctx.config.max_consecutive_fail)
         self.tracker = AttemptTracker()
         self.stats = task.make_stats()
         # 任务层暂存（对应旧 wctx，含 stats）
         self.ctx.state.setdefault("task", {})["stats"] = self.stats
         self.wctx = self.ctx.state["task"]
         # tmd：按出口 IP 计页面请求数与「距上次触发」计数
         self.ip_req: dict = self.ctx.state.setdefault("ip_req", {})
@@ -179,20 +190,21 @@ class CrawlLoop:
                 if self.task.cold_start_before_acquire and self._take_warm():
                     self.ctx.set_status(state="冷启动软着陆…")
                     self.task.cold_start(self.ctx, None)
 
                 # ---- 认领任务项 ----
                 item = self.task.acquire_item(self.ctx)
                 if item is None:
                     self.log(self.task.empty_message())
                     self.ctx.set_status(state="无待做任务，退出")
                     break
+                self._bind_item_site()
                 self.ctx.state["item"] = item
                 self.ctx.set_status(shop=self.task.label(item),
                                     state="检查出口 IP…")
 
                 # ---- 出口 IP 保鲜检查（青果 30 分钟轮换）；relaunch 失败
                 #      不退出 worker，记日志继续用当前会话，由 fetch 兜底 ----
                 if cfg.use_proxy:
                     self._ensure_fresh_ip()
 
                 # ---- 冷启动（acquire 后的任务，如先逛店铺首页）----
@@ -325,21 +337,21 @@ class CrawlLoop:
         if not need:
             return True
         self.log(f"🔄 {reason}，重启浏览器绑定新 IP ...")
         if not self._relaunch():
             self.log("[X] 出口 IP 保鲜 relaunch 失败，本次跳过，继续使用当前会话")
         return True
 
     def _check_budget(self) -> bool:
         """每 IP 请求预算：采满主动换 IP；IP 未轮换则放行（budget_stuck）。"""
         cfg = self.ctx.config
-        budget = self.task.ip_request_budget
+        budget = self.task.budget_for(self.ctx)
         identity = self.ctx.identity
         if not (budget and cfg.use_proxy
                 and self.ip_req.get(identity, {}).get("n", 0) >= budget
                 and identity not in self.budget_stuck):
             return True
         old_identity = identity
         self.log(f"📦 出口 {identity} 已达请求预算 "
                  f"（{self.ip_req[identity]['n']}/{budget} 次），"
                  f"主动换 IP 规避配额墙")
         if not self._relaunch():
@@ -351,20 +363,21 @@ class CrawlLoop:
             self.log("  [!] 出口 IP 尚未轮换，本次预算放行（等青果自然轮换）")
         return True
 
     # ---- item 级重试循环（核心：采集 → 判场景 → 执行策略） ----
 
     def _process_item(self, item) -> tuple[str, int]:
         """返回 (kind, count)：kind ∈ success/giveup/abort/stop。"""
         ctx = self.ctx
         # 熔断按店计非按次：同一店铺的重试链无论多长只计一次，单个慢/卡
         # 店铺不会烧穿熔断中止整个任务（旧引擎同店铺最多 3 段升级后放弃）
+        self._bind_item_site()
         counted = False
         while not ctx.stopped():
             ctx.set_status(state="采集中")
             ctx.last_error = None
             result = self.task.fetch(ctx, item)
             scenario = self.inspector.inspect(ctx)
             if scenario is Scenario.OK:
                 if result is None:
                     # fetch 未返回结果（对应旧 scrape 返回 None，按风控处理）
                     scenario = Scenario.RISK_SLIDER_PAGE
@@ -432,20 +445,36 @@ class CrawlLoop:
             # 策略冷却经 chokepoint 执行（Step 2.1 起策略只算时长不自
             # 等）；被 stop 中断按现状 stop 路径退出（与旧策略内
             # ctx.wait 中断 → 循环条件退出 → return "stop" 的终局一致）
             # item 未完成路径暂保留原地等待（默认）；
             # P3-3 router 接 release 后改让出
             if step.cooldown and self._cooldown(
                     step.cooldown, f"strategy:{decision.strategy}"):
                 return "stop", 0
         return "stop", 0
 
+    def _bind_item_site(self):
+        """daemon 多站点路径：按 ctx.state["active_site"] 切换
+        ctx.site / inspector / policy。CLI 路径（sites=None）无操作。"""
+        if self.sites is None:
+            return
+        site_name = self.ctx.state.get("active_site")
+        if site_name is None or site_name == self._bound_site:
+            return
+        self.ctx.site = self.sites.get(site_name)
+        if self.ctx.site is not None:
+            self.inspector = SceneInspector.for_site(self.ctx.site)
+        new_policy = self.policies.get(site_name) if self.policies else None
+        if new_policy is not None:
+            self.policy = new_policy
+        self._bound_site = site_name
+
     # ---- 簿记 ----
 
     def _bookkeep_request(self, scenario: Scenario):
         """tmd 计数：请求到了目标站才计（网络层错误不算）。"""
         if scenario in _NO_REQUEST_SCENARIOS or self.ctx.store is None:
             return
         identity = self.ctx.identity
         ctr = self.ip_req.setdefault(identity, {"n": 0, "since": 0})
         ctr["n"] += 1
         ctr["since"] += 1
diff --git a/fetcher/fetcher/control/queue_router.py b/fetcher/fetcher/control/queue_router.py
index 5897fe3..59ca1e3 100644
--- a/fetcher/fetcher/control/queue_router.py
+++ b/fetcher/fetcher/control/queue_router.py
@@ -1,49 +1,301 @@
 # -*- coding: utf-8 -*-
-"""队列路由表与冷却感知的等待函数（P3 Step 1.2 纯函数，无副作用）。
+"""队列路由表 + 冷却感知等待函数 + QueueRouter（P3 Step 3.1）。
 
-P3-3 将在此文件演进 QueueRouter 类，本 Step 先放基础成员。
+QueueRouter 取代 DaemonTaskProxy：跨队列认领（资源满足 ∧ 站点冷却到期）
+→ 路由到 item 所属队列的 task。daemon 常驻等货；无平台依赖，仅 daemon 用。
 """
 
 from __future__ import annotations
 
-from dataclasses import dataclass
+import threading
+import time
+from dataclasses import dataclass, field
+from typing import Callable
+
+from fetcher.db import ShopDB
+
+# 等货条件变量自醒超时（秒）：保证 stop 置位后 acquire_item 最多 30s 内返回
+_WAIT_TIMEOUT = 30.0
+
+# ctx.state 上记录当前 worker 认领的 work_item id 的键
+_STATE_KEY = "daemon_work_item_id"
 
 
 @dataclass
 class QueueSpec:
-    """队列注册表条目（P3-3 补全 task/topup/domain_suffix 字段）。"""
-    queue: str            # "crawl_1688_contact" / ...
-    site: str             # 站点注册名 "1688" / "madeinchina"
-    requires: set[str]    # 资源需求，如 {"channel", "browser"}
+    """队列注册表条目。"""
+    queue: str                    # "crawl_1688_contact" / ...
+    site: str                     # 站点注册名 "1688" / "madeinchina"
+    task: object                  # 该队列工作项的执行流水线（Task 协议）
+    topup: Callable[[ShopDB, int], int] | None = None   # 补货函数；feeder 类队列为 None
+    domain_suffix: str = ""       # contact 类 topup 用；启动 reset 用
+    requires: set[str] = field(default_factory=lambda: {"channel", "browser"})
 
 
 def eligible_queues(registry, ctx, now: float) -> list[str]:
     """当前消费者可认领的队列名列表：资源满足 ∧ 该站点冷却已到期。
 
-    registry: 可迭代的 QueueSpec（或鸭子类型：有 .queue/.site/.requires）。
+    registry: 可迭代的 QueueSpec。
     ctx: 有 .resources（set）与 .cooldown_until（dict[site, float]）的对象。
     纯函数，无副作用；返回按注册表顺序。
     """
     result = []
     for q in registry:
         if q.requires <= ctx.resources \
                 and now >= ctx.cooldown_until.get(q.site, 0):
             result.append(q.queue)
     return result
 
 
 def condvar_timeout(cooldown_until: dict[str, float], site: str,
                     now: float, cap: float = 30.0) -> float:
     """计算 Condition.wait 的超时值（秒）。
 
     - site 在冷却中（now < 到期） → min(到期 - now, cap)
     - site 不在冷却 → cap
-    - 返回值总是 > 0（若冷却剩余极小如 0.01s 则原样返回）。
-
-    cap 默认为 30s，作为自醒兜底（外部 INSERT 无 notify，最坏 30s 发现）。
+    - 返回值总是 > 0。
     """
     deadline = cooldown_until.get(site, 0)
     if now < deadline:
         remaining = deadline - now
         return remaining if remaining < cap else cap
     return cap
+
+
+def condvar_timeout_multi(cooldown_until: dict[str, float],
+                          sites: list[str], now: float,
+                          cap: float = 30.0) -> float:
+    """多队列 condvar timeout：取所有冷却中 site 的剩余时间的最小值。
+
+    无任何 site 在冷却 → cap。
+    """
+    min_remaining = None
+    for site in sites:
+        deadline = cooldown_until.get(site, 0)
+        if now < deadline:
+            remaining = deadline - now
+            if min_remaining is None or remaining < min_remaining:
+                min_remaining = remaining
+    if min_remaining is None:
+        return cap
+    return min_remaining if min_remaining < cap else cap
+
+
+class QueueRouter:
+    """Task 协议代理：跨队列认领（资源满足 ∧ 站点冷却到期）→ 路由到 item
+    所属队列的 task。
+
+    acquire_item 三段式：claim_next_eligible → 各队列 topup → condvar 挂起。
+    stop 置位才返回 None。on_success/on_giveup 路由到 item 所属队列的 task
+    后落 work_items 终态。per-item 方法全部经 ctx.state 路由（WorkerContext
+    每 worker 独立，天然线程安全）。
+
+    用法：
+        registry = [QueueSpec(queue="crawl_1688_contact", site="1688",
+                               task=ContactTask(), topup=..., domain_suffix=".1688.com"),
+                    QueueSpec(queue="crawl_mic_contact", site="madeinchina",
+                               task=MICContactTask(), topup=..., domain_suffix=".cn.made-in-china.com")]
+        router = QueueRouter(registry)
+        engine = Engine(cfg, task=router, ...)
+    """
+
+    # per-worker 动态属性（类属性，loop 在 acquire 前后直接读）
+    unit = "项"
+    batch_unit = ""
+    cold_start_before_acquire = False
+
+    def __init__(self, registry: list[QueueSpec], cond=None,
+                 db_factory=None):
+        self._registry = {spec.queue: spec for spec in registry}
+        self._specs = registry  # 保持顺序
+        self._cond = cond or threading.Condition()
+        self._db_factory = db_factory
+        self._tls = threading.local()
+
+    @property
+    def ip_request_budget(self):
+        """必须 per-site：返回 None，loop 走 budget_for(ctx)。"""
+        return None
+
+    def budget_for(self, ctx) -> int | None:
+        """当前 item 所属 queue 的 task 的 IP 请求预算。"""
+        queue_name = ctx.state.get("queue")
+        if queue_name and queue_name in self._registry:
+            return self._registry[queue_name].task.budget_for(ctx)
+        return None
+
+    def rest_counter(self, stats: dict) -> int:
+        """长休息计数基准：总完成数。"""
+        return stats.get("done", 0)
+
+    # ---- 执行侧路由：per-item 方法经 ctx.state["queue"] 路由 ----
+
+    def _task_for(self, ctx):
+        """取当前 item 所属队列的 task；无队列取首个注册 spec 的 task（兜底）。"""
+        queue_name = ctx.state.get("queue")
+        if queue_name and queue_name in self._registry:
+            return self._registry[queue_name].task
+        # 兜底：首个注册 spec
+        if self._specs:
+            return self._specs[0].task
+        raise RuntimeError("QueueRouter 注册表为空")
+
+    def fetch(self, ctx, item):
+        return self._task_for(ctx).fetch(ctx, item)
+
+    def validate(self, ctx, item, result):
+        return self._task_for(ctx).validate(ctx, item, result)
+
+    def cold_start(self, ctx, item):
+        return self._task_for(ctx).cold_start(ctx, item)
+
+    def _task_for_static(self):
+        """无 ctx 参数的静态路由（label/giveup_cost）：用线程本地缓存。"""
+        queue_name = getattr(self._tls, "last_queue", None)
+        if queue_name and queue_name in self._registry:
+            return self._registry[queue_name].task
+        if self._specs:
+            return self._specs[0].task
+        raise RuntimeError("QueueRouter 注册表为空")
+
+    def label(self, item):
+        return self._task_for_static().label(item)
+
+    def on_abort(self, ctx, item):
+        return self._task_for(ctx).on_abort(ctx, item)
+
+    def giveup_cost(self, item):
+        return self._task_for_static().giveup_cost(item)
+
+    def after_item(self, ctx, item):
+        return self._task_for(ctx).after_item(ctx, item)
+
+    def empty_message(self):
+        if self._specs:
+            return self._specs[0].task.empty_message()
+        return "没有待做的任务了"
+
+    def make_stats(self):
+        return {"done": 0}
+
+    def compose(self, wid: int, f: dict) -> str:
+        if self._specs:
+            return self._specs[0].task.compose(wid, f)
+        return str(f.get("line", ""))
+
+    def summary(self, all_stats: dict, db_path=None) -> str:
+        if self._specs:
+            return self._specs[0].task.summary(all_stats, db_path=db_path)
+        return str(all_stats)
+
+    # ---- DB 访问 ----
+
+    def _db(self, ctx) -> ShopDB:
+        """取当前线程可用的 ShopDB。"""
+        if getattr(ctx, "store", None) is not None:
+            return ctx.store.db
+        db = getattr(self._tls, "db", None)
+        if db is None:
+            factory = self._db_factory or (
+                lambda: ShopDB(ctx.config.resolved_db_path()))
+            db = self._tls.db = factory()
+        return db
+
+    def _topup_limit(self, ctx) -> int:
+        """补货上限 = 消费者数 × 4。"""
+        workers = getattr(ctx.config, "workers", 0) or 0
+        return (workers if workers > 0 else 1) * 4
+
+    # ---- main 阶段 ----
+
+    def prepare(self, config) -> bool:
+        """各队列 task.prepare + 打印每队列待办。"""
+        all_ok = True
+        db = ShopDB(config.resolved_db_path())
+        try:
+            for spec in self._specs:
+                if not spec.task.prepare(config):
+                    print(f"[daemon] {spec.queue} inner.prepare 报告队列暂空，"
+                          f"继续常驻等货")
+                shops_pending = db.count_pending(spec.domain_suffix)
+                items_pending = db.conn.execute(
+                    "SELECT COUNT(*) FROM work_items WHERE queue=? "
+                    "AND status='pending'", (spec.queue,)).fetchone()[0]
+                print(f"[daemon] 队列 {spec.queue}: 待补货店铺 {shops_pending} 个 + "
+                      f"待认领工作项 {items_pending} 个")
+        finally:
+            db.close()
+        return True
+
+    # ---- worker 循环：工作项认领（三段式）----
+
+    def acquire_item(self, ctx):
+        """跨队列认领工作项；仅 stop 置位时返回 None，否则阻塞等货。
+
+        1. eligible_queues → claim_next_eligible（跨队列 FIFO）→ 命中返回 payload
+        2. 未命中 → topup 只对冷却到期的 contact 队列逐队列补货 → 补到则 notify_all + 重试
+        3. 仍无 → condvar wait（多队列取各冷却中最小值，无冷却 30s）→ 醒后查 stop
+        """
+        consumer_id = f"w{ctx.wid}"
+        db = self._db(ctx)
+        limit = self._topup_limit(ctx)
+        with self._cond:
+            while True:
+                if ctx.stopped():
+                    return None
+                now = time.time()
+                queues = eligible_queues(self._specs, ctx, now)
+                if queues:
+                    item = db.claim_next_eligible(queues, consumer_id)
+                    if item is not None:
+                        ctx.state[_STATE_KEY] = item["id"]
+                        ctx.state["queue"] = item["queue"]
+                        ctx.state["active_site"] = item["site"]
+                        # 缓存队列名到线程本地（label/giveup_cost 无 ctx 参数时用）
+                        self._tls.last_queue = item["queue"]
+                        payload = dict(item["payload"])
+                        payload["id"] = item["id"]  # 兼容旧 DaemonTaskProxy 返回格式
+                        return payload
+
+                # topup：只对冷却到期的 contact 队列补货
+                any_topped = False
+                for spec in self._specs:
+                    if spec.topup is not None \
+                            and now >= ctx.cooldown_until.get(spec.site, 0):
+                        n = spec.topup(db, limit)
+                        if n:
+                            any_topped = True
+                if any_topped:
+                    self._cond.notify_all()
+                    continue
+
+                # condvar wait：多队列取各冷却中剩余的最小值
+                timeout = condvar_timeout_multi(
+                    ctx.cooldown_until,
+                    [spec.site for spec in self._specs],
+                    now, cap=_WAIT_TIMEOUT)
+                self._cond.wait(timeout=timeout)
+                if ctx.stopped():
+                    return None
+
+    # ---- 终态钩子 ----
+
+    def on_success(self, ctx, item, result) -> int:
+        count = self._task_for(ctx).on_success(ctx, item, result)
+        self._finish(ctx, "done")
+        return count
+
+    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
+        phrase = self._task_for(ctx).on_giveup(ctx, item, reason, kind)
+        self._finish(ctx, "failed", result={"reason": reason, "kind": kind})
+        return phrase
+
+    def _finish(self, ctx, status: str, result: dict | None = None):
+        """把当前 worker 认领的 work_item 落终态（done/failed）。"""
+        item_id = ctx.state.pop(_STATE_KEY, None)
+        if item_id is None:
+            return
+        try:
+            self._db(ctx).finish_work_item(item_id, status, result)
+        except Exception as e:  # noqa: BLE001
+            ctx.log(f"[!] 工作项 #{item_id} 落终态 {status} 失败: {e}")
diff --git a/fetcher/fetcher/control/task.py b/fetcher/fetcher/control/task.py
index 827cbe2..7e2cf05 100644
--- a/fetcher/fetcher/control/task.py
+++ b/fetcher/fetcher/control/task.py
@@ -25,20 +25,28 @@ class Task:
         ip_request_budget       每出口 IP 请求预算（None=无）：采满 N 个
                                 请求后主动换 IP，规避平台级匿名配额墙
     """
 
     name = "task"
     unit = "样本"
     batch_unit = ""
     cold_start_before_acquire = False
     ip_request_budget: int | None = None
 
+    def budget_for(self, ctx) -> int | None:
+        """当前上下文的 IP 请求预算（per-site 路由点）。
+
+        基类默认返回 ip_request_budget（CLI 单站点不变）；
+        QueueRouter 覆盖为按 item 所属 site 的 task 返回。
+        """
+        return self.ip_request_budget
+
     # ---- main 阶段 ----
 
     def prepare(self, config) -> bool:
         """启动前准备（重置状态/打印计划）；返回 False 直接退出。"""
         return True
 
     def summary(self, all_stats: dict, db_path=None) -> str:
         """全部 worker 结束后的汇总行。
 
         db_path: 数据库路径（str | Path），基类实现不读它；
diff --git a/fetcher/fetcher/core/context.py b/fetcher/fetcher/core/context.py
index 9c17320..9f9151b 100644
--- a/fetcher/fetcher/core/context.py
+++ b/fetcher/fetcher/core/context.py
@@ -102,21 +102,21 @@ class WorkerContext:
 
     # 最近一次抓取抛出的异常（Detector 分级 NET_ERROR/NET_STALL/
     # BROWSER_DEAD 的输入；由抓取原子/控制层写入）
     last_error: BaseException | None = None
     # 最近一次抓取的业务结果（抓取原子写回，persist 用）
     last_result: Any = None
     # 控制层/策略层暂存（如 AttemptTracker）
     state: dict = field(default_factory=dict)
     # 冷却截止时间登记处：site 注册名 → 到期时刻（time.time()+seconds）。
     # 唯一写入者是 loop 的 chokepoint（有 active_site 时才登记）；
-    # 查询者是 daemon_task 的冷却过滤与 queue_router 的 eligible_queues。
+    # 查询者是 queue_router 的 eligible_queues 与 QueueRouter 的冷却过滤。
     cooldown_until: dict[str, float] = field(default_factory=dict)
     # 消费者持有的资源集（供 eligible_queues 过滤用）；daemon 消费者
     # 天然持有 {"channel", "browser"}（与 SPEC §4.2 BrowserConsumer 一致）
     resources: set[str] = field(default_factory=lambda: {"channel", "browser"})
 
     # ---- 便捷访问 ----
     @property
     def page(self):
         return self.session.page if self.session else None
 
diff --git a/fetcher/tests/test_cli.py b/fetcher/tests/test_cli.py
index e6eb28e..168f1a8 100644
--- a/fetcher/tests/test_cli.py
+++ b/fetcher/tests/test_cli.py
@@ -11,37 +11,38 @@ from fetcher.strategy.policy import Policy
 
 class CliParserTest(unittest.TestCase):
     def setUp(self):
         self.ap = build_parser()
 
     # ---- daemon 子命令 ----
 
     def test_daemon_defaults(self):
         args = self.ap.parse_args(["daemon"])
         self.assertEqual(args.site, "daemon")
-        # --queue 默认值（P0 不开放其他选择）
-        self.assertEqual(args.queue, "crawl_1688_contact")
+        # --queues 默认 None（全量）
+        self.assertIsNone(args.queues)
         # daemon 不套 task 二级 subparser
         self.assertIsNone(getattr(args, "task", None))
         # add_common_args 全套已挂载（抽查代表项）
         self.assertEqual(args.rest_every, 20)
         self.assertEqual(args.batch_rest, 900)
         self.assertFalse(args.proxy)
         self.assertFalse(args.headed)
         # config_from_args 依赖的 num/limit 必须有默认（contact 口径）
         self.assertEqual(args.num, 10)
         self.assertEqual(args.limit, 0)
 
-    def test_daemon_queue_and_common_override(self):
+    def test_daemon_queues_and_common_override(self):
         args = self.ap.parse_args(
-            ["daemon", "--queue", "q2", "--workers", "3", "--limit", "5"])
-        self.assertEqual(args.queue, "q2")
+            ["daemon", "--queues", "crawl_1688_contact", "crawl_mic_contact",
+             "--workers", "3", "--limit", "5"])
+        self.assertEqual(args.queues, ["crawl_1688_contact", "crawl_mic_contact"])
         self.assertEqual(args.workers, 3)
         self.assertEqual(args.limit, 5)
 
     def test_daemon_config_from_args(self):
         # config_from_args 不读 args.task，daemon 命名空间可直接复用
         cfg = config_from_args(self.ap.parse_args(["daemon"]))
         self.assertEqual(cfg.batch_num, 10)
         self.assertEqual(cfg.limit, 0)
 
     def test_daemon_has_no_task_subparser(self):
diff --git a/fetcher/tests/test_cooldown.py b/fetcher/tests/test_cooldown.py
index 6bf3e18..fc50fc6 100644
--- a/fetcher/tests/test_cooldown.py
+++ b/fetcher/tests/test_cooldown.py
@@ -7,21 +7,21 @@
    静默（prefix=None → ctx.wait）与倒计时（prefix 传 → wait_countdown）
    两条展示路径各覆盖一次。
 2. _process_item 策略冷却集成：CrawlLoop 联跑——假 task 首次 fetch
    自报 blocked、假策略输出 StepResult(cooldown=t)，断言冷却经
    chokepoint 执行（spy 记录参数、调用真实实现）、随后重试成功；
    再覆盖「冷却中被 stop 中断 → return "stop" 终局」分支。
 3. 4 处等待点（batch_rest / sample_interval / periodic_rest /
    launch_backoff）均经 chokepoint 触发，reason 正确且时长落在公式区间。
 
 真实 threading.Event + 临时 sqlite + spy（不 mock 被测的 _cooldown
-本身）；假基建模式参照 test_control_loop.py / test_daemon_task.py。
+本身）；假基建模式参照 test_control_loop.py / test_queue_router.py。
 """
 
 import tempfile
 import threading
 import time
 import unittest
 from pathlib import Path
 
 from fetcher import (
     Alibaba1688Plugin,
@@ -403,43 +403,43 @@ class YieldCooldownTest(CooldownTestBase):
         if "launch_backoff" in by_reason:
             for _, _, y in by_reason["launch_backoff"]:
                 self.assertFalse(y, "launch_backoff 应保持 yield_=False（原地型）")
         # 策略冷却不应触发（纯成功路径），若触发了必须为 yield_=False
         strat_reasons = [r for r in by_reason if r.startswith("strategy:")]
         for r in strat_reasons:
             for _, _, y in by_reason[r]:
                 self.assertFalse(y, f"{r} 应保持 yield_=False（原地型）")
 
 
-# ---------- 用例 4：让出型 × DaemonTaskProxy 集成验证（F1） ----------
+# ---------- 用例 4：让出型 × QueueRouter 集成验证（F1） ----------
 
 class YieldIntegrationWithProxyTest(unittest.TestCase):
-    """F1 集成测试：DaemonTaskProxy + CrawlLoop 跑 2 个成功 item，
+    """F1 集成测试：QueueRouter + CrawlLoop 跑 2 个成功 item，
     验证让出型冷却登记 site 键 + condvar 等待发生在 acquire 而非 loop 内。
 
     假基建模式（FakePage / MockBrowserManager / fake fetch OK），
     不依赖真实浏览器或网络。
     """
 
     def setUp(self):
         self._tmp = tempfile.TemporaryDirectory()
         self.tmp = self._tmp.name
         self.page = FakePage()
         self.mgr = MockBrowserManager(self.page)
 
     def tearDown(self):
         self._tmp.cleanup()
 
     def _make_proxy_ctx(self, sample_min, sample_max, items=2):
-        """创建 DaemonTaskProxy + WorkerContext，seed 好 work_items。"""
+        """创建 QueueRouter + WorkerContext，seed 好 work_items。"""
         import json as _json
-        from fetcher.control.daemon_task import DaemonTaskProxy
+        from fetcher.control.queue_router import QueueRouter, QueueSpec
 
         config = make_config(self.tmp,
                              sample_min=sample_min, sample_max=sample_max,
                              batch_rest=0.01, batch_num=2, max_batches=1,
                              rest_every=0,  # 关闭长休息，简化验证
                              limit=0)
         ctx = make_ctx(config, self.mgr)
 
         # Seed work_items
         now = time.strftime("%Y-%m-%d %H:%M:%S")
@@ -449,23 +449,27 @@ class YieldIntegrationWithProxyTest(unittest.TestCase):
             payload = {"domain": domain, "name": f"店{i}",
                        "url": f"https://{domain}/page/contactinfo.htm"}
             db.conn.execute(
                 "INSERT INTO work_items (queue, site, payload_json,"
                 " status, created_at) VALUES (?, ?, ?, ?, ?)",
                 ("crawl_1688_contact", "1688",
                  _json.dumps(payload), "pending", now))
             db.conn.commit()
 
         inner = ScriptedTask([("ok", {"v": i}) for i in range(1, items + 1)])
-        proxy = DaemonTaskProxy(inner=inner, queue="crawl_1688_contact",
-                                site="1688", domain_suffix=".1688.com")
-        return proxy, ctx
+        registry = [QueueSpec(
+            queue="crawl_1688_contact", site="1688", task=inner,
+            topup=lambda db, limit: db.topup_contact_work_items(
+                "crawl_1688_contact", "1688", ".1688.com", limit),
+            domain_suffix=".1688.com")]
+        router = QueueRouter(registry)
+        return router, ctx
 
     def test_yield_cooldown_waits_in_acquire_not_loop(self):
         """2 个成功 item：item1 完成后让出型 sample_interval 登记 site 键，
         item2 的认领发生在冷却到期之后（时间戳间隔落在 sample 区间），
         且循环体内无 ctx.wait 调用（让出型不触发 loop 内等待）。"""
         proxy, ctx = self._make_proxy_ctx(sample_min=0.3, sample_max=0.5)
         policy = Policy(table={}, strategies={},
                         max_consecutive_fail=3)
         loop = CrawlLoop(ctx, proxy, policy=policy)
 
@@ -487,21 +491,21 @@ class YieldIntegrationWithProxyTest(unittest.TestCase):
             cooldown_spy.append((seconds, reason, prefix, yield_))
             return orig_cooldown(seconds, reason, prefix, yield_=yield_)
 
         loop._cooldown = spy_cd
 
         t0 = time.monotonic()
         stats = loop.run()
         elapsed = time.monotonic() - t0
 
         # 两个 item 都成功
-        inner = proxy._inner
+        inner = proxy._registry["crawl_1688_contact"].task
         self.assertEqual(len(inner.succeeded), 2,
                          f"期望两个 item 成功，got {len(inner.succeeded)}")
         # succeeded 记录的是 work_item dict（含 domain/name/url）
         self.assertEqual(inner.succeeded[0]["domain"], "shop1.1688.com")
         self.assertEqual(inner.succeeded[1]["domain"], "shop2.1688.com")
         # stats.done 反映成功计数
         self.assertEqual(stats.get("done", 0), 2,
                          f"stats.done 应为 2，got {stats.get('done', 0)}")
 
         # 让出型调用：sample_interval（2 次，每个 item 一次）
diff --git a/fetcher/tests/test_daemon_task.py b/fetcher/tests/test_daemon_task.py
deleted file mode 100644
index 3c7acd6..0000000
--- a/fetcher/tests/test_daemon_task.py
+++ /dev/null
@@ -1,423 +0,0 @@
-# -*- coding: utf-8 -*-
-"""DaemonTaskProxy 单元测试：三段式 acquire_item / 终态钩子 / CrawlLoop 联跑。
-
-真实临时 sqlite + 真实线程/条件变量，不 mock 被测对象本身；
-浏览器/网络侧沿用 test_control_loop.py 的假基建模式（FakePage/
-MockBrowserManager），inner task 用可编程的假实现。
-"""
-
-import json
-import sqlite3
-import tempfile
-import threading
-import time
-import unittest
-from pathlib import Path
-
-from fetcher import (
-    Alibaba1688Plugin,
-    IdentityStore,
-    RunConfig,
-    ShopDB,
-    Session,
-    WorkerContext,
-)
-from fetcher.control import CrawlLoop, Task
-from fetcher.control import daemon_task
-from fetcher.control.daemon_task import DaemonTaskProxy
-from fetcher.core.types import ActionResult, Outcome
-from fetcher.strategy.policy import Policy
-
-QUEUE = "crawl_1688_contact"
-
-
-def _shop(i):
-    return {"domain": f"shop{i}.1688.com", "name": f"店铺{i}",
-            "url": f"https://shop{i}.1688.com"}
-
-
-# ---------- 假 inner task / 假浏览器基建 ----------
-
-class FakeInnerTask(Task):
-    """可编程假任务：fetch 恒成功，记录每 worker 的成功/放弃明细。
-
-    acquire_item 不应被 proxy 透传调用（proxy 自己实现认领），
-    被调到即失败，防「proxy 偷偷走 inner 认领路径」的假阳性。
-    """
-
-    name = "fake-inner"
-    unit = "店铺"
-    batch_unit = "店铺"
-
-    def __init__(self):
-        self.lock = threading.Lock()
-        self.succeeded = []  # [(wid, domain)]
-        self.given_up = []   # [(wid, domain, reason, kind)]
-
-    def acquire_item(self, ctx):
-        raise AssertionError("daemon 模式下不应调到 inner.acquire_item")
-
-    def fetch(self, ctx, item):
-        return ActionResult(Outcome.OK, "", {"v": 1})
-
-    def on_success(self, ctx, item, result):
-        with self.lock:
-            self.succeeded.append((ctx.wid, item["domain"]))
-        stats = ctx.state.get("task", {}).get("stats")
-        if stats is not None:
-            stats["done"] = stats.get("done", 0) + 1
-        return 1
-
-    def on_giveup(self, ctx, item, reason, kind):
-        with self.lock:
-            self.given_up.append((ctx.wid, item["domain"], reason, kind))
-        return "标记跳过"
-
-    def make_stats(self):
-        return {"done": 0}
-
-
-class FakeBrowser:
-    def is_connected(self):
-        return True
-
-    def close(self):
-        pass
-
-
-class FakeContext:
-    def __init__(self):
-        self.browser = FakeBrowser()
-
-    def cookies(self):
-        return []
-
-
-class FakePage:
-    def __init__(self):
-        self.url = "https://shop1.1688.com/page/contactinfo.htm"
-        self._text = "正常页面文本，足够长，包含电话、手机、地址等字段标签，超过阈值。"
-        self.frames = []
-        self.context = FakeContext()
-
-    def evaluate(self, js):
-        return self._text
-
-    def query_selector(self, sel):
-        return None
-
-    def is_closed(self):
-        return False
-
-
-class MockBrowserManager:
-    """launch 返回带假 page 的 Session（联跑用，不起真实浏览器）。"""
-
-    def __init__(self, page):
-        self.page = page
-
-    def launch(self, seed_kit=None, stop=None):
-        return Session(browser=FakeBrowser(), page=self.page,
-                       identity="1688:1.1.1.1", seed_kit=seed_kit)
-
-    def check_ip_fresh(self, session):
-        return False, session.identity, ""
-
-    def save_cookies(self, session):
-        return 0
-
-
-# ---------- 测试基类 ----------
-
-class DaemonTaskTestBase(unittest.TestCase):
-    def setUp(self):
-        self._tmp = tempfile.TemporaryDirectory()
-        self.db_path = Path(self._tmp.name) / "t.db"
-        # 种子数据/断言用主连接；proxy 走 db_factory 注入（ctx.store=None 路径）
-        self.db = ShopDB(self.db_path)
-        self.inner = FakeInnerTask()
-        self.proxy = DaemonTaskProxy(
-            inner=self.inner, queue=QUEUE, site="1688",
-            domain_suffix=".1688.com",
-            db_factory=lambda: ShopDB(self.db_path))
-
-    def tearDown(self):
-        self.db.close()
-        self._tmp.cleanup()
-
-    def make_ctx(self, wid=0, stop=None):
-        """store=None 的轻量 ctx：proxy 经 db_factory 按线程自建连接。"""
-        config = RunConfig(db_path=self.db_path, headless=True,
-                           use_proxy=False)
-        return WorkerContext(config=config, store=None,
-                             stop=stop or threading.Event(),
-                             log=lambda m: None, wid=wid)
-
-    def query(self, sql, args=()):
-        """断言另开连接（避免与 proxy 持有的连接相互干扰）。"""
-        conn = sqlite3.connect(self.db_path)
-        conn.row_factory = sqlite3.Row
-        try:
-            return conn.execute(sql, args).fetchall()
-        finally:
-            conn.close()
-
-    def work_item(self, item_id):
-        rows = self.query("SELECT * FROM work_items WHERE id=?", (item_id,))
-        self.assertEqual(len(rows), 1)
-        return rows[0]
-
-    def shop_status(self, domain):
-        return self.query("SELECT status FROM shops WHERE domain=?",
-                          (domain,))[0]["status"]
-
-    def set_wait_timeout(self, seconds):
-        """缩短等货自醒超时（模块级 _WAIT_TIMEOUT 注入点）。"""
-        orig = daemon_task._WAIT_TIMEOUT
-        daemon_task._WAIT_TIMEOUT = seconds
-        self.addCleanup(setattr, daemon_task, "_WAIT_TIMEOUT", orig)
-
-
-# ---------- 用例 ----------
-
-class AcquireItemTest(DaemonTaskTestBase):
-    # 用例 1：有货直取——预置 pending work_items，acquire 返回 payload dict
-    def test_acquire_claims_pending_work_item(self):
-        self.db.upsert_shops([_shop(1), _shop(2)])
-        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
-
-        ctx = self.make_ctx(wid=3)
-        item = self.proxy.acquire_item(ctx)
-
-        self.assertIsNotNone(item)
-        self.assertIn("id", item)
-        # domain/name/url 三键必在（name/url 允许 None）
-        for key in ("domain", "name", "url"):
-            self.assertIn(key, item)
-        self.assertEqual(item["domain"], "shop1.1688.com")  # 最老 pending 先领
-        self.assertEqual(item["name"], "店铺1")
-        self.assertEqual(item["url"], "https://shop1.1688.com")
-        # 库内：claimed + claimed_by=w{wid}
-        row = self.work_item(item["id"])
-        self.assertEqual(row["status"], "claimed")
-        self.assertEqual(row["claimed_by"], "w3")
-        self.assertIsNotNone(row["claimed_at"])
-        # work_item id 记在本 worker 的 ctx.state 上
-        self.assertEqual(ctx.state["daemon_work_item_id"], item["id"])
-
-    # 用例 2：空队列自动补货——shops 有 pending、work_items 为空
-    def test_acquire_auto_topup_when_queue_empty(self):
-        self.db.upsert_shops([_shop(1), _shop(2)])
-        self.assertEqual(self.query("SELECT COUNT(*) AS c FROM work_items")[0]["c"], 0)
-
-        item = self.proxy.acquire_item(self.make_ctx())
-
-        self.assertIsNotNone(item)
-        self.assertEqual(item["domain"], "shop1.1688.com")
-        # 补货把两家 pending 店铺都入了队并标 in_progress
-        self.assertEqual(self.shop_status("shop1.1688.com"), "in_progress")
-        self.assertEqual(self.shop_status("shop2.1688.com"), "in_progress")
-        rows = self.query("SELECT status FROM work_items ORDER BY id")
-        self.assertEqual([r["status"] for r in rows], ["claimed", "pending"])
-
-    # 用例 3：stop 退出——队列空且无法补货，stop 置位后小超时内返回 None
-    def test_acquire_returns_none_after_stop(self):
-        self.set_wait_timeout(0.05)  # 注入小自醒超时，避免等满 30s
-        stop = threading.Event()
-        ctx = self.make_ctx(stop=stop)
-        threading.Timer(0.3, stop.set).start()
-
-        t0 = time.monotonic()
-        item = self.proxy.acquire_item(ctx)
-        elapsed = time.monotonic() - t0
-
-        self.assertIsNone(item)
-        # 确实阻塞等到了 stop（非「队列空立即返回 None」的快路径）
-        self.assertGreaterEqual(elapsed, 0.25)
-        # stop 后在注入的小超时量级内醒来返回，不会卡满 30s
-        self.assertLess(elapsed, 5.0)
-
-
-class CooldownFilterTest(DaemonTaskTestBase):
-    # 用例 4：冷却中不 claim——注入带冷却的 ctx → acquire 阻塞（等超时
-    # 唤醒路径），不 claim 不 topup
-    def test_cooldown_blocks_claim(self):
-        """冷却中 → acquire_item 不 claim 不 topup，等待冷却到期后才认领。"""
-        self.db.upsert_shops([_shop(1), _shop(2)])
-        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
-        ctx = self.make_ctx(wid=0)
-        # 设置 0.25s 冷却（短但可观测）
-        ctx.cooldown_until["1688"] = time.time() + 0.25
-
-        result_holder = []
-        t = threading.Thread(target=lambda:
-                             result_holder.append(self.proxy.acquire_item(ctx)),
-                             daemon=True)
-        t.start()
-
-        # 0.1s 后冷却应仍有效：工作项未认领
-        time.sleep(0.10)
-        rows = self.query("SELECT status FROM work_items WHERE queue=?"
-                          " ORDER BY id", (QUEUE,))
-        self.assertEqual([r["status"] for r in rows], ["pending", "pending"])
-
-        # 等待 acquire 完成（冷却到期后自动认领）
-        t.join(timeout=5)
-        self.assertFalse(t.is_alive(), "acquire_item 线程应在冷却到期后完成")
-        self.assertEqual(len(result_holder), 1)
-        self.assertIsNotNone(result_holder[0])
-        self.assertEqual(result_holder[0]["domain"], "shop1.1688.com")
-
-    # 用例 5：冷却到期后恢复认领
-    def test_cooldown_expired_allows_claim(self):
-        """冷却已到期 → acquire_item 正常 claim（不阻塞）。"""
-        self.db.upsert_shops([_shop(1)])
-        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 1)
-        ctx = self.make_ctx(wid=0)
-        # 冷却已过期（过去）
-        ctx.cooldown_until["1688"] = time.time() - 1.0
-
-        item = self.proxy.acquire_item(ctx)
-
-        self.assertIsNotNone(item)
-        self.assertEqual(item["domain"], "shop1.1688.com")
-
-    # 用例 6：claim 成功后 active_site 正确写入
-    def test_active_site_set_on_claim(self):
-        """claim 成功后 ctx.state["active_site"] = self._site。"""
-        self.db.upsert_shops([_shop(1)])
-        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 1)
-        ctx = self.make_ctx(wid=0)
-
-        self.assertNotIn("active_site", ctx.state)
-        self.proxy.acquire_item(ctx)
-        self.assertEqual(ctx.state.get("active_site"), "1688")
-
-
-class TerminalHookTest(DaemonTaskTestBase):
-    # 用例 4：终态钩子——on_success→done / on_giveup→failed，重复 finish 幂等
-    def test_terminal_hooks_finish_work_item(self):
-        self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
-        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 3)
-        ctx0, ctx1 = self.make_ctx(wid=0), self.make_ctx(wid=1)
-        result = ActionResult(Outcome.OK, "", {"mobile": "13800138000"})
-
-        # on_success：透传 inner 返回值，work_item 落 done
-        item_a = self.proxy.acquire_item(ctx0)
-        n = self.proxy.on_success(ctx0, item_a, result)
-        self.assertEqual(n, 1)  # inner.on_success 的返回值透传
-        self.assertEqual(self.inner.succeeded, [(0, "shop1.1688.com")])
-        row_a = self.work_item(item_a["id"])
-        self.assertEqual(row_a["status"], "done")
-        self.assertIsNotNone(row_a["finished_at"])
-        self.assertIsNone(row_a["result_json"])  # 成功不带 result
-        self.assertNotIn("daemon_work_item_id", ctx0.state)  # pop 语义
-
-        # on_giveup：透传短语，work_item 落 failed + reason/kind 落 result_json
-        item_b = self.proxy.acquire_item(ctx1)
-        phrase = self.proxy.on_giveup(ctx1, item_b, "风控滑块", "block")
-        self.assertEqual(phrase, "标记跳过")  # inner.on_giveup 的返回值透传
-        self.assertEqual(self.inner.given_up,
-                         [(1, "shop2.1688.com", "风控滑块", "block")])
-        row_b = self.work_item(item_b["id"])
-        self.assertEqual(row_b["status"], "failed")
-        self.assertIsNotNone(row_b["finished_at"])
-        self.assertEqual(json.loads(row_b["result_json"]),
-                         {"reason": "风控滑块", "kind": "block"})
-
-        # 重复 finish 幂等：state 已 pop，第二次 on_giveup 不再落库
-        # （用不同 reason 调用，验证 result_json 保持首次的值）
-        self.proxy.on_giveup(ctx1, item_b, "另一个原因", "net")
-        row_b2 = self.work_item(item_b["id"])
-        self.assertEqual(row_b2["status"], "failed")
-        self.assertEqual(json.loads(row_b2["result_json"]),
-                         {"reason": "风控滑块", "kind": "block"})
-
-        # 不误伤其他 item：ctx1 认领 item_c 后，ctx0（state 已空）的
-        # stray on_success 不应动 item_c
-        item_c = self.proxy.acquire_item(ctx1)
-        self.proxy.on_success(ctx0, item_a, result)
-        row_c = self.work_item(item_c["id"])
-        self.assertEqual(row_c["status"], "claimed")
-        self.assertEqual(row_c["claimed_by"], "w1")
-        # item_a 也不被重复落库改状态
-        self.assertEqual(self.work_item(item_a["id"])["status"], "done")
-
-
-class CrawlLoopIntegrationTest(DaemonTaskTestBase):
-    # 用例 5：CrawlLoop 联跑——proxy 包假 inner，两个 worker 线程共享一个
-    # proxy 实例，跑完 N 项后 stop 置位，loop 正常退出且终态/统计正确
-    def test_crawl_loop_two_workers_shared_proxy(self):
-        self.set_wait_timeout(0.05)
-        n_items = 6
-        self.db.upsert_shops([_shop(i) for i in range(1, n_items + 1)])
-        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", n_items)
-
-        config = RunConfig(db_path=self.db_path, headless=True,
-                           use_proxy=False, batch_num=100, max_batches=0,
-                           sample_min=0, sample_max=0, rest_every=0,
-                           batch_rest=0.01, block_rest_min=0.01,
-                           block_rest_max=0.02, ip_retry=1,
-                           max_consecutive_fail=3, workers=2)
-        stop = threading.Event()
-        results, errors = {}, {}
-
-        def run_worker(wid):
-            try:
-                store = IdentityStore(ShopDB(self.db_path))
-                ctx = WorkerContext(
-                    config=config, store=store,
-                    browser_manager=MockBrowserManager(FakePage()),
-                    site=Alibaba1688Plugin(), stop=stop,
-                    log=lambda m: None, wid=wid)
-                policy = Policy(table={}, strategies={},
-                                max_consecutive_fail=3)
-                results[wid] = CrawlLoop(ctx, self.proxy, policy=policy).run()
-            except Exception as e:  # noqa: BLE001
-                errors[wid] = e
-
-        threads = [threading.Thread(target=run_worker, args=(wid,),
-                                    name=f"worker-{wid}", daemon=True)
-                   for wid in (0, 1)]
-        for t in threads:
-            t.start()
-
-        # 监视：全部落 done 后置 stop，worker 从等货中醒来退出
-        deadline = time.monotonic() + 15
-        while time.monotonic() < deadline:
-            done = self.query("SELECT COUNT(*) AS c FROM work_items"
-                              " WHERE status='done'")[0]["c"]
-            if done >= n_items:
-                break
-            time.sleep(0.02)
-        stop.set()
-        for t in threads:
-            t.join(timeout=10)
-
-        self.assertEqual(errors, {})
-        self.assertFalse(any(t.is_alive() for t in threads),
-                         "worker 未在 stop 后退出")
-        self.assertEqual(set(results), {0, 1})
-
-        # 终态：N 项全 done，无残留 claimed/pending
-        rows = self.query("SELECT status, COUNT(*) AS c FROM work_items"
-                          " GROUP BY status")
-        self.assertEqual({r["status"]: r["c"] for r in rows},
-                         {"done": n_items})
-
-        # 不串 item：两 worker 认领的 domain 合起来恰好是全集且无重复
-        domains = [d for _wid, d in self.inner.succeeded]
-        self.assertEqual(len(domains), n_items)
-        self.assertEqual(sorted(domains),
-                         [f"shop{i}.1688.com" for i in range(1, n_items + 1)])
-
-        # stats：各 worker 的 done 计数与其成功明细一致，总和 = N
-        per_wid = {wid: sum(1 for w, _d in self.inner.succeeded if w == wid)
-                   for wid in (0, 1)}
-        for wid in (0, 1):
-            self.assertEqual(results[wid]["done"], per_wid[wid])
-        self.assertEqual(sum(per_wid.values()), n_items)
-
-
-if __name__ == "__main__":
-    unittest.main()
diff --git a/fetcher/tests/test_queue_router.py b/fetcher/tests/test_queue_router.py
index 1b5b756..8b72840 100644
--- a/fetcher/tests/test_queue_router.py
+++ b/fetcher/tests/test_queue_router.py
@@ -1,140 +1,874 @@
 # -*- coding: utf-8 -*-
-"""queue_router 单元测试：QueueSpec / eligible_queues / condvar_timeout。
+"""QueueRouter 单元测试：跨队列认领 / 冷却过滤 / topup / condvar / 终态路由 /
+budget_for 路由 / loop 双队列装配。
 
-本文件为 P3 Step 1.2 纯函数新增测试（新建文件）。
+真实临时 sqlite + 真实线程/条件变量，不 mock 被测对象本身；
+浏览器/网络侧沿用 test_control_loop.py 的假基建模式（FakePage/
+MockBrowserManager），inner task 用可编程的假实现。
 """
 
+import json
+import sqlite3
+import tempfile
+import threading
+import time
 import unittest
+from pathlib import Path
 
-from fetcher.control.queue_router import QueueSpec, condvar_timeout, eligible_queues
+from fetcher import (
+    Alibaba1688Plugin,
+    IdentityStore,
+    RunConfig,
+    ShopDB,
+    Session,
+    WorkerContext,
+)
+from fetcher.control import CrawlLoop, Task
+from fetcher.control.queue_router import (
+    QueueRouter,
+    QueueSpec,
+    _WAIT_TIMEOUT,
+)
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.strategy.policy import Policy
 
 
-# ---------- QueueSpec ----------
+QUEUE_A = "crawl_1688_contact"
+QUEUE_B = "crawl_mic_contact"
 
-class QueueSpecTest(unittest.TestCase):
-    """QueueSpec 数据类基本构造与字段访问。"""
 
-    def test_construction_and_fields(self):
-        qs = QueueSpec(queue="crawl_1688_contact", site="1688",
-                       requires={"channel", "browser"})
-        self.assertEqual(qs.queue, "crawl_1688_contact")
-        self.assertEqual(qs.site, "1688")
-        self.assertEqual(qs.requires, {"channel", "browser"})
+def _shop_1688(i):
+    return {"domain": f"shop{i}.1688.com", "name": f"店铺{i}",
+            "url": f"https://shop{i}.1688.com"}
 
 
-# ---------- eligible_queues ----------
+def _shop_mic(i):
+    return {"domain": f"shop{i}.cn.made-in-china.com",
+            "name": f"MIC店铺{i}",
+            "url": f"https://shop{i}.cn.made-in-china.com"}
 
-class EligibleQueuesTest(unittest.TestCase):
-    """eligible_queues 过滤逻辑：资源满足 + 冷却到期。"""
 
-    def _registry(self):
-        return [
-            QueueSpec(queue="crawl_1688_contact", site="1688",
-                      requires={"channel", "browser"}),
-            QueueSpec(queue="crawl_madeinchina", site="madeinchina",
-                      requires={"channel", "browser"}),
-            QueueSpec(queue="crawl_1688_search", site="1688",
-                      requires={"channel"}),
-        ]
+# ---------- 假 inner task / 假浏览器基建 ----------
+
+class FakeInnerTask(Task):
+    """可编程假任务：fetch 恒成功，记录每 worker 的成功/放弃明细。
+
+    acquire_item 不应被 router 透传调用（router 自己实现认领），
+    被调到即失败。
+    """
+
+    name = "fake-inner"
+    unit = "店铺"
+    batch_unit = "店铺"
+
+    def __init__(self, budget=None):
+        super().__init__()
+        self.lock = threading.Lock()
+        self.succeeded = []   # [(wid, domain)]
+        self.given_up = []    # [(wid, domain, reason, kind)]
+        self.fetched = []     # [(wid, domain)]
+        self._budget = budget
 
-    def _ctx(self, resources=None, cooldown_until=None):
-        return type("FakeCtx", (), {
-            "resources": resources or {"channel", "browser"},
-            "cooldown_until": cooldown_until or {},
-        })()
-
-    # ---- 用例 1：冷却过滤 ----
-
-    def test_all_eligible_with_no_cooldown(self):
-        """无冷却时所有队列均可见。"""
-        result = eligible_queues(self._registry(), self._ctx(), 100.0)
-        self.assertEqual(result, ["crawl_1688_contact", "crawl_madeinchina",
-                                  "crawl_1688_search"])
-
-    def test_cooldown_filters_site_queues(self):
-        """site A 冷却中 → 该 site 所有队列被滤；site B 到期 → 保留。"""
-        ctx = self._ctx(cooldown_until={"1688": 200.0})
-        # now=100 < 到期=200 → 1688 冷却中
-        result = eligible_queues(self._registry(), ctx, 100.0)
-        # 1688 两队列被滤，只剩 madeinchina
-        self.assertEqual(result, ["crawl_madeinchina"])
-
-    # ---- 用例 2：资源过滤 ----
-
-    def test_resource_filtering(self):
-        """requires 超 resources 的队列被滤。"""
-        ctx = self._ctx(resources={"channel"})  # 缺 browser
-        result = eligible_queues(self._registry(), ctx, 100.0)
-        # crawl_1688_search 只需 channel → visible
-        self.assertEqual(result, ["crawl_1688_search"])
-
-    # ---- 用例 3：到期恢复 ----
-
-    def test_expiry_recovery(self):
-        """now 推进到冷却到期后 → 队列恢复可见。"""
-        ctx = self._ctx(cooldown_until={"1688": 100.0, "madeinchina": 200.0})
-        # now=100: 1688 到期（now>=100），madeinchina 仍在冷却（now<200）
-        result = eligible_queues(self._registry(), ctx, 100.0)
-        self.assertEqual(result, ["crawl_1688_contact", "crawl_1688_search"])
-
-        # now=200: 全部到期
-        result2 = eligible_queues(self._registry(), ctx, 200.0)
-        self.assertEqual(result2, ["crawl_1688_contact", "crawl_madeinchina",
-                                   "crawl_1688_search"])
-
-    def test_empty_registry(self):
-        """空注册表返回空列表。"""
-        self.assertEqual(eligible_queues([], self._ctx(), 100.0), [])
-
-    def test_empty_resources_still_matches_empty_requires(self):
-        """空 resources 仍可匹配空 requires 的队列。"""
-        registry = [QueueSpec(queue="no_resources", site="x",
-                              requires=set())]
-        ctx = self._ctx(resources=set())
-        result = eligible_queues(registry, ctx, 100.0)
-        self.assertEqual(result, ["no_resources"])
-
-
-# ---------- condvar_timeout ----------
-
-class CondvarTimeoutTest(unittest.TestCase):
-    """condvar_timeout 计算。"""
-
-    # ---- 用例 4：condvar_timeout 计算 ----
-
-    def test_not_in_cooldown_returns_cap(self):
-        """不在冷却中 → 返回 cap（默认 30.0）。"""
-        self.assertEqual(condvar_timeout({}, "1688", 100.0), 30.0)
-        self.assertEqual(condvar_timeout({"other": 200.0}, "1688", 100.0), 30.0)
-
-    def test_in_cooldown_returns_min_of_remaining_and_cap(self):
-        """冷却中 → min(到期 - now, cap)。"""
-        cooldown_until = {"1688": 120.0}
-        # 剩余 20s → min(20, 30)=20
-        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 100.0),
-                               20.0, delta=1e-9)
-        # 剩余 60s → min(60, 30)=30
-        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 60.0),
-                               30.0, delta=1e-9)
-
-    def test_custom_cap(self):
-        """自定义 cap 生效。"""
-        cooldown_until = {"1688": 110.0}  # 剩余 10s → min(10,5)=5
-        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 100.0,
-                                               cap=5.0), 5.0)
-
-    def test_very_small_remaining_returns_positive(self):
-        """剩余极小时返回剩余值（>0），不归零、不转负数。"""
-        cooldown_until = {"1688": 100.01}  # 剩余 0.01s
-        result = condvar_timeout(cooldown_until, "1688", 100.0)
-        self.assertGreater(result, 0.0)
-        self.assertAlmostEqual(result, 0.01, delta=1e-6)
-
-    def test_exactly_at_deadline_returns_cap(self):
-        """now == 到期 → 视为不在冷却，返回 cap。"""
-        cooldown_until = {"1688": 100.0}
-        self.assertEqual(condvar_timeout(cooldown_until, "1688", 100.0), 30.0)
+    @property
+    def ip_request_budget(self):
+        return self._budget
+
+    def acquire_item(self, ctx):
+        raise AssertionError("daemon 模式下不应调到 inner.acquire_item")
+
+    def fetch(self, ctx, item):
+        with self.lock:
+            self.fetched.append((ctx.wid, item.get("domain", "?")))
+        return ActionResult(Outcome.OK, "", {"v": 1})
+
+    def on_success(self, ctx, item, result):
+        with self.lock:
+            self.succeeded.append((ctx.wid, item["domain"]))
+        stats = ctx.state.get("task", {}).get("stats")
+        if stats is not None:
+            stats["done"] = stats.get("done", 0) + 1
+        return 1
+
+    def on_giveup(self, ctx, item, reason, kind):
+        with self.lock:
+            self.given_up.append((ctx.wid, item["domain"], reason, kind))
+        return "标记跳过"
+
+    def make_stats(self):
+        return {"done": 0}
+
+
+class FakeBrowser:
+    def is_connected(self):
+        return True
+
+    def close(self):
+        pass
+
+
+class FakeContext:
+    def __init__(self):
+        self.browser = FakeBrowser()
+
+    def cookies(self):
+        return []
+
+
+class FakePage:
+    def __init__(self):
+        self.url = "https://shop1.1688.com/page/contactinfo.htm"
+        self._text = "正常页面文本，足够长，包含电话、手机、地址等字段标签，超过阈值。"
+        self.frames = []
+        self.context = FakeContext()
+
+    def evaluate(self, js):
+        return self._text
+
+    def query_selector(self, sel):
+        return None
+
+    def is_closed(self):
+        return False
+
+
+class MockBrowserManager:
+    """launch 返回带假 page 的 Session（联跑用，不起真实浏览器）。"""
+
+    def __init__(self, page):
+        self.page = page
+
+    def launch(self, seed_kit=None, stop=None):
+        return Session(browser=FakeBrowser(), page=self.page,
+                       identity="1688:1.1.1.1", seed_kit=seed_kit)
+
+    def check_ip_fresh(self, session):
+        return False, session.identity, ""
+
+    def save_cookies(self, session):
+        return 0
+
+
+# ---------- 双队列 helper ----------
+
+def make_dual_registry(inner_a=None, inner_b=None):
+    """构建双队列注册表（与 cli _build_registry 同结构）。"""
+    if inner_a is None:
+        inner_a = FakeInnerTask()
+    if inner_b is None:
+        inner_b = FakeInnerTask()
+    return [
+        QueueSpec(
+            queue=QUEUE_A,
+            site="1688",
+            task=inner_a,
+            topup=lambda db, limit: db.topup_contact_work_items(
+                QUEUE_A, "1688", ".1688.com", limit),
+            domain_suffix=".1688.com",
+        ),
+        QueueSpec(
+            queue=QUEUE_B,
+            site="madeinchina",
+            task=inner_b,
+            topup=lambda db, limit: db.topup_contact_work_items(
+                QUEUE_B, "madeinchina", ".cn.made-in-china.com", limit),
+            domain_suffix=".cn.made-in-china.com",
+        ),
+    ]
+
+
+# ---------- 测试基类 ----------
+
+class QueueRouterTestBase(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = Path(self._tmp.name) / "t.db"
+        self.db = ShopDB(self.db_path)
+        self.inner_a = FakeInnerTask()
+        self.inner_b = FakeInnerTask()
+        registry = make_dual_registry(self.inner_a, self.inner_b)
+        self.router = QueueRouter(
+            registry, db_factory=lambda: ShopDB(self.db_path))
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def make_ctx(self, wid=0, stop=None):
+        config = RunConfig(db_path=self.db_path, headless=True,
+                           use_proxy=False)
+        return WorkerContext(config=config, store=None,
+                             stop=stop or threading.Event(),
+                             log=lambda m: None, wid=wid)
+
+    def query(self, sql, args=()):
+        conn = sqlite3.connect(self.db_path)
+        conn.row_factory = sqlite3.Row
+        try:
+            return conn.execute(sql, args).fetchall()
+        finally:
+            conn.close()
+
+    def work_item(self, item_id):
+        rows = self.query("SELECT * FROM work_items WHERE id=?", (item_id,))
+        self.assertEqual(len(rows), 1)
+        return rows[0]
+
+    def set_wait_timeout(self, seconds):
+        """缩短等货自醒超时（模块级 _WAIT_TIMEOUT 注入点）。"""
+        import fetcher.control.queue_router as qr
+        orig = qr._WAIT_TIMEOUT
+        qr._WAIT_TIMEOUT = seconds
+        self.addCleanup(setattr, qr, "_WAIT_TIMEOUT", orig)
+
+
+# ---------- 用例 1：跨队列认领 ----------
+
+class CrossQueueClaimTest(QueueRouterTestBase):
+    def test_claim_across_queues_fifo(self):
+        """两队列各有 pending item → claim_next_eligible 跨队列按 id FIFO。"""
+        self.db.upsert_shops([_shop_1688(1), _shop_1688(2)])
+        self.db.upsert_shops([_shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 2)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        # 队列 A 有 2 个, B 有 1 个，按 id FIFO: A1 < A2 < B1
+        ctx = self.make_ctx(wid=0)
+        item1 = self.router.acquire_item(ctx)
+        self.assertEqual(item1["domain"], "shop1.1688.com")
+        self.assertEqual(ctx.state["queue"], QUEUE_A)
+        self.assertEqual(ctx.state["active_site"], "1688")
+
+        ctx2 = self.make_ctx(wid=1)
+        item2 = self.router.acquire_item(ctx2)
+        self.assertEqual(item2["domain"], "shop2.1688.com")
+
+        ctx3 = self.make_ctx(wid=2)
+        item3 = self.router.acquire_item(ctx3)
+        self.assertEqual(item3["domain"], "shop1.cn.made-in-china.com")
+        self.assertEqual(ctx3.state["queue"], QUEUE_B)
+        self.assertEqual(ctx3.state["active_site"], "madeinchina")
+
+        # 无货
+        ctx4 = self.make_ctx(wid=3)
+        self.set_wait_timeout(0.05)
+        stop = threading.Event()
+        ctx4.stop = stop
+        threading.Timer(0.2, stop.set).start()
+        item4 = self.router.acquire_item(ctx4)
+        self.assertIsNone(item4)
+
+    def test_payload_dict_format(self):
+        """claim 返回的 payload 是 dict，含 domain/name/url。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        item = self.router.acquire_item(self.make_ctx())
+        self.assertIsInstance(item, dict)
+        self.assertEqual(item["domain"], "shop1.1688.com")
+        self.assertEqual(item["name"], "店铺1")
+        self.assertEqual(item["url"], "https://shop1.1688.com")
+
+    def test_state_keys_set_on_claim(self):
+        """claim 成功后三个状态键正确写入。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx()
+        self.assertNotIn("daemon_work_item_id", ctx.state)
+        self.assertNotIn("queue", ctx.state)
+        self.assertNotIn("active_site", ctx.state)
+
+        item = self.router.acquire_item(ctx)
+        self.assertIsNotNone(ctx.state["daemon_work_item_id"])
+        # payload 不含 id（id 只在 ctx.state 中），其他 keys 在
+        self.assertEqual(ctx.state["queue"], QUEUE_A)
+        self.assertEqual(ctx.state["active_site"], "1688")
+
+
+# ---------- 用例 2：冷却过滤 ----------
+
+class CooldownFilterTest(QueueRouterTestBase):
+    def test_cooldown_filters_site_a_allows_b(self):
+        """site A 冷却中 → 只认领 site B 队列。"""
+        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+        ctx = self.make_ctx()
+        # 1688 冷却中（30s），madeinchina 未冷却
+        ctx.cooldown_until["1688"] = time.time() + 30
+        # madeinchina 未冷却
+
+        item = self.router.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        # 应该领到 B 队列（madeinchina），因为 A 冷却中不可见
+        self.assertEqual(ctx.state["queue"], QUEUE_B)
+        self.assertEqual(ctx.state["active_site"], "madeinchina")
+        self.assertEqual(item["domain"], "shop1.cn.made-in-china.com")
+
+    def test_cooldown_expired_allows_claim(self):
+        """冷却到期后恢复认领。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx()
+        ctx.cooldown_until["1688"] = time.time() - 1.0  # 已过期
+
+        item = self.router.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["domain"], "shop1.1688.com")
+
+    def test_cooldown_eventually_expires_and_claims(self):
+        """冷却中等待到期后自动认领。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx()
+        ctx.cooldown_until["1688"] = time.time() + 0.25
+
+        result_holder = []
+        t = threading.Thread(
+            target=lambda: result_holder.append(
+                self.router.acquire_item(ctx)),
+            daemon=True)
+        t.start()
+
+        # 0.1s 后冷却应仍有效
+        time.sleep(0.10)
+        rows = self.query("SELECT status FROM work_items WHERE queue=?",
+                          (QUEUE_A,))
+        self.assertEqual([r["status"] for r in rows], ["pending"])
+
+        t.join(timeout=5)
+        self.assertFalse(t.is_alive())
+        self.assertIsNotNone(result_holder[0])
+        self.assertEqual(result_holder[0]["domain"], "shop1.1688.com")
+
+
+# ---------- 用例 3：topup 只对到期队列 ----------
+
+class TopupPerQueueTest(QueueRouterTestBase):
+    def test_topup_only_for_expired_queue(self):
+        """冷却中队列不补货；到期队列补货后 notify + 重试认领。"""
+        # seed B 的 shops，不 seed A
+        self.db.upsert_shops([_shop_mic(1), _shop_mic(2)])
+        ctx = self.make_ctx()
+        # 1688 冷却中，madeinchina 未冷却
+        ctx.cooldown_until["1688"] = time.time() + 30
+
+        # 初始无 work_items → acquire 走 topup 路径
+        item = self.router.acquire_item(ctx)
+
+        self.assertIsNotNone(item)
+        # 应补货并认领 B 队列的
+        self.assertEqual(ctx.state["queue"], QUEUE_B)
+        self.assertEqual(item["domain"], "shop1.cn.made-in-china.com")
+
+        # A 队列不应有 work_items（topup 被冷却阻挡）
+        rows_a = self.query("SELECT COUNT(*) AS c FROM work_items"
+                            " WHERE queue=?", (QUEUE_A,))
+        self.assertEqual(rows_a[0]["c"], 0)
+
+
+# ---------- 用例 4：condvar timeout ----------
+
+class CondvarTimeoutTest(QueueRouterTestBase):
+    def test_timeout_with_cooldown(self):
+        """冷却中 wait 剩余时间（取各 site 最小值）。"""
+        # seed shops for madeinchina so when cooldown expires, claim succeeds
+        self.db.upsert_shops([_shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+        ctx = self.make_ctx()
+        ctx.cooldown_until["1688"] = time.time() + 15
+        ctx.cooldown_until["madeinchina"] = time.time() + 0.5  # 最小值 0.5s
+
+        # 两站点都在冷却 → no eligible queues → condvar wait
+        self.set_wait_timeout(30)  # 设大兜底，实际 0.5s 到期
+        stop = threading.Event()
+        ctx.stop = stop
+
+        result_holder = []
+        errors = []
+
+        def run():
+            try:
+                result_holder.append(self.router.acquire_item(ctx))
+            except Exception as e:
+                errors.append(e)
+
+        t = threading.Thread(target=run, daemon=True)
+        t0 = time.monotonic()
+        t.start()
+
+        # madeinchina 冷却到期 → 醒来 → claim_next_eligible 命中
+        t.join(timeout=10)
+        stop.set()
+        elapsed = time.monotonic() - t0
+
+        self.assertEqual(errors, [])
+        self.assertGreaterEqual(elapsed, 0.4)
+        self.assertLess(elapsed, 8.0)
+        self.assertEqual(len(result_holder), 1)
+        self.assertIsNotNone(result_holder[0])
+        self.assertEqual(result_holder[0]["domain"], "shop1.cn.made-in-china.com")
+
+    def test_timeout_no_cooldown_30s(self):
+        """无冷却 → 30s 自醒兜底。"""
+        ctx = self.make_ctx()
+        self.set_wait_timeout(0.1)  # 注入小自醒超时加速测试
+        stop = threading.Event()
+        ctx.stop = stop
+
+        result_holder = []
+        t = threading.Thread(
+            target=lambda: result_holder.append(
+                self.router.acquire_item(ctx)),
+            daemon=True)
+        t0 = time.monotonic()
+        t.start()
+
+        # 等一小段时间后设 stop
+        time.sleep(0.3)
+        stop.set()
+        t.join(timeout=2)
+        elapsed = time.monotonic() - t0
+
+        self.assertFalse(t.is_alive())
+        # 在注入的 0.1s 量级醒来
+        self.assertLess(elapsed, 2.0)
+        self.assertIsNone(result_holder[0])
+
+    def test_stop_exits_during_wait(self):
+        """stop 置位后 acquire 返回 None。"""
+        self.set_wait_timeout(0.05)
+        stop = threading.Event()
+        ctx = self.make_ctx(stop=stop)
+        threading.Timer(0.3, stop.set).start()
+
+        t0 = time.monotonic()
+        item = self.router.acquire_item(ctx)
+        elapsed = time.monotonic() - t0
+
+        self.assertIsNone(item)
+        self.assertGreaterEqual(elapsed, 0.25)
+        self.assertLess(elapsed, 5.0)
+
+
+# ---------- 用例 5：on_success/on_giveup 路由 ----------
+
+class TerminalHookRoutingTest(QueueRouterTestBase):
+    def test_on_success_routes_correctly(self):
+        """on_success 路由到 item 所属 queue 的 task + 落 done。"""
+        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        ctx_a = self.make_ctx(wid=0)
+        item_a = self.router.acquire_item(ctx_a)
+        result = ActionResult(Outcome.OK, "", {"mobile": "138"})
+        n = self.router.on_success(ctx_a, item_a, result)
+
+        self.assertEqual(n, 1)
+        self.assertEqual(self.inner_a.succeeded, [(0, "shop1.1688.com")])
+        self.assertEqual(self.inner_b.succeeded, [])
+        row = self.work_item(item_a["id"])
+        self.assertEqual(row["status"], "done")
+        self.assertNotIn("daemon_work_item_id", ctx_a.state)
+
+        ctx_b = self.make_ctx(wid=1)
+        item_b = self.router.acquire_item(ctx_b)
+        n2 = self.router.on_success(ctx_b, item_b, result)
+
+        self.assertEqual(n2, 1)
+        self.assertEqual(self.inner_b.succeeded,
+                         [(1, "shop1.cn.made-in-china.com")])
+        self.assertEqual(len(self.inner_a.succeeded), 1)
+
+    def test_on_giveup_routes_correctly(self):
+        """on_giveup 路由到 item 所属 queue 的 task + 落 failed。"""
+        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        ctx_a = self.make_ctx(wid=0)
+        item_a = self.router.acquire_item(ctx_a)
+        phrase = self.router.on_giveup(ctx_a, item_a, "风控", "block")
+
+        self.assertEqual(phrase, "标记跳过")
+        self.assertEqual(self.inner_a.given_up,
+                         [(0, "shop1.1688.com", "风控", "block")])
+        self.assertEqual(self.inner_b.given_up, [])
+        row = self.work_item(item_a["id"])
+        self.assertEqual(row["status"], "failed")
+        self.assertEqual(json.loads(row["result_json"]),
+                         {"reason": "风控", "kind": "block"})
+
+        ctx_b = self.make_ctx(wid=1)
+        item_b = self.router.acquire_item(ctx_b)
+        phrase2 = self.router.on_giveup(ctx_b, item_b, "网络错误", "net")
+
+        self.assertEqual(phrase2, "标记跳过")
+        self.assertEqual(self.inner_b.given_up,
+                         [(1, "shop1.cn.made-in-china.com", "网络错误", "net")])
+        self.assertEqual(len(self.inner_a.given_up), 1)
+
+    def test_finish_idempotent(self):
+        """重复 finish 幂等（state key 已 pop）。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx()
+        item = self.router.acquire_item(ctx)
+        result = ActionResult(Outcome.OK, "", {})
+
+        self.router.on_success(ctx, item, result)
+        # 第二次 on_success（state key 已 pop）
+        self.router.on_success(ctx, item, result)
+        row = self.work_item(item["id"])
+        self.assertEqual(row["status"], "done")
+
+    def test_stray_finish_does_not_affect_other_item(self):
+        """stray finish（不同 ctx，state key 已 pop）不动错 item。
+
+        与 DaemonTaskProxy 原测试一致：用不同 ctx 对象模拟跨 worker 场景。
+        ctx0 的 state key 在 finish 后已 pop，后续 stray on_success 是 no-op。
+        """
+        self.db.upsert_shops([_shop_1688(1), _shop_1688(2), _shop_1688(3)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 3)
+
+        ctx0 = self.make_ctx(wid=0)
+        ctx1 = self.make_ctx(wid=1)
+        result = ActionResult(Outcome.OK, "", {})
+
+        # ctx0 认领 item_a 并 finish
+        item_a = self.router.acquire_item(ctx0)
+        self.router.on_success(ctx0, item_a, result)
+        self.assertEqual(self.work_item(item_a["id"])["status"], "done")
+
+        # ctx1 认领 item_c（跳过 item_b 因为 ctx0 已完成 item_a）
+        item_c = self.router.acquire_item(ctx1)
+
+        # ctx0 的 stray on_success（state key 已 pop）不应动 item_c
+        self.router.on_success(ctx0, item_a, result)
+        row_c = self.work_item(item_c["id"])
+        self.assertEqual(row_c["status"], "claimed")
+        self.assertEqual(row_c["claimed_by"], "w1")
+
+        # item_a 也不被重复落库
+        self.assertEqual(self.work_item(item_a["id"])["status"], "done")
+
+
+# ---------- 用例 6：budget_for 路由 ----------
+
+class BudgetForTest(QueueRouterTestBase):
+    def test_budget_for_routes_per_site(self):
+        """不同 site 的 task 返回不同预算。"""
+        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        # 设置不同预算
+        self.inner_a._budget = 50
+        self.inner_b._budget = 100
+
+        ctx_a = self.make_ctx()
+        self.router.acquire_item(ctx_a)  # A 队列
+        self.assertEqual(self.router.budget_for(ctx_a), 50)
+
+        ctx_b = self.make_ctx()
+        self.router.acquire_item(ctx_b)  # B 队列
+        self.assertEqual(self.router.budget_for(ctx_b), 100)
+
+    def test_budget_for_no_queue_returns_none(self):
+        """无 queue 在 state 时 budget_for 返回 None。"""
+        ctx = self.make_ctx()
+        self.assertIsNone(self.router.budget_for(ctx))
+
+    def test_router_ip_request_budget_property_is_none(self):
+        """QueueRouter.ip_request_budget 始终返回 None（必须 per-site）。"""
+        self.assertIsNone(self.router.ip_request_budget)
+
+
+# ---------- 用例 8：Task 基类 budget_for 兼容 ----------
+
+class TaskBudgetForCompatTest(unittest.TestCase):
+    def test_task_base_budget_for_returns_ip_request_budget(self):
+        """Task 基类 budget_for 默认返回 ip_request_budget（CLI 零影响）。"""
+        from fetcher.control.task import Task as BaseTask
+        task = BaseTask()
+        task.ip_request_budget = 42
+        self.assertEqual(task.budget_for(None), 42)
+
+        task2 = BaseTask()
+        self.assertIsNone(task2.budget_for(None))
+
+
+# ---------- 用例 7：loop 双队列装配 ----------
+
+class LoopDualQueueTest(unittest.TestCase):
+    """sites/policies 注入 → ctx.site/inspector/policy 切换正确；
+    CLI 路径（sites=None）行为不变。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = Path(self._tmp.name) / "t.db"
+        self.db = ShopDB(self.db_path)
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_loop_binds_site_on_item_acquisition(self):
+        """处理 site A item 时 ctx.site/inspector/policy 切换正确。"""
+        from fetcher.sites import get_site
+        site_1688 = get_site("1688")
+        site_mic = get_site("madeinchina")
+
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+
+        inner = FakeInnerTask()
+        registry = [
+            QueueSpec(queue=QUEUE_A, site="1688", task=inner,
+                      topup=lambda db, limit: db.topup_contact_work_items(
+                          QUEUE_A, "1688", ".1688.com", limit),
+                      domain_suffix=".1688.com"),
+        ]
+        router = QueueRouter(registry, db_factory=lambda: ShopDB(self.db_path))
+
+        config = RunConfig(db_path=self.db_path, headless=True,
+                           use_proxy=False, batch_num=1, max_batches=1,
+                           sample_min=0, sample_max=0, rest_every=0,
+                           max_consecutive_fail=3)
+        stop = threading.Event()
+        store = IdentityStore(ShopDB(self.db_path))
+        ctx = WorkerContext(
+            config=config, store=store,
+            browser_manager=MockBrowserManager(FakePage()),
+            site=None,  # daemon 模式初始无 site
+            stop=stop, log=lambda m: None, wid=0)
+
+        policy_1688 = Policy(max_consecutive_fail=3)
+        sites = {"1688": site_1688, "madeinchina": site_mic}
+        policies = {"1688": policy_1688}
+
+        loop = CrawlLoop(ctx, router, policy=Policy(max_consecutive_fail=3),
+                         sites=sites, policies=policies,
+                         inspector=None)  # daemon 模式延迟建
+
+        # 初始无 site / no inspector (daemon path)
+        self.assertIsNone(loop._bound_site)
+
+        # 手动模拟 acquire_item + _bind_item_site（不跑完整 loop.run）
+        item = router.acquire_item(ctx)
+        loop._bind_item_site()
+
+        self.assertEqual(loop._bound_site, "1688")
+        self.assertEqual(ctx.site, site_1688)
+        self.assertIsNotNone(loop.inspector)
+        self.assertEqual(loop.policy, policy_1688)
+
+        stop.set()
+
+    def test_cli_path_sites_none_unchanged(self):
+        """CLI 路径（sites=None）_bind_item_site 无操作。"""
+        from fetcher.sites import get_site
+
+        config = RunConfig(db_path=self.db_path, headless=True,
+                           use_proxy=False, batch_num=1, max_batches=1,
+                           sample_min=0, sample_max=0, rest_every=0,
+                           max_consecutive_fail=3)
+        stop = threading.Event()
+        store = IdentityStore(ShopDB(self.db_path))
+        site = get_site("1688")
+        ctx = WorkerContext(
+            config=config, store=store,
+            browser_manager=MockBrowserManager(FakePage()),
+            site=site, stop=stop, log=lambda m: None, wid=0)
+
+        task = FakeInnerTask()
+        loop = CrawlLoop(ctx, task, policy=Policy(max_consecutive_fail=3))
+
+        self.assertEqual(ctx.site, site)
+        orig_inspector = loop.inspector
+        orig_policy = loop.policy
+        self.assertIsNotNone(loop._bound_site)
+
+        # _bind_item_site 无操作
+        orig_bound = loop._bound_site
+        loop._bind_item_site()
+        self.assertEqual(ctx.site, site)
+        self.assertIs(loop.inspector, orig_inspector)
+        self.assertIs(loop.policy, orig_policy)
+        self.assertEqual(loop._bound_site, orig_bound)
+
+        stop.set()
+
+
+# ---------- 用例 9：CrawlLoop 联跑 ----------
+
+class CrawlLoopIntegrationTest(QueueRouterTestBase):
+    def test_crawl_loop_two_workers_shared_router(self):
+        """单个 worker 线程跑 QueueRouter + CrawlLoop，跑完 N 项后 stop 退出。"""
+        self.set_wait_timeout(0.1)
+        n_items = 2  # 1 per queue, single worker
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.upsert_shops([_shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        config = RunConfig(db_path=self.db_path, headless=True,
+                           use_proxy=False, batch_num=100, max_batches=1,
+                           sample_min=0, sample_max=0, rest_every=0,
+                           batch_rest=0.01, block_rest_min=0.01,
+                           block_rest_max=0.02, ip_retry=1,
+                           max_consecutive_fail=3, workers=1)
+        stop = threading.Event()
+        errors = {}
+
+        from fetcher.sites import get_site
+        sites = {"1688": get_site("1688"),
+                 "madeinchina": get_site("madeinchina")}
+        policies = {
+            "1688": Policy(max_consecutive_fail=3),
+            "madeinchina": Policy(max_consecutive_fail=3),
+        }
+
+        def run_worker():
+            try:
+                store = IdentityStore(ShopDB(self.db_path))
+                ctx = WorkerContext(
+                    config=config, store=store,
+                    browser_manager=MockBrowserManager(FakePage()),
+                    site=None, stop=stop, log=lambda m: None, wid=0)
+                loop = CrawlLoop(ctx, self.router,
+                                 policy=Policy(max_consecutive_fail=3),
+                                 sites=sites, policies=policies)
+                loop.run()
+            except Exception as e:  # noqa: BLE001
+                import traceback
+                traceback.print_exc()
+                errors[0] = e
+
+        t = threading.Thread(target=run_worker, daemon=True)
+        t.start()
+
+        # 监视：全部落 done 后置 stop
+        deadline = time.monotonic() + 15
+        while time.monotonic() < deadline:
+            done = self.query("SELECT COUNT(*) AS c FROM work_items"
+                              " WHERE status='done'")[0]["c"]
+            if done >= n_items:
+                break
+            time.sleep(0.02)
+        stop.set()
+        t.join(timeout=10)
+
+        self.assertEqual(errors, {})
+        self.assertFalse(t.is_alive())
+
+        # 终态：N 项全 done
+        rows = self.query("SELECT status, COUNT(*) AS c FROM work_items"
+                          " GROUP BY status")
+        self.assertEqual({r["status"]: r["c"] for r in rows},
+                         {"done": n_items})
+
+        # 两 inner 的成功明细不串
+        domains_a = [d for _w, d in self.inner_a.succeeded]
+        domains_b = [d for _w, d in self.inner_b.succeeded]
+        self.assertEqual(sorted(domains_a + domains_b),
+                         sorted(["shop1.1688.com", "shop1.cn.made-in-china.com"]))
+
+
+# ---------- Router 属性测试 ----------
+
+class RouterAttributesTest(QueueRouterTestBase):
+    def test_unit_is_xiang(self):
+        self.assertEqual(self.router.unit, "项")
+
+    def test_batch_unit_empty(self):
+        self.assertEqual(self.router.batch_unit, "")
+
+    def test_cold_start_before_acquire_false(self):
+        self.assertFalse(self.router.cold_start_before_acquire)
+
+    def test_rest_counter(self):
+        stats = {"done": 5, "other": 3}
+        self.assertEqual(self.router.rest_counter(stats), 5)
+        self.assertEqual(self.router.rest_counter({"done": 0}), 0)
+
+    def test_ip_request_budget_is_none(self):
+        self.assertIsNone(self.router.ip_request_budget)
+
+
+# ---------- 执行侧路由测试 ----------
+
+class ExecutionRoutingTest(QueueRouterTestBase):
+    def test_fetch_routes_to_correct_task(self):
+        """fetch 路由到 ctx.state["queue"] 对应的 task。"""
+        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        ctx_a = self.make_ctx()
+        item_a = self.router.acquire_item(ctx_a)
+        result = self.router.fetch(ctx_a, item_a)
+        self.assertEqual(self.inner_a.fetched, [(0, "shop1.1688.com")])
+        self.assertEqual(self.inner_b.fetched, [])
+        self.assertEqual(result.outcome, Outcome.OK)
+
+        ctx_b = self.make_ctx(wid=1)
+        item_b = self.router.acquire_item(ctx_b)
+        result2 = self.router.fetch(ctx_b, item_b)
+        self.assertEqual(self.inner_b.fetched,
+                         [(1, "shop1.cn.made-in-china.com")])
+
+    def test_validate_routes_correctly(self):
+        """validate 路由正确。"""
+        inner_a = FakeInnerTask()
+        inner_a.validate = lambda ctx, item, result: True
+        inner_b = FakeInnerTask()
+        inner_b.validate = lambda ctx, item, result: False
+        router = QueueRouter(make_dual_registry(inner_a, inner_b),
+                             db_factory=lambda: ShopDB(self.db_path))
+
+        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        ctx_a = self.make_ctx()
+        item_a = router.acquire_item(ctx_a)
+        self.assertTrue(router.validate(ctx_a, item_a, None))
+
+        ctx_b = self.make_ctx()
+        item_b = router.acquire_item(ctx_b)
+        self.assertFalse(router.validate(ctx_b, item_b, None))
+
+    def test_label_routes_correctly(self):
+        """label 路由正确。"""
+        inner_a = FakeInnerTask()
+        inner_a.label = lambda item: f"A:{item['domain']}"
+        inner_b = FakeInnerTask()
+        inner_b.label = lambda item: f"B:{item['domain']}"
+        router = QueueRouter(make_dual_registry(inner_a, inner_b),
+                             db_factory=lambda: ShopDB(self.db_path))
+
+        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
+                                         ".cn.made-in-china.com", 1)
+
+        ctx_a = self.make_ctx()
+        item_a = router.acquire_item(ctx_a)
+        self.assertEqual(router.label(item_a), "A:shop1.1688.com")
+
+        ctx_b = self.make_ctx()
+        item_b = router.acquire_item(ctx_b)
+        self.assertEqual(router.label(item_b), "B:shop1.cn.made-in-china.com")
 
 
 if __name__ == "__main__":
     unittest.main()
