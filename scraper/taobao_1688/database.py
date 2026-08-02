# -*- coding: utf-8 -*-
"""
1688 采集数据存储层（SQLite）

数据库文件: .cache/1688.db（项目根目录下，gitignored）

表结构:

    crawl_runs  每次店铺采集任务的运行记录
    shops       店铺主表（域名唯一），status 跟踪联系方式抓取状态:
                    pending     — 待抓取联系方式
                    in_progress — 已被某个 worker 认领、抓取中
                                  （进程中断会残留，启动时自动重置回 pending）
                    done        — 已抓取，且店铺填有联系方式（已入 contacts 表）
                    no_contact  — 已抓取，但店铺未填任何联系方式（不入 contacts）
                    failed      — 抓取失败（可用 --retry-failed 重置后重试）

并发说明（contact_fetcher.py --workers / shop_crawler.py --workers）:
    - 每个 worker 线程各自持有 ShopDB 实例（sqlite3 连接不可跨线程共享）；
    - 数据库开 WAL 模式 + busy timeout 30s，多读单写互不阻塞；
    - 店铺认领走 claim_pending_shops()（BEGIN IMMEDIATE 事务内
      SELECT+UPDATE 为原子操作），不会两个 worker 抓到同一家店。
    contacts    店铺联系方式（一店一条；字段全空的也保留记录，
                用 shops.status 区分 done / no_contact）
    category_progress  类目分页进度（keyword 唯一）：next_page 为下次
                       应采集的页码；深页无结果时置 exhausted=1，
                       之后采集跳过该类目，避免重复采已采过的页
    cookies     按出口 IP 隔离的 1688 Cookie（identity = 出口 IP，
                直连记 'direct'），记录每个 Cookie 的过期时间 expires；
                会话链路一致性要求 Cookie 与出口 IP 不错配，
                因此代理模式与直连模式的 Cookie 分开存取

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

    # Cookie（按出口 IP 隔离）
    db.save_cookies(identity, playwright_cookies)
    cookies = db.load_cookies(identity)   # 自动剔除已过期的
    db.close()
"""

from __future__ import annotations  # 兼容 Python < 3.10 的 X | None 注解

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

CREATE TABLE IF NOT EXISTS cookies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    identity   TEXT NOT NULL,               -- 出口 IP；直连记 'direct'
    name       TEXT NOT NULL,
    value      TEXT NOT NULL,
    domain     TEXT NOT NULL,
    path       TEXT DEFAULT '/',
    secure     INTEGER DEFAULT 0,
    http_only  INTEGER DEFAULT 0,
    expires    INTEGER,                     -- Unix 时间戳；NULL/<=0 = 会话/未知
    updated_at TEXT NOT NULL,
    UNIQUE(identity, domain, path, name)
);

CREATE INDEX IF NOT EXISTS idx_cookies_identity ON cookies(identity);

-- 出口 IP 事件流水：记录每个 IP 的启动/风控遭遇（滑块/登录墙），
-- 用于评估代理 IP 质量、发现重复发放的 IP 和高危 IP
CREATE TABLE IF NOT EXISTS ip_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    identity   TEXT NOT NULL,      -- 出口 IP；直连记 'direct'
    event      TEXT NOT NULL,      -- launch / block_slider / block_login / block_other
    detail     TEXT,               -- 通道入口、风控原因等
    req_since_block INTEGER,       -- 仅 block_* 事件：本次触发时距该 IP
                                   -- 上次触发已爬多少个页面请求（触发阈值样本）
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ip_events_identity ON ip_events(identity);

