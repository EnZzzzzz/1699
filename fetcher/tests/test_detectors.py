# -*- coding: utf-8 -*-
"""Detector 单测：mock page（url/innerText/frames/query_selector），
验证各 Scenario 判定。不起真实浏览器/网络。"""

import unittest

from fetcher import (
    Alibaba1688Plugin,
    Scenario,
    SceneInspector,
    Session,
    WorkerContext,
)


# ---------- mock page ----------

class FakeElement:
    def __init__(self, visible=True):
        self._visible = visible

    def is_visible(self):
        return self._visible


class FakeFrame:
    def __init__(self, url):
        self.url = url


class FakeBrowser:
    def __init__(self, connected=True):
        self._connected = connected

    def is_connected(self):
        return self._connected


class FakeContext:
    def __init__(self, connected=True, cookies=()):
        self.browser = FakeBrowser(connected)
        self._cookies = list(cookies)

    def cookies(self):
        return list(self._cookies)


class FakePage:
    """鸭子类型 mock：支持 Detector 用到的全部 page 接口。"""

    def __init__(self, url="https://detail.1688.com/offer/1.html",
                 text="这是一段足够长的正常页面文本，包含商品详情、店铺信息、"
                      "联系方式与公司介绍，长度远超空白页判定阈值。",
                 frames=(), selectors=None, connected=True, closed=False):
        self.url = url
        self._text = text
        self.frames = list(frames)
        self._selectors = selectors or {}
        self.context = FakeContext(connected)
        self._closed = closed

    def evaluate(self, js):
        return self._text

    def query_selector(self, sel):
        return self._selectors.get(sel)

    def is_closed(self):
        return self._closed


def make_ctx(page=None, last_error=None):
    ctx = WorkerContext(log=lambda m: None)
    ctx.session = Session(page=page)
    ctx.site = Alibaba1688Plugin()
    ctx.last_error = last_error
    return ctx


class DetectorTestCase(unittest.TestCase):
    def setUp(self):
        self.inspector = SceneInspector.for_site(Alibaba1688Plugin())

    def inspect(self, page=None, last_error=None):
        return self.inspector.inspect(make_ctx(page, last_error))

    # ---- 风控场景 ----

    def test_login_wall_by_url(self):
        page = FakePage(url="https://login.1688.com/member/signin.htm")
        self.assertIs(self.inspect(page), Scenario.RISK_LOGIN)

    def test_login_wall_beats_slider_keywords(self):
        # 登录页常带"安全验证"文案：登录墙必须优先于整页滑块
        page = FakePage(url="https://login.1688.com/member/signin.htm",
                        text="安全验证 请登录后继续 " * 5)
        self.assertIs(self.inspect(page), Scenario.RISK_LOGIN)

    def test_slider_page_by_url(self):
        for url in ("https://sec.1688.com/punish.htm?x5sec=abc",
                    "https://detail.1688.com/captcha/verify"):
            with self.subTest(url=url):
                self.assertIs(self.inspect(FakePage(url=url)),
                              Scenario.RISK_SLIDER_PAGE)

    def test_slider_page_by_text_keyword(self):
        page = FakePage(text="亲，请完成验证，拖动下方滑块完成安全验证。"
                             "补充一些文本让长度超过空白阈值。")
        self.assertIs(self.inspect(page), Scenario.RISK_SLIDER_PAGE)

    def test_embedded_slider_by_iframe(self):
        frames = [FakeFrame("https://sec.1688.com/x5sec/punish_iframe.htm")]
        page = FakePage(frames=frames)
        self.assertIs(self.inspect(page), Scenario.RISK_SLIDER_EMBED)

    def test_embedded_slider_by_dom_selector(self):
        page = FakePage(selectors={"#nocaptcha": FakeElement(visible=True)})
        self.assertIs(self.inspect(page), Scenario.RISK_SLIDER_EMBED)

    def test_embedded_slider_invisible_selector_ignored(self):
        page = FakePage(selectors={"#nocaptcha": FakeElement(visible=False)})
        self.assertIs(self.inspect(page), Scenario.OK)

    def test_empty_page(self):
        page = FakePage(text="   ")
        self.assertIs(self.inspect(page), Scenario.EMPTY)

    def test_normal_page_is_ok(self):
        self.assertIs(self.inspect(FakePage()), Scenario.OK)

    # ---- 通用场景（错误分级） ----

    def test_net_error_by_marker(self):
        err = Exception("net::ERR_TUNNEL_CONNECTION_FAILED")
        self.assertIs(self.inspect(FakePage(), last_error=err),
                      Scenario.NET_ERROR)

    def test_net_stall_on_timeout_alive_browser(self):
        err = Exception("Timeout 60000ms exceeded.")
        self.assertIs(self.inspect(FakePage(), last_error=err),
                      Scenario.NET_STALL)

    def test_browser_dead_by_error_marker(self):
        err = Exception("Target page, context or browser has been closed")
        self.assertIs(self.inspect(FakePage(), last_error=err),
                      Scenario.BROWSER_DEAD)

    def test_browser_dead_by_probe(self):
        page = FakePage(connected=False)
        self.assertIs(self.inspect(page), Scenario.BROWSER_DEAD)

    def test_page_closed_is_dead(self):
        page = FakePage(closed=True)
        self.assertIs(self.inspect(page), Scenario.BROWSER_DEAD)

    def test_last_error_suppresses_site_detectors(self):
        # 有异常时站点探测器不读页面（即使 URL 像登录墙）
        page = FakePage(url="https://login.1688.com/member/signin.htm")
        err = Exception("net::ERR_CONNECTION_RESET")
        self.assertIs(self.inspect(page, last_error=err), Scenario.NET_ERROR)


if __name__ == "__main__":
    unittest.main()
