# -*- coding: utf-8 -*-
"""
1688 数据存储层（server 版重写）。

重写自 scraper/taobao_1688/database.py（蓝本只读，未被 import），
同样的表结构与 SQL 语义：WAL + busy_timeout、claim_pending_shops
原子认领（BEGIN IMMEDIATE）、Cookie 按出口 IP 隔离、类目分页进度。
Celery worker 进程与 FastAPI 进程共享 .cache/1688.db。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ... import config

DB_PATH = config.DB_PATH


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class ShopDB:
    """每线程一个实例（sqlite3 连接不可跨线程共享）。"""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.conn = sqlite3.connect(str(db_path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")

    # ---------- crawl_runs ----------
    def start_run(self, category_name: str = None,
                  category_keyword: str = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO crawl_runs (started_at, category_name, category_keyword)"
            " VALUES (?, ?, ?)",
            (_now(), category_name, category_keyword))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, shops_found: int = 0,
                   shops_picked: int = 0, note: str = None):
        self.conn.execute(
            "UPDATE crawl_runs SET finished_at=?, shops_found=?,"
            " shops_picked=?, note=? WHERE id=?",
            (_now(), shops_found, shops_picked, note, run_id))
        self.conn.commit()

    # ---------- shops ----------
    def upsert_shops(self, shops: list[dict], run_id: int = None,
                     category_keyword: str = None) -> int:
        now = _now()
        inserted = 0
        for s in shops:
            domain, name = s.get("domain"), s.get("name")
            url = s.get("url") or f"https://{domain}"
            exists = self.conn.execute(
                "SELECT 1 FROM shops WHERE domain=?", (domain,)).fetchone()
            self.conn.execute(
                """INSERT INTO shops (domain, name, url, category_keyword,
                                      run_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(domain) DO UPDATE SET
                       name = COALESCE(excluded.name, shops.name),
                       run_id = excluded.run_id,
                       last_seen_at = excluded.last_seen_at""",
                (domain, name, url, category_keyword, run_id, now, now))
            if not exists:
                inserted += 1
        self.conn.commit()
        return inserted

    def claim_pending_shops(self, limit: int = 1) -> list[sqlite3.Row]:
        """原子认领 pending 店铺（BEGIN IMMEDIATE 内 SELECT+UPDATE）。"""
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            rows = self.conn.execute(
                "SELECT * FROM shops WHERE status='pending'"
                " ORDER BY first_seen_at, id LIMIT ?", (limit,)).fetchall()
            if rows:
                ids = [r["id"] for r in rows]
                self.conn.execute(
                    f"UPDATE shops SET status='in_progress'"
                    f" WHERE id IN ({','.join('?' * len(ids))})", ids)
            self.conn.commit()
            return rows
        except Exception:
            self.conn.rollback()
            raise

    def reset_in_progress(self) -> int:
        cur = self.conn.execute(
            "UPDATE shops SET status='pending' WHERE status='in_progress'")
        self.conn.commit()
        return cur.rowcount

    def count_pending(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM shops WHERE status='pending'").fetchone()[0]

    def count_shops(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]

    def mark_shop_failed(self, domain: str):
        self.conn.execute(
            "UPDATE shops SET status='failed', attempts=attempts+1 WHERE domain=?",
            (domain,))
        self.conn.commit()

    def mark_shop_no_contact(self, domain: str, bump_attempts: bool = True):
        sql = "UPDATE shops SET status='no_contact'"
        if bump_attempts:
            sql += ", attempts=attempts+1"
        self.conn.execute(sql + " WHERE domain=?", (domain,))
        self.conn.commit()

    # ---------- category_progress ----------
    def get_category_progress(self, keyword: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM category_progress WHERE keyword=?",
            (keyword,)).fetchone()
        return dict(row) if row else None

    def advance_category_page(self, keyword: str, name: str = None,
                              shops_found: int = 0) -> int:
        self.conn.execute(
            """INSERT INTO category_progress
                   (keyword, name, next_page, pages_crawled, shops_found,
                    last_crawled_at)
               VALUES (?, ?, 2, 1, ?, ?)
               ON CONFLICT(keyword) DO UPDATE SET
                   name = COALESCE(excluded.name, category_progress.name),
                   next_page = category_progress.next_page + 1,
                   pages_crawled = category_progress.pages_crawled + 1,
                   shops_found = category_progress.shops_found
                                 + excluded.shops_found,
                   last_crawled_at = excluded.last_crawled_at""",
            (keyword, name, shops_found, _now()))
        self.conn.commit()
        return self.conn.execute(
            "SELECT next_page FROM category_progress WHERE keyword=?",
            (keyword,)).fetchone()[0]

    def mark_category_exhausted(self, keyword: str, name: str = None):
        self.conn.execute(
            """INSERT INTO category_progress (keyword, name, exhausted,
                                              last_crawled_at)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(keyword) DO UPDATE SET
                   name = COALESCE(excluded.name, category_progress.name),
                   exhausted = 1,
                   last_crawled_at = excluded.last_crawled_at""",
            (keyword, name, _now()))
        self.conn.commit()

    # ---------- contacts ----------
    def save_contact(self, domain: str, contact: dict,
                     source_url: str = None, raw_text: str = None):
        row = self.conn.execute(
            "SELECT id FROM shops WHERE domain=?", (domain,)).fetchone()
        if not row:
            raise ValueError(f"店铺不存在: {domain}")
        shop_id = row[0]
        self.conn.execute(
            """INSERT INTO contacts (shop_id, contact_person, gender, phone,
                                     mobile, fax, address, source_url,
                                     scraped_at, raw_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(shop_id) DO UPDATE SET
                   contact_person=excluded.contact_person,
                   gender=excluded.gender,
                   phone=excluded.phone,
                   mobile=excluded.mobile,
                   fax=excluded.fax,
                   address=excluded.address,
                   source_url=excluded.source_url,
                   scraped_at=excluded.scraped_at,
                   raw_text=excluded.raw_text""",
            (shop_id, contact.get("contact_person"), contact.get("gender"),
             contact.get("phone"), contact.get("mobile"), contact.get("fax"),
             contact.get("address"), source_url, _now(), raw_text))
        self.conn.execute(
            "UPDATE shops SET status='done', attempts=attempts+1 WHERE id=?",
            (shop_id,))
        self.conn.commit()

    # ---------- cookies（按出口 IP 隔离）----------
    def save_cookies(self, identity: str, cookies: list[dict]) -> int:
        now = _now()
        for c in cookies:
            exp = c.get("expires") or c.get("expirationDate")
            try:
                exp = int(float(exp)) if exp and float(exp) > 0 else None
            except (TypeError, ValueError):
                exp = None
            self.conn.execute(
                """INSERT INTO cookies (identity, name, value, domain, path,
                                        secure, http_only, expires, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(identity, domain, path, name) DO UPDATE SET
                       value=excluded.value, secure=excluded.secure,
                       http_only=excluded.http_only, expires=excluded.expires,
                       updated_at=excluded.updated_at""",
                (identity, c["name"], c.get("value", ""), c.get("domain", ""),
                 c.get("path") or "/", int(bool(c.get("secure"))),
                 int(bool(c.get("httpOnly", c.get("http_only")))), exp, now))
        self.conn.commit()
        return len(cookies)

    def load_cookies(self, identity: str) -> list[dict]:
        now = int(time.time())
        rows = self.conn.execute(
            """SELECT * FROM cookies WHERE identity=?
               AND (expires IS NULL OR expires <= 0 OR expires > ?)""",
            (identity, now)).fetchall()
        out = []
        for r in rows:
            c = {"name": r["name"], "value": r["value"], "domain": r["domain"],
                 "path": r["path"] or "/", "secure": bool(r["secure"]),
                 "httpOnly": bool(r["http_only"])}
            if r["expires"]:
                c["expires"] = r["expires"]
            out.append(c)
        return out

    def cookie_info(self, identity: str) -> dict:
        now = int(time.time())
        q = lambda sql, *a: self.conn.execute(sql, (identity, *a)).fetchone()[0]  # noqa: E731
        total = q("SELECT COUNT(*) FROM cookies WHERE identity=?")
        expired = q("SELECT COUNT(*) FROM cookies WHERE identity=?"
                    " AND expires IS NOT NULL AND expires > 0 AND expires <= ?",
                    now)
        earliest_ts = q("SELECT MIN(expires) FROM cookies WHERE identity=?"
                        " AND expires IS NOT NULL AND expires > ?", now)
        earliest = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(earliest_ts))
                    if earliest_ts else None)
        return {"total": total, "expired": expired, "earliest_expiry": earliest}

    def seed_cookies_from_json(self, identity: str, cookie_path: Path) -> int:
        import json
        raw = json.loads(Path(cookie_path).read_text(encoding="utf-8"))
        seeds = [c for c in raw if "1688.com" in c.get("domain", "")]
        return self.save_cookies(identity, seeds)

    # ---------- 统计 ----------
    def stats(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "runs": q("SELECT COUNT(*) FROM crawl_runs"),
            "shops": q("SELECT COUNT(*) FROM shops"),
            "pending": q("SELECT COUNT(*) FROM shops WHERE status='pending'"),
            "in_progress": q("SELECT COUNT(*) FROM shops WHERE status='in_progress'"),
            "done": q("SELECT COUNT(*) FROM shops WHERE status='done'"),
            "no_contact": q("SELECT COUNT(*) FROM shops WHERE status='no_contact'"),
            "failed": q("SELECT COUNT(*) FROM shops WHERE status='failed'"),
        }

    def close(self):
        self.conn.close()
