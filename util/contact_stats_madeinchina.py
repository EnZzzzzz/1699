#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国制造网(cn.made-in-china.com) 联系方式统计 —— contact_stats.py 的站点过滤版。

背景：1688.db 是 1688 + madeinchina 共库（shops/contacts 表共享、按域名区分来源）。
通用 contact_stats.py 统计的是全库（含 1688）；本脚本把每一处查询都按中国制造网
展厅子域名后缀过滤，只统计该站的采集/消耗管道平衡。

统计口径（与通用版一致，但全部限定 madeinchina）：
    - 当前 pending 存量  ：madeinchina shops.status='pending'（backlog）
    - 采集（shops 新增） ：madeinchina first_seen_at 落在窗口内
    - 消耗（联系方式页） ：madeinchina 店铺的 contacts.scraped_at 落在窗口内
        —— 比通用版更进一步：拆成「有效(phone/mobile 有值)」和「无号(no_contact)」两列
    - shops 更新         ：madeinchina last_seen_at 落在窗口内

时区说明：DB 时间戳（scraped_at/first_seen_at/last_seen_at）存的就是北京时间
(+0800)，窗口按北京时间计算，不做偏移；窗口终点取这几列的最大值（同一时钟域）。

用法：
    python util/contact_stats_madeinchina.py [--hours 12] [--db PATH]
    python util/contact_stats_madeinchina.py --suffix '.cn.yiwugo.com' --label 义乌购

