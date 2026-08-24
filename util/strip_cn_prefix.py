# -*- coding: utf-8 -*-
"""fb_contacts 中国手机号前缀清洗：+86 / 0086 / 86 + 11 位手机段统一剥壳为裸 11 位。

幂等，可反复执行；默认先备份（sqlite3 backup API，WAL 下安全）。
冲突处理：剥壳后目标裸号已存在（含另一个前缀行剥出的同号）时，把
wa_registered/wa_checked_at/wa_source/author_name/wa_name/exported_at 以
COALESCE 并入保留行、first_seen_at 取较早值，然后删除带前缀行；无冲突直接
UPDATE 剥前缀。非标号段（如 8612345678901 这类 861 后非 [3-9]）不动。

用法：
    python3 util/strip_cn_prefix.py                 # 备份 + 清洗
    python3 util/strip_cn_prefix.py --no-backup     # 只清洗
    python3 util/strip_cn_prefix.py --db 路径       # 指定库（默认 .cache/1688.db）
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / ".cache" / "1688.db"

# 剥壳目标：可选 +、可选 00、86、11 位手机段
RE_PREFIXED = re.compile(r"^\+?(?:00)?86(1[3-9]\d{9})$")

_MERGE_COLS = ("wa_registered", "wa_checked_at", "wa_source",
               "author_name", "wa_name", "exported_at")


def strip_target(number: str) -> str | None:
    """带前缀的中国手机号返回裸 11 位，否则返回 None（不动）。"""
    m = RE_PREFIXED.match((number or "").strip())
    return m.group(1) if m else None


def backup(db_path: Path) -> Path:
    dst = db_path.with_name(
        f"{db_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}-strip86")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(dst)
    src.backup(dst_conn)
    dst_conn.close()
    src.close()
    return dst


def _merge_into(conn, src_id: int, keep_id: int) -> None:
    """把 src_id 行的查号/导出字段并入 keep_id 行后删除 src_id 行。"""
    a = conn.execute(
        f"SELECT {', '.join(_MERGE_COLS)}, first_seen_at"
        " FROM fb_contacts WHERE id=?", (src_id,)).fetchone()
    conn.execute(
        "UPDATE fb_contacts SET"
        " wa_registered = COALESCE(wa_registered, ?),"
        " wa_checked_at = COALESCE(wa_checked_at, ?),"
        " wa_source     = COALESCE(wa_source, ?),"
        " author_name   = COALESCE(author_name, ?),"
        " wa_name       = COALESCE(wa_name, ?),"
        " exported_at   = COALESCE(exported_at, ?),"
        " first_seen_at = MIN(first_seen_at, ?)"
        " WHERE id=?", (*a, keep_id))
    conn.execute("DELETE FROM fb_contacts WHERE id=?", (src_id,))


def clean(db_path: Path) -> tuple[int, int]:
    """返回 (合并删除数, 直接剥壳数)。短事务 + busy_timeout。"""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        rows = conn.execute("SELECT id, number FROM fb_contacts").fetchall()
        # 裸形态（不带可剥前缀）号码 -> id，作为冲突判定与合并目标
        taken: dict[str, int] = {}
        cand: list[tuple[int, str]] = []  # (前缀行 id, 裸号)
        for rid, number in rows:
            bare = strip_target(number)
            if bare is None:
                taken[number] = rid
            else:
                cand.append((rid, bare))
        if not cand:
            conn.rollback()
            return 0, 0

        merged = stripped = 0
        for rid, bare in cand:
            keep = taken.get(bare)
            if keep is not None:
                _merge_into(conn, rid, keep)
                merged += 1
            else:
                conn.execute(
                    "UPDATE fb_contacts SET number=? WHERE id=?",
                    (bare, rid))
                taken[bare] = rid  # 剥出的新裸号也占位，防两个前缀行撞号
                stripped += 1
        conn.commit()
        return merged, stripped
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    if not args.no_backup:
        dst = backup(args.db)
        print(f"已备份 → {dst}")
    merged, stripped = clean(args.db)
    print(f"合并删除 {merged} 条（前缀形态与已有号重复），剥壳 {stripped} 条")
    if not (merged or stripped):
        print("库内无可清洗前缀，已是干净状态")


if __name__ == "__main__":
    sys.exit(main())
