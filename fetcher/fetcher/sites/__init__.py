# -*- coding: utf-8 -*-
"""sites：站点插件层 + 轻量注册表。

新增一个站点 = 新建子目录 + 在子目录 __init__ 里 register_site()，
主框架（net/atoms/detect/strategy/control/cli）一行不改：

    fetcher/sites/mysite/__init__.py 末尾:
        from fetcher.sites import register_site
        register_site("mysite", MySitePlugin)

sites 包导入时自动发现并 import 全部子目录（pkgutil 扫描），
各站点在导入时完成自注册。CLI/Engine 只经 get_site() 取插件。
"""

from __future__ import annotations

import importlib
import pkgutil

from fetcher.sites.base import SitePlugin

_SITE_REGISTRY: dict[str, type] = {}


def register_site(name: str, plugin_cls) -> None:
    """注册站点插件类（在各站点子包 __init__ 末尾调用）。"""
    if not isinstance(name, str) or not name:
        raise ValueError("站点名必须是非空字符串")
    _SITE_REGISTRY[name] = plugin_cls


def get_site(name: str):
    """按名取站点插件实例（CLI 用，如 "1688" / "taobao"）。"""
    _autodiscover()
    if name not in _SITE_REGISTRY:
        raise KeyError(f"未知站点: {name!r}（可选: {', '.join(site_names())}）")
    return _SITE_REGISTRY[name]()


def site_names() -> list[str]:
    _autodiscover()
    return sorted(_SITE_REGISTRY)


_discovered = False


def _autodiscover() -> None:
    """扫描 sites/ 的子目录并 import（各子包 import 时自注册）。"""
    global _discovered
    if _discovered:
        return
    _discovered = True
    for info in pkgutil.iter_modules(__path__):
        if info.ispkg and not info.name.startswith("_"):
            importlib.import_module(f"fetcher.sites.{info.name}")


# 兼容旧导入路径（P1 起的外部引用）
from fetcher.sites.alibaba1688 import Alibaba1688Plugin  # noqa: E402

__all__ = [
    "Alibaba1688Plugin",
    "SitePlugin",
    "get_site",
    "register_site",
    "site_names",
]
