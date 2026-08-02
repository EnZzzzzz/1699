# -*- coding: utf-8 -*-
"""
1688 采集网络层（共享模块）

原子化拆分后的两层架构:
    网络层（本模块）—— 管「怎么连」，不关心采什么:
        - Cookie / License 加载，Cookie 按出口 IP 隔离存取
        - 青果住宅代理接入、出口 IP 查询与轮换检测
        - CloakBrowser 启动/预热/重启（会话链路一致: Cookie / UA /
          指纹 / 出口 IP 不错配）
        - 风控检测（URL/文本/内嵌滑块）与错误分级（网络层/浏览器致命/
          风控拦截）
        - 多 worker 并发引擎（FetchTask 协议 + run_workers）：一 worker
          一通道，批次休息、样本间隔、风控状态机（原地休息 → 修复换
          IP → 放弃）、状态板显示
    任务层（contact_fetcher.py / shop_crawler.py）—— 管「采什么」:
        页面解析、数据入库、任务队列（pending 店铺 / 类目池），
        实现 FetchTask 协议挂到网络层引擎上运行。

被 shop_crawler.py（店铺采集）和 contact_fetcher.py（联系方式抓取）共用:

代理模式会话链路说明（按 scraper/README.md 经验）:
    - 直连模式: Cookie 是本机浏览器种下的，出口 IP = 本机 IP，链路一致
    - 代理模式: 出口 IP 变成青果住宅 IP，本机种下的 Cookie 与 IP 错配，
      容易触发 x5sec 风控。因此 Cookie 全部存进 SQLite（1688.db 的
      cookies 表），按出口 IP（identity）隔离存取，并记录每个 Cookie
      的过期时间 expires —— 哪个 IP 的 Cookie、什么时候过期一目了然。
    - 首次 --proxy --headed 运行，在代理出口下登录/过滑块，脚本退出时
      自动把浏览器最新 Cookie（含新 x5sec）写回该 IP 名下的记录，
      之后同一出口 IP 都复用它，保持 Cookie / x5sec / UA / 出口 IP 一致。
    - 身份来源两级：默认新出口 IP 以白板会话启动（warmup 时站点为当前
      出口现场签发全新身份，信任分从零，敏感端点容易弹滑块）；
      若 --seeds 目录（默认 .cache/seeds/）配置了种子身份池，每个
      worker 独占认领一份熟身份 —— 只种 cna/cookie2/t 等设备绑定
      Cookie（IP 绑定的 x5sec/sgcookie/isg 绝不跨 IP 复制），一对一
      绑定避免「同一身份多 IP 并发」的 Cookie 重放特征，指纹也按种子
      固定（cna 按设备签发，指纹必须与身份配套）。种子在多个新鲜 IP
      上首请求即被拦时判定烧毁，自动退回白板会话。
      （青果隧道出口 IP 每 30 分钟自动轮换一次，属产品特性；
       换 IP 后该 worker 重新播种自己的种子，warmup 补 IP 绑定 Cookie。）
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
# TODO(遗留事项): 实验「种子保留 x5sec/x5secdata」——种子一对一独占后
# 不存在并发重放，若 x5sec 实际绑设备而非严格绑 IP，保留它可能免滑块。
# 见 风控拦截分析_20260802.md 第八节（实验设计：--seed-x5sec 开关 + A/B）。
#
# 同理，cookie2 / t / cna / _tb_token_ 等匿名身份与设备标识也不能
# 跨 IP 复制（不登录站点也会用它们识别「同一个访客」）。因此代理模式
# 的新出口 IP 已改为完全不播种（见 launch_browser），本集合仅作
# 直连模式之外的历史参考保留。
SECURITY_COOKIE_NAMES = frozenset({
    "x5sec", "x5secdata", "x5sectag", "sgcookie", "sg", "isg",
})


# ---------- 种子身份池（.cache/seeds/*.json） ----------
#
# 背景：多 worker 化后新出口 IP 一律白板会话启动（防 Cookie 重放），
# 但白板身份信任分从零，凌晨严格时段首访敏感端点必弹滑块
# （2026-08-02 凌晨 30 个新 IP 全部 gap=1 被秒拦）。
#
# 解法：种子身份池 —— seeds_dir 下每份 json 是一个「熟身份」
# （真实浏览器长期养出的 Cookie，cna/cookie2/t 等设备绑定标识）。
# 每个 worker 独占认领一份，一对一绑定：
#   - 同一身份同时出现在多个 IP = Cookie 重放强信号（旧版单种子
#     多 worker 共用的问题），一对一独占后不存在；
#   - 一个身份顺序地随 IP 轮换迁移 = 真人换网络的弱信号，可接受。
# 只种设备绑定 Cookie；IP 绑定的安全 Cookie（SECURITY_COOKIE_NAMES）
# 在加载时剔除，绝不跨 IP 复制。指纹按种子固定（cna 按设备签发，
# 指纹必须与身份配套，否则是"身份被篡改"信号）。


# 种子里可保留的验证凭证（仅 --seed-x5sec 实验时启用）：
# x5sec/x5secdata 是纯人机验证凭证，种子一对一独占后不存在并发重放；
# 若 1688 对 x5sec 的校验实际绑设备而非严格绑 IP，保留它可免滑块。
# sgcookie/sg/isg/x5sectag 与会话安全上下文绑定更深，始终剔除。
X5SEC_SEEDABLE_NAMES = frozenset({"x5sec", "x5secdata"})


def load_seed_kits(seeds_dir, keep_x5sec: bool = False) -> list[dict]:
    """加载种子身份池：seeds_dir 下每个 .json 是一份 CDP 导出的熟身份 Cookie。

    返回 [{"name": 文件名（去扩展名）, "cookies": [Playwright 格式],
           "x5sec": bool}...]，只保留 1688 域且非 IP 绑定的设备身份 Cookie；
    keep_x5sec=True 时额外保留未过期的 x5sec/x5secdata（免滑块实验，
    kit["x5sec"] 标记供日志与 A/B 归因）。不含 cna/cookie2 的文件
    视为「不熟」（和白板没区别），跳过并打日志。
    """
    kits = []
    seeds_dir = Path(seeds_dir)
    if not seeds_dir.exists():
        return kits
    for f in sorted(seeds_dir.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            _log(f"    [seed] 种子 {f.name} 解析失败，跳过: {e}")
            continue
        cookies, names = [], set()
        for c in raw:
            if "1688.com" not in c.get("domain", ""):
                continue
            if c["name"] in SECURITY_COOKIE_NAMES:
                if not (keep_x5sec and c["name"] in X5SEC_SEEDABLE_NAMES):
                    continue  # IP 绑定的安全 Cookie 不跨 IP 复制
                # x5sec 短时效：过期的别种（带过期凭证比不带更可疑）
                exp = c.get("expires") or c.get("expirationDate")
                try:
                    if exp and float(exp) > 0 and float(exp) <= time.time():
                        continue
                except (TypeError, ValueError):
                    continue
            names.add(c["name"])
            cookies.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/") if not c.get("path", "").startswith("//") else "/",
                "secure": bool(c.get("secure", False)),
                "httpOnly": bool(c.get("httpOnly", False)),
            })
        if not ({"cna", "cookie2"} & names):
            _log(f"    [seed] 种子 {f.name} 不含 cna/cookie2"
                 f"（身份不够熟，和白板没区别），跳过")
            continue
        kits.append({"name": f.stem, "cookies": cookies,
                     "x5sec": bool(X5SEC_SEEDABLE_NAMES & names)})
    return kits



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
                   stop=None, seed_kit: dict = None):
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

    # cloakbrowser 的 GeoIP 探测（经代理向 ipify/ifconfig.me 等 3 个海外
    # echo 服务查出口 IP）默认总预算只有 5s，青果住宅隧道 RTT 高，经常
    # 全部超时打出 "Failed to discover exit IP through proxy"（只是
    # warning，但本次会话会缺失 GeoIP 定位）。放宽到 20s；可用
    # CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS 环境变量自行覆盖。
    os.environ.setdefault("CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS", "20")

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
    if use_proxy and not cookies and seed_kit:
        # 种子身份池：本 worker 独占的熟身份（仅设备绑定 Cookie，
        # IP 绑定的安全 Cookie 加载时已剔除，--seed-x5sec 实验组除外）。
        # 一对一绑定 worker，不存在同一身份多 IP 并发的重放特征；
        # 指纹也按种子固定。写入该出口 IP 名下，让会话链路在此 IP 上沉淀。
        cookies = [dict(c) for c in seed_kit["cookies"]]
        if db:
            db.save_cookies(identity, cookies)
            # 播种落库：A/B 归因用（哪个种子、是否含 x5sec、种到哪个 IP）
            db.record_ip_event(
                identity, "seed",
                f"kit={seed_kit['name']} x5sec={1 if seed_kit.get('x5sec') else 0}")
        _log(f"    [cookie] 新出口 IP 播种独占种子身份"
             f"「{seed_kit['name']}」（{len(cookies)} 个 Cookie"
             f"{'，含 x5sec 实验组' if seed_kit.get('x5sec') else ''}）")
    elif use_proxy and not cookies:
        # 无种子可用：空会话白板启动，由 warmup 让站点为当前出口
        # 现场签发一套全新的匿名身份（信任分从零，敏感端点容易弹滑块）
        _log(f"    [cookie] 无种子身份，新出口 IP 空会话白板启动，"
             f"warmup 时由站点为 {identity} 现场签发全新匿名身份")
    if not cookies and not use_proxy:
        sys.exit(f"[X] identity={identity} 下没有可用 Cookie（可能全部过期）")

    # 启动前等服务端有空余会话席位（上次异常退出的残留租约未释放时，
    # 直接 launch 会被服务端拒绝/启动后被关闭，表现为 TargetClosedError）
    tag = getattr(_tls, "tag", "")
    _log(f"    [launch] 检查 CloakBrowser 会话席位…")
    if not wait_for_license_seat(tag=f"{tag} " if tag else "",
                                 timeout=600.0):
        raise RuntimeError("等待 600s 后 CloakBrowser 会话席位仍满员，"
                           "请检查是否有残留会话未释放")

    # launch() 必须在「将要使用浏览器的同一个线程」里调用 ——
    # Playwright 同步 API 绑死创建线程（greenlet 调度），跨线程使用
    # 会抛 "cannot switch to a different thread"。因此不能为了加
    # 超时把 launch 放进临时线程（已踩过坑），看门狗只做纯观察：
    # 不触碰 playwright 对象，长时间未返回时打警告定位卡死环节。
    _log(f"    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…")
    _launch_done = threading.Event()

    def _launch_watchdog():
        if not _launch_done.wait(240):
            _log(f"    [X] launch() 已超过 240s 未返回，疑似库内部卡死"
                 f"（GeoIP 探测/二进制校验/代理配置解析）；"
                 f"无法安全跨线程中止，请人工观察处理")

    threading.Thread(target=_launch_watchdog, daemon=True,
                     name=f"launch-watchdog-{identity}").start()
    try:
        browser = launch(
            headless=headless,
            license_key=load_license_key(),
            humanize=True,
            locale="zh-CN",
            timezone="Asia/Shanghai",
            # 指纹：有种子身份时按种子名固定（cna 等设备标识按设备签发，
            # 指纹必须与身份配套，否则是"身份被篡改"信号；harvest_seeds
            # 收割的种子以原出口 IP 命名，恰好复现该身份养成时的指纹）；
            # 无种子按出口 IP 固定（同 IP 重启指纹不变，与库中 Cookie
            # 配套）；不硬编码 UA，由二进制指纹自报
            stealth_args=False,
            args=_fingerprint_args(seed_kit["name"] if seed_kit else identity),
            **({"proxy": proxy_conf, "geoip": True} if proxy_conf else {}),
        )
    except SystemExit as e:
        raise RuntimeError(f"CloakBrowser 二进制退出（code={e.code}，"
                           f"多为会话席位被占或 License 校验失败）")
    finally:
        _launch_done.set()
    _log(f"    [launch] 浏览器进程已启动，创建上下文并注入 Cookie…")
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
                        state_key: str = "state",
                        interval: float = 30.0) -> bool:
    """有头模式专用：等用户在浏览器窗口里手动过滑块/验证/登录。

    每 30s 检测一次当前页面是否已脱离拦截态（不发起新请求，只在
    当前页面上读 innerText，不会加重风控）。检测到验证通过立即返回
    True；超时、页面异常或浏览器死亡返回 False（调用方走原计划休息）。
    """
    deadline = time.monotonic() + seconds
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return False
        board.set(wid, **{state_key: f"等待手动过验证 剩 {fmt_dur(remain)}"})
        if stop.wait(min(interval, remain)):
            return False  # 用户中断，按未解决处理
        try:
            # 综合判定（含内嵌滑块）：滑块与内容同屏时纯文本判定会
            # 误判为已通过，必须走 page_block_reason
            if page_block_reason(page) is None:
                return True
        except Exception:
            if not browser_alive(page):
                return False  # 浏览器已死，交给后续流程


# 阿里系登录态 Cookie 标记：登录成功后站点才会签发（匿名会话没有），
# 用于检测「用户已在窗口里手动登录」
LOGIN_COOKIE_MARKERS = ("unb", "lid", "cookie1", "_nk_", "tracknick", "dnk")


def wait_manual_login(board: StatusBoard, wid: int, stop: threading.Event,
                      ctx, seconds: float, interval: float = 30.0) -> bool:
    """等 IP 轮换期间（有头模式专用）：轮询用户是否在当前窗口手动登录。

    与 wait_manual_unblock 的区别：此时浏览器刚重启过、页面停在新会话
    首页（不在拦截页上），页面状态判定会误判为「已通过」，改为对比
    Cookie 增量 —— 登录后站点会签发 unb / lid / cookie1 等登录态
    Cookie（匿名会话没有），出现即视为已登录；个别未知标记兜底：
    相比基线新增 >= 3 个 Cookie 名也视为发生了手动登录。
    检测到返回 True；超时、浏览器异常或收到停止信号返回 False。
    """
    try:
        baseline = {c["name"] for c in ctx.cookies()
                    if "1688.com" in c.get("domain", "")}
    except Exception:
        return False
    deadline = time.monotonic() + seconds
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return False
        board.set(wid, state=f"等 IP 轮换（可手动登录）剩 {fmt_dur(remain)}")
        if stop.wait(min(interval, remain)):
            return False  # 用户中断，按未解决处理
        try:
            names = {c["name"] for c in ctx.cookies()
                     if "1688.com" in c.get("domain", "")}
        except Exception:
            return False  # 浏览器已死，交给后续流程
        if any(m in names for m in LOGIN_COOKIE_MARKERS):
            return True
        if len(names - baseline) >= 3:
            return True


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




# ==========================================================================
# 多 worker 并发引擎（网络层执行框架）
#
# 任务层实现 FetchTask 协议（采什么 / 怎么入库），引擎管「怎么连」：
# 一 worker 一通道（独立出口 IP）、IP + Cookie 配套、批次休息、样本
# 间隔、风控状态机（原地休息 → 修复换 IP → 放弃）、状态板显示。
# contact_fetcher.py 与 shop_crawler.py 共用这一套，不允许各自另起
# 网络层逻辑。
# ==========================================================================


def relaunch_browser(board: StatusBoard, tag: str, wid: int, args,
                     db, proxy_server: str | None,
                     old_browser, old_ctx, old_identity: str,
                     stop: threading.Event, seed_kit: dict = None):
    """关闭旧浏览器（先回写 Cookie），重开新实例以绑定新出口 IP。

    青果出口 IP 每 30 分钟轮换一次，轮换后旧 identity 的 Cookie 与新
    出口 IP 错配，必须重启浏览器让 launch_browser 重新查询出口 IP 并
    按新 identity 加载/绑定 Cookie。最多重试 args.ip_retry 次（线性
    退避），全部失败抛 RuntimeError。
    """
    if old_ctx is not None:
        try:
            save_cookies(db, old_identity, old_ctx)
        except Exception as e:
            board.log(f"{tag}   [!] 旧 Cookie 回写失败: {e}")
    if old_browser is not None:
        try:
            old_browser.close()
        except Exception:
            pass

    board.set(wid, state="重启浏览器获取新 IP…", force=True)
    last_err = None
    for attempt in range(1, args.ip_retry + 1):
        if stop.is_set():
            raise RuntimeError("用户中断")
        try:
            browser, page, identity, req_proxies, _ = launch_browser(
                headless=not args.headed, use_proxy=args.proxy, db=db,
                proxy_server=proxy_server, pool_size=args.channels or None,
                stop=stop, seed_kit=seed_kit)
            board.set(wid, ip=identity, state="浏览器已重启", force=True)
            board.log(f"{tag} 浏览器已重启，新出口 IP={identity}")
            return browser, page, identity, req_proxies
        except (Exception, SystemExit) as e:
            last_err = e
            backoff = min(30 * attempt, 120)
            board.log(f"{tag}   [!] 获取新 IP 第 {attempt}/{args.ip_retry} "
                      f"次失败: {e}，{backoff}s 后重试...")
            if wait_countdown(board, wid, stop, backoff, "重启退避"):
                raise RuntimeError("用户中断")
    raise RuntimeError(f"重试 {args.ip_retry} 次仍无法获取新 IP: {last_err}")


def check_ip_fresh(req_proxies: dict, identity: str) -> tuple:
    """检查当前出口 IP 是否仍有效，返回 (need_relaunch, cur_ip, reason)。

    青果出口 IP 每 30 分钟轮换一次：查询到的 IP 与 identity 不一致即
    视为已过期；查询失败先短重试 3 次确认隧道是否真的失效。
    """
    cur_ip = get_exit_ip(req_proxies)
    if cur_ip is None:
        for _ in range(3):
            time.sleep(5)
            cur_ip = get_exit_ip(req_proxies)
            if cur_ip:
                break
    if cur_ip is None:
        return True, None, "出口 IP 查询失败，隧道疑似失效"
    if cur_ip != identity:
        return True, cur_ip, f"出口 IP 已轮换（{identity} -> {cur_ip}）"
    return False, cur_ip, ""


class FetchTask:
    """任务层协议：网络层引擎按此接口驱动一个采集任务。

    子类只需实现「采什么」：从哪取任务项、怎么抓、抓到怎么入库。
    scrape() 返回值约定（引擎按优先级判断，与历史脚本一致）：
        - 正常：dict（可含 _blocked 之外的业务字段）
        - {"_fatal": 原因}   浏览器进程死亡/被关闭（非风控，重启浏览器重试）
        - {"_net_error": 原因} 网络/代理层错误（非风控，原通道退避重试）
        - dict 含 "_blocked"  疑似风控拦截（进风控状态机）
        - None               其他异常（按风控处理）
    """

    unit = "样本"          # 状态行里的间隔单位名（"样本" / "页"）
    batch_unit = ""        # 批次日志里的计量名词（"" / "店铺"）
    cold_start_before_acquire = False  # True: 冷启动在 acquire 之前执行
                                       # （如类目池需要先逛首页填池）

    # ---- main 阶段 ----
    def prepare(self, args) -> bool:
        """启动前的准备（重置状态/打印计划）；返回 False 直接退出。"""
        return True

    def summary(self, all_stats: dict) -> str:
        """全部 worker 结束后的汇总行。"""
        return str(all_stats)

    # ---- 状态板 ----
    def compose(self, wid: int, f: dict) -> str:
        """状态行格式（StatusBoard compose 回调）。"""
        raise NotImplementedError

    def make_stats(self) -> dict:
        """每个 worker 的统计字典（结构任务自定）。"""
        return {}

    def rest_counter(self, stats: dict) -> int:
        """长休息计数基准（--rest-every 按此值取模）。"""
        return 0

    # ---- worker 循环 ----
    def acquire(self, db, wctx: dict):
        """认领一个任务项；没有可做的返回 None（worker 退出）。"""
        raise NotImplementedError

    def label(self, item) -> str:
        """状态行上显示的任务项名称。"""
        return str(item)

    def cold_start(self, page, item, log=None) -> None:
        """新会话冷启动软着陆（留下真实浏览轨迹）。

        cold_start_before_acquire=False 时在 acquire 之后调用（item 为
        当前任务项）；True 时在 acquire 之前调用（item 为 None）。
        """

    def empty_message(self) -> str:
        """任务队列耗尽时的一行滚动日志。"""
        return "没有待做的任务了"

    def scrape(self, page, item) -> dict | None:
        """抓取当前任务项（返回值约定见类 docstring）。"""
        raise NotImplementedError

    def on_success(self, db, item, info: dict, wctx: dict,
                   set_status, log) -> int:
        """抓取成功：入库/更新统计/状态行；返回计入批次配额的数量。"""
        return 1

    def on_giveup(self, db, item, reason: str, kind: str, wctx: dict,
                  set_status, log) -> str:
        """放弃当前任务项（kind: "net" 网络故障 / "block" 风控）；
        返回一句短语让引擎拼进日志（如 "标记 failed 跳过"）。"""
        return "跳过"

    def on_abort(self, item) -> str:
        """连续失败触发整体中止时的一行补充说明。"""
        return ""

    def giveup_cost(self, item) -> int:
        """放弃的任务项计入批次配额的数量（联系人按店铺计 1；
        类目页放弃时不计，页码本来就没前进）。"""
        return 0

    def after_item(self, item, wctx: dict) -> None:
        """当前任务项处理完毕（含放弃）后的收尾（如释放类目占用）。"""


# ---------- 引擎：worker 主循环 ----------

def _engine_worker(worker_id: int, args, task: FetchTask,
                   proxy_server: str | None, seed_kit: dict | None,
                   board: StatusBoard,
                   state: dict, lock: threading.Lock, stop: threading.Event):
    """单个 worker：独立浏览器 + 独立 DB 连接 + 独占代理通道。

    生命周期：领通道 → 启动浏览器按出口 IP 配 Cookie → 认领/抓取循环
    （样本间随机间隔，批次间大休息）→ 风控先休息当前 IP，再修复换 IP。
    """
    from database import ShopDB  # 延迟导入，保持 common 可独立加载

    tag = f"[w{worker_id}]"
    set_tag(tag)  # common 内部日志按本 worker 路由到状态板
    db = ShopDB()
    browser = None
    stats = task.make_stats()
    consecutive_fail = 0  # 连续风控失败计数，超限中止整个任务
    identity = "direct"
    ctx = None
    req_proxies = None
    wctx: dict = {"stats": stats}  # 任务层可用的 per-worker 暂存
    # tmd 统计：按出口 IP 计页面请求数与「距上次触发」计数
    # （identity 作 key，换 IP 后自然分开累计，无需手动清零）
    ip_req: dict = {}
    # 种子身份池：本 worker 独占的熟身份（None 则白板会话）。
    # 若它在多个新鲜 IP 上都首请求即被拦，说明被标记的是身份本身
    # 而非 IP —— 判定种子烧毁，停止播种，退回白板会话
    kit = seed_kit
    kit_burn_ips: set = set()

    def set_status(**kw):
        board.set(worker_id, **kw)

    def log(msg: str):
        board.log(msg)

    try:
        set_status(state="启动浏览器…", force=True)
        last_err = None
        for attempt in range(1, args.ip_retry + 1):
            if stop.is_set():
                return
            try:
                browser, page, identity, req_proxies, _ = launch_browser(
                    headless=not args.headed, use_proxy=args.proxy, db=db,
                    proxy_server=proxy_server,
                    pool_size=args.channels or None,
                    stop=stop, seed_kit=kit)
                break
            except (Exception, SystemExit) as e:
                last_err = e
                backoff = min(30 * attempt, 120)
                board.log(f"{tag}   [!] 启动浏览器第 {attempt}/{args.ip_retry} "
                          f"次失败: {e}，{backoff}s 后重试...")
                if wait_countdown(board, worker_id, stop, backoff, "启动退避"):
                    return  # 用户中断
        else:
            raise RuntimeError(f"启动浏览器重试 {args.ip_retry} "
                               f"次仍失败: {last_err}")
        # 出口 IP 一确定就持久打印（状态行的 detail 是瞬时的，
        # 且重定向到日志文件时会丢失）
        board.log(f"{tag} 浏览器就绪，出口 IP={identity}"
                  f"（{'通道 ' + proxy_server if proxy_server else '直连'}）")
        ctx = page.context
        batch_no = 1
        done_in_batch = 0  # 本 worker 当前批次已采数量（-n 按 worker 各自计）
        warm = True        # 新会话冷启动软着陆（首个任务前先留浏览轨迹）
        set_status(ip=identity, batch=batch_no, state="就绪", force=True)

        while not stop.is_set():
            # ---- 批次配额（每个 worker 各自计数）：本 worker 采满 -n 个后
            #      各自强制大休息（±10% 抖动），再自动开下一批；
            #      各 worker 批次互不同步，避免集体停工 ----
            if done_in_batch >= args.num:
                if args.max_batches and batch_no >= args.max_batches:
                    board.log(f"{tag} 第 {batch_no} 批采满，"
                              f"已达批次上限（--max-batches），收工")
                    set_status(state="收工")
                    return  # finally 会保存 Cookie、关闭浏览器
                rest = random.uniform(args.batch_rest * 0.9,
                                      args.batch_rest * 1.1)
                board.log(f"{tag} ⏸ 第 {batch_no} 批已采满 "
                          f"{args.num} 个{task.batch_unit}，"
                          f"强制休息 {rest / 60:.1f} 分钟（防风控）...")
                if wait_countdown(board, worker_id, stop, rest, "批次休息"):
                    return  # 用户中断
                batch_no += 1
                done_in_batch = 0
                board.log(f"{tag} ▶ 休息结束，开始第 {batch_no} 批")
                set_status(batch=batch_no, state="采集中")

            # ---- 会话冷启动软着陆（acquire 前执行的任务，如先逛首页
            #      提取类目填池）：新会话一上来就深链是明显的爬虫特征 ----
            if warm and task.cold_start_before_acquire:
                set_status(state="冷启动软着陆…")
                task.cold_start(page, None, log=log)
                warm = False

            # ---- 认领任务项 ----
            item = task.acquire(db, wctx)
            if item is None:
                board.log(f"{tag} {task.empty_message()}")
                set_status(state="无待做任务，退出")
                break
            set_status(shop=task.label(item), state="检查出口 IP…")

            # ---- 出口 IP 过期检查（青果每 30 分钟轮换一次出口）----
            if args.proxy:
                need_relaunch, cur_ip, reason = check_ip_fresh(
                    req_proxies, identity)
                if need_relaunch:
                    board.log(f"{tag} 🔄 {reason}，重启浏览器绑定新 IP ...")
                    browser, page, identity, req_proxies = relaunch_browser(
                        board, tag, worker_id, args, db, proxy_server,
                        browser, ctx, identity, stop, seed_kit=kit)
                    ctx = page.context
                    warm = True  # 新会话重新冷启动软着陆

            # ---- 会话冷启动软着陆（acquire 后执行的任务，如先逛店铺
            #      首页再进深链页面）----
            if warm:
                set_status(state="冷启动软着陆…")
                task.cold_start(page, item, log=log)
                warm = False

            # ---- 抓取（网络故障原通道退避重试，不计入风控计数；
            #      风控：先休息当前 IP → 再修复换 IP → 仍失败放弃）----
            block_stage = 0   # 0 未触发 / 1 已休息过一次 / 2 已修复换过 IP
            net_retried = 0
            while True:
                set_status(state="采集中")
                info = task.scrape(page, item)
                fatal_reason = info.pop("_fatal", None) if info else None
                net_reason = info.pop("_net_error", None) if info else None
                block_reason = info.pop("_blocked", None) if info else None
                # ---- tmd 统计：按出口 IP 累计页面请求数（网络/代理层
                #      错误和浏览器死亡说明请求没到目标站，不消耗该 IP
                #      的风控预算，不计数）----
                if not fatal_reason and not net_reason:
                    ctr = ip_req.setdefault(identity, {"n": 0, "since": 0})
                    ctr["n"] += 1
                    ctr["since"] += 1
                    db.ip_stat_request(identity, ok=bool(
                        info is not None and not block_reason))
                    set_status(ip_n=ctr["n"])
                if info is not None and not fatal_reason \
                        and not net_reason and not block_reason:
                    consecutive_fail = 0  # 抓到了，连续失败清零
                    break

                # ---- 浏览器进程死亡/被服务端关闭：与风控无关，
                #      直接重启浏览器重试（走网络故障同一条退避路径）----
                if fatal_reason:
                    net_reason = f"浏览器会话终止（{fatal_reason}）"

                # ---- 网络/代理层错误：与风控无关，不计入风控连续失败计数 ----
                if net_reason:
                    net_retried += 1
                    if net_retried > args.net_retry:
                        phrase = task.on_giveup(
                            db, item, net_reason, "net", wctx,
                            set_status, log)
                        board.log(f"{tag}   [X] 网络故障重试 "
                                  f"{args.net_retry} 次仍失败，{phrase}"
                                  f"（{net_reason}）")
                        info = None
                        break
                    backoff = min(30 * net_retried, 180)
                    board.log(f"{tag} ⚠ 网络/代理故障（{net_reason}），"
                              f"不计入风控计数，第 {net_retried}/{args.net_retry} "
                              f"次重试（{backoff}s 后）...")
                    if args.proxy:
                        try:
                            browser, page, identity, req_proxies = \
                                relaunch_browser(
                                    board, tag, worker_id, args, db,
                                    proxy_server, browser, ctx, identity,
                                    stop, seed_kit=kit)
                            ctx = page.context
                            warm = True  # 新会话重新冷启动软着陆
                        except RuntimeError as e:
                            board.log(f"{tag} [X] 原通道重启浏览器失败: {e}，"
                                      f"中止整个任务")
                            stop.set()
                            return
                    if wait_countdown(board, worker_id, stop, backoff,
                                      "网络故障退避"):
                        return  # 用户中断
                    continue  # 重试同一任务项

                # ---- 抓取失败或疑似被风控拦截 ----
                consecutive_fail += 1
                reason = block_reason or "页面加载失败（疑似风控拦截）"
                # 记录该出口 IP 的风控遭遇（评估代理 IP 质量用）；
                # 登录墙是更高一级的风控（会话被要求强制登录）：
                # 无头模式下原地休息/手动滑块都无意义，直接进修复换 IP
                # 阶段；有头模式下给用户手动登录消除风险的机会
                # （走 block_stage==0 的等待手动验证分支，页面仍停在
                # 登录页，wait_manual_unblock 每 30s 轮询页面状态，
                # 登录成功跳回目标页即检测到）
                login_wall = "login.1688.com" in reason
                ctr = ip_req.setdefault(identity, {"n": 0, "since": 0})
                since = ctr["since"]  # 距上次触发已爬多少个请求（触发阈值样本）
                db.record_ip_event(
                    identity,
                    "block_login" if login_wall else
                    ("block_slider" if block_reason else "block_other"),
                    reason, req_since_block=since)
                db.ip_stat_block(identity)
                ctr["since"] = 0  # 重新累计「距上次触发」的安全请求数
                board.log(f"{tag}   [tmd] 出口 {identity} 在 {since} 次请求后"
                          f"触发反爬（本 IP 累计 {ctr['n']} 次请求）")
                if kit and since <= 2:
                    # 首请求即被拦：记到种子头上。同一熟身份在多个新鲜
                    # IP 上都被秒拦，说明被标记的是身份而非 IP ——
                    # 判定种子烧毁，停止播种，退回白板会话
                    kit_burn_ips.add(identity)
                    if len(kit_burn_ips) >= 2:
                        board.log(f"{tag}   [!] 种子身份「{kit['name']}」已在 "
                                  f"{len(kit_burn_ips)} 个新鲜 IP 上首请求即被拦，"
                                  f"疑似已被风控标记，本 worker 停止播种，"
                                  f"后续按白板会话处理（换种子文件可恢复）")
                        kit = None
                if login_wall and block_stage == 0:
                    if args.headed:
                        board.log(f"{tag} ⚠ 触发登录墙（{reason}）"
                                  f" → 有头模式，可在 {identity} 的窗口里"
                                  f"手动登录消除风险（登录态 Cookie 会写回"
                                  f"该 IP 名下，本 IP 有效期内复用）")
                    else:
                        block_stage = 1
                        board.log(f"{tag} ⚠ 触发登录墙（{reason}），出口 "
                                  f"{identity} 已被高风险标记，"
                                  f"不原地休息，直接修复换 IP")
                if consecutive_fail >= args.max_consecutive_fail:
                    board.log(f"{tag} [X] 已连续失败 {consecutive_fail} 次"
                              f"（最近一次: {reason}），判定被风控，中止整个任务")
                    extra = task.on_abort(item)
                    if extra:
                        board.log(f"{tag}     {extra}")
                    stop.set()
                    return  # finally 会保存 Cookie、关闭浏览器

                if block_stage == 0:
                    # 第一次被风控：不换 IP，当前 IP 上长时间休息后再试
                    block_stage = 1
                    rest = random.uniform(args.block_rest_min,
                                          args.block_rest_max)
                    board.log(f"{tag} ⚠ {reason}（连续失败 "
                              f"{consecutive_fail}/{args.max_consecutive_fail}）"
                              f" → 保持当前 IP {identity}，"
                              f"休息 {rest / 60:.1f} 分钟后重试")
                    if args.headed:
                        # 有头模式：优先等用户手动过滑块/登录，过了立即继续，
                        # 并把新下发的 x5sec/登录态 Cookie 写回该出口 IP 名下
                        board.log(f"{tag}   👉 请在 {identity} 的浏览器窗口里"
                                  f"手动完成验证/登录，脚本每 30s 自动检测"
                                  f"（最长 {rest / 60:.1f} 分钟）...")
                        if wait_manual_unblock(board, worker_id, stop,
                                               page, rest):
                            board.log(f"{tag} ✓ 检测到验证已通过，"
                                      f"Cookie 写回 {identity}，立即继续采集")
                            try:
                                save_cookies(db, identity, ctx)
                            except Exception as e:
                                board.log(f"{tag}   [!] Cookie 回写失败: {e}")
                            continue  # 同一 IP 重试同一任务项
                        if stop.is_set():
                            return
                        board.log(f"{tag}   未检测到手动验证通过，"
                                  f"按原计划休息后重试")
                    if wait_countdown(board, worker_id, stop, rest,
                                      f"风控休息(1)"):
                        return  # 用户中断
                    continue  # 同一 IP 重试同一任务项

                if block_stage == 1:
                    # 休息后仍被风控 → 修复：重启浏览器拿新出口 IP。
                    # 青果 IP 时效 30 分钟，此时旧 IP 通常已过期轮换，
                    # launch_browser 会按新 IP 重新配对 Cookie。
                    block_stage = 2
                    board.log(f"{tag} ⚠ 休息后仍被风控（{reason}）"
                              f" → 修复：重启浏览器获取新出口 IP 并重新配对 Cookie")
                    old_identity = identity
                    try:
                        browser, page, identity, req_proxies = \
                            relaunch_browser(
                                board, tag, worker_id, args, db,
                                proxy_server, browser, ctx, identity,
                                stop, seed_kit=kit)
                        ctx = page.context
                        warm = True  # 新会话重新冷启动软着陆
                    except RuntimeError as e:
                        board.log(f"{tag} [X] 修复换 IP 失败: {e}，中止整个任务")
                        stop.set()
                        return
                    if args.proxy and identity == old_identity:
                        # 出口还没轮换（休息不足 30 分钟）：再等一轮让青果轮换
                        rest = random.uniform(args.block_rest_min,
                                              args.block_rest_max)
                        board.log(f"{tag}   [!] 出口 IP 尚未轮换（青果 30 分钟时效），"
                                  f"再休息 {rest / 60:.1f} 分钟等其过期后重试")
                        if args.headed:
                            # 有头模式：等轮换期间轮询用户是否手动登录
                            # （此时页面在新会话首页，靠 Cookie 增量检测），
                            # 登录成功立即继续，不必等轮换
                            board.log(f"{tag}   👉 等轮换期间你也可以在 "
                                      f"{identity} 的窗口里手动登录，脚本每 30s "
                                      f"检测 Cookie（登录成功立即继续）...")
                            if wait_manual_login(board, worker_id, stop,
                                                 ctx, rest):
                                board.log(f"{tag} ✓ 检测到已手动登录，"
                                          f"登录态 Cookie 写回 {identity}，"
                                          f"不等轮换立即继续采集")
                                try:
                                    save_cookies(db, identity, ctx)
                                except Exception as e:
                                    board.log(f"{tag}   [!] Cookie 回写失败: {e}")
                                continue  # 同一 IP 重试同一任务项
                            if stop.is_set():
                                return
                            board.log(f"{tag}   未检测到手动登录，"
                                      f"按原计划重启浏览器绑定新 IP")
                        elif wait_countdown(board, worker_id, stop, rest,
                                            "等 IP 轮换"):
                            return
                        try:
                            browser, page, identity, req_proxies = \
                                relaunch_browser(
                                    board, tag, worker_id, args, db,
                                    proxy_server, browser, ctx, identity,
                                    stop, seed_kit=kit)
                            ctx = page.context
                            warm = True  # 新会话重新冷启动软着陆
                        except RuntimeError as e:
                            board.log(f"{tag} [X] 二次修复仍失败: {e}，"
                                      f"中止整个任务")
                            stop.set()
                            return
                    continue  # 新 IP + 新 Cookie 重试同一任务项

                # 修复换 IP 后仍失败：放弃当前任务项，继续下一个
                phrase = task.on_giveup(db, item, reason, "block", wctx,
                                        set_status, log)
                board.log(f"{tag}   [X] 休息与修复后仍失败，{phrase}"
                          f"（{reason}）")
                info = None
                break

            if info is not None:
                done_in_batch += task.on_success(
                    db, item, info, wctx, set_status, log)
                # 每次成功后把浏览器里的最新 Cookie（含可能轮换的 x5sec、
                # 以及手动过证后新签发的安全 Cookie）写回该出口 IP 名下 ——
                # 进程意外退出也不丢信任链，同 IP 复访直接复用
                try:
                    save_cookies(db, identity, ctx)
                except Exception:
                    pass
            else:
                # 放弃的任务项是否计入批次配额由任务层决定
                # （联系人：failed 店铺计 1；类目页：页码未前进不计）
                done_in_batch += task.giveup_cost(item)

            # 当前任务项处理完毕（含放弃），任务层收尾（如释放类目占用）
            task.after_item(item, wctx)

            # 样本之间的随机间隔（防风控）；各 worker 按编号递增基准
            # 间隔，避免多 worker 同频齐步请求形成集群特征
            lo = args.sample_min + worker_id * 1.5
            hi = args.sample_max + worker_id * 2.5
            t = random.uniform(lo, hi)
            set_status(state=f"{task.unit}间隔 {t:.1f}s")
            if stop.wait(t):
                return
            # 每隔一定轮次随机长休息一次，模拟真人连续浏览后的停顿
            n_rest = task.rest_counter(stats)
            if (args.rest_every > 0 and n_rest > 0
                    and n_rest % args.rest_every == 0
                    and not stop.is_set()):
                t = random.uniform(args.rest_min, args.rest_max)
                board.log(f"{tag} ☕ 已连续抓取 {n_rest} 个{task.unit}，"
                          f"随机长休息 {t / 60:.1f} 分钟 ...")
                if wait_countdown(board, worker_id, stop, t, "长休息"):
                    return  # 用户中断
    except Exception as e:
        board.log(f"{tag} [X] worker 异常退出: {e}")
    finally:
        # 退出前把浏览器里的最新 Cookie（含新 x5sec）写回该出口 IP 名下
        if ctx is not None:
            try:
                save_cookies(db, identity, ctx)
            except Exception as e:
                board.log(f"{tag}   [!] Cookie 回写失败: {e}")
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        set_status(state="已退出", force=True)
        with lock:
            state["stats"][worker_id] = stats
        db.close()


# ---------- 引擎：CLI 参数与 main 编排 ----------

def add_common_args(ap):
    """添加所有任务共享的网络层 CLI 参数（任务层自己加 -n 等业务参数）。"""
    ap.add_argument("--batch-rest", type=float, default=900,
                    help="每批采满后的强制休息秒数（默认 900=15 分钟，±10%% 抖动）")
    ap.add_argument("--max-batches", type=int, default=0,
                    help="每个 worker 最多采集多少批（默认 0=不限）")
    ap.add_argument("--ip-retry", type=int, default=3,
                    help="重启浏览器获取新出口 IP 的重试次数（默认 3）")
    ap.add_argument("--block-rest-min", type=float, default=600,
                    help="风控后保持当前 IP 的休息时长下限秒数（默认 600=10 分钟）")
    ap.add_argument("--block-rest-max", type=float, default=900,
                    help="风控后保持当前 IP 的休息时长上限秒数（默认 900=15 分钟）")
    ap.add_argument("--net-retry", type=int, default=5,
                    help="单个任务项遇到网络/代理层错误（隧道断开等，非风控）"
                         "时的重试次数（默认 5，不计入风控连续失败计数）")
    ap.add_argument("--max-consecutive-fail", type=int, default=5,
                    help="连续失败多少次后判定被风控并中止整个任务（默认 5）")
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感）")
    ap.add_argument("--rest-every", type=int, default=20,
                    help="每个 worker 每完成多少个单位后长休息一次"
                         "（默认 20，0 关闭）")
    ap.add_argument("--sample-min", type=float, default=13.0,
                    help="样本之间随机间隔的下限秒数（默认 13）")
    ap.add_argument("--sample-max", type=float, default=20.0,
                    help="样本之间随机间隔的上限秒数（默认 20）")
    ap.add_argument("--rest-min", type=float, default=60,
                    help="长休息随机时长的下限秒数（默认 60）")
    ap.add_argument("--rest-max", type=float, default=180,
                    help="长休息随机时长的上限秒数（默认 180）")
    ap.add_argument("--stagger-min", type=float, default=15.0,
                    help="worker 启动错开的最小秒数（默认 15；多会话同分钟出生、"
                         "同节奏访问是集群特征，启动时间必须打散）")
    ap.add_argument("--stagger-max", type=float, default=60.0,
                    help="worker 启动错开的最大秒数（默认 60）")
    ap.add_argument("--proxy", action="store_true",
                    help="走 util/proxy_qingguo.py 的青果住宅代理；"
                         "Cookie 按出口 IP 存 SQLite（记录过期时间），"
                         "退出时自动把最新 Cookie 写回该 IP 名下")
    ap.add_argument("--seeds", type=str,
                    default=str(ROOT_DIR / ".cache" / "seeds"),
                    help="种子身份池目录（默认 .cache/seeds，每份熟身份一个 "
                         "CDP 导出的 json）；代理模式下 worker 一对一独占认领，"
                         "只种设备绑定 Cookie、指纹按种子固定；"
                         "种子数少于 worker 数时多余 worker 按白板会话启动")
    ap.add_argument("--seed-x5sec", action="store_true",
                    help="x5sec 免滑块实验：偶数 worker 的种子保留未过期的 "
                         "x5sec/x5secdata（A 组），奇数 worker 不含（B 组对照），"
                         "用巡检报告的 gap=1 比例判定 x5sec 是否绑设备")
    ap.add_argument("--channels", type=int, default=0,
                    help="青果通道池大小（默认取 proxy_qingguo.CONFIG['channels']）")
    ap.add_argument("--workers", type=int, default=0,
                    help="并发 worker 数；代理模式默认=通道数，直连模式默认 1")
    return ap


def run_workers(args, task: FetchTask) -> int:
    """引擎 main 编排：通道分配 → 状态板 → 信号处理 → 错开启动 → 汇总。

    任务层在自己的 main() 里：解析参数（含 add_common_args）→
    task.prepare(args) → 返回 run_workers(args, task)。
    """
    # ---- 并发度与通道分配（一 worker 一通道，IP + Cookie 配套）----
    proxy_servers: list = [None]
    if args.proxy:
        sys.path.insert(0, str(ROOT_DIR / "util"))
        import proxy_qingguo
        pool = proxy_qingguo.get_pool(args.channels or None)
        n_channels = len(pool.servers())
        workers = args.workers or n_channels
        if workers > n_channels:
            print(f"[!] workers({workers}) > 通道数({n_channels})，"
                  f"部分 worker 将共用通道（共享出口 IP），不建议")
        # 轮询取通道：workers <= 通道数时每个 worker 独占一个通道
        proxy_servers = [pool.acquire() for _ in range(workers)]
    else:
        workers = args.workers or 1
        proxy_servers = [None] * workers
        if workers > 1:
            print(f"[!] 直连模式多 worker 共用本机 IP 和同一份 Cookie，"
                  f"可能触发风控；建议 --proxy 走多通道")

    # 种子身份池：每个 worker 独占认领一份熟身份（一对一，避免同一身份
    # 多 IP 并发的 Cookie 重放特征）；种子不足时多余 worker 白板启动。
    # --seed-x5sec：A/B 实验，偶数 worker 用含 x5sec 的种子（A 组），
    # 奇数 worker 用不含的（B 组对照），同一批种子两种过滤口径
    seed_kits = load_seed_kits(args.seeds) if args.proxy else []
    seed_kits_x5 = (load_seed_kits(args.seeds, keep_x5sec=True)
                    if args.proxy and args.seed_x5sec else [])
    if args.proxy:
        if seed_kits:
            print(f"[seed] 种子身份池 {len(seed_kits)} 份: "
                  f"{', '.join(k['name'] for k in seed_kits)}")
            if workers > len(seed_kits):
                print(f"[!] worker 数({workers}) > 种子数({len(seed_kits)})，"
                      f"超出部分按白板会话启动（建议种子数 ≥ worker 数）")
            if args.seed_x5sec:
                n_x5 = sum(1 for k in seed_kits_x5 if k["x5sec"])
                print(f"[seed] --seed-x5sec 实验: 偶数 worker 为 A 组"
                      f"（含 x5sec，{n_x5}/{len(seed_kits_x5)} 份有有效 "
                      f"x5sec），奇数 worker 为 B 组对照（不含）")
        else:
            print(f"[seed] {args.seeds} 下没有可用种子身份，"
                  f"全部 worker 按白板会话启动")
    if args.seed_x5sec and seed_kits_x5:
        worker_kits = [
            (seed_kits_x5[i] if i % 2 == 0 else seed_kits[i])
            if i < len(seed_kits) else None
            for i in range(workers)]
    else:
        worker_kits = [seed_kits[i] if i < len(seed_kits) else None
                       for i in range(workers)]

    print(f"[2] 启动 {workers} 个 worker"
          f"（{'代理通道: ' + ', '.join(proxy_servers) if args.proxy else '直连'}）")

    # ---- 状态板：common 内部日志按线程标签路由进来 ----
    board = StatusBoard(workers, compose=task.compose)

    def _sink(tag: str, msg: str):
        """common 内部日志路由：错误/警告进滚动日志，常规细节进状态行。"""
        text = (msg or "").strip()
        if not text:
            return
        m = re.match(r"\[w(\d+)\]", tag or "")
        if "[X]" in text or "[!]" in text or "[license]" in text:
            board.log(f"{tag} {text}" if tag else text)
        elif m and int(m.group(1)) < workers:
            board.set(int(m.group(1)), detail=text[:80])
        else:
            board.log(f"{tag} {text}" if tag else text)

    set_log_sink(_sink)
    board.start()

    state = {"stats": {}}
    lock = threading.Lock()
    stop = threading.Event()

    # 直接关终端窗口(SIGHUP)或被 kill(SIGTERM)时也走正常清理流程：
    # 各 worker 关闭浏览器，服务端会话租约立即释放，
    # 否则残留租约要等 ~10 分钟才过期，会堵住下次启动的席位
    import signal

    def _graceful_exit(signum, frame):
        board.log(f"[!] 收到信号 {signum}，通知各 worker 清理后退出...")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _graceful_exit)
        except (OSError, ValueError):
            pass  # 平台不支持该信号时跳过

    threads = [
        threading.Thread(target=_engine_worker,
                         args=(i, args, task, proxy_servers[i],
                               worker_kits[i], board,
                               state, lock, stop),
                         name=f"worker-{i}", daemon=True)
        for i in range(workers)
    ]
    for i, t in enumerate(threads):
        t.start()
        if i < len(threads) - 1:
            # 启动时间打散（默认 15~60s/个）：多会话同一分钟内出生、
            # 同一节奏访问同一端点，是风控识别爬虫集群的强特征
            d = random.uniform(args.stagger_min, args.stagger_max)
            print(f"    错开启动：{d:.0f}s 后启动下一个 worker ...")
            time.sleep(d)

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        board.log("[!] 用户中断，等待各 worker 完成当前任务后退出...")
        stop.set()
        for t in threads:
            t.join(timeout=90)
        board.log("[!] 进度已保存，下次运行自动续爬")

    print(f"[OK] {task.summary(state['stats'])}")
    return 0
