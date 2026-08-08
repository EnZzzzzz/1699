# -*- coding: utf-8 -*-
"""FetchFbPost 原子 + facebook 提取逻辑单测。

样本全部来自 2026-08-06 PoC 实测帖（docs/channel-research/
facebook-groups.md §9），不依赖真实浏览器/网络。
"""

from __future__ import annotations

import threading
import unittest

from fetcher.atoms.facebook import FetchFbPost
from fetcher.core.types import Outcome
from fetcher.sites import get_site
from fetcher.sites.facebook.post import (
    BUCKET_CN_UNCERTAIN,
    BUCKET_DECLARED_WA,
    BUCKET_OVERSEAS,
    parse_post,
)

# ---- PoC 实测样本 ----

# 帖1：孚盟软件，标「电话☎微信」（注意 WhatsApp 出现在产品名里，是误标陷阱）
DESC_FUMENG = ("孚盟MX-WhatsApp管理功能重磅升级！助力外贸人高效沟通，促进成单！"
               "#WhatsApp #WhatsApp获客 #外贸获客 #外贸管理 #外贸软件 #外贸CRM"
               "管理软件【外贸获客-营销-管理系统软件。欢迎咨询👏 "
               "电话☎微信：13265351264】")

# 帖4：微信/WhatsApp 双标同号
DESC_DUAL = ("需要货代资源询价的工厂老板和外贸商们可以加我微信或者WhatsApp邀你进群，"
             "群内一手货代资源为您服务：微信：18118711701    "
             "WhatsApp：+8618118711701\n\nFactory owners and trading companies "
             "who need freight f")

# 帖2：ws 标签美国虚拟号 + TG + 薇信
DESC_WS = ("✨外贸获客效率王！Facebook/IG/WhatsApp 等全平台覆盖，智能 AI 自动化群发，"
           "矩阵视频营销 + 客服系统，官方 API 护航不踩雷，日获 50-300 + 精准客源🌍\n"
           "联系客服：TG:@ins98998  薇信：hhss777999 \n ws：+15623147681\n# 东南")

# 帖7：仅标微信（无冒号直连手机号形态）
DESC_WECHAT_ONLY = "寻找非洲进口到中国的货代 微信13819380524"

# 帖9：V+手机号
DESC_V_MOBILE = "有没有货代微信群，可以拉我一下吗V13609003989"

# DOM 正文里号码后紧跟换行+点赞计数（误并陷阱）
BODY_TRAILING_JUNK = "货代揽客 WhatsApp：+8618118711701\n1 条评论"


def _phones_by_bucket(info, bucket):
    return [p["number"] for p in info["phones"] if p["bucket"] == bucket]


class TestParsePost(unittest.TestCase):
    def test_product_name_whatsapp_not_a_label(self):
        """产品名里的 WhatsApp（后无号码）不应误判为自声明标签。"""
        info = parse_post(DESC_FUMENG, "")
        self.assertEqual(_phones_by_bucket(info, BUCKET_DECLARED_WA), [])
        self.assertEqual(_phones_by_bucket(info, BUCKET_CN_UNCERTAIN),
                         ["13265351264"])
        self.assertIn("13265351264", info["wechat_ids"])

    def test_dual_label_same_number(self):
        """微信/WhatsApp 双标同号 → 归自声明桶且只出现一次。"""
        info = parse_post(DESC_DUAL, "")
        self.assertEqual(_phones_by_bucket(info, BUCKET_DECLARED_WA),
                         ["8618118711701"])
        self.assertEqual(len(info["phones"]), 1)

    def test_ws_label_overseas_declared(self):
        """ws 标签的美国号 → 自声明桶（保留原国家码，不补 86）。"""
        info = parse_post(DESC_WS, "")
        self.assertEqual(_phones_by_bucket(info, BUCKET_DECLARED_WA),
                         ["15623147681"])
        self.assertEqual(_phones_by_bucket(info, BUCKET_CN_UNCERTAIN), [])
        self.assertIn("ins98998", info["tg_handles"])
        self.assertIn("hhss777999", info["wechat_ids"])

    def test_wechat_only_number_is_uncertain(self):
        """仅标微信的号 → 不确定桶（待 wa_check）。"""
        info = parse_post(DESC_WECHAT_ONLY, "")
        self.assertEqual(_phones_by_bucket(info, BUCKET_CN_UNCERTAIN),
                         ["13819380524"])
        self.assertIn("13819380524", info["wechat_ids"])

    def test_v_mobile_wechat_id(self):
        info = parse_post(DESC_V_MOBILE, "")
        self.assertEqual(_phones_by_bucket(info, BUCKET_CN_UNCERTAIN),
                         ["13609003989"])
        self.assertIn("13609003989", info["wechat_ids"])

    def test_wa_me_link(self):
        info = parse_post("咨询请加 wa.me/8613812345678 随时", "")
        self.assertEqual(_phones_by_bucket(info, BUCKET_DECLARED_WA),
                         ["8613812345678"])

    def test_group_invite(self):
        info = parse_post("进群 chat.whatsapp.com/AbCdEfGhIjKlMnOpQr12 欢迎", "")
        self.assertEqual(info["wa_group_invites"], ["AbCdEfGhIjKlMnOpQr12"])
        self.assertEqual(info["phones"], [])

    def test_intl_cc86_goes_cn_bucket(self):
        """未声明的 +86 国际格式号 → 中国不确定桶（存裸 11 位）。"""
        info = parse_post("call me +86 13912345678 anytime", "")
        self.assertEqual(_phones_by_bucket(info, BUCKET_CN_UNCERTAIN),
                         ["13912345678"])

    def test_intl_overseas_bucket(self):
        info = parse_post("contact +1 2025550123 for details", "")
        self.assertEqual(_phones_by_bucket(info, BUCKET_OVERSEAS),
                         ["12025550123"])

    def test_trailing_newline_junk_not_merged(self):
        """号码后换行+点赞计数不得并入号码。"""
        info = parse_post("", BODY_TRAILING_JUNK)
        self.assertEqual(_phones_by_bucket(info, BUCKET_DECLARED_WA),
                         ["8618118711701"])

    def test_empty_input(self):
        info = parse_post("", "")
        self.assertEqual(info["phones"], [])
        self.assertEqual(info["wa_group_invites"], [])


