# -*- coding: utf-8 -*-
"""费用记账 API：触发同步 + 按日期范围查询 cost_records。"""

from fastapi import APIRouter, Query

from app import costs
from app.db import connect

router = APIRouter(prefix="/costs", tags=["costs"])


@router.post("/sync")
def sync_costs():
    """同步费用记录：Apify 真实账单 + Bright Data + 渠道估算，幂等 upsert。"""
    return costs.sync_all()


@router.get("/daily")
def daily_costs(frm: str = Query(..., alias="from"),
                to: str = Query(...)):
    """按日期范围查费用记录（real=官方账单，estimate=单价折算）。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT date, provider, channel, service, source, quantity,"
            " unit, usd, synced_at FROM cost_records"
            " WHERE date >= ? AND date <= ?"
            " ORDER BY date, provider, channel, service",
            (frm, to)).fetchall()
    return {"from": frm, "to": to, "rows": [dict(r) for r in rows]}
