# -*- coding: utf-8 -*-
"""refresh_page 原子：原地刷新当前页面（网络卡顿/页面卡死的一二级处置）。

比 swap_ip 轻得多：不换通道、不重启浏览器、Cookie 原样保留，只是
page.reload + 轮询等页面重新渲染。对应「准备网络 → 观察现象 →
网络卡顿就刷新」策略链中的最低成本补救。

outcome 映射：
    刷新成功且页面重新渲染出内容    → ok
    page 不可用 / 网络层异常        → net_error（交回策略层升级，如换 IP）
    等待期间任务被停止              → stopped
"""
from __future__ import annotations

import time

from ..base import (
    Atom, AtomResult, Context,
    OUTCOME_NET_ERROR, OUTCOME_OK, OUTCOME_STOPPED,
)
from ..registry import register


@register
class RefreshPageAtom(Atom):
    name = "refresh_page"
    title = "刷新页面"
    inputs = {"resources.page": "Page（当前页）"}
    outputs = {"data": "url（刷新后的页面 URL）"}
    param_spec = {
        "type": "object",
        "properties": {
            "timeout_ms": {"type": "integer", "default": 30000,
                           "minimum": 1000,
                           "title": "reload 超时（毫秒）"},
            "render_wait": {"type": "number", "default": 8,
                            "minimum": 0,
                            "title": "渲染等待上限（秒）",
                            "description": "reload 后轮询等 body 出内容的"
                                           "最长时间（代理下页面渲染慢）"},
            "note": {"type": "string", "default": "",
                     "title": "事件备注（如触发原因）"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        page = ctx.resources.get("page")
        if page is None:
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail="ctx.resources 缺少 page（浏览器未启动）")

        timeout_ms = max(1000, int(params.get("timeout_ms") or 30000))
        render_wait = max(0.0, float(params.get("render_wait") or 8))
        note = params.get("note") or ""
        tag = f"（{note}）" if note else ""

        if ctx.stop_requested():
            return AtomResult(outcome=OUTCOME_STOPPED, detail="任务已停止")

        ctx.emit("info", f"刷新页面{tag}……", {"worker": ctx.worker_id})
        try:
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001 - 全部归为网络层故障
            reason = str(e).splitlines()[0][:200]
            ctx.emit("warning", f"刷新页面失败（{reason}）",
                     {"worker": ctx.worker_id, "reason": reason})
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail=f"刷新页面失败：{reason}")

        # ---- 轮询等渲染：body 出内容即认为刷新成功（停止感知切片）----
        deadline = time.monotonic() + render_wait
        while time.monotonic() < deadline:
            if ctx.stop_requested():
                return AtomResult(outcome=OUTCOME_STOPPED, detail="任务已停止")
            try:
                n = page.evaluate(
                    "() => document.body ? document.body.innerText.length : 0")
            except Exception:  # noqa: BLE001 - 渲染中 evaluate 偶发失败
                n = 0
            if isinstance(n, (int, float)) and n > 30:
                ctx.emit("info", f"页面已刷新（{page.url[:80]}）",
                         {"worker": ctx.worker_id, "url": page.url})
                return AtomResult(outcome=OUTCOME_OK,
                                  detail="页面已刷新",
                                  data={"url": page.url})
            if ctx.wait(min(0.5, max(0.0, deadline - time.monotonic()))):
                return AtomResult(outcome=OUTCOME_STOPPED, detail="任务已停止")

        # render_wait=0 或超时仍未出内容：不算网络故障（页面可能只是空白），
        # 如实报告让调用方（fetch 重跑后）自行分类
        ctx.emit("warning", f"刷新后 {render_wait:.0f}s 内页面仍未渲染出内容",
                 {"worker": ctx.worker_id, "url": page.url})
        return AtomResult(outcome=OUTCOME_OK,
                          detail="已刷新但页面暂未渲染出内容",
                          data={"url": page.url, "render_timeout": True})
