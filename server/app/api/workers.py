# -*- coding: utf-8 -*-
"""Worker / 队列看板 API。

- GET /api/workers         基于 Celery inspect 探测在线 worker、并发、运行中任务。
- GET /api/workers/queue   读取 broker（Redis celery list）中滞留的待发消息。
- DELETE /api/workers/queue/{celery_id}  从队列中清除指定消息（LREM 精确匹配）；
  对应平台任务仍在 pending 时一并标记 stopped，避免永远挂起。

任务创建接口复用 inspect_workers() 做离线告警：worker 全部离线时任务会
滞留在 broker 队列中无人消费（曾经出现过的故障场景），创建时即提示。
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config as app_config
from ..db import get_db
from ..models import Task

router = APIRouter(prefix="/api/workers", tags=["workers"])

# inspect 走 broker 广播：celery 无法预知 worker 数量，会等满 timeout 收回复。
# 因此 ① timeout 直接决定延迟，取 0.6s 兼顾 worker 忙碌时的回复窗口；
# ② 明细命令并行发出，总耗时 ≈ 单次而非 4 倍；
# ③ 结果带 3s TTL 缓存，前端 3s 轮询时大部分时间直接命中缓存。
INSPECT_TIMEOUT = 0.6
_CACHE_TTL = 3.0
_cache: dict = {"ts": 0.0, "data": None}
_cache_lock = threading.Lock()


def _parse_task_id(args) -> int | None:
    """active 任务的 args 可能是 list（[17]）或 str（'(17,)'），提取平台任务 id。"""
    if isinstance(args, (list, tuple)) and args:
        first = args[0]
        if isinstance(first, bool):
            return None
        if isinstance(first, (int, float)):
            return int(first)
        args = str(first)
    if not isinstance(args, str) or not args:
        return None
    m = re.search(r"\d+", args)
    return int(m.group()) if m else None


def inspect_workers(timeout: float = INSPECT_TIMEOUT,
                    use_cache: bool = True) -> dict:
    """返回 {online, count, workers, error?, checked_at}，任何失败不抛异常。

    默认走 3s TTL 缓存；worker 真实启停被感知的最大延迟即 TTL 时长。
    """
    if use_cache and _cache["data"] is not None \
            and time.time() - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]
    with _cache_lock:
        if use_cache and _cache["data"] is not None \
                and time.time() - _cache["ts"] < _CACHE_TTL:
            return _cache["data"]
        data = _inspect_workers_uncached(timeout)
        _cache["ts"] = time.time()
        _cache["data"] = data
        return data


def _inspect_workers_uncached(timeout: float) -> dict:
    from ..workers.celery_app import celery_app

    checked_at = app_config.now_str()
    try:
        insp = celery_app.control.inspect(timeout=timeout)
    except Exception as e:  # noqa: BLE001 - broker 挂掉时看板仍可展示离线态
        return {"online": False, "count": 0, "workers": [],
                "error": f"broker 不可达: {e}", "checked_at": checked_at}

    # 并行发出全部广播（串行每个都要等满 timeout，总耗时 x4）
    details: dict = {}

    def _run(key, fn):
        try:
            details[key] = fn() or {}
        except Exception:  # noqa: BLE001 - 单个命令失败不拖垮整体
            details[key] = {}

    threads = [threading.Thread(target=_run, args=(k, f), daemon=True)
               for k, f in (("ping", insp.ping),
                            ("stats", insp.stats),
                            ("active", insp.active),
                            ("registered", insp.registered))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout + 2.0)

    ping = details.get("ping") or {}
    if not ping:
        return {"online": False, "count": 0, "workers": [],
                "checked_at": checked_at}

    stats = details.get("stats") or {}
    active = details.get("active") or {}
    registered = details.get("registered") or {}

    workers = []
    for host in sorted(ping):
        st = stats.get(host) or {}
        pool = st.get("pool") or {}
        act = active.get(host) or []
        workers.append({
            "hostname": host,
            "status": "online",
            "pid": st.get("pid"),
            "uptime_seconds": st.get("uptime"),
            "concurrency": pool.get("max-concurrency"),
            "pool_impl": pool.get("implementation"),
            "registered": sorted(registered.get(host) or []),
            "active": [
                {
                    "celery_id": t.get("id"),
                    "name": t.get("name"),
                    "task_id": _parse_task_id(t.get("args")),
                    "time_start": t.get("time_start"),
                }
                for t in act
            ],
        })
    return {"online": True, "count": len(workers), "workers": workers,
            "checked_at": checked_at}


@router.get("")
def list_workers():
    """在线 worker 列表：主机名、并发、已注册任务、正在执行的任务。"""
    return inspect_workers()


# ---------- broker 队列（Redis celery list） ----------

QUEUE_KEY = "celery"
TERMINAL_STATUSES = ("done", "failed", "stopped")


def _redis_client():
    import redis  # celery 的 broker 依赖，必已安装
    return redis.Redis.from_url(app_config.REDIS_URL, decode_responses=True)


def _parse_queue_message(raw: str) -> dict:
    """解析 kombu 消息信封：headers 里有 task/id/argsrepr，body 是 base64 的
    [[args], kwargs, embed]，args[0] 即平台任务 id。"""
    env = json.loads(raw)
    headers = env.get("headers") or {}
    args = None
    body = env.get("body")
    if body:
        try:
            decoded = json.loads(base64.b64decode(body).decode("utf-8"))
            args = decoded[0] if decoded else None
        except Exception:  # noqa: BLE001 - 无法解码时退化为 headers 信息
            args = None
    return {
        "celery_id": headers.get("id"),
        "name": headers.get("task"),
        "task_id": _parse_task_id(args) if args is not None else None,
        "argsrepr": headers.get("argsrepr"),
        "eta": headers.get("eta"),
        "retries": headers.get("retries") or 0,
    }


def _attach_db_status(msgs: list[dict], db: Session) -> None:
    """回填对应平台任务状态；stale = 任务已终态或不存在（建议清除）。"""
    ids = [m["task_id"] for m in msgs if m.get("task_id") is not None]
    status_map: dict[int, str] = {}
    if ids:
        for t in db.query(Task).filter(Task.id.in_(ids)):
            status_map[t.id] = t.status
    for m in msgs:
        tid = m.get("task_id")
        m["db_status"] = status_map.get(tid) if tid is not None else None
        m["stale"] = tid is not None and (
            m["db_status"] is None or m["db_status"] in TERMINAL_STATUSES)


@router.get("/queue")
def list_queue(db: Session = Depends(get_db)):
    """队列中滞留的消息（第 1 条 = 下一个被消费；kombu LPUSH 入队、BRPOP 消费）。"""
    checked_at = app_config.now_str()
    try:
        raws = _redis_client().lrange(QUEUE_KEY, 0, -1)
    except Exception as e:  # noqa: BLE001 - Redis 挂掉时看板展示不可用态
        return {"available": False, "error": f"Redis 不可达: {e}",
                "count": 0, "messages": [], "checked_at": checked_at}
    msgs = []
    for raw in raws:
        try:
            msgs.append(_parse_queue_message(raw))
        except Exception:  # noqa: BLE001 - 单条损坏不影响整体展示
            msgs.append({"celery_id": None, "name": None, "task_id": None,
                         "argsrepr": None, "eta": None, "retries": 0,
                         "unparseable": True})
    msgs.reverse()  # lrange 从左（最新）开始；展示时第 1 条 = 下一个被消费
    _attach_db_status(msgs, db)
    return {"available": True, "count": len(msgs), "messages": msgs,
            "checked_at": checked_at}


@router.delete("/queue/{celery_id}")
def delete_queued(celery_id: str, db: Session = Depends(get_db)):
    """按 celery_id 精确匹配并 LREM 一条队列消息（不依赖下标，避免位移误删）。

    对应平台任务仍在 pending 的，一并标记 stopped —— 消息没了它永远等不到执行。
    """
    try:
        r = _redis_client()
        raws = r.lrange(QUEUE_KEY, 0, -1)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Redis 不可达: {e}") from e

    target_raw, target = None, None
    for raw in raws:
        try:
            msg = _parse_queue_message(raw)
        except Exception:  # noqa: BLE001
            continue
        if msg.get("celery_id") == celery_id:
            target_raw, target = raw, msg
            break
    if target_raw is None:
        raise HTTPException(status_code=404,
                            detail="队列中不存在该消息（可能已被 worker 消费）")

    removed = r.lrem(QUEUE_KEY, 1, target_raw)

    task_marked = False
    tid = (target or {}).get("task_id")
    if tid is not None:
        t = db.get(Task, tid)
        if t is not None and t.status == "pending":
            t.status = "stopped"
            t.stop_requested = 1
            t.finished_at = app_config.now_str()
            t.error = "队列消息已被手动清除"
            db.commit()
            task_marked = True
    return {"removed": removed, "celery_id": celery_id, "task_id": tid,
            "task_marked_stopped": task_marked}
