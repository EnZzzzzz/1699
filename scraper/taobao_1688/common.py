# -*- coding: utf-8 -*-
"""
1688 采集共享模块

被 shop_crawler.py（店铺采集）和 contact_fetcher.py（联系方式抓取）共用:
    - Cookie / License 加载
    - CloakBrowser 启动（会话链路一致: Cookie / UA / 出口 IP 不错配）
    - 青果住宅代理接入（可选，util/proxy_qingguo.py）
    - 联系方式页解析（联系人/性别/电话/手机/传真/地址）

代理模式会话链路说明（按 scraper/README.md 经验）:
    - 直连模式: Cookie 是本机浏览器种下的，出口 IP = 本机 IP，链路一致
    - 代理模式: 出口 IP 变成青果住宅 IP，本机种下的 Cookie 与 IP 错配，
      容易触发 x5sec 风控。因此 Cookie 全部存进 SQLite（1688.db 的
      cookies 表），按出口 IP（identity）隔离存取，并记录每个 Cookie
      的过期时间 expires —— 哪个 IP 的 Cookie、什么时候过期一目了然。
    - 首次 --proxy --headed 运行，在代理出口下登录/过滑块，脚本退出时
      自动把浏览器最新 Cookie（含新 x5sec）写回该 IP 名下的记录，
      之后同一出口 IP 都复用它，保持 Cookie / x5sec / UA / 出口 IP 一致。
      .cache/cookies_1688.json 仅作为首次启动的种子导入一次。
      （青果隧道出口 IP 每 30 分钟自动轮换一次，属产品特性；
       换 IP 后库里没有该 IP 的 Cookie，需重新过一次验证。）
"""

from __future__ import annotations  # 兼容 Python < 3.10 的 X | None 注解

import json
import random
import re
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]  # 项目根目录
COOKIE_JSON = ROOT_DIR / ".cache" / "cookies_1688.json"  # 首次启动的种子
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


def wait_for_license_seat(tag: str = "", timeout: float = 600.0,
                          interval: float = 20.0) -> bool:
    """启动浏览器前检查 CloakBrowser 会话席位（free 套餐仅 1 个）。

    背景：会话席位由 Pro 二进制向服务端租约。上次运行异常退出
    （Ctrl+C / 崩溃）时租约不会立即释放，残留期间新启动的二进制
    会在 launch 成功后自行退出，表现为不透明的 TargetClosedError。
    这里启动前主动轮询，等残留租约过期释放后再放行。

    返回 True 表示可以启动；False 表示超时仍被占用。
    查询失败（无 key / 网络问题 / 非 free 套餐上限未知）不阻塞，直接放行。
    """
    key = load_license_key()
    if not key:
        return True
    from cloakbrowser.license import (get_active_session_count,
                                      validate_license)
    try:
        info = validate_license(key)
    except Exception:
        return True
    if not info or info.plan != "free":
        return True  # 仅 free 套餐席位上限已知为 1
    deadline = time.time() + timeout
    while True:
        n = get_active_session_count(key)
        if n is None or n < 1:
            return True
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        wait = min(interval, remaining)
        print(f"{tag}[license] 服务端仍有 {n} 个活跃会话未释放"
              f"（free 套餐仅 1 个席位，多为上次异常退出的残留租约），"
              f"{wait:.0f}s 后重查...")
        time.sleep(wait)


def load_cookies_pw(cookie_path: Path = COOKIE_JSON) -> list[dict]:
    """把 CDP 导出的 Cookie 转成 Playwright 格式（仅 1688 域）。

    仅用于把 .cache/cookies_1688.json 作为种子导入 SQLite；
    日常运行以数据库 cookies 表为准。
    """
    raw = json.loads(cookie_path.read_text(encoding="utf-8"))
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


