# -*- coding: utf-8 -*-
"""青果网络 - 国内长效代理（动态）通道池（迁移自 util/proxy_qingguo.py）。

产品特性（订单 20260730304442，业务标识 unfbsqwi）：
    - 国内-长效代理-动态-10Mbps，存活周期 30 分钟；
    - 出口 IP 每 30 分钟自动轮换一次，隧道入口与账密不变，无需重新提取；
    - 通道提取：5 个通道各持一个隧道入口，背后各是独立出口 IP。

解析顺序：.cache 缓存 -> /query 在用通道 -> /get 补齐不足部分。
acquire() 轮询返回不同通道，一 worker 一通道即独占一个出口 IP。

requests 为延迟导入：import 本模块不需要安装任何第三方包。
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from pathlib import Path

from fetcher.net.proxy.base import Channel

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

# 缓存复用周期（秒）：与出口 IP 30 分钟轮换周期对齐
IP_TTL_SECONDS = 30 * 60

# 隧道入口持久化缓存文件（默认项目根 .cache/qingguo_tunnel.json，
# 与旧版路径一致，脚本重启后仍可复用；可用环境变量覆盖）
_CACHE_DEFAULT = Path(__file__).resolve().parents[4] / ".cache" / "qingguo_tunnel.json"
CACHE_FILE = Path(os.environ.get("FETCHER_QINGGUO_CACHE", str(_CACHE_DEFAULT)))


def _load_tunnel_cache(cache_file: Path = CACHE_FILE) -> dict | None:
    """从 .cache 读取缓存的隧道入口列表（兼容旧版单入口格式）。"""
    try:
        cache = json.loads(Path(cache_file).read_text(encoding="utf-8"))
        servers = cache.get("servers") or ([cache["server"]] if cache.get("server") else [])
        if servers and cache.get("expire_at", 0) > time.time():
            cache["servers"] = servers
            return cache
    except (OSError, ValueError):
        pass
    return None


def _save_tunnel_cache(servers: list, cache_file: Path = CACHE_FILE):
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
    Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
    Path(cache_file).write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                                encoding="utf-8")


class QingGuoException(Exception):
    def __init__(self, code=None, message=None, request_id=None):
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[QingGuoException] code: {code} message: {message} request_id: {request_id}")


def _api_get(path: str, params: dict) -> dict:
    """调用青果长效代理 API，统一处理错误码（requests 延迟导入）。"""
    import requests

    url = CONFIG["api_base"] + path
    params = {"key": CONFIG["key"], **{k: v for k, v in params.items() if v not in (None, "")}}
    r = requests.get(url, params=params, timeout=30)
    try:
        res = r.json()
    except ValueError:
        raise QingGuoException(r.status_code, r.text)
    if res.get("code") != "SUCCESS":
        raise QingGuoException(res.get("code"), res.get("message") or res.get("msg") or r.text, res.get("request_id"))
    return res


def query_inuse_ips(task: str = None) -> list:
    """查询在用IP资源（/query 接口），频率限制 60 次/分钟。"""
    res = _api_get("/query", {"task": task})
    return res.get("data") or []


def query_channels() -> dict:
    """查询通道数（/channels 接口），返回 {total, idle}。"""
    res = _api_get("/channels", {})
    return res.get("data")


def query_resource_areas() -> dict:
    """查询可提取的资源地区（/resources 接口）。"""
    res = _api_get("/resources", {})
    return res.get("data")


def _extract_servers(num: int, area: str = None, isp: int = None) -> list:
    """调 /get 提取 num 个隧道入口（占用 num 个空闲通道）。

    通道占满时抛 NO_AVAILABLE_CHANNEL，由调用方决定回退策略。
    """
    res = _api_get("/get", {
        "area": CONFIG["area"] if area is None else area,
        "isp": CONFIG["isp"] if isp is None else isp,
        "num": num,
    })
    data = res.get("data") or []
    if isinstance(data, dict):
        data = data.get("ips") or []
    servers = [item["server"] for item in data if item.get("server")]
    if not servers:
        raise QingGuoException("NO_SERVER", f"提取结果为空: {res}", res.get("request_id"))
    return servers


class QingGuoProvider:
    """青果通道池：持有 channels 个隧道入口，轮询分发（ProxyProvider 协议实现）。

    与旧版 ChannelPool 行为一致：缓存 -> /query -> /get 补齐；
    acquire() 轮询返回不同通道，连续 N 次调用得到 N 个不同入口。
    """

    name = "qingguo"

    def __init__(self, size: int = None, cache_file: Path = CACHE_FILE):
        self.size = int(size or CONFIG["channels"])
        self.cache_file = Path(cache_file)
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
                cache = _load_tunnel_cache(self.cache_file)
                if cache:
                    servers = list(cache["servers"])

            if not servers:
                servers = [item["server"] for item in query_inuse_ips()
                           if item.get("server")]

            # 不足 channels 个时调 /get 补齐（占用空闲通道）
            if len(servers) < self.size:
                try:
                    servers += _extract_servers(self.size - len(servers))
                except QingGuoException as e:
                    if e.code != "NO_AVAILABLE_CHANNEL":
                        raise

            if not servers:
                raise QingGuoException("NO_SERVER", "未获取到任何隧道入口")
            _save_tunnel_cache(servers, self.cache_file)
            self._servers = servers
            return self._servers

    def servers(self) -> list:
        return list(self._resolve())

    def acquire(self) -> Channel:
        """轮询取一个通道；连续调用依次得到不同通道。"""
        servers = self._resolve()
        with self._lock:
            server = servers[next(self._rr) % len(servers)]
        return Channel(server=server,
                       username=CONFIG["auth_key"],
                       password=CONFIG["auth_pwd"],
                       provider=self.name)

    def refresh(self) -> list:
        """隧道入口失效时强制重新校准（跳过缓存，/query 为准）。"""
        return list(self._resolve(force=True))

    def make_proxies(self, server: str = None) -> dict:
        """构造 requests 可用的 proxies 字典（账密验证）。"""
        server = server or self.acquire().server
        proxy_url = (f"http://{CONFIG['auth_key']}:{CONFIG['auth_pwd']}"
                     f"@{server}/")
        return {"http": proxy_url, "https": proxy_url}


# 默认全局池（兼容旧版 get_pool 语义；size 仅首次生效）
_default_pool = None
_default_pool_lock = threading.Lock()


def get_pool(size: int = None) -> QingGuoProvider:
    global _default_pool
    with _default_pool_lock:
        if _default_pool is None:
            _default_pool = QingGuoProvider(size)
        return _default_pool
