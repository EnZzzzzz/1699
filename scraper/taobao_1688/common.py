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
    - 代理模式的新出口 IP 不从 .cache/cookies_1688.json 播种：种子里的
      cookie2 / t / cna 等匿名身份标识一旦跨 IP 复制，就是「同一访客
      同时从多个 IP 出现」的 Cookie 重放特征（多 worker 并发时成倍放大）。
      新 IP 以空会话启动，由 warmup 时站点为当前出口现场签发全新身份。
      （青果隧道出口 IP 每 30 分钟自动轮换一次，属产品特性；
       换 IP 后库里没有该 IP 的 Cookie，需重新过一次验证。）
"""

from __future__ import annotations  # 兼容 Python < 3.10 的 X | None 注解

import json
import math
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

# 注意：不要给浏览器上下文硬编码 user_agent。CloakBrowser 二进制的
# 指纹补丁会按自身 Chromium 版本自报 UA 与 UA-CH（sec-ch-ua），
# 硬编码一个不一致的版本号（如二进制 145 却报 Chrome/150）会造成
# UA 与 UA-CH / JS 特征错配 —— 这是风控识别"UA 被篡改"的典型信号，
# 会抬高每个会话的基础风险分。让二进制原生指纹自报即可。


def _fingerprint_args(identity: str) -> list[str]:
    """按 identity 生成稳定的 CloakBrowser 指纹参数（替代默认的随机种子）。

    默认行为是每次 launch 用随机 --fingerprint 种子：同一出口 IP 被风控
    后重启浏览器，会顶着全新设备指纹加载该 IP 名下的旧 Cookie（cna 等
    按设备签发）——设备突变本身就是风控信号。改为按 identity 哈希取种：
    同一 IP 重启指纹不变（与库中 Cookie 配套），不同 IP 指纹不同
    （避免跨 IP 的设备关联）。种子空间与官方默认一致（10000-99999）。
    """
    import hashlib
    import platform
    seed = int(hashlib.md5(identity.encode()).hexdigest()[:8], 16) % 90000 + 10000
    plat = ("--fingerprint-platform=macos" if platform.system() == "Darwin"
            else "--fingerprint-platform=windows")
    return ["--no-sandbox", f"--fingerprint={seed}", plat]


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
#
# 同理，cookie2 / t / cna / _tb_token_ 等匿名身份与设备标识也不能
# 跨 IP 复制（不登录站点也会用它们识别「同一个访客」）。因此代理模式
# 的新出口 IP 已改为完全不播种（见 launch_browser），本集合仅作
# 直连模式之外的历史参考保留。
SECURITY_COOKIE_NAMES = frozenset({
    "x5sec", "x5secdata", "x5sectag", "sgcookie", "sg", "isg",
})


def seed_cookies_from_json(db, identity: str,
                           cookie_path: Path = COOKIE_JSON) -> int:
    """把 CDP 导出的 JSON Cookie 作为种子导入数据库（保留过期时间）。

    仅供直连模式（identity='direct'）：Cookie 是本机 IP 下签发的，
    链路一致，全量保留。代理模式的新出口 IP 不播种（见 launch_browser
    的 Cookie 加载段），避免把种子里的匿名身份标识（cookie2 / t / cna
    等）复制到多个 IP，形成「同一访客多 IP 并发」的 Cookie 重放特征。
    """
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
                   proxy_server: str = None, pool_size: int = None,
                   stop=None):
    """
    启动 CloakBrowser 并注入 1688 Cookie，返回
    (browser, page, identity, req_proxies, proxy_server)。

    Cookie 存取（SQLite，按出口 IP 隔离，保持会话链路一致）：
        - identity: 直连记 'direct'；代理模式记当前出口 IP
        - 先从 1688.db 的 cookies 表取该 identity 下未过期的 Cookie
        - 直连模式库里没有时用 .cache/cookies_1688.json 作种子导入一次；
          代理模式的新出口 IP 不播种 —— 种子里的 cookie2 / t / cna 等
          匿名身份标识跨 IP 复制会被风控识别为 Cookie 重放（同一访客
          多 IP 并发），改为空会话启动，由 warmup 现场签发全新身份

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

    # ---- Cookie：库优先；仅直连模式用 JSON 种子兜底 ----
    cookies = db.load_cookies(identity) if db else []
    if not cookies and not use_proxy:
        if not COOKIE_JSON.exists():
            sys.exit(f"[X] 数据库中没有 identity={identity} 的 Cookie，"
                     f"且找不到种子文件 {COOKIE_JSON}，请先导出 Cookie")
        n = seed_cookies_from_json(db, identity, COOKIE_JSON)
        cookies = db.load_cookies(identity)
        _log(f"    [cookie] 已从 {COOKIE_JSON.name} 导入 {n} 个 Cookie "
             f"到 identity={identity}")
    info = db.cookie_info(identity)
    _log(f"    [cookie] identity={identity}，可用 {len(cookies)} 个"
         f"（库内共 {info['total']}，已过期剔除 {info['expired']}，"
         f"最近过期: {info['earliest_expiry'] or '未知'}）")
    if use_proxy and not cookies:
        # 新出口 IP 不播种旧会话：种子里的 cookie2 / t / cna 等匿名身份
        # 标识跨 IP 复制 = 「同一访客多 IP 并发」的 Cookie 重放特征
        # （多 worker 并发时成倍放大）。空会话启动，由 warmup 让站点
        # 为当前出口现场签发一套全新的匿名身份。
        _log(f"    [cookie] 新出口 IP 不播种旧会话身份，"
             f"warmup 时由站点为 {identity} 现场签发全新匿名身份")
    if not cookies and not use_proxy:
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
        # 指纹按 identity 稳定生成（同 IP 重启指纹不变，与 Cookie 配套），
        # 替代库默认的每次随机种子；不硬编码 UA，由二进制指纹自报，
        # 避免 UA 与 UA-CH 版本错配
        stealth_args=False,
        args=_fingerprint_args(identity),
        **({"proxy": proxy_conf, "geoip": True} if proxy_conf else {}),
    )
    ctx = browser.new_context(locale="zh-CN")
    ctx.add_cookies(cookies)
    page = ctx.new_page()
    if use_proxy:
        # 新 IP / 新会话预热：访问首页让站点为当前出口现场签发独立
        # Cookie（sgcookie/isg/cna 等），立即回写该 IP 名下 ——
        # 每个 IP 的 Cookie 从此在值层面也是独立的，不再跨 IP 复制。
        # 有头模式下首页弹滑块会停下来等手动过证，过了立即保存 x5sec
        warmup_cookies(db, identity, page, ctx,
                       headed=not headless, stop=stop)
    if use_proxy and db:
        db.record_ip_event(identity, "launch", proxy_server or "")
    return browser, page, identity, req_proxies, proxy_server


