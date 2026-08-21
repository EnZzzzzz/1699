# -*- coding: utf-8 -*-
"""数据浏览接口：shops / contacts / fb-contacts 分页查询 + fb-contacts 导出（全部只读 SELECT）。

防御性说明：
- contacts 表的 wa_registered / wa_checked_at 两列由另一模块负责添加，可能尚不存在。
- 这里用 PRAGMA table_info 探测；缺列时：
  - items 中 wa_registered / wa_checked_at 统一返回 None
  - wa=registered / wa=unregistered 筛选返回空结果
  - wa=unchecked（或未传 wa）返回全量（即"全部未查"语义）
- fb_contacts / fb_posts 两表同理：缺表时直接返回空分页结果。
"""

import csv
import io
import time
import zipfile
from xml.sax.saxutils import escape

from fastapi import APIRouter, Query, Response

from app.db import connect, mark_fb_contacts_exported

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


def _fb_tables(cur) -> bool:
    """探测 fb_contacts / fb_posts 两表是否已存在。"""
    tables = {
        row[0]
        for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    return "fb_contacts" in tables and "fb_posts" in tables


@router.get("/fb-contacts")
def list_fb_contacts(
    wa: str = Query(default=""),
    bucket: str = Query(default=""),
    source: str = Query(default=""),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
):
    empty = {"total": 0, "page": page, "size": size, "items": []}
    with connect() as conn:
        cur = conn.cursor()
        if not _fb_tables(cur):
            return empty

        where_sql, params = _fb_where(wa, bucket, source, q)
        base = "FROM fb_contacts c LEFT JOIN fb_posts p ON p.url = c.post_url"
        total = cur.execute(
            f"SELECT COUNT(*) {base} {where_sql}", params).fetchone()[0]
        rows = cur.execute(
            f"""
            SELECT c.id, c.number, c.bucket, c.wa_source,
                   c.wa_registered, c.wa_checked_at,
                   c.post_url, c.group_id, c.first_seen_at,
                   p.group_name AS group_name, p.keyword AS keyword
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


def _fb_where(wa: str, bucket: str, source: str, q: str):
    """fb_contacts 通用筛选条件（分页列表与导出共用），返回 (where_sql, params)。"""
    # X 来源判定与看板 fb-pipeline 同口径（post_url 含 x.com/twitter.com）
    x_cond = "(c.post_url LIKE '%x.com%' OR c.post_url LIKE '%twitter.com%')"
    where = []
    params: list = []
    if source == "x":
        where.append(x_cond)
    elif source == "fb":
        where.append(f"NOT {x_cond}")
    if wa == "registered":
        where.append("c.wa_registered = 1")
    elif wa == "unregistered":
        where.append("c.wa_registered = 0")
    elif wa == "unchecked":
        # 无效号（wa_source='invalid'）已查过但永远查不出，不算「未查」
        where.append(
            "c.wa_registered IS NULL"
            " AND (c.wa_source IS NULL OR c.wa_source != 'invalid')")
    if bucket:
        where.append("c.bucket = ?")
        params.append(bucket)
    if q:
        where.append("(c.number LIKE ? OR c.post_url LIKE ? OR p.group_name LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return where_sql, params


# ==================== FB / X 联系方式导出 ====================
# 导出字段白名单：来源（FB / X）、帖子链接、群组属内部机密，一律不提供导出。
# 默认字段见 _EXPORT_DEFAULT_FIELDS（号码 / 用户名 / 发现时间）。

_EXPORT_BUCKET_LABELS = {
    "declared_wa": "声明 WA",
    "cn_uncertain": "国内待查",
    "overseas": "海外",
}


def _export_wa_status(row) -> str:
    if row["wa_source"] == "invalid":
        return "无效"
    if row["wa_registered"] == 1:
        return "已注册"
    if row["wa_registered"] == 0:
        return "未注册"
    return "未查"


# 字段 key -> (表头, 取值函数)；导出列顺序按请求 fields 顺序
_EXPORT_FIELDS = {
    "number": ("号码", lambda r: r["number"]),
    "author_name": ("用户名", lambda r: r["author_name"] or ""),
    "first_seen_at": ("发现时间", lambda r: r["first_seen_at"] or ""),
    "bucket": ("分桶", lambda r: _EXPORT_BUCKET_LABELS.get(r["bucket"], r["bucket"])),
    "wa_status": ("WhatsApp 状态", _export_wa_status),
    "wa_checked_at": ("查询时间", lambda r: r["wa_checked_at"] or ""),
}
_EXPORT_DEFAULT_FIELDS = ["number", "author_name", "first_seen_at"]


def _csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    """UTF-8 带 BOM，保证 Excel 直接打开不乱码。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(headers)
    w.writerows(rows)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def _xlsx_col_name(idx: int) -> str:
    """0 基列号 -> Excel 列名（A、B、…、AA）。"""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    """最小 xlsx 写入（stdlib zipfile + inlineStr，不引第三方依赖）。"""
    def cell(ref: str, value: str) -> str:
        v = escape(value or "")
        return (f'<c r="{ref}" t="inlineStr">'
                f'<is><t xml:space="preserve">{v}</t></is></c>')

    sheet_rows = []
    for r_idx, row in enumerate([headers] + rows, 1):
        cells = "".join(
            cell(f"{_xlsx_col_name(c_idx)}{r_idx}", str(v))
            for c_idx, v in enumerate(row))
        sheet_rows.append(f'<row r="{r_idx}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


@router.get("/fb-contacts/export")
def export_fb_contacts(
    wa: str = Query(default=""),
    bucket: str = Query(default=""),
    source: str = Query(default=""),
    q: str = Query(default=""),
    fields: str = Query(default=""),
    format: str = Query(default="xlsx"),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    mode: str = Query(default="first"),
):
    """导出 FB / X 联系方式（沿用列表筛选，全量不分页）。

    fields：逗号分隔的字段 key，限定白名单（见 _EXPORT_FIELDS），
    空则默认 号码/用户名/发现时间；列顺序按传入顺序。
    date_from / date_to：按发现时间（first_seen_at）圈定日期范围
    （YYYY-MM-DD，含首尾日），空则不限。
    mode：first=仅首次导出（未导出过的号码，默认）；repeat=重复导出
    （含已导出过的）。导出成功后统一回写 exported_at。
    """
    keys = [k.strip() for k in fields.split(",") if k.strip()]
    keys = [k for k in keys if k in _EXPORT_FIELDS]
    if not keys:
        keys = list(_EXPORT_DEFAULT_FIELDS)
    headers = [_EXPORT_FIELDS[k][0] for k in keys]
    getters = [_EXPORT_FIELDS[k][1] for k in keys]

    ids: list[int] = []
    rows: list[list[str]] = []
    has_exported = False
    with connect() as conn:
        cur = conn.cursor()
        if _fb_tables(cur):
            where_sql, params = _fb_where(wa, bucket, source, q)
            conds = [where_sql[7:]] if where_sql else []
            if date_from:
                conds.append("c.first_seen_at >= ?")
                params.append(f"{date_from} 00:00:00")
            if date_to:
                conds.append("c.first_seen_at <= ?")
                params.append(f"{date_to} 23:59:59")
            # exported_at 列由 migrate() 添加；防御性探测，缺列时
            # 首次导出退化为全量（一切都算未导出）且不写标记
            has_exported = "exported_at" in {
                r[1] for r in cur.execute(
                    "PRAGMA table_info(fb_contacts)").fetchall()
            }
            if mode == "first" and has_exported:
                conds.append("c.exported_at IS NULL")
            where_sql = f"WHERE {' AND '.join(conds)}" if conds else ""
            # SELECT 全量导出所需列（白名单字段的最大集）+ id（回写标记用）
            data_rows = cur.execute(
                f"""
                SELECT c.id, c.number, c.author_name, c.first_seen_at, c.bucket,
                       c.wa_source, c.wa_registered, c.wa_checked_at
                FROM fb_contacts c LEFT JOIN fb_posts p ON p.url = c.post_url
                {where_sql}
                ORDER BY c.id DESC
                """,
                params,
            ).fetchall()
            ids = [r["id"] for r in data_rows]
            rows = [[str(g(r)) for g in getters] for r in data_rows]

    stamp = time.strftime("%Y%m%d-%H%M%S")
    if format == "csv":
        content = _csv_bytes(headers, rows)
        media_type = "text/csv; charset=utf-8"
        filename = f"contacts-{stamp}.csv"
    else:
        content = _xlsx_bytes(headers, rows)
        media_type = ("application/vnd.openxmlformats-officedocument."
                      "spreadsheetml.sheet")
        filename = f"contacts-{stamp}.xlsx"

    # 导出成功后回写已导出标记（重复导出也刷新为最近一次导出时间）
    if ids and has_exported:
        mark_fb_contacts_exported(ids)

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Exported-Count": str(len(ids)),
        },
    )
