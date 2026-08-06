# -*- coding: utf-8 -*-
"""Facebook 风控特征表 + 站点探测器装配。

实测（2026-08，见 docs/channel-research/facebook-groups.md §9 PoC）：
- 群帖 permalink（/groups/{gid}/posts/{pid}/）**匿名可读**：登录墙只是
  遮罩弹窗，og:description 与 DOM 正文完整可提取；首屏评论部分可见。
- 纯 HTTP GET（urllib/curl 带浏览器 UA）被 TLS/HTTP 指纹识别一律 400，
  抓取必须走真实浏览器（Playwright/CloakBrowser/WebBridge）。
- 匿名硬拦截的表现是 **302 跳登录页**（login.php / /checkpoint），
  不是滑块；频率限制是整页文案（"You're Temporarily Blocked"）。
- 成功页正文也含「登录/忘记账户了」遮罩文案，故 BLOCK_TEXT_KEYWORDS
  绝不能含「登录」类词，只能放频率限制专属文案。
"""

from __future__ import annotations

from fetcher.detect.generic import (
    EmbeddedSliderDetector,
    EmptyPageDetector,
    LoginWallDetector,
    SliderPageDetector,
    make_block_reason,
)

HOMEPAGE = "https://www.facebook.com/"

# ---------- facebook 风控特征表 ----------

# 匿名抓 permalink 的硬拦截 = 强制跳登录（遮罩不算，URL 跳转才算）
LOGIN_URL_PATTERNS = (
    "facebook.com/login",
    "/login.php",
    "facebook.com/checkpoint",
)

# FB 无阿里式滑块页；拦截以 URL 跳转为主，整页 URL 特征留空
BLOCK_URL_PATTERNS = ()

# 频率限制整页文案（成功页不会出现；中英两版都备上）
BLOCK_TEXT_KEYWORDS = (
    "You're Temporarily Blocked",
    "You’re Temporarily Blocked",
    "misusing this feature",
    "You can't use this feature",
    "你暂时无法使用",
    "操作过于频繁",
)

# 空白页阈值：成功帖页（含遮罩文案）innerText ≥ 200 字符，阈值沿用通用值
EMPTY_TEXT_THRESHOLD = 30

# 帖子删除/无权限的内容缺失文案（业务态 EMPTY，不是风控）
CONTENT_UNAVAILABLE_KEYWORDS = (
    "This content isn't available",
    "content isn't available right now",
    "此内容当前不可用",
    "内容不可用",
    "The link you followed may be broken",
)

# FB 匿名抓取无内嵌验证组件先例，特征留空（保持四探测器装配统一）
EMBEDDED_SLIDER_IFRAME_PATTERNS = ()
EMBEDDED_SLIDER_SELECTORS = ()


# ---------- 探测器装配（优先级序：登录墙 > 整页拦截 > 内嵌 > 空页） ----------

def make_detectors() -> list:
    """facebook 站点探测器（SceneInspector 拼在通用探测器之后）。"""
    return [
        LoginWallDetector(LOGIN_URL_PATTERNS, name="facebook_login_wall"),
        SliderPageDetector(BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
                           name="facebook_rate_limit_page"),
        EmbeddedSliderDetector(EMBEDDED_SLIDER_IFRAME_PATTERNS,
                               EMBEDDED_SLIDER_SELECTORS,
                               name="facebook_captcha_embed"),
        EmptyPageDetector(EMPTY_TEXT_THRESHOLD, name="facebook_empty_page"),
    ]


# 「是否被拦」的统一口径（含登录墙与空白页）
page_block_reason = make_block_reason(
    LOGIN_URL_PATTERNS, BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
    EMBEDDED_SLIDER_IFRAME_PATTERNS, EMBEDDED_SLIDER_SELECTORS,
    threshold=EMPTY_TEXT_THRESHOLD)
