# -*- coding: utf-8 -*-
"""Atom 协议：原子能力的标准契约（参考 docs/flow-architecture.md §3.1）。

原子只负责「做一件事并报告结果分类」，不感知重试次数、不决定是否
换 IP —— 决策在策略层。判断与行动分离：Atom 绝不做场景检测
（页面上有什么由 Detector 回答），只做动作并报告 Outcome。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fetcher.core.types import ActionResult


@runtime_checkable
class Atom(Protocol):
    """原子能力协议：run(ctx, params) -> ActionResult。"""

    name: str                    # 注册名，如 "sleep"
    title: str                   # 显示名，如 "等待"

    def run(self, ctx, params: dict) -> ActionResult:
        """执行动作。ctx 为 WorkerContext（鸭子类型，便于单测 mock）。"""
        ...
