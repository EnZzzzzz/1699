# -*- coding: utf-8 -*-
"""店铺 / 联系方式分页查询（现有 5 表走原生 SQL，只读）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

router = APIRouter(prefix="/api", tags=["data"])

SHOP_STATUSES = ("pending", "in_progress", "done", "no_contact", "failed")


def _shop_filters(status, category, keyword):
    where, params = [], {}
    if status:
        where.append("status = :status")
        params["status"] = status
    if category:
        where.append("category_keyword = :category")
        params["category"] = category
    if keyword:
        where.append("(name LIKE :kw OR domain LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    return (" WHERE " + " AND ".join(where)) if where else "", params


@router.get("/shops")
def list_shops(status: str | None = None, category: str | None = None,
               keyword: str | None = None, page: int = 1, page_size: int = 20,
               db: Session = Depends(get_db)):
    where, params = _shop_filters(status, category, keyword)
    total = db.execute(text(f"SELECT COUNT(*) FROM shops{where}"), params).scalar()
    rows = db.execute(
        text(f"SELECT * FROM shops{where}"
             " ORDER BY id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return {"items": [dict(r) for r in rows], "total": total, "page": page}


@router.get("/contacts")
def list_contacts(keyword: str | None = None, page: int = 1,
                  page_size: int = 20, db: Session = Depends(get_db)):
    where, params = "", {}
    if keyword:
        where = (" WHERE (s.name LIKE :kw OR s.domain LIKE :kw"
                 " OR c.contact_person LIKE :kw OR c.mobile LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    base = (" FROM contacts c JOIN shops s ON s.id = c.shop_id" + where)
    total = db.execute(text("SELECT COUNT(*)" + base), params).scalar()
    rows = db.execute(
        text("SELECT c.*, s.domain, s.name AS shop_name, s.category_keyword"
             + base + " ORDER BY c.id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return {"items": [dict(r) for r in rows], "total": total, "page": page}
