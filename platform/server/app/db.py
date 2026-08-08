# -*- coding: utf-8 -*-
"""SQLite 只读访问层 + 幂等迁移。

注意（与 util/contact_stats.py 一致）：
- 1688.db 处于 WAL 模式，读需要访问 -shm，因此【不能用】 uri mode=ro / immutable，
  这里用普通连接打开，但除 migrate() 外所有调用方只允许 SELECT，绝不写入。
- 库内时间戳均为北京时间字符串（UTC+8），不要再做 +8 偏移。
- 爬虫可能正在写库，设置较长的 busy_timeout 避免读锁冲突。
"""

import sqlite3
from contextlib import contextmanager

DB_PATH = "/Volumes/DataDrive/proj/public/1699/.cache/1688.db"


def migrate() -> None:
    """幂等迁移：contacts 表补 WhatsApp 查号结果列 + task_templates 表。

    - wa_registered INTEGER NULL：1=已注册 0=未注册 NULL=未查
    - wa_checked_at  TEXT NULL：查号完成时间（北京时间）
    - task_templates：任务模板（name/type/params_json）
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}
        if "wa_registered" not in cols:
            conn.execute(
                "ALTER TABLE contacts ADD COLUMN wa_registered INTEGER")
        if "wa_checked_at" not in cols:
            conn.execute(
                "ALTER TABLE contacts ADD COLUMN wa_checked_at TEXT")
        # 任务模板表（P2）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS task_templates ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT NOT NULL, "
            "type TEXT NOT NULL, "
            "params_json TEXT NOT NULL, "
            "created_at TEXT, "
            "updated_at TEXT)")
        # 供应商与代理通道表（历史手工建表，补进幂等迁移；
        # 结构以 docs/service-architecture.md 与实际库为准）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS providers ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "kind TEXT NOT NULL, "
            "name TEXT NOT NULL, "
            "config_json TEXT NOT NULL, "
            "enabled INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS proxy_channels ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "provider_id INTEGER REFERENCES providers(id), "
            "tunnel TEXT, "
            "exit_ip TEXT, "
            "status TEXT NOT NULL DEFAULT 'idle', "
            "used_by_task INTEGER REFERENCES tasks(id), "
            "ip_expires_at TEXT, "
            "last_probe_at TEXT, "
            "UNIQUE(provider_id, tunnel))")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_channels_provider"
            " ON proxy_channels(provider_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_channels_status"
            " ON proxy_channels(status)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_channels_task"
            " ON proxy_channels(used_by_task)")
        conn.commit()
    finally:
        conn.close()


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
