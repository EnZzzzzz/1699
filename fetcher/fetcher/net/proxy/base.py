# -*- coding: utf-8 -*-
"""ProxyProvider 协议与 Channel：代理厂商的统一抽象。

一个 Channel = 一个隧道入口（host:port + 账密），背后是一个独占
出口 IP。一 worker 一通道，Cookie 按各通道的出口 IP 隔离。
直连是特殊通道（DirectProvider 产出的 Channel.server=None）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Channel:
    """一个代理通道（隧道入口）。

    server 为 None 表示直连通道（本机出口）。
    """

    server: str | None           # "host:port"；None = 直连
    username: str | None = None
    password: str | None = None
    provider: str = ""           # 厂商名（日志用）

    @property
    def is_direct(self) -> bool:
        return self.server is None

    def playwright_proxy(self) -> dict | None:
        """拆成 Playwright proxy dict（内嵌账密的 URL 直接传给 Chromium
        会报 ERR_NO_SUPPORTED_PROXIES，必须拆开传）。"""
        if self.is_direct:
            return None
        return {
            "server": f"http://{self.server}",
            "username": self.username,
            "password": self.password,
        }

    def requests_proxies(self) -> dict | None:
        """requests 查询出口 IP 用的内嵌账密代理字典。"""
        if self.is_direct:
            return None
        url = f"http://{self.username}:{self.password}@{self.server}"
        return {"http": url, "https": url}


@runtime_checkable
class ProxyProvider(Protocol):
    """代理厂商协议：提供一组独占通道，轮询分发给并发 worker。"""

    name: str

    def servers(self) -> list[str]:
        """全部隧道入口列表（必要时解析/补齐）。"""
        ...

    def acquire(self) -> Channel:
        """轮询取一个通道；连续调用依次得到不同通道。"""
        ...

    def refresh(self) -> list[str]:
        """通道失效时强制重新校准。"""
        ...