-- 每个出口 IP 的抓取计数与风控触发统计（tmd 率 = blocks / requests），
-- 回答「一个 IP 爬多少个会触发反爬、多少以内算安全」
CREATE TABLE IF NOT EXISTS ip_stats (
    identity      TEXT PRIMARY KEY,              -- 出口 IP；直连记 'direct'
    requests      INTEGER NOT NULL DEFAULT 0,    -- 累计页面请求数（含被拦的尝试）
    ok            INTEGER NOT NULL DEFAULT 0,    -- 成功解析次数
    blocks        INTEGER NOT NULL DEFAULT 0,    -- 风控触发次数（滑块/登录墙/其他）
    last_block_at TEXT,                          -- 最近一次触发时间
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_progress (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword         TEXT NOT NULL UNIQUE,           -- 类目关键词
    name            TEXT,                           -- 类目显示名
    next_page       INTEGER NOT NULL DEFAULT 1,     -- 下次应采集的页码（1 起）
    pages_crawled   INTEGER NOT NULL DEFAULT 0,     -- 已采页数
    shops_found     INTEGER NOT NULL DEFAULT 0,     -- 累计提取到的店铺数（含重复）
    exhausted       INTEGER NOT NULL DEFAULT 0,     -- 1 = 已采到末页，之后跳过
    last_crawled_at TEXT
);
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
        # busy timeout 30s：多 worker 并发写时等待锁而不是直接报 database is locked
        self.conn = sqlite3.connect(str(db_path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        # WAL：多读单写并发互不阻塞（对多 worker 抓取至关重要）
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
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
        # 旧库中字段全空的 contacts 记录，对应店铺 -> no_contact（记录保留备查）
        self.conn.execute(
            """UPDATE shops SET status='no_contact'
               WHERE status='done' AND id IN (
                   SELECT shop_id FROM contacts
                   WHERE contact_person IS NULL AND phone IS NULL
                     AND mobile IS NULL AND fax IS NULL AND address IS NULL)""")
        # ip_events 补 req_since_block 列（tmd 触发阈值样本：
        # 本次触发时距该 IP 上次触发已爬多少个页面请求）
        evt_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(ip_events)")}
        if "req_since_block" not in evt_cols:
            self.conn.execute(
                "ALTER TABLE ip_events ADD COLUMN req_since_block INTEGER")

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

    def claim_pending_shops(self, limit: int = 1) -> list[sqlite3.Row]:
        """原子认领 pending 店铺：SELECT + 置为 in_progress 在同一事务内完成。

        多 worker 并发调用安全（BEGIN IMMEDIATE 立即取写锁），
        同一店铺只会被一个 worker 领到。返回认领到的店铺行（可能少于 limit）。
        """
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
        """把 in_progress 重置回 pending（进程中断残留的认领，启动时调用）。"""
        cur = self.conn.execute(
            "UPDATE shops SET status='pending' WHERE status='in_progress'")
        self.conn.commit()
        return cur.rowcount

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

    def mark_shop_no_contact(self, domain: str, bump_attempts: bool = True):
        """店铺已抓取但未填任何联系方式，标记 no_contact。

        空联系方式现在也会入 contacts 表备查；此时 save_contact 已计过一次
        attempts，调用方应传 bump_attempts=False 避免重复计数。
        """
        sql = "UPDATE shops SET status='no_contact'"
        if bump_attempts:
            sql += ", attempts=attempts+1"
        self.conn.execute(sql + " WHERE domain=?", (domain,))
        self.conn.commit()

    # ---------- category_progress ----------
    def get_category_progress(self, keyword: str) -> dict | None:
        """取类目分页进度（无记录返回 None）。"""
        row = self.conn.execute(
            "SELECT * FROM category_progress WHERE keyword=?",
            (keyword,)).fetchone()
        return dict(row) if row else None

    def advance_category_page(self, keyword: str, name: str = None,
                              shops_found: int = 0) -> int:
        """记录类目一页采集完成：页码 +1、累计页数/店铺数，返回下次应采页码。"""
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

    def get_exhausted_keywords(self) -> set:
        """返回所有已采到末页的类目关键词（shop_crawler 选类目时跳过）。"""
        rows = self.conn.execute(
            "SELECT keyword FROM category_progress WHERE exhausted=1").fetchall()
        return {r[0] for r in rows}

    def mark_category_exhausted(self, keyword: str, name: str = None):
        """标记类目已采到末页（页码不前进，之后采集跳过该类目）。"""
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

    # ---------- cookies ----------
    def save_cookies(self, identity: str, cookies: list[dict]) -> int:
        """保存某出口 IP 下的 Cookie（按 identity+domain+path+name UPSERT 覆盖）。"""
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
        """加载某出口 IP 下未过期的 Cookie（Playwright 格式，自动剔除已过期）。"""
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
        """某出口 IP 下 Cookie 的数量/已过期数/最近过期时间（用于日志）。"""
        now = int(time.time())
        q = lambda sql, *a: self.conn.execute(sql, (identity, *a)).fetchone()[0]
        total = q("SELECT COUNT(*) FROM cookies WHERE identity=?")
        expired = q("SELECT COUNT(*) FROM cookies WHERE identity=?"
                    " AND expires IS NOT NULL AND expires > 0 AND expires <= ?",
                    now)
        earliest_ts = q("SELECT MIN(expires) FROM cookies WHERE identity=?"
                        " AND expires IS NOT NULL AND expires > ?", now)
        earliest = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(earliest_ts))
                    if earliest_ts else None)
        return {"total": total, "expired": expired, "earliest_expiry": earliest}

    # ---------- IP 事件流水 ----------

    def record_ip_event(self, identity: str, event: str,
                        detail: str = "",
                        req_since_block: int | None = None) -> None:
        """记录一条出口 IP 事件（launch / block_slider / block_login 等）。

        req_since_block — 仅 block_* 事件使用：本次触发时，距该 IP 上次
        触发已爬多少个页面请求（触发阈值样本，评估「爬多少个会触发」用）。
        """
        try:
            self.conn.execute(
                "INSERT INTO ip_events (identity, event, detail,"
                " req_since_block, created_at) VALUES (?, ?, ?, ?, ?)",
                (identity, event, detail[:300] if detail else "",
                 req_since_block, _now()))
            self.conn.commit()
        except Exception:
            pass  # 事件流水不影响主流程

    def ip_event_summary(self) -> list[dict]:
        """按 IP 汇总事件次数（评估 IP 质量用）。"""
        rows = self.conn.execute(
            """SELECT identity,
                      SUM(event='launch')       AS launches,
                      SUM(event='block_slider') AS sliders,
                      SUM(event='block_login')  AS login_walls,
                      MAX(created_at)           AS last_seen
               FROM ip_events WHERE identity != 'direct'
               GROUP BY identity ORDER BY last_seen DESC""").fetchall()
        return [dict(r) for r in rows]

    # ---------- tmd（反爬验证）触发统计 ----------

    def ip_stat_request(self, identity: str, ok: bool = False) -> None:
        """累计该出口 IP 的一次页面请求（ok=True 表示成功解析）。

        每次 scrape 调用 = 一次页面请求；网络/代理层错误（请求没到目标站）
        由调用方跳过不计。tmd 率 = blocks / requests。
        """
        try:
            self.conn.execute(
                """INSERT INTO ip_stats (identity, requests, ok, updated_at)
                   VALUES (?, 1, ?, ?)
                   ON CONFLICT(identity) DO UPDATE SET
                       requests = requests + 1,
                       ok = ok + ?,
                       updated_at = ?""",
                (identity, 1 if ok else 0, _now(), 1 if ok else 0, _now()))
            self.conn.commit()
        except Exception:
            pass  # 统计不影响主流程

    def ip_stat_block(self, identity: str) -> None:
        """累计该出口 IP 的一次风控触发（滑块/登录墙/其他拦截）。"""
        try:
            self.conn.execute(
                """INSERT INTO ip_stats (identity, blocks, last_block_at,
                                         updated_at)
                   VALUES (?, 1, ?, ?)
                   ON CONFLICT(identity) DO UPDATE SET
                       blocks = blocks + 1,
                       last_block_at = ?,
                       updated_at = ?""",
                (identity, _now(), _now(), _now(), _now()))
            self.conn.commit()
        except Exception:
            pass

    def tmd_report(self) -> dict:
        """tmd（反爬验证）触发统计：每 IP 的请求/触发计数与触发间隔分布。

        返回 {"rows": [...], "gaps": [...]}:
            rows — 每 IP 一行：requests/ok/blocks/last_block_at +
                   avg_gap/min_gap/max_gap（历史每次触发时「距上次触发
                   已爬多少个页面请求」的分布，即触发阈值的经验值）
            gaps — 全部触发间隔原始值（算整体经验值用）
        """
        rows = self.conn.execute(
            """SELECT s.identity, s.requests, s.ok, s.blocks, s.last_block_at,
                      AVG(e.req_since_block) AS avg_gap,
                      MIN(e.req_since_block) AS min_gap,
                      MAX(e.req_since_block) AS max_gap
               FROM ip_stats s
               LEFT JOIN ip_events e
                   ON e.identity = s.identity
                  AND e.event LIKE 'block\\_%' ESCAPE '\\'
                  AND e.req_since_block IS NOT NULL
               GROUP BY s.identity
               ORDER BY s.requests DESC""").fetchall()
        gaps = [r[0] for r in self.conn.execute(
            """SELECT req_since_block FROM ip_events
               WHERE event LIKE 'block\\_%' ESCAPE '\\'
                 AND req_since_block IS NOT NULL""").fetchall()]
        return {"rows": [dict(r) for r in rows], "gaps": gaps}

    def format_tmd_report(self) -> str:
        """把 tmd 触发统计渲染成可读报告（summary / --tmd-report 共用）。

        回答三个问题：
            - tmd 率是多少：触发次数 / 页面请求数
            - 每爬多少个会触发一次反爬：触发间隔的平均/最少/最多
            - 一个 IP 爬多少个以内算安全：最少触发间隔 × 0.8
        """
        rep = self.tmd_report()
        rows, gaps = rep["rows"], rep["gaps"]
        if not rows:
            return "暂无 tmd 统计（还没有带统计的抓取记录）"
        lines = ["tmd（反爬验证）触发统计 —— 每个出口 IP 的安全性:",
                 f"    {'出口IP':<17}{'请求':>6}{'成功':>6}{'触发':>5}"
                 f"{'tmd率':>8}{'平均间隔':>9}{'最少':>6}{'最多':>6}  最近触发"]
        for r in rows:
            rate = (f"{r['blocks'] / r['requests'] * 100:.1f}%"
                    if r["requests"] else "—")
            fmt = lambda v: f"{v:.0f}" if v is not None else "—"
            lines.append(
                f"    {r['identity']:<17}{r['requests']:>6}{r['ok']:>6}"
                f"{r['blocks']:>5}{rate:>8}{fmt(r['avg_gap']):>9}"
                f"{fmt(r['min_gap']):>6}{fmt(r['max_gap']):>6}  "
                f"{r['last_block_at'] or '—'}")
        tot_req = sum(r["requests"] for r in rows)
        tot_blk = sum(r["blocks"] for r in rows)
        if tot_req:
            lines.append(f"    整体: {tot_req} 次页面请求，触发 {tot_blk} 次，"
                         f"tmd率 {tot_blk / tot_req * 100:.2f}%")
        if gaps:
            avg = sum(gaps) / len(gaps)
            safe = max(1, int(min(gaps) * 0.8))
            lines.append(
                f"    经验值: 平均爬 ~{avg:.0f} 个页面触发一次反爬；"
                f"历史最少 {min(gaps)} 个、最多 {max(gaps)} 个即触发")
            lines.append(
                f"    安全线: 单 IP 连续抓取 ≤ {safe} 个（最少触发间隔 × 0.8）"
                f"相对安全，超过 {min(gaps)} 个后触发风险显著上升")
        else:
            lines.append("    尚无触发记录，样本不足，继续跑一段时间后再看经验值")
        return "\n".join(lines)

    # ---------- 查询 ----------
    def stats(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        return {
            "runs": q("SELECT COUNT(*) FROM crawl_runs"),
            "shops": q("SELECT COUNT(*) FROM shops"),
            "pending": q("SELECT COUNT(*) FROM shops WHERE status='pending'"),
            "in_progress": q("SELECT COUNT(*) FROM shops WHERE status='in_progress'"),
            "done": q("SELECT COUNT(*) FROM shops WHERE status='done'"),
            "no_contact": q("SELECT COUNT(*) FROM shops WHERE status='no_contact'"),
            "failed": q("SELECT COUNT(*) FROM shops WHERE status='failed'"),
            "with_mobile": q("SELECT COUNT(*) FROM contacts"
                             " WHERE mobile IS NOT NULL AND mobile != ''"),
            "categories_tracked": q("SELECT COUNT(*) FROM category_progress"),
            "categories_exhausted": q("SELECT COUNT(*) FROM category_progress"
                                      " WHERE exhausted=1"),
        }

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    db = ShopDB()
    print(f"数据库: {DB_PATH}")
    print(f"统计: {db.stats()}")
    db.close()
