# -*- coding: utf-8 -*-
"""wa_check_apify.py — 用 Apify actor 批量查 WhatsApp 注册态并回写 fb_contacts。

背景（docs/feat_2026-08-07_apify-provider-pairing-login/SPEC.md §1.1）：
actor `devscrapper/whatsapp-number-validator`，REST 调用、$0.004/号、
准确率实测 29/30 与 Baileys 一致；token 存 providers 表（kind=apify）。
用于 Baileys 小号 403/封号时的查号替代通道。
（2026-08-17 曾试切 vtrdev~whatsapp-number-validator $0.001/号，实测其
上游 WhatsApp 查询全量 500 且有 100 号 quota 限制，当日回退。）

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


def normalize_number(number: str) -> str | None:
    """送 actor 前归一化：去非数字、去 00 前缀、裸 11 位中国手机号补 86。

    背景（2026-08-17 实测）：actor 要求带国家码，裸 11 位直接被拒为
    invalid——曾有 1782 个真实手机号因此被误标无效。返回 None = 号段
    明显不可能（如 110/119/125 等 11 位非手机号段、长度越界），
    调用方应直接标 invalid 不再浪费 API 额度。
    """
    d = re.sub(r"\D+", "", number or "")
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 11 and d.startswith("1"):
        # 中国手机号段 13x-19x；11 位但 10x/11x/12x 开头的不是手机号
        d = "86" + d if re.match(r"1[3-9]\d{9}$", d) else None
    if not d or len(d) < 8 or len(d) > 15:
        return None
    return d


def _ensure_quota_col(conn: sqlite3.Connection) -> None:
    """防御性探测：老库可能没跑过 server 迁移，缺列就现场补（幂等）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(providers)")}
    if "quota_exhausted_at" not in cols:
        conn.execute("ALTER TABLE providers ADD COLUMN quota_exhausted_at TEXT")
        conn.commit()


# 月额度账期约 30 天：quota_exhausted_at 距今不足 30 天视为仍欠费
QUOTA_CYCLE_DAYS = 30


