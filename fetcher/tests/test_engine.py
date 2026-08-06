# -*- coding: utf-8 -*-
"""Engine 编排测试：worker 启动、通道分配、种子认领、汇总。
全 mock（工厂注入，不起浏览器/网络/线程真实浏览器）。"""

import tempfile
import unittest
from pathlib import Path

from fetcher import RunConfig, Session
from fetcher.control import Engine, Task
from fetcher.net.proxy.base import Channel


class FakeProvider:
    """记录 acquire 顺序的假通道池。"""

    name = "fake"

    def __init__(self, n=3):
        self._servers = [f"10.0.0.{i}:8080" for i in range(1, n + 1)]
        self.acquired = []

    def servers(self):
        return list(self._servers)

    def acquire(self):
        server = self._servers[len(self.acquired) % len(self._servers)]
        self.acquired.append(server)
        return Channel(server=server, username="u", password="p",
                       provider=self.name)

    def refresh(self):
        return self.servers()


class FakeLoop:
    """记录装配参数的假 CrawlLoop（不跑真实循环）。"""

    instances = []

    def __init__(self, ctx, task, policy=None, board=None, seed_kit=None):
        self.ctx = ctx
        self.seed_kit = seed_kit
        FakeLoop.instances.append(self)

    def run(self):
        return {"done": 1, "wid": self.ctx.wid}


class FakeTask(Task):
    name = "fake"

    def summary(self, all_stats):
        return f"汇总 {len(all_stats)} 个 worker"


class EngineTest(unittest.TestCase):
    def setUp(self):
        FakeLoop.instances = []
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _config(self, **kw):
        base = dict(headless=True, use_proxy=True, workers=0,
                    db_path=str(Path(self._tmp.name) / "t.db"),
                    seeds_dir=str(Path(self._tmp.name) / "no_seeds"),
                    stagger_min=0, stagger_max=0)
        base.update(kw)
        return RunConfig(**base)

    def _engine(self, cfg, provider):
        return Engine(cfg, FakeTask(), provider=provider,
                      browser_manager_factory=lambda store: object(),
                      loop_factory=FakeLoop)

    def test_workers_default_to_channel_count(self):
        provider = FakeProvider(3)
        engine = self._engine(self._config(), provider)
        engine.run()
        self.assertEqual(len(FakeLoop.instances), 3)
        # 一 worker 一通道，连续 acquire 得到不同通道
        self.assertEqual(len(set(provider.acquired)), 3)

    def test_explicit_workers_and_channel_round_robin(self):
        provider = FakeProvider(2)
        engine = self._engine(self._config(workers=2), provider)
        engine.run()
        self.assertEqual(len(FakeLoop.instances), 2)

    def test_allocated_channel_threaded_to_browser_manager(self):
        """分配的通道透传给 BrowserManager（一 worker 一通道；relaunch
        沿用 session.channel，不会重新从通道池轮询跳隧道）。"""
        from fetcher.net.browser import BrowserManager
        provider = FakeProvider(2)
        # 不用 _engine（其 browser_manager_factory 会短路真实构造）
        engine = Engine(self._config(workers=1), FakeTask(),
                        provider=provider, loop_factory=FakeLoop)
        _workers, channels = engine._alloc_workers()
        mgr = engine._make_browser_manager(None, channels[0])
        self.assertIsInstance(mgr, BrowserManager)
        self.assertIs(mgr.channel, channels[0])

    def test_seed_kit_exclusive_assignment(self):
        # 种子池 2 份、worker 3 个：前两 worker 独占，第三个白板
        import json
        seeds = Path(self._tmp.name) / "seeds"
        seeds.mkdir()
        for name in ("kitA", "kitB"):
            (seeds / f"{name}.json").write_text(json.dumps([
                {"name": "cna", "value": "v", "domain": ".1688.com"},
                {"name": "cookie2", "value": "v", "domain": ".1688.com"},
            ]), encoding="utf-8")
        cfg = self._config(workers=3, seeds_dir=str(seeds))
        engine = self._engine(cfg, FakeProvider(3))
        engine.run()
        kits = {loop.ctx.wid: loop.seed_kit for loop in FakeLoop.instances}
        self.assertEqual(kits[0]["name"], "kitA")
        self.assertEqual(kits[1]["name"], "kitB")
        self.assertIsNone(kits[2])

    def test_summary_aggregates_all_workers(self):
        provider = FakeProvider(2)
        engine = self._engine(self._config(), provider)
        engine.run()
        self.assertEqual(sorted(engine.state["stats"]), [0, 1])
        self.assertEqual(engine.task.summary(engine.state["stats"]),
                         "汇总 2 个 worker")

    def test_each_worker_gets_own_store(self):
        provider = FakeProvider(2)
        engine = self._engine(self._config(), provider)
        engine.run()
        stores = [loop.ctx.store for loop in FakeLoop.instances]
        self.assertIsNot(stores[0], stores[1])
        self.assertIsNot(stores[0].db.conn, stores[1].db.conn)


if __name__ == "__main__":
    unittest.main()
