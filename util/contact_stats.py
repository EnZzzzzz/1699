#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监控最近 N 小时 shops 与 contacts 的变化，并评估采集 vs 消耗的管道平衡。

时区说明（重要）：
    1688.db 里的时间戳（scraped_at / first_seen_at / last_seen_at 等）
    存的就是北京时间（UTC+8），不是 UTC。
    核对依据：系统本地 CST(+0800) 09:46:36 时，DB 最新 scraped_at = 09:46:21，
    而同一时刻 UTC 才 01:46 —— 入库时间即北京时间。
    因此本脚本对 DB 时间戳【不再做 +8 偏移】；窗口按北京时间计算，
    输出的小时列即为北京时刻。

统计口径（监控什么）：
    - 当前 pending 存量  ：shops.status='pending' 数量（backlog）
    - 采集（shops 新增） ：first_seen_at 落在窗口内 —— 采集进队列
    - 消耗（contacts 成功）：scraped_at 落在窗口内 —— 抓取成功出队列（done）
      注意：no_contact / failed 同样消耗队列，但 shops 表无状态变更时间戳、
      task_events 记录不完整，故逐小时消耗只统计 done 一条；真实消耗 ≥ 此值。
    - shops 更新         ：last_seen_at 落在窗口内 —— 后续轮次再次见到（含新增）
    窗口终点取这几列的最大值，与数据同一时钟域，避免错位。

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


def _max_time(cur, table_col_pairs):
    """取多张表时间列的最大值，作为窗口终点（同一时钟域）。"""
    best = None
    for table, col in table_col_pairs:
        cur.execute(f"SELECT MAX({col}) FROM {table}")
        v = cur.fetchone()[0]
        if v and (best is None or v > best):
            best = v
    return best


def _hourly(cur, sql, start_str):
    """按小时分组计数，返回 {hour_label: cnt}（缺失的小时由打印侧补 0）。"""
    cur.execute(sql, (start_str,))
    return {hour: cnt for hour, cnt in cur.fetchall()}


def _sum_from(hourly: dict, start_label: str) -> int:
    """累加 start_label（含）之后的小时计数。hour_label 形如 '08-03 12:00'，
    零填充字符串比较即时间顺序，跨月也正确。"""
    return sum(c for label, c in hourly.items() if label >= start_label)


