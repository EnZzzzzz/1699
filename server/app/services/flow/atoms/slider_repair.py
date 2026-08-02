# -*- coding: utf-8 -*-
"""slider_repair 原子：风控修复·滑块优先（分阶段升级处置）。

策略链（引擎经 params["_attempt"] 注入第几次补救，1 起）：

    阶段 1（_attempt <= slider_attempts，默认 1~2 次）：
        调 solve_slider——滑块是风控里最便宜的一关，过了就保住当前
        出口 IP 和 Cookie，零资源成本；页面没滑块它也会秒过（ok）
    阶段 2（_attempt == slider_attempts + 1，默认第 3 次）：
        滑块连打失败 → 原地等待 wait_min~wait_max 分钟（停止感知 +
        {total, elapsed} 进度）→ 调 refresh_page 刷新页面
    阶段 3（_attempt == slider_attempts + 2，默认第 4 次）：
        刷新后再调 solve_slider 重试（新渲染的滑块 + 轨迹库换着用）
    阶段 4（_attempt 再往上）：
        委托 swap_ip 换出口 IP（最后的重处置；直连模式 swap_ip 自身
        已退化为退避，语义自然衔接）

与旧 block_repair（长休→换 IP）并存：本原子把「自动过滑块」插到
补救链最前面，适合已具备轨迹库的无人值守场景；旧原子不动供灰度对比。

注：补救原子的返回值会被引擎策略拦截器丢弃（run_with_policy 只按
_fetch 的 outcome 计数），所以各阶段只管做事 + 发事件 + 报进度，
是否需要升级由「下一次 fetch 仍然 blocked」自然驱动。
"""
from __future__ import annotations

import random
import time

from ..base import Atom, AtomResult, Context, OUTCOME_STOPPED
from ..registry import register
from .refresh_page import RefreshPageAtom
from .solve_slider import SolveSliderAtom
from .swap_ip import SwapIpAtom


@register
class SliderRepairAtom(Atom):
    name = "slider_repair"
    title = "风控修复（滑块优先）"
    inputs = {"resources.page": "Page", "resources.*": "换 IP 阶段所需资源"}
    outputs = {"resources.*": "换 IP 阶段由 swap_ip 更新"}
    param_spec = {
        "type": "object",
        "properties": {
            "slider_attempts": {"type": "integer", "default": 2,
                                "minimum": 0, "maximum": 10,
                                "title": "前置滑块尝试次数",
                                "description": "前几次被风控先自动过滑块"
                                               "（默认 2 次），之后才进入"
                                               "等待刷新阶段"},
            "slider_max_attempts": {"type": "integer", "default": 8,
                                    "minimum": 1, "maximum": 20,
                                    "title": "单层滑块尝试次数（透传 solve_slider）"},
            "wait_min": {"type": "number", "default": 180,
                         "title": "等待下限（秒）",
                         "description": "滑块连打失败后的原地等待，默认 3 分钟"},
            "wait_max": {"type": "number", "default": 300,
                         "title": "等待上限（秒）",
                         "description": "默认 5 分钟"},
            "ip_retry": {"type": "integer", "default": 3, "minimum": 1,
                         "title": "换 IP 重试次数（透传 swap_ip）"},
            "headed": {"type": "boolean", "default": False,
                       "title": "重启浏览器有头模式（透传 swap_ip）"},
        },
        "required": [],
    }

    # ------------------------------------------------------------------

    def _wait_stage(self, ctx: Context, seconds: float) -> AtomResult | None:
        """停止感知的等待 + {total, elapsed} 进度；被停止返回 STOPPED 结果。"""
        ctx.report_progress({"stage": "wait", "total": seconds,
                             "elapsed": 0.0})
        deadline = time.monotonic() + seconds
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            if ctx.wait(min(1.0, left)):
                return AtomResult(outcome=OUTCOME_STOPPED,
                                  detail="等待期间任务已停止")
            ctx.report_progress({"stage": "wait", "total": seconds,
                                 "elapsed": round(seconds - left, 3)})
        ctx.report_progress({"stage": "wait", "total": seconds,
                             "elapsed": seconds})
        return None

    # ------------------------------------------------------------------

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        attempt = max(1, int(params.get("_attempt") or 1))
        slider_attempts = max(0, int(params.get("slider_attempts") or 2))
        wait_stage_at = slider_attempts + 1      # 默认 3：等待 + 刷新
        retry_stage_at = slider_attempts + 2     # 默认 4：刷新后再过滑块

        # ---- 阶段 4：换出口 IP（最终处置）----
        if attempt > retry_stage_at:
            ctx.emit("warning",
                     f"第 {attempt} 次疑似风控，滑块与等待刷新均未恢复，"
                     "修复换 IP（最终处置）",
                     {"worker": ctx.worker_id, "attempt": attempt,
                      "stage": "swap_ip"})
            return SwapIpAtom().run(ctx, {
                "ip_retry": max(1, int(params.get("ip_retry") or 3)),
                "headed": bool(params.get("headed", False)),
                "note": "滑块修复未恢复，换 IP",
            })

        # ---- 阶段 2：等待几分钟 → 刷新页面 ----
        if attempt == wait_stage_at:
            lo = float(params.get("wait_min") or 180)
            hi = float(params.get("wait_max") or 300)
            if hi < lo:
                lo, hi = hi, lo
            seconds = lo if lo == hi else random.uniform(lo, hi)
            ctx.emit("warning",
                     f"滑块连续未通过，原地等待 {seconds / 60:.1f} 分钟后"
                     "刷新页面重试",
                     {"worker": ctx.worker_id, "attempt": attempt,
                      "stage": "wait_refresh", "seconds": round(seconds)})
            stopped = self._wait_stage(ctx, seconds)
            if stopped is not None:
                return stopped
            ctx.emit("info", "等待结束，刷新页面……",
                     {"worker": ctx.worker_id, "stage": "wait_refresh"})
            return RefreshPageAtom().run(ctx, {"note": "风控等待后刷新"})

        # ---- 阶段 1 / 3：自动过滑块（阶段 3 是刷新后的重试）----
        stage = "slider" if attempt <= slider_attempts else "slider_retry"
        ctx.emit("info",
                 f"第 {attempt} 次疑似风控，尝试自动过滑块"
                 f"{'（刷新后重试）' if stage == 'slider_retry' else ''}",
                 {"worker": ctx.worker_id, "attempt": attempt,
                  "stage": stage})
        result = SolveSliderAtom().run(ctx, {
            "max_attempts": max(1, int(params.get("slider_max_attempts") or 8)),
        })
        data = dict(result.data or {})
        data["attempt"] = attempt
        data["stage"] = stage
        return AtomResult(outcome=result.outcome, detail=result.detail,
                          data=data)
