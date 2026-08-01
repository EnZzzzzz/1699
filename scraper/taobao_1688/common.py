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
import os
import random
import re
import sys
import threading
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


# ---------- 日志出口（多 worker 时可把内部消息路由到状态板，避免刷屏） ----------

_LOG_SINK = None          # callable(tag, msg)；None 时退回普通 print
_tls = threading.local()  # 每线程的 worker 标签（contact_fetcher 用 set_tag 设置）


def set_log_sink(fn):
    """设置内部日志出口 fn(tag, msg)；传 None 恢复直接 print。"""
    global _LOG_SINK
    _LOG_SINK = fn


def set_tag(tag: str):
    """给当前线程打标（如 '[w0]'），内部日志按 worker 归属路由。"""
    _tls.tag = tag


def _log(msg: str):
    tag = getattr(_tls, "tag", "")
    if _LOG_SINK is not None:
        _LOG_SINK(tag, msg)
    elif tag:
        print(f"{tag} {msg}")
    else:
        print(msg)


# ---------- 配置加载 ----------

def load_license_key() -> str | None:
    # 环境变量优先（export CLOAKBROWSER_LICENSE_KEY=...），config.json 兜底
    key = os.environ.get("CLOAKBROWSER_LICENSE_KEY")
    if key:
        return key
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text())["CLOAKBROWSER_LICENSE_KEY"]
        except Exception:
            return None
    return None


# 各套餐的并发会话席位上限（服务端强制，超限的 launch 会以退出码 76
# 拒绝；此处仅用于启动前主动等待，上限未知的套餐不阻塞直接放行）
PLAN_SEATS = {"free": 1, "solo": 5}


