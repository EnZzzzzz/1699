# -*- coding: utf-8 -*-
"""任务模板 API：保存常用 type + params 组合，便于快速建任务。"""

import json
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import DB_PATH, connect
from app.runner import beijing_now

router = APIRouter()


def _row_to_template(r):
    t = dict(r)
    try:
        t["params"] = json.loads(t.pop("params_json") or "{}")
    except (ValueError, TypeError):
        t["params"] = {}
    return t


@router.get("/task-templates")
def list_templates():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_templates ORDER BY id DESC").fetchall()
    return [_row_to_template(r) for r in rows]


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    params: dict = Field(default_factory=dict)


@router.post("/task-templates", status_code=201)
def create_template(body: TemplateCreate):
    ts = beijing_now()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        cur = conn.execute(
            "INSERT INTO task_templates "
            "(name, type, params_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (body.name, body.type,
             json.dumps(body.params, ensure_ascii=False), ts, ts),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM task_templates WHERE id=?",
                           (cur.lastrowid,)).fetchone()
        return _row_to_template(row)
    finally:
        conn.close()


@router.delete("/task-templates/{template_id}")
def delete_template(template_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        cur = conn.execute("DELETE FROM task_templates WHERE id=?",
                           (template_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404,
                                detail=f"模板 {template_id} 不存在")
        return {"ok": True}
    finally:
        conn.close()
