# -*- coding: utf-8 -*-
"""
代理 Provider 抽象（docs/service-architecture.md §5）。

新增厂商 = 新增一个 provider 模块 + 装饰器注册进 PROVIDER_REGISTRY；
前端配置表单由 config_schema 驱动，无需改前端代码。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ProviderConfigError(ValueError):
    """配置校验失败（API 层转成 400）。"""


class ProviderAPIError(RuntimeError):
    """厂商 API 调用失败（API 层转成 502）。"""
    def __init__(self, message: str, code: str | None = None, request_id: str | None = None):
        self.code = code
        self.request_id = request_id
        super().__init__(message)


@dataclass
class Channel:
    """一条代理通道（隧道入口 + 最近探测到的出口 IP）。"""
    tunnel: str                       # host:port
    exit_ip: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class ProxyProvider:
    """Provider 基类。实现类必须定义 kind / config_schema 并覆盖下列方法。"""

    kind: str = ""
    # 前端动态渲染配置表单用：{"字段名": {"type": "...", "label": "...", "secret": bool, ...}}
    config_schema: dict[str, dict] = {}

    def validate(self, config: dict) -> None:
        """校验密钥/参数格式，不合法抛 ProviderConfigError。"""
        raise NotImplementedError

    def test_connectivity(self, config: dict) -> dict:
        """连通性测试（前端"测试"按钮）：返回通道数/隧道/出口 IP 等。"""
        raise NotImplementedError

    def sync_channels(self, config: dict, cached: list[str] | None = None) -> list[Channel]:
        """校准通道列表。cached = 已知的隧道入口（库中已有记录，替代旧版 .cache 文件缓存）。"""
        raise NotImplementedError

    def make_proxies(self, channel: Channel, config: dict) -> dict:
        """构造 requests 可用的 proxies 字典。"""
        raise NotImplementedError

    def exit_ip_ttl(self, config: dict) -> int:
        """出口 IP 存活秒数（用于推算 ip_expires_at）。"""
        raise NotImplementedError


PROVIDER_REGISTRY: dict[str, type[ProxyProvider]] = {}


def register_provider(cls: type[ProxyProvider]) -> type[ProxyProvider]:
    assert cls.kind, "provider 必须定义 kind"
    PROVIDER_REGISTRY[cls.kind] = cls
    return cls


def get_provider(kind: str) -> ProxyProvider:
    cls = PROVIDER_REGISTRY.get(kind)
    if cls is None:
        raise ProviderConfigError(
            f"未知代理厂商 kind={kind!r}，已注册: {sorted(PROVIDER_REGISTRY)}")
    return cls()
