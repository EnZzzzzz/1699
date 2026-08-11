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
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / ".cache" / "1688.db"
ACTOR = "devscrapper~whatsapp-number-validator"
API = "https://api.apify.com/v2"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_tokens(conn: sqlite3.Connection) -> list[str]:
    """全部启用的 apify token（新的在前），402 欠费时按序轮换。"""
    rows = conn.execute(
        "SELECT config_json FROM providers WHERE kind='apify' AND enabled=1 "
        "ORDER BY id DESC").fetchall()
    tokens = [t for t in (json.loads(r[0]).get("api_token") for r in rows) if t]
    if not tokens:
        sys.exit("[!] providers 表里没有启用的 apify 供应商")
    return tokens


def run_actor(tokens: list[str], numbers: list[str], timeout: int = 600) -> list[dict]:
    """同步调 actor，返回 [{"phone","exists","status",...}...]。

    actor 限制 2 次/分钟（超限 run 直接 FAILED，API 返回 400），
    遇到限流按提示秒数退避重试；402 欠费自动换下一个启用账号。
    """
    body = json.dumps({"phoneNumbers": numbers}).encode()
    ti = 0
    for attempt in range(6 + len(tokens)):
        token = tokens[ti]
        url = (f"{API}/acts/{ACTOR}/run-sync-get-dataset-items"
               f"?token={token}&timeout={timeout}")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code == 402 and ti + 1 < len(tokens):
                ti += 1
                log(f"账号额度耗尽（402），切换下一个 apify 账号（{ti + 1}/{len(tokens)}）")
                continue
            # 400 体里只有 run ID，限流原因要查 run 的 statusMessage
            if e.code in (400, 429) and _is_rate_limited(token, detail):
                wait = 70
                log(f"actor 限流（2 次/分钟），退避 {wait}s 后重试…")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("actor 持续限流/欠费，重试仍失败")


def _is_rate_limited(token: str, detail: str) -> bool:
    """从 400 错误体提取 run ID，查 statusMessage 是否限流。"""
    m = re.search(r"run ID: ([\w]+)", detail)
    if not m:
        return "rate limit" in detail.lower()
    url = f"{API}/actor-runs/{m.group(1)}?token={token}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            msg = json.loads(resp.read().decode())["data"].get("statusMessage") or ""
        return "rate limit" in msg.lower()
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Apify 批量查 WhatsApp 注册态")
    ap.add_argument("--bucket", default="declared_wa",
                    help="查哪个桶的未查号，逗号分隔多个（缺省 declared_wa）")
    ap.add_argument("--limit", type=int, default=0, help="最多查多少个（缺省不限）")
    ap.add_argument("--min-batch", type=int, default=1,
                    help="未查号少于此数直接退出不开火（攒批省 run，缺省 1=不攒）")
    ap.add_argument("--dry-run", action="store_true", help="只列号不调 API")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    tokens = load_tokens(conn)
    log(f"启用 apify 账号 {len(tokens)} 个（欠费自动轮换）")

    buckets = [b.strip() for b in args.bucket.split(",") if b.strip()]
    sql = (f"SELECT id, number FROM fb_contacts"
           f" WHERE bucket IN ({','.join('?' * len(buckets))})"
           " AND wa_checked_at IS NULL ORDER BY id")
    rows = conn.execute(sql, buckets).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    numbers = [r[1] for r in rows]
    log(f"fb_contacts[{args.bucket}] 未查号 {len(numbers)} 个，"
        f"预估费用 ${len(numbers) * 0.004:.3f}")
    if len(numbers) < args.min_batch:
        log(f"不足 --min-batch {args.min_batch}，攒批中本轮不开火")
        return 0
    if not numbers or args.dry_run:
        for n in numbers:
            print(" ", n)
        return 0

    log(f"调 actor {ACTOR}（{len(numbers)} 个号，100 号/run 分批）…")
    t0 = time.time()
    # actor 单 run 上限 100 号、2 run/分钟；分批同步调、逐批回写（中断不丢已查结果）
    tot = {"reg": 0, "not": 0, "err": 0, "inv": 0, "wb": 0}
    for i in range(0, len(rows), 100):
        chunk_rows = rows[i:i + 100]
        results = run_actor(tokens, [r[1] for r in chunk_rows])
        # 回写（与 daemon wa_task 同口径；actor 的 phone 是纯数字带国家码。
        # 兼容 86 前缀差异：库里中国号可能存裸 11 位）
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        by_phone = {}
        for r in results:
            p = re.sub(r"\D+", "", str(r.get("phone", "")))
            by_phone[p] = r
            if p.startswith("86") and len(p) == 13:
                by_phone.setdefault(p[2:], r)
        for row_id, number in chunk_rows:
            r = by_phone.get(re.sub(r"\D+", "", number))
            if not r:
                tot["err"] += 1
                continue
            if r.get("exists") is None:
                # 运营商/提供商拒绝的号（虚拟段等）永远查不出，
                # 标记 wa_source='invalid' 防止每次重查浪费额度
                if r.get("status") == "invalid":
                    conn.execute(
                        "UPDATE fb_contacts SET wa_checked_at=?,"
                        " wa_source='invalid' WHERE id=?", (ts, row_id))
                    tot["inv"] += 1
                else:
                    tot["err"] += 1
                continue
            reg = 1 if r["exists"] else 0
            cur = conn.execute(
                "UPDATE fb_contacts SET wa_registered=?, wa_checked_at=?,"
                " wa_source='checked' WHERE id=?", (reg, ts, row_id))
            tot["wb"] += cur.rowcount
            tot["reg"] += reg
            tot["not"] += (1 - reg)
        conn.commit()
        log(f"  已查 {min(i + 100, len(rows))}/{len(rows)}"
            f"（{time.time() - t0:.0f}s，已注册 {tot['reg']}）")
        if i + 100 < len(rows):
            time.sleep(35)  # 2 run/分钟节奏
    rate = tot["reg"] / (tot["reg"] + tot["not"]) * 100 if (tot["reg"] + tot["not"]) else 0
    log(f"回写 {tot['wb']} 行：已注册 {tot['reg']}，未注册 {tot['not']}，"
        f"无效号 {tot['inv']}，查询失败 {tot['err']}——注册率 {rate:.1f}%")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
