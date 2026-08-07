=== git log ===
f6034dd feat(fetcher): DaemonTaskProxy（daemon 工作项来源切换 work_items 表，三段式 acquire + 终态钩子）

=== diff --stat ===
 .../task-2.1-brief.md                              |  37 ++++
 .../task-2.1-report.md                             |  80 +++++++++
 fetcher/fetcher/control/daemon_task.py             | 195 +++++++++++++++++++++
 3 files changed, 312 insertions(+)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.1-brief.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.1-brief.md
new file mode 100644
index 0000000..58f0cd9
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.1-brief.md
@@ -0,0 +1,37 @@
+# Step 2.1 brief — DaemonTaskProxy 实现
+
+> 来源：PLAN.md Phase 2 Step 2.1 + SPEC §3.3。本文本是你的需求唯一来源。
+
+## 内容
+
+新增 `fetcher/fetcher/control/daemon_task.py`：`DaemonTaskProxy(inner, queue, site, domain_suffix)`，实现 Task 协议（`fetcher/fetcher/control/task.py`），包装既有 task（P0 为 ContactTask）让它的工作项来源从「自己 claim shops」换成「从 work_items 表认领」。
+
+### acquire_item 三段式（SPEC §3.3）
+
+1. `db.claim_work_item(queue, consumer_id)`；命中 → 返回 payload dict（必须含 `domain`/`name`/`url` 三键，name/url 允许 None 但键必须存在）；
+2. 未命中 → `db.topup_contact_work_items(queue, site, domain_suffix, limit=消费者数×4)` → 补到货则对条件变量 `notify_all` 并重试 claim；
+3. 仍无货 → 条件变量 wait（超时 30s 自醒），醒后先查 `ctx.stop`，置位则返回 None，否则回到 1。
+
+consumer_id 用 `f"w{ctx.wid}"`。消费者数从 `ctx.config.workers` 取（注意 workers=0 时表示「按通道数」，此时退用 `len(provider.servers())` 不可行——proxy 拿不到 provider；裁定：workers<=0 时补货上限按 4×1=4 的兜底，或你在读码后发现 config 上有更合适的已解析字段，用那个并在 report 说明）。
+
+### 必须处理的设计点（Step 1.1 已验证的事实）
+
+- **proxy 实例跨 worker 线程共享**（Engine 把同一个 task 对象传给所有 worker 的 CrawlLoop）：条件变量、以及「当前 worker 认领的 work_item id」都必须线程安全。work_item id 的记录建议用 `ctx.state`（WorkerContext 每 worker 独立）或 wid 键字典+锁——你读 `control/loop.py`/`core/context.py` 后选定，report 说明理由。
+- **proxy 不继承 Task 基类**，纯组合：显式定义 `acquire_item/prepare/after_item`，显式转发类属性 `unit/batch_unit/cold_start_before_acquire/ip_request_budget`，其余方法用 `__getattr__` 透传 inner。（若继承基类，基类默认实现会挡住 `__getattr__`，透传失效——这是坑，不许踩。）
+- **finish_work_item 的挂载点**：要求「work_item 的终态必须反映该 item 的最终处置（成功→done，放弃→failed）」。你先读 `control/task.py` 的 `after_item/on_success/on_giveup` 签名和 `control/loop.py` 的调用点，判断 `after_item` 是否能拿到最终处置结果；拿不到就改挂 `on_success`/`on_giveup`（透传 inner 返回值的同时落终态）。选择哪个钩子、为什么，写进 report。注意 inner ContactTask 未定义 `after_item`（基类默认空实现），透传时容错。
+- **prepare(config)**：调 inner.prepare；打印队列当前 pending 数（口径=shops pending 未补货数 + work_items pending 数——用现有 db 方法能拿到什么算什么，report 说明口径）。
+- **dict payload 已被 Step 1.1 验证可 1:1 替代 sqlite Row**（contact.py 全部 8 处访问均为 `item["..."]` 键访问）；站点 cold_start 对 dict 走店铺首页分支是 SPEC §3.3 已裁定的可接受差异，无需处理。
+- stop 置位时 acquire_item 最多 30s 内返回 None。
+
+### 验收
+
+- [ ] proxy 不显式 import ContactTask（对任意 inner task 成立）
+- [ ] stop 置位时 acquire_item 最多 30s 内返回 None
+- [ ] proxy 实例跨 worker 共享时无线程安全问题（条件变量、work_item id 记录）
+- [ ] `__getattr__` 透传不被任何基类默认实现挡住（proxy 不继承 Task）
+
+## 约束
+
+- 只新增 `fetcher/fetcher/control/daemon_task.py` 一个文件；不改 loop.py/engine.py/task.py/contact.py 等任何既有文件。
+- 本 Step 不写测试（测试在 Step 2.2），但你写的接口必须是可测的（DB 路径经 ctx.config.resolved_db_path() 或注入，参考既有代码怎么拿 ShopDB——读 `engine.py:48-51` 的 store_factory 和 `context.py` 再决定，report 说明）。
+- 代码风格：中文注释、文件顶部一行注释说明模块职责（项目约定）。
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.1-report.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.1-report.md
new file mode 100644
index 0000000..3964197
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.1-report.md
@@ -0,0 +1,80 @@
+# Step 2.1 报告 — DaemonTaskProxy 实现
+
+## 实现了什么
+
+新增 `fetcher/fetcher/control/daemon_task.py`（唯一改动文件），实现
+`DaemonTaskProxy(inner, queue, site, domain_suffix, db_factory=None)`：
+
+- 纯组合、不继承 Task 基类。显式定义 `acquire_item / prepare /
+  after_item / on_success / on_giveup`，显式以 property 转发类属性
+  `unit / batch_unit / cold_start_before_acquire / ip_request_budget`，
+  其余（`compose / make_stats / label / fetch / validate / summary` 等）
+  经 `__getattr__` 透传 inner。
+- `acquire_item` 三段式（SPEC §3.3）：claim → 未命中则
+  `topup_contact_work_items`（limit=消费者数×4）+ `notify_all` 重试 →
+  仍无货则条件变量 `wait(timeout=30)` 自醒，醒后先查 `ctx.stop`，
+  置位返回 None。整个「claim→topup→wait」决策在条件变量锁内完成，
+  避免「补货 notify 发生在对方 wait 之前」的丢失唤醒。
+- 不 import ContactTask，对任意 inner task 成立。
+
+## 关键设计选择及理由
+
+- **finish 钩子挂 `on_success` / `on_giveup`，不挂 `after_item`**：
+  读 `control/loop.py:347-383` 确认 `after_item(ctx, item)` 签名拿不到
+  处置结果（成功/放弃只存在于 `_process_item` 的局部 kind），而
+  `on_success`（loop.py:350）与 `on_giveup`（loop.py:380）正好是
+  终态分叉点。proxy 透传 inner 返回值的同时落
+  `finish_work_item(id, "done" / "failed")`（failed 附带
+  `{"reason", "kind"}`）。abort/stop 路径 item 保持 claimed，由
+  daemon 重启时 `reset_claimed_work_items()` 回收（Step 1.2 已有）。
+- **work_item id 按 worker 隔离用 `ctx.state`**（键
+  `daemon_work_item_id`）：`WorkerContext` 每 worker 独立
+  （engine.py:149 每 worker 新建），`ctx.state` 天然线程隔离，
+  比「wid 键字典+锁」少一个共享状态、少一把锁。claim 命中时写入，
+  `_finish` 时 pop（幂等，重复 finish 不会误伤别人的 item）。
+- **ShopDB 从 `ctx.store.db` 拿**：Engine 的 store_factory
+  （engine.py:48-51）已为每 worker 线程建好独立 ShopDB 连接
+  （sqlite 连接禁跨线程，proxy 共享实例不能自持单一连接），且与
+  inner.on_success 的写库同一连接。无 `ctx.store`（单测/直跑）时
+  退回 `db_factory` 注入或 `ShopDB(ctx.config.resolved_db_path())`，
+  按线程缓存在 `threading.local`。
+- **补货上限**：`(workers if workers > 0 else 1) * 4`。读
+  `context.py` 确认 RunConfig 上没有「按通道数解析后」的 workers
+  字段（解析发生在 `Engine._alloc_workers` 局部，不写回 config），
+  故 workers<=0 按 brief 裁定的 4×1=4 兜底。
+- **prepare**：调 `inner.prepare`（保留其 reset_in_progress 等副作用），
+  但其返回 False（现仅「pending 为空」一种情形）不退出——daemon
+  模式下队列空不是终止条件，acquire 会阻塞等货；只打印一行提示。
+  队列待办口径 = `count_pending(domain_suffix)`（shops pending 未
+  补货数）+ 直读连接 `SELECT COUNT(*) FROM work_items WHERE queue=?
+  AND status='pending'`（db 层无现成 work_items 计数方法，只读直查）。
+- **after_item 容错透传**：1688/madeinchina ContactTask 均未定义
+  after_item（基类空实现），`getattr(inner, "after_item", None)` 判空。
+- **落终态失败不打死 worker**：`_finish` 捕获异常只记日志，残留
+  claimed 由重启回收。
+
+## 验证命令与输出
+
+- `cd fetcher && python -c "from fetcher.control.daemon_task import DaemonTaskProxy"` → `import ok`
+- `cd fetcher && python -m pytest tests -x -q` → `221 passed, 2 subtests passed in 9.25s`（无回归）
+- 临时脚本冒烟（未入库，仅验证用，覆盖）：空库 topup 补货→claim 返回
+  含 domain/name/url 三键的 dict；on_success 落 done、on_giveup 落
+  failed；stop 置位立即返回 None；两线程并发等货一得一等、stop 后
+  27s 内全部退出（≤30s 自醒）；`__getattr__` 透传与类属性转发正常、
+  inner 没有的属性正确抛 AttributeError。输出：`smoke ok: [(0, 2)] 退出耗时 27.0s`
+
+## 改动的文件
+
+- 新增：`fetcher/fetcher/control/daemon_task.py`（未触碰任何既有文件）
+
+## 自查发现、疑虑
+
+- 等待中的 worker 只能靠 30s 自醒感知 stop（stop Event 与条件变量
+  不联动），最坏 30s 退出——满足验收「最多 30s 内返回 None」。
+- `prepare` 忽略 inner 的 False 是对 brief「调 inner.prepare」的主动
+  扩展裁定（daemon 语义要求），已在上方说明；若 Step 2.3 接线时
+  希望「启动即空队列直接退出」，在 CLI 侧判断即可，proxy 不需要改。
+- `on_giveup` 落 failed 时把 reason/kind 写进 result_json，便于排查；
+  done 不写 result（联系方式已在 contacts 表）。
+- 条件变量锁内执行 DB 事务（BEGIN IMMEDIATE），多 worker 串行化
+  claim/topup；单条操作毫秒级，不构成瓶颈，且换来无丢失唤醒。
diff --git a/fetcher/fetcher/control/daemon_task.py b/fetcher/fetcher/control/daemon_task.py
new file mode 100644
index 0000000..629b52c
--- /dev/null
+++ b/fetcher/fetcher/control/daemon_task.py
@@ -0,0 +1,195 @@
+# -*- coding: utf-8 -*-
+"""DaemonTaskProxy：daemon 模式的 Task 代理（SPEC §3.3）。
+
+包装既有 Task（P0 为 ContactTask），把工作项来源从「inner 自己 claim
+shops」换成「从 work_items 表认领」：acquire_item 三段式
+（claim → 补货 → 条件变量等货），只有 stop 置位才返回 None（worker
+退出），否则阻塞等货——daemon 模式下「队列空」不等于「任务结束」。
+
+纯组合不继承 Task 基类：基类默认实现会挡住 __getattr__ 使透传失效，
+故显式定义 acquire_item/prepare/after_item 与 on_success/on_giveup
+（落终态钩子），类属性显式转发，其余方法经 __getattr__ 透传 inner。
+
+线程安全：proxy 实例被 Engine 跨 worker 线程共享——条件变量负责
+等货/补货通知；每 worker 认领的 work_item id 记在该 worker 自己的
+ctx.state 上（WorkerContext 每 worker 独立），天然隔离无需加锁。
+"""
+
+from __future__ import annotations
+
+import threading
+
+from fetcher.db import ShopDB
+
+# 等货条件变量自醒超时（秒）：保证 stop 置位后 acquire_item 最多 30s 内返回
+_WAIT_TIMEOUT = 30.0
+
+# ctx.state 上记录当前 worker 认领的 work_item id 的键
+_STATE_KEY = "daemon_work_item_id"
+
+
+class DaemonTaskProxy:
+    """Task 协议代理：工作项来源切换为 work_items 表（daemon 常驻等货）。
+
+    用法：
+        task = DaemonTaskProxy(inner=ContactTask(), queue="contact",
+                               site="1688", domain_suffix="1688.com")
+        engine = Engine(cfg, task=task, ...)
+    """
+
+    def __init__(self, inner, queue: str, site: str, domain_suffix: str,
+                 db_factory=None):
+        self._inner = inner
+        self._queue = queue
+        self._site = site
+        self._domain_suffix = domain_suffix
+        # 测试注入用 DB 工厂（无参可调）；None=按 ctx 取（见 _db）
+        self._db_factory = db_factory
+        # 等货/补货条件变量（跨 worker 共享，持有锁完成 claim→wait 决策，
+        # 避免「补货 notify 发生在对方 wait 之前」的丢失唤醒）
+        self._cond = threading.Condition()
+        # 无 ctx.store 时按线程缓存的自建 ShopDB（sqlite 连接不可跨线程）
+        self._tls = threading.local()
+
+    # ---- 显式转发的类属性（loop/engine 按实例属性读取）----
+
+    @property
+    def unit(self):
+        return self._inner.unit
+
+    @property
+    def batch_unit(self):
+        return self._inner.batch_unit
+
+    @property
+    def cold_start_before_acquire(self):
+        return self._inner.cold_start_before_acquire
+
+    @property
+    def ip_request_budget(self):
+        return self._inner.ip_request_budget
+
+    # ---- 其余方法透传 inner（不继承基类，__getattr__ 不会被挡住）----
+
+    def __getattr__(self, name):
+        # 下划线开头的属性不应走到这里（防 _inner 未就绪时无限递归）
+        if name.startswith("_"):
+            raise AttributeError(name)
+        return getattr(self._inner, name)
+
+    # ---- DB 访问 ----
+
+    def _db(self, ctx) -> ShopDB:
+        """取当前线程可用的 ShopDB。
+
+        优先用 ctx.store.db（Engine 的 store_factory 已为每 worker 线程
+        建好独立连接，与 inner.on_success 的写库用同一连接）；无 store
+        （单测/直跑）时经 db_factory 或 config.resolved_db_path() 自建，
+        按线程缓存（sqlite 连接禁止跨线程使用）。
+        """
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
+        """补货上限 = 消费者数 × 4；workers<=0（按通道数解析）时 proxy
+        拿不到解析后的通道数，按 1 个消费者兜底（=4）。"""
+        workers = getattr(ctx.config, "workers", 0) or 0
+        return (workers if workers > 0 else 1) * 4
+
+    # ---- main 阶段 ----
+
+    def prepare(self, config) -> bool:
+        """调 inner.prepare（保留其重置/打印副作用），再打印队列待办数。
+
+        口径：shops pending 未补货数（count_pending）+ work_items 该队列
+        pending 数（db 层无现成计数方法，直读连接 SELECT COUNT）。
+        inner 返回 False（现仅有「pending 为空」一种情形）不退出：
+        daemon 模式下队列空不是终止条件，acquire_item 会阻塞等货。
+        """
+        if not self._inner.prepare(config):
+            print("[daemon] inner.prepare 报告队列暂空，继续常驻等货")
+        db = ShopDB(config.resolved_db_path())
+        try:
+            shops_pending = db.count_pending(self._domain_suffix)
+            items_pending = db.conn.execute(
+                "SELECT COUNT(*) FROM work_items"
+                " WHERE queue=? AND status='pending'",
+                (self._queue,)).fetchone()[0]
+        finally:
+            db.close()
+        print(f"[daemon] 队列 {self._queue}: 待补货店铺 {shops_pending} 个 + "
+              f"待认领工作项 {items_pending} 个")
+        return True
+
+    # ---- worker 循环：工作项认领（三段式）----
+
+    def acquire_item(self, ctx):
+        """认领一个工作项；仅 stop 置位时返回 None，否则阻塞等货。
+
+        1. claim 命中 → 记录 work_item id 后返回 payload dict
+           （必含 domain/name/url 三键，由 claim_work_item 保证）；
+        2. 未命中 → 补货（limit=消费者数×4），补到则 notify_all 唤醒
+           等货的其他 worker 并重试 claim；
+        3. 仍无货 → 条件变量 wait（30s 自醒兜底），醒后先查 stop。
+        """
+        consumer_id = f"w{ctx.wid}"
+        db = self._db(ctx)
+        limit = self._topup_limit(ctx)
+        with self._cond:
+            while True:
+                if ctx.stopped():
+                    return None
+                item = db.claim_work_item(self._queue, consumer_id)
+                if item is not None:
+                    # 记在本 worker 自己的 ctx.state 上，跨 worker 天然隔离
+                    ctx.state[_STATE_KEY] = item["id"]
+                    return item
+                n = db.topup_contact_work_items(
+                    self._queue, self._site, self._domain_suffix, limit=limit)
+                if n:
+                    self._cond.notify_all()
+                    continue
+                self._cond.wait(timeout=_WAIT_TIMEOUT)
+                if ctx.stopped():
+                    return None
+
+    # ---- 终态钩子：work_item 终态必须反映 item 的最终处置 ----
+    # after_item(ctx, item) 拿不到处置结果（成功/放弃），故挂在
+    # on_success/on_giveup 上：透传 inner 返回值的同时落终态。
+
+    def on_success(self, ctx, item, result) -> int:
+        count = self._inner.on_success(ctx, item, result)
+        self._finish(ctx, "done")
+        return count
+
+    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
+        phrase = self._inner.on_giveup(ctx, item, reason, kind)
+        self._finish(ctx, "failed", result={"reason": reason, "kind": kind})
+        return phrase
+
+    def _finish(self, ctx, status: str, result: dict | None = None):
+        """把当前 worker 认领的 work_item 落终态（done/failed）。
+
+        无认领记录（如 inner 自行 acquire 的路径）时跳过；落库失败只记
+        日志不打死 worker（残留的 claimed 由 daemon 重启时
+        reset_claimed_work_items 回收）。
+        """
+        item_id = ctx.state.pop(_STATE_KEY, None)
+        if item_id is None:
+            return
+        try:
+            self._db(ctx).finish_work_item(item_id, status, result)
+        except Exception as e:  # noqa: BLE001
+            ctx.log(f"[!] 工作项 #{item_id} 落终态 {status} 失败: {e}")
+
+    def after_item(self, ctx, item) -> None:
+        # inner 可能未定义 after_item（基类默认空实现），容错透传
+        hook = getattr(self._inner, "after_item", None)
+        if hook is not None:
+            hook(ctx, item)
