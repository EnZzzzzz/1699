# -*- coding: utf-8 -*-
"""SQLite 只读访问层 + 幂等迁移。

注意（与 util/contact_stats.py 一致）：
- 1688.db 处于 WAL 模式，读需要访问 -shm，因此【不能用】 uri mode=ro / immutable，
  这里用普通连接打开，但除 migrate() 外所有调用方只允许 SELECT，绝不写入。
- 库内时间戳均为北京时间字符串（UTC+8），不要再做 +8 偏移。
- 爬虫可能正在写库，设置较长的 busy_timeout 避免读锁冲突。
"""

import json
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "/Volumes/DataDrive/proj/public/1699/.cache/1688.db"


def _bj_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _write(sql, params=()):
    """短事务写入 + busy_timeout（批次入队等平台侧写操作共用）。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        cur = conn.execute(sql, params)
        conn.commit()
        return cur
    finally:
        conn.close()


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
        # P4：work_items 批次索引（生产库表由 fetcher 建，平台只补索引不建表；
        # 探测式——表不存在则跳过，防御性）
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "work_items" in tables:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_items_batch"
                " ON work_items(batch_id, status)")
        conn.commit()
    finally:
        conn.close()


# ==================== P4 批次入队（平台侧 SQL，与 fetcher 同事务语义） ====================
# SPEC §3.1 裁定：平台不 import fetcher，批次 SQL 平台侧重写；两边重复
# 是有意为之的边界，语义由同一 SPEC + 测试锚定。


def enqueue_contact_batch(queue: str, site: str, domain_suffix: str,
                          batch_id: int, limit: int) -> int:
    """contact 批次入队：SELECT pending shops → INSERT items 带 batch_id
    → shops 置 in_progress（BEGIN IMMEDIATE 单事务，与 daemon topup 互斥）。

    limit>0 限量（<=0 不限）。返回入队行数。
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        sql = ("SELECT * FROM shops WHERE status='pending'"
               " AND substr(domain, -?, ?) = ?"
               " ORDER BY first_seen_at, id")
        params: list = [len(domain_suffix), len(domain_suffix), domain_suffix]
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        now = _bj_now()
        for r in rows:
            payload = json.dumps(
                {"domain": r["domain"], "name": r["name"],
                 "url": r["url"]},
                ensure_ascii=False)
            conn.execute(
                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (queue, site, batch_id, payload, now))
            conn.execute(
                "UPDATE shops SET status='in_progress' WHERE id=?",
                (r["id"],))
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def enqueue_feeder_batch(queue: str, site: str, batch_id: int,
                         limit: int) -> tuple[int, int]:
    """feeder 批次入队：1 条 discover + 活跃类目 category 种子，全部带
    batch_id 与 payload.batch_limit（收束边界，0=不限）。幂等：已有同
    keyword pending category / pending discover 跳过。返回 (n_cat, n_disc)。
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        n_cat = 0
        for row in conn.execute(
                "SELECT keyword, name FROM category_progress"
                " WHERE exhausted=0 ORDER BY id").fetchall():
            kw, name = row[0], row[1] or row[0]
            exists = conn.execute(
                "SELECT COUNT(*) FROM work_items WHERE queue=?"
                " AND status='pending'"
                " AND json_extract(payload_json, '$.kind')='category'"
                " AND json_extract(payload_json, '$.keyword')=?",
                (queue, kw)).fetchone()[0]
            if exists:
                continue
            payload = {"kind": "category", "keyword": kw, "name": name,
                       "batch_limit": limit}
            conn.execute(
                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (queue, site, batch_id,
                 json.dumps(payload, ensure_ascii=False), _bj_now()))
            n_cat += 1
        n_disc = 0
        exists_disc = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE queue=?"
            " AND status='pending'"
            " AND json_extract(payload_json, '$.kind')='discover'",
            (queue,)).fetchone()[0]
        if not exists_disc:
            payload = {"kind": "discover", "batch_limit": limit}
            conn.execute(
                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (queue, site, batch_id,
                 json.dumps(payload, ensure_ascii=False), _bj_now()))
            n_disc = 1
        conn.commit()
        return n_cat, n_disc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _normalize_numbers(raw, default_cc="86"):
    """规范化号码为纯数字（E.164 不含 +），8-15 位；11 位 1 开头补国家码。

    与 fetcher.atoms.wa_check.normalize_numbers 同语义（平台不 import
    fetcher，本地复制，SPEC §3.1 双份裁定）。
    """
    import re
    digits_re = re.compile(r"\D+")
    cn_re = re.compile(r"1\d{10}$")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        digits = digits_re.sub("", str(item or ""))
        if default_cc and cn_re.fullmatch(digits):
            digits = default_cc + digits
        if 8 <= len(digits) <= 15 and digits not in seen:
            seen.add(digits)
            out.append(digits)
    return out


def enqueue_wa_batch(batch_id: int, accounts: list[str],
                     limit: int = 0) -> int:
    """wa_check 批次入队：contacts 未查号码 → 50/块 → 账号按块轮换。

    accounts 为空拒绝（防空跑 default 主号，与 wa_tasks 拒绝语义一致）。
    requires=["local"]、site=NULL。返回入队 item 数。
    """
    accounts = [str(a).strip() for a in (accounts or []) if str(a).strip()]
    if not accounts:
        return 0
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        sql = ("SELECT mobile FROM contacts WHERE wa_checked_at IS NULL"
               " AND mobile IS NOT NULL AND TRIM(mobile) <> ''"
               " ORDER BY id ASC")
        if limit > 0:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()
        numbers: list[str] = []
        for (mobile,) in rows:
            for n in _normalize_numbers([mobile], "86"):
                numbers.append(n)
        batches = [numbers[i:i + 50]
                   for i in range(0, len(numbers), 50)]
        n = 0
        now = _bj_now()
        for i, batch in enumerate(batches):
            account = accounts[i % len(accounts)]
            payload = {"numbers": batch, "account": account,
                       "batch_size": 50}
            conn.execute(
                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
                " requires, created_at) VALUES (?, NULL, ?, ?, ?, ?)",
                ("wa_check", batch_id,
                 json.dumps(payload, ensure_ascii=False),
                 '["local"]', now))
            n += 1
        conn.commit()
        return n
    except Exception:
        conn.rollback()
        raise
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
