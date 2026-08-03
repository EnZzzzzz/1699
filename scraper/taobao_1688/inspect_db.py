#!/usr/bin/env python3
import sqlite3
conn = sqlite3.connect(".cache/1688.db")
cursor = conn.cursor()

# List tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
print("Tables:", [r[0] for r in cursor.fetchall()])

# Schema for key tables
for tbl in ["ip_stats", "ip_events", "contacts", "cookies"]:
    try:
        cursor.execute(f"PRAGMA table_info({tbl})")
        cols = [(r[1], r[2]) for r in cursor.fetchall()]
        print(f"\n{tbl}: {cols}")
    except Exception as e:
        print(f"\n{tbl}: ERROR {e}")

conn.close()
