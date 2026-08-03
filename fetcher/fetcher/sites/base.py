# -*- coding: utf-8 -*-
"""SitePlugin 协议：一个站点 = 一份风控特征表 + 一组探测器 + 任务钩子。

站点插件是多站点扩展的唯一入口（1688 是第一个实现）。控制层（P2）
只面向本协议编程，不认识任何具体站点。

判断与行动分离在插件层同样成立：
    - detectors() 只读状态返回 Scenario；
    - fetch() 只负责「采什么」并报告 Outcome；
    - 处置动作一律走策略层。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fetcher.core.types import ActionResult


@runtime_checkable
class SitePlugin(Protocol):
    """站点插件协议。"""

    name: str                 # 站点名，如 "alibaba1688"
    cookie_domain: str        # Cookie 隔离的域过滤词，如 "1688.com"
    homepage: str             # 低敏落地页（warmup/冷启动用）

    def detectors(self) -> list:
        """站点专属探测器（按优先级序；SceneInspector 拼在通用探测器之后）。"""
        ...

    def block_reason(self, page) -> str | None:
        """综合判定当前页是否被风控/待验证（人工过证等场景的统一口径）。

        返回命中原因；未命中返回 None。只读页面状态，不动浏览器。
        """
        ...

    def validate(self, page, data) -> bool:
        """抓取结果的有效性校验（如字段是否为空）。"""
        ...

    def acquire_item(self, db, wctx: dict):
        """认领一个任务项；没有可做的返回 None。"""
        ...

    def fetch(self, ctx, item) -> ActionResult:
        """抓取当前任务项（采什么）。异常由实现内部分级写入
        ActionResult.outcome / ctx.last_error。"""
        ...

    def persist(self, ctx, item, result: ActionResult) -> None:
        """抓取成功后的入库。"""
        ...

    def cold_start(self, page, item, log=print) -> None:
        """新会话冷启动软着陆（留下真实浏览轨迹）。"""
        ...
