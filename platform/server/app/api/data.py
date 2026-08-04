# -*- coding: utf-8 -*-
"""数据浏览接口：shops / contacts 分页查询（全部只读 SELECT）。

防御性说明：
- contacts 表的 wa_registered / wa_checked_at 两列由另一模块负责添加，可能尚不存在。
- 这里用 PRAGMA table_info 探测；缺列时：
  - items 中 wa_registered / wa_checked_at 统一返回 None
  - wa=registered / wa=unregistered 筛选返回空结果
  - wa=unchecked（或未传 wa）返回全量（即"全部未查"语义）
"""

from fastapi import APIRouter, Query

from app.db import connect

router = APIRouter(prefix="/data")


def _contacts_wa_columns(cur) -> bool:
    """探测 contacts 是否已具备 wa 两列。"""
    cols = {row[1] for row in cur.execute("PRAGMA table_info(contacts)").fetchall()}
    return "wa_registered" in cols and "wa_checked_at" in cols


@router.get("/shops")
def list_shops(
    status: str = Query(default=""),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
):
    where = []
    params: list = []
    if status:
        where.append("s.status = ?")
        params.append(status)
    if q:
        where.append("(s.domain LIKE ? OR s.name LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with connect() as conn:
        cur = conn.cursor()
        total = cur.execute(
            f"SELECT COUNT(*) FROM shops s {where_sql}", params).fetchone()[0]
        rows = cur.execute(
            f"""
            SELECT s.id, s.domain, s.name, s.status, s.first_seen_at, s.last_seen_at,
                   (SELECT COUNT(*) FROM contacts c WHERE c.shop_id = s.id) AS contact_count
            FROM shops s
            {where_sql}
            ORDER BY s.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [size, (page - 1) * size],
        ).fetchall()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [dict(r) for r in rows],
    }


@router.get("/contacts")
def list_contacts(
    wa: str = Query(default=""),
    has_mobile: str = Query(default=""),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
):
    with connect() as conn:
        cur = conn.cursor()
        has_wa = _contacts_wa_columns(cur)

        where = []
        params: list = []
        # wa 筛选：列缺失时 registered/unregistered 恒为空集，unchecked 不限制（全量即未查）
        if wa == "registered":
            where.append("c.wa_registered = 1" if has_wa else "1 = 0")
        elif wa == "unregistered":
            where.append("c.wa_registered = 0" if has_wa else "1 = 0")
        elif wa == "unchecked":
            if has_wa:
                where.append("c.wa_registered IS NULL")
        if has_mobile == "1":
            where.append("c.mobile IS NOT NULL AND c.mobile != ''")
        if q:
            where.append("(c.contact_person LIKE ? OR c.mobile LIKE ? OR c.phone LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        base = "FROM contacts c LEFT JOIN shops s ON s.id = c.shop_id"
        total = cur.execute(
            f"SELECT COUNT(*) {base} {where_sql}", params).fetchone()[0]

        wa_select = (
            "c.wa_registered AS wa_registered, c.wa_checked_at AS wa_checked_at"
            if has_wa
            else "NULL AS wa_registered, NULL AS wa_checked_at"
        )
        rows = cur.execute(
            f"""
            SELECT c.id, c.shop_id, c.contact_person, c.gender, c.phone, c.mobile,
                   c.address, c.scraped_at, {wa_select},
                   s.domain AS shop_domain, s.name AS shop_name
            {base}
            {where_sql}
            ORDER BY c.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [size, (page - 1) * size],
        ).fetchall()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [dict(r) for r in rows],
    }
