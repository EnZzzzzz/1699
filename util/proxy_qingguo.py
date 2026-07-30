#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
青果网络 - 国内长效代理（动态）通道池

产品信息（订单 20260730304442，业务标识 unfbsqwi）：
    - 产品类型: 国内-长效代理-动态-10Mbps
    - 存活周期: 30 分钟（出口 IP 每 30 分钟自动轮换一次，无需重新提取）
    - 提取方式: 通道提取，通道数 5 个（CONFIG["channels"] 可配置）
    - 隧道转发: 支持（/get 返回的是隧道入口 host:port，连上后由隧道转发到当前出口 IP）

通道机制（按青果官方文档）：
    - 每个通道同时占用一个出口 IP，各通道独立地每 30 分钟轮换一次出口；
      5 个通道 = 同时持有 5 个隧道入口（server），各自背后是独立出口 IP。
    - /get?num=N 一次提取 N 个 IP，占用 N 个空闲通道（频率限制 通道数*5+10 次/分）；
    - 通道全部占用时再提取会报 NO_AVAILABLE_CHANNEL，
      此时用 /query（60 次/分）取回全部在用通道的隧道入口即可；
    - /channels 查询 {total, idle} 通道总数/空闲数。

工作原理：
    1. ChannelPool 启动时先读 .cache 缓存的隧道入口列表；
    2. 缓存过期则调 /query 取当前在用通道，不足 channels 个再调 /get 补齐；
    3. acquire() 轮询分发隧道入口 —— 连续获取得到的是不同通道，
       并发场景下每个 worker 取一个，即各自独占一个出口 IP；
    4. 隧道入口和账密不变，出口 IP 由青果每 30 分钟自动轮换，代码无需重新提取
       （入口失效时 refresh() 重新 /query 即可）。

必要依赖:
    pip install requests

参考文档:
    - 长效代理-API接口介绍: https://www.qg.net/doc/2143.html
    - 长效代理-提取IP接口: https://www.qg.net/doc/1863.html
    - 长效代理-查询在用IP: https://www.qg.net/doc/1861.html
    - 长效代理-查询通道数: https://www.qg.net/doc/1860.html
    - 接口错误码: https://www.qg.net/list/117.html
