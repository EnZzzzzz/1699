# -*- coding: utf-8 -*-
"""
1688 采集共享模块

被 shop_crawler.py（店铺采集）和 contact_fetcher.py（联系方式抓取）共用:
    - Cookie / License 加载
    - CloakBrowser 启动（会话链路一致: 直连本机 IP + 原 UA）
    - 联系方式页解析（联系人/性别/电话/手机/传真/地址）
"""

import json
import random
import re
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]  # 项目根目录
COOKIE_JSON = ROOT_DIR / ".cache" / "cookies_1688.json"
CONFIG_JSON = ROOT_DIR / ".cache" / "config.json"

HOMEPAGE = "https://www.1688.com/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/150.0.0.0 Safari/537.36")


# ---------- 配置加载 ----------

def load_license_key() -> str | None:
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text())["CLOAKBROWSER_LICENSE_KEY"]
        except Exception:
            return None
    return None


def load_cookies_pw() -> list[dict]:
    """把 CDP 导出的 Cookie 转成 Playwright 格式（仅 1688 域）。"""
    raw = json.loads(COOKIE_JSON.read_text(encoding="utf-8"))
    cookies = []
    for c in raw:
        domain = c.get("domain", "")
        if "1688.com" not in domain:
            continue
        cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path", "/") if not c.get("path", "").startswith("//") else "/",
            "secure": bool(c.get("secure", False)),
            "httpOnly": bool(c.get("httpOnly", False)),
        })
    return cookies


# ---------- 浏览器 ----------

def launch_browser(headless: bool = True):
    """启动 CloakBrowser 并注入 1688 Cookie，返回 (browser, page)。"""
    from cloakbrowser import launch

    browser = launch(
        headless=headless,
        license_key=load_license_key(),
        humanize=True,
        locale="zh-CN",
        timezone="Asia/Shanghai",
    )
    ctx = browser.new_context(user_agent=UA, locale="zh-CN")
    ctx.add_cookies(load_cookies_pw())
    return browser, ctx.new_page()


def human_pause(lo: float = 2.0, hi: float = 5.0):
    t = random.uniform(lo, hi)
    print(f"    ...随机等待 {t:.1f}s")
    time.sleep(t)


# ---------- 联系方式解析 ----------

def parse_contact_text(text: str) -> dict:
    """
    从联系方式页 innerText 解析字段。页面格式稳定:

        电话：86-757-xxxx   （可能只有区号/暂无）
        手机：138xxxxxxxx  （或 暂无）
        传真：暂无
        地址：广东xxx
        张三女士/先生        （联系人，性别由后缀推断）
    """

    def grab(label: str) -> str | None:
        m = re.search(rf"{label}[：:]\s*([^\n]*)", text)
        if not m:
            return None
        v = m.group(1).strip()
        if not v or v == "暂无" or v == "86":
            return None
        return v

    # 联系人：地址行之后、以 先生/女士 结尾的独立行
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
    """进入店铺「联系方式」页并解析字段，失败返回 None。"""
    url = f"https://{shop_domain}/page/contactinfo.htm"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000,
                  referer=referer or f"https://{shop_domain}/")
        time.sleep(random.uniform(2.0, 4.0))
        text = page.evaluate("() => document.body.innerText")
        info = parse_contact_text(text)
        info["_raw"] = text[:500]
        info["_source_url"] = page.url
        return info
    except Exception as e:
        print(f"    [X] {shop_domain} 联系方式抓取失败: {e}")
        return None
