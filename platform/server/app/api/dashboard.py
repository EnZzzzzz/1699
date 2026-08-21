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
        # 防御性探测 wa 列是否存在（迁移可能未执行）；列缺失时 wa 统计返回 0
        cols = {row[1] for row in cur.execute("PRAGMA table_info(contacts)").fetchall()}
        if "wa_registered" in cols and "wa_checked_at" in cols:
            c_wa_reg, c_wa_unreg, c_wa_unchecked = cur.execute(
                "SELECT "
                "SUM(CASE WHEN wa_registered = 1 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN wa_registered = 0 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN wa_registered IS NULL THEN 1 ELSE 0 END) "
                "FROM contacts").fetchone()
        else:
            c_wa_reg = c_wa_unreg = c_wa_unchecked = 0
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
            "wa_registered": c_wa_reg or 0,
            "wa_unregistered": c_wa_unreg or 0,
            "wa_unchecked": c_wa_unchecked or 0,
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


def _resolve_window(period, hours, start, end, table_col_pairs):
    """解析统计窗口 [win_start, win_end]（带 TZ）。两种用法：
    - hours=N：最近 N 小时（终点取 table_col_pairs 各时间列最大值）
    - period=today|yesterday|7d|30d|custom：预设/自定义时间段（按自然日界）
      custom 需 start（YYYY-MM-DD[ HH:MM[:SS]]），end 可缺省=现在
    返回 (win_start, win_end, error)；error 非 None 时为可直接返回前端的 dict。
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
                return None, None, {"error": "custom 模式需提供 start 参数"}
            try:
                win_start = _parse_dt(start, is_end=False)
                win_end = _parse_dt(end, is_end=True) if end else now_real
            except ValueError:
                return None, None, {"error": f"时间格式无法解析: start={start!r} end={end!r}"}
        else:
            return None, None, {"error": f"未知 period: {period!r}"}
    else:
        hours = hours or 12
        with connect() as conn:
            now_str = _max_time(conn.cursor(), table_col_pairs)
        win_end = (datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                   if now_str else now_real)
        win_start = win_end - timedelta(hours=hours)
    return win_start, win_end, None


def _bucket_axis(win_start: datetime, win_end: datetime):
    """分桶轴：窗口 ≤48h 按小时桶，否则按天桶。
    返回 (bucket, label_fmt, step, span_h)。"""
    span_h = (win_end - win_start).total_seconds() / 3600
    bucket = "hour" if span_h <= 48 else "day"
    label_fmt = "%m-%d %H:00" if bucket == "hour" else "%m-%d"
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    return bucket, label_fmt, step, span_h


@router.get("/pipeline")
def pipeline(period: str = Query(default=None),
             hours: int = Query(default=None, ge=1, le=720),
             start: str = Query(default=None),
             end: str = Query(default=None)):
    """管道平衡统计。参数用法见 _resolve_window。
    粒度自适应：窗口 ≤48h 按小时桶，否则按天桶。
    """
    win_start, win_end, err = _resolve_window(
        period, hours, start, end,
        [("contacts", "scraped_at"), ("shops", "first_seen_at"),
         ("shops", "last_seen_at")])
    if err:
        return err

    bucket, label_fmt, step, span_h = _bucket_axis(win_start, win_end)

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


# fb_contacts 来源判别：X 帖 URL 含 x.com / twitter.com，其余归 FB
_X_COND = "(post_url LIKE '%x.com%' OR post_url LIKE '%twitter.com%')"

# WA 查号单价（与 app/costs.py、scraper/wa_check_apify.py:214 一致，改价三处同步）
_WA_COST_PER_NUMBER = 0.004


def _window_costs(cur, start_str: str, end_str: str,
                  win_start: datetime, win_end: datetime,
                  fb_reg: int, x_reg: int):
    """窗口成本估算（与时间范围对齐）。

    - FB/X 采集成本：cost_records 估算行（date 为北京日期）按天取出，
      窗口只覆盖某天一部分时按「窗口内采集数 / 当天采集数」折算；
      cost_records 表不存在（migrate 未跑）时返回 None，前端隐藏成本行
    - WA 校验成本：wa_checked_at 落窗条数 × $0.004（真实单价，窗口精确）
    - per_registered = 窗口总成本 / 窗口内采集且已注册数（采集口径）；
      fb_per/x_per 为各渠道「每个已注册样本」成本，wa_per 为每校验号成本
    """
    tables = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "cost_records" not in tables:
        return None
    d0 = win_start.strftime("%Y-%m-%d")
    d1 = win_end.strftime("%Y-%m-%d")
    # 每日估算费用：FB = memo23 + SERP，X = x_keyword
    daily_usd: dict = {}
    for date, channel, usd in cur.execute(
            "SELECT date, channel, SUM(usd) FROM cost_records"
            " WHERE source='estimate'"
            " AND channel IN ('fb_memo23', 'fb_serp', 'x_keyword')"
            " AND date BETWEEN ? AND ? GROUP BY date, channel",
            (d0, d1)).fetchall():
        slot = daily_usd.setdefault(date, {"fb": 0.0, "x": 0.0})
        if channel == "x_keyword":
            slot["x"] += usd or 0
        else:
            slot["fb"] += usd or 0
    # 窗口内按天采集数（FB/X 分列）
    win_cnt = {d: (x or 0, fb or 0) for d, x, fb in cur.execute(
        f"SELECT substr(first_seen_at, 1, 10), SUM({_X_COND}),"
        f" SUM(NOT {_X_COND}) FROM fb_contacts"
        " WHERE first_seen_at BETWEEN ? AND ? GROUP BY 1",
        (start_str, end_str)).fetchall()}
    # 这些天的全天采集数（折算分母）
    day_cnt = {d: (x or 0, fb or 0) for d, x, fb in cur.execute(
        f"SELECT substr(first_seen_at, 1, 10), SUM({_X_COND}),"
        f" SUM(NOT {_X_COND}) FROM fb_contacts"
        " WHERE substr(first_seen_at, 1, 10) BETWEEN ? AND ? GROUP BY 1",
        (d0, d1)).fetchall()}

    def _share(channel: str, idx: int) -> float:
        cost = 0.0
        for date, usd_slot in daily_usd.items():
            usd = usd_slot[channel]
            total = day_cnt.get(date, (0, 0))[idx]
            if usd and total:
                cost += usd * win_cnt.get(date, (0, 0))[idx] / total
        return cost

    fb_cost = _share("fb", 1)
    x_cost = _share("x", 0)
    checked = cur.execute(
        "SELECT COUNT(*) FROM fb_contacts WHERE wa_checked_at BETWEEN ? AND ?",
        (start_str, end_str)).fetchone()[0]
    wa_cost = checked * _WA_COST_PER_NUMBER
    total = fb_cost + x_cost + wa_cost
    registered = fb_reg + x_reg
    return {
        "fb": round(fb_cost, 4),
        "x": round(x_cost, 4),
        "wa": round(wa_cost, 4),
        "total": round(total, 4),
        "per_registered": round(total / registered, 4)
        if registered else None,
        "fb_per": round(fb_cost / fb_reg, 4) if fb_reg else None,
        "x_per": round(x_cost / x_reg, 4) if x_reg else None,
        "wa_per": round(wa_cost / checked, 4) if checked else None,
        "currency": "USD",
    }


@router.get("/fb-pipeline")
def fb_pipeline(period: str = Query(default=None),
                hours: int = Query(default=None, ge=1, le=720),
                start: str = Query(default=None),
                end: str = Query(default=None)):
    """FB/X 采号管道统计（fb_contacts）。参数用法同 /pipeline。
    - 采集量：first_seen_at 落窗，按 post_url 分 FB / X
    - WA 查号：wa_checked_at 落窗，分已注册 / 未注册（totals.wa_registered/wa_unregistered、
      rates.wa_check、buckets 的查号转化均为查号时间口径，反映查号工作量）
    - totals.fb_wa_*/x_wa_*/fb_pending/x_pending 为采集时间口径（窗口内采集的号
      当前的查号结果），与采集量对齐：fb = 已注册 + 未注册 + 待查
    - 快照（与窗口无关）：FB/X 全表总数及已注册数 + 待确认总数 + 全表注册率
    """
    win_start, win_end, err = _resolve_window(
        period, hours, start, end,
        [("fb_contacts", "first_seen_at"), ("fb_contacts", "wa_checked_at")])
    if err:
        return err

    bucket, label_fmt, step, span_h = _bucket_axis(win_start, win_end)
    start_str = win_start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = win_end.strftime("%Y-%m-%d %H:%M:%S")
    args = (start_str, end_str)

    with connect() as conn:
        cur = conn.cursor()
        t_x, t_fb = cur.execute(
            f"SELECT SUM({_X_COND}), SUM(NOT {_X_COND}) FROM fb_contacts"
            " WHERE first_seen_at BETWEEN ? AND ?", args).fetchone()
        w_reg, w_unreg = cur.execute(
            "SELECT SUM(wa_registered = 1), SUM(wa_registered = 0) FROM fb_contacts"
            " WHERE wa_checked_at BETWEEN ? AND ?", args).fetchone()
        # 窗口内采集的号码按查号结果细分（FB / X），与采集量同口径：
        # fb = fb_wa_registered + fb_wa_unregistered + fb_pending 恒成立
        w_x_reg, w_x_unreg, w_fb_reg, w_fb_unreg = cur.execute(
            f"SELECT SUM(({_X_COND}) AND wa_registered = 1),"
            f" SUM(({_X_COND}) AND wa_registered = 0),"
            f" SUM((NOT {_X_COND}) AND wa_registered = 1),"
            f" SUM((NOT {_X_COND}) AND wa_registered = 0) FROM fb_contacts"
            " WHERE first_seen_at BETWEEN ? AND ?", args).fetchone()
        # 窗口内采集但尚未查号的数量（按来源细分），用于补齐「采集 = 已注册 + 未注册 + 待查」
        # 待查口径用 wa_registered IS NULL（存在 wa_checked_at 已写但结果 NULL 的查询失败行）
        w_x_pend, w_fb_pend = cur.execute(
            f"SELECT SUM({_X_COND}), SUM(NOT {_X_COND}) FROM fb_contacts"
            " WHERE first_seen_at BETWEEN ? AND ? AND wa_registered IS NULL",
            args).fetchone()
        snap_pending = cur.execute(
            "SELECT COUNT(*) FROM fb_contacts WHERE wa_registered IS NULL"
        ).fetchone()[0]
        # 待核实按来源细分（FB / X）
        snap_x_pending, snap_fb_pending = cur.execute(
            f"SELECT SUM({_X_COND}), SUM(NOT {_X_COND}) FROM fb_contacts"
            " WHERE wa_registered IS NULL").fetchone()
        snap_reg, snap_unreg = cur.execute(
            "SELECT SUM(wa_registered = 1), SUM(wa_registered = 0) FROM fb_contacts"
        ).fetchone()
        snap_x, snap_fb = cur.execute(
            f"SELECT SUM({_X_COND}), SUM(NOT {_X_COND}) FROM fb_contacts"
        ).fetchone()
        snap_x_reg, snap_fb_reg = cur.execute(
            f"SELECT SUM(({_X_COND}) AND wa_registered = 1),"
            f" SUM((NOT {_X_COND}) AND wa_registered = 1) FROM fb_contacts"
        ).fetchone()
        new_map = {h: (n, x or 0) for h, n, x in cur.execute(f"""
            SELECT strftime('{label_fmt}', first_seen_at), COUNT(*), SUM({_X_COND})
            FROM fb_contacts WHERE first_seen_at BETWEEN ? AND ? GROUP BY 1""",
            args).fetchall()}
        chk_map = {h: (reg or 0, unreg or 0) for h, reg, unreg in cur.execute(f"""
            SELECT strftime('{label_fmt}', wa_checked_at),
                   SUM(wa_registered = 1), SUM(wa_registered = 0)
            FROM fb_contacts WHERE wa_checked_at BETWEEN ? AND ? GROUP BY 1""",
            args).fetchall()}
        costs = _window_costs(cur, start_str, end_str, win_start, win_end,
                              w_fb_reg or 0, w_x_reg or 0)

    buckets = []
    cur_t = win_start.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        cur_t = cur_t.replace(hour=0)
    while cur_t <= win_end:
        label = cur_t.strftime(label_fmt)
        n, x = new_map.get(label, (0, 0))
        reg, unreg = chk_map.get(label, (0, 0))
        buckets.append({
            "label": label,
            "fb": n - x,
            "x": x,
            "wa_registered": reg,
            "wa_unregistered": unreg,
        })
        cur_t += step

    t_fb, t_x = t_fb or 0, t_x or 0
    w_reg, w_unreg = w_reg or 0, w_unreg or 0
    snap_total_checked = (snap_reg or 0) + (snap_unreg or 0)
    divisor = max(span_h if bucket == "hour" else span_h / 24, 0.01)
    return {
        "window": {"start": start_str, "end": end_str, "bucket": bucket},
        "totals": {"fb": t_fb, "x": t_x,
                   "wa_registered": w_reg, "wa_unregistered": w_unreg,
                   "fb_wa_registered": w_fb_reg or 0,
                   "fb_wa_unregistered": w_fb_unreg or 0,
                   "x_wa_registered": w_x_reg or 0,
                   "x_wa_unregistered": w_x_unreg or 0,
                   "fb_pending": w_fb_pend or 0,
                   "x_pending": w_x_pend or 0},
        "snapshot": {
            "fb_total": snap_fb or 0,
            "x_total": snap_x or 0,
            "fb_registered": snap_fb_reg or 0,
            "x_registered": snap_x_reg or 0,
            "pending": snap_pending,
            "fb_pending": snap_fb_pending or 0,
            "x_pending": snap_x_pending or 0,
            "reg_rate": round((snap_reg or 0) / snap_total_checked, 4)
                        if snap_total_checked else None,
        },
        "rates": {
            "unit": "每小时" if bucket == "hour" else "每天",
            "fb": round(t_fb / divisor, 2),
            "x": round(t_x / divisor, 2),
            "wa_check": round((w_reg + w_unreg) / divisor, 2),
        },
        "costs": costs,
        "buckets": buckets,
    }
