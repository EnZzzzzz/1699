# -*- coding: utf-8 -*-
"""net.proxy：代理厂商插件（青果 / 快代理 / 直连）。"""

from fetcher.net.proxy.base import Channel, ProxyProvider
from fetcher.net.proxy.direct import DirectProvider
from fetcher.net.proxy.kuaidaili import KdlException, KuaiDaiLiProvider
from fetcher.net.proxy.qingguo import QingGuoException, QingGuoProvider, get_pool

__all__ = [
    "Channel",
    "DirectProvider",
    "KdlException",
    "KuaiDaiLiProvider",
    "ProxyProvider",
    "QingGuoException",
    "QingGuoProvider",
    "get_pool",
]
