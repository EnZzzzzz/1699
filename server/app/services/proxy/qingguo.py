# -*- coding: utf-8 -*-
"""
青果网络 - 国内长效代理（动态）Provider。

逻辑迁移自 util/proxy_qingguo.py（该文件保持独立、不被 import）：
    - 通道校准顺序：cached（库中已有隧道，替代旧 .cache 文件缓存）-> /query 在用 -> /get 补齐
    - 出口 IP 每 30 分钟自动轮换（exit_ip_ttl = 1800）
    - 账密转发代理 URL

差异：密钥不再硬编码，全部从 providers.config_json 读入；
隧道持久化以 proxy_channels 表为准（不再写 .cache/qingguo_tunnel.json）。

参考文档:
    - 长效代理-API接口介绍: https://www.qg.net/doc/2143.html
    - 接口错误码: https://www.qg.net/list/117.html
"""
from __future__ import annotations

import requests

from .base import (
    Channel, ProviderAPIError, ProviderConfigError, ProxyProvider, register_provider,
)

DEFAULT_API_BASE = "https://longterm.proxy.qg.net"
DEFAULT_TEST_URL = "https://ipinfo.io/json"
EXIT_IP_TTL_SECONDS = 30 * 60  # 青果长效动态：出口 IP 每 30 分钟轮换一次


class QingGuoException(ProviderAPIError):
    """青果 API 返回非 SUCCESS（保留 code / request_id 便于排查）。"""


def _api_get(config: dict, path: str, params: dict) -> dict:
    """调用青果长效代理 API，统一处理错误码。"""
    base = (config.get("api_base") or DEFAULT_API_BASE).rstrip("/")
    params = {"key": config["key"], **{k: v for k, v in params.items() if v not in (None, "")}}
    try:
        r = requests.get(base + path, params=params, timeout=30)
    except requests.RequestException as e:
        raise QingGuoException(f"青果 API 请求失败: {e}") from e
    # 青果部分错误会以非 200 状态码返回，但 body 仍是 JSON（含 code/message）
    try:
        res = r.json()
    except ValueError:
        raise QingGuoException(r.text, code=str(r.status_code))
    if res.get("code") != "SUCCESS":
        raise QingGuoException(
            res.get("message") or res.get("msg") or r.text,
            code=res.get("code"), request_id=res.get("request_id"))
    return res