"""

import itertools
import json
import os
import sys
import threading
import time

import requests


# ==================== 青果网络业务密钥（用户中心 > 代理IP > 按时业务） ====================
CONFIG = {
    # API 公共参数 key，即后台的 Authkey（产品唯一标识）
    "key": "C29CFA1A",
    # 代理账密：用户名 = Authkey，密码 = Authpwd
    "auth_key": "C29CFA1A",
    "auth_pwd": "9588C47B4A82",

    # 通道数（购买的通道配额，决定同时持有几个独立出口 IP）
    "channels": 5,

    # 长效代理 API 域名
    "api_base": "https://longterm.proxy.qg.net",

    # 提取参数（可选）：地区 / 运营商
    "area": "",        # 按地区提取，如 "河北"，留空不筛选
    "isp": 0,          # 0: 不筛选  1: 电信  2: 移动  3: 联通

    # 测试目标地址
    "test_url": "https://ipinfo.io/json",
}
# =====================================================================

# 缓存复用周期（秒）：与出口 IP 30 分钟轮换周期对齐，
# 到期后重新 /query 校准通道列表（隧道入口本身不失效，仅作保守刷新）
IP_TTL_SECONDS = 30 * 60

# 隧道入口持久化缓存文件（.cache/qingguo_tunnel.json），脚本重启后仍可复用
CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".cache",
    "qingguo_tunnel.json",
)


def _load_tunnel_cache() -> dict:
    """从 .cache 读取缓存的隧道入口列表，返回 {servers, fetched_at, expire_at} 或 None。

    兼容旧版单入口缓存格式（{"server": "..."}）。
    """
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        servers = cache.get("servers") or ([cache["server"]] if cache.get("server") else [])
        if servers and cache.get("expire_at", 0) > time.time():
            cache["servers"] = servers
            return cache
    except (OSError, ValueError):
        pass
    return None


def _save_tunnel_cache(servers: list):
    """把隧道入口列表和过期时间（提取时间 + 30 分钟）写入 .cache"""
    now = time.time()
    cache = {
        "servers": list(servers),
        "fetched_at": now,
        "expire_at": now + IP_TTL_SECONDS,
        "fetched_at_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "expire_at_str": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(now + IP_TTL_SECONDS)
        ),
    }
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


class QingGuoException(Exception):
    def __init__(self, code=None, message=None, request_id=None):
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[QingGuoException] code: {code} message: {message} request_id: {request_id}")


def _api_get(path: str, params: dict) -> dict:
    """调用青果长效代理 API，统一处理错误码"""
    url = CONFIG["api_base"] + path
    params = {"key": CONFIG["key"], **{k: v for k, v in params.items() if v not in (None, "")}}
    r = requests.get(url, params=params, timeout=30)
    # 青果部分错误会以非 200 状态码返回，但 body 仍是 JSON（含 code/message）
    try:
        res = r.json()
    except ValueError:
        raise QingGuoException(r.status_code, r.text)
    if res.get("code") != "SUCCESS":
        raise QingGuoException(res.get("code"), res.get("message") or res.get("msg") or r.text, res.get("request_id"))
    return res


def query_inuse_ips(task: str = None) -> list:
    """
    查询在用IP资源（/query 接口），返回在用通道列表 [{server, distinct}, ...]。
    task: 可选，按提取批次筛选，多批次用逗号隔开。
    频率限制: 60 次/分钟。
    """
    res = _api_get("/query", {"task": task})
    return res.get("data") or []


def query_channels() -> dict:
    """查询通道数（/channels 接口），返回 {total, idle} 通道总数/空闲数"""
    res = _api_get("/channels", {})
    return res.get("data")


def query_resource_areas() -> dict:
    """查询可提取的资源地区（/resources 接口）"""
    res = _api_get("/resources", {})
    return res.get("data")


def _extract_servers(num: int, area: str = None, isp: int = None) -> list:
    """调 /get 提取 num 个隧道入口（占用 num 个空闲通道）。

    频率限制: (通道数*5+10) 次/分钟。
    通道占满时抛 NO_AVAILABLE_CHANNEL，由调用方决定回退策略。
    """
    res = _api_get("/get", {
        "area": CONFIG["area"] if area is None else area,
        "isp": CONFIG["isp"] if isp is None else isp,
        "num": num,
    })
    data = res.get("data") or []
    # 兼容两种返回结构：{"ips": [...]} 或直接 [...]
    if isinstance(data, dict):
        data = data.get("ips") or []
    servers = [item["server"] for item in data if item.get("server")]
    if not servers:
        raise QingGuoException("NO_SERVER", f"提取结果为空: {res}", res.get("request_id"))
    return servers


class ChannelPool:
    """青果通道池：持有 channels 个隧道入口，轮询分发给并发调用方。

    解析顺序：.cache 缓存 -> /query 在用通道 -> /get 补齐不足部分。
    acquire() 轮询返回不同通道的 server，连续 N 次调用得到 N 个不同入口，
    并发 worker 各自 acquire 一次即独占一个出口 IP 通道。
    """

    def __init__(self, size: int = None):
        self.size = int(size or CONFIG["channels"])
        self._servers: list = []
        self._rr = itertools.count()  # 轮询游标
        self._lock = threading.Lock()

    def _resolve(self, force: bool = False) -> list:
        """确保通道列表就绪（线程安全）。force=True 跳过缓存重新校准。"""
        with self._lock:
            if not force and self._servers:
                return self._servers

            servers = []
            if not force:
                cache = _load_tunnel_cache()
                if cache:
                    servers = list(cache["servers"])

            if not servers:
                # 缓存缺失/过期：以青果后台的在用通道为准
                servers = [item["server"] for item in query_inuse_ips()
                           if item.get("server")]

            # 不足 channels 个时调 /get 补齐（占用空闲通道）
            if len(servers) < self.size:
                try:
                    servers += _extract_servers(self.size - len(servers))
                except QingGuoException as e:
                    # 通道已全部占用：以在用通道为准，有几条用几条
                    if e.code != "NO_AVAILABLE_CHANNEL":
                        raise

            if not servers:
                raise QingGuoException("NO_SERVER", "未获取到任何隧道入口")
            _save_tunnel_cache(servers)
            self._servers = servers
            return self._servers

    def servers(self) -> list:
        """返回全部隧道入口列表（必要时解析/补齐）。"""
        return list(self._resolve())

    def acquire(self) -> str:
        """轮询取一个隧道入口；连续调用依次得到不同通道。"""
        servers = self._resolve()
        with self._lock:
            return servers[next(self._rr) % len(servers)]

    def refresh(self) -> list:
        """隧道入口失效时强制重新校准（跳过缓存，/query 为准）。"""
        return list(self._resolve(force=True))

    def make_proxies(self, server: str = None) -> dict:
        """构造 requests 可用的 proxies 字典（账密验证）。

        server 为空时通过 acquire() 轮询取一个通道。
        """
        server = server or self.acquire()
        proxy_url = "http://%(user)s:%(pwd)s@%(proxy)s/" % {
            "user": CONFIG["auth_key"],
            "pwd": CONFIG["auth_pwd"],
            "proxy": server,
        }
        return {"http": proxy_url, "https": proxy_url}


# 默认全局池（CONFIG["channels"] 大小），调用方可用 ChannelPool(size) 自建
_default_pool = None
_default_pool_lock = threading.Lock()


def get_pool(size: int = None) -> ChannelPool:
    """取全局默认通道池；size 仅首次生效，之后沿用已建池的大小。"""
    global _default_pool
    with _default_pool_lock:
        if _default_pool is None:
            _default_pool = ChannelPool(size)
        return _default_pool


# ---------- 兼容旧接口 ----------

def get_proxy(area: str = None, isp: int = None, num: int = 1, use_cache: bool = True) -> list:
    """兼容旧调用：返回通道池中的隧道入口列表（最多 num 个）。

    新代码建议直接用 ChannelPool / get_pool()。
    """
    servers = get_pool().servers()
    return servers[:max(1, num)]


def make_proxies(server: str = None, refresh: bool = False) -> dict:
    """构造 requests 可用的 proxies 字典（账密验证）。

    server 为空时从通道池轮询取一个通道；refresh=True 强制重新校准通道列表。
    """
    pool = get_pool()
    if refresh:
        pool.refresh()
    return pool.make_proxies(server)


def test_requests_proxy(proxies: dict = None, url: str = None, retry_on_fail: bool = True) -> requests.Response:
    """使用代理发起一个测试请求；失败时强制刷新通道池后重试一次"""
    if proxies is None:
        proxies = make_proxies()
    url = url or CONFIG["test_url"]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        # 动态代理出口会轮换，关闭 keep-alive 避免连接复用导致出口不切换
        "Connection": "close",
        "Accept-Encoding": "gzip",
    }

    print(f"[test_requests_proxy] 正在通过代理访问: {url}")
    print(f"[test_requests_proxy] proxies: {proxies}")

    try:
        resp = requests.get(url, proxies=proxies, headers=headers, timeout=30)
    except requests.RequestException as e:
        if not retry_on_fail:
            raise
        print(f"[test_requests_proxy] 请求失败({e})，重新校准通道池后重试...")
        proxies = make_proxies(refresh=True)
        print(f"[test_requests_proxy] proxies: {proxies}")
        resp = requests.get(url, proxies=proxies, headers=headers, timeout=30)

    print(f"[test_requests_proxy] status: {resp.status_code}")
    print(f"[test_requests_proxy] body:\n{resp.text}\n")
    return resp


def test_cloakbrowser_proxy(proxies: dict = None, url: str = None):
    """
    如果你安装了 cloakbrowser，可以用这个函数让浏览器也走青果代理。
    需要先: pip install cloakbrowser
    """
    try:
        from cloakbrowser import launch
    except ImportError as e:
        print("[test_cloakbrowser_proxy] 未安装 cloakbrowser，跳过。pip install cloakbrowser")
        raise e

    if proxies is None:
        proxies = make_proxies()

    url = url or CONFIG["test_url"]
    proxy_url = proxies["https"]  # cloakbrowser 需要完整的代理 URL

    print(f"[test_cloakbrowser_proxy] 启动 cloakbrowser，代理: {proxy_url}")
    browser = launch(
        headless=False,
        humanize=True,
        proxy=proxy_url,
        geoip=True,
    )
    page = browser.new_page()
    page.goto(url, wait_until="networkidle")
    print(f"[test_cloakbrowser_proxy] title: {page.title()}")
    browser.close()


def main():
    # 0. 检查配置
    if not CONFIG["key"] or not CONFIG["auth_pwd"]:
        print("请先编辑 proxy_qingguo.py 顶部的 CONFIG，填入 Authkey / Authpwd")
        sys.exit(1)

    # 1. 查询通道配额
    try:
        ch = query_channels()
        print(f"[query_channels] 通道总数 {ch.get('total')}，空闲 {ch.get('idle')}"
              f"（池配置 channels={CONFIG['channels']}）")
    except QingGuoException as e:
        print(f"[query_channels] 查询失败: {e}")

    # 2. 解析通道池（缓存 -> /query -> /get 补齐）
    pool = get_pool()
    servers = pool.servers()
    cache = _load_tunnel_cache()
    if cache:
        print(f"[pool] 隧道入口 {len(servers)} 个（缓存过期时间: {cache['expire_at_str']}）:")
    else:
        print(f"[pool] 隧道入口 {len(servers)} 个:")
    for i, s in enumerate(servers):
        print(f"    通道{i}: {s}")

    # 3. 逐通道查询出口 IP（每个通道是独立出口）
    for i, s in enumerate(servers):
        proxies = pool.make_proxies(s)
        try:
            r = requests.get(CONFIG["test_url"], proxies=proxies,
                             headers={"Connection": "close"}, timeout=30)
            ip = r.json().get("ip", "?")
            print(f"    通道{i} 出口 IP: {ip}")
        except Exception as e:
            print(f"    通道{i} 出口 IP 查询失败: {e}")

    # 4. 跑一个 requests 测试（轮询取通道）
    test_requests_proxy()

    # 5. 如需用浏览器测试，取消下面注释（需安装 cloakbrowser）
    # test_cloakbrowser_proxy()


if __name__ == "__main__":
    main()
