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


@router.get("/providers")
def list_providers():
    with connect() as conn:
        providers = conn.execute(
            "SELECT * FROM providers ORDER BY id").fetchall()
        channels = conn.execute(
            "SELECT * FROM proxy_channels ORDER BY provider_id, id").fetchall()

    by_provider = {}
    for ch in channels:
        by_provider.setdefault(ch["provider_id"], []).append(dict(ch))

    result = []
    for p in providers:
        item = dict(p)
        item["config_json"] = _parse_json(item.get("config_json"))
        item["proxy_channels"] = by_provider.get(p["id"], [])
        result.append(item)
    return result
