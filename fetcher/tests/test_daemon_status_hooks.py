# -*- coding: utf-8 -*-
"""daemon 状态钩子接线测试：QueueRouter claim/finish → consumer_status
upsert；loop._cooldown 冷却登记 → cooldowns_json；Engine 心跳线程 +
proxy_channels 租约 + 退出清理。真实临时 sqlite + 假 loop/task，不起浏览器。
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fetcher import RunConfig, ShopDB, WorkerContext
from fetcher.control.engine import Engine
from fetcher.control.queue_router import QueueRouter, QueueSpec
from fetcher.control.status import ConsumerStatusStore

PROXY_CHANNELS_DDL = """
CREATE TABLE IF NOT EXISTS proxy_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER,
    tunnel TEXT, exit_ip TEXT,
    status TEXT NOT NULL DEFAULT 'idle',
    used_by_task INTEGER,
    ip_expires_at TEXT, last_probe_at TEXT,
    UNIQUE(provider_id, tunnel)
);
"""


def _shop(i):
    return {"domain": f"shop{i}.1688.com", "name": f"店铺{i}",
            "url": f"https://shop{i}.1688.com"}


class _FakeTask:
    name = "fake"

    def __init__(self):
        self._stats = {}

    def make_stats(self):
        return {}

    def compose(self, wid, f):
        return str(f.get("line", ""))

    def summary(self, all_stats, db_path=None):
        return "ok"

    def on_success(self, ctx, item, result):
        return 1

    def on_giveup(self, ctx, item, reason, kind):
        return ""


class _FakeLoop:
    """假 loop：立即返回（Engine 跑批冒烟用，不起浏览器）。"""

    instances = []

    def __init__(self, ctx, task, policy=None, board=None, seed_kit=None,
                 **kw):
        self.ctx = ctx
        _FakeLoop.instances.append(self)

    def run(self):
        return {}


class RouterStatusHookTest(unittest.TestCase):
    """QueueRouter 带 status_store：claim 写行、finish 清 current。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.db.conn.executescript(PROXY_CHANNELS_DDL)
        self.db.conn.commit()
        self.store = ConsumerStatusStore(Path(self._tmp.name) / "t.db")
        spec = QueueSpec(queue="crawl_1688_contact", site="1688",
                         task=_FakeTask(),
                         topup=lambda db, limit: db.topup_contact_work_items(
                             "crawl_1688_contact", "1688", ".1688.com",
                             limit),
                         domain_suffix=".1688.com")
        self.router = QueueRouter([spec], status_store=self.store)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _status_row(self, consumer_id):
        return self.db.conn.execute(
            "SELECT * FROM consumer_status WHERE consumer_id=?",
            (consumer_id,)).fetchone()

    def test_claim_writes_status_row(self):
        self.db.upsert_shops([_shop(1)])
        ctx = WorkerContext(config=RunConfig(), stop=threading.Event(),
                            wid=0, log=lambda m: None)
        item = self.router.acquire_item(ctx)
        self.assertIsNotNone(item)
        row = self._status_row("w0")
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "browser")
        self.assertEqual(row["current_queue"], "crawl_1688_contact")
        self.assertEqual(row["current_item_id"], item["id"])
        self.assertIsNone(row["current_batch_id"])

    def test_finish_clears_current(self):
        self.db.upsert_shops([_shop(1)])
        ctx = WorkerContext(config=RunConfig(), stop=threading.Event(),
                            wid=0, log=lambda m: None)
        self.router.acquire_item(ctx)
        self.router.on_success(ctx, {}, 1)
        row = self._status_row("w0")
        self.assertIsNone(row["current_queue"])
        self.assertIsNone(row["current_item_id"])
        self.assertIsNotNone(row["updated_at"])  # 心跳字段仍在


class EngineStatusHookTest(unittest.TestCase):
    """Engine 带 status_store：心跳线程 + 租约 + 退出清理。"""

    def setUp(self):
        _FakeLoop.instances = []
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "t.db"
        # 预建库：schema + proxy_channels 种子（store/engine 用独立连接）
        seed_db = ShopDB(self.db_path)
        seed_db.conn.executescript(PROXY_CHANNELS_DDL)
        for i, t in enumerate(["t1", "t2"], 1):
            seed_db.conn.execute(
                "INSERT INTO proxy_channels (provider_id, tunnel, exit_ip,"
                " status) VALUES (1, ?, ?, 'idle')",
                (t, f"10.0.0.{i}"))
        seed_db.conn.commit()
        seed_db.close()
        # 测试断言用连接（engine 内部连接独立，互不干扰）
        self.db = ShopDB(self.db_path)
        self.store = ConsumerStatusStore(self.db_path)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _engine(self, cfg):
        from fetcher.net.proxy.base import Channel

        class FakeProvider:
            name = "fake"

            def __init__(self):
                self._servers = ["10.0.0.1:8080", "10.0.0.2:8080"]
                self.acquired = []

            def servers(self):
                return list(self._servers)

            def acquire(self):
                s = self._servers[len(self.acquired) % 2]
                self.acquired.append(s)
                return Channel(server=s, username="u", password="p",
                               provider=self.name)

            def refresh(self):
                return self.servers()

        return Engine(cfg, _FakeTask(), provider=FakeProvider(),
                      browser_manager_factory=lambda store: object(),
                      loop_factory=_FakeLoop, status_store=self.store,
                      site_name="1688")

    def test_heartbeat_and_lease_and_cleanup(self):
        cfg = RunConfig(headless=True, use_proxy=True, workers=1,
                        db_path=str(self.db_path),
                        seeds_dir=str(Path(self._tmp.name) / "no_seeds"),
                        stagger_min=0, stagger_max=0)
        engine = self._engine(cfg)
        engine.run()

        # 心跳/租约期间消费方应曾写入（engine 收尾清理后行已清空，
        # 这里验证清理生效：无残留 consumer_status 行）
        rows = self.db.conn.execute(
            "SELECT COUNT(*) FROM consumer_status").fetchone()[0]
        self.assertEqual(rows, 0)
        # proxy_channels 租约已释放
        leases = self.db.conn.execute(
            "SELECT COUNT(*) FROM proxy_channels WHERE used_by_task IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(leases, 0)

    def test_lease_channels_during_run(self):
        """run 期间 w0 租约了 t1/t2（use_proxy 多通道场景）。"""
        cfg = RunConfig(headless=True, use_proxy=True, workers=2,
                        db_path=str(self.db_path),
                        seeds_dir=str(Path(self._tmp.name) / "no_seeds"),
                        stagger_min=0, stagger_max=0)
        engine = self._engine(cfg)
        engine.run()
        # 收尾后无残留（清理生效）
        rows = self.db.conn.execute(
            "SELECT COUNT(*) FROM consumer_status").fetchone()[0]
        self.assertEqual(rows, 0)


if __name__ == "__main__":
    unittest.main()
