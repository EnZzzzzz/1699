# -*- coding: utf-8 -*-
"""
任务详情实时看板（GET /api/tasks/{id} 的 board 对象）。

每次请求现算（轻量 COUNT 查询 + 一次 usage 窗口聚合），不依赖
progress_json 的周期快照；现有 5 表走原生 SQL 只读。

collected 口径：
    - shop_crawl：本任务启动后新增店铺数（shops.first_seen_at >= started_at）
    - contact_fetch：task_done + task_failed + task_no_contact（本任务已处理
      总数）。task_no_contact/task_failed 以 shops.last_seen_at >= started_at
      近似归属本任务（last_seen_at 也会被店铺再发现刷新，多任务并发时口径
      为近似值；单任务场景准确）。started_at 为 null 时回退 progress.collected。
"""
from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Task
from . import usage as usage_service

SHOP_CRAWL = "shop_crawl"
CONTACT_FETCH = "contact_fetch"


def _parse_ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return None


def build_board(db: Session, task: Task) -> dict:
    d = task.to_dict()
    params = d["params"]
    progress = d["progress"] or {}
    started_epoch = _parse_ts(task.started_at)

    # ---- 公共部分 ----
    per_minute = float(progress.get("per_minute") or 0)
    elapsed = (int(time.time() - started_epoch)
               if started_epoch is not None else None)

    channels = _task_channels(db, task.id)

    board: dict = {
        "type": task.type,
        "phase": progress.get("phase"),
        "collected": 0,   # 下面按类型填
        "total": None,
        "remaining": None,
        "per_minute": per_minute,
        "elapsed_seconds": elapsed,
        "eta_seconds": None,
        "channels": channels,
    }

    if task.type == SHOP_CRAWL:
        _fill_shop_crawl(db, task, d, params, progress, board)
    elif task.type == CONTACT_FETCH:
        _fill_contact_fetch(db, task, d, params, progress, board)
    else:
        board["collected"] = int(progress.get("collected") or 0)

    total = board["total"]
    if total is not None:
        board["remaining"] = max(0, total - board["collected"])
        if per_minute > 0:
            board["eta_seconds"] = int(board["remaining"] / per_minute * 60)
    return board


def _task_channels(db: Session, task_id: int) -> list[dict]:
    """本任务当前占用的通道（含近5分钟请求数）。"""
    from ..models import Provider, ProxyChannel

    counts = usage_service.channel_counts(5)
    providers = {p.id: p for p in db.query(Provider).all()}
    rows = (db.query(ProxyChannel)
            .filter(ProxyChannel.used_by_task == task_id)
            .order_by(ProxyChannel.id).all())
    out = []
    for ch in rows:
        p = providers.get(ch.provider_id) if ch.provider_id else None
        out.append({
            "id": ch.id,
            "tunnel": ch.tunnel,
            "exit_ip": ch.exit_ip,
            "provider_name": p.name if p else "本机 IP",
            "status": ch.status,
            "requests_5m": counts.get(ch.id, 0),
        })
    return out


def _fill_shop_crawl(db: Session, task: Task, d: dict, params: dict,
                     progress: dict, board: dict) -> None:
    q = lambda sql, **kw: db.execute(text(sql), kw).scalar()  # noqa: E731
    if task.started_at:
        collected = q("SELECT COUNT(*) FROM shops WHERE first_seen_at >= :s",
                      s=task.started_at)
    else:
        collected = int(progress.get("collected") or 0)

    categories = db.execute(
        text("SELECT keyword, next_page, exhausted FROM category_progress"
             " ORDER BY next_page DESC LIMIT 10")).mappings().all()

    board.update({
        "collected": collected,
        "total": int(params.get("target") or 0),
        "target": int(params.get("target") or 0),
        "pending_contacts": q("SELECT COUNT(*) FROM shops WHERE status='pending'"),
        "categories": [
            {"keyword": r["keyword"], "next_page": r["next_page"],
             "exhausted": bool(r["exhausted"])}
            for r in categories
        ],
    })


def _fill_contact_fetch(db: Session, task: Task, d: dict, params: dict,
                        progress: dict, board: dict) -> None:
    q = lambda sql, **kw: db.execute(text(sql), kw).scalar()  # noqa: E731

    status_counts = {"pending": 0, "in_progress": 0, "done": 0,
                     "no_contact": 0, "failed": 0, "blocked": 0}
    for status, cnt in db.execute(
            text("SELECT status, COUNT(*) FROM shops GROUP BY status")).all():
        if status in status_counts:
            status_counts[status] = cnt
    # shops 表无 blocked 状态（被风控的店铺保持 in_progress/pending），恒为 0

    if task.started_at:
        s = task.started_at
        task_done = q("SELECT COUNT(*) FROM contacts WHERE scraped_at >= :s", s=s)
        # last_seen_at 近似归属（单任务场景准确；多任务并发为近似口径）
        task_failed = q("SELECT COUNT(*) FROM shops WHERE status='failed'"
                        " AND last_seen_at >= :s", s=s)
        task_no_contact = q("SELECT COUNT(*) FROM shops WHERE status='no_contact'"
                            " AND last_seen_at >= :s", s=s)
        collected = task_done + task_failed + task_no_contact
    else:
        task_done = task_failed = 0
        collected = int(progress.get("collected") or 0)

    limit = int(params.get("limit") or 0)
    board.update({
        "collected": collected,
        "total": limit or None,
        "status_counts": status_counts,
        "task_done": task_done,
        "task_failed": task_failed,
    })
