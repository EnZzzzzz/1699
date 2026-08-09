# -*- coding: utf-8 -*-
"""Step 3.1: wa_check 双源挑号 + 回写双表测试。

覆盖：wa_check_topup 挑号 SQL 扩展为 contacts ∪ fb_contacts（fb 侧仅
cn_uncertain 桶且未查过）、跨源去重、WaCheckTask.on_success 回写双表
（fb 侧附带 wa_source='checked'）、1688-only 场景零回归（无 fb_contacts
时行为与既有完全一致）。全 mock（node/原子），不起真实网络。
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

POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
            "1437583168191347/")


class WaCheckDualSourceTopupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _seed_contacts(self, rows):
        """rows: [(shop_id, mobile, wa_checked_at), ...]"""
        for shop_id, mobile, checked in rows:
            self.db.conn.execute(
                "INSERT INTO contacts (shop_id, contact_person, mobile,"
                " scraped_at, wa_registered, wa_checked_at)"
                " VALUES (?, ?, ?, '2026-08-08 10:00:00', NULL, ?)",
                (shop_id, "", mobile, checked))
        self.db.conn.commit()

    def _seed_fb_contacts(self, rows):
        """rows: [(number, bucket, wa_checked_at), ...]"""
        for number, bucket, checked in rows:
            self.db.conn.execute(
                "INSERT INTO fb_contacts (number, bucket, wa_source,"
                " post_url, group_id, wa_checked_at, first_seen_at)"
                " VALUES (?, ?, ?, ?, 'g1', ?, '2026-08-08 10:00:00')",
                (number, bucket,
                 "declared" if bucket == "declared_wa" else None,
                 POST_URL, checked))
        self.db.conn.commit()

    def _items(self):
        return self.db.conn.execute(
            "SELECT * FROM work_items WHERE queue='wa_check'"
            " ORDER BY id").fetchall()

    def _numbers_in_items(self):
        out = []
        for r in self._items():
            out.extend(json.loads(r["payload_json"])["numbers"])
        return out

    def test_dual_source_union_picks_both(self):
        """contacts 未查 + fb cn_uncertain 未查 → 双源都入队。"""
        self._seed_contacts([(1, "13800000001", None)])
        self._seed_fb_contacts([("18588244213", "cn_uncertain", None)])
        n = wa_check_topup(self.db, limit=0)
        self.assertEqual(n, 1)
        nums = self._numbers_in_items()
        self.assertEqual(sorted(nums), ["8613800000001", "8618588244213"])

    def test_fb_only_cn_uncertain_bucket(self):
        """fb 侧 UNION 只挑 cn_uncertain：overseas 永不入队；declared 经抽样
        混入但已查过的不重抽（这里标记已查 → 不出现）。"""
        self._seed_fb_contacts([
            ("8618588244213", "declared_wa", "2026-08-08 10:00:00"),
            ("13812345678", "cn_uncertain", None),
            ("1562562681", "overseas", None),
        ])
        n = wa_check_topup(self.db, limit=0)
        nums = self._numbers_in_items()
        self.assertEqual(nums, ["8613812345678"])

    def test_fb_checked_numbers_excluded(self):
        """fb 已查过（wa_checked_at 非空）的不入队。"""
        self._seed_fb_contacts([
            ("13800000001", "cn_uncertain", "2026-08-08 10:00:00"),
            ("13800000002", "cn_uncertain", None),
        ])
        n = wa_check_topup(self.db, limit=0)
        self.assertEqual(self._numbers_in_items(), ["8613800000002"])

    def test_cross_source_dedup(self):
        """同号双源（contacts mobile 与 fb number 同源同值）→ 只入队一次。"""
        self._seed_contacts([(1, "13800000001", None)])
        self._seed_fb_contacts([("13800000001", "cn_uncertain", None)])
        n = wa_check_topup(self.db, limit=0)
        nums = self._numbers_in_items()
        self.assertEqual(nums, ["8613800000001"])  # 去重

    def test_fb_numbers_prioritized_over_contacts(self):
        """FB 源优先：fb cn_uncertain 号排在 contacts 号之前入队。

        contacts 用 131 段（字典序在 fb 的 137 段之前），旧 UNION
        ORDER BY number 会把 contacts 排前面；新逻辑 fb 源显式优先。
        """
        self._seed_contacts([(i, f"131{i:08d}", None) for i in range(60)])
        self._seed_fb_contacts(
            [(f"137{i:08d}", "cn_uncertain", None) for i in range(10)])
        wa_check_topup(self.db, limit=0)
        nums = self._numbers_in_items()
        # 前 10 个应全部是 fb 号（86137 段），contacts（86131 段）排后面
        self.assertTrue(all(x.startswith("86137") for x in nums[:10]))
        self.assertTrue(all(x.startswith("86131") for x in nums[10:]))

    def test_1688_only_no_regression(self):
        """无 fb_contacts 行时行为与既有完全一致（账号轮换/切块/幂等）。"""
        self._seed_contacts([(i, f"138{i:08d}", None) for i in range(105)])
        with patch.object(wa_task, "ACCOUNTS", ["a1", "a2"]):
            n = wa_check_topup(self.db, limit=0)
        self.assertEqual(n, 3)
        accounts = [json.loads(r["payload_json"])["account"]
                    for r in self._items()]
        self.assertEqual(accounts, ["a1", "a2", "a1"])  # 按块轮换不变
        sizes = [len(json.loads(r["payload_json"])["numbers"])
                 for r in self._items()]
        self.assertEqual(sizes, [50, 50, 5])
        # 幂等：再 topup 整批跳过
        n2 = wa_check_topup(self.db, limit=0)
        self.assertEqual(n2, 0)


class WaCheckDualSourceWritebackTest(unittest.TestCase):
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

    def _seed_fb(self, number):
        self.db.conn.execute(
            "INSERT INTO fb_contacts (number, bucket, wa_source, post_url,"
            " group_id, first_seen_at) VALUES (?, 'cn_uncertain', NULL, ?,"
            " 'g1', '2026-08-08 10:00:00')",
            (number, POST_URL))
        self.db.conn.commit()

    def test_writes_back_fb_contacts_with_checked_source(self):
        """查号结果回写 fb_contacts：wa_registered + wa_checked_at + wa_source='checked'。"""
        self._seed_fb("18588244213")
        ctx = self._ctx()
        item = {"numbers": ["8618588244213"], "account": "a1"}
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [{"number": "8618588244213",
                                            "registered": True}]})
        n = self.task.on_success(ctx, item, result)
        self.assertEqual(n, 1)
        row = self.db.conn.execute(
            "SELECT wa_registered, wa_checked_at, wa_source FROM fb_contacts"
            " WHERE number='18588244213'").fetchone()
        self.assertEqual(row[0], 1)
        self.assertIsNotNone(row[1])
        self.assertEqual(row[2], "checked")

    def test_writes_back_not_registered(self):
        self._seed_fb("13812345678")
        ctx = self._ctx()
        item = {"numbers": ["8613812345678"], "account": "a1"}
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [{"number": "8613812345678",
                                            "registered": False}]})
        self.task.on_success(ctx, item, result)
        row = self.db.conn.execute(
            "SELECT wa_registered, wa_source FROM fb_contacts"
            " WHERE number='13812345678'").fetchone()
        self.assertEqual(row[0], 0)
        self.assertEqual(row[1], "checked")

    def test_both_tables_written_same_number(self):
        """同号双源都存在 → 两张表各 UPDATE 一次（幂等命中）。"""
        self.db.conn.execute(
            "INSERT INTO contacts (shop_id, mobile, scraped_at)"
            " VALUES (1, '13812345678', '2026-08-08 10:00:00')")
        self._seed_fb("13812345678")
        ctx = self._ctx()
        item = {"numbers": ["8613812345678"], "account": "a1"}
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [{"number": "8613812345678",
                                            "registered": True}]})
        n = self.task.on_success(ctx, item, result)
        self.assertEqual(n, 2)  # contacts 1 行 + fb_contacts 1 行
        c_row = self.db.conn.execute(
            "SELECT wa_registered FROM contacts WHERE shop_id=1").fetchone()
        self.assertEqual(c_row[0], 1)
        fb_row = self.db.conn.execute(
            "SELECT wa_registered, wa_source FROM fb_contacts"
            " WHERE number='13812345678'").fetchone()
        self.assertEqual(fb_row[0], 1)
        self.assertEqual(fb_row[1], "checked")

    def test_1688_only_writeback_no_regression(self):
        """无 fb_contacts 时回写行为与既有一致。"""
        self.db.conn.execute(
            "INSERT INTO contacts (shop_id, mobile, scraped_at)"
            " VALUES (1, '13800000001', '2026-08-08 10:00:00')")
        self.db.conn.commit()
        ctx = self._ctx()
        item = {"numbers": ["8613800000001"], "account": "a1"}
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [{"number": "8613800000001",
                                            "registered": True}]})
        n = self.task.on_success(ctx, item, result)
        self.assertEqual(n, 1)
        row = self.db.conn.execute(
            "SELECT wa_registered FROM contacts WHERE shop_id=1").fetchone()
        self.assertEqual(row[0], 1)


class WaCheckDeclaredSamplingTest(unittest.TestCase):
    """Step 3.2: declared_wa 桶抽样校准混入。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _seed_fb(self, rows):
        """rows: [(number, bucket, wa_checked_at), ...]"""
        for number, bucket, checked in rows:
            self.db.conn.execute(
                "INSERT INTO fb_contacts (number, bucket, wa_source,"
                " post_url, group_id, wa_checked_at, first_seen_at)"
                " VALUES (?, ?, ?, ?, 'g1', ?, '2026-08-08 10:00:00')",
                (number, bucket,
                 "declared" if bucket == "declared_wa" else None,
                 POST_URL, checked))
        self.db.conn.commit()

    def _numbers(self):
        out = []
        for r in self.db.conn.execute(
                "SELECT * FROM work_items WHERE queue='wa_check'"
                " ORDER BY id").fetchall():
            out.extend(json.loads(r["payload_json"])["numbers"])
        return out

    def test_declared_sampled_at_10_percent(self):
        """10 个不确定号 → 配 max(1, 10×10%)=1 个 declared 抽样。"""
        self._seed_fb(
            [(f"1380000000{i}", "cn_uncertain", None) for i in range(10)]
            + [("8618588244213", "declared_wa", None)])
        n = wa_check_topup(self.db, limit=0)
        self.assertEqual(n, 1)
        nums = self._numbers()
        uncertain = [x for x in nums if x.startswith("861380000000")]
        declared = [x for x in nums if x == "8618588244213"]
        self.assertEqual(len(uncertain), 10)
        self.assertEqual(len(declared), 1)  # 抽样混入

    def test_small_uncertain_still_samples_one(self):
        """3 个不确定号 → 10%=0 → max(1,0)=1 个 declared 抽样。"""
        self._seed_fb(
            [(f"1380000000{i}", "cn_uncertain", None) for i in range(3)]
            + [("8618588244213", "declared_wa", None)])
        wa_check_topup(self.db, limit=0)
        nums = self._numbers()
        self.assertIn("8618588244213", nums)

    def test_empty_declared_bucket_no_sampling(self):
        """declared 桶空 → 只入队不确定号。"""
        self._seed_fb(
            [(f"1380000000{i}", "cn_uncertain", None) for i in range(10)])
        n = wa_check_topup(self.db, limit=0)
        self.assertEqual(n, 1)
        nums = self._numbers()
        self.assertEqual(len(nums), 10)
        self.assertTrue(all(x.startswith("861380000000") for x in nums))

    def test_checked_declared_not_resampled(self):
        """已查过的 declared（wa_checked_at 非空）不重复抽样。"""
        self._seed_fb(
            [(f"1380000000{i}", "cn_uncertain", None) for i in range(10)]
            + [("8618588244213", "declared_wa", "2026-08-08 10:00:00")])
        wa_check_topup(self.db, limit=0)
        nums = self._numbers()
        self.assertNotIn("8618588244213", nums)  # 已查不重抽

    def test_declared_sample_writeback_uses_checked_source(self):
        """抽样号查完回写：wa_source='checked'（供一致率统计）。"""
        self._seed_fb([("8618588244213", "declared_wa", None)])
        task = WaCheckTask()
        ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
        from fetcher import IdentityStore
        ctx.store = IdentityStore(self.db)
        ctx.state["task"] = {"stats": task.make_stats()}
        item = {"numbers": ["8618588244213"], "account": "a1"}
        result = ActionResult(Outcome.OK, "ok",
                              {"results": [{"number": "8618588244213",
                                            "registered": True}]})
        task.on_success(ctx, item, result)
        row = self.db.conn.execute(
            "SELECT wa_source, wa_registered FROM fb_contacts"
            " WHERE number='8618588244213'").fetchone()
        self.assertEqual(row[0], "checked")
        self.assertEqual(row[1], 1)


if __name__ == "__main__":
    unittest.main()
