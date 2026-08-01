# -*- coding: utf-8 -*-
"""
通道使用事件记录与窗口聚合（docs/service-architecture.md §6）。

- Celery 任务每次请求经池上报一条 proxy_usage_events（支持批量）；
- 前端"近 N 分钟请求数 / 频率" = 按 channel_id 窗口聚合；
- 事件表保留 7 天，cleanup_old() 定时清理（默认由出口 IP 探测循环顺带执行）。
"""
from __future__ import annotations

import time
from typing import Iterable

from sqlalchemy import func

from ..db import SessionLocal
from ..models import ProxyUsageEvent


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _cutoff(minutes: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - minutes * 60))


def record_event(channel_id: int, task_id: int | None = None,
                 task_type: str | None = None, exit_ip: str | None = None,
                 result: str = "ok", ts: str | None = None) -> int:
    """记录一条使用事件，返回事件 id。"""
    with SessionLocal() as db:
        ev = ProxyUsageEvent(channel_id=channel_id, task_id=task_id,
                             task_type=task_type, exit_ip=exit_ip,
                             result=result, ts=ts or _now())
        db.add(ev)
        db.commit()
        return ev.id


def record_events(events: Iterable[dict]) -> int:
    """批量记录使用事件（worker 高频写时建议走批量）。返回写入条数。"""
    rows = [ProxyUsageEvent(
        channel_id=e["channel_id"], task_id=e.get("task_id"),
        task_type=e.get("task_type"), exit_ip=e.get("exit_ip"),
        result=e.get("result", "ok"), ts=e.get("ts") or _now(),
    ) for e in events]
    if not rows:
        return 0
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()
    return len(rows)


def channel_counts(minutes: int = 5) -> dict[int, int]:
    """近 N 分钟每通道请求数：{channel_id: count}。"""
    with SessionLocal() as db:
        rows = (db.query(ProxyUsageEvent.channel_id, func.count())
                .filter(ProxyUsageEvent.ts >= _cutoff(minutes))
                .group_by(ProxyUsageEvent.channel_id).all())
    return {cid: cnt for cid, cnt in rows}


def channel_minute_series(minutes: int = 5) -> dict[int, list[int]]:
    """近 N 分钟每通道的逐分钟请求数序列：{channel_id: [c1..cN]}（长度 N）。

    桶按本地时间分钟对齐，最旧在前、最新（当前分钟）在后，供迷你趋势图。
    """
    now = time.time()
    # 起点：N 分钟前的整分钟
    start = now - minutes * 60
    lt = time.localtime(start)
    start_epoch = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                               lt.tm_hour, lt.tm_min, 0, 0, 0, -1))
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_epoch))
    with SessionLocal() as db:
        rows = (db.query(ProxyUsageEvent.channel_id, ProxyUsageEvent.ts)
                .filter(ProxyUsageEvent.ts >= cutoff).all())
    out: dict[int, list[int]] = {}
    for cid, ts in rows:
        try:
            epoch = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        idx = int((epoch - start_epoch) // 60)
        if not 0 <= idx < minutes:
            continue
        series = out.setdefault(cid, [0] * minutes)
        series[idx] += 1
    return out


def window_stats(minutes: int = 5) -> dict:
    """近 N 分钟窗口聚合：总量、每分钟频率、按通道明细、按结果分布。"""
    cutoff = _cutoff(minutes)
    with SessionLocal() as db:
        per_channel = (db.query(ProxyUsageEvent.channel_id, func.count())
                       .filter(ProxyUsageEvent.ts >= cutoff)
                       .group_by(ProxyUsageEvent.channel_id).all())
        per_result = (db.query(ProxyUsageEvent.result, func.count())
                      .filter(ProxyUsageEvent.ts >= cutoff)
                      .group_by(ProxyUsageEvent.result).all())
    total = sum(c for _, c in per_channel)
    return {
        "minutes": minutes,
        "total": total,
        "rpm": round(total / max(minutes, 1), 2),
        "per_channel": [
            {"channel_id": cid, "count": cnt, "rpm": round(cnt / max(minutes, 1), 2)}
            for cid, cnt in sorted(per_channel)
        ],
        "per_result": {r or "unknown": c for r, c in per_result},
    }


def cleanup_old(days: int = 7) -> int:
    """清理 days 天前的旧事件，返回删除条数。"""
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S",
                           time.localtime(time.time() - days * 86400))
    with SessionLocal() as db:
        n = (db.query(ProxyUsageEvent)
             .filter(ProxyUsageEvent.ts < cutoff).delete())
        db.commit()
    return n
