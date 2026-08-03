# -*- coding: utf-8 -*-
"""淘宝风控特征表 + 站点探测器装配 + mtop 握手（taobao.com 域）。

与 1688 同属阿里系，判定结构完全复用通用件（detect/generic.py
参数化探测器 + sites/mtop.py），本文件只有特征表数据。

⚠️ 待真实环境校准的条目（标注 [CAL]）：以下特征按阿里系公开认知与
1688 同族经验合理编写，尚未在淘宝真实风控页上逐条验证：
    [CAL-1] LOGIN_URL_PATTERNS：login.taobao.com 为主登录域；
            未包含 login.tmall.com（天猫任务启用时再补）。
    [CAL-2] BLOCK_URL_PATTERNS：sec.taobao.com / punish / x5sec /
            captcha 与 1688 同族；淘宝特有的 "_____tmd_____" 路径段
            是否出现在整页跳转 URL 中待确认（目前只放在 iframe 特征里）。
    [CAL-3] BLOCK_TEXT_KEYWORDS：与 1688 基本一致（同源验证组件），
            淘宝是否有关键词差异（如「亲，验证码」）待真实拦截页校准。
    [CAL-4] EMBEDDED_SLIDER_SELECTORS：nocaptcha/nc_*/baxia 为阿里系
            通用组件，理论上同构，但淘宝搜索页的实际挂载方式
            （模态 vs 内嵌）待验证。
    [CAL-5] SEARCH_HOME 低敏落地页用 s.taobao.com 首页做 mtop 握手，
            与 1688 的 s.1688.com 同机制（h5api.m.taobao.com），
            实测握手目标页是否需要换更低敏页面待确认。
"""

from __future__ import annotations

from fetcher.detect.generic import (
    EmbeddedSliderDetector,
    EmptyPageDetector,
    LoginWallDetector,
    SliderPageDetector,
    make_block_reason,
)
from fetcher.sites import mtop as _mtop

HOMEPAGE = "https://www.taobao.com/"

# 搜索域落地页（低敏）：mtop 握手目标页 [CAL-5]
SEARCH_HOME = "https://s.taobao.com/"

# ---------- 淘宝风控特征表 ----------

# 登录墙 URL 特征 [CAL-1]
LOGIN_URL_PATTERNS = ("login.taobao.com",)

# 整页风控跳转的 URL 特征 [CAL-2]
BLOCK_URL_PATTERNS = (
    "sec.taobao.com",
    "punish",
    "x5sec",
    "captcha",
)

# 风控拦截页的内容关键词 [CAL-3]
BLOCK_TEXT_KEYWORDS = (
    "滑动验证", "安全验证", "拖动下方滑块", "验证中心",
    "访问受限", "访问存在异常", "访问过于频繁",
    "系统检测到您的访问异常", "亲，请完成验证",
)

EMPTY_TEXT_THRESHOLD = 30

# 内嵌滑块 iframe URL 特征 [CAL-2][CAL-4]
EMBEDDED_SLIDER_IFRAME_PATTERNS = (
    "x5sec", "punish", "captcha", "_____tmd_____", "sec.taobao.com",
)
# 内嵌滑块 DOM 容器选择器 [CAL-4]
EMBEDDED_SLIDER_SELECTORS = (
    "#nocaptcha",
    "[id^='nc_']",
    ".nc-container",
    "#baxia-dialog",
    "[class*='baxia']",
)

MTOP_TOKEN_NAME = _mtop.MTOP_TOKEN_NAME
COOKIE_DOMAIN = "taobao.com"


# ---------- 探测器装配（与 1688 同优先级序） ----------

def make_detectors() -> list:
    return [
        LoginWallDetector(LOGIN_URL_PATTERNS, name="taobao_login_wall"),
        SliderPageDetector(BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
                           name="taobao_slider_page"),
        EmbeddedSliderDetector(EMBEDDED_SLIDER_IFRAME_PATTERNS,
                               EMBEDDED_SLIDER_SELECTORS,
                               name="taobao_slider_embed"),
        EmptyPageDetector(EMPTY_TEXT_THRESHOLD, name="taobao_empty_page"),
    ]


page_block_reason = make_block_reason(
    LOGIN_URL_PATTERNS, BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
    EMBEDDED_SLIDER_IFRAME_PATTERNS, EMBEDDED_SLIDER_SELECTORS,
    threshold=EMPTY_TEXT_THRESHOLD)


# ---------- mtop 握手（淘宝搜索域，_m_h5_tk @ taobao.com） ----------

def has_mtop_token(page) -> bool:
    return _mtop.has_mtop_token(page, domain=COOKIE_DOMAIN)


def ensure_mtop_token(page, log=None, attempts: int = 2) -> bool:
    return _mtop.ensure_mtop_token(page, SEARCH_HOME, HOMEPAGE,
                                   domain=COOKIE_DOMAIN, log=log,
                                   attempts=attempts)
