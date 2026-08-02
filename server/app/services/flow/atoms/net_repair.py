# -*- coding: utf-8 -*-
"""net_repair 原子：网络修复（先刷新页面，后换 IP）。

对应「网络卡顿先刷新、刷新救不回来再换 IP」的分阶段处置。引擎经
params["_attempt"] 注入第几次补救（1 起）：

    _attempt <= refresh_attempts（默认 1~2 次）：调 refresh_page——
        不换通道、不重启浏览器、Cookie 保留，成本最低
    _attempt 再往上：委托 swap_ip 换出口 IP（直连模式 swap_ip 自身
        已退化为退避，语义自然衔接）

旧模板 on_net_error 直接 swap_ip（每次网络抖动都换通道 + 重启浏览器），
本原子把轻量刷新插到补救链最前面；旧策略不动供灰度对比。
"""
from __future__ import annotations

from ..base import Atom, AtomResult, Context
from ..registry import register
from .refresh_page import RefreshPageAtom
from .swap_ip import SwapIpAtom


@register
class NetRepairAtom(Atom):
    name = "net_repair"
    title = "网络修复（先刷新后换 IP）"
    inputs = {"resources.page": "Page", "resources.*": "换 IP 阶段所需资源"}
    outputs = {"resources.*": "换 IP 阶段由 swap_ip 更新"}
    param_spec = {
        "type": "object",
        "properties": {
            "refresh_attempts": {"type": "integer", "default": 2,
                                 "minimum": 0, "maximum": 10,
                                 "title": "前置刷新次数",
                                 "description": "前几次网络故障先原地刷新页面"
                                                "（默认 2 次），之后才换 IP"},
            "timeout_ms": {"type": "integer", "default": 30000,
                           "minimum": 1000,
                           "title": "刷新超时（毫秒，透传 refresh_page）"},
            "ip_retry": {"type": "integer", "default": 3, "minimum": 1,
                         "title": "换 IP 重试次数（透传 swap_ip）"},
            "headed": {"type": "boolean", "default": False,
                       "title": "重启浏览器有头模式（透传 swap_ip）"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        attempt = max(1, int(params.get("_attempt") or 1))
        refresh_attempts = max(0, int(params.get("refresh_attempts") or 2))

        # ---- 阶段 2：换出口 IP ----
        if attempt > refresh_attempts:
            ctx.emit("warning",
                     f"第 {attempt} 次网络故障，刷新页面未恢复，换出口 IP",
                     {"worker": ctx.worker_id, "attempt": attempt,
                      "stage": "swap_ip"})
            return SwapIpAtom().run(ctx, {
                "ip_retry": max(1, int(params.get("ip_retry") or 3)),
                "headed": bool(params.get("headed", False)),
                "note": "网络故障刷新未恢复，换 IP",
            })

        # ---- 阶段 1：原地刷新页面 ----
        ctx.emit("info",
                 f"第 {attempt} 次网络故障，原地刷新页面（不换 IP）",
                 {"worker": ctx.worker_id, "attempt": attempt,
                  "stage": "refresh"})
        result = RefreshPageAtom().run(ctx, {
            "timeout_ms": max(1000, int(params.get("timeout_ms") or 30000)),
            "note": "网络故障刷新",
        })
        data = dict(result.data or {})
        data["attempt"] = attempt
        data["stage"] = "refresh"
        return AtomResult(outcome=result.outcome, detail=result.detail,
                          data=data)
