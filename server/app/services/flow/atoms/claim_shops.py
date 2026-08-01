# -*- coding: utf-8 -*-
"""
claim_shops 原子：认领店铺。

包装 ShopDB.claim_pending_shops（server/app/services/crawl/shopdb.py L76-92：
BEGIN IMMEDIATE 内 SELECT+UPDATE 的原子认领，语义不变）。认领结果写入
ctx.vars["shops"] 供下游节点（如 fetch_contact）消费；sqlite3.Row 转 dict
便于节点间传递与 JSON 序列化（键/值不变）。
"""
from __future__ import annotations

from ..base import Atom, AtomResult, Context, OUTCOME_EMPTY, OUTCOME_OK
from ..registry import register


@register
class ClaimShopsAtom(Atom):
    name = "claim_shops"
    title = "认领店铺"
    inputs = {"db": "ShopDB"}
    outputs = {"vars.shops": "list[dict]"}
    param_spec = {
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": "本次认领的 pending 店铺数（状态置为 in_progress）",
            },
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        n = max(1, int((params or {}).get("n") or 1))
        db = ctx.resources["db"]
        rows = db.claim_pending_shops(n)
        shops = [dict(r) for r in rows]
        ctx.vars["shops"] = shops
        if not shops:
            # 对齐 contact_fetch.py L187-189：没有待抓取店铺
            ctx.emit("info", "没有待抓取的店铺了")
            return AtomResult(outcome=OUTCOME_EMPTY,
                              detail="没有待认领的 pending 店铺")
        ctx.emit("info", f"已认领 {len(shops)} 个店铺",
                 {"domains": [s.get("domain") for s in shops]})
        return AtomResult(outcome=OUTCOME_OK,
                          detail=f"认领 {len(shops)} 个店铺",
                          data={"count": len(shops)})
