# -*- coding: utf-8 -*-
"""confirm_human 原子：人工确认（headed 模式下等运营在页面上完成登录/验证后确认）。

包装 app/services/pool_client.py 的 wait_confirmation：
- 返回 True（已确认 / 无 Redis 时跳过确认，等价 -y）-> outcome "ok"
- 返回 False 且期间收到停止请求 -> outcome "stopped"
- 返回 False（超时）-> outcome "timeout"

原函数内部 time.sleep(poll) 轮询 Redis、无进度回调；为每秒左右
report_progress({"total", "elapsed"})，wait_confirmation 在守护线程中原样执行
（参数/返回语义不变），主线程只做进度上报，不改动其等待行为。
"""
from __future__ import annotations

import threading
import time

from ...pool_client import wait_confirmation
from ..base import Atom, AtomResult, Context, OUTCOME_OK, OUTCOME_STOPPED
from ..registry import register

OUTCOME_TIMEOUT = "timeout"


@register
class ConfirmHumanAtom(Atom):
    name = "confirm_human"
    title = "人工确认"
    inputs = {}
    outputs = {}
    param_spec = {
        "type": "object",
        "properties": {
            "timeout": {
                "type": "integer",
                "default": 600,
                "minimum": 1,
                "title": "确认超时（秒）",
                "description": "超过该时长未确认按取消处理",
            },
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        timeout = params.get("timeout", 600)
        timeout = 600.0 if timeout is None else float(timeout)
        timeout = max(1.0, timeout)
        ctx.emit("info", f"等待人工确认（超时 {int(timeout)} 秒）",
                 {"timeout": timeout})
        box: dict = {}

        def _wait() -> None:
            try:
                # 委托原函数，行为不变（停止经 should_stop 回调传入）
                box["confirmed"] = wait_confirmation(
                    ctx.task_id, timeout=timeout,
                    should_stop=ctx.stop_requested)
            except Exception as e:  # noqa: BLE001 - 回主线程统一抛出
                box["error"] = e

        t = threading.Thread(target=_wait, daemon=True,
                             name=f"confirm-{ctx.task_id}")
        start = time.monotonic()
        ctx.report_progress({"total": timeout, "elapsed": 0.0})
        t.start()
        while t.is_alive():
            t.join(timeout=1.0)
            ctx.report_progress({
                "total": timeout,
                "elapsed": round(min(time.monotonic() - start, timeout), 3),
            })
        ctx.report_progress({
            "total": timeout,
            "elapsed": round(min(time.monotonic() - start, timeout), 3),
        })
        if "error" in box:
            raise box["error"]
        if box.get("confirmed"):
            ctx.emit("success", "人工确认通过")
            return AtomResult(outcome=OUTCOME_OK, detail="人工确认通过")
        if ctx.stop_requested():
            ctx.emit("warning", "人工确认期间收到停止请求，按取消处理")
            return AtomResult(outcome=OUTCOME_STOPPED,
                              detail="人工确认期间被停止")
        ctx.emit("warning", f"人工确认超时（{int(timeout)} 秒），按取消处理")
        return AtomResult(outcome=OUTCOME_TIMEOUT,
                          detail=f"等待人工确认超时（{int(timeout)} 秒）")