def _wait_manual_pass(page, stop, seconds: float, interval: float = 5.0) -> bool:
    """轮询当前页面是否已脱离拦截态（不发起新请求，只在当前页读
    innerText，不会加重风控）。检测到验证通过返回 True；超时、
    页面/浏览器异常或收到停止信号返回 False。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop is not None and stop.is_set():
            return False
        try:
            # 综合判定（含内嵌滑块），与 wait_manual_unblock 同口径
            if page_block_reason(page) is None:
                return True
        except Exception:
            return False  # 页面/浏览器异常，交给调用方后续流程
        if stop is not None:
            stop.wait(interval)
        else:
            time.sleep(interval)
    return False


def warmup_cookies(db, identity: str, page, ctx, headed: bool = False,
                   stop=None, max_wait: float = 600.0) -> bool:
    """新 IP 的 Cookie 自动更新：访问 1688 首页触发站点现场签发。

    匿名身份与风控 Cookie（cookie2/cna/x5sec/sgcookie/isg 等）必须由
    站点按「当前出口 IP + 当前会话」现场签发才算配套，不能跨 IP 复制。
    首页是低风险页面，预热一次即完成绑定，顺带让首个店铺请求带上真实
    的站内浏览轨迹（直接深链 contactinfo.htm 而无首页访问记录本身
    也是爬虫特征）。

    headed=True 且首页即命中滑块时：停下来等用户手动拖动滑块
    （每 5s 检测一次，最长 max_wait 秒），检测到通过立即把新签发的
    x5sec 等 Cookie 写回该出口 IP 名下并返回 True。

    返回 True 表示预热顺利（含手动过证后）；未过证/预热失败返回 False
    （不阻断启动，后续抓取重试/手动过证流程会处理）。
    """
    try:
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
        blocked = page_block_reason(page)
        if blocked and headed:
            # 有头模式：等用户手动拖滑块，过了立即保存 x5sec 并继续
            _log(f"    [warmup] 首页命中风控（{blocked}）")
            _log(f"    [warmup] 👉 请在 {identity} 的浏览器窗口里手动"
                 f"拖动滑块，脚本每 5s 自动检测"
                 f"（最长 {max_wait / 60:.0f} 分钟）...")
            if _wait_manual_pass(page, stop, max_wait):
                n = save_cookies(db, identity, ctx)
                _log(f"    [warmup] ✓ 检测到验证已通过，{n} 个 Cookie"
                     f"（含新 x5sec）已写回 {identity} 名下")
                return True
            if stop is not None and stop.is_set():
                return False
            _log(f"    [warmup] 等待超时仍未过证（不阻断启动，"
                 f"后续抓取重试流程会处理）")
            return False
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
    """拟人随机等待：对数正态（重尾）分布。

    大部分等待落在 lo~hi 附近（中位数取区间中点），但允许偶发的
    长停（截断上限 hi*5），间隔序列的形状比均匀分布更接近真人浏览
    节奏。均匀分布截断了头尾（永不快于 lo、永不久于 hi），长时间
    运行后"上千次操作零长停"本身就是可被判定的机器特征。

    lo / hi 语义保持与旧版兼容：大致的等待量级不变，只是分布形状
    从平顶换成长尾。
    """
    median = (lo + hi) / 2
    t = random.lognormvariate(math.log(median), 0.5)
    t = max(lo * 0.5, min(t, hi * 5))
    _log(f"    ...随机等待 {t:.1f}s")
    time.sleep(t)


# ---------- 终端状态板与等待工具（contact_fetcher / shop_crawler 共用） ----------

def fmt_dur(sec: float) -> str:
    """秒 -> mm:ss（状态行倒计时用）。"""
    m, s = divmod(max(0, int(sec)), 60)
    return f"{m:02d}:{s:02d}"


def _disp_width(s: str) -> int:
    """字符串的终端显示宽度（CJK 全角字符占 2 列）。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in s)


