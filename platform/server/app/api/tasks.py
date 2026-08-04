# -*- coding: utf-8 -*-
import json

from fastapi import APIRouter

from app.db import connect

router = APIRouter()


def _parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


@router.get("/tasks")
def list_tasks():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    tasks = []
    for r in rows:
        t = dict(r)
        t["params_json"] = _parse_json(t.get("params_json"))
        t["progress_json"] = _parse_json(t.get("progress_json"))
        tasks.append(t)
    return tasks
