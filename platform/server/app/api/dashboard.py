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


def _parse_dt(s: str, is_end: bool) -> datetime:
    """解析 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM[:SS]'，日期型按当天起/止。"""
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=TZ)
    return d + (timedelta(days=1, seconds=-1) if is_end else timedelta())


@router.get("/pipeline")
def pipeline(period: str = Query(default=None),
             hours: int = Query(default=None, ge=1, le=720),
             start: str = Query(default=None),
             end: str = Query(default=None)):
    """管道平衡统计。两种用法：
    - hours=N：最近 N 小时（向后兼容，终点取数据最大时间）
    - period=today|yesterday|7d|30d|custom：预设/自定义时间段（按自然日界）
      custom 需 start（YYYY-MM-DD[ HH:MM[:SS]]），end 可缺省=现在
    粒度自适应：窗口 ≤48h 按小时桶，否则按天桶。
    """
    now_real = datetime.now(TZ)

    if period:
        today0 = now_real.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "today":
            win_start, win_end = today0, now_real
        elif period == "yesterday":
            win_start = today0 - timedelta(days=1)
            win_end = today0 - timedelta(seconds=1)
        elif period == "7d":
            win_start, win_end = now_real - timedelta(days=7), now_real
        elif period == "30d":
            win_start, win_end = now_real - timedelta(days=30), now_real
        elif period == "custom":
            if not start:
                return {"error": "custom 模式需提供 start 参数"}
            try:
                win_start = _parse_dt(start, is_end=False)
                win_end = _parse_dt(end, is_end=True) if end else now_real
            except ValueError:
                return {"error": f"时间格式无法解析: start={start!r} end={end!r}"}
        else:
            return {"error": f"未知 period: {period!r}"}
    else:
        hours = hours or 12
        with connect() as conn:
            now_str = _max_time(conn.cursor(), [("contacts", "scraped_at"),
                                                ("shops", "first_seen_at"),
                                                ("shops", "last_seen_at")])
        win_end = (datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                   if now_str else now_real)
        win_start = win_end - timedelta(hours=hours)

    span_h = (win_end - win_start).total_seconds() / 3600
    bucket = "hour" if span_h <= 48 else "day"
    label_fmt = "%m-%d %H:00" if bucket == "hour" else "%m-%d"
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)

    start_str = win_start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = win_end.strftime("%Y-%m-%d %H:%M:%S")

    with connect() as conn:
        cur = conn.cursor()
        backlog = cur.execute(
            "SELECT COUNT(*) FROM shops WHERE status = 'pending'").fetchone()[0]
        collected = cur.execute(
            "SELECT COUNT(*) FROM shops WHERE first_seen_at BETWEEN ? AND ?",
            (start_str, end_str)).fetchone()[0]
        consumed = cur.execute(
            "SELECT COUNT(*) FROM contacts WHERE scraped_at BETWEEN ? AND ?",
            (start_str, end_str)).fetchone()[0]
        collect_map = dict(cur.execute(f"""
            SELECT strftime('{label_fmt}', first_seen_at), COUNT(*)
            FROM shops WHERE first_seen_at BETWEEN ? AND ? GROUP BY 1""",
            (start_str, end_str)).fetchall())
        consume_map = dict(cur.execute(f"""
            SELECT strftime('{label_fmt}', scraped_at), COUNT(*)
            FROM contacts WHERE scraped_at BETWEEN ? AND ? GROUP BY 1""",
            (start_str, end_str)).fetchall())

    buckets = []
    cur_t = win_start.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        cur_t = cur_t.replace(hour=0)
    while cur_t <= win_end:
        label = cur_t.strftime(label_fmt)
        buckets.append({
            "label": label,
            "collected": collect_map.get(label, 0),
            "consumed": consume_map.get(label, 0),
        })
        cur_t += step

    divisor = max(span_h if bucket == "hour" else span_h / 24, 0.01)
    return {
        "window": {"start": start_str, "end": end_str, "bucket": bucket},
        "backlog": backlog,
        "totals": {"collected": collected, "consumed": consumed},
        "rates": {
            "unit": "每小时" if bucket == "hour" else "每天",
            "collect": round(collected / divisor, 2),
            "consume": round(consumed / divisor, 2),
        },
        "buckets": buckets,
    }
