# -*- coding: utf-8 -*-
import asyncio
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.db import DB_PATH, connect
from app.runner import (IN_PROCESS_TYPES, PYTHON_BIN, TASK_COMMANDS,
                        beijing_now, build_command, runner)

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
    """任务参数：全部可选，None=缺省（CLI 自带默认值，不输出对应参数）。"""
    batch_num: int | None = None            # → -n
    max_batches: int | None = None          # → --max-batches
    limit: int | None = None                # → --limit
    workers: int | None = None              # → --workers
    channels: int | None = None             # → --channels
    batch_rest: float | None = None         # → --batch-rest
    sample_min: float | None = None         # → --sample-min
    sample_max: float | None = None         # → --sample-max
    rest_every: int | None = None           # → --rest-every
    rest_min: float | None = None           # → --rest-min
    rest_max: float | None = None           # → --rest-max
    stagger_min: float | None = None        # → --stagger-min
    stagger_max: float | None = None        # → --stagger-max
    ip_retry: int | None = None             # → --ip-retry
    net_retry: int | None = None            # → --net-retry
    max_consecutive_fail: int | None = None  # → --max-consecutive-fail
    block_rest_min: float | None = None     # → --block-rest-min
    block_rest_max: float | None = None     # → --block-rest-max
    # 开关
    use_proxy: bool | None = None           # true → --proxy
    headless: bool | None = None            # false → --headed
    auto_solve: bool | None = None          # false → --no-auto-solve
    retry_failed: bool | None = None        # true 且 1688_contact → --retry-failed
    # wa_check（进程内 WhatsApp 查号）专用：
    interval: float | None = None           # 批间间隔秒
    accounts: list[str] | None = None       # 账号池，空 = 仅默认账号
    # 循环模式：本轮正常结束（done/failed）后 N 秒自动重启；None/<=0 = 不循环
    repeat_interval: int | None = None


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


# ---------------- 命令预览 / 参数修改 ----------------


class CommandParse(BaseModel):
    command: str = Field(..., min_length=1)


@router.post("/tasks/parse")
def parse_task_command(body: CommandParse):
    """把 fetcher CLI 命令文本解析回 type + params（build_command 的反向）。

    容忍 python -m fetcher / 直接 fetcher 前缀与 while/for + sleep N 循环包裹。
    """
    from app.cmdparse import CommandParseError, parse_command
    try:
        return parse_command(body.command)
    except CommandParseError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/tasks/preview")
def preview_task(body: TaskCreate):
    """按 type + params 预览实际将执行的 fetcher CLI 命令（不落库）。"""
    if body.type not in TASK_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"未知任务类型 {body.type!r}，可选: {TASK_TYPES}")
    params = body.params.model_dump()
    if body.type in IN_PROCESS_TYPES:
        return {"cmd": None, "cmdline": "进程内执行（CheckWhatsApp 原子）"}
    try:
        cmd = build_command(body.type, params)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # 展示串：绝对路径 python 换成 python，保持真实可读
    cmdline = " ".join("python" if p == PYTHON_BIN else p for p in cmd)
    return {"cmd": cmd, "cmdline": cmdline}


class TaskUpdate(BaseModel):
    params: TaskParams = Field(...)


class TaskBatch(BaseModel):
    action: str = Field(...)              # start / stop / delete
    ids: list[int] = Field(..., min_length=1, max_length=200)


@router.post("/tasks/batch")
def batch_tasks(body: TaskBatch):
    """批量操作：逐个执行并汇总结果，单项失败不影响其他项。"""
    if body.action not in ("start", "stop", "delete"):
        raise HTTPException(status_code=422, detail=f"未知批量操作 {body.action!r}")
    results = []
    for tid in body.ids:
        try:
            with connect() as conn:
                row = conn.execute("SELECT * FROM tasks WHERE id=?",
                                   (tid,)).fetchone()
            if not row:
                results.append({"id": tid, "ok": False, "detail": "不存在"})
                continue
            status = row["status"]
            if body.action == "start":
                if status not in ("pending", "failed", "stopped"):
                    results.append({"id": tid, "ok": False, "detail": f"状态 {status} 不可启动"})
                    continue
                if runner.is_running(tid):
                    results.append({"id": tid, "ok": False, "detail": "进程已在运行"})
                    continue
                _write(
                    "UPDATE tasks SET status='running', error=NULL, progress_json=NULL, "
                    "stop_requested=0, started_at=?, finished_at=NULL WHERE id=?",
                    (beijing_now(), tid))
                params = _parse_json(row["params_json"]) or {}
                pid = runner.start(tid, row["type"], params)
                results.append({"id": tid, "ok": True, "detail": f"已启动 pid={pid}"})
            elif body.action == "stop":
                if status != "running":
                    results.append({"id": tid, "ok": False, "detail": f"状态 {status} 不可停止"})
                    continue
                runner.stop(tid)
                results.append({"id": tid, "ok": True, "detail": "已请求停止"})
            else:  # delete
                if status == "running" or runner.is_running(tid):
                    results.append({"id": tid, "ok": False, "detail": "运行中，需先停止"})
                    continue
                runner.cancel_timer(tid)  # 循环模式待重启 Timer 一并取消
                _write("DELETE FROM task_events WHERE task_id=?", (tid,))
                _write("DELETE FROM tasks WHERE id=?", (tid,))
                results.append({"id": tid, "ok": True, "detail": "已删除"})
        except Exception as e:
            results.append({"id": tid, "ok": False, "detail": str(e)[:200]})
    ok = sum(1 for r in results if r["ok"])
    return {
        "ok": ok,
        "failed": len(results) - ok,
        "results": results,
    }


@router.put("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate):
    """修改任务参数：仅 pending/failed/stopped 可改，否则 409。"""
    row = _get_task_row(task_id)
    status = row["status"]
    if status not in ("pending", "failed", "stopped"):
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {status!r} 不可修改参数（仅 pending/failed/stopped）")
    params_json = json.dumps(body.params.model_dump(), ensure_ascii=False)
    _write("UPDATE tasks SET params_json=? WHERE id=?",
           (params_json, task_id))
    return _row_to_task(_get_task_row(task_id))


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    """删除任务及其全部日志事件：running 不可删（先停止），否则 409。"""
    row = _get_task_row(task_id)
    status = row["status"]
    if status == "running" or runner.is_running(task_id):
        raise HTTPException(
            status_code=409,
            detail="任务运行中，请先停止再删除")
    runner.cancel_timer(task_id)  # 循环模式待重启 Timer 一并取消
    _write("DELETE FROM task_events WHERE task_id=?", (task_id,))
    _write("DELETE FROM tasks WHERE id=?", (task_id,))
    return {"ok": True}


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
    # running 可停；done/failed 但循环模式待重启（Timer 挂起）也可停
    if row["status"] != "running" and not runner.has_pending_timer(task_id):
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {row['status']!r} 不可停止（仅 running 或循环等待中）")
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
