# -*- coding: utf-8 -*-
"""IP 池状态 / 通道占用 / 使用统计 / acquire-release（docs/service-architecture.md §6/§8）。

acquire/release/events 端点是 M4 Celery 任务的对接约定：任务侧不直连厂商 API，
统一经本端点申请与归还通道、上报使用事件。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Task
from ..services import usage as usage_service

router = APIRouter(prefix="/api/pool", tags=["pool"])


class AcquireIn(BaseModel):
    task_id: int
    n: int = 1
    use_proxy: bool = True


class ReleaseIn(BaseModel):
    task_id: int


class SwapIn(BaseModel):
    task_id: int
    channel_id: int


class EventIn(BaseModel):
    channel_id: int
    task_id: int | None = None
    task_type: str | None = None
    exit_ip: str | None = None
    result: str = "ok"


def _pool(request: Request):
    return request.app.state.pool


@router.get("/channels")
def list_channels(request: Request, minutes: int = 5, db: Session = Depends(get_db)):
    """通道列表（含占用任务、出口 IP、过期时间、近5min请求数、逐分钟频率）。"""
    pool = _pool(request)
    channels = pool.list_channels()
    counts = usage_service.channel_counts(5)
    series = usage_service.channel_minute_series(5)
    task_types = {t.id: t.type for t in db.query(Task).all()}
    for ch in channels:
        n = counts.get(ch["id"], 0)
        ch["requests_5m"] = n
        ch["rpm_5m"] = round(n / 5, 2)
        ch["freq_5m"] = series.get(ch["id"], [0] * 5)
        ch["used_by_task_type"] = task_types.get(ch["used_by_task"]) \
            if ch["used_by_task"] else None
    return {"minutes": minutes, "channels": channels,
            "occupancy": pool.occupancy(), "waiting": pool.waiting()}


@router.get("/usage")
def usage(minutes: int = 5):
    """使用统计聚合（近 N 分钟请求数/频率/结果分布）。"""
    return usage_service.window_stats(minutes)


@router.post("/acquire")
def acquire(body: AcquireIn, request: Request):
    """任务申请 n 条通道；不足返回 channels=[] 且任务入等待队列（FIFO 唤醒）。"""
    if body.n < 1:
        raise HTTPException(status_code=400, detail="n 必须 >= 1")
    pool = _pool(request)
    channels = pool.acquire(body.task_id, body.n, body.use_proxy)
    return {"granted": bool(channels), "channels": channels,
            "waiting": pool.waiting()}


@router.post("/release")
def release(body: ReleaseIn, request: Request):
    """任务归还全部通道（幂等）；有等待任务时按 FIFO 自动分配。"""
    pool = _pool(request)
    released = pool.release(body.task_id)
    return {"released": released, "waiting": pool.waiting()}


@router.post("/swap")
def swap(body: SwapIn, request: Request):
    """原子换通道：释放指定通道并随机改占一条其他空闲通道。

    返回 {swapped, reused, channel}；reused=True 表示池内无其他空闲
    通道、继续持有原通道。通道不存在或不属于该任务时 409。
    """
    pool = _pool(request)
    ch = pool.swap_channel(body.task_id, body.channel_id)
    if ch is None:
        raise HTTPException(status_code=409,
                            detail=f"通道 {body.channel_id} 不存在"
                                   f"或不属于任务 {body.task_id}")
    reused = bool(ch.pop("reused", False))
    return {"swapped": not reused, "reused": reused, "channel": ch}


@router.post("/events", status_code=201)
def record_events(body: EventIn | list[EventIn]):
    """上报通道使用事件（单条或批量）。"""
    items = body if isinstance(body, list) else [body]
    n = usage_service.record_events([e.model_dump() for e in items])
    return {"recorded": n}
