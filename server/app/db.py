# -*- coding: utf-8 -*-
"""
数据库层：SQLAlchemy 引擎（指向 .cache/1688.db，WAL + busy_timeout）、
新增 4 表迁移（CREATE TABLE IF NOT EXISTS，绝不动现有 5 表）、青果 provider seed。
"""
from __future__ import annotations

import json

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

Base = declarative_base()

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 新增表 DDL（与 docs/service-architecture.md §4 一致；IF NOT EXISTS 幂等）
# ---------------------------------------------------------------------------
NEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    config_json TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT NOT NULL,
    params_json   TEXT NOT NULL,
    celery_id     TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    progress_json TEXT,
    stop_requested INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT
);

CREATE TABLE IF NOT EXISTS proxy_channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id  INTEGER REFERENCES providers(id),
    tunnel       TEXT,
    exit_ip      TEXT,
    status       TEXT NOT NULL DEFAULT 'idle',
    used_by_task INTEGER REFERENCES tasks(id),
    ip_expires_at TEXT,
    last_probe_at TEXT,
    UNIQUE(provider_id, tunnel)
);

CREATE TABLE IF NOT EXISTS proxy_usage_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES proxy_channels(id),
    task_id    INTEGER REFERENCES tasks(id),
    task_type  TEXT,
    exit_ip    TEXT,
    result     TEXT,
    ts         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON proxy_usage_events(ts);
CREATE INDEX IF NOT EXISTS idx_usage_channel_ts ON proxy_usage_events(channel_id, ts);

-- 任务实时事件流（每任务保留最近 500 条，超出由 emit 侧删除）
CREATE TABLE IF NOT EXISTS task_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES tasks(id),
    ts         TEXT NOT NULL,
    level      TEXT NOT NULL,            -- info / success / warning / error
    message    TEXT NOT NULL,
    data_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);

CREATE INDEX IF NOT EXISTS idx_channels_provider ON proxy_channels(provider_id);
CREATE INDEX IF NOT EXISTS idx_channels_status ON proxy_channels(status);
CREATE INDEX IF NOT EXISTS idx_channels_task ON proxy_channels(used_by_task);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

# 青果密钥 seed（迁移自 util/proxy_qingguo.py 顶部 CONFIG；仅此一份入库，
# 之后以 providers.config_json 为准，util/ 脚本保持独立不动）
_QINGGUO_SEED = {
    "key": "C29CFA1A",
    "auth_key": "C29CFA1A",
    "auth_pwd": "9588C47B4A82",
    "channels": 5,
    "api_base": "https://longterm.proxy.qg.net",
    "area": "",
    "isp": 0,
    "test_url": "https://ipinfo.io/json",
}


def migrate() -> None:
    """创建新增 4 表及索引（幂等）。不触碰现有表。"""
    with engine.begin() as conn:
        for stmt in NEW_SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))


def seed_providers() -> bool:
    """若库中尚无青果 provider，则 seed 一条。返回是否新插入。"""
    from .models import Provider  # 延迟导入避免循环

    db = SessionLocal()
    try:
        exists = db.query(Provider).filter(Provider.kind == "qingguo").first()
        if exists:
            return False
        now = config.now_str()
        db.add(Provider(
            kind="qingguo",
            name="青果-长效动态",
            config_json=json.dumps(_QINGGUO_SEED, ensure_ascii=False),
            enabled=1,
            created_at=now,
            updated_at=now,
        ))
        db.commit()
        return True
    finally:
        db.close()


def init_db() -> None:
    migrate()
    seed_providers()