def wait_for_license_seat(tag: str = "", timeout: float = 600.0,
                          interval: float = 20.0,
                          max_seats: int | None = None) -> bool:
    """启动浏览器前检查 CloakBrowser 会话席位是否还有空余。

    背景：会话席位由 Pro 二进制向服务端租约。上次运行异常退出
    （Ctrl+C / 崩溃 / 进程被杀）时租约不会立即释放，残留期间新启动
    的二进制会被服务端拒绝（退出码 76）或 launch 后自行退出，表现为
    不透明的 TargetClosedError。这里启动前主动轮询，等残留租约过期
    释放后再放行。

    席位上限取 PLAN_SEATS（free=1 / solo=5），可用 max_seats 覆盖；
    上限未知的套餐不阻塞。返回 True 表示可以启动；False 表示超时仍满员。
    查询失败（无 key / 网络问题）不阻塞，直接放行。
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
    seats = max_seats or (PLAN_SEATS.get(info.plan) if info else None)
    if not seats:
        return True  # 套餐席位上限未知，不阻塞
    deadline = time.time() + timeout
    while True:
        n = get_active_session_count(key)
        if n is None or n < seats:
            return True
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        wait = min(interval, remaining)
        _log(f"{tag}[license] 服务端 {n}/{seats} 个会话席位被占用"
              f"（多为上次异常退出的残留租约，等其过期释放），"
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


# 阿里系风控安全 Cookie：由站点按「IP + 设备 + 会话」现场签发，
# 不能跨 IP 复制 —— 把 A 地签发的 x5sec/sgcookie/isg 带到 B 地出口，
# 等于主动告诉风控系统「同一客户端在 IP 池里跳」，是账号被标记的
# 最强信号。新 identity 播种时必须剔除，让站点为当前出口重新签发。
SECURITY_COOKIE_NAMES = frozenset({
    "x5sec", "x5secdata", "x5sectag", "sgcookie", "sg", "isg",
})


def seed_cookies_from_json(db, identity: str,
                           cookie_path: Path = COOKIE_JSON) -> int:
    """把 CDP 导出的 JSON Cookie 作为种子导入数据库（保留过期时间）。

    代理模式（identity 为出口 IP）播种时剔除风控安全 Cookie
    （x5sec/sgcookie/isg 等）：它们由站点按 IP+会话签发，跨 IP 复制
    会触发风控；剔除后首次访问由站点为当前出口重新签发，之后
    save_cookies 写回的才是与该 IP 配套的安全 Cookie。
    直连模式（identity='direct'）Cookie 本来就是本机 IP 下签发的，全量保留。
    """
    raw = json.loads(cookie_path.read_text(encoding="utf-8"))
    seeds = [c for c in raw if "1688.com" in c.get("domain", "")]
    if identity != "direct":
        stripped = [c for c in seeds
                    if c.get("name") in SECURITY_COOKIE_NAMES]
        if stripped:
            seeds = [c for c in seeds
                     if c.get("name") not in SECURITY_COOKIE_NAMES]
            _log(f"    [cookie] 播种 identity={identity} 时已剔除 "
                 f"{len(stripped)} 个跨 IP 风控 Cookie"
                 f"（{', '.join(sorted(c['name'] for c in stripped))}），"
                 f"将由站点为当前出口重新签发")
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
        # 出口 IP 是 Cookie 隔离的 identity 基准，查不到就不能继续 ——
        # 用 qingguo:host 之类的伪 identity 会让 Cookie 绑错对象，
        # 且该 IP 的真实 Cookie 永远无法沉淀。短重试后仍失败直接抛错，
        # 交给调用方（relaunch_browser）退避重试。
        exit_ip = get_exit_ip(req_proxies)
        if exit_ip is None:
            for _ in range(3):
                time.sleep(5)
                exit_ip = get_exit_ip(req_proxies)
                if exit_ip:
                    break
        if exit_ip is None:
            raise RuntimeError(f"经通道 {host} 查询出口 IP 失败，"
                               f"隧道疑似不可用，无法绑定 Cookie identity")
        identity = exit_ip
        _log(f"    [proxy] 青果住宅代理: {host}，出口 IP: {exit_ip}")

    # ---- Cookie：库优先，JSON 种子兜底 ----
    cookies = db.load_cookies(identity) if db else []
    if not cookies:
        if not COOKIE_JSON.exists():
            sys.exit(f"[X] 数据库中没有 identity={identity} 的 Cookie，"
                     f"且找不到种子文件 {COOKIE_JSON}，请先导出 Cookie")
        n = seed_cookies_from_json(db, identity, COOKIE_JSON)
        seeded_from_local = True
        cookies = db.load_cookies(identity)
        _log(f"    [cookie] 已从 {COOKIE_JSON.name} 导入 {n} 个 Cookie "
             f"到 identity={identity}")
    info = db.cookie_info(identity)
    _log(f"    [cookie] identity={identity}，可用 {len(cookies)} 个"
         f"（库内共 {info['total']}，已过期剔除 {info['expired']}，"
         f"最近过期: {info['earliest_expiry'] or '未知'}）")
    if use_proxy and seeded_from_local:
        _log(f"    [cookie] 该出口 IP 的 Cookie 来自本机种子（已剔除跨 IP"
             f" 风控 Cookie），预热时将由站点为当前出口重新签发")
    if not cookies:
        sys.exit(f"[X] identity={identity} 下没有可用 Cookie（可能全部过期）")

    # 启动前等服务端有空余会话席位（上次异常退出的残留租约未释放时，
    # 直接 launch 会被服务端拒绝/启动后被关闭，表现为 TargetClosedError）
    tag = getattr(_tls, "tag", "")
    if not wait_for_license_seat(tag=f"{tag} " if tag else "",
                                 timeout=600.0):
        raise RuntimeError("等待 600s 后 CloakBrowser 会话席位仍满员，"
                           "请检查是否有残留会话未释放")

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
    page = ctx.new_page()
    if use_proxy:
        # 新 IP / 新会话预热：访问首页让站点为当前出口现场签发独立
        # Cookie（sgcookie/isg/cna 等），立即回写该 IP 名下 ——
        # 每个 IP 的 Cookie 从此在值层面也是独立的，不再跨 IP 复制
        warmup_cookies(db, identity, page, ctx)
    return browser, page, identity, req_proxies, proxy_server


def warmup_cookies(db, identity: str, page, ctx) -> bool:
    """新 IP 的 Cookie 自动更新：访问 1688 首页触发站点现场签发。

    播种只能提供登录态（cookie2/_tb_token_），风控与会话 Cookie 必须由
    站点按「当前出口 IP + 当前会话」签发才算配套。首页是低风险页面，
    预热一次即完成绑定，顺带让首个店铺请求带上真实的站内浏览轨迹
    （直接深链 contactinfo.htm 而无首页访问记录本身也是爬虫特征）。

    返回 True 表示预热顺利；首页即命中风控或预热失败返回 False
    （不阻断启动，后续抓取重试/手动过证流程会处理）。
    """
    try:
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
        text = ""
        try:
            text = page.evaluate("() => document.body.innerText") or ""
        except Exception:
            pass
        blocked = is_risk_blocked(page.url, text)
        n = save_cookies(db, identity, ctx)
        if blocked:
            _log(f"    [warmup] 首页即命中风控（{blocked}），已回写 {n} 个"
                 f" Cookie；headed 模式可在窗口手动过证后自动继续")
            return False
        _log(f"    [warmup] 首页预热完成，{n} 个 Cookie 已与出口 "
             f"{identity} 绑定（站点现场签发）")
        return True
    except Exception as e:
        _log(f"    [!] 首页预热失败（不阻断启动，后续抓取重试处理）: "
             f"{str(e).splitlines()[0][:150]}")
        return False


def save_cookies(db, identity: str, ctx) -> int:
    """把浏览器上下文中的 1688 Cookie 写回数据库（按 identity 隔离）。

    每次运行结束调用：新下发的 x5sec 等字段随之持久化，
    保证下次启动时 Cookie 与同一出口 IP 链路一致。
    """
    cookies = [c for c in ctx.cookies() if "1688.com" in c.get("domain", "")]
    if not cookies:
        return 0
    n = db.save_cookies(identity, cookies)
    _log(f"    [cookie] 已把 {n} 个 Cookie 写回数据库 (identity={identity})")
    return n


def human_pause(lo: float = 2.0, hi: float = 5.0):
    t = random.uniform(lo, hi)
    _log(f"    ...随机等待 {t:.1f}s")
    time.sleep(t)


# ---------- 风控拦截检测 ----------

# 网络/代理层错误特征（Chromium net 错误码）。
# 这类错误说明请求根本没到目标站（隧道断、连接重置、DNS 失败等），
# 与风控无关，调用方不应计入风控连续失败计数，应换通道/退避后重试。
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
    "net::ERR",  # 兜底：所有 Chromium 网络层错误都先按网络故障处理
)


def is_network_error(err) -> bool:
    """判断异常是否属于网络/代理层错误（与目标站风控无关）。"""
    s = str(err or "")
    return any(m in s for m in NETWORK_ERR_MARKERS)


# 浏览器进程级致命错误特征（与目标站风控完全无关）。
# 典型场景：CloakBrowser 会话被服务端关闭（席位超限/租约被顶掉）、
# 浏览器进程崩溃、上下文被销毁。表现为 Playwright 的 TargetClosedError，
# 若误当风控处理会在一台死浏览器上空等/重试，必须识别出来让调用方
# 直接重启浏览器。
FATAL_ERR_MARKERS = (
    "Target closed",
    "TargetClosedError",
    "has been closed",   # "Target page, context or browser has been closed"
    "Target crashed",
    "Browser closed",
    "Connection closed",
)


def is_fatal_browser_error(err) -> bool:
    """判断异常是否属于浏览器进程死亡/被关闭（应重启浏览器，非风控）。"""
    s = str(err or "")
    return any(m in s for m in FATAL_ERR_MARKERS)


def browser_alive(page) -> bool:
    """探测浏览器/页面是否还活着（goto 超时后鉴别死浏览器 vs 页面挂起）。"""
    try:
        b = page.context.browser
        return bool(b and b.is_connected()) and not page.is_closed()
    except Exception:
        return False


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
    """进入店铺「联系方式」页并解析字段。

    返回值约定（调用方按优先级判断）：
        - 正常解析：dict，含联系方式字段 + _raw/_source_url/_blocked
        - 浏览器进程死亡/被服务端关闭（TargetClosed、崩溃等，非风控）：
          返回 {"_fatal": <原因>} 标记 dict，调用方应直接重启浏览器重试，
          不应计入风控连续失败计数，更不该在死浏览器上空等
        - 网络/代理层错误（隧道断、连接重置等，与风控无关）：
          返回 {"_net_error": <原因>} 标记 dict，调用方应换通道/退避重试，
          不应计入风控连续失败计数
        - 其他异常（超时、解析失败等）：返回 None
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
        # 风控拦截检测：命中时返回原因字符串，调用方据此换 IP 重试
        info["_blocked"] = is_risk_blocked(page.url, text)
        return info
    except Exception as e:
        reason = str(e).splitlines()[0][:200]
        # 1) 浏览器进程级致命错误（会话被服务端关闭、崩溃等），优先识别
        if is_fatal_browser_error(e):
            _log(f"    [X] {shop_domain} 浏览器已关闭/崩溃（非风控，"
                 f"可能是会话被服务端终止）: {reason}")
            return {"_fatal": reason}
        # 2) 网络/代理层错误
        if is_network_error(e):
            _log(f"    [X] {shop_domain} 联系方式抓取失败"
                 f"（网络/代理层错误，非风控）: {e}")
            return {"_net_error": reason}
        # 3) 其他异常（多为 goto 超时）：先鉴别浏览器是不是已经死了
        if not browser_alive(page):
            _log(f"    [X] {shop_domain} 抓取失败且浏览器连接已断开"
                 f"（非风控，会话疑似被终止）: {reason}")
            return {"_fatal": f"浏览器连接断开: {reason}"}
        # 浏览器还活着：记录当前停留 URL 辅助鉴别（拦截页挂起 vs 真风控）
        try:
            cur_url = page.url
        except Exception:
            cur_url = ""
        _log(f"    [X] {shop_domain} 联系方式抓取失败"
             f"（当前停留 URL: {cur_url or '未知'}）: {e}")
        return None
