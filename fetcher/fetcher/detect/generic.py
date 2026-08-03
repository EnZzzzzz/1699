# -*- coding: utf-8 -*-
"""通用探测器：与具体站点无关的场景判断。

FatalErrorDetector  浏览器死活（BROWSER_DEAD）——优先级最高：
                    浏览器死了，页面上的一切特征都不可信。
NetworkDetector     网络层错误分级（NET_ERROR / NET_STALL）：
                    依据 ctx.last_error（抓取时捕获的异常）分级；
                    无异常时不命中。
"""

from __future__ import annotations

from fetcher.core.errors import (
    browser_alive,
    is_fatal_browser_error,
    is_network_error,
)
from fetcher.core.types import Scenario


class FatalErrorDetector:
    """浏览器进程死亡/被关闭 → BROWSER_DEAD。

    命中条件（任一）：
        - ctx.last_error 命中致命特征（TargetClosed / 会话被服务端关闭等）；
        - 浏览器连接已断 / 页面已关闭（browser_alive 探测）。
    """

    name = "fatal_error"

    def detect(self, ctx) -> Scenario | None:
        err = ctx.last_error
        if err is not None and is_fatal_browser_error(err):
            return Scenario.BROWSER_DEAD
        page = ctx.page
        if page is not None and not browser_alive(page):
            return Scenario.BROWSER_DEAD
        return None


class NetworkDetector:
    """网络层错误分级：NET_ERROR（隧道层）/ NET_STALL（页面没加载出来）。

    只依据 ctx.last_error 分级，不主动发请求：
        - 命中 Chromium net::ERR_* 特征 → NET_ERROR（请求没到目标站，
          与风控无关，不应计入风控连续失败计数）；
        - 其他异常（多为 goto 超时）且浏览器活着 → NET_STALL；
        - 无异常 → None（放行给站点探测器）。
    """

    name = "network"

    def detect(self, ctx) -> Scenario | None:
        err = ctx.last_error
        if err is None:
            return None
        if is_fatal_browser_error(err):
            return None  # 交给 FatalErrorDetector
        if is_network_error(err):
            return Scenario.NET_ERROR
        return Scenario.NET_STALL


# ---------------------------------------------------------------- 参数化站点探测器
#
# 阿里系（1688/淘宝/天猫...）风控判定结构同构：登录墙 URL、整页滑块
# URL/文本特征、内嵌滑块 iframe/DOM、空白页。差异全在特征表数据。
# 以下探测器以特征表为构造参数，站点插件只提供自己的表即可复用判定
# 结构 ——「继承通用件 + 只写差异」。


def page_url(page) -> str:
    """安全读取当前 URL（只读，不动浏览器）。"""
    try:
        return page.url or ""
    except Exception:  # noqa: BLE001
        return ""


def page_text(page) -> str:
    """安全读取 body innerText（只读，不发起新请求）。"""
    try:
        return page.evaluate(
            "() => document.body ? document.body.innerText : ''") or ""
    except Exception:  # noqa: BLE001
        return ""


def url_hit(url: str, patterns) -> str | None:
    """URL 命中特征表中的任一项，返回命中项。"""
    u = (url or "").lower()
    for p in patterns:
        if p in u:
            return p
    return None


class LoginWallDetector:
    """登录墙（被强制跳登录页）→ RISK_LOGIN。站点探测器中优先级最高：

    登录页通常同时带滑块/验证文案，不先拆出来会被滑块场景截胡，
    而登录墙的处置（烧毁身份）与滑块完全不同。
    """

    def __init__(self, url_patterns, name: str = "login_wall"):
        self.url_patterns = tuple(url_patterns)
        self.name = name

    def detect(self, ctx) -> Scenario | None:
        page = ctx.page
        if page is None or ctx.last_error is not None:
            return None
        if url_hit(page_url(page), self.url_patterns):
            return Scenario.RISK_LOGIN
        return None


