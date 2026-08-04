# -*- coding: utf-8 -*-
import asyncio
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.db import DB_PATH, connect
from app.runner import IN_PROCESS_TYPES, TASK_COMMANDS, beijing_now, runner

router = APIRouter()

TASK_TYPES = sorted(set(TASK_COMMANDS) | IN_PROCESS_TYPES)


def _parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _row_to_task(r):
    t = dict(r)
    t["params_json"] = _parse_json(t.get("params_json"))
    t["progress_json"] = _parse_json(t.get("progress_json"))
    return t


def _write(sql, params=()):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        cur = conn.execute(sql, params)
        conn.commit()
        return cur
    finally:
        conn.close()


@router.get("/tasks")
def list_tasks():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    return [_row_to_task(r) for r in rows]


class TaskParams(BaseModel):
    batch_num: int = 10
    max_batches: int = 0
    limit: int = 0
    use_proxy: bool = True
    headless: bool = True
    # wa_check（进程内 WhatsApp 查号）专用：
    interval: float = 2.0       # 批间间隔秒
    accounts: list[str] = []    # 账号池，空 = 仅默认账号


class TaskCreate(BaseModel):
    type: str = Field(...)
    params: TaskParams = Field(default_factory=TaskParams)


@router.post("/tasks", status_code=201)
def create_task(body: TaskCreate):
    if body.type not in TASK_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"未知任务类型 {body.type!r}，可选: {TASK_TYPES}")
    params_json = json.dumps(body.params.model_dump(), ensure_ascii=False)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        cur = conn.execute(
            "INSERT INTO tasks (type, params_json, status, created_at) "
            "VALUES (?, ?, 'pending', ?)",
            (body.type, params_json, beijing_now()),
        )
        conn.commit()
        task_id = cur.lastrowid
        row = conn.execute("SELECT * FROM tasks WHERE id=?",
                           (task_id,)).fetchone()
        return _row_to_task(row)
    finally:
        conn.close()


def _get_task_row(task_id: int):
    with connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?",
                           (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return row


@router.post("/tasks/{task_id}/start")
def start_task(task_id: int):
    row = _get_task_row(task_id)
    status = row["status"]
    if status not in ("pending", "failed", "stopped"):
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {status!r} 不可启动（仅 pending/failed/stopped）")
    if runner.is_running(task_id):
        raise HTTPException(status_code=409, detail="任务进程已在运行")
    # 同行重置状态、清空 error、写 started_at
    _write(
        "UPDATE tasks SET status='running', error=NULL, progress_json=NULL, "
        "stop_requested=0, started_at=?, finished_at=NULL WHERE id=?",
        (beijing_now(), task_id),
    )
    params = _parse_json(row["params_json"]) or {}
    try:
        pid = runner.start(task_id, row["type"], params)
    except Exception as e:
        _write(
            "UPDATE tasks SET status='failed', error=?, finished_at=? "
            "WHERE id=?",
            (f"进程启动失败: {e}"[:500], beijing_now(), task_id),
        )
        raise HTTPException(status_code=500, detail=f"进程启动失败: {e}")
    return {"ok": True, "pid": pid}


@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: int):
    row = _get_task_row(task_id)
    if row["status"] != "running":
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {row['status']!r} 不可停止（仅 running）")
    runner.stop(task_id)
    return {"ok": True}


@router.get("/tasks/{task_id}")
def get_task(task_id: int):
    return _row_to_task(_get_task_row(task_id))


# ---------------- SSE 事件流 ----------------

_REPLAY_LIMIT = 200
_POLL_SEC = 1.0
_PING_SEC = 15.0


def _fetch_events(task_id: int, last_id: int, limit: int = None):
    sql = ("SELECT id, task_id, ts, level, message, data_json "
           "FROM task_events WHERE task_id=? AND id>? ORDER BY id ASC")
    params = [task_id, last_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _fetch_status(task_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn.execute(
            "SELECT status, finished_at FROM tasks WHERE id=?",
            (task_id,)).fetchone()
    finally:
        conn.close()


def _sse_event(ev: dict) -> str:
    payload = {
        "id": ev["id"],
        "task_id": ev["task_id"],
        "ts": ev["ts"],
        "level": ev["level"],
        "message": ev["message"],
        "data": _parse_json(ev.get("data_json")),
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: int, request: Request):
    _get_task_row(task_id)

    async def stream():
        last_id = 0
        # 1) 回放最近 200 条（按 id 升序）
        replay = await asyncio.to_thread(_replay_recent, task_id)
        for ev in replay:
            yield _sse_event(ev)
            last_id = max(last_id, ev["id"])

        last_status = None
        last_ping = asyncio.get_event_loop().time()
        terminal_sent = False
        # 2) 增量轮询 + 状态推送 + 心跳
        while True:
            if await request.is_disconnected():
                break
            new_events = await asyncio.to_thread(
                _fetch_events, task_id, last_id)
            for ev in new_events:
                yield _sse_event(ev)
                last_id = ev["id"]

            row = await asyncio.to_thread(_fetch_status, task_id)
            if row:
                status, finished_at = row[0], row[1]
                if status != last_status:
                    last_status = status
                    yield ("event: status\n"
                           f"data: {json.dumps({'status': status, 'finished_at': finished_at}, ensure_ascii=False)}\n\n")
                    if status in ("done", "failed", "stopped"):
                        terminal_sent = True

            now = asyncio.get_event_loop().time()
            if now - last_ping >= _PING_SEC:
                last_ping = now
                yield ": ping\n\n"

            if terminal_sent:
                # 终态已推送且事件已补发完毕，再多轮一次后收尾
                new_events = await asyncio.to_thread(
                    _fetch_events, task_id, last_id)
                for ev in new_events:
                    yield _sse_event(ev)
                    last_id = ev["id"]
                break

            await asyncio.sleep(_POLL_SEC)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _replay_recent(task_id: int):
    """最近 200 条（按 id 升序返回）。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        rows = conn.execute(
            "SELECT id, task_id, ts, level, message, data_json "
            "FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT ?",
            (task_id, _REPLAY_LIMIT)).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()
