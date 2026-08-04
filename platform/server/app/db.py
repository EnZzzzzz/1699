# -*- coding: utf-8 -*-
"""SQLite 只读访问层。

注意（与 util/contact_stats.py 一致）：
- 1688.db 处于 WAL 模式，读需要访问 -shm，因此【不能用】 uri mode=ro / immutable，
  这里用普通连接打开，但所有调用方只允许 SELECT，绝不写入。
- 库内时间戳均为北京时间字符串（UTC+8），不要再做 +8 偏移。
- 爬虫可能正在写库，设置较长的 busy_timeout 避免读锁冲突。
"""

import sqlite3
from contextlib import contextmanager

DB_PATH = "/Volumes/DataDrive/proj/public/1699/.cache/1688.db"


@contextmanager
def connect():
    """打开一个只读用途的连接（普通模式，WAL 下可读 shm）。调用方不得执行写操作。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
    finally:
        conn.close()
