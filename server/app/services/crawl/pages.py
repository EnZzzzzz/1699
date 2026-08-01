# -*- coding: utf-8 -*-
"""
1688 页面逻辑（纯函数，无浏览器/DB 依赖）。

重写自 scraper/taobao_1688/common.py 与 shop_crawler.py 的页面解析部分
（蓝本只读，未被 import）：类目/店铺提取 JS、分页 URL、风控检测、
联系方式页解析。
"""
from __future__ import annotations

import random
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

HOMEPAGE = "https://www.1688.com/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/150.0.0.0 Safari/537.36")


# ---------- 节奏 ----------

def human_pause(lo: float = 2.0, hi: float = 5.0):
    time.sleep(random.uniform(lo, hi))


# ---------- 网络/风控检测 ----------

NETWORK_ERR_MARKERS = (
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_TIMED_OUT",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_SOCKET_NOT_CONNECTED",
    "ERR_ADDRESS_UNREACHABLE",
    "ERR_NETWORK_CHANGED",
    "ERR_HTTP2_PROTOCOL_ERROR",
    "net::ERR",
)

BLOCK_URL_PATTERNS = (
    "login.1688.com", "sec.1688.com", "punish", "x5sec", "captcha",
)

BLOCK_TEXT_KEYWORDS = (
    "滑动验证", "安全验证", "拖动下方滑块", "验证中心",
    "访问受限", "访问存在异常", "访问过于频繁",
    "系统检测到您的访问异常", "亲，请完成验证",
)


def is_network_error(err) -> bool:
    """异常是否属于网络/代理层错误（与目标站风控无关）。"""
    s = str(err or "")
    return any(m in s for m in NETWORK_ERR_MARKERS)


def is_risk_blocked(url: str, text: str) -> str | None:
    """判定是否疑似被风控拦截，返回命中原因；未命中返回 None。"""
    u = (url or "").lower()
    for p in BLOCK_URL_PATTERNS:
        if p in u:
            return f"URL 命中风控特征 '{p}'（{url}）"
    t = (text or "").strip()
    for kw in BLOCK_TEXT_KEYWORDS:
        if kw in t:
            return f"页面内容命中风控关键词 '{kw}'"
    if len(t) < 30:
        return f"页面内容异常空白（仅 {len(t)} 字符，疑似拦截页）"
    return None


# ---------- 页面提取 ----------

def extract_categories(page) -> list[dict]:
    """从首页提取类目链接（全部类目侧边栏）。"""
    return page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('a[href*="offer_search.htm"]').forEach(a => {
                const m = a.href.match(/keywords=([^&]+)/);
                if (m && a.textContent.trim()) {
                    out.push({name: a.textContent.trim(),
                              keyword: decodeURIComponent(m[1]),
                              url: a.href});
                }
            });
            const seen = new Set();
            return out.filter(c => !seen.has(c.url) && seen.add(c.url));
        }"""
    )


def extract_shops(page) -> list[dict]:
    """从类目搜索结果页提取店铺（shop 域名 + 公司名）。"""
    return page.evaluate(
        """() => {
            const shops = new Map();
            document.querySelectorAll('a[href*="//shop"]').forEach(a => {
                const m = a.href.match(/\\/\\/(shop[0-9a-z]+\\.1688\\.com)/);
                if (m) {
                    const name = a.textContent.trim();
                    const prev = shops.get(m[1]);
                    if (!prev || (name && name.length > prev.length)) {
                        if (name) shops.set(m[1], name);
                    }
                }
            });
            return [...shops.entries()].map(([domain, name]) => ({
                domain, name, url: 'https://' + domain
            }));
        }"""
    )


def category_page_url(url: str, page_no: int) -> str:
    """给类目搜索 URL 设置分页参数（1688 搜索分页参数为 page）。"""
    if page_no <= 1:
        return url
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query))
    q["page"] = str(page_no)
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(q), parts.fragment))


def page_blocked(page) -> bool:
    """粗判当前页是否为风控/验证页（区分末页空结果与被风控）。"""
    try:
        return bool(page.evaluate(
            """() => {
                if (/punish|x5sec|captcha|verify/i.test(location.href)) return true;
                const t = document.body ? document.body.innerText.slice(0, 2000) : '';
                return /滑动验证|安全验证|访问受限|异常流量/.test(t);
            }"""))
    except Exception:
        return False


# ---------- 联系方式解析 ----------

def parse_contact_text(text: str) -> dict:
    """从联系方式页 innerText 解析字段（电话/手机/传真/地址/联系人/性别）。"""

    def grab(label: str) -> str | None:
        m = re.search(rf"{label}[：:]\s*([^\n]*)", text)
        if not m:
            return None
        v = m.group(1).strip()
        if not v or v == "暂无" or v == "86":
            return None
        return v

    contact_person, gender = None, None
    m = re.search(r"地址[：:][^\n]*\n\s*([^\n]{1,20}?)(先生|女士)\s*\n", text)
    if m:
        contact_person = m.group(1).strip() or None
        gender = {"先生": "男", "女士": "女"}.get(m.group(2))

    return {
        "phone": grab("电话"),
        "mobile": grab("手机"),
        "fax": grab("传真"),
        "address": grab("地址"),
        "contact_person": contact_person,
        "gender": gender,
    }


def scrape_contact(page, shop_domain: str, referer: str = None) -> dict | None:
    """进入店铺「联系方式」页并解析字段。

    返回约定（与蓝本一致）：
        - 正常：dict（字段 + _raw/_source_url/_blocked）
        - 网络/代理层错误：{"_net_error": 原因}
        - 其他异常：None
    """
    url = f"https://{shop_domain}/page/contactinfo.htm"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000,
                  referer=referer or f"https://{shop_domain}/")
        time.sleep(random.uniform(2.0, 4.0))
        text = page.evaluate("() => document.body.innerText")
        info = parse_contact_text(text)
        info["_raw"] = text[:500]
        info["_source_url"] = page.url
        info["_blocked"] = is_risk_blocked(page.url, text)
        return info
    except Exception as e:
        if is_network_error(e):
            return {"_net_error": str(e).splitlines()[0][:200]}
        return None
