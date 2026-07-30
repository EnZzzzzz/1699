#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
青果网络 - 国内长效代理（动态）使用示例

产品信息（订单 20260730304442，业务标识 unfbsqwi）：
    - 产品类型: 国内-长效代理-动态-10Mbps
    - 存活周期: 30 分钟（出口 IP 每 30 分钟自动轮换一次，无需重新提取）
    - 提取方式: 通道提取，通道数 1 个
    - 隧道转发: 支持（/get 返回的是隧道入口 host:port，连上后由隧道转发到当前出口 IP）

工作原理：
    1. 调用 /get 接口提取代理，得到隧道入口 server（如 tunpool-xxx.qg.net:端口）；
    2. 用 Authkey:Authpwd 作为代理账密连接该入口；
    3. 30 分钟存活周期到期后，青果后台自动把该通道切换到新的出口 IP，
       隧道入口和账密不变，代码无需重新提取（入口失效时可再调 /get 刷新）；
    4. 提取到的隧道入口和过期时间会持久化到 .cache/qingguo_tunnel.json，
       脚本重启后直接复用，过期或失效才重新提取。

必要依赖:
    pip install requests

参考文档:
    - 长效代理-API接口介绍: https://www.qg.net/doc/2143.html
    - 长效代理-提取IP接口: https://www.qg.net/doc/1863.html
    - 长效代理-查询在用IP: https://www.qg.net/doc/1861.html
    - 接口错误码: https://www.qg.net/list/117.html
"""

import json
import os
import sys
import time

import requests


# ==================== 青果网络业务密钥（用户中心 > 代理IP > 按时业务） ====================
CONFIG = {
    # API 公共参数 key，即后台的 Authkey（产品唯一标识）
    "key": "C29CFA1A",
    # 代理账密：用户名 = Authkey，密码 = Authpwd
    "auth_key": "C29CFA1A",
    "auth_pwd": "9588C47B4A82",

    # 长效代理 API 域名
    "api_base": "https://longterm.proxy.qg.net",

    # 提取参数（可选）：地区 / 运营商
    "area": "",        # 按地区提取，如 "河北"，留空不筛选
    "isp": 0,          # 0: 不筛选  1: 电信  2: 移动  3: 联通

    # 测试目标地址
    "test_url": "https://ipinfo.io/json",
}
# =====================================================================

# 出口 IP 存活周期（秒）：30 分钟，到期后认为缓存的隧道入口需要刷新
IP_TTL_SECONDS = 30 * 60

# 隧道入口持久化缓存文件（.cache/qingguo_tunnel.json），脚本重启后仍可复用
CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".cache",
    "qingguo_tunnel.json",
)


def _load_tunnel_cache() -> dict:
    """从 .cache 读取缓存的隧道入口，返回 {server, fetched_at, expire_at} 或 None"""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if cache.get("server") and cache.get("expire_at", 0) > time.time():
            return cache
    except (OSError, ValueError):
        pass
    return None


def _save_tunnel_cache(server: str):
    """把隧道入口和过期时间（提取时间 + 30 分钟存活周期）写入 .cache"""
    now = time.time()
    cache = {
        "server": server,
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


def get_proxy(area: str = None, isp: int = None, num: int = 1, use_cache: bool = True) -> list:
    """
    提取IP（/get 接口），返回隧道入口列表，如 ["tunpool-xxx.qg.net:29629"]。

    注意：动态型长效代理每个通道同时只占用一个出口 IP；
    返回的 server 是隧道入口，真正的出口 IP 由青果每 30 分钟自动轮换。
    请求频率限制: (通道数*5+10) 次/分钟。
    """
    if use_cache:
        cache = _load_tunnel_cache()
        if cache:
            return [cache["server"]]

    try:
        res = _api_get("/get", {
            "area": CONFIG["area"] if area is None else area,
            "isp": CONFIG["isp"] if isp is None else isp,
            "num": num,
        })
    except QingGuoException as e:
        # 动态型长效代理不支持手动释放，通道被占用时（NO_AVAILABLE_CHANNEL）
        # 回退到 /query 取当前通道在用的隧道入口
        if e.code != "NO_AVAILABLE_CHANNEL":
            raise
        inuse = query_inuse_ips() or []
        servers = [item["server"] for item in inuse if item.get("server")]
        if not servers:
            raise
        _save_tunnel_cache(servers[0])
        return servers

    data = res.get("data") or []
    servers = [item["server"] for item in data if item.get("server")]
    if not servers:
        raise QingGuoException("NO_SERVER", f"提取结果为空: {res}", res.get("request_id"))

    _save_tunnel_cache(servers[0])
    return servers


def query_inuse_ips(task: str = None) -> dict:
    """
    查询在用IP资源（/query 接口），返回 data 字段（提取批次列表）。
    task: 可选，按提取批次筛选，多批次用逗号隔开。
    频率限制: 60 次/分钟。
    """
    res = _api_get("/query", {"task": task})
    return res.get("data")


def query_channels() -> dict:
    """查询通道数（/channels 接口），返回通道总数/已用数等信息"""
    res = _api_get("/channels", {})
    return res.get("data")


def query_resource_areas() -> dict:
    """查询可提取的资源地区（/resources 接口）"""
    res = _api_get("/resources", {})
    return res.get("data")


def make_proxies(server: str = None, refresh: bool = False) -> dict:
    """
    构造 requests 可用的 proxies 字典（账密验证）。
    server 为空时自动通过 /get 提取（优先用缓存的隧道入口）；
    refresh=True 强制重新提取。
    """
    if not server:
        server = get_proxy(use_cache=not refresh)[0]

    proxy_url = "http://%(user)s:%(pwd)s@%(proxy)s/" % {
        "user": CONFIG["auth_key"],
        "pwd": CONFIG["auth_pwd"],
        "proxy": server,
    }
    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def test_requests_proxy(proxies: dict = None, url: str = None, retry_on_fail: bool = True) -> requests.Response:
    """使用代理发起一个测试请求；失败时自动重新提取隧道入口重试一次"""
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
        print(f"[test_requests_proxy] 请求失败({e})，重新提取隧道入口后重试...")
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

    # 1. 提取隧道入口
    servers = get_proxy(use_cache=False)
    print(f"[get_proxy] 提取到隧道入口: {servers}")

    # 2. 查询在用IP
    try:
        inuse = query_inuse_ips()
        print(f"[query_inuse_ips] 在用资源: {inuse}")
    except QingGuoException as e:
        print(f"[query_inuse_ips] 查询失败: {e}")

    # 3. 跑一个 requests 测试
    test_requests_proxy()

    # 4. 如需用浏览器测试，取消下面注释（需安装 cloakbrowser）
    # test_cloakbrowser_proxy()


if __name__ == "__main__":
    main()