依赖：python3 标准库（sqlite3 / argparse / datetime / zoneinfo），无第三方包。
"""

import argparse
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_DB = "/Volumes/DataDrive/proj/public/1699/.cache/1688.db"
TZ = ZoneInfo("Asia/Shanghai")  # 北京时间


def _domain_cond(suffix: str) -> str:
    """展厅子域名后缀 → SQL 域名过滤条件（与 db.claim_pending_shops 同款）。"""
    return f"substr(domain, -{len(suffix)}, {len(suffix)}) = '{suffix}'"


def _max_time(cur, specs):
    """取多列时间最大值作为窗口终点（同一时钟域）。

    specs: (table_sql, col, where) —— table_sql 可含 JOIN。
    """
    best = None
    for table, col, where in specs:
        q = f"SELECT MAX({col}) FROM {table}"
        if where:
            q += f" WHERE {where}"
        cur.execute(q)
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
        description="中国制造网联系方式统计（contact_stats.py 的站点过滤版）")
    parser.add_argument("--hours", type=int, default=12, help="统计窗口小时数（默认 12）")
    parser.add_argument("--db", default=DEFAULT_DB, help="sqlite 数据库路径")
    parser.add_argument("--suffix", default=".cn.made-in-china.com",
                        help="店铺域名后缀（默认中国制造网，可改看共库里的其他站）")
    parser.add_argument("--label", default="中国制造网", help="站点显示名")
    args = parser.parse_args()

    cond = _domain_cond(args.suffix)

    # 爬虫正在写库，避免读锁冲突
    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    cur = conn.cursor()

    # 以该站数据自身的最大时间为窗口终点（同一时钟域）
    now_str = _max_time(cur, [
        ("contacts c JOIN shops s ON s.id = c.shop_id", "c.scraped_at", cond),
        ("shops", "first_seen_at", cond),
        ("shops", "last_seen_at", cond),
    ])
    if not now_str:
        print(f"该站（{args.label}，后缀 {args.suffix}）暂无数据")
        return
    now = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    start = now - timedelta(hours=args.hours)
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")

    # ---- 总量（限该站）----
    total_shops = cur.execute(
        f"SELECT COUNT(*) FROM shops WHERE {cond}").fetchone()[0]
    total_contacts = cur.execute(
        f"SELECT COUNT(*) FROM contacts c JOIN shops s ON s.id = c.shop_id"
        f" WHERE {cond}").fetchone()[0]

    # ---- 当前状态分布（pending 存量即 backlog）----
    status_now = dict(cur.execute(
        f"SELECT status, COUNT(*) FROM shops WHERE {cond} GROUP BY status").fetchall())
    pending_now = status_now.get("pending", 0)

    # ---- 消耗（联系方式页）：拆 有效 / 无号 两列 ----
    c_ok = cur.execute(
        f"SELECT COUNT(*) FROM contacts c JOIN shops s ON s.id = c.shop_id"
        f" WHERE {cond} AND c.scraped_at >= ?"
        f" AND ((c.phone IS NOT NULL AND c.phone <> '')"
        f"  OR (c.mobile IS NOT NULL AND c.mobile <> ''))",
        (start_str,)).fetchone()[0]
    c_empty = cur.execute(
        f"SELECT COUNT(*) FROM contacts c JOIN shops s ON s.id = c.shop_id"
        f" WHERE {cond} AND c.scraped_at >= ?"
        f" AND (c.phone IS NULL OR c.phone = '')"
        f" AND (c.mobile IS NULL OR c.mobile = '')",
        (start_str,)).fetchone()[0]
    c_total = c_ok + c_empty
    c_ok_hourly = _hourly(cur, f"""
        SELECT strftime('%m-%d %H:00', c.scraped_at), COUNT(*)
        FROM contacts c JOIN shops s ON s.id = c.shop_id
        WHERE {cond} AND c.scraped_at >= ?
          AND ((c.phone IS NOT NULL AND c.phone <> '')
            OR (c.mobile IS NOT NULL AND c.mobile <> ''))
        GROUP BY 1""", start_str)
    c_empty_hourly = _hourly(cur, f"""
        SELECT strftime('%m-%d %H:00', c.scraped_at), COUNT(*)
        FROM contacts c JOIN shops s ON s.id = c.shop_id
        WHERE {cond} AND c.scraped_at >= ?
          AND (c.phone IS NULL OR c.phone = '')
          AND (c.mobile IS NULL OR c.mobile = '')
        GROUP BY 1""", start_str)

    # ---- 采集新增 / 更新（限该站）----
    s_new = cur.execute(
        f"SELECT COUNT(*) FROM shops WHERE {cond} AND first_seen_at >= ?",
        (start_str,)).fetchone()[0]
    s_upd = cur.execute(
        f"SELECT COUNT(*) FROM shops WHERE {cond} AND last_seen_at >= ?",
        (start_str,)).fetchone()[0]
    s_new_hourly = _hourly(cur, f"""
        SELECT strftime('%m-%d %H:00', first_seen_at), COUNT(*)
        FROM shops WHERE {cond} AND first_seen_at >= ? GROUP BY 1""", start_str)
    s_upd_hourly = _hourly(cur, f"""
        SELECT strftime('%m-%d %H:00', last_seen_at), COUNT(*)
        FROM shops WHERE {cond} AND last_seen_at >= ? GROUP BY 1""", start_str)

    # 新增店铺当前状态分布（看采集的店是否被消费）
    s_status = dict(cur.execute(f"""
        SELECT status, COUNT(*) FROM shops WHERE {cond} AND first_seen_at >= ?
        GROUP BY status ORDER BY 2 DESC""", (start_str,)).fetchall())

    conn.close()

    collect_rate = s_new / args.hours
    consume_rate = c_total / args.hours

    # 本采集轮起点：窗口内首个采集 >0 的小时（同通用版，避免相位差误导）
    active_label = None
    for label in sorted(s_new_hourly):
        if s_new_hourly[label] > 0:
            active_label = label
            break
    act_collect = act_consume = act_hours = 0.0
    act_collect_rate = act_consume_rate = 0.0
    if active_label:
        active_start = datetime.strptime(f"{active_label} {now.year}",
                                         "%m-%d %H:00 %Y").replace(tzinfo=TZ)
        act_hours = (now - active_start).total_seconds() / 3600.0
        act_collect = _sum_from(s_new_hourly, active_label)
        act_consume = (_sum_from(c_ok_hourly, active_label)
                       + _sum_from(c_empty_hourly, active_label))
        act_collect_rate = act_collect / max(act_hours, 0.1)
        act_consume_rate = act_consume / max(act_hours, 0.1)

    # ---- 输出 ----
    print(f"窗口：{start.strftime('%Y-%m-%d %H:%M')} ~ "
          f"{now.strftime('%Y-%m-%d %H:%M')}（北京时间，共 {args.hours} 小时）\n")

    # ① 总量 + 当前 pending 存量
    print(f"{args.label} shops 总量：{total_shops}  |  contacts 总量：{total_contacts}")
    dist_now = "  ".join(f"{k} {v}" for k, v in
                         sorted(status_now.items(),
                                key=lambda kv: kv[1], reverse=True))
    print(f"当前 pending 存量（backlog）：{pending_now}")
    print(f"当前全部状态：{dist_now}\n")

    # ② 管道平衡
    print("========== 管道平衡 ==========")
    print(f"[全窗口 {args.hours} 小时]  采集 {s_new} 条（{collect_rate:.1f}/时）  "
          f"消耗(联系方式页) {c_total} 条（{consume_rate:.1f}/时）"
          f"〔有效 {c_ok} / 无号 {c_empty}〕")
    if active_label:
        print(f"[本采集轮 {act_hours:.1f} 小时] 采集 {act_collect} 条"
              f"（{act_collect_rate:.1f}/时）  消耗 {act_consume} 条"
              f"（{act_consume_rate:.1f}/时）  ← 自 {active_label} 起")
    print("说明：有效=手机或座机有值；无号=两者皆空（no_contact），同样消耗队列")
    if active_label:
        if act_consume_rate >= act_collect_rate:
            print(f"结论：本采集轮消耗 {act_consume_rate:.1f}/时 ≥ 采集 "
                  f"{act_collect_rate:.1f}/时 → pending 在消化，采集赶不上消耗。")
        else:
            print(f"结论：本采集轮消耗 {act_consume_rate:.1f}/时 < 采集 "
                  f"{act_collect_rate:.1f}/时 → 若不加速消耗，pending 会积累。")
    else:
        print("结论：窗口内无采集（只在消耗旧 backlog）→ pending 在消化。")
    print()
    _print_hourly(start, now, args.hours, ["采集", "有效", "无号"],
                  [s_new_hourly, c_ok_hourly, c_empty_hourly])

    # ③ 明细：shops 新增/更新 + 状态分布
    print(f"\n---------- {args.label} shops 变化明细 ----------")
    print(f"最近 {args.hours} 小时 shops 新增总数（first_seen_at）：{s_new}")
    print(f"最近 {args.hours} 小时 shops 更新总数（last_seen_at）：{s_upd}")
    if s_status:
        dist = "  ".join(f"{k} {v}" for k, v in s_status.items())
        print(f"新增店铺状态分布：{dist}")
    _print_hourly(start, now, args.hours, ["新增", "更新"],
                  [s_new_hourly, s_upd_hourly])

    # ④ 明细：contacts
    print(f"\n---------- {args.label} contacts 明细 ----------")
    print(f"最近 {args.hours} 小时 contacts 新增总数：{c_total}"
          f"〔有效 {c_ok} / 无号 {c_empty}〕")
    _print_hourly(start, now, args.hours, ["有效", "无号"],
                  [c_ok_hourly, c_empty_hourly])


if __name__ == "__main__":
    main()
