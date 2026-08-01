# -*- coding: utf-8 -*-
"""Dashboard 总览（前端契约字段名）。现有 5 表走原生 SQL（只读）。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Task

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _rate_last_hour(db: Session) -> list[int]:
    """近 60 分钟每分钟新增店铺数（长度 60，最旧在前、当前分钟在后）。"""
    now = time.time()
    lt = time.localtime(now - 59 * 60)
    start_epoch = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                               lt.tm_hour, lt.tm_min, 0, 0, 0, -1))
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_epoch))
    rows = db.execute(
        text("SELECT first_seen_at FROM shops WHERE first_seen_at >= :c"),
        {"c": cutoff}).scalars().all()
    buckets = [0] * 60
    for ts in rows:
        try:
            epoch = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError):
            continue
        idx = int((epoch - start_epoch) // 60)
        if 0 <= idx < 60:
            buckets[idx] += 1
    return buckets


@router.get("/overview")
def overview(request: Request, db: Session = Depends(get_db)):
    """总览：总店铺、pending、今日新增、运行任务数、通道占用、近1小时速率。"""
    today = time.strftime("%Y-%m-%d 00:00:00")
    q = lambda sql, **kw: db.execute(text(sql), kw).scalar()  # noqa: E731

    occupancy = request.app.state.pool.occupancy()
    running_tasks = db.query(Task).filter(Task.status == "running").count()

    return {
        "total_shops": q("SELECT COUNT(*) FROM shops"),
        "pending_shops": q("SELECT COUNT(*) FROM shops WHERE status='pending'"),
        "today_new": q("SELECT COUNT(*) FROM shops WHERE first_seen_at >= :t", t=today),
        "running_tasks": running_tasks,
        "channels_total": occupancy["total"],
        "channels_in_use": occupancy["in_use"],
        "rate_last_hour": _rate_last_hour(db),
    }
