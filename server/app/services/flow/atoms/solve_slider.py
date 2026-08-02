# -*- coding: utf-8 -*-
"""solve_slider 原子：检测并自动过滑块验证（真人轨迹回放）。

包装 util/slider_track.py 的能力（轨迹库回放 / 多层滑块循环 /
"验证失败点击重试"状态处理 / 多 worker 拖动互斥锁），接入 flow 体系。

设计要点：
- util/slider_track.py 以文件路径懒加载（importlib），不在模块级 import：
  server 包不依赖 sys.path 里有项目根，且单测可 mock _load_slider_mod
  完全脱离真实浏览器与轨迹库
- 先检测后动手：页面无滑块信号立即 ok 返回（成本极低），因此上游
  fetch 不需要细分 "blocked 里是不是滑块"——策略层无脑把本原子放在
  补救链第一级即可
- 轨迹库缺失/模块加载失败 → blocked（交回策略层升级到下一阶段，
  如等待刷新或换 IP），不让策略链原地空转
- 拖动互斥由 slider_track 模块级 _DRAG_LOCK 保证（并行 worker 安全）

outcome 映射：
    页面无滑块 / 滑块全部通过       → ok
    滑块打不动（层数/次数超限）     → blocked
    轨迹库缺失 / 模块加载失败       → blocked（detail 说明原因）
    页面崩溃等网络层异常            → net_error
    开始前任务已停止                → stopped
"""
from __future__ import annotations

import importlib.util

from .... import config
from ...crawl.pages import is_network_error
from ..base import (
    Atom, AtomResult, Context,
    OUTCOME_BLOCKED, OUTCOME_NET_ERROR, OUTCOME_OK, OUTCOME_STOPPED,
)
from ..registry import register

_SLIDER_TRACK_PATH = config.ROOT_DIR / "util" / "slider_track.py"


@register
class SolveSliderAtom(Atom):
    name = "solve_slider"
    title = "过滑块验证"
    inputs = {"resources.page": "Page（当前页，任意页面状态均可）"}
    outputs = {"data": "slider（是否检测到滑块）/ solved（是否通过）"}
    param_spec = {
        "type": "object",
        "properties": {
            "max_attempts": {"type": "integer", "default": 8,
                             "minimum": 1, "maximum": 20,
                             "title": "单层滑块最多尝试次数",
                             "description": "对应 slider_track.solve_with_retry "
                                            "的 max_attempts（换轨迹 + 每失败 "
                                            "2 次刷新页面）"},
            "max_rounds": {"type": "integer", "default": 3,
                           "minimum": 1, "maximum": 10,
                           "title": "多层滑块最大层数",
                           "description": "阿里风控常「过一关弹一关」（底层验证页"
                                          "过了上层模态框又弹），对应 "
                                          "solve_all_sliders 的 max_rounds"},
        },
        "required": [],
    }

    @staticmethod
    def _load_slider_mod():
        """按文件路径加载 util/slider_track.py（单测可 mock 本方法）。"""
        spec = importlib.util.spec_from_file_location(
            "slider_track", _SLIDER_TRACK_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载 {_SLIDER_TRACK_PATH}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        page = ctx.resources.get("page")
        if page is None:
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail="ctx.resources 缺少 page（浏览器未启动）")
        if ctx.stop_requested():
            return AtomResult(outcome=OUTCOME_STOPPED, detail="任务已停止")

        # ---- 加载滑块模块（懒加载，隔离重依赖）----
        try:
            mod = self._load_slider_mod()
        except Exception as e:  # noqa: BLE001
            ctx.emit("error", f"滑块模块加载失败：{e}",
                     {"worker": ctx.worker_id})
            return AtomResult(outcome=OUTCOME_BLOCKED,
                              detail=f"滑块模块加载失败：{e}")

        # ---- 检测：无滑块信号 → 直接 ok（本原子可放补救链第一级无脑调用）----
        ctx.report_progress({"phase": "detect"})
        try:
            present = bool(mod._slider_present(page, (
                "[id$='_n1z']", ".nc_iconfont.btn_slide", ".btn_slide")))
        except Exception as e:  # noqa: BLE001
            if is_network_error(e):
                return AtomResult(outcome=OUTCOME_NET_ERROR,
                                  detail=str(e).splitlines()[0][:200])
            # 检测本身失败（页面渲染中/frame 切换）：不算通过也不算打不动，
            # 报 blocked 让策略层重试
            return AtomResult(outcome=OUTCOME_BLOCKED,
                              detail=f"滑块检测异常：{e}")
        if not present:
            return AtomResult(outcome=OUTCOME_OK,
                              detail="页面无滑块信号",
                              data={"slider": False})

        # ---- 轨迹库预检：缺失/为空就别空打，交回策略层升级 ----
        try:
            tracks = mod.load_tracks()
        except Exception as e:  # noqa: BLE001
            ctx.emit("error", f"检测到滑块但轨迹库不可用：{e}",
                     {"worker": ctx.worker_id})
            return AtomResult(outcome=OUTCOME_BLOCKED,
                              detail=f"轨迹库不可用：{e}")
        if not tracks:
            return AtomResult(outcome=OUTCOME_BLOCKED,
                              detail="轨迹库为空（有效轨迹 <1 条）")

        max_attempts = max(1, int(params.get("max_attempts") or 8))
        max_rounds = max(1, int(params.get("max_rounds") or 3))
        ctx.emit("info",
                 f"检测到滑块验证，开始自动拖动（轨迹库 {len(tracks)} 条，"
                 f"单层最多 {max_attempts} 次 × 最多 {max_rounds} 层）",
                 {"worker": ctx.worker_id, "tracks": len(tracks)})
        ctx.report_progress({"phase": "solving", "max_rounds": max_rounds,
                             "max_attempts": max_attempts})

        try:
            solved = bool(mod.solve_all_sliders(
                page, max_rounds=max_rounds, max_attempts=max_attempts))
        except Exception as e:  # noqa: BLE001
            if is_network_error(e):
                return AtomResult(outcome=OUTCOME_NET_ERROR,
                                  detail=str(e).splitlines()[0][:200])
            return AtomResult(outcome=OUTCOME_BLOCKED,
                              detail=f"滑块回放异常：{e}")

        ctx.report_progress({"phase": "done", "solved": solved})
        if solved:
            ctx.emit("success", "滑块验证已通过",
                     {"worker": ctx.worker_id, "url": page.url[:80]})
            return AtomResult(outcome=OUTCOME_OK,
                              detail="滑块验证已通过",
                              data={"slider": True, "solved": True})
        ctx.emit("warning",
                 f"滑块 {max_rounds} 层 × {max_attempts} 次均未通过",
                 {"worker": ctx.worker_id})
        return AtomResult(outcome=OUTCOME_BLOCKED,
                          detail=f"滑块未通过（{max_rounds} 层 × "
                                 f"{max_attempts} 次尝试）",
                          data={"slider": True, "solved": False})
