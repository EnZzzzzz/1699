# -*- coding: utf-8 -*-
"""DaemonTaskProxy：daemon 模式的 Task 代理（SPEC §3.3）。

包装既有 Task（P0 为 ContactTask），把工作项来源从「inner 自己 claim
shops」换成「从 work_items 表认领」：acquire_item 三段式
（claim → 补货 → 条件变量等货），只有 stop 置位才返回 None（worker
退出），否则阻塞等货——daemon 模式下「队列空」不等于「任务结束」。

纯组合不继承 Task 基类：基类默认实现会挡住 __getattr__ 使透传失效，
故显式定义 acquire_item/prepare/after_item 与 on_success/on_giveup
（落终态钩子），类属性显式转发，其余方法经 __getattr__ 透传 inner。

线程安全：proxy 实例被 Engine 跨 worker 线程共享——条件变量负责
等货/补货通知；每 worker 认领的 work_item id 记在该 worker 自己的
ctx.state 上（WorkerContext 每 worker 独立），天然隔离无需加锁。
"""

from __future__ import annotations

import threading
import time

from fetcher.control.queue_router import condvar_timeout
from fetcher.db import ShopDB

# 等货条件变量自醒超时（秒）：保证 stop 置位后 acquire_item 最多 30s 内返回
_WAIT_TIMEOUT = 30.0

# ctx.state 上记录当前 worker 认领的 work_item id 的键
_STATE_KEY = "daemon_work_item_id"


