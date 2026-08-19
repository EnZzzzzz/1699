#!/usr/bin/env python3
# 产量巡检：查 fb_contacts 在指定时间范围内的增量，输出 Markdown 表格报告
# 用法：
#   python3 scraper/inspect_stats.py --since "2026-08-19 01:05:04"          # 累计 + 最近 1 小时新增
#   python3 scraper/inspect_stats.py --since "2026-08-19 01:05:04" --window 2   # 新增窗口改 2 小时
#   python3 scraper/inspect_stats.py --from "2026-08-19 00:00:00" --to "2026-08-19 01:00:00"  # 任意范围
# 时间一律北京时间字符串（库内时间戳已是北京时间，不做换算）。
import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / ".cache" / "1688.db"
FMT = "%Y-%m-%d %H:%M:%S"

X_URL_COND = "(post_url LIKE '%x.com%' OR post_url LIKE '%twitter.com%')"


def parse_ts(s: str) -> str:
    """校验并归一化时间字符串（支持省略秒）。"""
    for f in (FMT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).strftime(FMT)
        except ValueError:
            continue
    raise SystemExit(f"无法解析时间: {s!r}（支持 'YYYY-MM-DD [HH:MM[:SS]]'）")


def counts(con: sqlite3.Connection, col: str, start: str, end: str) -> dict:
    """统计 [start, end) 内：FB 新增、X 新增、确认注册、确认未注册。"""
    where = f"{col} >= ? AND {col} < ?"
    args = (start, end)
    fb = con.execute(
        f"SELECT COUNT(*) FROM fb_contacts WHERE {where} AND NOT {X_URL_COND}",
        args).fetchone()[0]
    x = con.execute(
        f"SELECT COUNT(*) FROM fb_contacts WHERE {where} AND {X_URL_COND}",
        args).fetchone()[0]
    reg_where = f"wa_checked_at >= ? AND wa_checked_at < ?"
    reg = con.execute(
        f"SELECT COUNT(*) FROM fb_contacts WHERE {reg_where} AND wa_registered = 1",
        args).fetchone()[0]
    unreg = con.execute(
        f"SELECT COUNT(*) FROM fb_contacts WHERE {reg_where} AND wa_registered = 0",
        args).fetchone()[0]
    return {"fb": fb, "x": x, "reg": reg, "unreg": unreg}


def main() -> None:
    ap = argparse.ArgumentParser(description="fb_contacts 产量巡检（北京时间）")
    ap.add_argument("--since", help="累计口径起点（与 --from 二选一）")
    ap.add_argument("--window", type=float, default=1.0,
                    help="新增窗口小时数，默认 1（配合 --since）")
    ap.add_argument("--from", dest="frm", help="范围起点（与 --to 搭配，只查该范围增量）")
    ap.add_argument("--to", help="范围终点，默认当前时间")
    args = ap.parse_args()

    if not DB.exists():
        raise SystemExit(f"库不存在: {DB}")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    now = datetime.now().strftime(FMT)
    end = parse_ts(args.to) if args.to else now
    pending = con.execute(
        "SELECT COUNT(*) FROM fb_contacts WHERE wa_checked_at IS NULL").fetchone()[0]

    def rate(c: dict) -> str:
        tot = c["reg"] + c["unreg"]
        return f"{c['reg'] / tot * 100:.1f}%" if tot else "—"

    if args.frm:
        # 任意范围模式：只报该范围增量
        start = parse_ts(args.frm)
        c = counts(con, "first_seen_at", start, end)
        print(f"范围: `{start}` ~ `{end}`（北京时间）\n")
        print("| 指标 | 范围内增量 |")
        print("|---|---|")
        print(f"| 采集联系人（FB） | +{c['fb']} |")
        print(f"| 采集联系人（X） | +{c['x']} |")
        print(f"| 已确认注册 | +{c['reg']} |")
        print(f"| 确认未注册 | +{c['unreg']} |")
        print(f"| 待确认（截至终点快照） | {pending} |")
        print(f"| 注册率（范围内） | {rate(c)} |")
        return

    if not args.since:
        ap.error("需要 --since（累计+窗口模式）或 --from/--to（任意范围模式）")
    since = parse_ts(args.since)
    win_start = (datetime.strptime(end, FMT)
                 - timedelta(hours=args.window)).strftime(FMT)
    cum = counts(con, "first_seen_at", since, end)
    win = counts(con, "first_seen_at", max(win_start, since), end)

    print(f"基线: `{since}`　窗口: 最近 {args.window:g} 小时（截至 `{end}`，北京时间）\n")
    print("| 指标 | 本次累计 | 本窗口新增 |")
    print("|---|---|---|")
    print(f"| 采集联系人（FB） | {cum['fb']} | +{win['fb']} |")
    print(f"| 采集联系人（X） | {cum['x']} | +{win['x']} |")
    print(f"| 已确认注册 | {cum['reg']} | +{win['reg']} |")
    print(f"| 确认未注册 | {cum['unreg']} | +{win['unreg']} |")
    print(f"| 待确认 | {pending} | — |")
    print(f"| 注册率 | {rate(cum)} | — |")


if __name__ == "__main__":
    sys.exit(main())
