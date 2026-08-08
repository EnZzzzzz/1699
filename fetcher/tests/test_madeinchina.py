# -*- coding: utf-8 -*-
"""madeinchina 站点插件测试：注册发现 / 探测器 / 解析纯函数 / fetch /
入库流转 / shop 任务 / 策略覆盖。全 mock，不起浏览器/网络。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fetcher import IdentityStore, RunConfig, Scenario, Session, ShopDB, \
    WorkerContext
from fetcher.core.types import ActionResult, Outcome
from fetcher.detect.base import SceneInspector
from fetcher.sites import get_site, site_names
from fetcher.sites.madeinchina.contact import (
    MadeInChinaContactTask,
    contact_url_for,
    parse_contact_page,
    showroom_sub,
)
from fetcher.sites.madeinchina.features import HOMEPAGE, MARKET_DIR
from fetcher.sites.madeinchina.shop import (
    ZERO_NEW_LIMIT,
    MadeInChinaShopTask,
    PLATFORM_SUBDOMAINS,
    build_market_url,
    is_platform_subdomain,
)
from fetcher.strategy.policy import Policy

from tests.test_control_loop import FakePage

CONTACT_URL = "https://cn.made-in-china.com/showroom/dihewujin-contact.html"
META = ("中国制造网，东莞市桥头迪贺五金制品厂，联系人：赵，"
        "联系电话：13728319349")
BODY = ("地址：广东省 东莞市 桥头镇 中国广东省东莞市桥头禾坑和里新村122\n"
        "传真：0769-82367598\n赵女士（业务员）\n")


class MICPage(FakePage):
    """madeinchina 联系方式页假页面：evaluate 按脚本分发 meta/正文。"""

    def __init__(self, meta=META, text=BODY, url=CONTACT_URL):
        super().__init__()
        self.url = url
        self._meta = meta
        self._text = text
        self.goto_calls = []
        self._exceptions = []

    def evaluate(self, js):
        if "meta[name" in js:
            return self._meta
        if "innerText" in js:
            return self._text
        return ""

    def goto(self, url, **kw):
        self.goto_calls.append((url, kw))
        self.url = url

    def set_captcha(self):
        """模拟 vemic 验证页：URL 不变、正文命中关键词。"""
        self._text = ("请验证\n请完成安全验证\n.main_div{width:80%}"
                      "captcha.vemic.com")
        self._meta = ""


class Frame:
    def __init__(self, url):
        self.url = url


class CtxStub:
    """探测器/策略测试用的最小 ctx（只读页面状态）。"""

    def __init__(self, page, last_error=None):
        self.page = page
        self.last_error = last_error


# ---------- 注册与发现 ----------

class RegistrationTest(unittest.TestCase):
    def test_site_registered(self):
        self.assertIn("madeinchina", site_names())

    def test_plugin_meta(self):
        site = get_site("madeinchina")
        self.assertEqual(site.name, "madeinchina")
        self.assertEqual(site.cookie_domain, "made-in-china.com")
        self.assertTrue(site.homepage.startswith("https://cn.made-in-china.com"))

    def test_task_names_and_make_task(self):
        site = get_site("madeinchina")
        self.assertEqual(site.task_names(), ["shop", "contact"])
        self.assertIsInstance(site.make_task("shop"), MadeInChinaShopTask)
        self.assertIsInstance(site.make_task("contact"),
                              MadeInChinaContactTask)
        with self.assertRaises(KeyError):
            site.make_task("nope")


# ---------- 探测器 ----------

class DetectorTest(unittest.TestCase):
    def setUp(self):
        site = get_site("madeinchina")
        self.inspector = SceneInspector.for_site(site)

    def test_normal_contact_page_ok(self):
        page = MICPage()
        hit = self.inspector.inspect(CtxStub(page))
        self.assertEqual(hit, Scenario.OK)

    def test_vemic_page_detected_by_text(self):
        # vemic 拦截页 URL 不变，靠正文关键词判定
        page = MICPage()
        page.set_captcha()
        hit = self.inspector.inspect(CtxStub(page))
        self.assertEqual(hit, Scenario.RISK_SLIDER_PAGE)

    def test_vemic_iframe_detected(self):
        page = MICPage()
        page.frames = [Frame("https://captcha.vemic.com/captcha?k=1")]
        hit = self.inspector.inspect(CtxStub(page))
        self.assertEqual(hit, Scenario.RISK_SLIDER_EMBED)

    def test_other_site_markers_not_hit(self):
        # 1688/义乌购的特征不误伤 madeinchina 正常页
        page = MICPage()
        page._text = "normal content with login.1688.com and nc_1_wrapper"
        hit = self.inspector.inspect(CtxStub(page))
        self.assertEqual(hit, Scenario.OK)


# ---------- 解析纯函数 ----------

class ParseTest(unittest.TestCase):
    def test_full_fields(self):
        info = parse_contact_page(META, BODY)
        self.assertEqual(info["mobile"], "13728319349")   # 裸号
        self.assertEqual(info["contact_person"], "赵")
        self.assertEqual(info["gender"], "女")            # 正文「赵女士」推断
        self.assertEqual(info["_company"], "东莞市桥头迪贺五金制品厂")
        self.assertEqual(info["address"],
                         "广东省 东莞市 桥头镇 中国广东省东莞市桥头禾坑和里新村122")
        self.assertEqual(info["fax"], "0769-82367598")
        self.assertIsNone(info["phone"])                   # 正文无座机行

    def test_body_full_name_preferred_over_meta_surname(self):
        # meta 只给姓「程」，正文给全名「程金明先生」→ 取全名 + 性别
        meta = "中国制造网，广东信烨管业有限公司，联系人：程，联系电话：13727426937"
        body = "程金明先生 （销售总监）\n地址：广东省 佛山市 顺德区\n"
        info = parse_contact_page(meta, body)
        self.assertEqual(info["contact_person"], "程金明")
        self.assertEqual(info["gender"], "男")

    def test_meta_full_name_wins_over_shorter_body(self):
        # meta 给全名「衣述刚」、正文只有「衣女士」→ 取更长的 meta 全名
        meta = "中国制造网，重庆灼光物资有限公司，联系人：衣述刚，联系电话：13452486668"
        body = "衣女士（业务员）\n地址：重庆市 大渡口区\n"
        info = parse_contact_page(meta, body)
        self.assertEqual(info["contact_person"], "衣述刚")
        self.assertEqual(info["gender"], "女")

    def test_mobile_with_spaces_dash(self):
        info = parse_contact_page("联系人：李，联系电话：137 1234 5678", "")
        self.assertEqual(info["mobile"], "13712345678")

    def test_empty_meta_and_body(self):
        info = parse_contact_page("", "")
        self.assertIsNone(info["mobile"])
        self.assertIsNone(info["contact_person"])
        self.assertIsNone(info["_company"])

    def test_contact_person_from_body_fallback(self):
        info = parse_contact_page("", "地址：佛山\n联系人：王\n")
        self.assertEqual(info["contact_person"], "王")

    def test_ascii_colon(self):
        info = parse_contact_page("联系人: 陈, 联系电话: 15538136469", "")
        self.assertEqual(info["mobile"], "15538136469")
        self.assertEqual(info["contact_person"], "陈")

    def test_contact_btn_placeholder_not_phone(self):
        # 正文「联系电话：」行是「查看电话号码」按钮占位（号码只在 meta），
        # 不能把占位文本塞进 phone 字段
        body = "联系电话：\n查看电话号码\n传真：\n0769-82367598\n地址：广东\n"
        info = parse_contact_page(META, body)
        self.assertIsNone(info["phone"])
        self.assertEqual(info["mobile"], "13728319349")
        self.assertEqual(info["fax"], "0769-82367598")

    def test_standalone_phone_line_parsed(self):
        body = ("电话：86-757-88886666\n传真：暂无\n地址：佛山\n"
                "联系电话：\n查看电话号码\n")
        info = parse_contact_page(META, body)
        self.assertEqual(info["phone"], "86-757-88886666")

    def test_url_helpers(self):
        self.assertEqual(showroom_sub("dihewujin.cn.made-in-china.com"),
                         "dihewujin")
        self.assertEqual(contact_url_for("dihewujin.cn.made-in-china.com"),
                         CONTACT_URL)

    def test_platform_subdomain_filter(self):
        self.assertTrue(is_platform_subdomain("caigou"))
        self.assertTrue(is_platform_subdomain("membercenter"))
        self.assertIn("caigou", PLATFORM_SUBDOMAINS)
        self.assertFalse(is_platform_subdomain("dihewujin"))


# ---------- contact fetch ----------

def ok_result(data):
    return ActionResult(Outcome.OK, "", data)


def make_ctx(page, db=None):
    ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
    ctx.session = Session(page=page)
    if db is not None:
        ctx.store = IdentityStore(db)
    ctx.state["task"] = {"stats": MadeInChinaContactTask().make_stats()}
    return ctx


class ContactFetchTest(unittest.TestCase):
    def setUp(self):
        self.task = MadeInChinaContactTask()
        self.item = {"domain": "dihewujin.cn.made-in-china.com",
                     "name": "迪贺五金",
                     "url": "https://dihewujin.cn.made-in-china.com/"}

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    def test_fetch_parses_contact(self, _r, _s):
        page = MICPage()
        ctx = make_ctx(page)
        result = self.task.fetch(ctx, self.item)
        self.assertEqual(result.outcome, Outcome.OK)
        self.assertEqual(result.data["mobile"], "13728319349")
        self.assertEqual(result.data["address"].startswith("广东省"), True)
        # goto 了联系方式页且 referer 是展厅首页
        url, kw = page.goto_calls[0]
        self.assertEqual(url, CONTACT_URL)
        self.assertEqual(kw.get("referer"),
                         "https://dihewujin.cn.made-in-china.com/")

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    def test_fetch_404_marks_dead(self, _r, _s):
        # 404 = HTTP 200 + 重定向到 errorDocs/404.html（实测非 404 状态码），
        # 按最终 URL 判定为 dead 死店
        page = MICPage()
        page.goto = lambda *a, **kw: setattr(
            page, "url",
            "https://cn.made-in-china.com/errorDocs/404.html")
        ctx = make_ctx(page)
        result = self.task.fetch(ctx, self.item)
        self.assertEqual(result.outcome, Outcome.OK)
        self.assertTrue(result.data.get("dead"))

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    def test_fetch_captcha_page_still_ok_data(self, _r, _s):
        # 验证页下 evaluate 取到的 meta/正文不匹配：fetch 不崩，走 blocked 由
        # 探测器判场景；这里验证 fetch 在异常页面下仍返回 OK（判空交给 validate）
        page = MICPage()
        page.set_captcha()
        ctx = make_ctx(page)
        result = self.task.fetch(ctx, self.item)
        self.assertEqual(result.outcome, Outcome.OK)

    def test_validate_dead(self):
        # 404 死店是合法业务态，直接放行（不进策略链空转）
        r = ok_result({"dead": True})
        self.assertTrue(self.task.validate(None, None, r))

    def test_validate_cases(self):
        cases = [
            # (data, expect_valid)
            ({"mobile": "13728319349", "_raw": "x"}, True),
            ({"phone": None, "mobile": None, "fax": None, "address": None,
              "contact_person": None, "_company": None,
              "_raw": "地址：暂无\n联系人：暂无\n联系电话：暂无"}, True),
            ({"phone": None, "mobile": None, "contact_person": None,
              "_raw": "恭喜发财大吉大利今晚吃鸡万事如意恭喜"}, False),
        ]
        for data, expect in cases:
            self.assertEqual(
                self.task.validate(None, None, ok_result(data)), expect)


# ---------- contact 入库 ----------

class ContactPersistTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "t.db")
        self.task = MadeInChinaContactTask()
        self.db.upsert_shops([
            {"domain": "dihewujin.cn.made-in-china.com", "name": "迪贺五金"},
            {"domain": "cqzgwz.cn.made-in-china.com", "name": "重庆灼光"},
        ])
        self.item1 = self.db.conn.execute(
            "SELECT * FROM shops WHERE domain='dihewujin.cn.made-in-china.com'"
        ).fetchone()
        self.item2 = self.db.conn.execute(
            "SELECT * FROM shops WHERE domain='cqzgwz.cn.made-in-china.com'"
        ).fetchone()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _status(self, domain):
        return self.db.conn.execute(
            "SELECT status FROM shops WHERE domain=?", (domain,)).fetchone()[0]

    def test_success_with_mobile_marks_done(self):
        ctx = make_ctx(MICPage(), db=self.db)
        r = ok_result({"phone": None, "mobile": "13728319349", "fax": None,
                       "address": "东莞", "contact_person": "赵",
                       "gender": None, "_company": "迪贺", "_raw": "raw",
                       "_source_url": "u"})
        n = self.task.on_success(ctx, self.item1, r)
        self.assertEqual(n, 1)
        self.assertEqual(self._status("dihewujin.cn.made-in-china.com"),
                         "done")
        contact = self.db.conn.execute(
            "SELECT mobile, address FROM contacts c"
            " JOIN shops s ON c.shop_id=s.id"
            " WHERE s.domain='dihewujin.cn.made-in-china.com'").fetchone()
        self.assertEqual(contact["mobile"], "13728319349")

    def test_success_without_phone_marks_no_contact(self):
        ctx = make_ctx(MICPage(), db=self.db)
        r = ok_result({"phone": None, "mobile": None, "fax": None,
                       "address": "重庆", "contact_person": "衣",
                       "gender": None, "_company": "灼光", "_raw": "raw",
                       "_source_url": "u"})
        self.task.on_success(ctx, self.item2, r)
        self.assertEqual(self._status("cqzgwz.cn.made-in-china.com"),
                         "no_contact")

    def test_acquire_claims_pending(self):
        ctx = make_ctx(MICPage(), db=self.db)
        item = self.task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(self._status(item["domain"]), "in_progress")

    def test_success_dead_marks_no_contact_without_row(self):
        # 404 死店：标 no_contact 但**不写 contacts 行**（无可解析数据），
        # 也不计 failed（--retry-failed 不应再重试它）
        ctx = make_ctx(MICPage(), db=self.db)
        r = ok_result({"dead": True})
        n = self.task.on_success(ctx, self.item1, r)
        self.assertEqual(n, 1)
        self.assertEqual(self._status("dihewujin.cn.made-in-china.com"),
                         "no_contact")
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM contacts c JOIN shops s ON c.shop_id=s.id"
            " WHERE s.domain='dihewujin.cn.made-in-china.com'").fetchone()[0]
        self.assertEqual(row, 0)  # 不入 contacts 表

    def test_acquire_skips_other_source_shops(self):
        # 共享库：1688 店铺不该被 madeinchina contact 认领（否则会拿 1688
        # 域名拼 made-in-china 联系方式 URL，并触发 1688 风控）
        self.db.upsert_shops([{"domain": "shop1.1688.com", "name": "1688店"}])
        ctx = make_ctx(MICPage(), db=self.db)
        item = self.task.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertTrue(item["domain"].endswith(".cn.made-in-china.com"))
        # 1688 店铺保持 pending，未被触碰
        self.assertEqual(self._status("shop1.1688.com"), "pending")
        # 两个 madeinchina 店都认领完后，acquire 返回 None（1688 店不补位）
        _ = self.task.acquire_item(ctx)
        self.assertIsNone(self.task.acquire_item(ctx))


# ---------- shop 任务 ----------

class ShopTaskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ShopDB(Path(self._tmp.name) / "s.db")
        self.task = MadeInChinaShopTask()
        self._tmp2 = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()
        self._tmp2.cleanup()

    def test_build_market_url(self):
        self.assertEqual(build_market_url("wujingj", 1),
                         "https://cn.made-in-china.com/market/wujingj_2-1.html")
        self.assertEqual(build_market_url("wujingj", 2),
                         "https://cn.made-in-china.com/market/wujingj_2-2.html")
        # -N 体系：fmt="plain" 拼 {slug}-{page}.html（jgdbj/huafangchuan 等）
        self.assertEqual(build_market_url("jgdbj", 1, fmt="plain"),
                         "https://cn.made-in-china.com/market/jgdbj-1.html")
        self.assertEqual(build_market_url("jgdbj", 2, fmt="plain"),
                         "https://cn.made-in-china.com/market/jgdbj-2.html")

    def test_fetch_uses_fmt_from_payload(self):
        # fmt="plain"：fetch 应拼 {slug}-{page}.html，而不是 _2-
        page = MICPage()
        page.url = "https://cn.made-in-china.com/market/jgdbj-1.html"
        page._shops = [
            {"domain": "daqinjiguang.cn.made-in-china.com", "name": "大秦"}]
        page._next = False
        orig_evaluate = page.evaluate

        def eval_dispatch(js):
            if "location.pathname" in js:
                return {"shops": page._shops, "next": False,
                        "found": "1"}
            return orig_evaluate(js)

        page.evaluate = eval_dispatch
        ctx = make_ctx(page, db=self.db)
        # fmt 从 payload 获取（不再查池）
        item = {"kind": "category", "keyword": "jgdbj",
                "name": "激光打标机", "fmt": "plain"}
        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)
        # 访问的是 -1.html 短链 URL（不是 _2-1.html）
        url, kw = page.goto_calls[0]
        self.assertEqual(url,
                         "https://cn.made-in-china.com/market/jgdbj-1.html")
        self.assertEqual(kw.get("referer"), HOMEPAGE)

    def test_is_platform_subdomain(self):
        self.assertTrue(is_platform_subdomain("caigou"))
        self.assertFalse(is_platform_subdomain("dihewujin"))

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    def test_fetch_extracts_showrooms(self, _r, _s):
        page = MICPage()
        page.url = "https://cn.made-in-china.com/market/wujingj_2-1.html"
        page._shops = [
            {"domain": "dihewujin.cn.made-in-china.com", "name": "迪贺"},
            {"domain": "caigou.cn.made-in-china.com", "name": "采购"},  # 平台子域
            {"domain": "cqzgwz.cn.made-in-china.com", "name": "灼光"},
        ]
        page._next = True
        orig_evaluate = page.evaluate

        def eval_dispatch(js):
            if "location.pathname" in js:      # _JS_EXTRACT_SHOWROOMS
                return {"shops": page._shops, "next": page._next,
                        "found": str(len(page._shops))}
            return orig_evaluate(js)

        page.evaluate = eval_dispatch
        ctx = make_ctx(page, db=self.db)
        # page_no 从 category_progress 读（无记录→1）
        item = {"kind": "category", "keyword": "wujingj",
                "name": "五金工具", "fmt": "x2"}
        result = self.task.fetch(ctx, item)
        self.assertEqual(result.outcome, Outcome.OK)
        domains = [s["domain"] for s in result.data["shops"]]
        self.assertIn("dihewujin.cn.made-in-china.com", domains)
        self.assertNotIn("caigou.cn.made-in-china.com", domains)  # 已过滤
        self.assertEqual(result.data["has_more"], True)
        # 确认访问了第 1 页（无 category_progress → 1）
        url, kw = page.goto_calls[0]
        self.assertEqual(url, build_market_url("wujingj", 1))
        self.assertEqual(kw.get("referer"), HOMEPAGE)

    def test_on_success_empty_marks_exhausted(self):
        page = MICPage()
        ctx = make_ctx(page, db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()
        r = ok_result({"shops": [], "has_more": False})
        item = {"kind": "category", "keyword": "wujingj",
                "name": "五金工具", "fmt": "x2"}
        n = self.task.on_success(ctx, item, r)
        self.assertEqual(n, 0)
        self.assertIn("wujingj", self.db.get_exhausted_keywords())

    def test_on_success_zero_new_marks_exhausted_after_limit(self):
        page = MICPage()
        ctx = make_ctx(page, db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()
        self.db.upsert_shops([
            {"domain": "dup1.cn.made-in-china.com", "name": "重复店"}])
        r = ok_result({"shops": [
            {"domain": "dup1.cn.made-in-china.com", "name": "重复店"}],
            "has_more": True})
        # 前 limit-1 页零新增：页码前进，不 exhausted
        for _ in range(1, ZERO_NEW_LIMIT):
            item = {"kind": "category", "keyword": "bxgyxg",
                    "name": "不锈钢异型管", "fmt": "x2"}
            self.task.on_success(ctx, item, r)
            self.assertNotIn("bxgyxg", self.db.get_exhausted_keywords())
        # 第 limit 页零新增：标 exhausted
        item = {"kind": "category", "keyword": "bxgyxg",
                "name": "不锈钢异型管", "fmt": "x2"}
        self.task.on_success(ctx, item, r)
        self.assertIn("bxgyxg", self.db.get_exhausted_keywords())

    def test_on_success_zero_new_resets_after_fresh_page(self):
        page = MICPage()
        ctx = make_ctx(page, db=self.db)
        ctx.state["task"]["stats"] = self.task.make_stats()
        self.db.upsert_shops([
            {"domain": "dup1.cn.made-in-china.com", "name": "重复店"}])
        dup = ok_result({"shops": [
            {"domain": "dup1.cn.made-in-china.com", "name": "重复店"}],
            "has_more": True})
        fresh = ok_result({"shops": [
            {"domain": "fresh1.cn.made-in-china.com", "name": "新店"}],
            "has_more": True})
        # 1 页零新增 → 1 页有新增（清计数）→ 再 1 页零新增：不应 exhausted
        item = {"kind": "category", "keyword": "wujingj",
                "name": "五金工具", "fmt": "x2"}
        self.task.on_success(ctx, item, dup)
        self.task.on_success(ctx, item, fresh)
        self.task.on_success(ctx, item, dup)
        self.assertNotIn("wujingj", self.db.get_exhausted_keywords())

    # ---- 类目提取正则：兼容 _2-N 与 -N，排除 _1-N ----

    def test_extract_categories_js_matches_both_url_forms(self):
        # 只有拼音类目才算 madeinchina market slug；中文关键词行（1688 等
        # 其他任务）与 company: 前缀不算，exhausted 的不算
        from fetcher.db import _is_pinyin_slug
        self.assertTrue(_is_pinyin_slug("bxgyxg"))
        self.assertTrue(_is_pinyin_slug("wujingj"))
        self.assertFalse(_is_pinyin_slug("马面裙"))
        self.assertFalse(_is_pinyin_slug("company:快递袋"))
        self.assertFalse(_is_pinyin_slug("运动腰包、配件包"))

    def test_prepare_seeds_from_db(self):
        # prepare 从 category_progress 播种 category item + discover item
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page) "
            "VALUES ('bxgyxg', '不锈钢异型管', 2)")
        self.db.conn.execute(
            "INSERT INTO category_progress (keyword, name, next_page, "
            "exhausted) VALUES ('xxylsb', '新型游乐设备', 1, 1)")
        self.db.conn.commit()
        db_path = self.db.conn.execute(
            "PRAGMA database_list").fetchone()[2]
        self.db.close()
        cfg = RunConfig()
        cfg.db_path = db_path
        task = MadeInChinaShopTask()
        self.assertTrue(task.prepare(cfg))
        # 验证播种了 work_items
        db_check = ShopDB(db_path)
        import json
        items = db_check.conn.execute(
            "SELECT payload_json FROM work_items WHERE queue=? "
            "AND status='pending' ORDER BY id",
            ("crawl_mic_shop",)).fetchall()
        payloads = [json.loads(r["payload_json"]) for r in items]
        # bxgyxg 应播种为 category item
        self.assertTrue(any(
            p.get("kind") == "category" and p.get("keyword") == "bxgyxg"
            for p in payloads))
        # xxylsb 是 exhausted，不应播种
        self.assertFalse(any(
            p.get("keyword") == "xxylsb" for p in payloads))
        # 至少一条 discover
        self.assertTrue(any(
            p.get("kind") == "discover" for p in payloads))
        db_check.close()

    def test_get_active_categories_pinyin_only(self):
        import re
        # 与 _JS_EXTRACT_CATEGORIES 里的正则镜像校验：JS 侧 regex 是
        # /\\/market\\/([a-zA-Z0-9]+?)(?:_2)?-\\d+\\.html/，这里用等价
        # Python 正则验证匹配语义（_2- 分页页与 -1.html 短链都要，_1- 移动
        # 端变体排除），并验证 fmt 判定（含 _2- 前缀 -> x2，否则 plain）
        pat = re.compile(r"/market/([a-zA-Z0-9]+?)(?:_2)?-\d+\.html")
        cases = [
            ("/market/bxgyxg_2-1.html", "bxgyxg", "x2"),    # _2- 分页格式
            ("/market/jgdbj-1.html", "jgdbj", "plain"),     # -1.html 短链
            ("/market/CODcdy-1.html", "CODcdy", "plain"),   # 含大写 slug
            ("/market/PEgsg-1.html", "PEgsg", "plain"),
            ("/market/316Lbxg-1.html", "316Lbxg", "plain"),
            ("/market/cspsj_1-1.html", None, None),         # _1- 移动端变体，排除
            ("/market/mzhxt_1-1.html", None, None),
        ]
        for href, expect_slug, expect_fmt in cases:
            m = pat.search(href)
            got = m.group(1) if m else None
            self.assertEqual(got, expect_slug, href)
            if m is not None:
                fmt = "x2" if "_2-" in m.group(0) else "plain"
                self.assertEqual(fmt, expect_fmt, href)

    # ---- cold_start 纯浏览软着陆 ----

    @patch("time.sleep")
    @patch("random.uniform", return_value=1.0)
    def test_cold_start_browses_home_and_market_dir(self, _r, _s):
        """冷启动仅浏览首页+导航页（软着陆），不提取类目。"""
        page = MICPage()
        ctx = make_ctx(page)
        self.task.cold_start(ctx, None)
        urls = [u for u, _ in page.goto_calls]
        self.assertIn(HOMEPAGE, urls)
        self.assertIn(MARKET_DIR, urls)
        # 没有提取类目（cold_start 不再做这事）
        # 验证 goto 正常完成即可
        self.assertEqual(len(urls), 2)


# ---------- 策略覆盖 ----------

class PolicyOverrideTest(unittest.TestCase):
    def test_no_solve_slider_for_vemic(self):
        site = get_site("madeinchina")
        overrides = site.policy_overrides
        self.assertIn(Scenario.RISK_SLIDER_PAGE, overrides)
        for chain in overrides.values():
            actions = [a for a, _ in chain]
            self.assertNotIn("solve_slider", actions)


if __name__ == "__main__":
    unittest.main()