class SliderPageDetector:
    """整页滑块跳转（URL/文本命中风控特征）→ RISK_SLIDER_PAGE。"""

    def __init__(self, url_patterns, text_keywords,
                 name: str = "slider_page"):
        self.url_patterns = tuple(url_patterns)
        self.text_keywords = tuple(text_keywords)
        self.name = name

    def block_reason(self, url: str, text: str) -> str | None:
        hit = url_hit(url, self.url_patterns)
        if hit:
            return f"URL 命中风控特征 '{hit}'（{url}）"
        t = (text or "").strip()
        for kw in self.text_keywords:
            if kw in t:
                return f"页面内容命中风控关键词 '{kw}'"
        return None

    def detect(self, ctx) -> Scenario | None:
        page = ctx.page
        if page is None or ctx.last_error is not None:
            return None
        if self.block_reason(page_url(page), page_text(page)):
            return Scenario.RISK_SLIDER_PAGE
        return None


class EmbeddedSliderDetector:
    """内嵌滑块（滑块组件与页面内容同屏）→ RISK_SLIDER_EMBED。

    iframe 内容不进 innerText，纯文本判定会把内嵌滑块误判为已通过，
    必须看 iframe URL 特征 + 滑块 DOM 容器选择器。
    """

    def __init__(self, iframe_patterns, dom_selectors,
                 name: str = "slider_embed"):
        self.iframe_patterns = tuple(iframe_patterns)
        self.dom_selectors = tuple(dom_selectors)
        self.name = name

    def embedded_reason(self, page) -> str | None:
        try:
            for f in page.frames:
                hit = url_hit(f.url, self.iframe_patterns)
                if hit:
                    return f"页面内嵌验证 iframe（{f.url[:120]}）"
        except Exception:  # noqa: BLE001
            pass
        try:
            for sel in self.dom_selectors:
                el = page.query_selector(sel)
                if el is not None and el.is_visible():
                    return f"页面内嵌滑块组件（选择器 {sel}）"
        except Exception:  # noqa: BLE001
            pass
        return None

    def detect(self, ctx) -> Scenario | None:
        page = ctx.page
        if page is None or ctx.last_error is not None:
            return None
        if self.embedded_reason(page):
            return Scenario.RISK_SLIDER_EMBED
        return None


class EmptyPageDetector:
    """页面内容异常空白（innerText 短于阈值）→ EMPTY。

    可能是软拦截也可能是正常空页 —— 判 EMPTY 走软处置链；任务层的
    validate() 结构化判空优先，本探测器只是兜底。
    """

    def __init__(self, threshold: int = 30, name: str = "empty_page"):
        self.threshold = threshold
        self.name = name

    def detect(self, ctx) -> Scenario | None:
        page = ctx.page
        if page is None or ctx.last_error is not None:
            return None
        if len(page_text(page).strip()) < self.threshold:
            return Scenario.EMPTY
        return None


def make_block_reason(login_patterns, url_patterns, text_keywords,
                      iframe_patterns, dom_selectors, threshold: int = 30):
    """生成站点「是否被拦/已过证」的统一判定函数（含登录墙与空白页）。

    所有人工过证/自动过证场景的判定统一走它，避免各入口口径不一致。
    """
    slider = SliderPageDetector(url_patterns, text_keywords)
    embed = EmbeddedSliderDetector(iframe_patterns, dom_selectors)

    def block_reason(page) -> str | None:
        url = page_url(page)
        text = page_text(page)
        hit = url_hit(url, login_patterns)
        if hit:
            return f"URL 命中登录墙（{url}）"
        reason = slider.block_reason(url, text)
        if reason:
            return reason
        reason = embed.embedded_reason(page)
        if reason:
            return reason
        t = (text or "").strip()
        if len(t) < threshold:
            return f"页面内容异常空白（仅 {len(t)} 字符，疑似拦截页）"
        return None

    return block_reason
