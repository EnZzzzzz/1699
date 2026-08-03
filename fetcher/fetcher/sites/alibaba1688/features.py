# -*- coding: utf-8 -*-
"""1688 风控特征表 + 站点探测器装配 + mtop 握手（1688 域）。

判定结构（登录墙/整页滑块/内嵌滑块/空页探测器、page_block_reason、
mtop 握手）全部复用通用件（detect/generic.py 参数化探测器 +
sites/mtop.py），本文件只提供 1688 的特征表数据与域参数 ——
与 taobao 插件的差异即特征表内容，结构零重复。
"""

from __future__ import annotations

from fetcher.detect.generic import (
    EmbeddedSliderDetector,
    EmptyPageDetector,
    LoginWallDetector,
    SliderPageDetector,
    make_block_reason,
    page_text,
    page_url,
    url_hit,
)
from fetcher.sites import mtop as _mtop

HOMEPAGE = "https://www.1688.com/"

# 搜索域落地页（低敏）：用于 mtop 握手，不直接碰 offer_search 深链
SEARCH_HOME = "https://s.1688.com/"

# ---------- 1688 风控特征表 ----------

# 登录墙 URL 特征（最高级风控，单独成场景）
LOGIN_URL_PATTERNS = ("login.1688.com",)

# 风控拦截页的 URL 特征（除登录墙外）
BLOCK_URL_PATTERNS = (
    "sec.1688.com",     # 安全中心拦截
    "punish",           # 处罚/验证页
    "x5sec",            # x5sec 滑块验证
    "captcha",
)

# 风控拦截页的内容关键词
BLOCK_TEXT_KEYWORDS = (
    "滑动验证", "安全验证", "拖动下方滑块", "验证中心",
    "访问受限", "访问存在异常", "访问过于频繁",
    "系统检测到您的访问异常", "亲，请完成验证",
)

# 空白页阈值：innerText 少于此字符数视为异常空白
EMPTY_TEXT_THRESHOLD = 30

# 内嵌滑块/验证组件特征：滑块常作为 iframe 或独立 DOM 容器注入业务
# 页面（联系方式与滑块同屏的场景），innerText 检测会漏判
EMBEDDED_SLIDER_IFRAME_PATTERNS = (
    "x5sec", "punish", "captcha", "_____tmd_____", "sec.1688.com",
)
EMBEDDED_SLIDER_SELECTORS = (
    "#nocaptcha",        # 阿里滑动验证容器（经典版）
    "[id^='nc_']",       # nc_1_wrapper / nc_1_nocaptcha 等新版滑块
    ".nc-container",     # 新版滑块容器
    "#baxia-dialog",     # 百隙安全弹窗
    "[class*='baxia']",  # 百隙组件
)

MTOP_TOKEN_NAME = _mtop.MTOP_TOKEN_NAME
COOKIE_DOMAIN = "1688.com"


# ---------- 探测器装配（优先级序：登录墙 > 整页滑块 > 内嵌滑块 > 空页） ----------

def make_detectors() -> list:
    """1688 站点探测器（SceneInspector 拼在通用探测器之后）。"""
    return [
        LoginWallDetector(LOGIN_URL_PATTERNS, name="1688_login_wall"),
        SliderPageDetector(BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
                           name="1688_slider_page"),
        EmbeddedSliderDetector(EMBEDDED_SLIDER_IFRAME_PATTERNS,
                               EMBEDDED_SLIDER_SELECTORS,
                               name="1688_slider_embed"),
        EmptyPageDetector(EMPTY_TEXT_THRESHOLD, name="1688_empty_page"),
    ]


# 「是否被拦/已过证」的统一口径（含登录墙与空白页）
page_block_reason = make_block_reason(
    LOGIN_URL_PATTERNS, BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
    EMBEDDED_SLIDER_IFRAME_PATTERNS, EMBEDDED_SLIDER_SELECTORS,
    threshold=EMPTY_TEXT_THRESHOLD)


# ---------- 兼容引用（历史调用点，行为不变） ----------

def is_login_wall(url: str) -> bool:
    return url_hit(url, LOGIN_URL_PATTERNS) is not None


def block_page_reason(url: str, text: str) -> str | None:
    """整页滑块判定（URL + 文本特征），未命中返回 None。"""
    return SliderPageDetector(BLOCK_URL_PATTERNS,
                              BLOCK_TEXT_KEYWORDS).block_reason(url, text)


def detect_embedded_slider(page) -> str | None:
    """检测页面内嵌的滑块/验证组件（iframe URL + 滑块 DOM 容器）。"""
    return EmbeddedSliderDetector(
        EMBEDDED_SLIDER_IFRAME_PATTERNS,
        EMBEDDED_SLIDER_SELECTORS).embedded_reason(page)


# ---------- mtop 握手（搜索域入场券，1688 域） ----------

def has_mtop_token(page) -> bool:
    """会话是否已持有 mtop API 令牌（_m_h5_tk，1688 域）。"""
    return _mtop.has_mtop_token(page, domain=COOKIE_DOMAIN)


def ensure_mtop_token(page, log=None, attempts: int = 2) -> bool:
    """确保会话持有 _m_h5_tk：没有就访问搜索域落地页触发签发。"""
    return _mtop.ensure_mtop_token(page, SEARCH_HOME, HOMEPAGE,
                                   domain=COOKIE_DOMAIN, log=log,
                                   attempts=attempts)
