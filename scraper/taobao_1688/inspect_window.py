#!/usr/bin/env python3
"""巡检脚本：统计最近 2 小时拦截率"""
import sqlite3
from datetime import datetime, timedelta

# 当前时间锚点
now = datetime(2026, 8, 3, 12, 23, 36)
window_start = now - timedelta(hours=2)

print(f"巡检窗口：{window_start.strftime('%Y-%m-%d %H:%M:%S')} ～ {now.strftime('%Y-%m-%d %H:%M:%S')}")

conn = sqlite3.connect(".cache/1688.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# ---- 1. ip_stats：窗口内活跃 IP（updated_at 在窗口内）----
cursor.execute("""
    SELECT identity, requests, ok, blocks, last_block_at, updated_at
    FROM ip_stats
    WHERE updated_at >= ?
    ORDER BY updated_at DESC
""", (window_start.strftime('%Y-%m-%d %H:%M:%S'),))
ip_stats_rows = [dict(r) for r in cursor.fetchall()]
print(f"\n=== ip_stats 窗口内活跃 IP 数：{len(ip_stats_rows)} ===")
for r in ip_stats_rows:
    print(f"  {r['identity']}: requests={r['requests']}, ok={r['ok']}, blocks={r['blocks']}, updated_at={r['updated_at']}")

# ---- 2. ip_events：窗口内事件统计 ----
cursor.execute("""
    SELECT event, COUNT(*) as cnt, COUNT(DISTINCT identity) as unique_ips,
           AVG(req_since_block) as avg_gap,
           MIN(req_since_block) as min_gap, MAX(req_since_block) as max_gap
    FROM ip_events
    WHERE created_at >= ?
    GROUP BY event
""", (window_start.strftime('%Y-%m-%d %H:%M:%S'),))
event_summary = [dict(r) for r in cursor.fetchall()]
print(f"\n=== ip_events 窗口内事件统计 ===")
for r in event_summary:
    avg_gap = r['avg_gap']
    avg_gap_str = f"{avg_gap:.1f}" if avg_gap is not None else "N/A"
    print(f"  {r['event']}: {r['cnt']} 次, 涉及 {r['unique_ips']} 个 IP, avg_gap={avg_gap_str}, min_gap={r['min_gap']}, max_gap={r['max_gap']}")

# 详细事件
cursor.execute("""
    SELECT identity, event, detail, created_at, req_since_block
    FROM ip_events
    WHERE created_at >= ?
    ORDER BY created_at DESC
""", (window_start.strftime('%Y-%m-%d %H:%M:%S'),))
all_events = [dict(r) for r in cursor.fetchall()]
print(f"\n  全部 {len(all_events)} 条事件（按时间倒序）：")
for r in all_events[:30]:
    print(f"    {r['created_at']} | {r['identity'][:25]:25} | {r['event']:15} | gap={r['req_since_block']} | {r['detail']}")

# gap 分布
gap_dist = {}
for r in all_events:
    if r['event'] in ('block_slider', 'block_login', 'block_other'):
        g = r['req_since_block']
        if g is None:
            g = 'NULL'
        gap_dist[g] = gap_dist.get(g, 0) + 1
print(f"\n  gap(req_since_block) 分布（仅 block 事件）：")
for g in sorted(gap_dist.keys(), key=lambda x: (x == 'NULL', x)):
    print(f"    gap={g}: {gap_dist[g]} 次")

# ---- 3. contacts：窗口内新增条数 ----
cursor.execute("""
    SELECT COUNT(*) as cnt FROM contacts WHERE scraped_at >= ?
""", (window_start.strftime('%Y-%m-%d %H:%M:%S'),))
contacts_count = cursor.fetchone()['cnt']
print(f"\n=== contacts 窗口内新增：{contacts_count} 条 ===")

# 最近几条
cursor.execute("""
    SELECT id, shop_id, scraped_at FROM contacts WHERE scraped_at >= ? ORDER BY scraped_at DESC LIMIT 5
""", (window_start.strftime('%Y-%m-%d %H:%M:%S'),))
for r in cursor.fetchall():
    print(f"  id={r['id']}, shop_id={r['shop_id']}, scraped_at={r['scraped_at']}")

# ---- 4. 拦截率计算 ----
block_events = sum(r['cnt'] for r in event_summary if r['event'] in ('block_slider', 'block_login', 'block_other'))
launch_events = sum(r['cnt'] for r in event_summary if r['event'] == 'launch')

# 请求数近似：block 数 + contacts 产出（每个 contact 至少一次页面请求）
approx_requests = block_events + contacts_count
block_rate = (block_events / approx_requests * 100) if approx_requests > 0 else 0

print(f"\n=== 拦截率估算 ===")
print(f"  block 事件数：{block_events}")
print(f"  launch 事件数：{launch_events}")
print(f"  contacts 产出：{contacts_count}")
print(f"  近似请求数：{approx_requests}")
print(f"  拦截率：{block_rate:.1f}%")

# 独立 IP 数
cursor.execute("""
    SELECT COUNT(DISTINCT identity) as unique_ips FROM ip_events WHERE created_at >= ?
""", (window_start.strftime('%Y-%m-%d %H:%M:%S'),))
unique_ips = cursor.fetchone()['unique_ips']
print(f"  涉及独立 IP 数：{unique_ips}")

conn.close()
