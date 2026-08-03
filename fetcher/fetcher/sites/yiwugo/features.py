# -*- coding: utf-8 -*-
"""义乌购风控特征表 + csrf 握手 + API 客户端（yiwugo.com 域）。

实测（2026-08-03，裸 curl + 前端 JS 逆向）——义乌购的防护体系与
阿里系完全不同（全新的一套）：

    1. 无 WAF / 无 JS challenge：裸 curl 直接 200，没有 x5sec/滑块
       跳转那套阿里族机制；
    2. Cookie 体系：服务端只下发一个 session 级 `csrfToken`
       （path=/，实测同一会话复用 30+ 次不轮换）。所有 /api/* 接口
       必须带 `x-csrf-token` 请求头 = csrfToken 值（前端 axios 的
       xsrfCookieName/xsrfHeaderName 标准配置），否则返回
       {"code":-1,"msg":"非法请求"}。客户端自生成的 imei/imei2
       （UUID）、登录态 yiwugouid 等匿名采集都不需要；
    3. 数据接口全部是 GET + JSON（www.yiwugo.com/api/ 下）：
       搜索   /api/search/s.htm?q=&cpage=&pageSize=&appid=6&source=pc
       详情   /api/product/detail.htm?productId=（含 contacter /
              telephone / mobile / email / qq / weixin —— 联系方式
              匿名可见，无需登录）；
    4. 错误码（requestErrorCodes.js）："1" 成功 / "-1" 非法请求 /
       "-2" 未授权 / "-5" 验证码错误；
    5. 风控验证码：自研滑块 captcha.yiwugo.com（/gen 下发 SLIDER 型
       base64 底图 + id，/secondcheck?id=&data= 校验）——与阿里滑块
       不同构，轨迹回放不适用，过证策略走休息/换 IP；
    6. 频率实测：搜索 30 连发、详情 50 连发均未触发拦截，防护强度
       远低于阿里系；失效商品返回 code="1" 但 content.errorInfo
       ="商品不存在，已被..."（结构化校验识别，不算拦截）。

⚠️ 待真实环境校准的条目（标注 [CAL]）：
    [CAL-1] 登录墙/验证码整页跳转的 URL 与文本特征：匿名采集链路
            （搜索/详情 API）不经过登录页与整页风控页，以下特征按
            前端 JS 中的域名与通用文案合理推断，未在真实拦截页验证；
    [CAL-2] 自研滑块在页面内的挂载方式（模态容器选择器）未知，
            EMBEDDED_SLIDER 目前只靠 captcha.yiwugo.com iframe 特征；
    [CAL-3] 高频/长时间采集下 -5 验证码与 IP 级封禁的实际触发阈值
            未知（实测 50 连发未触发），策略按「休息 + 换 IP」编排，
            阈值出现后回调 ip_request_budget。
"""

from __future__ import annotations

import random
import time

from fetcher.detect.generic import (
    EmbeddedSliderDetector,
    EmptyPageDetector,
    LoginWallDetector,
    SliderPageDetector,
    make_block_reason,
)

HOMEPAGE = "https://www.yiwugo.com/"
API_BASE = "https://www.yiwugo.com"

# ---------- 义乌购风控特征表 ----------

# 登录墙 URL 特征 [CAL-1]（前端登录组件指向 passport 域）
LOGIN_URL_PATTERNS = ("passport.yiwugo.com",)

# 整页风控跳转的 URL 特征 [CAL-1]
BLOCK_URL_PATTERNS = ("captcha.yiwugo.com", "/captcha/")

# 风控拦截页的内容关键词 [CAL-1]
BLOCK_TEXT_KEYWORDS = (
    "请完成安全验证", "拖动滑块完成验证", "滑动验证",
    "访问过于频繁", "操作过于频繁", "系统检测到您的访问异常",
)

EMPTY_TEXT_THRESHOLD = 30

# 内嵌验证码 iframe URL 特征 [CAL-2]
EMBEDDED_SLIDER_IFRAME_PATTERNS = ("captcha.yiwugo.com",)
# 内嵌验证码 DOM 容器选择器 [CAL-2]（真实挂载方式待验证，保守留空
# 之外的通用猜测项，误报风险低）
EMBEDDED_SLIDER_SELECTORS = ()

CSRF_COOKIE_NAME = "csrfToken"
CSRF_HEADER_NAME = "x-csrf-token"
COOKIE_DOMAIN = "yiwugo.com"

