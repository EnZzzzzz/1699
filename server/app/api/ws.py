# -*- coding: utf-8 -*-
"""WebSocket 聚合推送。

下行帧（1s 节流，无变化去重）：
    {type:'pool_status', channels}
    {type:'task_progress', task}
    {type:'task_event', task_id, event:{id,ts,level,message,data}}  —— 需订阅

上行（客户端 -> 服务端）：
    {"subscribe_task": <id>}                关注某任务事件（默认从最新事件起收）
    {"subscribe_task": <id>, "after_id": n} 从指定事件 id 之后起收（补历史）
    {"unsubscribe_task": <id>}              取消关注

事件推送采用每连接增量轮询（按 task_events.id > last_id），多连接各自独立；
连接断开时订阅状态随连接回收，无泄漏。
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from ..db import SessionLocal
from ..models import Task, TaskEvent
from ..services import usage as usage_service

router = APIRouter()

ACTIVE_STATUSES = ("pending", "waiting_channel", "running", "stopping")


def _snapshot(app) -> dict:
    """采集一帧推送数据（同步，在线程池执行）。"""
    with SessionLocal() as db:
        tasks = [t.to_dict() for t in db.query(Task)
                 .filter(Task.status.in_(ACTIVE_STATUSES))
                 .order_by(Task.id.desc()).all()]
        channels = app.state.pool.list_channels()
        counts = usage_service.channel_counts(5)
        series = usage_service.channel_minute_series(5)
        task_types = {t["id"]: t["type"] for t in tasks}
        for ch in channels:
            ch["requests_5m"] = counts.get(ch["id"], 0)
            ch["freq_5m"] = series.get(ch["id"], [0] * 5)
            ch["used_by_task_type"] = task_types.get(ch["used_by_task"]) \
                if ch["used_by_task"] else None
    return {"tasks": tasks, "channels": channels}


def _latest_event_id(task_id: int) -> int:
    with SessionLocal() as db:
        ev = (db.query(TaskEvent).filter(TaskEvent.task_id == task_id)
              .order_by(TaskEvent.id.desc()).first())
        return ev.id if ev else 0


def _fetch_new_events(subs: dict[int, int]) -> dict[int, list[dict]]:
    """按订阅增量取新事件：{task_id: [event, ...]}，并推进 last_id。"""
    out: dict[int, list[dict]] = {}
    with SessionLocal() as db:
        for task_id, last_id in list(subs.items()):
            rows = (db.query(TaskEvent)
                    .filter(TaskEvent.task_id == task_id,
                            TaskEvent.id > last_id)
                    .order_by(TaskEvent.id).limit(100).all())
            if rows:
                out[task_id] = [e.to_dict() for e in rows]
                subs[task_id] = rows[-1].id
    return out


@router.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    app = websocket.app
    last_payload = None
    subs: dict[int, int] = {}  # task_id -> 已推送到的事件 id
    try:
        while True:
            # 用 receive 做断开探测 + 接收订阅指令（超时 1s 即为本轮节流间隔）
            try:
                raw = await asyncio.wait_for(websocket.receive_text(),
                                             timeout=1.0)
                try:
                    msg = json.loads(raw)
                except ValueError:
                    msg = None
                if isinstance(msg, dict):
                    if "subscribe_task" in msg:
                        tid = int(msg["subscribe_task"])
                        if "after_id" in msg:
                            subs[tid] = max(0, int(msg["after_id"]))
                        elif tid not in subs:
                            # 默认从最新事件起收（历史走 REST /events 增量补）
                            subs[tid] = await asyncio.to_thread(
                                _latest_event_id, tid)
                    elif "unsubscribe_task" in msg:
                        subs.pop(int(msg["unsubscribe_task"]), None)
            except asyncio.TimeoutError:
                pass

            try:
                snap, new_events = await asyncio.gather(
                    asyncio.to_thread(_snapshot, app),
                    asyncio.to_thread(_fetch_new_events, subs) if subs
                    else asyncio.sleep(0, result={}),
                )
            except Exception as e:  # noqa: BLE001 - 单帧失败不断线
                logger.warning("WS 快照失败: {}", e)
                continue

            frames = [{"type": "pool_status", "channels": snap["channels"]}]
            frames += [{"type": "task_progress", "task": t} for t in snap["tasks"]]
            payload = json.dumps(frames, ensure_ascii=False, sort_keys=True)
            if payload != last_payload:  # 无变化不重发
                for frame in frames:
                    await websocket.send_text(
                        json.dumps(frame, ensure_ascii=False))
                last_payload = payload
            for task_id, events in new_events.items():
                for ev in events:
                    await websocket.send_text(json.dumps(
                        {"type": "task_event", "task_id": task_id,
                         "event": ev}, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.info("WS 连接结束: {}", e)
    finally:
        subs.clear()  # 订阅状态随连接回收
