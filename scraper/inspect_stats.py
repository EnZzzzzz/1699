#!/usr/bin/env python3
# 产量巡检：查 fb_contacts 在指定时间范围内的增量，输出 Markdown 表格报告（只读）。
# 用法：
#   python3 scraper/inspect_stats.py --since "2026-08-19 01:05:04"            # 累计 + 本小时新增
#   python3 scraper/inspect_stats.py --since "2026-08-19 01:05:04" --window 8 # 附最近 8 小时逐小时明细
#   python3 scraper/inspect_stats.py --from "2026-08-18 20:00:00" --to "2026-08-19 00:00:00"  # 任意范围
# 时间一律北京时间字符串（库内时间戳已是北京时间，直接字符串比较，不做换算）。
import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / ".cache" / "1688.db"
FMT = "%Y-%m-%d %H:%M:%S"

X_URL_COND = "(post_url LIKE '%x.com%' OR post_url LIKE '%twitter.com%')"


def parse_ts(s: str) -> datetime:
    """解析时间字符串（支持省略秒/分），返回 datetime。"""
    for f in (FMT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    raise SystemExit(f"无法解析时间: {s!r}（支持 'YYYY-MM-DD [HH:MM[:SS]]'）")


def counts(con: sqlite3.Connection, start: str, end: str) -> dict:
    """统计 [start, end) 内：FB 新增、X 新增、确认注册、确认未注册。"""
    args = (start, end)
    fb = con.execute(
        "SELECT COUNT(*) FROM fb_contacts"
        f" WHERE first_seen_at >= ? AND first_seen_at < ? AND NOT {X_URL_COND}",
        args).fetchone()[0]
    x = con.execute(
        "SELECT COUNT(*) FROM fb_contacts"
        f" WHERE first_seen_at >= ? AND first_seen_at < ? AND {X_URL_COND}",
        args).fetchone()[0]
    reg = con.execute(
        "SELECT COUNT(*) FROM fb_contacts"
        " WHERE wa_checked_at >= ? AND wa_checked_at < ? AND wa_registered = 1",
        args).fetchone()[0]
    unreg = con.execute(
        "SELECT COUNT(*) FROM fb_contacts"
        " WHERE wa_checked_at >= ? AND wa_checked_at < ? AND wa_registered = 0",
        args).fetchone()[0]
    return {"fb": fb, "x": x, "reg": reg, "unreg": unreg}


def rate(c: dict) -> str:
    tot = c["reg"] + c["unreg"]
    return f"{c['reg'] / tot * 100:.1f}%" if tot else "—"


def pending(con: sqlite3.Connection) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM fb_contacts WHERE wa_checked_at IS NULL"
    ).fetchone()[0]


def print_summary(cum: dict, win: dict, pend: int, win_label: str) -> None:
    print("| 指标 | 本次累计 | " + win_label + " |")
    print("|---|---|---|")
    print(f"| 采集联系人（FB） | {cum['fb']} | +{win['fb']} |")
    print(f"| 采集联系人（X） | {cum['x']} | +{win['x']} |")
    print(f"| 已确认注册 | {cum['reg']} | +{win['reg']} |")
    print(f"| 确认未注册 | {cum['unreg']} | +{win['unreg']} |")
    print(f"| 待确认 | {pend} | — |")
    print(f"| 注册率 | {rate(cum)} | — |")


def print_hourly(con: sqlite3.Connection, end: datetime, hours: int) -> None:
    """最近 hours 个小时桶（含当前小时），连续升序、无数据小时补 0。"""
    cur_hour = end.replace(minute=0, second=0)
    start = cur_hour - timedelta(hours=hours - 1)
    rows = con.execute(
        "SELECT substr(first_seen_at, 1, 13) h,"
        f" SUM({X_URL_COND}) x, COUNT(*) n FROM fb_contacts"
        " WHERE first_seen_at >= ? AND first_seen_at < ? GROUP BY h",
        (start.strftime(FMT), (cur_hour + timedelta(hours=1)).strftime(FMT))
    ).fetchall()
    new_by_h = {h: (n, x or 0) for h, x, n in rows}
    rows = con.execute(
        "SELECT substr(wa_checked_at, 1, 13) h, COUNT(*) n,"
        " SUM(wa_registered = 1) reg FROM fb_contacts"
        " WHERE wa_checked_at >= ? AND wa_checked_at < ? GROUP BY h",
        (start.strftime(FMT), (cur_hour + timedelta(hours=1)).strftime(FMT))
    ).fetchall()
    chk_by_h = {h: (n, reg or 0) for h, n, reg in rows}

    print(f"\n逐小时明细（最近 {hours} 小时）：\n")
    print("| 时间 | 新增 FB | 新增 X | 新增合计 | WA 查号 | 已注册 | 未注册 |")
    print("|---|---|---|---|---|---|---|")
    for i in range(hours):
        h = start + timedelta(hours=i)
        key = h.strftime("%Y-%m-%d %H")
        n, x = new_by_h.get(key, (0, 0))
        chk, reg = chk_by_h.get(key, (0, 0))
        print(f"| {key}:00 | {n - x} | {x} | {n} | {chk} | {reg} | {chk - reg} |")


def main() -> None:
    ap = argparse.ArgumentParser(description="fb_contacts 产量巡检（北京时间，Markdown 表格输出）")
    ap.add_argument("--since", help="累计口径起点（与 --from 二选一）")
    ap.add_argument("--window", type=int, default=0,
                    help="配合 --since：附最近 N 小时逐小时明细表")
    ap.add_argument("--from", dest="frm", help="范围起点（与 --to 搭配，只查该范围增量）")
    ap.add_argument("--to", help="范围终点，默认当前时间")
    args = ap.parse_args()

    if not DB.exists():
        raise SystemExit(f"库不存在: {DB}")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    end_dt = parse_ts(args.to) if args.to else datetime.now()
    end = end_dt.strftime(FMT)
    hour_start = end_dt.replace(minute=0, second=0).strftime(FMT)

    if args.frm:
        # 任意范围模式：只报该范围增量
        start = parse_ts(args.frm).strftime(FMT)
        c = counts(con, start, end)
        print(f"范围: `{start}` ~ `{end}`（北京时间）\n")
        print("| 指标 | 范围内增量 |")
        print("|---|---|")
        print(f"| 采集联系人（FB） | +{c['fb']} |")
        print(f"| 采集联系人（X） | +{c['x']} |")
        print(f"| 已确认注册 | +{c['reg']} |")
        print(f"| 确认未注册 | +{c['unreg']} |")
        print(f"| 待确认（截至终点快照） | {pending(con)} |")
        print(f"| 注册率（范围内） | {rate(c)} |")
        return

    if not args.since:
        ap.error("需要 --since（累计+本小时模式）或 --from/--to（任意范围模式）")
    since = parse_ts(args.since).strftime(FMT)
    cum = counts(con, since, end)
    win = counts(con, max(hour_start, since), end)

    print(f"基线: `{since}`　截至: `{end}`（北京时间）\n")
    print_summary(cum, win, pending(con), "本小时新增")
    if args.window > 0:
        print_hourly(con, end_dt, args.window)


if __name__ == "__main__":
    sys.exit(main())
