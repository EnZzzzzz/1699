# -*- coding: utf-8 -*-
"""wa_check_apify.py — 用 Apify actor 批量查 WhatsApp 注册态并回写 fb_contacts。

背景（docs/feat_2026-08-07_apify-provider-pairing-login/SPEC.md §1.1）：
actor `devscrapper/whatsapp-number-validator`，REST 调用、$0.004/号、
准确率实测 29/30 与 Baileys 一致；token 存 providers 表（kind=apify）。
用于 Baileys 小号 403/封号时的查号替代通道。

用法：
    python3 scraper/wa_check_apify.py                      # 查 declared_wa 全部未查号
    python3 scraper/wa_check_apify.py --bucket cn_uncertain # 查指定桶的未查号
    python3 scraper/wa_check_apify.py --limit 20           # 限量
    python3 scraper/wa_check_apify.py --dry-run            # 只列出要查的号，不调 API
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / ".cache" / "1688.db"
ACTOR = "devscrapper~whatsapp-number-validator"
API = "https://api.apify.com/v2"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_token(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT config_json FROM providers WHERE name='apify' "
        "OR kind='apify' LIMIT 1").fetchone()
    if not row:
        sys.exit("[!] providers 表里没有 apify 供应商")
    token = json.loads(row[0]).get("api_token")
    if not token:
        sys.exit("[!] apify 供应商缺 api_token")
    return token


def run_actor(token: str, numbers: list[str], timeout: int = 600) -> list[dict]:
    """同步调 actor，返回 [{"phone","exists","status",...}...]。"""
    url = (f"{API}/acts/{ACTOR}/run-sync-get-dataset-items"
           f"?token={token}&timeout={timeout}")
    body = json.dumps({"phoneNumbers": numbers}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout + 60) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser(description="Apify 批量查 WhatsApp 注册态")
    ap.add_argument("--bucket", default="declared_wa",
                    help="查哪个桶的未查号（缺省 declared_wa）")
    ap.add_argument("--limit", type=int, default=0, help="最多查多少个（缺省不限）")
    ap.add_argument("--dry-run", action="store_true", help="只列号不调 API")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    token = load_token(conn)

    sql = ("SELECT id, number FROM fb_contacts WHERE bucket=? "
           "AND wa_checked_at IS NULL ORDER BY id")
    rows = conn.execute(sql, (args.bucket,)).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    numbers = [r[1] for r in rows]
    log(f"fb_contacts[{args.bucket}] 未查号 {len(numbers)} 个，"
        f"预估费用 ${len(numbers) * 0.004:.3f}")
    if not numbers or args.dry_run:
        for n in numbers:
            print(" ", n)
        return 0

    log(f"调 actor {ACTOR}（{len(numbers)} 个号，同步等待）…")
    t0 = time.time()
    results = run_actor(token, numbers)
    log(f"actor 返回 {len(results)} 条（{time.time() - t0:.0f}s）")

    # 回写（与 daemon wa_task 同口径；actor 的 phone 是纯数字带国家码，
    # 与库内 number 精确匹配）
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    by_phone = {re.sub(r"\D+", "", str(r.get("phone", ""))): r for r in results}
    n_reg = n_not = n_err = n_wb = 0
    for row_id, number in rows:
        r = by_phone.get(re.sub(r"\D+", "", number))
        if not r or r.get("exists") is None:
            n_err += 1
            continue
        reg = 1 if r["exists"] else 0
        cur = conn.execute(
            "UPDATE fb_contacts SET wa_registered=?, wa_checked_at=?,"
            " wa_source='checked' WHERE id=?", (reg, ts, row_id))
        n_wb += cur.rowcount
        n_reg += reg
        n_not += (1 - reg)
    conn.commit()
    rate = n_reg / (n_reg + n_not) * 100 if (n_reg + n_not) else 0
    log(f"回写 {n_wb} 行：已注册 {n_reg}，未注册 {n_not}，查询失败 {n_err}"
        f"——注册率 {rate:.1f}%")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
