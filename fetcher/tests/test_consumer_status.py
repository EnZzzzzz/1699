# -*- coding: utf-8 -*-
"""consumer_status 心跳 + proxy_channels 租约存储层测试（临时 sqlite）。

consumer_status 表由 fetcher SCHEMA 建；proxy_channels 是平台表，fetcher
不建——测试临时库手工补建（仿平台 migrate DDL）。
"""

import json
import tempfile
import threading
import unittest
from pathlib import Path

from fetcher.db import ShopDB
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


class ConsumerStatusTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "t.db"
        self.db = ShopDB(self._db_path)
        self.db.conn.executescript(PROXY_CHANNELS_DDL)
        self.db.conn.commit()
        self.store = ConsumerStatusStore(self._db_path)

    def db_path(self):
        return self._db_path

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _row(self, consumer_id):
        return self.db.conn.execute(
            "SELECT * FROM consumer_status WHERE consumer_id=?",
            (consumer_id,)).fetchone()

    def _channels(self):
        return self.db.conn.execute(
            "SELECT * FROM proxy_channels ORDER BY id").fetchall()

    # ---- upsert ----

    def test_upsert_inserts_row(self):
        self.store.upsert("w0", "browser", tunnel="t1",
                          exit_ip="1.2.3.4", queue="crawl_1688_contact",
                          item_id=5, batch_id=7,
                          cooldowns={"1688": 1234.5})
        row = self._row("w0")
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "browser")
        self.assertEqual(row["tunnel"], "t1")
        self.assertEqual(row["exit_ip"], "1.2.3.4")
        self.assertEqual(row["current_queue"], "crawl_1688_contact")
        self.assertEqual(row["current_item_id"], 5)
        self.assertEqual(row["current_batch_id"], 7)
        self.assertEqual(json.loads(row["cooldowns_json"]), {"1688": 1234.5})
        # 北京时间格式
        import re
        self.assertRegex(row["updated_at"],
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_upsert_updates_existing_row(self):
        self.store.upsert("w0", "browser", tunnel="t1")
        self.store.upsert("w0", "browser", queue="crawl_mic_shop",
                          item_id=9)
        rows = self.db.conn.execute(
            "SELECT COUNT(*) FROM consumer_status").fetchone()[0]
        self.assertEqual(rows, 1)  # 不产生重复行
        row = self._row("w0")
        self.assertEqual(row["current_queue"], "crawl_mic_shop")
        self.assertEqual(row["current_item_id"], 9)
        self.assertEqual(row["tunnel"], "t1")  # 未传字段保留

    def test_upsert_clears_optional_fields_when_none(self):
        """显式传 None 的字段要清空（item 完成后 current_* 归零）。"""
        self.store.upsert("w0", "browser", queue="crawl_mic_shop",
                          item_id=9, batch_id=3)
        self.store.upsert("w0", "browser", queue=None, item_id=None,
                          batch_id=None)  # 显式清空
        row = self._row("w0")
        self.assertIsNone(row["current_queue"])
        self.assertIsNone(row["current_item_id"])
        self.assertIsNone(row["current_batch_id"])

    # ---- clear / heartbeat ----

    def test_clear_removes_row(self):
        self.store.upsert("w0", "browser")
        self.store.upsert("w1", "local")
        self.store.clear("w0")
        self.assertIsNone(self._row("w0"))
        self.assertIsNotNone(self._row("w1"))

    def test_heartbeat_all_refreshes_without_clobber(self):
        self.store.upsert("w0", "browser", tunnel="t1", queue="q1",
                          item_id=3)
        self.store.upsert("w1", "local", queue="wa_check")
        # 模拟 10s 后心跳：只刷新 updated_at，保留其他字段
        self.store.heartbeat_all(["w0", "w1"])
        row0 = self._row("w0")
        self.assertEqual(row0["tunnel"], "t1")
        self.assertEqual(row0["current_queue"], "q1")
        self.assertEqual(row0["current_item_id"], 3)
        row1 = self._row("w1")
        self.assertEqual(row1["current_queue"], "wa_check")

    def test_heartbeat_all_missing_consumers_skipped(self):
        """心跳只刷新在册 consumer；不在册的（已 clear）不重建。"""
        self.store.upsert("w0", "browser")
        self.store.heartbeat_all(["w0", "w1"])  # w1 不在册
        self.assertIsNone(self._row("w1"))

    # ---- proxy_channels 租约 ----

    def _seed_channels(self):
        for i, t in enumerate(["t1", "t2", "t3"], 1):
            self.db.conn.execute(
                "INSERT INTO proxy_channels (provider_id, tunnel, exit_ip,"
                " status) VALUES (1, ?, ?, 'idle')",
                (t, f"10.0.0.{i}"))
        self.db.conn.commit()

    def test_lease_channels_by_tunnel(self):
        self._seed_channels()
        n = self.store.lease_channels("w0", ["t1", "t3"])
        self.assertEqual(n, 2)
        rows = {r["tunnel"]: r for r in self._channels()}
        self.assertEqual(rows["t1"]["used_by_task"], "w0")
        self.assertEqual(rows["t3"]["used_by_task"], "w0")
        self.assertIsNone(rows["t2"]["used_by_task"])

    def test_lease_idempotent(self):
        self._seed_channels()
        self.store.lease_channels("w0", ["t1"])
        n2 = self.store.lease_channels("w0", ["t1"])
        self.assertEqual(n2, 1)
        rows = {r["tunnel"]: r for r in self._channels()}
        self.assertEqual(rows["t1"]["used_by_task"], "w0")

    def test_lease_unknown_tunnel_returns_zero(self):
        self._seed_channels()
        n = self.store.lease_channels("w0", ["nope"])
        self.assertEqual(n, 0)

    def test_release_channels_clears_lease(self):
        self._seed_channels()
        self.store.lease_channels("w0", ["t1", "t2"])
        n = self.store.release_channels("w0")
        self.assertEqual(n, 2)
        for r in self._channels():
            self.assertIsNone(r["used_by_task"])

    def test_release_without_lease_returns_zero(self):
        self._seed_channels()
        n = self.store.release_channels("w0")
        self.assertEqual(n, 0)

    # ---- 跨线程（sqlite 连接不可跨线程的回归防线）----

    def test_upsert_from_worker_thread(self):
        """worker 线程 upsert、主线程可读：线程本地连接各自独立。"""
        errs = []

        def worker():
            try:
                # 注意：线程本地连接在建 shop 表前不可用——先触发建库
                self.store.upsert("w0", "browser", queue="q1",
                                  item_id=3)
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(errs, [])
        row = self._row("w0")
        self.assertIsNotNone(row)
        self.assertEqual(row["current_queue"], "q1")
        self.assertEqual(row["current_item_id"], 3)
        # 主线程 clear（各自连接互不干扰）
        self.store.clear("w0")
        self.assertIsNone(self._row("w0"))


if __name__ == "__main__":
    unittest.main()