def seed_cookies_from_json(db, identity: str,
                           cookie_path: Path = COOKIE_JSON) -> int:
    """把 CDP 导出的 JSON Cookie 作为种子导入数据库（保留过期时间）。"""
    raw = json.loads(cookie_path.read_text(encoding="utf-8"))
    seeds = [c for c in raw if "1688.com" in c.get("domain", "")]
    return db.save_cookies(identity, seeds)


# ---------- 浏览器 ----------

def _get_qingguo_proxy(server: str = None, pool_size: int = None) -> dict:
    """从 util/proxy_qingguo.py 取青果隧道代理，拆成 Playwright proxy dict。

    server 为空时从通道池（ChannelPool）轮询取一个通道 —— 多 worker 并发时
    每个浏览器实例各拿一个不同通道，即独占一个出口 IP；
    pool_size 可覆盖 CONFIG["channels"] 的通道数（仅首次建池时生效）。

    make_proxies() 返回的是内嵌账密的 URL（http://user:pwd@host:port/），
    原样传给 Chromium 会报 ERR_NO_SUPPORTED_PROXIES；拆开传 server /
    username / password，由 cloakbrowser 按二进制能力选择内联认证或
    Playwright CDP 认证。
    """
    from urllib.parse import urlparse

    sys.path.insert(0, str(ROOT_DIR / "util"))
    import proxy_qingguo
    pool = proxy_qingguo.get_pool(pool_size)
    url = pool.make_proxies(server)["https"]
    p = urlparse(url)
    return {
        "server": f"{p.scheme}://{p.hostname}:{p.port}",
        "username": p.username,
        "password": p.password,
    }


def get_exit_ip(proxies: dict = None, timeout: int = 10) -> str | None:
    """查询当前出口 IP（代理模式下经代理查询），失败返回 None。"""
    import requests
    try:
        r = requests.get("https://ipinfo.io/json", proxies=proxies,
                         timeout=timeout)
        return r.json().get("ip")
    except Exception:
        return None


