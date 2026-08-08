# -*- coding: utf-8 -*-
"""Engine 编排测试：worker 启动、通道分配、种子认领、汇总。
全 mock（工厂注入，不起浏览器/网络/线程真实浏览器）。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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

    def summary(self, all_stats, db_path=None):
        self._last_summary_db_path = db_path
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
                        provider=provider, loop_factory=FakeLoop,
                        site_name="1688")
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
        cfg = self._config()
        engine = self._engine(cfg, provider)
        engine.run()
        self.assertEqual(sorted(engine.state["stats"]), [0, 1])
        self.assertEqual(engine.task.summary(engine.state["stats"],
                                              cfg.resolved_db_path()),
                         "汇总 2 个 worker")

    def test_summary_receives_db_path_from_config(self):
        """Engine 调用 summary 时传入 config.resolved_db_path()。"""
        provider = FakeProvider(1)
        cfg = self._config(db_path="/tmp/test_engine.db")
        engine = self._engine(cfg, provider)
        engine.run()
        self.assertEqual(engine.task._last_summary_db_path,
                         cfg.resolved_db_path(),
                         "Engine 应将 resolved_db_path() 传给 summary")

    # ---- Step 1.3: site_name guard ----

    def test_site_without_site_name_raises_runtime_error(self):
        """site 非空而 site_name=None → RuntimeError。

        RED 预期（修正前）：没有 guard，site_name=None 静默通过，
        后续拼键出 'None:direct' 才暴露问题。
        """
        with self.assertRaises(RuntimeError) as ctx:
            Engine(self._config(), FakeTask(), site=MagicMock(),
                   site_name=None)
        self.assertIn("site_name 必传", str(ctx.exception))

    def test_site_with_site_name_constructs_successfully(self):
        """site 非空且 site_name 传入 → 正常构造（对照）。"""
        engine = Engine(self._config(), FakeTask(), site=MagicMock(),
                        site_name="1688",
                        browser_manager_factory=lambda store: object(),
                        loop_factory=FakeLoop)
        self.assertEqual(engine.site_name, "1688")
        self.assertIsNotNone(engine.site)

    def test_site_none_without_site_name_constructs_successfully(self):
        """site=None 时不触发 guard（允许不指定 site_name）。"""
        engine = Engine(self._config(), FakeTask(), site=None,
                        site_name=None,
                        browser_manager_factory=lambda store: object(),
                        loop_factory=FakeLoop)
        self.assertIsNone(engine.site)
        self.assertIsNone(engine.site_name)

    def test_each_worker_gets_own_store(self):
        provider = FakeProvider(2)
        engine = self._engine(self._config(), provider)
        engine.run()
        stores = [loop.ctx.store for loop in FakeLoop.instances]
        self.assertIsNot(stores[0], stores[1])
        self.assertIsNot(stores[0].db.conn, stores[1].db.conn)


# ============================================================
# Task 2.2: 种子池 (worker, site) 粒度
# ============================================================

class SeedPoolMultiSiteTest(unittest.TestCase):
    """_alloc_seed_kits 多站点支持。"""

    def setUp(self):
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

    def _engine(self, cfg, site=None, site_name=None):
        return Engine(cfg, FakeTask(), site=site, site_name=site_name,
                      browser_manager_factory=lambda store: object(),
                      loop_factory=FakeLoop)

    # ---- sites=None 返回 list（CLI 等价） ----

    def test_sites_none_returns_list_unchanged(self):
        """sites=None（CLI 单站点路径）→ 返回 list[kit]，行为逐字不变。"""
        cfg = self._config(workers=3, use_proxy=False)
        engine = self._engine(cfg)
        result = engine._alloc_seed_kits(3)
        self.assertIsInstance(result, list,
                              f"sites=None 应返回 list，实际={type(result)}")
        self.assertEqual(len(result), 3)
        # 直连模式全为 None
        self.assertEqual(result, [None, None, None])

    def test_sites_none_with_seeds_returns_list(self):
        """sites=None 有种子时仍返回 list。"""
        import json
        seeds = Path(self._tmp.name) / "seeds"
        seeds.mkdir()
        for name in ("kitA", "kitB"):
            (seeds / f"{name}.json").write_text(json.dumps([
                {"name": "cna", "value": "v", "domain": ".1688.com"},
                {"name": "cookie2", "value": "v", "domain": ".1688.com"},
            ]), encoding="utf-8")
        cfg = self._config(workers=3, seeds_dir=str(seeds))
        engine = Engine(
            cfg, FakeTask(), site=MagicMock(cookie_domain="1688.com"),
            site_name="1688",
            browser_manager_factory=lambda store: object(),
            loop_factory=FakeLoop)
        result = engine._alloc_seed_kits(3)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "kitA")
        self.assertEqual(result[1]["name"], "kitB")
        self.assertIsNone(result[2], "越界 worker 应为 None=白板")

    # ---- sites 非空返回 dict[site][worker] ----

    def test_sites_nonempty_returns_dict_of_lists(self):
        """sites 非空 → 返回 dict[site_name, list[kit]]。"""
        cfg = self._config(workers=2, use_proxy=False)
        engine = self._engine(cfg)
        from types import SimpleNamespace
        sites = [
            SimpleNamespace(name="1688", cookie_domain="1688.com"),
            SimpleNamespace(name="yiwugo", cookie_domain="yiwugo.com"),
        ]
        result = engine._alloc_seed_kits(2, sites=sites)
        self.assertIsInstance(result, dict,
                              f"sites 非空应返回 dict，实际={type(result)}")
        self.assertEqual(set(result.keys()), {"1688", "yiwugo"})
        for site_name in ("1688", "yiwugo"):
            self.assertIsInstance(result[site_name], list)
            self.assertEqual(len(result[site_name]), 2)

    def test_sites_nonempty_per_worker_per_site_independent(self):
        """每 (worker, site) 独立分配，越界 None。

        用 sites 参数传入两站点：1688（2 份种子）和 yiwugo（1 份种子），
        验证 dict[site][worker] 各自独立映射。
        """
        import json
        from types import SimpleNamespace

        seeds_dir = Path(self._tmp.name) / "seeds"
        seeds_dir.mkdir()
        # 1688 域种子
        for name, domain in (("kitA", ".1688.com"), ("kitB", ".1688.com")):
            (seeds_dir / f"{name}.json").write_text(json.dumps([
                {"name": "cna", "value": "v", "domain": domain},
                {"name": "cookie2", "value": "v", "domain": domain},
            ]), encoding="utf-8")
        # yiwugo 域种子（只有 1 份）
        (seeds_dir / "kitY.json").write_text(json.dumps([
            {"name": "cna", "value": "v", "domain": ".yiwugo.com"},
            {"name": "cookie2", "value": "v", "domain": ".yiwugo.com"},
        ]), encoding="utf-8")

        cfg = self._config(workers=3, seeds_dir=str(seeds_dir))
        engine = Engine(
            cfg, FakeTask(),
            site=MagicMock(cookie_domain="1688.com"),
            site_name="1688",
            browser_manager_factory=lambda store: object(),
            loop_factory=FakeLoop)

        sites = [
            SimpleNamespace(name="1688", cookie_domain="1688.com"),
            SimpleNamespace(name="yiwugo", cookie_domain="yiwugo.com"),
        ]
        result = engine._alloc_seed_kits(3, sites=sites)

        # 验证 dict 结构
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()), {"1688", "yiwugo"})

        # 1688: 2 份种子，3 workers → [kitA, kitB, None]
        self.assertEqual(len(result["1688"]), 3)
        self.assertEqual(result["1688"][0]["name"], "kitA")
        self.assertEqual(result["1688"][1]["name"], "kitB")
        self.assertIsNone(result["1688"][2])

        # yiwugo: 1 份种子，3 workers → [kitY, None, None]
        self.assertEqual(len(result["yiwugo"]), 3)
        self.assertEqual(result["yiwugo"][0]["name"], "kitY")
        self.assertIsNone(result["yiwugo"][1])
        self.assertIsNone(result["yiwugo"][2])

    def test_sites_nonempty_cookie_domain_filter(self):
        """不同 site 不同 cookie_domain → 各自池按各自域加载。"""
        import json
        seeds_1688 = Path(self._tmp.name) / "seeds_1688"
        seeds_1688.mkdir()
        (seeds_1688 / "kit_1688.json").write_text(json.dumps([
            {"name": "cna", "value": "v", "domain": ".1688.com"},
            {"name": "cookie2", "value": "v", "domain": ".1688.com"},
        ]), encoding="utf-8")

        seeds_mic = Path(self._tmp.name) / "seeds_mic"
        seeds_mic.mkdir()
        (seeds_mic / "kit_mic.json").write_text(json.dumps([
            {"name": "cna", "value": "v", "domain": ".made-in-china.com"},
            {"name": "cookie2", "value": "v", "domain": ".made-in-china.com"},
        ]), encoding="utf-8")

        from types import SimpleNamespace
        from unittest.mock import patch

        cfg = self._config(workers=1)
        engine = self._engine(cfg)

        # 用 mock 验证 load_seed_kits 被不同 domain 调用
        with patch('fetcher.control.engine.load_seed_kits') as mock_load:
            mock_load.return_value = []
            sites = [
                SimpleNamespace(name="1688", cookie_domain="1688.com"),
                SimpleNamespace(name="madeinchina", cookie_domain="made-in-china.com"),
            ]
            engine._alloc_seed_kits(1, sites=sites)
            # 每个 site 调用一次
            self.assertEqual(mock_load.call_count, 2)
            # 验证 domain 参数不同
            calls = mock_load.call_args_list
            domains = {c[1].get('domain') for c in calls}
            self.assertEqual(domains, {"1688.com", "made-in-china.com"})

    # ---- seed_x5sec 分支 ----

    def test_sites_nonempty_seed_x5sec(self):
        """seed_x5sec 实验：sites 非空 + seed_x5sec=True →
        dict[site][worker] 结构，偶数 worker A 组（含 x5sec），
        奇数 worker B 组对照。两站点各有独立域的种子。"""
        import json
        from types import SimpleNamespace
        seeds = Path(self._tmp.name) / "seeds"
        seeds.mkdir()
        # 1688 域种子：kitA 含 x5sec，kitB 不含
        for name, has_x5sec, domain in (
            ("kitA", True, ".1688.com"),
            ("kitB", False, ".1688.com"),
            ("kitY", True, ".yiwugo.com"),
            ("kitZ", False, ".yiwugo.com"),
        ):
            cookies = [
                {"name": "cna", "value": "v", "domain": domain},
                {"name": "cookie2", "value": "v", "domain": domain},
            ]
            if has_x5sec:
                cookies.append({"name": "x5sec", "value": "xv",
                                "domain": domain, "expires": 9999999999})
            (seeds / f"{name}.json").write_text(json.dumps(cookies),
                                                encoding="utf-8")

        cfg = self._config(workers=2, seeds_dir=str(seeds), seed_x5sec=True)
        engine = Engine(
            cfg, FakeTask(),
            site=MagicMock(cookie_domain="1688.com"),
            site_name="1688",
            browser_manager_factory=lambda store: object(),
            loop_factory=FakeLoop)
        # sites 非空 → 多站点路径
        sites = [
            SimpleNamespace(name="1688", cookie_domain="1688.com"),
            SimpleNamespace(name="yiwugo", cookie_domain="yiwugo.com"),
        ]
        result = engine._alloc_seed_kits(2, sites=sites)
        # 验证 dict 结构
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()), {"1688", "yiwugo"})
        for site_name in ("1688", "yiwugo"):
            self.assertIsInstance(result[site_name], list)
            self.assertEqual(len(result[site_name]), 2)
            # 每个 site 内：worker 0 (偶数) A 组，worker 1 (奇数) B 组
            self.assertTrue(result[site_name][0].get("x5sec"),
                            f"{site_name} worker 0 应为 A 组（含 x5sec），"
                            f"实际={result[site_name][0]}")
            self.assertFalse(result[site_name][1].get("x5sec"),
                             f"{site_name} worker 1 应为 B 组（不含 x5sec），"
                             f"实际={result[site_name][1]}")

    def test_sites_none_seed_x5sec_unchanged(self):
        """sites=None 时 seed_x5sec 行为与现状一致。"""
        import json
        seeds = Path(self._tmp.name) / "seeds"
        seeds.mkdir()
        for name, has_x5sec in (("kitA", True), ("kitB", False)):
            cookies = [
                {"name": "cna", "value": "v", "domain": ".1688.com"},
                {"name": "cookie2", "value": "v", "domain": ".1688.com"},
            ]
            if has_x5sec:
                cookies.append({"name": "x5sec", "value": "xv",
                                "domain": ".1688.com",
                                "expires": 9999999999})
            (seeds / f"{name}.json").write_text(json.dumps(cookies),
                                                encoding="utf-8")

        cfg = self._config(workers=2, seeds_dir=str(seeds), seed_x5sec=True)
        engine = Engine(
            cfg, FakeTask(),
            site=MagicMock(cookie_domain="1688.com"),
            site_name="1688",
            browser_manager_factory=lambda store: object(),
            loop_factory=FakeLoop)
        result = engine._alloc_seed_kits(2)  # sites=None default
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0].get("x5sec"))
        self.assertFalse(result[1].get("x5sec"))


if __name__ == "__main__":
    unittest.main()
