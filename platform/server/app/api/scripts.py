# -*- coding: utf-8 -*-
"""采集脚本管理 API。

路由前缀 /scripts（由 app.api 挂载在 /api 下）：
- GET  /scripts                 三脚本汇总：运行状态、pid、启动时间、当前参数、额度/产量
- POST /scripts/{name}/start    启动（body 可带 params 先落配置）
- POST /scripts/{name}/stop     停止（SIGTERM → SIGKILL 兜底）
- POST /scripts/{name}/restart  重启（先停后启，body 可带 params 先落配置）
- POST /scripts/{name}/params   保存参数（仅落库，不隐式重启）
- GET  /scripts/{name}/logs     日志增量 tail（offset 续传）
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import scripts

router = APIRouter(prefix="/scripts")


class ScriptParamsBody(BaseModel):
    params: dict = Field(default_factory=dict)


class ScriptStartBody(BaseModel):
    params: Optional[dict] = None


def _spec_or_404(name: str) -> None:
    if name not in scripts.SPECS:
        raise HTTPException(
            status_code=404,
            detail=f"未知脚本 {name!r}（支持: {sorted(scripts.SPECS)}）")


@router.get("")
def list_scripts():
    """三脚本汇总卡片数据。seed 默认配置（幂等）后逐个拼状态。"""
    scripts.ensure_configs()
    result = []
    for name, spec in scripts.SPECS.items():
        st = scripts.status(name)
        result.append({
            "name": name,
            "title": spec["title"],
            "log_file": spec["log"],
            "running": st["running"],
            "pid": st["pid"],
            "started_at": st["started_at"],
            "uptime": st["uptime"],
            "params": scripts.get_params(name),
            "stats": scripts.stats(name),
        })
    return result


@router.post("/{name}/start")
def start_script(name: str, body: ScriptStartBody = None):
    _spec_or_404(name)
    try:
        if body and body.params:
            scripts.save_params(name, body.params)
        return scripts.start(name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{name}/stop")
def stop_script(name: str):
    _spec_or_404(name)
    return scripts.stop(name)


@router.post("/{name}/restart")
def restart_script(name: str, body: ScriptStartBody = None):
    _spec_or_404(name)
    try:
        if body and body.params:
            scripts.save_params(name, body.params)
        return scripts.restart(name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{name}/params")
def save_script_params(name: str, body: ScriptParamsBody):
    _spec_or_404(name)
    try:
        params = scripts.save_params(name, body.params)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"name": name, "params": params}


@router.get("/{name}/logs")
def script_logs(name: str, offset: int = 0):
    _spec_or_404(name)
    return scripts.tail_log(name, offset)
