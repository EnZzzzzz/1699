# -*- coding: utf-8 -*-
"""detect：场景判断层（Detector 只返回 Scenario，绝不动浏览器）。

generic.py 含两类：
    - 站点无关探测器（FatalErrorDetector / NetworkDetector）；
    - 参数化站点探测器（LoginWall/SliderPage/EmbeddedSlider/EmptyPage，
      特征表作构造参数）+ make_block_reason 统一判定工厂 ——
      站点插件只提供特征表数据即可复用判定结构。
"""

from fetcher.detect.base import Detector, SceneInspector
from fetcher.detect.generic import (
    EmbeddedSliderDetector,
    EmptyPageDetector,
    FatalErrorDetector,
    LoginWallDetector,
    NetworkDetector,
    SliderPageDetector,
    make_block_reason,
    page_text,
    page_url,
    url_hit,
)

__all__ = [
    "Detector",
    "EmbeddedSliderDetector",
    "EmptyPageDetector",
    "FatalErrorDetector",
    "LoginWallDetector",
    "NetworkDetector",
    "SceneInspector",
    "SliderPageDetector",
    "make_block_reason",
    "page_text",
    "page_url",
    "url_hit",
]
