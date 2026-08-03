#!/usr/bin/env python3
"""1688 爬虫风控拦截率巡检脚本 —— 最近 2 小时窗口"""

import sqlite3
from datetime import datetime, timedelta, timezone
import os

DB_PATH = "/Volumes/DataDrive/proj/public/1699/.cache/1688.db"
REPORT_DIR = "/Volumes/DataDrive/proj/public/1699/scraper/taobao_1688/reports"
REPORT_PATH = os.path.join(REPORT_DIR, "拦截率巡检.md")

# 当前时间：2026-08-03 06:23:38 CST (+0800)
now = datetime(2026, 8, 3, 6, 23, 38, tzinfo=timezone(timedelta(hours=8)))
window_start = now - timedelta(hours=2)

now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
window_iso = window_start.strftime("%Y-%m-%d %H:%M:%S")

print(f"巡检窗口: {window_iso} ~ {now_iso} (CST+8)")
print()

if not os.path.exists(DB_PATH):
    print("数据库不存在")
    exit(0)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# --- 1. ip_stats：窗口内 updated_at 有更新的 IP ---
c.execute("""
    SELECT identity, requests, ok, blocks, updated_at, last_block_at
    FROM ip_stats
    WHERE updated_at >= ?
    ORDER BY updated_at DESC
""", (window_iso,))

ip_stats_rows = c.fetchall()
print("=== ip_stats (窗口内 updated_at 有活动) ===")
if not ip_stats_rows:
    print("无")
else:
    total_req = sum(r[1] for r in ip_stats_rows)
    total_ok = sum(r[2] for r in ip_stats_rows)
    total_blocks = sum(r[3] for r in ip_stats_rows)
    print(f"涉及 IP 数: {len(ip_stats_rows)}")
    print(f"累计 requests: {total_req}, ok: {total_ok}, blocks: {total_blocks}")
    for r in ip_stats_rows:
        print(f"  {r[0]}: req={r[1]} ok={r[2]} blocks={r[3]} updated={r[4]} last_block={r[5]}")
print()

# --- 2. ip_events：窗口内事件 ---
c.execute("""
    SELECT identity, event, detail, created_at, req_since_block
    FROM ip_events
    WHERE created_at >= ?
    ORDER BY created_at DESC
""", (window_iso,))

ip_events_rows = c.fetchall()
print("=== ip_events (窗口内) ===")
if not ip_events_rows:
    print("无")
else:
    events_by_type = {}
    ips_involved = set()
    gap_dist = {}
    for r in ip_events_rows:
        ev = r[1]
        events_by_type[ev] = events_by_type.get(ev, 0) + 1
        ips_involved.add(r[0])
        if ev.startswith("block") and r[4] is not None:
            gap = r[4]
            gap_dist[gap] = gap_dist.get(gap, 0) + 1
    print(f"总事件数: {len(ip_events_rows)}")
    print(f"涉及独立 IP 数: {len(ips_involved)}")
    print("事件分布:", events_by_type)
    print("gap 分布 (req_since_block):", dict(sorted(gap_dist.items())))
    for r in ip_events_rows:
        print(f"  {r[3]} | {r[0]} | {r[1]} | gap={r[4]} | {r[2]}")
print()

# --- 3. contacts：窗口内新增 ---
c.execute("""
    SELECT COUNT(*) FROM contacts WHERE scraped_at >= ?
""", (window_iso,))
contacts_count = c.fetchone()[0]
print("=== contacts (窗口内新增) ===")
print(f"新增条数: {contacts_count}")
print()

# --- 计算拦截率 ---
# block 事件数
block_events = sum(1 for r in ip_events_rows if r[1].startswith("block"))
# 页面请求数近似 = block 数 + contacts 新增数（成功产出）
# 或者用 ip_stats 增量：但 ip_stats 是累计值，无法直接得窗口增量
# 这里用 block + contacts 近似，再加上 launch 事件可能代表请求
approx_requests = block_events + contacts_count
# 更准确的：看看有没有 proxy_usage_events 或 task_events
c.execute("""
    SELECT COUNT(*) FROM proxy_usage_events WHERE ts >= ?
""", (window_iso,))
proxy_usage_count = c.fetchone()[0]
print(f"proxy_usage_events 窗口内记录: {proxy_usage_count}")

# 再试从 ip_events 里 block + launch 来估算
launch_events = sum(1 for r in ip_events_rows if r[1] == "launch")
print(f"launch 事件数: {launch_events}")

# 用 ip_stats 里窗口内更新的 IP 的 requests 字段（累计值），
# 但无法知道窗口开始时的值。如果窗口内只有这些 IP 有活动，
# 且是全新 IP（从 launch 推断），那 requests 约等于窗口内请求数。
# 更合理的近似：proxy_usage_events 或 ip_events 中 launch/block 的总和。
approx_requests_v2 = block_events + contacts_count
if launch_events > 0:
    approx_requests_v2 = max(approx_requests_v2, launch_events)

# 再查 ip_stats 中窗口内更新的 IP，如果 last_block_at 也在窗口内，
# 且 blocks 很小（1 或 2），可能是新 IP，requests 约等于窗口内值。
window_ip_requests = sum(r[1] for r in ip_stats_rows)
window_ip_blocks = sum(r[3] for r in ip_stats_rows)

print("=== 拦截率估算 ===")
print(f"block 事件数: {block_events}")
print(f"contacts 新增: {contacts_count}")
print(f"proxy_usage_events: {proxy_usage_count}")
print(f"ip_stats 窗口内 IP 累计 requests: {window_ip_requests}")
print(f"ip_stats 窗口内 IP 累计 blocks: {window_ip_blocks}")

if approx_requests_v2 > 0:
    block_rate = block_events / approx_requests_v2 * 100
    print(f"近似拦截率 (block / (block+contacts)): {block_rate:.1f}%")
else:
    block_rate = None
    print("无请求活动，无法计算拦截率")

if window_ip_requests > 0:
    block_rate_v2 = window_ip_blocks / window_ip_requests * 100
    print(f"ip_stats 累计拦截率 (blocks/requests): {block_rate_v2:.1f}%")
else:
    block_rate_v2 = None

conn.close()
