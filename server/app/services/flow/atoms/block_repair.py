# -*- coding: utf-8 -*-
"""block_repair 原子：风控修复（先休息后换 IP）。

复刻蓝本 scraper/taobao_1688/contact_fetcher.py docstring
「风控处理流程（单店）」的两阶段处置：
  第 1 次被风控 → 保持当前 IP，原地长休 block_rest_min~max 秒
                 （蓝本 --block-rest-min/max 默认 10~15 分钟）后重试；
  第 2 次被风控 → 修复换 IP：重启浏览器拿新出口 IP（青果 IP 时效 30 分钟，
                 长休后旧 IP 通常已过期轮换），按新 IP 重新配对 Cookie。

阶段判定：引擎策略拦截器把 on_blocked 的第 N 次补救以 params["_attempt"]
注入（executor.run_with_policy，1 起）。_attempt == 1 走一阶段长休，
_attempt >= 2 委托 swap_ip 原子（直连时 swap_ip 自身已退化为退避，
语义与蓝本直连「无法换 IP 只退避」自然衔接）。

长休实现同 sleep 原子：ctx.wait 切片（停止感知）+ 每秒 report_progress
{total, elapsed} 供前端画进度。
"""
from __future__ import annotations

import random
import time

from ..base import Atom, AtomResult, Context, OUTCOME_STOPPED
from ..registry import register
from .swap_ip import SwapIpAtom


@register
class BlockRepairAtom(Atom):
    name = "block_repair"
    title = "风控修复（先休息后换 IP）"
    inputs = {"resources.*": "二阶段委托 swap_ip 所需资源"}
    outputs = {"resources.*": "二阶段换 IP 时由 swap_ip 更新"}
    param_spec = {
        "type": "object",
        "properties": {
            "block_rest_min": {"type": "number", "default": 600,
                               "title": "一阶段休息下限（秒）",
                               "description": "蓝本 --block-rest-min，默认 600"},
            "block_rest_max": {"type": "number", "default": 900,
                               "title": "一阶段休息上限（秒）",
                               "description": "蓝本 --block-rest-max，默认 900"},
            "ip_retry": {"type": "integer", "default": 3, "minimum": 1,
                         "title": "二阶段换 IP 重试次数（透传 swap_ip）"},
            "headed": {"type": "boolean", "default": False,
                       "title": "二阶段重启浏览器有头模式（透传 swap_ip）"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        attempt = max(1, int(params.get("_attempt") or 1))

        # ---- 二阶段：修复换 IP（委托 swap_ip；直连自动退化为退避）----
        if attempt >= 2:
            ctx.emit("warning",
                     f"第 {attempt} 次疑似风控，修复换 IP（蓝本二阶段）",
                     {"worker": ctx.worker_id, "attempt": attempt})
            return SwapIpAtom().run(ctx, {
                "ip_retry": max(1, int(params.get("ip_retry") or 3)),
                "headed": bool(params.get("headed", False)),
                "note": "风控修复换 IP",
            })

        # ---- 一阶段：不换 IP，原地长休（停止感知 + 实时进度）----
        lo = float(params.get("block_rest_min") or 600)
        hi = float(params.get("block_rest_max") or 900)
        if hi < lo:  # 宽容归一化（同 sleep 原子）
            lo, hi = hi, lo
        seconds = lo if lo == hi else random.uniform(lo, hi)
        ctx.emit("warning",
                 f"疑似风控，保持当前 IP 休息 {seconds / 60:.1f} 分钟后重试"
                 "（蓝本一阶段）",
                 {"worker": ctx.worker_id, "seconds": round(seconds),
                  "attempt": attempt})
        ctx.report_progress({"total": seconds, "elapsed": 0.0})
        deadline = time.monotonic() + seconds
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            if ctx.wait(min(1.0, left)):
                return AtomResult(outcome=OUTCOME_STOPPED,
                                  detail="休息期间任务已停止")
            ctx.report_progress({"total": seconds,
                                 "elapsed": round(seconds - left, 3)})
        ctx.report_progress({"total": seconds, "elapsed": seconds})
        return AtomResult(data={"rested": round(seconds), "attempt": attempt})
