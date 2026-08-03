# -*- coding: utf-8 -*-
"""Sleep / BackoffSleep 原子。

Sleep：拟人随机等待，对数正态（重尾）分布（迁移自 common.human_pause）。
    大部分等待落在 min~max 附近（中位数取区间中点），允许偶发长停
    （截断上限 max*5）——「上千次操作零长停」本身就是机器特征。
    min == max 时退化为固定等待。

BackoffSleep：线性退避等待（迁移自引擎的 min(30*attempt, cap) 退避），
    按 ctx.state["attempt"]（或 params["attempt"]）计算时长。
"""

from __future__ import annotations

import math
import random

from fetcher.core.types import ActionResult, Outcome


def human_pause_duration(lo: float = 2.0, hi: float = 5.0) -> float:
    """拟人随机等待时长（对数正态分布，截断 [lo*0.5, hi*5]）。"""
    if lo >= hi:
        return float(lo)
    median = (lo + hi) / 2
    t = random.lognormvariate(math.log(median), 0.5)
    return max(lo * 0.5, min(t, hi * 5))


class Sleep:
    """等待原子：params = {"min": 秒, "max": 秒}（相等 = 固定）。"""

    name = "sleep"
    title = "等待"

    def run(self, ctx, params: dict) -> ActionResult:
        lo = float(params.get("min", 2.0))
        hi = float(params.get("max", 5.0))
        t = human_pause_duration(lo, hi)
        ctx.log(f"    ...随机等待 {t:.1f}s")
        interrupted = ctx.wait(t)
        if interrupted:
            return ActionResult(Outcome.SKIPPED, "被停止信号中断")
        return ActionResult.success(f"等待 {t:.1f}s", seconds=t)


class BackoffSleep:
    """退避等待原子：min(base * attempt, cap) 秒。

    params = {"base": 30, "cap": 180, "attempt": None}
    attempt 缺省取 ctx.state["attempt"]（策略层写入的重试序号）。
    """

    name = "backoff_sleep"
    title = "退避等待"

    def run(self, ctx, params: dict) -> ActionResult:
        base = float(params.get("base", 30.0))
        cap = float(params.get("cap", 180.0))
        attempt = params.get("attempt") or ctx.state.get("attempt", 1)
        t = min(base * int(attempt), cap)
        ctx.log(f"    ...退避等待 {t:.0f}s（第 {attempt} 次）")
        interrupted = ctx.wait(t)
        if interrupted:
            return ActionResult(Outcome.SKIPPED, "被停止信号中断")
        return ActionResult.success(f"退避 {t:.0f}s", seconds=t)