def load_accounts(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """有额度的启用账号 [(id, name, token)]（新的在前），402/403 欠费时按序轮换。
    quota_exhausted_at 在 30 天账期内的账号跳过并提示预计恢复日期。"""
    _ensure_quota_col(conn)
    rows = conn.execute(
        "SELECT id, name, config_json, quota_exhausted_at FROM providers"
        " WHERE kind='apify' AND enabled=1 ORDER BY id DESC").fetchall()
    accounts = []
    now = time.time()
    for pid, name, cfg, exhausted in rows:
        token = json.loads(cfg).get("api_token")
        if not token:
            continue
        if exhausted:
            try:
                age_days = (now - time.mktime(
                    time.strptime(exhausted, "%Y-%m-%d %H:%M:%S"))) / 86400
            except ValueError:
                age_days = QUOTA_CYCLE_DAYS  # 时间串解析失败按已恢复处理
            if age_days < QUOTA_CYCLE_DAYS:
                recover = time.strftime("%Y-%m-%d", time.localtime(
                    now + (QUOTA_CYCLE_DAYS - age_days) * 86400))
                log(f"跳过 {name}（{exhausted} 额度耗尽，预计 {recover} 恢复）")
                continue
        accounts.append((pid, name, token))
    if not accounts:
        sys.exit("[!] 没有可用额度的 apify 账号（全部耗尽或未启用）")
    return accounts


def mark_exhausted(conn: sqlite3.Connection, pid: int, name: str) -> None:
    """记录额度耗尽时间（北京时间），恢复日 ≈ +30 天账期。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    recover = time.strftime("%Y-%m-%d", time.localtime(
        time.time() + QUOTA_CYCLE_DAYS * 86400))
    conn.execute("UPDATE providers SET quota_exhausted_at=? WHERE id=?",
                 (ts, pid))
    conn.commit()
    log(f"{name} 额度耗尽，已记录 {ts}，预计 {recover} 恢复")


def run_actor(conn: sqlite3.Connection,
              accounts: list[tuple[int, str, str]],
              numbers: list[str], timeout: int = 600) -> list[dict]:
    """同步调 actor，返回 [{"phone","exists","status",...}...]。

    actor 限制 2 次/分钟（超限 run 直接 FAILED，API 返回 400），
    遇到限流按提示秒数退避重试；402/403 欠费记录耗尽时间并换下一个账号。
    """
    body = json.dumps({"phoneNumbers": numbers}).encode()
    ti = 0
    for attempt in range(6 + len(accounts)):
        pid, name, token = accounts[ti]
        url = (f"{API}/acts/{ACTOR}/run-sync-get-dataset-items"
               f"?token={token}&timeout={timeout}")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            # 402=欠费；403 platform-feature-disabled=月硬顶超限，都要换号
            if e.code in (402, 403):
                mark_exhausted(conn, pid, name)
                if ti + 1 < len(accounts):
                    ti += 1
                    log(f"切换下一个 apify 账号：{accounts[ti][1]}"
                        f"（{ti + 1}/{len(accounts)}）")
                    continue
                raise RuntimeError("全部 apify 账号额度耗尽") from e
            # 400 体里只有 run ID，限流原因要查 run 的 statusMessage
            if e.code in (400, 429):
                if _is_rate_limited(token, detail):
                    wait = 70
                    log(f"actor 限流（2 次/分钟），退避 {wait}s 后重试…")
                    time.sleep(wait)
                    continue
                # 非限流 400（多为 run FAILED：actor 崩溃/内存等瞬时原因），
                # 记录详情并重试，仍失败才抛出（由 main 按块跳过）
                log(f"actor 400 非限流（第{attempt + 1}次）：{detail[:300]}")
                if attempt < 2:
                    time.sleep(30)
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
    accounts = load_accounts(conn)
    log(f"启用 apify 账号 {len(accounts)} 个（欠费自动轮换）："
        f"{'、'.join(a[1] for a in accounts)}")

    buckets = [b.strip() for b in args.bucket.split(",") if b.strip()]
    sql = (f"SELECT id, number FROM fb_contacts"
           f" WHERE bucket IN ({','.join('?' * len(buckets))})"
           " AND wa_checked_at IS NULL ORDER BY id")
    rows = conn.execute(sql, buckets).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    # 送 actor 前归一化（裸 11 位中国号补 86）；号段明显不可能的直接标
    # invalid，不浪费 API 额度（实测此类号送 actor 也只会被拒）
    send_rows, pre_inv = [], 0
    ts_now = time.strftime("%Y-%m-%d %H:%M:%S")
    for row_id, number in rows:
        norm = normalize_number(number)
        if norm is None:
            conn.execute("UPDATE fb_contacts SET wa_checked_at=?,"
                         " wa_source='invalid' WHERE id=?", (ts_now, row_id))
            pre_inv += 1
        else:
            send_rows.append((row_id, norm))
    if pre_inv:
        conn.commit()
        log(f"号段预过滤：{pre_inv} 个明显无效号直接标记（未调 API）")
    rows = send_rows
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

    # 实测（2026-08-17）：100 号/run 必现 run-failed，50 号稳定秒回——批次上限按 50
    batch = 50
    log(f"调 actor {ACTOR}（{len(numbers)} 个号，{batch} 号/run 分批）…")
    t0 = time.time()
    # actor 2 run/分钟；分批同步调、逐批回写（中断不丢已查结果）
    tot = {"reg": 0, "not": 0, "err": 0, "inv": 0, "wb": 0}
    for i in range(0, len(rows), batch):
        chunk_rows = rows[i:i + batch]
        try:
            results = run_actor(conn, accounts, [r[1] for r in chunk_rows])
        except Exception as e:  # noqa: BLE001
            # 单批失败不中断整轮：跳过该块（未回写的号下轮自动补查）
            log(f"  第 {i // batch + 1} 批失败跳过（{type(e).__name__}: {e}），"
                f"下轮补查")
            time.sleep(60)
            continue
        # 回写：chunk_rows 里的号已归一化（与发给 actor 的一致），
        # 按原样匹配返回值即可；返回键同样去 00 前缀兜底
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        by_phone = {}
        for r in results:
            p = re.sub(r"\D+", "", str(r.get("phone", "")))
            if p.startswith("00"):
                p = p[2:]
            by_phone[p] = r
            if p.startswith("86") and len(p) == 13:
                by_phone.setdefault(p[2:], r)
        for row_id, number in chunk_rows:
            r = by_phone.get(number)
            if not r:
                tot["err"] += 1
                continue
            if r.get("exists") is None:
                # 运营商/提供商拒绝的号（虚拟号段等）永远查不出，
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
        log(f"  已查 {min(i + batch, len(rows))}/{len(rows)}"
            f"（{time.time() - t0:.0f}s，已注册 {tot['reg']}）")
        if i + batch < len(rows):
            time.sleep(35)  # 2 run/分钟节奏
    rate = tot["reg"] / (tot["reg"] + tot["not"]) * 100 if (tot["reg"] + tot["not"]) else 0
    log(f"回写 {tot['wb']} 行：已注册 {tot['reg']}，未注册 {tot['not']}，"
        f"无效号 {tot['inv']}，查询失败 {tot['err']}——注册率 {rate:.1f}%")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
