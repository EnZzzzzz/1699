# -*- coding: utf-8 -*-
"""中国制造网(cn.made-in-china.com) 风控特征表 + 站点探测器装配。

实测（2026-08-05，见 docs/made-in-china-scraping.md）：
- 联系方式页免登录：手机号完整写死在 <meta name="Description"> 里
  （`中国制造网，{公司}，联系人：{姓}，联系电话：{手机号}`），无登录墙。
- 反爬是 vemic FCaptcha（captcha.vemic.com，「请验证」页）：拦截页 **URL 不变**
  （仍是 showroom/xxx-contact.html），因此只能靠正文关键词 + 内嵌 iframe 判定，
  不能靠 URL。快速连刷触发；慢速 + 带验证 cookie 的浏览器会话可批量拉。
- 页面 GBK 编码：由 Playwright 渲染自动解码，提取侧无需手动解码。

判定结构（登录墙/整页滑块/内嵌滑块/空页探测器、page_block_reason）全部复用
通用件（detect/generic.py 参数化探测器），本文件只提供 madeinchina 的特征表
数据与域参数 —— 与 1688/义乌购插件的差异即特征表内容，结构零重复。
"""

from __future__ import annotations

from fetcher.detect.generic import (
    EmbeddedSliderDetector,
    EmptyPageDetector,
    LoginWallDetector,
    SliderPageDetector,
    make_block_reason,
)

HOMEPAGE = "https://cn.made-in-china.com/"

# 市场导航页：全站 market 类目目录（~947 个类目；首页只暴露 ~129 个，
# 2026-08-06 首页类目已全部采干，类目主力入口改为本页，见 shop.py cold_start）
MARKET_DIR = "https://cn.made-in-china.com/shichang/"

# 展厅子域名后缀（{sub}.cn.made-in-china.com，shop 任务提取、contact 任务构造 URL）
SHOWROOM_DOMAIN_SUFFIX = ".cn.made-in-china.com"

# ---------- madeinchina 风控特征表 ----------

# 免登录：无登录墙，login 特征留空（保持四探测器装配统一）
LOGIN_URL_PATTERNS = ()

# vemic FCaptcha：拦截页 URL 不变，BLOCK_URL_PATTERNS 只在整页确实跳到该域时命中
BLOCK_URL_PATTERNS = ("captcha.vemic.com",)

# 风控拦截页的内容关键词（实测「请验证」页标题/正文 + 通用安全验证文案）
BLOCK_TEXT_KEYWORDS = (
    "请验证", "vemic", "请完成安全验证", "安全验证",
    "访问过于频繁", "访问异常", "系统检测到您的访问异常",
)

# 空白页阈值：innerText 少于此字符数视为异常空白（与 1688/义乌购一致）
EMPTY_TEXT_THRESHOLD = 30

# 内嵌验证 iframe 特征：vemic 验证组件可能以 iframe 注入业务页
EMBEDDED_SLIDER_IFRAME_PATTERNS = ("captcha.vemic.com",)
# vemic DOM 容器未知，先靠 iframe 判定 [CAL]：真实代理运行后按需补选择器
EMBEDDED_SLIDER_SELECTORS = ()


# ---------- 探测器装配（优先级序：登录墙 > 整页滑块 > 内嵌滑块 > 空页） ----------

def make_detectors() -> list:
    """madeinchina 站点探测器（SceneInspector 拼在通用探测器之后）。"""
    return [
        LoginWallDetector(LOGIN_URL_PATTERNS, name="madeinchina_login_wall"),
        SliderPageDetector(BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
                           name="madeinchina_captcha_page"),
        EmbeddedSliderDetector(EMBEDDED_SLIDER_IFRAME_PATTERNS,
                               EMBEDDED_SLIDER_SELECTORS,
                               name="madeinchina_captcha_embed"),
        EmptyPageDetector(EMPTY_TEXT_THRESHOLD, name="madeinchina_empty_page"),
    ]


# 「是否被拦/已过证」的统一口径（含登录墙与空白页）
page_block_reason = make_block_reason(
    LOGIN_URL_PATTERNS, BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
    EMBEDDED_SLIDER_IFRAME_PATTERNS, EMBEDDED_SLIDER_SELECTORS,
    threshold=EMPTY_TEXT_THRESHOLD)
