# -*- coding: utf-8 -*-
"""Detector 协议与 SceneInspector（优先级链）。

判断与行动分离：Detector 只读页面/上下文状态并返回 Scenario，
绝不动浏览器（不 goto、不 reload、不点击）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fetcher.core.types import Scenario


@runtime_checkable
class Detector(Protocol):
    """场景探测器：detect(ctx) -> Scenario | None（None = 未命中，放行给下一个）。"""

    name: str

    def detect(self, ctx) -> Scenario | None:
        ...


class SceneInspector:
    """按优先级链依次询问各 Detector，返回第一个命中的 Scenario。

    链的顺序即优先级：通用层（浏览器死活/网络错误）通常在前，
    站点层（登录墙/滑块/空页）在后；全部未命中返回 Scenario.OK。
    """

    def __init__(self, detectors: list):
        self.detectors = list(detectors)

    def inspect(self, ctx) -> Scenario:
        for d in self.detectors:
            try:
                hit = d.detect(ctx)
            except Exception:  # noqa: BLE001 - 单个探测器异常不阻断链路
                continue
            if hit is not None:
                return hit
        return Scenario.OK

    @classmethod
    def for_site(cls, site) -> "SceneInspector":
        """装配标准链：通用探测器（站点可裁剪）+ 站点探测器。"""
        from fetcher.detect.generic import FatalErrorDetector, NetworkDetector
        generic = [FatalErrorDetector(), NetworkDetector()]
        site_detectors = list(site.detectors()) if site is not None else []
        order = getattr(site, "generic_detectors", None)
        if order is not None:  # 站点显式声明了通用探测器（含顺序/裁剪）
            generic = order
        return cls(generic + site_detectors)
