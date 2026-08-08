# -*- coding: utf-8 -*-
"""dispatcher 可观测 API（P4）：daemon 存活 + 队列深度 + 消费者状态。

读方（平台）→ 写方（fetcher daemon 的 consumer_status / work_items）。
只 SELECT（app.db.connect），绝不写库。

- GET /api/dispatcher/status：daemon 存活（心跳新于 30s）+ 队列深度聚合
  + 今日 done 计数。
- GET /api/dispatcher/consumers：全量 consumer_status 行，附 offline
  标记（updated_at 超 30s）与解析后的 cooldowns_json。
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from fastapi import APIRouter

from app.db import DB_PATH, connect

router = APIRouter()

# 心跳新鲜度阈值（秒）：updated_at 距今超此值判定 daemon/消费者离线
STALE_SECONDS = 30

_BJ_NOW = datetime.now().strftime  # 北京时间字符串（与库内一致）


def _now_bj() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _is_stale(updated_at: str | None) -> bool:
    """updated_at 距今是否超过 STALE_SECONDS（离线判定）。"""
    if not updated_at:
        return True
    try:
        ts = time.mktime(time.strptime(updated_at, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return True
    return (time.time() - ts) > STALE_SECONDS


def daemon_alive() -> bool:
    """daemon 存活：consumer_status 存在心跳新于 30s 的行。"""
    with connect() as conn:
        row = conn.execute(
            "SELECT updated_at FROM consumer_status"
            " ORDER BY updated_at DESC LIMIT 1").fetchone()
    if not row:
        return False
    return not _is_stale(row["updated_at"])


def queue_depth() -> dict:
    """各队列 work_items 状态计数（GROUP BY queue, status）。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT queue, status, COUNT(*) FROM work_items"
            " GROUP BY queue, status").fetchall()
    depth: dict = {}
    for queue, status, cnt in rows:
        d = depth.setdefault(queue, {})
        d[status] = cnt
    return depth


def today_done() -> int:
    """今日（北京时间）done 计数。"""
    today = _now_bj()[:10]
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM work_items"
            " WHERE status='done' AND finished_at LIKE ?",
            (today + "%",)).fetchone()[0]


@router.get("/dispatcher/status")
def dispatcher_status():
    return {
        "daemon_alive": daemon_alive(),
        "queue_depth": queue_depth(),
        "today_done": today_done(),
    }


@router.get("/dispatcher/consumers")
def list_consumers():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM consumer_status").fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["offline"] = _is_stale(item.get("updated_at"))
        try:
            item["cooldowns"] = json.loads(item.get("cooldowns_json") or "{}")
        except (ValueError, TypeError):
            item["cooldowns"] = {}
        out.append(item)
    return out
