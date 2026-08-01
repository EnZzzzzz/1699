# -*- coding: utf-8 -*-
"""Celery 任务共享运行时：任务状态/进度写库、协作式停止检查、心跳线程、实时事件流。

emit(level, message, data)：写 task_events 表（每任务保留最近 500 条）+
发布 Redis pub/sub（task_events:{task_id}）。写库失败 / Redis 失败只记日志，
绝不阻塞或中断采集主流程。
"""
from __future__ import annotations

import json
import random
import threading
import time
from collections import deque

from loguru import logger

from ..db import SessionLocal
from ..models import Task, TaskEvent
from .. import config as app_config
from .pool_client import clear_heartbeat, heartbeat

TERMINAL_STATUSES = ("done", "failed", "stopped")
EVENT_KEEP_PER_TASK = 500

# 状态迁移 -> 自动事件（级别, 消息模板）
_STATUS_EVENTS = {
    "running": ("info", "任务开始运行"),
    "stopping": ("warning", "收到停止请求，等待当前步骤安全收尾"),
    "done": ("success", "任务完成"),
    "failed": ("error", "任务失败"),
    "stopped": ("warning", "任务已停止"),
}


class TaskRuntime:
    """任务运行期上下文（Celery task 内使用，多线程安全）。

    - stop_requested(): 每 ~2s 轮询 tasks.stop_requested（协作式停止）
    - heartbeat 线程：每 5s 写 Redis 心跳（PoolManager.reclaim_stale 兜底）
    - track(n): 计数 + 滑窗速率（progress_json.per_minute）
    - emit(): 实时事件流（写库 + Redis pub/sub，失败不阻塞）
    """

    def __init__(self, task_id: int):
        self.task_id = task_id
        self._stop_cache = (0.0, False)
        self._lock = threading.Lock()
        self._events: deque[float] = deque()
        self.collected = 0
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None

    # ---------------- 事件流 ----------------
    def emit(self, level: str, message: str, data: dict | None = None) -> int | None:
        """写一条任务事件（线程安全；任何失败只记日志）。返回事件 id。"""
        try:
            ev = TaskEvent(task_id=self.task_id, ts=app_config.now_str(),
                           level=level, message=message,
                           data_json=json.dumps(data, ensure_ascii=False)
                           if data else None)
            with SessionLocal() as db:
                db.add(ev)
                # flush 在会话内分配自增 id；to_dict 也必须在会话内完成——
                # commit 后属性会过期（expire_on_commit 默认 True），
                # 会话关闭后再读 ev 属性会抛 "not bound to a Session"
                db.flush()
                payload = ev.to_dict()
                db.commit()
                # 每任务保留最近 500 条
                db.query(TaskEvent).filter(
                    TaskEvent.task_id == self.task_id,
                    TaskEvent.id <= payload["id"] - EVENT_KEEP_PER_TASK).delete()
                db.commit()
            self._publish(payload)
            return payload["id"]
        except Exception as e:  # noqa: BLE001 - emit 绝不阻塞主流程
            logger.warning("task {} emit 失败（忽略）: {}", self.task_id, e)
            return None

    def _publish(self, payload: dict) -> None:
        """Redis pub/sub fire-and-forget（Redis 挂了不影响主流程）。"""
        try:
            from .pool_client import _redis
            r = _redis()
            if r is not None:
                r.publish(f"task_events:{self.task_id}",
                          json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            logger.debug("task {} 事件发布 Redis 失败（忽略）: {}",
                         self.task_id, e)

    # ---------------- 状态写库 ----------------
    def set_status(self, status: str, **fields) -> None:
        error = fields.get("error")
        with SessionLocal() as db:
            t = db.get(Task, self.task_id)
            if t is None:
                return
            # 已进入终态的任务不再被覆盖（stop 竞态保护）
            if t.status in TERMINAL_STATUSES and status not in TERMINAL_STATUSES:
                return
            t.status = status
            if status == "running" and not t.started_at:
                t.started_at = app_config.now_str()
            if status in TERMINAL_STATUSES:
                t.finished_at = app_config.now_str()
            for k, v in fields.items():
                setattr(t, k, v)
            db.commit()
        logger.info("task {} 状态 -> {}{}", self.task_id, status,
                    f"（{error}）" if error else "")
        # 阶段变化自动 emit
        tpl = _STATUS_EVENTS.get(status)
        if tpl:
            level, msg = tpl
            data = {"status": status}
            if error:
                msg = f"{msg}：{error}"
                data["error"] = error
            self.emit(level, msg, data)

    def set_progress(self, **fields) -> None:
        with SessionLocal() as db:
            t = db.get(Task, self.task_id)
            if t is None:
                return
            prog = json.loads(t.progress_json) if t.progress_json else {}
            prog.update(fields)
            t.progress_json = json.dumps(prog, ensure_ascii=False)
            db.commit()

    def set_error(self, error: str) -> None:
        with SessionLocal() as db:
            t = db.get(Task, self.task_id)
            if t:
                t.error = error[:2000]
                db.commit()

    # ---------------- 协作式停止 ----------------
    def stop_requested(self) -> bool:
        now = time.time()
        cached_at, cached_val = self._stop_cache
        if now - cached_at < 2.0:
            return cached_val
        with SessionLocal() as db:
            t = db.get(Task, self.task_id)
            val = bool(t and t.stop_requested)
        self._stop_cache = (now, val)
        return val

    # ---------------- 计数 / 速率 ----------------
    def track(self, n: int = 1) -> None:
        with self._lock:
            self.collected += n
            now = time.time()
            for _ in range(n):
                self._events.append(now)
            while self._events and self._events[0] < now - 60:
                self._events.popleft()

    def per_minute(self) -> float:
        with self._lock:
            now = time.time()
            while self._events and self._events[0] < now - 60:
                self._events.popleft()
            return float(len(self._events))

    # ---------------- 心跳线程 ----------------
    def start_heartbeat(self, interval: float = 5.0) -> None:
        def loop():
            while not self._hb_stop.is_set():
                heartbeat(self.task_id)
                self._hb_stop.wait(interval)
        self._hb_thread = threading.Thread(target=loop, daemon=True,
                                           name=f"hb-{self.task_id}")
        self._hb_thread.start()

    def close(self) -> None:
        self._hb_stop.set()
        if self._hb_thread:
            self._hb_thread.join(timeout=3)
        clear_heartbeat(self.task_id)


def start_delay_countdown(rt: TaskRuntime, delay_min: float,
                          delay_max: float) -> bool:
    """启动前等待：在 [delay_min, delay_max] 内随机抽一个等待时长并倒计时。

    都为 0 → 不等待；相等 → 固定等该秒数；不等 → random.uniform 抽签。
    不合法输入宽容归一化（负值取 0、max<min 时交换）并在事件/日志注明。
    倒计时每 10s 一条事件，期间每 ~2s 检查停止。

    返回 True=倒计时结束可以开始执行；False=等待期间收到停止请求
    （调用方负责置 stopped 终态并返回，此时未占用任何通道/浏览器资源）。
    """
    lo, hi = float(delay_min or 0), float(delay_max or 0)
    if lo < 0 or hi < 0:
        lo, hi = max(0.0, lo), max(0.0, hi)
        logger.warning("task {} start_delay 存在负值，已按 0 归一化为 {}~{}",
                       rt.task_id, lo, hi)
        rt.emit("warning", f"启动等待参数存在负值，已按 {lo:g}~{hi:g} 秒归一化")
    if hi < lo:
        lo, hi = hi, lo
        logger.warning("task {} start_delay min>max，已交换归一化为 {}~{}",
                       rt.task_id, lo, hi)
        rt.emit("warning", f"启动等待参数下限大于上限，已按 {lo:g}~{hi:g} 秒"
                "交换归一化")
    if hi <= 0:
        return True
    seconds = lo if lo == hi else random.uniform(lo, hi)
    shown = int(round(seconds))
    range_note = f"（随机区间 {lo:g}~{hi:g} 秒）" if lo != hi else ""
    rt.emit("info", f"将于 {shown} 秒后开始执行{range_note}"
            "（等待期间可停止，不占用通道资源）",
            {"seconds": shown, "delay_min": lo, "delay_max": hi})
    deadline = time.monotonic() + seconds
    announced: set[int] = set()
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        if rt.stop_requested():
            rt.emit("warning", "启动前等待期间收到停止请求，任务取消",
                    {"remaining": int(left)})
            return False
        elapsed_step = int(seconds - left) // 10 * 10
        if (elapsed_step > 0 and elapsed_step not in announced
                and left > 2):  # 末尾不足 2s 不再报"剩余 0 秒"
            announced.add(elapsed_step)
            rt.emit("info", f"倒计时：剩余 {int(round(left))} 秒",
                    {"remaining": int(round(left))})
        time.sleep(min(2.0, left))
    rt.emit("info", "开始执行")
    return True
