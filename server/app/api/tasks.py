# -*- coding: utf-8 -*-
"""任务 API：创建（校验→入库→celery send_task）、列表/详情、停止、headed 确认。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config as app_config
from ..db import get_db
from ..models import Task, TaskEvent
from ..services.board import build_board
from ..services.pool_client import set_confirmation

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

TASK_TYPES = {
    "shop_crawl": "crawl.shop_crawl",
    "contact_fetch": "crawl.contact_fetch",
}

# 各类型允许的 params 字段及类型（宽松校验：未知字段拒绝，缺省用默认）
PARAM_SPEC = {
    "shop_crawl": {
        "target": int, "category": str, "workers": int, "channels": int,
        "proxy": bool, "headed": bool, "yes": bool, "rest_every": int,
        "delay_min": (int, float), "delay_max": (int, float),
        "rest_min": (int, float), "rest_max": (int, float),
        "start_delay_min": int, "start_delay_max": int,
        "rotate_every": int,
    },
    "contact_fetch": {
        "workers": int, "channels": int, "proxy": bool, "limit": int,
        "headed": bool, "num": int, "batch_rest": (int, float),
        "max_batches": int, "ip_retry": int, "block_retry": int,
        "net_retry": int, "max_consecutive_fail": int, "rest_every": int,
        "rest_min": (int, float), "rest_max": (int, float),
        "start_delay_min": int, "start_delay_max": int,
        "rotate_every": int,
    },
}

# 前端动态表单用的完整参数定义（name 必须与 worker 实际读取的 params 键一致；
# default 与 worker _normalize_params 缺省值一致；group 供前端分组渲染）
PARAM_SPECS = {
    "shop_crawl": [
        {"name": "target", "label": "目标数量", "type": "int", "default": 0,
         "min": 0, "group": "基本",
         "help": "本任务新增店铺数，0=每 worker 采 1 轮"},
        {"name": "category", "label": "指定类目", "type": "str", "default": "",
         "group": "基本",
         "help": "类目关键词（空=全类目轮采；指定后单 worker 只采该类目）"},
        {"name": "workers", "label": "并发数", "type": "int", "default": 1,
         "min": 1, "max": 8, "group": "基本",
         "help": "采集 worker 线程数（CloakBrowser free 单席位，>1 会串行化）"},
        {"name": "channels", "label": "通道数", "type": "int", "default": 1,
         "min": 1, "max": 8, "group": "基本",
         "help": "向共享池申请的通道数（实际占用 min(channels, workers)，"
                 "超出并发数的部分会被截断）"},
        {"name": "proxy", "label": "走代理", "type": "bool", "default": True,
         "group": "基本", "help": "False=直连本机 IP"},
        {"name": "start_delay_min", "label": "启动前等待下限（秒）",
         "type": "int", "default": 0, "min": 0, "group": "基本",
         "help": "与上限配合：相等=固定等待，不等=启动时在区间内随机抽取"},
        {"name": "start_delay_max", "label": "启动前等待上限（秒）",
         "type": "int", "default": 0, "min": 0, "group": "基本",
         "help": "任务 running 后延迟再申请通道开始执行，都为 0=立即；"
                 "等待期间可停止，不占用任何资源"},
        {"name": "headed", "label": "有头模式", "type": "bool",
         "default": False, "group": "浏览器",
         "help": "弹出浏览器窗口（可用于人工过滑块/登录）"},
        {"name": "yes", "label": "跳过人工确认", "type": "bool",
         "default": True, "group": "浏览器",
         "help": "无人值守；headed+yes=False 时引导页打开后等人工确认"},
        {"name": "rest_every", "label": "每 N 轮长休", "type": "int",
         "default": 0, "min": 0, "group": "节奏控制",
         "help": "每 worker 每采 N 轮（页）后长时休息，0=关闭"},
        {"name": "rotate_every", "label": "每 N 个主动换 IP", "type": "int",
         "default": 0, "min": 0, "group": "节奏控制",
         "help": "0=不主动换；>0 时每成功处理 N 个随机更换一次出口 IP"
                 "（新 IP 可能无 Cookie 需重新验证）"},
        {"name": "delay_min", "label": "轮间延迟下限（秒）", "type": "float",
         "default": 15.0, "min": 0, "group": "节奏控制"},
        {"name": "delay_max", "label": "轮间延迟上限（秒）", "type": "float",
         "default": 45.0, "min": 0, "group": "节奏控制"},
        {"name": "rest_min", "label": "长休时长下限（秒）", "type": "float",
         "default": 300.0, "min": 0, "group": "节奏控制",
         "help": "配合「每 N 轮长休」，在上下限之间随机取休息时长"},
        {"name": "rest_max", "label": "长休时长上限（秒）", "type": "float",
         "default": 600.0, "min": 0, "group": "节奏控制"},
    ],
    "contact_fetch": [
        {"name": "limit", "label": "本次限抓数量", "type": "int",
         "default": 0, "min": 0, "group": "基本",
         "help": "本次最多抓取多少家店铺，0=抓完全部 pending"},
        {"name": "workers", "label": "并发数", "type": "int", "default": 1,
         "min": 1, "max": 8, "group": "基本",
         "help": "抓取 worker 线程数（CloakBrowser free 单席位，>1 会串行化）"},
        {"name": "channels", "label": "通道数", "type": "int", "default": 1,
         "min": 1, "max": 8, "group": "基本",
         "help": "向共享池申请的通道数（实际占用 min(channels, workers)，"
                 "超出并发数的部分会被截断）"},
        {"name": "proxy", "label": "走代理", "type": "bool", "default": True,
         "group": "基本", "help": "False=直连本机 IP"},
        {"name": "start_delay_min", "label": "启动前等待下限（秒）",
         "type": "int", "default": 0, "min": 0, "group": "基本",
         "help": "与上限配合：相等=固定等待，不等=启动时在区间内随机抽取"},
        {"name": "start_delay_max", "label": "启动前等待上限（秒）",
         "type": "int", "default": 0, "min": 0, "group": "基本",
         "help": "任务 running 后延迟再申请通道开始执行，都为 0=立即；"
                 "等待期间可停止，不占用任何资源"},
        {"name": "headed", "label": "有头模式", "type": "bool",
         "default": False, "group": "浏览器",
         "help": "弹出浏览器窗口（可用于人工过滑块/登录）"},
        {"name": "num", "label": "每批数量", "type": "int", "default": 10,
         "min": 1, "group": "节奏控制",
         "help": "每批抓取多少家后强制批间休息"},
        {"name": "batch_rest", "label": "批间休息（秒）", "type": "float",
         "default": 900.0, "min": 0, "group": "节奏控制",
         "help": "每批采满「每批数量」后强制休息（实际在 0.9~1.1 倍间随机）"},
        {"name": "max_batches", "label": "最多批数", "type": "int",
         "default": 0, "min": 0, "group": "节奏控制",
         "help": "0=不限批数"},
        {"name": "rest_every", "label": "每 N 个长休", "type": "int",
         "default": 20, "min": 0, "group": "节奏控制",
         "help": "每抓 N 个店铺（含失败/无联系方式）后长时休息，0=关闭"},
        {"name": "rotate_every", "label": "每 N 个主动换 IP", "type": "int",
         "default": 0, "min": 0, "group": "节奏控制",
         "help": "0=不主动换；>0 时每成功处理 N 个随机更换一次出口 IP"
                 "（新 IP 可能无 Cookie 需重新验证）"},
        {"name": "rest_min", "label": "长休时长下限（秒）", "type": "float",
         "default": 60.0, "min": 0, "group": "节奏控制",
         "help": "配合「每 N 个长休」，在上下限之间随机取休息时长"},
        {"name": "rest_max", "label": "长休时长上限（秒）", "type": "float",
         "default": 180.0, "min": 0, "group": "节奏控制"},
        {"name": "ip_retry", "label": "换 IP 重试次数", "type": "int",
         "default": 3, "min": 0, "group": "重试策略",
         "help": "出口 IP 失效/浏览器重启的最大重试次数"},
        {"name": "block_retry", "label": "风控换通道重试次数", "type": "int",
         "default": 2, "min": 0, "group": "重试策略",
         "help": "单店铺疑似风控后换通道重试次数，超限标记 failed"},
        {"name": "net_retry", "label": "网络故障重试次数", "type": "int",
         "default": 5, "min": 0, "group": "重试策略",
         "help": "单店铺网络/代理故障重试次数，超限标记 failed"},
        {"name": "max_consecutive_fail", "label": "连续失败中止阈值",
         "type": "int", "default": 5, "min": 1, "group": "重试策略",
         "help": "连续 N 次疑似风控即判定被风控，中止整个任务"},
    ],
}

ACTIVE_STATUSES = ("pending", "waiting_channel", "running", "stopping")


class TaskCreate(BaseModel):
    type: str
    params: dict = {}


def _validate_params(task_type: str, params: dict) -> dict:
    spec = PARAM_SPEC[task_type]
    out = {}
    for k, v in (params or {}).items():
        if k not in spec:
            raise HTTPException(
                status_code=400,
                detail=f"任务类型 {task_type} 不支持参数 {k!r}，允许: {sorted(spec)}")
        types = spec[k]
        # bool 是 int 子类，显式区分
        if types is int and (isinstance(v, bool) or not isinstance(v, int)):
            raise HTTPException(status_code=400, detail=f"参数 {k} 必须是整数")
        if types is str and not isinstance(v, str):
            raise HTTPException(status_code=400, detail=f"参数 {k} 必须是字符串")
        if types is bool and not isinstance(v, bool):
            raise HTTPException(status_code=400, detail=f"参数 {k} 必须是布尔值")
        if isinstance(types, tuple) and not isinstance(v, types):
            raise HTTPException(status_code=400, detail=f"参数 {k} 必须是数值")
        out[k] = v
    return out


@router.post("", status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    if body.type not in TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"未知任务类型 {body.type!r}，支持: {sorted(TASK_TYPES)}")
    params = _validate_params(body.type, body.params)
    task = Task(type=body.type,
                params_json=json.dumps(params, ensure_ascii=False),
                status="pending",
                progress_json=json.dumps(
                    {"collected": 0, "pending": 0, "per_minute": 0},
                    ensure_ascii=False),
                created_at=app_config.now_str())
    db.add(task)
    db.commit()
    db.refresh(task)

    dispatched = True
    dispatch_error = None
    try:
        from ..workers.celery_app import celery_app
        celery_app.send_task(TASK_TYPES[body.type], args=[task.id])
    except Exception as e:  # noqa: BLE001 - broker 不可用时任务留 pending
        dispatched = False
        dispatch_error = str(e)
        task.error = f"celery 派发失败（任务保留 pending，可重启 worker 后重派）: {e}"
        db.commit()

    result = task.to_dict()
    result["dispatched"] = dispatched
    if dispatch_error:
        result["dispatch_error"] = dispatch_error

    # worker 离线预警：消息会滞留 broker 队列无人消费（曾发生过的故障）
    if dispatched:
        try:
            from .workers import inspect_workers
            if not inspect_workers(timeout=0.8)["online"]:
                result["warning"] = (
                    "当前没有在线的 celery worker，任务会滞留在队列中无人执行；"
                    "请先在项目根目录执行 ./start.sh 启动 worker")
        except Exception:  # noqa: BLE001 - 探测失败不影响创建
            pass
    return result


@router.get("")
def list_tasks(status: str | None = None, page: int = 1, page_size: int = 20,
               db: Session = Depends(get_db)):
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    total = q.count()
    rows = (q.order_by(Task.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"items": [t.to_dict() for t in rows], "total": total, "page": page}


@router.get("/param-specs")
def get_param_specs():
    """任务参数规格：按任务类型返回完整参数定义，供前端动态渲染表单。"""
    return PARAM_SPECS


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = t.to_dict()
    result["board"] = build_board(db, t)  # 每次请求现算的实时看板
    return result


@router.get("/{task_id}/events")
def get_task_events(task_id: int, after_id: int = 0, limit: int = 200,
                    db: Session = Depends(get_db)):
    """任务实时事件流（增量拉取）：after_id 之后的事件，按 id 升序。

    返回 {items: [{id, ts, level, message, data}], latest_id}；
    每任务保留最近 500 条，超出部分由写入侧自动清理。
    """
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    limit = max(1, min(limit, 500))
    rows = (db.query(TaskEvent)
            .filter(TaskEvent.task_id == task_id, TaskEvent.id > after_id)
            .order_by(TaskEvent.id).limit(limit).all())
    latest_id = (db.query(TaskEvent)
                 .filter(TaskEvent.task_id == task_id)
                 .order_by(TaskEvent.id.desc()).first())
    return {
        "items": [e.to_dict() for e in rows],
        "latest_id": latest_id.id if latest_id else 0,
    }


@router.post("/{task_id}/stop")
def stop_task(task_id: int, db: Session = Depends(get_db)):
    """协作式停止：置 stop_requested；pending 任务 revoke 兜底直接标 stopped。"""
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if t.status in ("done", "failed", "stopped"):
        return t.to_dict()

    t.stop_requested = 1
    if t.status in ("running", "waiting_channel"):
        t.status = "stopping"
        db.commit()
        return t.to_dict()

    # pending：还没被 worker 领取，revoke 兜底 + 直接终态
    if t.celery_id:
        try:
            from ..workers.celery_app import celery_app
            celery_app.control.revoke(t.celery_id)
        except Exception:
            pass
    t.status = "stopped"
    t.finished_at = app_config.now_str()
    db.commit()
    return t.to_dict()


@router.post("/{task_id}/confirm")
def confirm_task(task_id: int, db: Session = Depends(get_db)):
    """headed 模式人工确认（引导浏览器打开类目页后由前端触发）。"""
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    ok = set_confirmation(task_id)
    if not ok:
        raise HTTPException(status_code=503,
                            detail="Redis 不可用，无法传递确认标记")
    return {"confirmed": True, "task_id": task_id}
