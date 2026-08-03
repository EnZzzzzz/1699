# -*- coding: utf-8 -*-
"""1688 contact 任务层测试：parse_contact_text 解析用例 + validate 结构化判空。
不起浏览器/网络；入库路径用临时 sqlite。"""

import tempfile
import unittest
from pathlib import Path

from fetcher import IdentityStore, ShopDB, WorkerContext
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.alibaba1688.contact import ContactTask, parse_contact_text


class ParseContactTextTest(unittest.TestCase):
    def test_full_fields(self):
        text = ("联系方式\n"
                "电话：86-757-88886666\n"
                "手机：13800138000\n"
                "传真：86-757-88886667\n"
                "地址：广东省佛山市顺德区某某工业园\n"
                "张三女士\n"
                "其他行\n")
        info = parse_contact_text(text)
        self.assertEqual(info["phone"], "86-757-88886666")
        self.assertEqual(info["mobile"], "13800138000")
        self.assertEqual(info["fax"], "86-757-88886667")
        self.assertEqual(info["address"], "广东省佛山市顺德区某某工业园")
        self.assertEqual(info["contact_person"], "张三")
        self.assertEqual(info["gender"], "女")

    def test_zanwu_and_area_code_only(self):
        text = ("电话：86\n"
                "手机：暂无\n"
                "传真：暂无\n"
                "地址：广东东莞\n"
                "李四先生\n")
        info = parse_contact_text(text)
        self.assertIsNone(info["phone"])   # 只有区号视为无
        self.assertIsNone(info["mobile"])  # 暂无视为无
        self.assertIsNone(info["fax"])
        self.assertEqual(info["address"], "广东东莞")
        self.assertEqual(info["contact_person"], "李四")
        self.assertEqual(info["gender"], "男")

    def test_no_contact_person(self):
        text = "电话：757-1234567\n手机：13900001111\n传真：暂无\n地址：广州\n"
        info = parse_contact_text(text)
        self.assertEqual(info["phone"], "757-1234567")
        self.assertIsNone(info["contact_person"])
        self.assertIsNone(info["gender"])

    def test_empty_text(self):
        info = parse_contact_text("")
        self.assertTrue(all(v is None for v in info.values()))

    def test_ascii_colon(self):
        text = "电话: 757-9999999\n手机: 13711112222\n传真: 暂无\n地址: 深圳\n王五先生\n"
        info = parse_contact_text(text)
        self.assertEqual(info["phone"], "757-9999999")
        self.assertEqual(info["mobile"], "13711112222")


def ok_result(data):
    return ActionResult(Outcome.OK, "", data)


class ContactValidateTest(unittest.TestCase):
    def setUp(self):
        self.task = ContactTask()

    def test_valid_with_fields(self):
        r = ok_result({"phone": None, "mobile": None, "contact_person": "张三",
                       "_raw": "一些文本"})
        self.assertTrue(self.task.validate(None, None, r))

    def test_valid_no_contact_page(self):
        # 「无联系方式」合法页：字段全空但带字段标签 → done/no_contact，
        # 不能误判为 EMPTY 进策略链空转
        r = ok_result({"phone": None, "mobile": None, "fax": None,
                       "address": None, "contact_person": None,
                       "_raw": "联系方式\n电话：暂无\n手机：暂无\n地址：暂无\n"})
        self.assertTrue(self.task.validate(None, None, r))

    def test_invalid_garbage_page(self):
        # 软拦截/跳转错页：无字段也无标签 → False（按 EMPTY 处置）
        r = ok_result({"phone": None, "mobile": None, "contact_person": None,
                       "_raw": "恭喜发财大吉大利今晚吃鸡万事如意恭喜"})
        self.assertFalse(self.task.validate(None, None, r))


class ContactPersistTest(unittest.TestCase):
    """on_success / on_giveup 的入库语义（临时 sqlite）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = ContactTask()
        self.ctx = WorkerContext(store=IdentityStore(self.db),
                                 log=lambda m: None)
        self.ctx.state["task"] = {"stats": self.task.make_stats()}
        self.db.upsert_shops([{"domain": "shop1.1688.com", "name": "店铺一"},
                              {"domain": "shop2.1688.com", "name": "店铺二"}])
        self.item1 = self.db.conn.execute(
            "SELECT * FROM shops WHERE domain='shop1.1688.com'").fetchone()
        self.item2 = self.db.conn.execute(
            "SELECT * FROM shops WHERE domain='shop2.1688.com'").fetchone()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _status(self, domain):
        return self.db.conn.execute(
            "SELECT status FROM shops WHERE domain=?", (domain,)).fetchone()[0]

    def test_success_with_phone_marks_done(self):
        r = ok_result({"phone": "757-123", "mobile": None, "fax": None,
                       "address": "佛山", "contact_person": "张三",
                       "gender": "男", "_raw": "raw", "_source_url": "u"})
        n = self.task.on_success(self.ctx, self.item1, r)
        self.assertEqual(n, 1)
        self.assertEqual(self._status("shop1.1688.com"), "done")
        contact = self.db.conn.execute(
            "SELECT phone, contact_person FROM contacts c"
            " JOIN shops s ON c.shop_id=s.id"
            " WHERE s.domain='shop1.1688.com'").fetchone()
        self.assertEqual(contact["phone"], "757-123")

    def test_success_without_phone_marks_no_contact(self):
        r = ok_result({"phone": None, "mobile": None, "fax": None,
                       "address": "佛山", "contact_person": "李四",
                       "gender": "女", "_raw": "raw", "_source_url": "u"})
        self.task.on_success(self.ctx, self.item2, r)
        self.assertEqual(self._status("shop2.1688.com"), "no_contact")

    def test_giveup_marks_failed_and_costs_one(self):
        phrase = self.task.on_giveup(self.ctx, self.item1, "风控", "block")
        self.assertIn("failed", phrase)
        self.assertEqual(self._status("shop1.1688.com"), "failed")
        self.assertEqual(self.task.giveup_cost(self.item1), 1)

    def test_acquire_claims_pending(self):
        item = self.task.acquire_item(self.ctx)
        self.assertIsNotNone(item)
        self.assertEqual(self._status(item["domain"]), "in_progress")
        item2 = self.task.acquire_item(self.ctx)
        self.assertIsNotNone(item2)
        self.assertNotEqual(item["domain"], item2["domain"])  # 原子认领不撞单
        self.assertIsNone(self.task.acquire_item(self.ctx))


if __name__ == "__main__":
    unittest.main()
