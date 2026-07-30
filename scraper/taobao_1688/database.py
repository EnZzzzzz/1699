# -*- coding: utf-8 -*-
"""
1688 采集数据存储层（SQLite）

数据库文件: .cache/1688.db（项目根目录下，gitignored）

表结构:

    crawl_runs  每次店铺采集任务的运行记录
    shops       店铺主表（域名唯一），status 跟踪联系方式抓取状态:
                    pending    — 待抓取联系方式
                    done       — 已抓取，且店铺填有联系方式（已入 contacts 表）
                    no_contact — 已抓取，但店铺未填任何联系方式（不入 contacts）
                    failed     — 抓取失败（可用 --retry-failed 重置后重试）
    contacts    店铺联系方式（一店一条，仅记录有实际内容的店铺）

两个脚本分工:
    shop_crawler.py    生产者：类目 -> 店铺入库（status=pending）
    contact_fetcher.py 消费者：取 pending 店铺 -> 抓联系方式 -> 更新状态
                       可随时中断重启，自动从断点续爬

用法:
    from database import ShopDB
    db = ShopDB()
    run_id = db.start_run(category_name, category_keyword)
    db.upsert_shops(shops, run_id=run_id)
    pending = db.get_pending_shops(limit=10)
    db.save_contact(domain, contact_dict, source_url=..., raw_text=...)
    db.mark_shop_failed(domain)
    db.finish_run(run_id, shops_found=35)
    db.close()
"""

import sqlite3
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = ROOT_DIR / ".cache" / "1688.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS crawl_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    category_name    TEXT,
    category_keyword TEXT,
    shops_found      INTEGER DEFAULT 0,
    shops_picked     INTEGER DEFAULT 0,
    note             TEXT
);

CREATE TABLE IF NOT EXISTS shops (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    domain           TEXT NOT NULL UNIQUE,          -- shopxxx.1688.com
    name             TEXT,                          -- 公司/店铺名
    url              TEXT NOT NULL,
    category_keyword TEXT,                          -- 首次发现时的类目关键词
    run_id           INTEGER REFERENCES crawl_runs(id),
    status           TEXT NOT NULL DEFAULT 'pending', -- pending/done/failed
    attempts         INTEGER NOT NULL DEFAULT 0,    -- 联系方式抓取尝试次数
    first_seen_at    TEXT NOT NULL,
    last_seen_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id        INTEGER NOT NULL UNIQUE REFERENCES shops(id),
    contact_person TEXT,                            -- 联系人姓名
    gender         TEXT,                            -- 男/女（由 先生/女士 推断）
    phone          TEXT,                            -- 座机
    mobile         TEXT,                            -- 手机
    fax            TEXT,                            -- 传真
    address        TEXT,                            -- 地址
    source_url     TEXT,                            -- 联系方式页 URL
    scraped_at     TEXT NOT NULL,
    raw_text       TEXT                             -- 页面原始文本片段（备查）
);

CREATE INDEX IF NOT EXISTS idx_shops_run ON shops(run_id);
CREATE INDEX IF NOT EXISTS idx_contacts_shop ON contacts(shop_id);
"""

# 依赖迁移后列（status）的索引，单独在 _migrate 之后创建
INDEXES_AFTER_MIGRATE = """
CREATE INDEX IF NOT EXISTS idx_shops_status ON shops(status);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class ShopDB:
    def __init__(self, db_path: Path | str = DB_PATH):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.executescript(INDEXES_AFTER_MIGRATE)
        self.conn.commit()

    def _migrate(self):
        """旧库升级: shops 表补 status/attempts 列，并把已有联系方式的店铺标记 done。"""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(shops)")}
        if "status" not in cols:
            self.conn.execute(
                "ALTER TABLE shops ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
        if "attempts" not in cols:
            self.conn.execute(
                "ALTER TABLE shops ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        # 已有 contacts 记录的店铺 -> done
        self.conn.execute(
            """UPDATE shops SET status='done'
               WHERE status='pending' AND id IN (SELECT shop_id FROM contacts)""")
        # contacts 中字段全空的记录清理掉，对应店铺 -> no_contact
        self.conn.execute(
            """UPDATE shops SET status='no_contact'
               WHERE status='done' AND id IN (
                   SELECT shop_id FROM contacts
                   WHERE contact_person IS NULL AND phone IS NULL
                     AND mobile IS NULL AND fax IS NULL AND address IS NULL)""")
        self.conn.execute(
            """DELETE FROM contacts
               WHERE contact_person IS NULL AND phone IS NULL
                 AND mobile IS NULL AND fax IS NULL AND address IS NULL""")

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
        """
        shops: [{"domain","name","url"}, ...]
        新店铺以 status='pending' 插入；已存在的只更新名字/last_seen，
        不动 status（保持抓取进度）。返回新增店铺数。
        """
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

    def get_pending_shops(self, limit: int = 10) -> list[sqlite3.Row]:
        """取 status='pending' 的店铺，按发现顺序返回。"""
        return self.conn.execute(
            "SELECT * FROM shops WHERE status='pending'"
            " ORDER BY first_seen_at, id LIMIT ?", (limit,)).fetchall()

    def count_pending(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM shops WHERE status='pending'").fetchone()[0]

    def reset_failed(self) -> int:
        """把 failed 的店铺重置回 pending（用于重试）。"""
        cur = self.conn.execute(
            "UPDATE shops SET status='pending' WHERE status='failed'")
        self.conn.commit()
        return cur.rowcount

    def mark_shop_done(self, domain: str):
        self.conn.execute(
            "UPDATE shops SET status='done', attempts=attempts+1 WHERE domain=?",
            (domain,))
        self.conn.commit()

    def mark_shop_failed(self, domain: str):
        self.conn.execute(
            "UPDATE shops SET status='failed', attempts=attempts+1 WHERE domain=?",
            (domain,))
        self.conn.commit()

    def mark_shop_no_contact(self, domain: str):
        """店铺已抓取但未填任何联系方式，标记 no_contact（不入 contacts 表）。"""
        self.conn.execute(
            "UPDATE shops SET status='no_contact', attempts=attempts+1"
            " WHERE domain=?", (domain,))
        self.conn.commit()

    # ---------- contacts ----------
    def save_contact(self, domain: str, contact: dict,
                     source_url: str = None, raw_text: str = None):
        """按店铺域名保存联系方式（一店一条，重复抓取则覆盖），并把店铺标记 done。"""
        row = self.conn.execute(
            "SELECT id FROM shops WHERE domain=?", (domain,)).fetchone()
        if not row:
            raise ValueError(f"店铺不存在，请先 upsert_shops: {domain}")
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

    # ---------- 查询 ----------
    def stats(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        return {
            "runs": q("SELECT COUNT(*) FROM crawl_runs"),
            "shops": q("SELECT COUNT(*) FROM shops"),
            "pending": q("SELECT COUNT(*) FROM shops WHERE status='pending'"),
            "done": q("SELECT COUNT(*) FROM shops WHERE status='done'"),
            "no_contact": q("SELECT COUNT(*) FROM shops WHERE status='no_contact'"),
            "failed": q("SELECT COUNT(*) FROM shops WHERE status='failed'"),
            "with_mobile": q("SELECT COUNT(*) FROM contacts"
                             " WHERE mobile IS NOT NULL AND mobile != ''"),
        }

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    db = ShopDB()
    print(f"数据库: {DB_PATH}")
    print(f"统计: {db.stats()}")
    db.close()
