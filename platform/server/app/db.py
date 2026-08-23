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
            "CREATE TABLE IF NOT EXISTS providers ("            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "kind TEXT NOT NULL, "
            "name TEXT NOT NULL, "
            "config_json TEXT NOT NULL, "
            "enabled INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)")
        # 额度耗尽时间（如 Apify 月硬顶），查号脚本据此跳过并估算恢复日（约 30 天账期）
        prov_cols = {r[1] for r in conn.execute("PRAGMA table_info(providers)")}
        if "quota_exhausted_at" not in prov_cols:
            conn.execute(
                "ALTER TABLE providers ADD COLUMN quota_exhausted_at TEXT")
        # 账号邮箱（区分同 kind 多账号，如 Apify 免费号）
        if "email" not in prov_cols:
            conn.execute("ALTER TABLE providers ADD COLUMN email TEXT")
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
        # 费用记账表（costs.py 同步写入）：
        # - date 口径：Apify real 行存原始 UTC 账单日期（与 Apify 控制台对账），
        #   estimate 行存北京日期（state JSON 的 daily key 即北京日期）
        # - source：real=官方账单 API；estimate=单价折算
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cost_records ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "date TEXT NOT NULL, "
            "provider TEXT NOT NULL, "
            "channel TEXT NOT NULL, "
            "service TEXT, "  # Apify 服务项；估算行存 ''（SQLite UNIQUE 中 NULL 互不相等，不能用 NULL）
            "source TEXT NOT NULL, "
            "quantity REAL, "
            "unit TEXT, "
            "usd REAL NOT NULL, "
            "detail_json TEXT, "
            "synced_at TEXT NOT NULL, "
            "UNIQUE(date, provider, channel, service, source))")
        # 采集脚本参数配置表（/scripts 页调参落库，scripts.py seed 默认值）：
        # name=fb/x/wa，params 为 JSON（{"memo23_daily_results":10000} 等）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS script_configs ("
            "name TEXT PRIMARY KEY, "
            "params TEXT NOT NULL DEFAULT '{}', "
            "updated_at TEXT)")
        # P4：work_items 批次索引（生产库表由 fetcher 建，平台只补索引不建表；
        # 探测式——表不存在则跳过，防御性）
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        # fb_contacts 导出标记列（表由 fetcher 建，缺表跳过）：
        # exported_at TEXT NULL：导出时间（北京时间），NULL=从未导出
        if "fb_contacts" in tables:
            fb_cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(fb_contacts)")}
            if "exported_at" not in fb_cols:
                conn.execute(
                    "ALTER TABLE fb_contacts ADD COLUMN exported_at TEXT")
        if "work_items" in tables:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_items_batch"
                " ON work_items(batch_id, status)")
        # P5：tasks 表重建——删除 celery_id/flow_id 死列与 flows 表（方案 B 交换式）
        # 守卫：旧 schema 才重建；已迁移库重跑 migrate() 零变化（幂等）。
        # 交换顺序（建 tasks_new → INSERT SELECT → DROP tasks → RENAME）保证
        # task_events/proxy_channels 的 REFERENCES tasks(id) 不被 SQLite RENAME
        # 重写成指向被删表名（RENAME-first 会让外键悬空）。
        # 前提：本库从未启用 PRAGMA foreign_keys；若启用，DROP TABLE tasks 会
        # 因 task_events/proxy_channels 引用直接失败。
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        if "celery_id" in cols:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("""
                    CREATE TABLE tasks_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        type TEXT NOT NULL,
                        params_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        progress_json TEXT,
                        stop_requested INTEGER NOT NULL DEFAULT 0,
                        error TEXT,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT
                    )""")
                conn.execute("""
                    INSERT INTO tasks_new (id, type, params_json, status,
                                           progress_json, stop_requested, error,
                                           created_at, started_at, finished_at)
                    SELECT id, type, params_json, status, progress_json,
                           stop_requested, error, created_at, started_at,
                           finished_at
                    FROM tasks""")
                conn.execute("DROP TABLE tasks")
                conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
                conn.execute("DROP TABLE IF EXISTS flows")
                conn.execute("CREATE INDEX idx_tasks_status ON tasks(status)")
                conn.execute("COMMIT")
            except Exception:
                conn.rollback()  # 幂等：无事务时不抛；失败留原表（tasks 未动）
                raise
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