def _truncate_disp(s: str, max_cols: int) -> str:
    """按终端显示宽度截断（中文按 2 列算），防止超宽换行打乱固定行渲染。"""
    import unicodedata
    w, out = 0, []
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > max_cols:
            break
        out.append(ch)
        w += cw
    return "".join(out)


class StatusBoard:
    """终端底部固定 workers 行显示各 worker 实时状态（不刷屏）。

    - fields 结构由调用方自定，渲染格式由 compose(wid, fields) 回调决定；
      detail 字段保留给 common 内部日志路由（set 时未显式给则清空）；
    - set() 更新某 worker 的状态字段并重绘整板（有最小重绘间隔节流）；
    - log() 把重要事件以滚动日志打印在状态板上方；
    - 非 TTY（重定向到文件/管道）时 set() 不重绘、log() 直接 print。
    """

    def __init__(self, n_workers: int, compose=None):
        self.n = n_workers
        self.tty = sys.stdout.isatty()
        self.lock = threading.Lock()
        self.compose = compose or (lambda wid, f: str(f.get("line", "")))
        self.fields = [{"detail": ""} for _ in range(n_workers)]
        self._started = False
        self._last_render = 0.0

    # ---- 渲染 ----

    def _width(self) -> int:
        import shutil
        return max(60, shutil.get_terminal_size((120, 24)).columns - 1)

    def _render_locked(self, force: bool = False):
        if not self.tty or not self._started:
            return
        now = time.monotonic()
        if not force and now - self._last_render < 0.2:
            return
        self._last_render = now
        out = [f"\033[{self.n}A"]  # 光标回到状态板首行
        for wid in range(self.n):
            f = self.fields[wid]
            line = self.compose(wid, f)
            if f.get("detail"):
                line += f" · {f['detail']}"
            out.append("\033[2K\r" + _truncate_disp(line, self._width()) + "\n")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    # ---- 对外接口 ----

    def start(self):
        """预留状态板空间并首次绘制（启动日志打印完之后调用）。"""
        if self.tty and not self._started:
            sys.stdout.write("\n" * self.n)
            sys.stdout.flush()
            self._started = True
            with self.lock:
                self._render_locked(force=True)

    def set(self, wid: int, force: bool = False, **kw):
        """更新 worker 状态字段；未显式给 detail 时清空旧细节。"""
        with self.lock:
            f = self.fields[wid]
            if "detail" not in kw:
                f["detail"] = ""
            f.update(kw)
            self._render_locked(force=force)

    def log(self, msg: str):
        """重要事件：滚动打印在状态板上方（自动按显示宽度折行）。"""
        with self.lock:
            if not self.tty or not self._started:
                print(msg, flush=True)
                return
            width = self._width()
            # 先按显示宽度折行，保证每物理行触发一次滚动，状态板位置不错位
            lines = []
            for part in str(msg).splitlines() or [""]:
                while _disp_width(part) > width:
                    cut = _truncate_disp(part, width)
                    lines.append(cut)
                    part = part[len(cut):]
                lines.append(part)
            out = [f"\033[{self.n}A"]  # 光标回到状态板首行
            for ln in lines:
                out.append("\033[2K\r" + ln + "\n")  # 逐行下推，终端随之滚动
            for wid in range(self.n):  # 在腾出的新位置重绘状态板
                f = self.fields[wid]
                line = self.compose(wid, f)
                if f.get("detail"):
                    line += f" · {f['detail']}"
                out.append("\033[2K\r"
                           + _truncate_disp(line, width) + "\n")
            sys.stdout.write("".join(out))
            sys.stdout.flush()
            self._last_render = time.monotonic()


