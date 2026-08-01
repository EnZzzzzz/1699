# -*- coding: utf-8 -*-
"""Excel/CSV 导出（openpyxl），筛选条件与分页查询一致，Content-Disposition 触发下载。"""
from __future__ import annotations

import csv
import io
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from .shops import _shop_filters

router = APIRouter(prefix="/api/export", tags=["export"])

SHOP_COLUMNS = ["id", "domain", "name", "url", "category_keyword", "status",
                "attempts", "first_seen_at", "last_seen_at"]
CONTACT_COLUMNS = ["id", "domain", "shop_name", "category_keyword",
                   "contact_person", "gender", "phone", "mobile", "fax",
                   "address", "source_url", "scraped_at"]


def _contact_rows(db: Session, keyword):
    where, params = "", {}
    if keyword:
        where = (" WHERE (s.name LIKE :kw OR s.domain LIKE :kw"
                 " OR c.contact_person LIKE :kw OR c.mobile LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    return db.execute(
        text("SELECT c.*, s.domain, s.name AS shop_name, s.category_keyword"
             " FROM contacts c JOIN shops s ON s.id = c.shop_id"
             + where + " ORDER BY c.id"),
        params).mappings().all()


def _shop_rows(db: Session, status, category, keyword):
    where, params = _shop_filters(status, category, keyword)
    return db.execute(text(f"SELECT * FROM shops{where} ORDER BY id"),
                      params).mappings().all()


def _xlsx_response(columns: list[str], rows, filename: str, sheet: str):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(columns)
    for r in rows:
        ws.append([r.get(c) for c in columns])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"})


def _csv_response(columns: list[str], rows, filename: str):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for r in rows:
        w.writerow([r.get(c) for c in columns])
    data = io.BytesIO("\ufeff".encode("utf-8") + buf.getvalue().encode("utf-8"))
    return StreamingResponse(
        data, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"})


def _fname(kind: str, ext: str) -> str:
    return f"1688_{kind}_{time.strftime('%Y%m%d_%H%M%S')}.{ext}"


@router.get("/shops.xlsx")
def export_shops_xlsx(status: str | None = None, category: str | None = None,
                      keyword: str | None = None, db: Session = Depends(get_db)):
    rows = _shop_rows(db, status, category, keyword)
    return _xlsx_response(SHOP_COLUMNS, rows, _fname("shops", "xlsx"), "shops")


@router.get("/shops.csv")
def export_shops_csv(status: str | None = None, category: str | None = None,
                     keyword: str | None = None, db: Session = Depends(get_db)):
    rows = _shop_rows(db, status, category, keyword)
    return _csv_response(SHOP_COLUMNS, rows, _fname("shops", "csv"))


@router.get("/contacts.xlsx")
def export_contacts_xlsx(keyword: str | None = None,
                         db: Session = Depends(get_db)):
    rows = _contact_rows(db, keyword)
    return _xlsx_response(CONTACT_COLUMNS, rows, _fname("contacts", "xlsx"),
                          "contacts")


@router.get("/contacts.csv")
def export_contacts_csv(keyword: str | None = None,
                        db: Session = Depends(get_db)):
    rows = _contact_rows(db, keyword)
    return _csv_response(CONTACT_COLUMNS, rows, _fname("contacts", "csv"))