class DaemonTaskProxy:
    """Task 协议代理：工作项来源切换为 work_items 表（daemon 常驻等货）。

    用法：
        task = DaemonTaskProxy(inner=ContactTask(), queue="crawl_1688_contact",
                               site="1688", domain_suffix=".1688.com")
        engine = Engine(cfg, task=task, ...)
    """

    def __init__(self, inner, queue: str, site: str, domain_suffix: str,
                 db_factory=None):
        self._inner = inner
        self._queue = queue
        self._site = site
        self._domain_suffix = domain_suffix
        # 测试注入用 DB 工厂（无参可调）；None=按 ctx 取（见 _db）
        self._db_factory = db_factory
        # 等货/补货条件变量（跨 worker 共享，持有锁完成 claim→wait 决策，
        # 避免「补货 notify 发生在对方 wait 之前」的丢失唤醒）
        self._cond = threading.Condition()
        # 无 ctx.store 时按线程缓存的自建 ShopDB（sqlite 连接不可跨线程）
        self._tls = threading.local()

    # ---- 显式转发的类属性（loop/engine 按实例属性读取）----

    @property
    def unit(self):
        return self._inner.unit

    @property
    def batch_unit(self):
        return self._inner.batch_unit

    @property
    def cold_start_before_acquire(self):
        return self._inner.cold_start_before_acquire

    @property
    def ip_request_budget(self):
        return self._inner.ip_request_budget

    # ---- 其余方法透传 inner（不继承基类，__getattr__ 不会被挡住）----

    def __getattr__(self, name):
        # 下划线开头的属性不应走到这里（防 _inner 未就绪时无限递归）
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    # ---- DB 访问 ----

    def _db(self, ctx) -> ShopDB:
        """取当前线程可用的 ShopDB。

        优先用 ctx.store.db（Engine 的 store_factory 已为每 worker 线程
        建好独立连接，与 inner.on_success 的写库用同一连接）；无 store
        （单测/直跑）时经 db_factory 或 config.resolved_db_path() 自建，
        按线程缓存（sqlite 连接禁止跨线程使用）。
        """
        if getattr(ctx, "store", None) is not None:
            return ctx.store.db
        db = getattr(self._tls, "db", None)
        if db is None:
            factory = self._db_factory or (
                lambda: ShopDB(ctx.config.resolved_db_path()))
            db = self._tls.db = factory()
        return db

    def _topup_limit(self, ctx) -> int:
        """补货上限 = 消费者数 × 4；workers<=0（按通道数解析）时 proxy
        拿不到解析后的通道数，按 1 个消费者兜底（=4）。"""
        workers = getattr(ctx.config, "workers", 0) or 0
        return (workers if workers > 0 else 1) * 4

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        """调 inner.prepare（保留其重置/打印副作用），再打印队列待办数。

        口径：shops pending 未补货数（count_pending）+ work_items 该队列
        pending 数（db 层无现成计数方法，直读连接 SELECT COUNT）。
        inner 返回 False（现仅有「pending 为空」一种情形）不退出：
        daemon 模式下队列空不是终止条件，acquire_item 会阻塞等货。
        """
        if not self._inner.prepare(config):
            print("[daemon] inner.prepare 报告队列暂空，继续常驻等货")
        db = ShopDB(config.resolved_db_path())
        try:
            shops_pending = db.count_pending(self._domain_suffix)
            items_pending = db.conn.execute(
                "SELECT COUNT(*) FROM work_items"
                " WHERE queue=? AND status='pending'",
                (self._queue,)).fetchone()[0]
        finally:
            db.close()
        print(f"[daemon] 队列 {self._queue}: 待补货店铺 {shops_pending} 个 + "
              f"待认领工作项 {items_pending} 个")
        return True

    # ---- worker 循环：工作项认领（三段式）----

    def acquire_item(self, ctx):
        """认领一个工作项；仅 stop 置位时返回 None，否则阻塞等货。

        1. 冷却过滤：claim 前查冷却（site 键），冷却中不 claim 不 topup，
           直接进 condvar wait（timeout 经 condvar_timeout 计算）；
        2. claim 命中 → 记录 work_item id + active_site 后返回 payload；
        3. 未命中 → 补货（limit=消费者数×4），补到则 notify_all 并重试；
        4. 仍无货 → 条件变量 wait（30s 自醒兜底），醒后先查 stop。
        """
        consumer_id = f"w{ctx.wid}"
        db = self._db(ctx)
        limit = self._topup_limit(ctx)
        with self._cond:
            while True:
                if ctx.stopped():
                    return None
                now = time.time()
                # 冷却中：不 claim 不 topup，直接进 condvar wait
                if now < ctx.cooldown_until.get(self._site, 0):
                    timeout = condvar_timeout(
                        ctx.cooldown_until, self._site, now)
                    self._cond.wait(timeout=timeout)
                    if ctx.stopped():
                        return None
                    continue
                item = db.claim_work_item(self._queue, consumer_id)
                if item is not None:
                    # 记在本 worker 自己的 ctx.state 上，跨 worker 天然隔离
                    ctx.state[_STATE_KEY] = item["id"]
                    ctx.state["active_site"] = self._site
                    return item
                n = db.topup_contact_work_items(
                    self._queue, self._site, self._domain_suffix, limit=limit)
                if n:
                    self._cond.notify_all()
                    continue
                self._cond.wait(timeout=_WAIT_TIMEOUT)
                if ctx.stopped():
                    return None

    # ---- 终态钩子：work_item 终态必须反映 item 的最终处置 ----
    # after_item(ctx, item) 拿不到处置结果（成功/放弃），故挂在
    # on_success/on_giveup 上：透传 inner 返回值的同时落终态。

    def on_success(self, ctx, item, result) -> int:
        count = self._inner.on_success(ctx, item, result)
        self._finish(ctx, "done")
        return count

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        phrase = self._inner.on_giveup(ctx, item, reason, kind)
        self._finish(ctx, "failed", result={"reason": reason, "kind": kind})
        return phrase

    def _finish(self, ctx, status: str, result: dict | None = None):
        """把当前 worker 认领的 work_item 落终态（done/failed）。

        无认领记录（如 inner 自行 acquire 的路径）时跳过；落库失败只记
        日志不打死 worker（残留的 claimed 由 daemon 重启时
        reset_claimed_work_items 回收）。
        """
        item_id = ctx.state.pop(_STATE_KEY, None)
        if item_id is None:
            return
        try:
            self._db(ctx).finish_work_item(item_id, status, result)
        except Exception as e:  # noqa: BLE001
            ctx.log(f"[!] 工作项 #{item_id} 落终态 {status} 失败: {e}")

    def after_item(self, ctx, item) -> None:
        # inner 可能未定义 after_item（基类默认空实现），容错透传
        hook = getattr(self._inner, "after_item", None)
        if hook is not None:
            hook(ctx, item)
