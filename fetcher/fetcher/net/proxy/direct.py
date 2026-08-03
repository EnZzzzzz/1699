# -*- coding: utf-8 -*-
"""直连通道：无代理，出口 IP = 本机 IP，identity 记 "direct"。

直连多 worker 会共用本机 IP 和同一份 Cookie（可能触发风控），
仅建议单 worker 使用 —— 与旧版引擎的警告行为一致。
"""

from __future__ import annotations

from fetcher.net.proxy.base import Channel


class DirectProvider:
    """直连 provider：始终返回同一个直连通道。"""

    name = "direct"

    def servers(self) -> list[str]:
        return []

    def acquire(self) -> Channel:
        return Channel(server=None, provider=self.name)

    def refresh(self) -> list[str]:
        return []