def launch_browser(headless: bool = True, use_proxy: bool = False, db=None,
                   proxy_server: str = None, pool_size: int = None):
    """
    启动 CloakBrowser 并注入 1688 Cookie，返回
    (browser, page, identity, req_proxies, proxy_server)。

    Cookie 存取（SQLite，按出口 IP 隔离，保持会话链路一致）：
        - identity: 直连记 'direct'；代理模式记当前出口 IP
        - 先从 1688.db 的 cookies 表取该 identity 下未过期的 Cookie；
          库里没有时用 .cache/cookies_1688.json 作种子导入一次
        - use_proxy=True 时若该出口 IP 的 Cookie 是从本机种子导入的，
          会打印错配警告（建议 --proxy --headed 重新登录/过滑块）

    多通道并发（proxy_server / pool_size）：
        - proxy_server: 指定隧道入口（host:port），None 时从通道池轮询取一个；
          每个 worker 各 acquire 一次即各独占一个通道（独立出口 IP，
          Cookie 按各自出口 IP 隔离，互不串号）
        - pool_size: 覆盖通道池大小（青果 CONFIG["channels"]），仅首次建池生效

    Returns:
        (browser, page, identity, req_proxies, proxy_server)
        req_proxies — 用于 requests 查询出口 IP 的代理字典（代理模式），
                      直连模式为 None；
        proxy_server — 本实例实际使用的隧道入口，直连模式为 None。

    db 为 ShopDB 实例（必传，Cookie 存取都走它）。
    多线程用法：每个线程独立调用本函数（cloakbrowser 每次 launch 都会
    新建自己的 Playwright 实例，线程间互不共享）。
    """
    from cloakbrowser import launch

    proxy_conf = None
    identity = "direct"
    seeded_from_local = False
    req_proxies = None  # 供调用方逐次查询出口 IP 用
    if use_proxy:
        proxy_conf = _get_qingguo_proxy(proxy_server, pool_size)
        host = proxy_conf["server"].split("://")[-1]
        proxy_server = host
        # requests 查询出口 IP 需要内嵌账密的 URL 形式
        req_proxies_url = (f"http://{proxy_conf['username']}"
                           f":{proxy_conf['password']}@{host}")
        req_proxies = {"http": req_proxies_url, "https": req_proxies_url}
        exit_ip = get_exit_ip(req_proxies)
        identity = exit_ip or f"qingguo:{host}"
        print(f"    [proxy] 青果住宅代理: {host}，出口 IP: {exit_ip or '查询失败'}")

    # ---- Cookie：库优先，JSON 种子兜底 ----
    cookies = db.load_cookies(identity) if db else []
    if not cookies:
        if not COOKIE_JSON.exists():
            sys.exit(f"[X] 数据库中没有 identity={identity} 的 Cookie，"
                     f"且找不到种子文件 {COOKIE_JSON}，请先导出 Cookie")
        n = seed_cookies_from_json(db, identity, COOKIE_JSON)
        seeded_from_local = True
        cookies = db.load_cookies(identity)
        print(f"    [cookie] 已从 {COOKIE_JSON.name} 导入 {n} 个 Cookie "
              f"到 identity={identity}")
    info = db.cookie_info(identity)
    print(f"    [cookie] identity={identity}，可用 {len(cookies)} 个"
          f"（库内共 {info['total']}，已过期剔除 {info['expired']}，"
          f"最近过期: {info['earliest_expiry'] or '未知'}）")
    if use_proxy and seeded_from_local:
        print(f"    [!] 该出口 IP 的 Cookie 来自本机种子 —— "
              f"Cookie 与代理出口 IP 错配，可能触发 x5sec 风控；"
              f"建议跑 --proxy --headed 在代理下登录/过滑块，"
              f"退出时会自动把新 Cookie 写回该 IP 名下")
    if not cookies:
        sys.exit(f"[X] identity={identity} 下没有可用 Cookie（可能全部过期）")

    browser = launch(
        headless=headless,
        license_key=load_license_key(),
        humanize=True,
        locale="zh-CN",
        timezone="Asia/Shanghai",
        **({"proxy": proxy_conf, "geoip": True} if proxy_conf else {}),
    )
    ctx = browser.new_context(user_agent=UA, locale="zh-CN")
    ctx.add_cookies(cookies)
    return browser, ctx.new_page(), identity, req_proxies, proxy_server


def save_cookies(db, identity: str, ctx) -> int:
    """把浏览器上下文中的 1688 Cookie 写回数据库（按 identity 隔离）。

    每次运行结束调用：新下发的 x5sec 等字段随之持久化，
    保证下次启动时 Cookie 与同一出口 IP 链路一致。
    """
    cookies = [c for c in ctx.cookies() if "1688.com" in c.get("domain", "")]
    if not cookies:
        return 0
    n = db.save_cookies(identity, cookies)
    print(f"    [cookie] 已把 {n} 个 Cookie 写回数据库 (identity={identity})")
    return n


def human_pause(lo: float = 2.0, hi: float = 5.0):
    t = random.uniform(lo, hi)
    print(f"    ...随机等待 {t:.1f}s")
    time.sleep(t)


# ---------- 风控拦截检测 ----------

# 风控拦截页的 URL 特征（1688 常见拦截跳转）
BLOCK_URL_PATTERNS = (
    "login.1688.com",   # 被强制跳登录
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


def is_risk_blocked(url: str, text: str) -> str | None:
    """判定是否疑似被风控拦截，返回命中原因；未命中返回 None。

    1688 被风控时的典型表现：跳转登录/安全中心/x5sec 滑块页，
    或页面出现验证类关键词，或 body 异常空白。
    """
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
        # 风控拦截检测：命中时返回原因字符串，调用方据此换 IP 重试
        info["_blocked"] = is_risk_blocked(page.url, text)
        return info
    except Exception as e:
        print(f"    [X] {shop_domain} 联系方式抓取失败: {e}")
        return None