@register_provider
class QingguoProvider(ProxyProvider):
    kind = "qingguo"

    config_schema = {
        "key":      {"type": "string",  "label": "Authkey（API 公共参数 key）", "required": True},
        "auth_key": {"type": "string",  "label": "代理用户名（= Authkey）", "required": True},
        "auth_pwd": {"type": "string",  "label": "代理密码（Authpwd）", "required": True, "secret": True},
        "channels": {"type": "integer", "label": "通道数（购买的通道配额）", "required": True, "default": 5, "min": 1},
        "api_base": {"type": "string",  "label": "API 域名", "required": False, "default": DEFAULT_API_BASE},
        "area":     {"type": "string",  "label": "提取地区（留空不筛选）", "required": False, "default": ""},
        "isp":      {"type": "integer", "label": "运营商 0不限/1电信/2移动/3联通", "required": False, "default": 0},
        "test_url": {"type": "string",  "label": "测试目标地址", "required": False, "default": DEFAULT_TEST_URL},
    }

    # ---------------- 抽象接口实现 ----------------

    def validate(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise ProviderConfigError("config 必须是对象")
        for field in ("key", "auth_key", "auth_pwd"):
            v = config.get(field)
            if not isinstance(v, str) or not v.strip():
                raise ProviderConfigError(f"{field} 必填且必须是非空字符串")
        channels = config.get("channels")
        if not isinstance(channels, int) or isinstance(channels, bool) or channels < 1:
            raise ProviderConfigError("channels 必须是 >= 1 的整数")
        isp = config.get("isp", 0)
        if isp not in (0, 1, 2, 3):
            raise ProviderConfigError("isp 必须是 0/1/2/3")
        area = config.get("area", "")
        if area is not None and not isinstance(area, str):
            raise ProviderConfigError("area 必须是字符串")
        api_base = config.get("api_base") or DEFAULT_API_BASE
        if not isinstance(api_base, str) or not api_base.startswith(("http://", "https://")):
            raise ProviderConfigError("api_base 必须是 http(s) URL")

    def exit_ip_ttl(self, config: dict) -> int:
        return EXIT_IP_TTL_SECONDS

    def make_proxies(self, channel: Channel, config: dict) -> dict:
        proxy_url = "http://%(user)s:%(pwd)s@%(proxy)s/" % {
            "user": config["auth_key"],
            "pwd": config["auth_pwd"],
            "proxy": channel.tunnel,
        }
        return {"http": proxy_url, "https": proxy_url}

    # ---------------- 青果 API ----------------

    def query_inuse_ips(self, config: dict, task: str | None = None) -> list:
        """/query 查询在用通道 [{server, distinct}, ...]（60 次/分）。"""
        res = _api_get(config, "/query", {"task": task})
        return res.get("data") or []

    def query_channel_quota(self, config: dict) -> dict:
        """/channels 查询 {total, idle} 通道总数/空闲数。"""
        return _api_get(config, "/channels", {}).get("data") or {}

    def _extract_servers(self, config: dict, num: int) -> list[str]:
        """/get 提取 num 个隧道入口（占用 num 个空闲通道）。
        通道占满时抛 code=NO_AVAILABLE_CHANNEL，由调用方决定回退策略。"""
        res = _api_get(config, "/get", {
            "area": config.get("area") or None,
            "isp": config.get("isp", 0),
            "num": num,
        })
        data = res.get("data") or []
        if isinstance(data, dict):
            data = data.get("ips") or []
        servers = [item["server"] for item in data if item.get("server")]
        if not servers:
            raise QingGuoException(f"提取结果为空: {res}", code="NO_SERVER",
                                   request_id=res.get("request_id"))
        return servers

    # ---------------- 通道校准 / 连通性 ----------------

    def sync_channels(self, config: dict, cached: list[str] | None = None) -> list[Channel]:
        """校准通道列表：cached -> /query 在用 -> /get 补齐（沿用旧 ChannelPool 逻辑）。

        cached 为库中已有的隧道入口（替代旧版 .cache 文件缓存）。
        """
        size = int(config["channels"])
        servers: list[str] = list(cached or [])

        if not servers:
            servers = [item["server"] for item in self.query_inuse_ips(config)
                       if item.get("server")]

        if len(servers) < size:
            try:
                servers += self._extract_servers(config, size - len(servers))
            except QingGuoException as e:
                # 通道已全部占用：以在用通道为准，有几条用几条
                if e.code != "NO_AVAILABLE_CHANNEL":
                    raise

        if not servers:
            raise QingGuoException("未获取到任何隧道入口", code="NO_SERVER")
        # 去重保序
        seen: set[str] = set()
        unique = [s for s in servers if not (s in seen or seen.add(s))]
        return [Channel(tunnel=s) for s in unique]

    def test_connectivity(self, config: dict, cached: list[str] | None = None) -> dict:
        """连通性测试：通道配额 + 校准隧道列表 + 逐通道探测出口 IP。"""
        quota = self.query_channel_quota(config)
        channels = self.sync_channels(config, cached=cached)
        test_url = config.get("test_url") or DEFAULT_TEST_URL
        probes = []
        for ch in channels:
            try:
                r = requests.get(test_url, proxies=self.make_proxies(ch, config),
                                 headers={"Connection": "close"}, timeout=30)
                probes.append({"tunnel": ch.tunnel, "ok": True,
                               "exit_ip": r.json().get("ip"), "http_status": r.status_code})
            except Exception as e:  # noqa: BLE001 - 测试接口需要逐通道容错
                probes.append({"tunnel": ch.tunnel, "ok": False, "error": str(e)})
        return {
            "ok": all(p.get("ok") for p in probes) and bool(probes),
            "quota": quota, "channel_count": len(channels), "probes": probes,
        }
