# -*- coding: utf-8 -*-
"""
1688 联系方式定时补抓 — Automation 执行入口

流程:
    1. 子进程运行 contact_fetcher.py（断点续爬，抓取 limit 个 pending 店铺）
    2. 向 1688.db 的 stats_snapshots 表写入本次统计快照
    3. 输出 artifact: 店铺状态统计 + 历史积累 + 本批结果

stdin:  AutomationCodeRequest JSON
stdout: {"artifact": {...}}
"""

import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path("/Volumes/DataDrive/proj/public/1699")
SCRAPER_DIR = PROJECT_ROOT / "scraper" / "taobao_1688"
DB_PATH = PROJECT_ROOT / ".cache" / "1688.db"
FETCHER = SCRAPER_DIR / "contact_fetcher.py"

DEFAULT_LIMIT = 20


def run_batch(limit: int) -> dict:
    """运行 contact_fetcher.py，从输出解析本批结果。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(FETCHER), "-n", str(limit)],
            cwd=str(SCRAPER_DIR), capture_output=True, text=True,
            timeout=780)
        out = proc.stdout + proc.stderr
        m = re.search(r"有联系方式 (\d+), 无联系方式 (\d+), 失败 (\d+)", out)
        if m:
            return {"ok": int(m.group(1)), "empty": int(m.group(2)),
                    "failed": int(m.group(3)), "limit": limit}
        # 没有待抓取店铺时 contact_fetcher 直接退出
        if "没有待抓取的店铺" in out:
            return {"ok": 0, "empty": 0, "failed": 0, "limit": limit}
        return {"ok": 0, "empty": 0, "failed": 0, "limit": limit}
    except subprocess.TimeoutExpired:
        return {"ok": 0, "empty": 0, "failed": 0, "limit": limit}


def get_stats(conn: sqlite3.Connection) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "shops": q("SELECT COUNT(*) FROM shops"),
        "pending": q("SELECT COUNT(*) FROM shops WHERE status='pending'"),
        "done": q("SELECT COUNT(*) FROM shops WHERE status='done'"),
        "no_contact": q("SELECT COUNT(*) FROM shops WHERE status='no_contact'"),
        "failed": q("SELECT COUNT(*) FROM shops WHERE status='failed'"),
        "with_mobile": q("SELECT COUNT(*) FROM contacts"
                         " WHERE mobile IS NOT NULL AND mobile != ''"),
    }


def record_snapshot(conn: sqlite3.Connection, stats: dict):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS stats_snapshots (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               ts TEXT NOT NULL,
               shops INTEGER, pending INTEGER, done INTEGER,
               no_contact INTEGER, failed INTEGER, with_mobile INTEGER)""")
    conn.execute(
        "INSERT INTO stats_snapshots (ts, shops, pending, done,"
        " no_contact, failed, with_mobile) VALUES (?,?,?,?,?,?,?)",
        (time.strftime("%Y-%m-%d %H:%M:%S"), stats["shops"], stats["pending"],
         stats["done"], stats["no_contact"], stats["failed"],
         stats["with_mobile"]))
    conn.commit()


def get_history(conn: sqlite3.Connection, limit: int = 30) -> list:
    try:
        rows = conn.execute(
            "SELECT ts, shops, done, with_mobile FROM stats_snapshots"
            " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"at": r[0][5:16], "shops": r[1], "done": r[2], "with_mobile": r[3]}
            for r in reversed(rows)]


def run(ctx):
    """托管 Python 运行器入口。ctx 含 input 等上下文。"""
    inp = (ctx or {}).get("input") or {}
    if isinstance(inp, str):
        inp = json.loads(inp) if inp.strip() else {}
    limit = int(inp.get("limit") or DEFAULT_LIMIT)

    batch = run_batch(limit)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        stats = get_stats(conn)
        record_snapshot(conn, stats)
        history = get_history(conn)
    finally:
        conn.close()

    artifact = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": stats,
        "history": history,
        "last_batch": batch,
    }
    return {"artifact": artifact}
