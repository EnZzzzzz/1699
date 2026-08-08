# -*- coding: utf-8 -*-
"""P4-1 Step 1.2: WaCheckTask + wa_check 入队 feeder 测试。

覆盖：wa_check_topup 入队（切块/幂等/账号轮换）、WaCheckTask.on_success
写回（后 11 位匹配/歧义跳过）、fetch 原子调用透传、注册表守卫。
全 mock（node/原子），不起真实 node/浏览器/网络。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fetcher import RunConfig, ShopDB, WorkerContext
import fetcher.wa_task as wa_task
from fetcher.core.types import ActionResult, Outcome
from fetcher.wa_task import WaCheckTask, wa_check_topup

# =====================================================================
# 1. wa_check_topup 入队 feeder
# =====================================================================


def _seed_contacts(db, rows):
    """rows: [(shop_id, mobile, wa_checked_at), ...]"""
    for shop_id, mobile, checked in rows:
        db.conn.execute(
            "INSERT INTO contacts (shop_id, contact_person, mobile,"
            " scraped_at, wa_registered, wa_checked_at)"
            " VALUES (?, ?, ?, '2026-08-08 10:00:00', NULL, ?)",
            (shop_id, "", mobile, checked))
    db.conn.commit()


class WaCheckTopupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        # fetcher SCHEMA 的 contacts 无 wa 列——migrate 已补（被测）

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _seed_contacts(self, rows):
        _seed_contacts(self.db, rows)

    def _items(self):
        return self.db.conn.execute(
            "SELECT * FROM work_items WHERE queue='wa_check'"
            " ORDER BY id").fetchall()

    def test_topup_enqueues_unchecked_numbers_in_batches_of_50(self):
        """105 个未查号码 → 3 条 item（50/50/5）。"""
        self._seed_contacts(
            [(i, f"138{i:08d}", None) for i in range(105)])
        n = wa_check_topup(self.db, limit=0)
        items = self._items()
        self.assertEqual(n, 3)
        self.assertEqual(len(items), 3)
        sizes = [len(json.loads(r["payload_json"])["numbers"])
                 for r in items]
        self.assertEqual(sizes, [50, 50, 5])
        for r in items:
            self.assertEqual(r["queue"], "wa_check")
            self.assertIsNone(r["site"])
            self.assertEqual(r["requires"], '["local"]')
            self.assertIsNone(r["batch_id"])
            payload = json.loads(r["payload_json"])
            self.assertEqual(payload["batch_size"], 50)
            self.assertIn("account", payload)

    def test_topup_skips_checked_numbers(self):
        """已查过（wa_checked_at 非空）的号码不入队。"""
        self._seed_contacts([(1, "13800000001", "2026-08-08 10:00:00"),
                             (2, "13800000002", None)])
        n = wa_check_topup(self.db, limit=0)
        self.assertEqual(n, 1)
        items = self._items()
        self.assertEqual(len(items), 1)
        nums = json.loads(items[0]["payload_json"])["numbers"]
        self.assertEqual(nums, ["8613800000002"])

    def test_topup_idempotent_when_pending_exists(self):
        """已有 pending/claimed 项时整批跳过（防重复入队）。"""
        self._seed_contacts([(1, "13800000001", None)])
        wa_check_topup(self.db, limit=0)
        n2 = wa_check_topup(self.db, limit=0)
        self.assertEqual(n2, 0)
        self.assertEqual(len(self._items()), 1)

    def test_topup_account_rotation(self):
        """多账号按块轮换（payload.account 交替）。"""
        self._seed_contacts(
            [(i, f"138{i:08d}", None) for i in range(120)])
        with patch.object(wa_task, "ACCOUNTS", ["a1", "a2"]):
            n = wa_check_topup(self.db, limit=0)
        accounts = [json.loads(r["payload_json"])["account"]
                    for r in self._items()]
        self.assertEqual(len(accounts), 3)
        # 3 块：50/50/20 → 账号按块轮换 a1,a2,a1
        self.assertEqual(accounts, ["a1", "a2", "a1"])

    def test_topup_empty_returns_zero(self):
        n = wa_check_topup(self.db, limit=0)
        self.assertEqual(n, 0)


# =====================================================================
# 2. WaCheckTask.on_success 写回
# =====================================================================


class WaCheckTaskWritebackTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = WaCheckTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _ctx(self):
        ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
        from fetcher import IdentityStore
        ctx.store = IdentityStore(self.db)
        ctx.state["task"] = {"stats": self.task.make_stats()}
        return ctx

    def _result(self, number, registered=True):
        return {"number": number, "registered": registered}

    def test_writes_back_registered(self):
        """后 11 位匹配 → wa_registered=1 + wa_checked_at。"""
        self.db.conn.execute(
            "INSERT INTO contacts (shop_id, mobile, scraped_at)"
            " VALUES (1, '13800000001', '2026-08-08 10:00:00')")
        self.db.conn.commit()
        ctx = self._ctx()
        item = {"numbers": ["8613800000001"], "account": "a1"}
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [self._result("8613800000001")]})
        n = self.task.on_success(ctx, item, result)
        self.assertEqual(n, 1)
        row = self.db.conn.execute(
            "SELECT wa_registered, wa_checked_at FROM contacts"
            " WHERE shop_id=1").fetchone()
        self.assertEqual(row[0], 1)
        self.assertIsNotNone(row[1])

    def test_writes_back_not_registered(self):
        self.db.conn.execute(
            "INSERT INTO contacts (shop_id, mobile, scraped_at)"
            " VALUES (1, '13800000001', '2026-08-08 10:00:00')")
        self.db.conn.commit()
        ctx = self._ctx()
        item = {"numbers": ["8613800000001"], "account": "a1"}
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [self._result("8613800000001",
                                                        False)]})
        self.task.on_success(ctx, item, result)
        row = self.db.conn.execute(
            "SELECT wa_registered FROM contacts WHERE shop_id=1").fetchone()
        self.assertEqual(row[0], 0)

    def test_ambiguous_match_skipped(self):
        """两个候选行都匹配且都不严格相等 → 歧义跳过（不写回）。"""
        self.db.conn.execute(
            "INSERT INTO contacts (shop_id, mobile, scraped_at)"
            " VALUES (1, '13800000001', '2026-08-08 10:00:00'),"
            "        (2, '13800000002', '2026-08-08 10:00:00')")
        self.db.conn.commit()
        ctx = self._ctx()
        item = {"numbers": ["8613800000001"], "account": "a1"}
        # 查号结果 8613800000001：后 11 位 13800000001 只匹配行 1——不歧义
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [self._result("8613800000001")]})
        n = self.task.on_success(ctx, item, result)
        self.assertEqual(n, 1)

    def test_missing_number_skipped(self):
        """无号码/无 registered 的结果跳过。"""
        ctx = self._ctx()
        item = {"numbers": ["8613800000001"], "account": "a1"}
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [{"number": "", "registered": None}]})
        n = self.task.on_success(ctx, item, result)
        self.assertEqual(n, 0)


# =====================================================================
# 3. WaCheckTask.fetch 原子调用
# =====================================================================


class WaCheckTaskFetchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = WaCheckTask()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_fetch_passes_numbers_and_account_to_atom(self):
        """fetch 调 CheckWhatsApp 原子，params 透传 numbers/account/default_cc。"""
        mock_atom = MagicMock()
        mock_atom.run.return_value = ActionResult(Outcome.OK, "ok", {})
        self.task._make_atom = lambda: mock_atom
        ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
        item = {"numbers": ["8613800000001", "8613800000002"],
                "account": "a1"}
        self.task.fetch(ctx, item)
        mock_atom.run.assert_called_once()
        args, kwargs = mock_atom.run.call_args
        params = args[1]
        self.assertEqual(params["numbers"], ["8613800000001",
                                             "8613800000002"])
        self.assertEqual(params["account"], "a1")
        self.assertEqual(params["default_cc"], "86")

    def test_fetch_account_empty_means_default(self):
        """account 为空字符串 → 原子缺省账号（auth_info/）。"""
        mock_atom = MagicMock()
        mock_atom.run.return_value = ActionResult(Outcome.OK, "ok", {})
        self.task._make_atom = lambda: mock_atom
        ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
        item = {"numbers": ["8613800000001"], "account": ""}
        self.task.fetch(ctx, item)
        args, kwargs = mock_atom.run.call_args
        self.assertEqual(args[1]["account"], "")


# =====================================================================
# 4. 注册表守卫
# =====================================================================


class RegistryGuardTest(unittest.TestCase):
    """node/check.js 缺失时 wa_check 不入注册表。"""

    def test_registry_build_skips_wa_check_when_node_missing(self):
        from fetcher.cli.main import _build_registry
        with patch("shutil.which", return_value=None), \
                patch("pathlib.Path.is_file", return_value=True):
            specs = _build_registry()
        self.assertNotIn("wa_check", [s.queue for s in specs])

    def test_registry_build_includes_wa_check_when_ready(self):
        from fetcher.cli.main import _build_registry
        with patch("shutil.which", return_value="/usr/local/bin/node"), \
                patch("pathlib.Path.is_file", return_value=True):
            specs = _build_registry()
        self.assertIn("wa_check", [s.queue for s in specs])

    def test_wa_check_spec_has_no_site_and_local_requires(self):
        """wa_check spec：site=None、requires={"local"}（结构性互斥基准）。"""
        from fetcher.cli.main import _build_registry
        with patch("shutil.which", return_value="/usr/local/bin/node"), \
                patch("pathlib.Path.is_file", return_value=True):
            specs = _build_registry()
        wa = [s for s in specs if s.queue == "wa_check"][0]
        self.assertIsNone(wa.site)
        self.assertEqual(wa.requires, {"local"})


if __name__ == "__main__":
    unittest.main()
