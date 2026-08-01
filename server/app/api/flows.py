# -*- coding: utf-8 -*-
"""流水线模板 API（docs/flow-architecture.md §7）。

模板 CRUD / 复制 / 删除保护 + 独立 DAG 校验 + 原子目录。
builtin=1 的内置模板只读：PUT/DELETE 拒绝，经 duplicate 派生副本后修改。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config as app_config
from ..db import get_db
from ..models import Flow, Task
from ..services.flow import registry
from ..services.flow.dag import validate_dag

router = APIRouter(tags=["flows"])


class FlowCreate(BaseModel):
    name: str
    description: str | None = None
    dag: dict


class FlowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    dag: dict | None = None


class DagValidateIn(BaseModel):
    dag: dict


def _get_flow(db: Session, flow_id: int) -> Flow:
    f = db.get(Flow, flow_id)
    if f is None:
        raise HTTPException(status_code=404, detail="流水线模板不存在")
    return f


# 注意路由顺序：/api/flows/validate 必须先于 /api/flows/{flow_id} 注册，
# 否则 "validate" 会被当 flow_id 解析。
@router.post("/api/flows/validate")
def validate_flow_dag(body: DagValidateIn):
    """独立 DAG 校验（保存前调用）：返回 {ok, errors, warnings}。"""
    errors, warnings = validate_dag(body.dag)
    return {"ok": not errors, "errors": errors, "warnings": warnings}


@router.get("/api/atoms")
def list_atoms():
    """原子目录（name/title/inputs/outputs/param_spec），前端表单/编辑器用。"""
    return registry.catalog()


@router.get("/api/flows")
def list_flows(db: Session = Depends(get_db)):
    """模板列表（不含 dag 大字段）。"""
    rows = db.query(Flow).order_by(Flow.id).all()
    return [f.to_dict(include_dag=False) for f in rows]


@router.post("/api/flows", status_code=201)
def create_flow(body: FlowCreate, db: Session = Depends(get_db)):
    """新建模板：先校验 DAG，errors 非空 400（带 errors+warnings）。"""
    errors, warnings = validate_dag(body.dag)
    if errors:
        raise HTTPException(status_code=400,
                            detail={"errors": errors, "warnings": warnings})
    now = app_config.now_str()
    f = Flow(name=body.name, description=body.description,
             dag_json=json.dumps(body.dag, ensure_ascii=False),
             builtin=0, created_at=now, updated_at=now)
    db.add(f)
    db.commit()
    db.refresh(f)
    result = f.to_dict()
    result["warnings"] = warnings
    return result


@router.get("/api/flows/{flow_id}")
def get_flow(flow_id: int, db: Session = Depends(get_db)):
    """模板详情（含 dag）。"""
    return _get_flow(db, flow_id).to_dict()


@router.put("/api/flows/{flow_id}")
def update_flow(flow_id: int, body: FlowUpdate, db: Session = Depends(get_db)):
    """更新模板：builtin=1 拒绝；dag 变更需重新校验。"""
    f = _get_flow(db, flow_id)
    if f.builtin:
        raise HTTPException(status_code=400,
                            detail="内置模板为只读，请用「复制」生成副本后修改")
    warnings: list[str] = []
    if body.dag is not None:
        errors, warnings = validate_dag(body.dag)
        if errors:
            raise HTTPException(status_code=400,
                                detail={"errors": errors, "warnings": warnings})
        f.dag_json = json.dumps(body.dag, ensure_ascii=False)
    if body.name is not None:
        f.name = body.name
    if body.description is not None:
        f.description = body.description
    f.updated_at = app_config.now_str()
    db.commit()
    result = f.to_dict()
    result["warnings"] = warnings
    return result


@router.post("/api/flows/{flow_id}/duplicate", status_code=201)
def duplicate_flow(flow_id: int, db: Session = Depends(get_db)):
    """复制出新版本：name 加「（副本）」，builtin=0。"""
    f = _get_flow(db, flow_id)
    now = app_config.now_str()
    dup = Flow(name=f.name + "（副本）", description=f.description,
               dag_json=f.dag_json, builtin=0, created_at=now, updated_at=now)
    db.add(dup)
    db.commit()
    db.refresh(dup)
    return dup.to_dict()


@router.delete("/api/flows/{flow_id}")
def delete_flow(flow_id: int, db: Session = Depends(get_db)):
    """删除模板：builtin=1 拒绝；被任务引用时 409 保留（历史任务可追溯）。"""
    f = _get_flow(db, flow_id)
    if f.builtin:
        raise HTTPException(status_code=400, detail="内置模板不可删除")
    refs = db.query(Task).filter(Task.flow_id == flow_id).count()
    if refs:
        raise HTTPException(
            status_code=409,
            detail=f"该模板被 {refs} 个任务引用，为保证历史任务可追溯不能删除")
    db.delete(f)
    db.commit()
    return {"deleted": flow_id}
