# -*- coding: utf-8 -*-
"""sleep 原子：等待（固定时长或区间随机），倒计时事件 + 实时进度 + 协作式停止。

行为对齐 app/services/task_runtime.py 的 start_delay_countdown。因契约差异
（ctx.rt 可为 None；原子需每秒左右 report_progress 供前端画进度条），
此处按原逻辑移植为 ctx 版本，并注明与来源的差异：

- rt.emit -> ctx.emit；rt.stop_requested -> ctx.stop_requested
- 等待切片由 time.sleep(min(2s, left)) 改为 ctx.wait(min(1s, left))，
  以便每秒左右上报 progress {"total", "elapsed"}
- 归一化（负值取 0、min>max 交换并告警）、每 10s 一条倒计时事件、
  末尾不足 2s 不再报剩余，均与原实现一致
"""
from __future__ import annotations

import random
import time

from ..base import Atom, AtomResult, Context, OUTCOME_OK, OUTCOME_STOPPED
from ..registry import register


@register
class SleepAtom(Atom):
    name = "sleep"
    title = "等待"
    inputs = {}
    outputs = {}
    param_spec = {
        "type": "object",
        "properties": {
            "min": {
                "type": "integer",
                "default": 0,
                "minimum": 0,
                "title": "最短等待（秒）",
                "description": "与 max 相等时为固定等待；不等时在区间内随机抽签；都为 0 时不等待",
            },
            "max": {
                "type": "integer",
                "default": 0,
                "minimum": 0,
                "title": "最长等待（秒）",
            },
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        lo = float(params.get("min", 0) or 0)
        hi = float(params.get("max", 0) or 0)
        # 以下归一化与倒计时逻辑移植自 start_delay_countdown（见模块 docstring）
        if lo < 0 or hi < 0:
            lo, hi = max(0.0, lo), max(0.0, hi)
            ctx.emit("warning", f"等待参数存在负值，已按 {lo:g}~{hi:g} 秒归一化")
        if hi < lo:
            lo, hi = hi, lo
            ctx.emit("warning", f"等待参数下限大于上限，已按 {lo:g}~{hi:g} 秒交换归一化")
        if hi <= 0:
            return AtomResult(outcome=OUTCOME_OK, detail="无需等待")
        seconds = lo if lo == hi else random.uniform(lo, hi)
        shown = int(round(seconds))
        range_note = f"（随机区间 {lo:g}~{hi:g} 秒）" if lo != hi else ""
        ctx.emit("info", f"将于 {shown} 秒后继续{range_note}（等待期间可停止）",
                 {"seconds": shown, "min": lo, "max": hi})
        ctx.report_progress({"total": seconds, "elapsed": 0.0})
        deadline = time.monotonic() + seconds
        announced: set[int] = set()
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            if ctx.stop_requested():
                ctx.emit("warning", "等待期间收到停止请求，节点取消",
                         {"remaining": int(left)})
                return AtomResult(outcome=OUTCOME_STOPPED,
                                  detail=f"等待期间被停止（剩余 {int(left)} 秒）")
            elapsed_step = int(seconds - left) // 10 * 10
            if (elapsed_step > 0 and elapsed_step not in announced
                    and left > 2):  # 末尾不足 2s 不再报"剩余 0 秒"
                announced.add(elapsed_step)
                ctx.emit("info", f"倒计时：剩余 {int(round(left))} 秒",
                         {"remaining": int(round(left))})
            ctx.report_progress({"total": seconds,
                                 "elapsed": round(seconds - left, 3)})
            ctx.wait(min(1.0, left))
        ctx.report_progress({"total": seconds, "elapsed": seconds})
        ctx.emit("info", "等待结束")
        return AtomResult(outcome=OUTCOME_OK, detail=f"等待 {shown} 秒完成")
