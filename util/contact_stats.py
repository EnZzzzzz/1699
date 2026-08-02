#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询最近 N 小时 contacts 的新增数量（总数 + 每小时明细）。

时区说明（重要）：
    1688.db 里的时间戳（scraped_at / first_seen_at / last_seen_at 等）
    存的就是北京时间（UTC+8），不是 UTC。
    核对依据：系统本地 CST(+0800) 09:46:36 时，DB 最新 scraped_at = 09:46:21，
    而同一时刻 UTC 才 01:46 —— 入库时间即北京时间。
    因此本脚本对 DB 时间戳【不再做 +8 偏移】；若再 +8，会把 09:46 显示成 17:46，
    窗口整体错位 8 小时。窗口按北京时间计算，输出的小时列即为北京时刻。

用法：
    python util/contact_stats.py [--hours 12] [--db PATH]

依赖：python3 标准库（sqlite3 / argparse / datetime / zoneinfo），无第三方包。
"""

import argparse
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_DB = "/Volumes/DataDrive/proj/public/1699/.cache/1688.db"
TZ = ZoneInfo("Asia/Shanghai")  # 北京时间


def main() -> None:
    parser = argparse.ArgumentParser(description="查询最近 N 小时 contacts 新增数量")
    parser.add_argument("--hours", type=int, default=12, help="统计窗口小时数（默认 12）")
    parser.add_argument("--db", default=DEFAULT_DB, help="sqlite 数据库路径")
    args = parser.parse_args()

    # 爬虫正在写库，避免读锁冲突
    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    cur = conn.cursor()

    # 以 DB 内最新一条采集时间为"现在"作为窗口终点（与数据同一时钟域，最准确）
    cur.execute("SELECT MAX(scraped_at) FROM contacts")
    now_str = cur.fetchone()[0]
    if not now_str:
        print("contacts 表为空")
        return
    now = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    start = now - timedelta(hours=args.hours)
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")

    # 1) 窗口内总新增
    cur.execute(
        "SELECT COUNT(*) FROM contacts WHERE scraped_at >= ?",
        (start_str,),
    )
    total = cur.fetchone()[0]

    # 2) 每小时明细（DB 时间即北京时区，按小时分组；缺失的小时补 0）
    cur.execute(
        """
        SELECT strftime('%m-%d %H:00', scraped_at) AS hour,
               COUNT(*) AS cnt
        FROM contacts
        WHERE scraped_at >= ?
        GROUP BY hour
        """,
        (start_str,),
    )
    hour_count = {hour: cnt for hour, cnt in cur.fetchall()}
    conn.close()

    print(f"窗口：{start.strftime('%Y-%m-%d %H:%M')} ~ {now.strftime('%Y-%m-%d %H:%M')}（北京时间，共 {args.hours} 小时）")
    print(f"最近 {args.hours} 小时 contacts 新增总数：{total}\n")
    print(f"{'小时（北京）':<14}{'新增':>8}")

    # 生成完整的小时序列（窗口起点对齐到小时整点 ~ 终点对齐到小时整点，含 0 的小时）
    cur_hour = start.replace(minute=0, second=0, microsecond=0)
    end_hour = now.replace(minute=0, second=0, microsecond=0)

    active_hours = 0
    total_in_show = 0
    while cur_hour <= end_hour:
        label = cur_hour.strftime("%m-%d %H:00")
        cnt = hour_count.get(label, 0)
        total_in_show += cnt
        if cnt > 0:
            active_hours += 1
        print(f"{label:<14}{cnt:>8}")
        cur_hour += timedelta(hours=1)

    print("-" * 24)
    print(f"{'合计':<14}{total_in_show:>8}")
    if active_hours:
        avg = total / args.hours
        print(f"\n平均速率：约 {avg:.1f} 条/小时（按 {args.hours} 小时窗口均摊）")
        active_avg = total / active_hours
        print(f"活跃时段速率：约 {active_avg:.1f} 条/小时（按有数据的 {active_hours} 个小时均摊）")


if __name__ == "__main__":
    main()
