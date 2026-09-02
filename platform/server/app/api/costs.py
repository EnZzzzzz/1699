# -*- coding: utf-8 -*-
"""费用记账 API：触发同步 + 按日期范围查询 cost_records。"""

from typing import Optional

from fastapi import APIRouter, Query

from app import costs
from app.db import connect

router = APIRouter(prefix="/costs", tags=["costs"])


@router.post("/sync")
def sync_costs(provider: Optional[str] = None, account: Optional[str] = None):
    """同步费用记录：Apify 真实账单 + Bright Data + 渠道估算，幂等 upsert。

    不带参数 = 全量同步；provider=brightdata / apify / numberchecker 时只同步
    对应供应商（apify/numberchecker 可用 account=<provider 名> 进一步限定
    单账号），供供应商卡片单独刷新余额/用量。
    """
    costs.migrate()
    if provider == "brightdata":
        return {"synced_at": costs._bj_now(),
                "brightdata": costs.sync_brightdata()}
    if provider == "apify":
        return {"synced_at": costs._bj_now(),
                "apify": costs.sync_apify(account)}
    if provider == "numberchecker":
        return {"synced_at": costs._bj_now(),
                "numberchecker": costs.sync_numberchecker(account)}
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
