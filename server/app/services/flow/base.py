# -*- coding: utf-8 -*-
"""
Atom 契约（docs/flow-architecture.md §3.1）。

设计要点：
- 原子只负责"做一件事并报告结果分类"，不感知重试次数、不决策是否换 IP
  （策略由引擎层 FlowExecutor 的拦截器统一执行，见设计文档 §5.2）。
- 原子不直接操作通道池与浏览器生命周期，一律经 ctx.resources 访问。
- Context 保持轻量、可脱离 Celery/TaskRuntime 单测：rt 为 None 时
  emit/report_progress 退化为本地记录，停止语义由 stop_event 提供。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# 结果分类（引擎策略键 on_<outcome> 与之对应）
OUTCOME_OK = "ok"
OUTCOME_BLOCKED = "blocked"        # 疑似风控
OUTCOME_NET_ERROR = "net_error"    # 网络/代理故障
OUTCOME_EMPTY = "empty"            # 成功执行但无有效数据（如无联系方式）
OUTCOME_STOPPED = "stopped"        # 协作式停止触发
OUTCOME_TIMEOUT = "timeout"        # 等待类原子超时（如人工确认超时）


@dataclass
class AtomResult:
    """原子执行结果。outcome 见上方常量；detail 供事件消息；data 为产出数据。"""
    outcome: str = OUTCOME_OK
    detail: str = ""
    data: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK


class Context:
    """原子执行上下文（黑board + 资源代理 + 停止/进度通道）。

    属性：
        task_id / rt        任务标识与 TaskRuntime（单测时可为 None）
        resources           引擎管理的资源 dict（channel / browser / page /
                            pool_client / db 等），原子只取不管生命周期
        vars                节点间数据传递（如 claim_shops 产出的店铺列表）
        worker_id           并行容器内 worker 序号（顶层为 None）
        consecutive_fail    熔断计数（由引擎/容器维护，原子只读）
        progress            最近一次 report_progress 的数据
    """

    def __init__(
        self,
        *,
        task_id: int | None = None,
        rt: Any = None,
        resources: Optional[dict] = None,
        vars: Optional[dict] = None,
        worker_id: int | None = None,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        self.task_id = task_id
        self.rt = rt
        self.resources: dict = resources if resources is not None else {}
        self.vars: dict = vars if vars is not None else {}
        self.worker_id = worker_id
        self.consecutive_fail = 0
        self.progress: dict = {}
        self._stop_event = stop_event or threading.Event()

    # ---- 停止 ----
    def stop_requested(self) -> bool:
        if self._stop_event.is_set():
            return True
        rt = self.rt
        return bool(rt is not None and getattr(rt, "stop_requested", lambda: False)())

    def wait(self, seconds: float) -> bool:
        """停止感知的睡眠；返回 True 表示等待期间被停止。

        同时监听 stop_event 与 rt.stop_requested()（rt 侧走 DB 轮询，
        最快 1s 切片发现），两者任一触发即返回 True。
        """
        if seconds <= 0:
            return self.stop_requested()
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self.stop_requested()
            if self._stop_event.wait(min(remaining, 1.0)):
                return True
            rt = self.rt
            if rt is not None and getattr(rt, "stop_requested", lambda: False)():
                return True

    # ---- 观测 ----
    def emit(self, level: str, message: str, data: Optional[dict] = None) -> None:
        """发任务事件；rt 缺失时静默丢弃（单测可读取 self.progress 断言）。"""
        rt = self.rt
        if rt is not None:
            rt.emit(level, message, data)

    def report_progress(self, data: dict) -> None:
        """上报节点实时进度（如 sleep 的 {total, elapsed}）。"""
        self.progress.update(data)


class Atom:
    """原子基类。子类必须设置 name，并实现 run()。

    param_spec 为 Draft JSON Schema（object），供前端表单与保存前校验使用。
    inputs/outputs 声明读写的 ctx.resources / ctx.vars 键，仅作文档与校验。
    """

    name: str = ""
    title: str = ""
    inputs: dict = {}
    outputs: dict = {}
    param_spec: dict = {"type": "object", "properties": {}, "required": []}

    def run(self, ctx: Context, params: dict) -> AtomResult:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Atom {self.name!r}>"