def wait_countdown(board: StatusBoard, wid: int, stop: threading.Event,
                   seconds: float, state_prefix: str,
                   state_key: str = "state") -> bool:
    """可中断等待，状态行每秒刷新倒计时。返回 True 表示被用户中断。"""
    deadline = time.monotonic() + seconds
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return False
        board.set(wid, **{state_key: f"{state_prefix} 剩 {fmt_dur(remain)}"})
        if stop.wait(min(1.0, remain)):
            return True


def wait_manual_unblock(board: StatusBoard, wid: int, stop: threading.Event,
                        page, seconds: float,
                        state_key: str = "state") -> bool:
    """有头模式专用：等用户在浏览器窗口里手动过滑块/验证。

    每 15s 检测一次当前页面是否已脱离拦截态（不发起新请求，只在
    当前页面上读 innerText，不会加重风控）。检测到验证通过立即返回
    True；超时、页面异常或浏览器死亡返回 False（调用方走原计划休息）。
    """
    deadline = time.monotonic() + seconds
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return False
        board.set(wid, **{state_key: f"等待手动过验证 剩 {fmt_dur(remain)}"})
        if stop.wait(min(15.0, remain)):
            return False  # 用户中断，按未解决处理
        try:
            # 综合判定（含内嵌滑块）：滑块与内容同屏时纯文本判定会
            # 误判为已通过，必须走 page_block_reason
            if page_block_reason(page) is None:
                return True
        except Exception:
            if not browser_alive(page):
                return False  # 浏览器已死，交给后续流程


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

    注意：本函数只看 URL + innerText，检测不到**内嵌**在页面里的
    滑块组件（iframe 内容不进 innerText，会出现「滑块与页面内容
    同屏」的漏判）。完整判定请用 page_block_reason(page)。
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


# 内嵌滑块/验证组件特征：阿里系滑块常作为 iframe 或独立 DOM 容器
# 注入业务页面（联系方式与滑块同屏的场景），innerText 检测会漏判
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


def detect_embedded_slider(page) -> str | None:
    """检测页面内嵌的滑块/验证组件（iframe URL + 滑块 DOM 容器）。

    用于弥补 innerText 检测的盲区：滑块以 iframe 形式内嵌时，
    页面正文（如联系方式）照常可见，但会话实际处于待验证状态，
    此时应立即等待手动过证并更新 Cookie，而不是当作正常结果。
    """
    try:
        for f in page.frames:
            u = (f.url or "").lower()
            for p in EMBEDDED_SLIDER_IFRAME_PATTERNS:
                if p in u:
                    return f"页面内嵌验证 iframe（{f.url[:120]}）"
    except Exception:
        pass
    try:
        for sel in EMBEDDED_SLIDER_SELECTORS:
            el = page.query_selector(sel)
            if el is not None and el.is_visible():
                return f"页面内嵌滑块组件（选择器 {sel}）"
    except Exception:
        pass
    return None


def page_block_reason(page) -> str | None:
    """综合判定当前页是否被风控/待验证：URL + 文本特征 + 内嵌滑块组件。

    所有「是否被拦」「是否已过证」的判定统一走这里，避免各入口
    检测口径不一致（例如纯文本判定会把内嵌滑块误判为已通过）。
    """
    try:
        url = page.url
    except Exception:
        url = ""
    text = ""
    try:
        text = page.evaluate(
            "() => document.body ? document.body.innerText : ''") or ""
    except Exception:
        pass
    return is_risk_blocked(url, text) or detect_embedded_slider(page)


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
        info["_blocked"] = page_block_reason(page)
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
