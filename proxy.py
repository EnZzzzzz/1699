#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快代理隧道代理使用示例

用法:
    1. 把你的 tunnel host:port、用户名、密码填到下面 CONFIG 里，直接跑测试请求；
    2. 或者把 SecretId/SecretKey 填到 CONFIG 里，通过 API 拉取 tunnel host:port。

必要依赖:
    pip install requests

参考文档:
    - 获取隧道代理IP: https://www.kuaidaili.com/doc/api/gettps/
    - HTTP隧道代码样例: https://www.kuaidaili.com/doc/dev/sdk_tps_http/
    - API授权与验证: https://www.kuaidaili.com/doc/api/auth/
"""

import os
import sys
import json
import time
import base64
import hashlib
import hmac
from urllib.parse import quote

import requests


# ==================== 请在这里填写你的快代理订单信息 ====================
CONFIG = {
    # 方式一：直接在快代理后台订单详情里复制 tunnel host:port 和用户名密码
    "tunnel": "i361.kdltps.com:15818",   # 例如 tps121.kdlapi.com:15818
    "username": "t18533893502192",       # 隧道代理用户名
    "password": "26yqmrl8",              # 隧道代理密码

    # 方式二：通过 API 获取 tunnel host:port（需要订单 API 密钥）
    # 如果上面的 tunnel 已填好，可以忽略下面两项
    "secret_id": "t18533893502192",
    "secret_key": "26yqmrl8",

    # 测试目标地址
    "test_url": "https://dev.kdlapi.com/testproxy",
}
# =====================================================================


class KdlException(Exception):
    def __init__(self, code=None, message=None):
        self.code = code
        self.message = message
        super().__init__(f"[KdlException] code: {code} message: {message}")


def _get_secret_token(secret_id: str, secret_key: str) -> tuple:
    """调用 auth.kdlapi.com 获取密钥令牌，返回 (secret_token, expire_seconds, timestamp)"""
    url = "https://auth.kdlapi.com/api/get_secret_token"
    r = requests.post(url, data={"secret_id": secret_id, "secret_key": secret_key}, timeout=30)
    if r.status_code != 200:
        raise KdlException(r.status_code, r.text)
    res = r.json()
    if res.get("code") != 0:
        raise KdlException(res.get("code"), res.get("msg"))
    data = res["data"]
    return data["secret_token"], data["expire"], time.time()


def _cached_secret_token(secret_id: str, secret_key: str, cache_path: str = ".kdl_secret_token") -> str:
    """带本地缓存的 secret_token 获取，快过期前自动刷新"""
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                token, expire, ts, cached_id = f.read().strip().split("|")
            if cached_id == secret_id and float(ts) + float(expire) - 3 * 60 > time.time():
                return token
        except Exception:
            pass

    token, expire, ts = _get_secret_token(secret_id, secret_key)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(f"{token}|{expire}|{ts}|{secret_id}")
    return token


def _hmac_signature(secret_id: str, secret_key: str, endpoint: str, params: dict) -> str:
    """hmacsha1 数字签名"""
    sorted_params = sorted(params.items())
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in sorted_params)
    raw = f"GET{endpoint}?{query}"
    dig = hmac.new(secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(dig).decode("utf-8")


def get_tunnel_proxy(
    secret_id: str = None,
    secret_key: str = None,
    sign_type: str = "token",
    num: int = 1,
    fmt: str = "json",
) -> list:
    """
    通过 API 获取隧道代理 host:port 列表。
    返回值类似: ["tps121.kdlapi.com:15818"]
    """
    secret_id = secret_id or CONFIG["secret_id"]
    secret_key = secret_key or CONFIG["secret_key"]

    endpoint = "/api/gettps"
    url = f"https://tps.kdlapi.com{endpoint}"

    params = {
        "secret_id": secret_id,
        "num": num,
        "format": fmt,
    }

    if sign_type == "token":
        params["sign_type"] = "token"
        params["signature"] = _cached_secret_token(secret_id, secret_key)
    elif sign_type == "hmacsha1":
        params["sign_type"] = "hmacsha1"
        params["timestamp"] = int(time.time())
        params["signature"] = _hmac_signature(secret_id, secret_key, endpoint, params)
    else:
        raise ValueError("sign_type 只支持 token 或 hmacsha1")

    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise KdlException(r.status_code, r.text)

    if fmt == "json":
        res = r.json()
        if res.get("code") != 0:
            raise KdlException(res.get("code"), res.get("msg"))
        return res["data"]["proxy_list"]

    # text 格式
    text = r.text.strip()
    if text.startswith("ERROR"):
        raise KdlException(None, text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def make_proxies(tunnel: str = None, username: str = None, password: str = None) -> dict:
    """
    构造 requests 可用的 proxies 字典。
    如果未提供 tunnel，会尝试用 API 拉取。
    """
    tunnel = tunnel or CONFIG["tunnel"]
    username = username or CONFIG["username"]
    password = password or CONFIG["password"]

    # tunnel 没填或还是占位符，尝试 API
    if not tunnel or tunnel.startswith("xxx.") or tunnel.startswith("your_"):
        proxies_list = get_tunnel_proxy()
        tunnel = proxies_list[0]
        print(f"[API] 获取到 tunnel: {tunnel}")

    proxy_url = "http://%(user)s:%(pwd)s@%(proxy)s/" % {
        "user": username,
        "pwd": password,
        "proxy": tunnel,
    }
    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def test_requests_proxy(proxies: dict = None, url: str = None) -> requests.Response:
    """使用隧道代理发起一个测试请求"""
    if proxies is None:
        proxies = make_proxies()
    url = url or CONFIG["test_url"]

    # 建议关闭 keep-alive，避免连接复用导致隧道不能切换出口 IP
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Connection": "close",
        "Accept-Encoding": "gzip",
    }

    print(f"[test_requests_proxy] 正在通过代理访问: {url}")
    print(f"[test_requests_proxy] proxies: {proxies}")

    resp = requests.get(url, proxies=proxies, headers=headers, timeout=30)
    print(f"[test_requests_proxy] status: {resp.status_code}")
    print(f"[test_requests_proxy] body:\n{resp.text}\n")
    return resp


def test_cloakbrowser_proxy(proxies: dict = None, url: str = None):
    """
    如果你安装了 cloakbrowser，可以用这个函数让浏览器也走隧道代理。
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
    # 检查配置是否还是占位符
    placeholders = ["your_tunnel_username", "your_tunnel_password", "your_secret_id", "your_secret_key"]
    if any(CONFIG.get(k, "").startswith("your_") or CONFIG.get(k, "") == "" for k in ["tunnel", "username", "password"]):
        # 如果 tunnel/用户名/密码没填，必须有 secret_id/secret_key 通过 API 拉
        if CONFIG.get("secret_id", "").startswith("your_") or CONFIG.get("secret_key", "").startswith("your_"):
            print("请先编辑 proxy.py 顶部的 CONFIG，填入你的快代理 tunnel/用户名/密码 或 SecretId/SecretKey")
            sys.exit(1)

    # 1. 跑一个 requests 测试
    test_requests_proxy()

    # 2. 如需用浏览器测试，取消下面注释（需安装 cloakbrowser）
    # test_cloakbrowser_proxy()


if __name__ == "__main__":
    main()
