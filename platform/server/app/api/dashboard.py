# -*- coding: utf-8 -*-
"""Dashboard 聚合接口。

pipeline 统计口径复用 util/contact_stats.py：
- 采集 = shops.first_seen_at 落窗
- 消耗 = contacts.scraped_at 落窗（done 口径；no_contact/failed 无时间戳未计入）
- 窗口终点 = contacts.scraped_at / shops.first_seen_at / shops.last_seen_at 三列最大值
- 时间戳均为北京时间，不做 +8 偏移
- 逐小时缺失补 0
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.db import connect

router = APIRouter(prefix="/dashboard")

TZ = ZoneInfo("Asia/Shanghai")


def _now_bj() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


@router.get("/overview")
def overview():
    with connect() as conn:
        cur = conn.cursor()
        shop_status = dict(cur.execute(
            "SELECT status, COUNT(*) FROM shops GROUP BY status").fetchall())
        c_total, c_mobile = cur.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN mobile IS NOT NULL AND mobile != '' THEN 1 ELSE 0 END) "
            "FROM contacts").fetchone()
        task_status = dict(cur.execute(
            "SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall())
    return {
        "ts": _now_bj(),
        "shops": {
            "pending": shop_status.get("pending", 0),
            "done": shop_status.get("done", 0),
            "no_contact": shop_status.get("no_contact", 0),
            "failed": shop_status.get("failed", 0),
            "total": sum(shop_status.values()),
        },
        "contacts": {
            "total": c_total,
            "with_mobile": c_mobile or 0,
        },
        "tasks": {
            "running": task_status.get("running", 0),
            "pending": task_status.get("pending", 0),
            "done": task_status.get("done", 0),
            "failed": task_status.get("failed", 0),
        },
    }


def _max_time(cur, table_col_pairs):
    """取多张表时间列的最大值作为窗口终点（与数据同一时钟域）。"""
    best = None
    for table, col in table_col_pairs:
        cur.execute(f"SELECT MAX({col}) FROM {table}")
        v = cur.fetchone()[0]
        if v and (best is None or v > best):
            best = v
    return best


@router.get("/pipeline")
def pipeline(hours: int = Query(default=3, ge=1, le=720)):
    with connect() as conn:
        cur = conn.cursor()

        now_str = _max_time(cur, [("contacts", "scraped_at"),
                                  ("shops", "first_seen_at"),
                                  ("shops", "last_seen_at")])
        if not now_str:
            return {
                "window": {"start": None, "end": None, "hours": hours},
                "backlog": 0,
                "rates": {"collect_per_hour": 0.0, "consume_per_hour": 0.0},
                "hourly": [],
            }

        now = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        start = now - timedelta(hours=hours)
        start_str = start.strftime("%Y-%m-%d %H:%M:%S")

        backlog = cur.execute(
            "SELECT COUNT(*) FROM shops WHERE status = 'pending'").fetchone()[0]

        collected = cur.execute(
            "SELECT COUNT(*) FROM shops WHERE first_seen_at >= ?",
            (start_str,)).fetchone()[0]
        consumed = cur.execute(
            "SELECT COUNT(*) FROM contacts WHERE scraped_at >= ?",
            (start_str,)).fetchone()[0]

        collect_hourly = dict(cur.execute("""
            SELECT strftime('%m-%d %H:00', first_seen_at), COUNT(*)
            FROM shops WHERE first_seen_at >= ? GROUP BY 1""",
            (start_str,)).fetchall())
        consume_hourly = dict(cur.execute("""
            SELECT strftime('%m-%d %H:00', scraped_at), COUNT(*)
            FROM contacts WHERE scraped_at >= ? GROUP BY 1""",
            (start_str,)).fetchall())

    hourly = []
    cur_hour = start.replace(minute=0, second=0, microsecond=0)
    end_hour = now.replace(minute=0, second=0, microsecond=0)
    while cur_hour <= end_hour:
        label = cur_hour.strftime("%m-%d %H:00")
        hourly.append({
            "label": label,
            "collected": collect_hourly.get(label, 0),
            "consumed": consume_hourly.get(label, 0),
        })
        cur_hour += timedelta(hours=1)

    return {
        "window": {
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": now.strftime("%Y-%m-%d %H:%M:%S"),
            "hours": hours,
        },
        "backlog": backlog,
        "rates": {
            "collect_per_hour": round(collected / hours, 2),
            "consume_per_hour": round(consumed / hours, 2),
        },
        "hourly": hourly,
    }
