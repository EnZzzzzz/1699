# -*- coding: utf-8 -*-
"""队列路由表 + 冷却感知等待函数 + QueueRouter（P3 Step 3.1）。

QueueRouter 取代 DaemonTaskProxy：跨队列认领（资源满足 ∧ 站点冷却到期）
→ 路由到 item 所属队列的 task。daemon 常驻等货；无平台依赖，仅 daemon 用。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from fetcher.db import ShopDB

# 等货条件变量自醒超时（秒）：保证 stop 置位后 acquire_item 最多 30s 内返回
_WAIT_TIMEOUT = 30.0

# ctx.state 上记录当前 worker 认领的 work_item id 的键
_STATE_KEY = "daemon_work_item_id"


def consumer_id_for(ctx) -> str:
    """按消费者类型生成 consumer_id：browser→"w{wid}"、local→"local{wid}"。

    consumer_status 主键/心跳/退出清理都以它为准（P4-1 起 local 消费者
    与浏览器消费者同池并存，命名必须区分）。
    """
    prefix = "local" if getattr(ctx, "consumer_kind", "browser") == "local" \
        else "w"
    return f"{prefix}{ctx.wid}"


@dataclass
class QueueSpec:
    """队列注册表条目。"""
    queue: str                    # "crawl_1688_contact" / ...
    site: str                     # 站点注册名 "1688" / "madeinchina"
    task: object = None             # 该队列工作项的执行流水线（Task 协议）
    topup: object | None = None   # Callable[[ShopDB, int], int] | None；补货函数
    domain_suffix: str = ""       # contact 类 topup 用；启动 reset 用
    requires: set[str] = field(default_factory=lambda: {"channel", "browser"})


def eligible_queues(registry, ctx, now: float) -> list[str]:
    """当前消费者可认领的队列名列表：资源满足 ∧ 该站点/队列冷却已到期。

    registry: 可迭代的 QueueSpec。
    ctx: 有 .resources（set）与 .cooldown_until（dict[str, float]）的对象。
    纯函数，无副作用；返回按注册表顺序。

    冷却键泛化（P4-1）：site 非空用 site 名；site 为空（wa_check 等
    非站点队列）退 queue 名。
    """
    result = []
    for q in registry:
        if q.requires <= ctx.resources \
                and now >= ctx.cooldown_until.get(q.site or q.queue, 0):
            result.append(q.queue)
    return result


def condvar_timeout_multi(cooldown_until: dict[str, float],
                          keys: list[str], now: float,
                          cap: float = 30.0) -> float:
    """多队列 condvar timeout：取所有冷却中键的剩余时间的最小值。

    无任何键在冷却 → cap。keys 为冷却键列表（site 或 queue 名，
    由调用方展开 spec.site or spec.queue）。
    """
    min_remaining = None
    for key in keys:
        deadline = cooldown_until.get(key, 0)
        if now < deadline:
            remaining = deadline - now
            if min_remaining is None or remaining < min_remaining:
                min_remaining = remaining
    if min_remaining is None:
        return cap
    return min_remaining if min_remaining < cap else cap


class QueueRouter:
    """Task 协议代理：跨队列认领（资源满足 ∧ 站点冷却到期）→ 路由到 item
    所属队列的 task。

    acquire_item 三段式：claim_next_eligible → 各队列 topup → condvar 挂起。
    stop 置位才返回 None。on_success/on_giveup 路由到 item 所属队列的 task
    后落 work_items 终态。per-item 方法全部经 ctx.state 路由（WorkerContext
    每 worker 独立，天然线程安全）。

    用法：
        registry = [QueueSpec(queue="crawl_1688_contact", site="1688",
                               task=ContactTask(), topup=..., domain_suffix=".1688.com"),
                    QueueSpec(queue="crawl_mic_contact", site="madeinchina",
                               task=MICContactTask(), topup=..., domain_suffix=".cn.made-in-china.com")]
        router = QueueRouter(registry)
        engine = Engine(cfg, task=router, ...)
    """

    # per-worker 动态属性（类属性，loop 在 acquire 前后直接读）
    unit = "项"
    batch_unit = ""
    cold_start_before_acquire = False

    def __init__(self, registry: list[QueueSpec], cond=None,
                 db_factory=None, status_store=None):
        self._registry = {spec.queue: spec for spec in registry}
        self._specs = registry  # 保持顺序
        self._cond = cond or threading.Condition()
        self._db_factory = db_factory
        self._status_store = status_store
        self._tls = threading.local()

    def _status(self, ctx) -> object | None:
        """取当前 worker 的状态写入口（ConsumerStatusStore 或 None）。

        优先 ctx.status_store（loop 冷却上报用同一 store）；无则回退
        本 router 持有的 store 并注入 ctx（供 loop._cooldown 使用）。
        """
        store = getattr(ctx, "status_store", None)
        if store is None and self._status_store is not None:
            ctx.status_store = self._status_store
            store = self._status_store
        return store

    @property
    def ip_request_budget(self):
        """必须 per-site：返回 None，loop 走 budget_for(ctx)。"""
        return None

    def budget_for(self, ctx) -> int | None:
        """当前 item 所属 queue 的 task 的 IP 请求预算。"""
        queue_name = ctx.state.get("queue")
        if queue_name and queue_name in self._registry:
            return self._registry[queue_name].task.budget_for(ctx)
        return None

    def rest_counter(self, stats: dict) -> int:
        """长休息计数基准：委托给首个注册 task。"""
        if self._specs:
            return self._specs[0].task.rest_counter(stats)
        return 0

    # ---- 执行侧路由：per-item 方法经 ctx.state["queue"] 路由 ----

    def _task_for(self, ctx):
        """取当前 item 所属队列的 task；无队列取首个注册 spec 的 task（兜底）。"""
        queue_name = ctx.state.get("queue")
        if queue_name and queue_name in self._registry:
            return self._registry[queue_name].task
        # 兜底：首个注册 spec
        if self._specs:
            return self._specs[0].task
        raise RuntimeError("QueueRouter 注册表为空")

    def fetch(self, ctx, item):
        return self._task_for(ctx).fetch(ctx, item)

    def validate(self, ctx, item, result):
        return self._task_for(ctx).validate(ctx, item, result)

    def cold_start(self, ctx, item):
        return self._task_for(ctx).cold_start(ctx, item)

    def _task_for_static(self):
        """无 ctx 参数的静态路由（label/giveup_cost）：用线程本地缓存。"""
        queue_name = getattr(self._tls, "last_queue", None)
        if queue_name and queue_name in self._registry:
            return self._registry[queue_name].task
        if self._specs:
            return self._specs[0].task
        raise RuntimeError("QueueRouter 注册表为空")

    def label(self, item):
        return self._task_for_static().label(item)

    def on_abort(self, ctx, item):
        return self._task_for(ctx).on_abort(ctx, item)

    def giveup_cost(self, item):
        return self._task_for_static().giveup_cost(item)

    def after_item(self, ctx, item):
        return self._task_for(ctx).after_item(ctx, item)

    def empty_message(self):
        if self._specs:
            return self._specs[0].task.empty_message()
        return "没有待做的任务了"

    def make_stats(self):
        """合并所有注册队列 task 的统计键。

        各 task 的 on_success/on_giveup 通过 ctx.state["task"]["stats"]
        读写统计，键集合必须覆盖所有可能路由到的 task 的预期键。
        """
        merged = {}
        for spec in self._specs:
            merged.update(spec.task.make_stats())
        return merged

    def compose(self, wid: int, f: dict) -> str:
        # 简单方案：委托首个注册 task（多队列下统计口径待后续细化）
        if self._specs:
            return self._specs[0].task.compose(wid, f)
        return str(f.get("line", ""))

    def summary(self, all_stats: dict, db_path=None) -> str:
        # 简单方案：委托首个注册 task（多队列下统计口径待后续细化）
        if self._specs:
            return self._specs[0].task.summary(all_stats, db_path=db_path)
        return str(all_stats)

    # ---- DB 访问 ----

    def _db(self, ctx) -> ShopDB:
        """取当前线程可用的 ShopDB。"""
        if getattr(ctx, "store", None) is not None:
            return ctx.store.db
        db = getattr(self._tls, "db", None)
        if db is None:
            factory = self._db_factory or (
                lambda: ShopDB(ctx.config.resolved_db_path()))
            db = self._tls.db = factory()
        return db

    def _topup_limit(self, ctx) -> int:
        """补货上限 = 消费者数 × 4。"""
        workers = getattr(ctx.config, "workers", 0) or 0
        return (workers if workers > 0 else 1) * 4

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        """各队列 task.prepare + 打印每队列待办。"""
        all_ok = True
        db = ShopDB(config.resolved_db_path())
        try:
            for spec in self._specs:
                if not spec.task.prepare(config):
                    print(f"[daemon] {spec.queue} inner.prepare 报告队列暂空，"
                          f"继续常驻等货")
                shops_pending = db.count_pending(spec.domain_suffix)
                items_pending = db.conn.execute(
                    "SELECT COUNT(*) FROM work_items WHERE queue=? "
                    "AND status='pending'", (spec.queue,)).fetchone()[0]
                print(f"[daemon] 队列 {spec.queue}: 待补货店铺 {shops_pending} 个 + "
                      f"待认领工作项 {items_pending} 个")
        finally:
            db.close()
        return True

    # ---- worker 循环：工作项认领（三段式）----

    def acquire_item(self, ctx):
        """跨队列认领工作项；仅 stop 置位时返回 None，否则阻塞等货。

        1. eligible_queues → claim_next_eligible（跨队列 FIFO）→ 命中返回 payload
        2. 未命中 → topup 只对冷却到期的 contact 队列逐队列补货 → 补到则 notify_all + 重试
        3. 仍无 → condvar wait（多队列取各冷却中最小值，无冷却 30s）→ 醒后查 stop
        """
        consumer_id = consumer_id_for(ctx)
        db = self._db(ctx)
        limit = self._topup_limit(ctx)
        with self._cond:
            while True:
                if ctx.stopped():
                    return None
                now = time.time()
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
                        # 保留 id 键：测试/DB 验证用（site 插件只依赖 domain/name/url）
                        payload["id"] = item["id"]
                        # P4 批次：把 batch_id 注入 payload（feeder 续喂/
                        # 补插继承用；daemon 自喂为 None 时不注入）
                        if item.get("batch_id") is not None:
                            payload["batch_id"] = item["batch_id"]
                        # P4 daemon 可观测：claim 即时上报（队列/工作项/批次）
                        store = self._status(ctx)
                        if store is not None:
                            try:
                                store.upsert(
                                    consumer_id, ctx.consumer_kind,
                                    queue=item["queue"],
                                    item_id=item["id"],
                                    batch_id=item.get("batch_id"),
                                    cooldowns=ctx.cooldown_until)
                            except Exception as e:  # noqa: BLE001
                                ctx.log(f"[!] claim 状态上报失败: {e}")
                        from datetime import datetime
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ctx.log(f"[claim] queue={item['queue']} item={item['id']} "
                                f"site={item['site']} @{ts}")
                        return payload

                # topup：只对冷却到期的 contact 队列补货
                any_topped = False
                for spec in self._specs:
                    if spec.topup is not None \
                            and now >= ctx.cooldown_until.get(
                                spec.site or spec.queue, 0):
                        n = spec.topup(db, limit)
                        if n:
                            any_topped = True
                if any_topped:
                    self._cond.notify_all()
                    continue

                # condvar wait：多队列取各冷却中剩余的最小值
                # （冷却键泛化 P4-1：site 或 queue 名）
                timeout = condvar_timeout_multi(
                    ctx.cooldown_until,
                    [spec.site or spec.queue for spec in self._specs],
                    now, cap=_WAIT_TIMEOUT)
                self._cond.wait(timeout=timeout)
                if ctx.stopped():
                    return None

    # ---- 终态钩子 ----

    def on_success(self, ctx, item, result) -> int:
        count = self._task_for(ctx).on_success(ctx, item, result)
        self._finish(ctx, "done")
        return count

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        phrase = self._task_for(ctx).on_giveup(ctx, item, reason, kind)
        self._finish(ctx, "failed", result={"reason": reason, "kind": kind})
        return phrase

    def release_item(self, ctx) -> str:
        """当前 worker 的 item 释放回 pending（attempts+1，耗尽置 failed）。

        返回终态（"pending"/"failed"）供日志；无认领记录时返回 ""。
        """
        item_id = ctx.state.pop(_STATE_KEY, None)
        if item_id is None:
            return ""
        try:
            status = self._db(ctx).release_work_item(item_id, max_attempts=3)
            from datetime import datetime
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if status == "failed":
                ctx.log(f"[release] item={item_id} status=failed "
                        f"(attempts exhausted) @{ts}")
                item = ctx.state.get("item")
                if item is not None:
                    self._task_for(ctx).refill_item(ctx, item)
            else:
                ctx.log(f"[release] item={item_id} status={status} @{ts}")
            return status
        except Exception as e:  # noqa: BLE001
            ctx.log(f"[!] 工作项 #{item_id} 释放失败: {e}")
            return ""

    def timeout_release(self, ctx) -> str:
        """看门狗超时释放：当前 worker 认领的 item 强制回 pending（attempts+1，
        耗尽置 failed）。与 release_item 的差异：由看门狗线程调用（非 worker
        自己），并清理 consumer_status 的 current 字段。无认领记录返回 ""
        """
        item_id = ctx.state.pop(_STATE_KEY, None)
        if item_id is None:
            return ""
        try:
            status = self._db(ctx).release_work_item(item_id, max_attempts=3)
            store = self._status(ctx)
            if store is not None:
                try:
                    store.upsert(
                        consumer_id_for(ctx),
                        getattr(ctx, "consumer_kind", "browser"),
                        queue=None, item_id=None, batch_id=None,
                        cooldowns=ctx.cooldown_until)
                except Exception as e:  # noqa: BLE001
                    ctx.log(f"[!] watchdog 状态上报失败: {e}")
            from datetime import datetime
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ctx.log(f"[watchdog] item={item_id} 超时释放 status={status} @{ts}")
            return status
        except Exception as e:  # noqa: BLE001
            ctx.log(f"[!] watchdog 释放工作项 #{item_id} 失败: {e}")
            return ""

    def _finish(self, ctx, status: str, result: dict | None = None):
        """把当前 worker 认领的 work_item 落终态（done/failed）。"""
        item_id = ctx.state.pop(_STATE_KEY, None)
        if item_id is None:
            return
        # 任务侧侧车（FbPostTask 微信/TG/邀请链接等观测副产物）：on_success
        # 经 ctx.state["result_json"] 带上，_finish 落库（仅当调用方未显式
        # 给 result 时生效；既有任务不设该键零影响）。
        if result is None:
            result = ctx.state.pop("result_json", None)
        try:
            self._db(ctx).finish_work_item(item_id, status, result)
            # P4 daemon 可观测：finish 清空 current_*（保留心跳字段）
            store = self._status(ctx)
            if store is not None:
                try:
                    store.upsert(
                        consumer_id_for(ctx), ctx.consumer_kind,
                        queue=None, item_id=None, batch_id=None,
                        cooldowns=ctx.cooldown_until)
                except Exception as e:  # noqa: BLE001
                    ctx.log(f"[!] finish 状态上报失败: {e}")
            from datetime import datetime
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ctx.log(f"[finish] item={item_id} status={status} @{ts}")
        except Exception as e:  # noqa: BLE001
            ctx.log(f"[!] 工作项 #{item_id} 落终态 {status} 失败: {e}")