def _print_hourly(start, now, hours, col_labels, col_dicts):
    """逐小时打印多列计数表（含补 0 的小时），并输出合计与平均速率。"""
    cur_hour = start.replace(minute=0, second=0, microsecond=0)
    end_hour = now.replace(minute=0, second=0, microsecond=0)

    header = f"{'小时（北京）':<14}" + "".join(f"{lbl:>8}" for lbl in col_labels)
    print(header)
    totals = [0] * len(col_dicts)
    while cur_hour <= end_hour:
        label = cur_hour.strftime("%m-%d %H:00")
        row = [f"{label:<14}"]
        for i, d in enumerate(col_dicts):
            c = d.get(label, 0)
            totals[i] += c
            row.append(f"{c:>8}")
        print("".join(row))
        cur_hour += timedelta(hours=1)

    print("-" * len(header))
    print(f"{'合计':<14}" + "".join(f"{t:>8}" for t in totals))
    rates = " / ".join(f"{lbl} {t / hours:.1f} 条/小时"
                       for lbl, t in zip(col_labels, totals))
    print(f"\n平均速率：{rates}（按 {hours} 小时窗口均摊）")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="监控最近 N 小时 shops/contacts 变化与管道平衡")
    parser.add_argument("--hours", type=int, default=12, help="统计窗口小时数（默认 12）")
    parser.add_argument("--db", default=DEFAULT_DB, help="sqlite 数据库路径")
    args = parser.parse_args()

    # 爬虫正在写库，避免读锁冲突
    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    cur = conn.cursor()

    # 以数据自身的最大时间为窗口终点（同一时钟域，最准确）
    now_str = _max_time(cur, [("contacts", "scraped_at"),
                              ("shops", "first_seen_at"),
                              ("shops", "last_seen_at")])
    if not now_str:
        print("contacts / shops 表均为空")
        return
    now = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    start = now - timedelta(hours=args.hours)
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")

    # ---- 当前状态分布（pending 存量即 backlog）----
    status_now = dict(cur.execute(
        "SELECT status, COUNT(*) FROM shops GROUP BY status").fetchall())
    pending_now = status_now.get("pending", 0)

    # ---- contacts 消耗（done，时间戳精确）----
    c_total = cur.execute(
        "SELECT COUNT(*) FROM contacts WHERE scraped_at >= ?",
        (start_str,)).fetchone()[0]
    c_hourly = _hourly(cur, """
        SELECT strftime('%m-%d %H:00', scraped_at), COUNT(*)
        FROM contacts WHERE scraped_at >= ? GROUP BY 1""", start_str)

    # ---- shops 采集新增 / 更新 ----
    s_new = cur.execute(
        "SELECT COUNT(*) FROM shops WHERE first_seen_at >= ?",
        (start_str,)).fetchone()[0]
    s_upd = cur.execute(
        "SELECT COUNT(*) FROM shops WHERE last_seen_at >= ?",
        (start_str,)).fetchone()[0]
    s_new_hourly = _hourly(cur, """
        SELECT strftime('%m-%d %H:00', first_seen_at), COUNT(*)
        FROM shops WHERE first_seen_at >= ? GROUP BY 1""", start_str)
    s_upd_hourly = _hourly(cur, """
        SELECT strftime('%m-%d %H:00', last_seen_at), COUNT(*)
        FROM shops WHERE last_seen_at >= ? GROUP BY 1""", start_str)

    # 新增店铺当前状态分布（看采集的店是否被消费）
    s_status = dict(cur.execute("""
        SELECT status, COUNT(*) FROM shops
        WHERE first_seen_at >= ? GROUP BY status ORDER BY 2 DESC""",
        (start_str,)).fetchall())

    conn.close()

    collect_rate = s_new / args.hours
    consume_rate = c_total / args.hours

    # 本采集轮起点：窗口内首个采集 >0 的小时。
    # 采集开始前消耗在追旧 backlog，用全窗口均摊对比会被相位差误导，
    # 故结论以"本采集轮"（采集启动至今）为准。
    active_label = None
    for label in sorted(s_new_hourly):
        if s_new_hourly[label] > 0:
            active_label = label
            break
    if active_label:
        active_start = datetime.strptime(f"{active_label} {now.year}",
                                         "%m-%d %H:00 %Y").replace(tzinfo=TZ)
        active_hours = (now - active_start).total_seconds() / 3600.0
        act_collect = _sum_from(s_new_hourly, active_label)
        act_consume = _sum_from(c_hourly, active_label)
        act_collect_rate = act_collect / max(active_hours, 0.1)
        act_consume_rate = act_consume / max(active_hours, 0.1)

    # ---- 输出 ----
    print(f"窗口：{start.strftime('%Y-%m-%d %H:%M')} ~ "
          f"{now.strftime('%Y-%m-%d %H:%M')}（北京时间，共 {args.hours} 小时）\n")

    # ① 当前 pending 存量
    dist_now = "  ".join(f"{k} {v}" for k, v in
                         sorted(status_now.items(),
                                key=lambda kv: kv[1], reverse=True))
    print(f"当前 pending 存量（backlog）：{pending_now}")
    print(f"当前全部状态：{dist_now}\n")

    # ② 管道平衡
    print(f"========== 管道平衡 ==========")
    print(f"[全窗口 {args.hours} 小时]  采集 {s_new} 条（{collect_rate:.1f}/时）  "
          f"消耗(done) {c_total} 条（{consume_rate:.1f}/时）")
    if active_label:
        print(f"[本采集轮 {active_hours:.1f} 小时] 采集 {act_collect} 条"
              f"（{act_collect_rate:.1f}/时）  消耗(done) {act_consume} 条"
              f"（{act_consume_rate:.1f}/时）  ← 自 {active_label} 起")
    print("说明：no_contact/failed 同样消耗队列但无逐小时时间戳，真实消耗 ≥ 上值")
    if active_label:
        if act_consume_rate >= act_collect_rate:
            print(f"结论：本采集轮消耗 {act_consume_rate:.1f}/时 ≥ 采集 "
                  f"{act_collect_rate:.1f}/时（done，且 no_contact/failed 额外"
                  "消耗）→ pending 在消化，采集赶不上消耗。")
        else:
            print(f"结论：本采集轮消耗 {act_consume_rate:.1f}/时 < 采集 "
                  f"{act_collect_rate:.1f}/时（done 口径；真实消耗需再加 "
                  "no_contact/failed）→ 若不加速消耗，pending 会积累。")
    else:
        if consume_rate >= collect_rate:
            print("结论：窗口内无采集（只在消耗旧 backlog）→ pending 在消化。")
        else:
            print("结论：窗口内无采集活动。")
    print()
    _print_hourly(start, now, args.hours, ["采集", "消耗"],
                  [s_new_hourly, c_hourly])

    # ③ 明细：shops 新增/更新 + 状态分布
    print(f"\n---------- shops 变化明细 ----------")
    print(f"最近 {args.hours} 小时 shops 新增总数（first_seen_at）：{s_new}")
    print(f"最近 {args.hours} 小时 shops 更新总数（last_seen_at）：{s_upd}")
    if s_status:
        dist = "  ".join(f"{k} {v}" for k, v in s_status.items())
        print(f"新增店铺状态分布：{dist}")
    _print_hourly(start, now, args.hours, ["新增", "更新"],
                  [s_new_hourly, s_upd_hourly])

    # ④ 明细：contacts
    print(f"\n---------- contacts 明细 ----------")
    print(f"最近 {args.hours} 小时 contacts 新增总数：{c_total}")
    _print_hourly(start, now, args.hours, ["新增"], [c_hourly])


if __name__ == "__main__":
    main()
