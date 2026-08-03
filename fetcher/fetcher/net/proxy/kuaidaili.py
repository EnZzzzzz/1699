# -*- coding: utf-8 -*-
"""快代理隧道代理（迁移自 util/proxy_kuaidaili.py，作为第二个厂商插件）。

单隧道产品：所有通道共用同一个隧道入口，出口由快代理侧切换。
requests 为延迟导入。

参考文档:
    - 获取隧道代理IP: https://www.kuaidaili.com/doc/api/gettps/
    - API授权与验证: https://www.kuaidaili.com/doc/api/auth/
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from pathlib import Path
from urllib.parse import quote

from fetcher.net.proxy.base import Channel

# ==================== 快代理订单信息 ====================
CONFIG = {
    # 方式一：直接在后台订单详情里复制 tunnel host:port 和用户名密码
    "tunnel": "i361.kdltps.com:15818",
    "username": "t18533893502192",
    "password": "26yqmrl8",

    # 方式二：通过 API 获取 tunnel host:port（需要订单 API 密钥）
    "secret_id": "t18533893502192",
    "secret_key": "26yqmrl8",

    # 测试目标地址
    "test_url": "https://dev.kdlapi.com/testproxy",
}
# =====================================================================

_TOKEN_CACHE_DEFAULT = Path(__file__).resolve().parents[4] / ".cache" / ".kdl_secret_token"


class KdlException(Exception):
    def __init__(self, code=None, message=None):
        self.code = code
        self.message = message
        super().__init__(f"[KdlException] code: {code} message: {message}")


def _get_secret_token(secret_id: str, secret_key: str) -> tuple:
    """调用 auth.kdlapi.com 获取密钥令牌（requests 延迟导入）。"""
    import requests

    url = "https://auth.kdlapi.com/api/get_secret_token"
    r = requests.post(url, data={"secret_id": secret_id, "secret_key": secret_key}, timeout=30)
    if r.status_code != 200:
        raise KdlException(r.status_code, r.text)
    res = r.json()
    if res.get("code") != 0:
        raise KdlException(res.get("code"), res.get("msg"))
    data = res["data"]
    return data["secret_token"], data["expire"], time.time()


def _cached_secret_token(secret_id: str, secret_key: str,
                         cache_path: Path = _TOKEN_CACHE_DEFAULT) -> str:
    """带本地缓存的 secret_token 获取，快过期前自动刷新。"""
    cache_path = Path(cache_path)
    if cache_path.exists():
        try:
            token, expire, ts, cached_id = cache_path.read_text(
                encoding="utf-8").strip().split("|")
            if cached_id == secret_id and float(ts) + float(expire) - 3 * 60 > time.time():
                return token
        except Exception:  # noqa: BLE001
            pass

    token, expire, ts = _get_secret_token(secret_id, secret_key)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(f"{token}|{expire}|{ts}|{secret_id}", encoding="utf-8")
    return token


def _hmac_signature(secret_id: str, secret_key: str, endpoint: str, params: dict) -> str:
    """hmacsha1 数字签名。"""
    sorted_params = sorted(params.items())
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in sorted_params)
    raw = f"GET{endpoint}?{query}"
    dig = hmac.new(secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(dig).decode("utf-8")


def get_tunnel_proxy(secret_id: str = None, secret_key: str = None,
                     sign_type: str = "token", num: int = 1,
                     fmt: str = "json") -> list:
    """通过 API 获取隧道代理 host:port 列表。"""
    import requests

    secret_id = secret_id or CONFIG["secret_id"]
    secret_key = secret_key or CONFIG["secret_key"]

    endpoint = "/api/gettps"
    url = f"https://tps.kdlapi.com{endpoint}"

    params = {"secret_id": secret_id, "num": num, "format": fmt}

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

    text = r.text.strip()
    if text.startswith("ERROR"):
        raise KdlException(None, text)
    return [line.strip() for line in text.splitlines() if line.strip()]


class KuaiDaiLiProvider:
    """快代理隧道 provider（ProxyProvider 协议实现）。

    单隧道产品：acquire() 始终返回同一隧道入口；并发 worker 会共用
    同一出口，不适合多通道隔离场景（仅作厂商扩展示例/备用）。
    """

    name = "kuaidaili"

    def __init__(self, tunnel: str = None, username: str = None,
                 password: str = None):
        self.tunnel = tunnel or CONFIG["tunnel"]
        self.username = username or CONFIG["username"]
        self.password = password or CONFIG["password"]

    def _resolve_tunnel(self) -> str:
        if not self.tunnel or self.tunnel.startswith(("xxx.", "your_")):
            self.tunnel = get_tunnel_proxy()[0]
        return self.tunnel

    def servers(self) -> list[str]:
        return [self._resolve_tunnel()]

    def acquire(self) -> Channel:
        return Channel(server=self._resolve_tunnel(),
                       username=self.username,
                       password=self.password,
                       provider=self.name)

    def refresh(self) -> list[str]:
        self.tunnel = get_tunnel_proxy()[0]
        return [self.tunnel]

    def make_proxies(self, server: str = None) -> dict:
        server = server or self._resolve_tunnel()
        proxy_url = f"http://{self.username}:{self.password}@{server}/"
        return {"http": proxy_url, "https": proxy_url}
