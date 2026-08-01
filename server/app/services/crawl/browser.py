# -*- coding: utf-8 -*-
"""
CloakBrowser 启动 / Cookie 管理（server 版重写）。

重写自 scraper/taobao_1688/common.py 的浏览器部分（蓝本只读，未被 import）。
与蓝本差异：代理不再从 util/proxy_qingguo 取，而是由调用方（Celery task）
通过 PoolClient 向共享池申请通道后，把 tunnel + 账密以显式参数传入。

cloakbrowser 为可选依赖：懒导入，缺失时抛出明确错误，不影响其他功能。

会话链路一致性（scraper/README.md 经验）：
    Cookie 按出口 IP（identity）隔离存取；直连记 'direct'，代理记实际出口 IP；
    退出时把浏览器最新 Cookie（含新 x5sec）写回该 identity 名下。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from loguru import logger

from ... import config
from .pages import UA
from .shopdb import ShopDB

COOKIE_JSON = config.ROOT_DIR / ".cache" / "cookies_1688.json"
CONFIG_JSON = config.ROOT_DIR / ".cache" / "config.json"


class BrowserUnavailable(RuntimeError):
    """cloakbrowser 未安装或不可用。"""


def _cb_launch(**kwargs):
    try:
        from cloakbrowser import launch
    except ImportError as e:
        raise BrowserUnavailable(
            "cloakbrowser 未安装：pip install cloakbrowser。"
            "采集任务需要它启动指纹浏览器；其余 API 功能不受影响。") from e
    return launch(**kwargs)


# ---------- License ----------

def load_license_key() -> str | None:
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text())["CLOAKBROWSER_LICENSE_KEY"]
        except Exception:
            return None
    return None


def wait_for_license_seat(tag: str = "", timeout: float = 600.0,
                          interval: float = 20.0) -> bool:
    """启动前检查 CloakBrowser 会话席位（free 套餐仅 1 个）。

    上次运行异常退出时租约不立即释放，残留期间新二进制会自行退出
    （不透明的 TargetClosedError）；这里主动轮询等残留租约过期。
    查询失败不阻塞，直接放行。
    """
    key = load_license_key()
    if not key:
        return True
    try:
        from cloakbrowser.license import get_active_session_count, validate_license
    except ImportError:
        return True
    try:
        info = validate_license(key)
    except Exception:
        return True
    if not info or info.plan != "free":
        return True
    deadline = time.time() + timeout
    while True:
        n = get_active_session_count(key)
        if n is None or n < 1:
            return True
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        wait = min(interval, remaining)
        logger.info("{}[license] 服务端仍有 {} 个活跃会话未释放，{:.0f}s 后重查...",
                    tag, n, wait)
        time.sleep(wait)


# ---------- 出口 IP ----------

def get_exit_ip(req_proxies: dict = None, timeout: int = 10) -> str | None:
    """查询当前出口 IP（代理模式下经代理查询），失败返回 None。"""
    try:
        r = requests.get("https://ipinfo.io/json", proxies=req_proxies,
                         timeout=timeout)
        return r.json().get("ip")
    except Exception:
        return None


# ---------- 启动浏览器 ----------

def launch_browser(db: ShopDB, headless: bool = True,
                   proxy_server: str | None = None,
                   proxy_auth: tuple[str, str] | None = None):
    """启动 CloakBrowser 并注入 1688 Cookie。

    proxy_server: 隧道入口 host:port（None = 直连）；
    proxy_auth:   (auth_key, auth_pwd) 代理账密（proxy_server 非空时必传）。

    返回 (browser, page, identity, req_proxies, proxy_server)：
        identity     — Cookie 隔离键：直连 'direct'，代理为当前出口 IP
        req_proxies  — requests 查询出口 IP 用的代理字典（直连为 None）
    """
    proxy_conf = None
    identity = "direct"
    seeded_from_local = False
    req_proxies = None
    if proxy_server:
        user, pwd = proxy_auth
        proxy_conf = {
            "server": f"http://{proxy_server}",
            "username": user,
            "password": pwd,
        }
        url = f"http://{user}:{pwd}@{proxy_server}"
        req_proxies = {"http": url, "https": url}
        exit_ip = get_exit_ip(req_proxies)
        identity = exit_ip or f"qingguo:{proxy_server}"
        logger.info("    [proxy] 通道 {}，出口 IP: {}",
                    proxy_server, exit_ip or "查询失败")

    # ---- Cookie：库优先，JSON 种子兜底 ----
    cookies = db.load_cookies(identity)
    if not cookies:
        if not COOKIE_JSON.exists():
            raise RuntimeError(
                f"数据库中没有 identity={identity} 的 Cookie，"
                f"且找不到种子文件 {COOKIE_JSON}，请先导出 Cookie")
        n = db.seed_cookies_from_json(identity, COOKIE_JSON)
        seeded_from_local = True
        cookies = db.load_cookies(identity)
        logger.info("    [cookie] 已从 {} 导入 {} 个 Cookie 到 identity={}",
                    COOKIE_JSON.name, n, identity)
    info = db.cookie_info(identity)
    logger.info("    [cookie] identity={}，可用 {} 个（库内共 {}，已过期剔除 {}）",
                identity, len(cookies), info["total"], info["expired"])
    if proxy_server and seeded_from_local:
        logger.warning("    [!] 该出口 IP 的 Cookie 来自本机种子 —— Cookie 与"
                       "代理出口 IP 错配，可能触发 x5sec 风控；"
                       "建议有头模式在代理下登录/过滑块")
    if not cookies:
        raise RuntimeError(f"identity={identity} 下没有可用 Cookie（可能全部过期）")

    browser = _cb_launch(
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


def save_cookies(db: ShopDB, identity: str, ctx) -> int:
    """把浏览器上下文中的 1688 Cookie 写回数据库（按 identity 隔离）。"""
    cookies = [c for c in ctx.cookies() if "1688.com" in c.get("domain", "")]
    if not cookies:
        return 0
    n = db.save_cookies(identity, cookies)
    logger.info("    [cookie] 已把 {} 个 Cookie 写回数据库 (identity={})",
                n, identity)
    return n