# API 错误码（app/web/pageConfig/requestErrorCodes.js）
CODE_SUCCESS = "1"
CODE_ILLEGAL = "-1"        # 非法请求（缺/错 x-csrf-token）
CODE_UNAUTHORIZED = "-2"   # 未授权（需登录）
CODE_CAPTCHA = "-5"        # 验证码错误（触发自研滑块）

# 失效商品的内容标记（code 仍是 "1"，不算拦截）
DEAD_PRODUCT_MARKERS = ("商品不存在", "已被删除", "已下架")


# ---------- 探测器装配（与 1688/淘宝同优先级序） ----------

def make_detectors() -> list:
    return [
        LoginWallDetector(LOGIN_URL_PATTERNS, name="yiwugo_login_wall"),
        SliderPageDetector(BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
                           name="yiwugo_captcha_page"),
        EmbeddedSliderDetector(EMBEDDED_SLIDER_IFRAME_PATTERNS,
                               EMBEDDED_SLIDER_SELECTORS,
                               name="yiwugo_captcha_embed"),
        EmptyPageDetector(EMPTY_TEXT_THRESHOLD, name="yiwugo_empty_page"),
    ]


page_block_reason = make_block_reason(
    LOGIN_URL_PATTERNS, BLOCK_URL_PATTERNS, BLOCK_TEXT_KEYWORDS,
    EMBEDDED_SLIDER_IFRAME_PATTERNS, EMBEDDED_SLIDER_SELECTORS,
    threshold=EMPTY_TEXT_THRESHOLD)


# ---------- csrf 握手（csrfToken @ yiwugo.com，替代 mtop 握手） ----------

def get_csrf_token(page, domain: str = COOKIE_DOMAIN) -> str | None:
    """从会话 Cookie 中读 csrfToken 值；没有返回 None。"""
    try:
        for c in page.context.cookies():
            if c.get("name") == CSRF_COOKIE_NAME \
                    and domain in c.get("domain", ""):
                return c.get("value") or None
    except Exception:  # noqa: BLE001
        pass
    return None


def has_csrf_token(page, domain: str = COOKIE_DOMAIN) -> bool:
    return get_csrf_token(page, domain) is not None


def ensure_csrf_token(page, log=None, attempts: int = 2) -> bool:
    """确保会话持有 csrfToken：没有就访问站点首页触发服务端签发
    （任意页面响应都会 set-cookie，首页最低敏）。拿到返回 True。"""
    if has_csrf_token(page):
        return True
    for i in range(attempts):
        try:
            page.goto(HOMEPAGE, wait_until="domcontentloaded",
                      timeout=45000)
            time.sleep(random.uniform(2.0, 4.0))
        except Exception:  # noqa: BLE001
            pass
        if has_csrf_token(page):
            if log:
                log(f"csrf 握手完成（第 {i + 1} 次尝试），"
                    f"会话已持有 csrfToken（{COOKIE_DOMAIN}）")
            return True
    return False


# ---------- API 客户端（经 page.request 与浏览器共享 Cookie jar） ----------

def api_get(page, path: str, params: dict | None = None,
            referer: str = HOMEPAGE, timeout: float = 30000) -> dict:
    """调义乌购 JSON API：自动带 x-csrf-token 头与 Referer。

    走 page.request（Playwright APIRequestContext），与浏览器 context
    共享 Cookie jar —— csrfToken 的签发（页面导航）与消费（API 请求）
    在同一个身份里，IdentityStore 按出口 IP 隔离的语义完整保留。

    返回解析后的 JSON dict；HTTP 层失败/非 JSON 返回 {}（调用方按
    EMPTY 处理）。csrfToken 缺失时抛 RuntimeError（调用方应先用
    ensure_csrf_token 握手）。
    """
    token = get_csrf_token(page)
    if not token:
        raise RuntimeError(f"会话缺少 {CSRF_COOKIE_NAME}，"
                           "API 请求会被判非法请求（-1）")
    resp = page.request.get(
        API_BASE + path,
        params={k: v for k, v in (params or {}).items() if v is not None},
        headers={
            CSRF_HEADER_NAME: token,
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=timeout,
    )
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def api_code(data: dict) -> str:
    """API 响应错误码归一化（实测成功响应 code 是字符串 "1"）。"""
    return str((data or {}).get("code", ""))