def enqueue_fb_post_batch(queue: str, site: str, batch_id: int,
                           limit: int) -> int:
    """fb_post 批次入队：SELECT pending fb_posts → INSERT items 带
    batch_id → fb_posts 置 in_progress（BEGIN IMMEDIATE 单事务，与 daemon
    topup_fb_post_work_items 互斥不双喂，SPEC §7.4）。

    payload 键 {url,domain,name}（SPEC §3.2：domain=群 URL，由 group_id
    拼接）；fb_posts 表不存在（fetcher 侧未建表）→ 返回 0（防御性探测，
    参照 work_items 索引探测模式）。limit>0 限量（<=0 不限）。返回入队行数。
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "fb_posts" not in tables:
            return 0
        conn.execute("BEGIN IMMEDIATE")
        sql = ("SELECT * FROM fb_posts WHERE status='pending'"
               " ORDER BY first_seen_at, id")
        params: list = []
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        now = _bj_now()
        for r in rows:
            domain = (f"https://www.facebook.com/groups/{r['group_id']}"
                      if r["group_id"] else "")
            payload = json.dumps(
                {"url": r["url"], "domain": domain,
                 "name": r["group_name"] or ""},
                ensure_ascii=False)
            conn.execute(
                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (queue, site, batch_id, payload, now))
            conn.execute(
                "UPDATE fb_posts SET status='in_progress' WHERE id=?",
                (r["id"],))
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def enqueue_fb_discover_batch(batch_id: int, keywords: str,
                               pages: int) -> int:
    """fb_discover 批次入队：关键词（换行分隔）逐词 × 页码展开。

    payload {"kind":"serp","engine":"ddg","query":kw,"page":N}；
    requires=["local"]、site=NULL。幂等：同 query+page 已有 pending
    跳过（防循环模式重入批量重复堆栈，参照 enqueue_feeder_batch 的
    json_extract 幂等模式）。keywords 空 → 0。返回入队 item 数。
    """
    words = [w.strip() for w in (keywords or "").splitlines()]
    words = [w for w in words if w]
    if not words:
        return 0
    pages = max(1, int(pages))
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        now = _bj_now()
        n = 0
        for kw in words:
            for page in range(1, pages + 1):
                exists = conn.execute(
                    "SELECT COUNT(*) FROM work_items WHERE queue=?"
                    " AND status='pending'"
                    " AND json_extract(payload_json, '$.query')=?"
                    " AND json_extract(payload_json, '$.page')=?",
                    ("discover_fb", kw, page)).fetchone()[0]
                if exists:
                    continue
                payload = {"kind": "serp", "engine": "ddg",
                           "query": kw, "page": page}
                conn.execute(
                    "INSERT INTO work_items (queue, site, batch_id,"
                    " payload_json, requires, created_at)"
                    " VALUES (?, NULL, ?, ?, ?, ?)",
                    ("discover_fb", batch_id,
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


def enqueue_fb_group_batch(batch_id: int, provider: str,
                           posts_per_group: int, limit: int) -> int:
    """fb_group 批次入队：SELECT pending fb_groups → INSERT items →
    源行置 in_progress（BEGIN IMMEDIATE 单事务，与群采集消费互斥不双喂，
    对齐 enqueue_fb_post_batch）。

    payload {"url","provider","limit"}（limit=posts_per_group）；
    requires=["local"]、site=NULL。fb_groups 表不存在（fetcher 侧未建
    表）→ 返回 0（防御性探测）。limit>0 限量（<=0 不限）。返回入队行数。
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "fb_groups" not in tables:
            return 0
        conn.execute("BEGIN IMMEDIATE")
        sql = ("SELECT * FROM fb_groups WHERE status='pending'"
               " ORDER BY first_seen_at, id")
        params: list = []
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        now = _bj_now()
        for r in rows:
            payload = json.dumps(
                {"url": r["url"], "provider": provider,
                 "limit": posts_per_group},
                ensure_ascii=False)
            conn.execute(
                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
                " requires, created_at) VALUES (?, NULL, ?, ?, ?, ?)",
                ("crawl_fb_group", batch_id, payload, '["local"]', now))
            conn.execute(
                "UPDATE fb_groups SET status='in_progress' WHERE id=?",
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
    """wa_check 批次入队：fb_contacts ∪ contacts 未查号码（FB 源优先）
    → 50/块 → 账号按块轮换（双源口径与 fetcher wa_check_topup 一致，SPEC §7.6）。

    - fb_contacts：仅 bucket='cn_uncertain' 未查号（declared_wa/overseas
      桶不进），排在 contacts 未查 mobile 之前 → 批次按 FB 优先消费；
      跨源同号经 seen 去重；
    - declared_wa 抽样校准（Step 3.2）：按 max(1, N×10%) 抽未查 declared
      号混入同批（ORDER BY RANDOM()），供一致率统计；
    - limit>0 时作用于不确定号上限（fb 优先截取），抽样在其上追加；
    accounts 为空拒绝（防空跑 default 主号）。requires=["local"]、
    site=NULL。返回入队 item 数。
    """
    accounts = [str(a).strip() for a in (accounts or []) if str(a).strip()]
    if not accounts:
        return 0
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        # 防御性探测（SPEC §4.3）：fb_contacts 表不存在（fetcher 侧未建表/旧库）
        # 时回退 contacts-only 挑号，与历史行为一致
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "fb_contacts" in tables:
            fb_rows = conn.execute(
                "SELECT number FROM fb_contacts"
                " WHERE bucket='cn_uncertain' AND wa_checked_at IS NULL"
                " ORDER BY number").fetchall()
            contact_rows = conn.execute(
                "SELECT mobile FROM contacts"
                " WHERE wa_checked_at IS NULL AND mobile IS NOT NULL"
                "   AND TRIM(mobile) <> ''"
                " ORDER BY mobile").fetchall()
            rows = fb_rows + contact_rows
        else:
            rows = conn.execute(
                "SELECT mobile FROM contacts"
                " WHERE wa_checked_at IS NULL AND mobile IS NOT NULL"
                "   AND TRIM(mobile) <> '' ORDER BY id").fetchall()
        if limit > 0:
            rows = rows[:limit]
        numbers: list[str] = []
        seen: set[str] = set()
        for (number,) in rows:
            for n in _normalize_numbers([number], "86"):
                if n not in seen:
                    seen.add(n)
                    numbers.append(n)
        if not numbers:
            # 无不确定号可查 → 不产生批次（与 fetcher wa_check_topup 一致，
            # 抽样以不确定号数为基准，N=0 不抽）
            return 0
        # declared_wa 抽样（已查不重抽；fb_contacts 缺失时跳过）
        if "fb_contacts" in tables:
            n_sample = max(1, int(len(numbers) * 0.10))
            declared = conn.execute(
                "SELECT number FROM fb_contacts WHERE bucket='declared_wa'"
                " AND wa_checked_at IS NULL ORDER BY RANDOM() LIMIT ?",
                (n_sample,)).fetchall()
            for (number,) in declared:
                for n in _normalize_numbers([number], "86"):
                    if n not in seen:
                        seen.add(n)
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


def mark_fb_contacts_exported(ids: list[int]) -> int:
    """把导出的 fb_contacts 行标记为已导出（exported_at=北京时间）。

    短事务 + busy_timeout；ids 分块（SQLite 变量上限 999，取 500 一块）。
    返回更新行数。ids 为空直接返回 0。
    """
    if not ids:
        return 0
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        now = _bj_now()
        n = 0
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"UPDATE fb_contacts SET exported_at=? WHERE id IN ({q})",
                [now] + list(chunk))
            n += cur.rowcount
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
