# -*- coding: utf-8 -*-
"""Refresh 原子：页面刷新（网络卡顿 NET_STALL 的轻处置）。

刷新对风控的影响与人工 F5 相当，是网络卡/页面没加载出来时的
第一档处置，比重启浏览器换 IP 便宜得多。
"""

from __future__ import annotations

import random
import time

from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult


class Refresh:
    """刷新当前页面：params = {"timeout_ms": 30000, "render_wait": [1.5, 3.0]}。"""

    name = "refresh"
    title = "刷新页面"

    def run(self, ctx, params: dict) -> ActionResult:
        page = ctx.page
        if page is None:
            return ActionResult.fatal("无活动页面")
        timeout = int(params.get("timeout_ms", 30000))
        wait_lo, wait_hi = params.get("render_wait", (1.5, 3.0))
        try:
            page.reload(wait_until="domcontentloaded", timeout=timeout)
            time.sleep(random.uniform(wait_lo, wait_hi))
            return ActionResult.success("页面已刷新")
        except Exception as e:  # noqa: BLE001
            ctx.last_error = e
            kind = classify_error(e, page)
            reason = str(e).splitlines()[0][:200]
            if kind == "fatal":
                return ActionResult.fatal(f"刷新时浏览器死亡: {reason}")
            if kind == "net_error":
                return ActionResult.net_error(f"刷新遇网络层错误: {reason}")
            return ActionResult.net_error(f"刷新超时/卡顿: {reason}")