# ---- 原子测试（FakePage） ----

class FakePage:
    """最小 Playwright page 替身：goto 记录 URL，evaluate 按 JS 内容分发。"""

    class _Ctx:
        class browser:
            @staticmethod
            def is_connected():
                return True

    def __init__(self, og_desc="", body="", final_url=None, goto_error=None):
        self.og_desc = og_desc
        self.body = body
        self.url = final_url or ("https://www.facebook.com/groups/1/posts/2/")
        self.goto_error = goto_error
        self.frames = []
        self.context = self._Ctx()

    def is_closed(self):
        return False

    def goto(self, url, **kw):
        if self.goto_error:
            raise self.goto_error
        self.url = self.url

    def evaluate(self, js, *a):
        if "og:description" in js:
            return {"description": self.og_desc, "title": "T"}
        if "innerText" in js:
            return self.body
        return None

    def query_selector(self, sel):
        return None


class FakeCtx:
    def __init__(self, page=None, stopped=False):
        self.page = page
        self.stop = threading.Event()
        if stopped:
            self.stop.set()
        self.last_error = None
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)

    def stopped(self):
        return self.stop.is_set()

    def wait(self, seconds):
        return self.stop.wait(seconds)


class TestFetchFbPostAtom(unittest.TestCase):
    def setUp(self):
        self.atom = FetchFbPost()

    def test_missing_url(self):
        r = self.atom.run(FakeCtx(FakePage()), {})
        self.assertIs(r.outcome, Outcome.FATAL)

    def test_no_page(self):
        r = self.atom.run(FakeCtx(None), {"url": "https://x"})
        self.assertIs(r.outcome, Outcome.FATAL)

    def test_stopped(self):
        r = self.atom.run(FakeCtx(FakePage(), stopped=True),
                          {"url": "https://x"})
        self.assertIs(r.outcome, Outcome.SKIPPED)

    def test_ok_extracts_contacts(self):
        page = FakePage(og_desc=DESC_DUAL, body=DESC_DUAL)
        r = self.atom.run(FakeCtx(page),
                          {"url": "https://www.facebook.com/groups/1/posts/2/",
                           "render_wait": (0, 0)})
        self.assertIs(r.outcome, Outcome.OK)
        self.assertTrue(r.data["has_contact"])
        self.assertEqual(r.data["phones"][0]["bucket"], BUCKET_DECLARED_WA)

    def test_login_redirect_is_blocked(self):
        page = FakePage(body="请登录",
                        final_url="https://www.facebook.com/login.php?next=...")
        r = self.atom.run(FakeCtx(page), {"url": "https://x",
                                          "render_wait": (0, 0)})
        self.assertIs(r.outcome, Outcome.BLOCKED)

    def test_rate_limit_text_is_blocked(self):
        page = FakePage(body="You're Temporarily Blocked from using this "
                             "feature. " * 3)
        r = self.atom.run(FakeCtx(page), {"url": "https://x",
                                          "render_wait": (0, 0)})
        self.assertIs(r.outcome, Outcome.BLOCKED)

    def test_content_unavailable_is_empty(self):
        page = FakePage(body="This content isn't available right now. "
                             "When this happens, it's usually because the "
                             "owner only shared it with a small group.")
        r = self.atom.run(FakeCtx(page), {"url": "https://x",
                                          "render_wait": (0, 0)})
        self.assertIs(r.outcome, Outcome.EMPTY)

    def test_goto_timeout_is_net_error(self):
        page = FakePage(goto_error=TimeoutError("Timeout 60000ms exceeded"))
        r = self.atom.run(FakeCtx(page), {"url": "https://x",
                                          "render_wait": (0, 0)})
        self.assertIs(r.outcome, Outcome.NET_ERROR)


class TestPluginRegistration(unittest.TestCase):
    def test_site_registered(self):
        plugin = get_site("facebook")
        self.assertEqual(plugin.name, "facebook")
        self.assertEqual(plugin.cookie_domain, "facebook.com")
        # 二期接线（PLAN 1.2）：task_names 注册 post 任务（一期为空）
        self.assertEqual(plugin.task_names(), ["post"])
        self.assertEqual(len(plugin.detectors()), 4)


if __name__ == "__main__":
    unittest.main()
