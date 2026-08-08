# -*- coding: utf-8 -*-
"""P4-1 Step 1.1: LocalExecutor 消费者 + requires="local" 互斥测试。

覆盖：eligible_queues 资源互斥与冷却键泛化、Engine local_workers 装配、
LocalLoop 执行循环。真实临时 sqlite + 假 task/loop，不起浏览器/网络。
"""

import tempfile
import threading
import unittest
from pathlib import Path

from fetcher import RunConfig, ShopDB, WorkerContext
from fetcher.control.engine import Engine
from fetcher.control.local_loop import LocalLoop
from fetcher.control.queue_router import (
    QueueRouter,
    QueueSpec,
    eligible_queues,
)
from fetcher.core.types import ActionResult, Outcome

# =====================================================================
# 1. 结构性互斥 + 冷却键泛化（纯函数）
# =====================================================================


class EligibleQueuesLocalTest(unittest.TestCase):
    """browser/local 消费者跨 requires 互斥 + 冷却键泛化。"""

    def test_consumer_id_prefix_by_kind(self):
        """consumer_id：browser→w{wid}、local→local{wid}（心跳/清理命名基准）。"""
        from fetcher.control.queue_router import consumer_id_for
        b = type("Ctx", (), {"consumer_kind": "browser", "wid": 3})()
        l = type("Ctx", (), {"consumer_kind": "local", "wid": 1})()
        self.assertEqual(consumer_id_for(b), "w3")
        self.assertEqual(consumer_id_for(l), "local1")

    def _registry(self):
        return [
            # browser 队列（现状）
            QueueSpec(queue="crawl_1688_contact", site="1688",
                      requires={"channel", "browser"}),
            # wa_check 本地队列：site 为空（非站点），requires local
            QueueSpec(queue="wa_check", site=None,
                      requires={"local"}),
        ]

    def _ctx(self, resources, cooldown_until=None):
        return type("FakeCtx", (), {
            "resources": resources,
            "cooldown_until": cooldown_until or {},
        })()

    def test_browser_consumer_cannot_see_local_queue(self):
        """browser 消费者看不到 requires={"local"} 的 wa_check 队列。"""
        ctx = self._ctx({"channel", "browser"})
        queues = eligible_queues(self._registry(), ctx, 100.0)
        self.assertIn("crawl_1688_contact", queues)
        self.assertNotIn("wa_check", queues)

    def test_local_consumer_cannot_see_browser_queue(self):
        """local 消费者看不到 requires={"channel","browser"} 的队列。"""
        ctx = self._ctx({"local"})
        queues = eligible_queues(self._registry(), ctx, 100.0)
        self.assertNotIn("crawl_1688_contact", queues)
        self.assertIn("wa_check", queues)

    def test_cooldown_key_falls_back_to_queue_name(self):
        """wa_check（site=None）冷却用 queue 名登记/查询。"""
        # 冷却中：site 为 None 的队列，冷却键取 queue 名
        ctx = self._ctx({"local"}, cooldown_until={"wa_check": 200.0})
        queues = eligible_queues(self._registry(), ctx, 100.0)
        self.assertEqual(queues, [])  # wa_check 冷却中 → 不可见

        ctx2 = self._ctx({"local"}, cooldown_until={"wa_check": 50.0})
        queues2 = eligible_queues(self._registry(), ctx2, 100.0)
        self.assertEqual(queues2, ["wa_check"])  # 到期 → 可见


# =====================================================================
# 2. LocalLoop 执行循环
# =====================================================================


class _FakeLocalTask:
    """可编程假 Task：模拟 wa_check 的 acquire→fetch→on_success 链。"""

    def __init__(self, results=None):
        self._results = list(results or [])
        self._i = 0
        self.calls = []
        self.stats = {"checked": 0}

    def acquire_item(self, ctx):
        if ctx.stopped():
            return None
        if self._i >= len(self._results):
            return None  # 队列空 → worker 退出
        item = {"id": self._i}
        self._i += 1
        return item

    def fetch(self, ctx, item):
        self.calls.append(("fetch", item["id"]))
        return self._results[item["id"]]

    def on_success(self, ctx, item, result):
        ctx.state["task"]["stats"]["checked"] += 1
        return 1

    def on_giveup(self, ctx, item, reason, kind):
        self.calls.append(("giveup", item["id"], kind))
        return ""

    def after_item(self, ctx, item):
        pass

    def make_stats(self):
        return {"checked": 0}


def _ok():
    return ActionResult(Outcome.OK, "ok")


class LocalLoopTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _ctx(self):
        return WorkerContext(config=RunConfig(), stop=threading.Event(),
                             wid=0, log=lambda m: None)

    def test_runs_success_chain(self):
        """OK 结果逐项 on_success，队列空后退出。"""
        task = _FakeLocalTask([_ok(), _ok()])
        loop = LocalLoop(self._ctx(), task)
        stats = loop.run()
        self.assertEqual(stats["checked"], 2)

    def test_fatal_stops(self):
        """FATAL 结果 → on_giveup(fatal) 后停止，不再取下一项。"""
        fatal = ActionResult(Outcome.FATAL, "未登录")
        task = _FakeLocalTask([_ok(), fatal, _ok()])
        loop = LocalLoop(self._ctx(), task)
        loop.run()
        self.assertEqual(task.calls, [("fetch", 0),
                                      ("fetch", 1),
                                      ("giveup", 1, "fatal")])

    def test_skipped_stops(self):
        """SKIPPED（停止信号）→ 立即收工。"""
        skipped = ActionResult.skipped("被停止")
        task = _FakeLocalTask([skipped, _ok()])
        loop = LocalLoop(self._ctx(), task)
        stats = loop.run()
        self.assertEqual(stats["checked"], 0)

    def test_net_error_is_giveup_net(self):
        """NET_ERROR → on_giveup(net)，继续下一项。"""
        net = ActionResult.net_error("连接失败")
        task = _FakeLocalTask([net, _ok()])
        loop = LocalLoop(self._ctx(), task)
        stats = loop.run()
        self.assertEqual(stats["checked"], 1)
        self.assertEqual(task.calls, [("fetch", 0),
                                      ("giveup", 0, "net"),
                                      ("fetch", 1)])

    def test_stopped_event_breaks_loop(self):
        """stop 置位后 acquire 返回 None → 退出。"""
        stop = threading.Event()
        ctx = WorkerContext(config=RunConfig(), stop=stop, wid=0,
                            log=lambda m: None)
        task = _FakeLocalTask([_ok()])
        stop.set()  # 尚未开始就停止
        loop = LocalLoop(ctx, task)
        stats = loop.run()
        self.assertEqual(stats["checked"], 0)


# =====================================================================
# 3. Engine local_workers 装配
# =====================================================================


class _FakeLoop:
    instances = []

    def __init__(self, ctx, task, policy=None, board=None, seed_kit=None,
                 **kw):
        self.ctx = ctx
        _FakeLoop.instances.append(self)

    def run(self):
        return {}


class _FakeTask:
    name = "fake"

    def make_stats(self):
        return {}

    def compose(self, wid, f):
        return str(f.get("line", ""))

    def summary(self, all_stats, db_path=None):
        return "ok"


class EngineLocalWorkerTest(unittest.TestCase):
    """Engine local_workers>0 时起无浏览器 local 线程，浏览器 worker 不受影响。"""

    def setUp(self):
        _FakeLoop.instances = []
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _engine(self, cfg, provider=None, local_workers=0):
        if provider is None:
            provider = None
        return Engine(cfg, _FakeTask(), provider=provider,
                      browser_manager_factory=lambda store: object(),
                      loop_factory=_FakeLoop, local_workers=local_workers,
                      local_loop_factory=_FakeLoop,
                      site_name="1688")

    def test_local_workers_start_local_threads(self):
        cfg = RunConfig(headless=True, use_proxy=False, workers=1,
                        db_path=str(Path(self._tmp.name) / "t.db"),
                        seeds_dir=str(Path(self._tmp.name) / "no_seeds"),
                        stagger_min=0, stagger_max=0)
        engine = self._engine(cfg, local_workers=2)
        engine.run()
        # 浏览器 1 + local 2 = 3 个 loop
        self.assertEqual(len(_FakeLoop.instances), 3)
        # local 线程的 ctx.resources == {"local"}、consumer_kind == "local"
        local_loops = [l for l in _FakeLoop.instances
                       if l.ctx.consumer_kind == "local"]
        self.assertEqual(len(local_loops), 2)
        for l in local_loops:
            self.assertEqual(l.ctx.resources, {"local"})
        # 浏览器线程 consumer_kind == "browser"
        browser_loops = [l for l in _FakeLoop.instances
                         if l.ctx.consumer_kind == "browser"]
        self.assertEqual(len(browser_loops), 1)
        self.assertEqual(browser_loops[0].ctx.resources,
                         {"channel", "browser"})

    def test_local_workers_zero_is_cli_default(self):
        cfg = RunConfig(headless=True, use_proxy=False, workers=1,
                        db_path=str(Path(self._tmp.name) / "t.db"),
                        seeds_dir=str(Path(self._tmp.name) / "no_seeds"),
                        stagger_min=0, stagger_max=0)
        engine = self._engine(cfg, local_workers=0)
        engine.run()
        self.assertEqual(len(_FakeLoop.instances), 1)  # 只有浏览器 worker


if __name__ == "__main__":
    unittest.main()
