# -*- coding: utf-8 -*-
"""human_pause 原子：拟人停顿（店铺/页面操作之间的随机间隔）。

来源：app/services/crawl/pages.py 的 human_pause(lo, hi)，原实现仅一行
time.sleep(random.uniform(lo, hi))，不支持停止感知与进度上报。
此处保留其"区间均匀抽签"行为，睡眠改用 ctx.wait 实现协作式停止，
并每秒左右 report_progress({"total", "elapsed"})（原子高频调用，不发事件）。
"""
from __future__ import annotations

import random
import time

from ..base import Atom, AtomResult, Context, OUTCOME_OK, OUTCOME_STOPPED
from ..registry import register


@register
class HumanPauseAtom(Atom):
    name = "human_pause"
    title = "拟人停顿"
    inputs = {}
    outputs = {}
    param_spec = {
        "type": "object",
        "properties": {
            "min": {
                "type": "number",
                "default": 3,
                "minimum": 0,
                "title": "最短停顿（秒）",
                "description": "与 max 相等时为固定停顿；不等时在区间内随机抽签",
            },
            "max": {
                "type": "number",
                "default": 7,
                "minimum": 0,
                "title": "最长停顿（秒）",
            },
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        lo = params.get("min", 3)
        hi = params.get("max", 7)
        lo = 3.0 if lo is None else float(lo)
        hi = 7.0 if hi is None else float(hi)
        # 负值宽容归一化（原实现 time.sleep(负数) 会直接抛 ValueError）
        lo, hi = max(0.0, lo), max(0.0, hi)
        if hi < lo:
            lo, hi = hi, lo
        # 抽签行为同 pages.human_pause：random.uniform(lo, hi)
        seconds = lo if lo == hi else random.uniform(lo, hi)
        if seconds <= 0:
            return AtomResult(outcome=OUTCOME_OK, detail="无需停顿")
        ctx.report_progress({"total": seconds, "elapsed": 0.0})
        deadline = time.monotonic() + seconds
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            if ctx.stop_requested():
                return AtomResult(outcome=OUTCOME_STOPPED,
                                  detail=f"拟人停顿期间被停止（剩余 {left:.1f} 秒）")
            ctx.report_progress({"total": seconds,
                                 "elapsed": round(seconds - left, 3)})
            ctx.wait(min(1.0, left))
        ctx.report_progress({"total": seconds, "elapsed": seconds})
        return AtomResult(outcome=OUTCOME_OK,
                          detail=f"停顿 {seconds:.1f} 秒完成")
