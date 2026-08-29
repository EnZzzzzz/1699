# -*- coding: utf-8 -*-
"""wa_avatar_profile.py — 用 Apify clearpath actor 批量补 WA 头像画像（性别/年龄）并回写 fb_contacts。

actor `clearpath/whatsapp-profile-avatar-age-gender-api`（2026-08-25 实测 500 号）：
- 按 profile_analyzed 事件计费，实测 $7.53/千号（ Bronze $9/千刊例），
  每个送检号码都计费（含无头像/未注册），500 号起批、单 run 上限 10000；
- 输出 hasWhatsapp/hasAvatar/avatarUrl/estimatedAge/inferredGender/
  profileImageCategory 等；性别年龄是头像推断，只做参考不做硬过滤。
- 实测质量（500 个 wa_registered=1 号）：头像覆盖 94%，性别产出 47%
  （仅 individual_portrait 子集出性别，该子集占 45%），肖像年龄分布合理。
- avatarUrl 走 waavatar.xyz 代理，裸 python UA 403、带浏览器 UA 可下，
  时效未知，需要留图要送检后尽快另行下载（本脚本只存 URL）。

只查 wa_registered=1 的号（未注册号没有 WA 资料，送检纯浪费钱）。
回写列（ defensive ALTER，幂等）：wa_gender/wa_age/wa_avatar_category/
wa_avatar_url/wa_profiled_at/wa_profile_json（原始行 JSON 兜底）。

用法：
    python3 scraper/wa_avatar_profile.py                # 查全部已注册未画像号
    python3 scraper/wa_avatar_profile.py --limit 1000   # 限量
    python3 scraper/wa_avatar_profile.py --dry-run      # 只列号不调 API
    python3 scraper/wa_avatar_profile.py --stats        # 只看画像进度
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
ACTOR = "clearpath~whatsapp-profile-avatar-age-gender-api"
API = "https://api.apify.com/v2"

# actor 硬限制：单 run 最少 500、最多 10000 个去重号码
MIN_BATCH = 500
MAX_BATCH = 10000
# 实测单价（2026-08-25，500 号 $3.765）
COST_PER_NUMBER = 0.00753

# 画像列：性别/年龄/头像分类/头像URL/画像时间/原始 JSON
PROFILE_COLS = {
    "wa_gender": "TEXT",          # male/female/unknown（头像推断，仅供参考）
    "wa_age": "INTEGER",          # 头像推断年龄，未知为 NULL
    "wa_avatar_category": "TEXT",  # individual_portrait/object/cartoon_avatar/group_photo/unknown
    "wa_avatar_url": "TEXT",      # waavatar.xyz 代理 URL，时效未知
    "wa_profiled_at": "TEXT",     # 北京时间，NULL=未画像（送检过即写入，含无头像）
    "wa_profile_json": "TEXT",    # actor 返回的原始行 JSON
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize_number(number: str) -> str | None:
    """送 actor 前归一化：去非数字、去 00 前缀、裸 11 位中国手机号补 86。
    返回 E.164 不带 + 的数字串；None = 号段明显不可能（不送检）。"""
    d = re.sub(r"\D+", "", number or "")
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 11 and d.startswith("1"):
        d = "86" + d if re.match(r"1[3-9]\d{9}$", d) else None
    if not d or len(d) < 8 or len(d) > 15:
        return None
    return d


def _ensure_profile_cols(conn: sqlite3.Connection) -> None:
    """防御性探测：老库没跑过画像就现场补列（幂等）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(fb_contacts)")}
    for col, typ in PROFILE_COLS.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE fb_contacts ADD COLUMN {col} {typ}")
    conn.commit()


def _ensure_quota_col(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(providers)")}
    if "quota_exhausted_at" not in cols:
        conn.execute("ALTER TABLE providers ADD COLUMN quota_exhausted_at TEXT")
        conn.commit()


# 月额度账期约 30 天：quota_exhausted_at 距今不足 30 天视为仍欠费
QUOTA_CYCLE_DAYS = 30


def load_accounts(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """有额度的启用账号 [(id, name, token)]（新的在前），402/403 欠费时按序轮换。"""
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
                age_days = QUOTA_CYCLE_DAYS
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
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    recover = time.strftime("%Y-%m-%d", time.localtime(
        time.time() + QUOTA_CYCLE_DAYS * 86400))
    conn.execute("UPDATE providers SET quota_exhausted_at=? WHERE id=?",
                 (ts, pid))
    conn.commit()
    log(f"{name} 额度耗尽，已记录 {ts}，预计 {recover} 恢复")


def _api(req: urllib.request.Request, timeout: int = 60) -> dict:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def run_actor(conn: sqlite3.Connection,
              accounts: list[tuple[int, str, str]],
              numbers: list[str]) -> list[dict]:
    """异步跑一个 run（start → 轮询 → 取 dataset），返回结果行列表。

    500 号实测约 2.5 分钟，同步端点 300s 上限对大批次不安全，故走异步。
    402/403 欠费记录耗尽时间并换下一个账号重试整个 run。
    """
    body = json.dumps({"testMode": False, "phoneNumbers": numbers,
                       "onlyWhatsappUsers": False}).encode()
    ti = 0
    while True:
        pid, name, token = accounts[ti]
        try:
            run = _api(urllib.request.Request(
                f"{API}/acts/{ACTOR}/runs?token={token}", data=body,
                headers={"Content-Type": "application/json"}))["data"]
        except urllib.error.HTTPError as e:
            if e.code in (402, 403):
                mark_exhausted(conn, pid, name)
                if ti + 1 < len(accounts):
                    ti += 1
                    log(f"切换下一个 apify 账号：{accounts[ti][1]}"
                        f"（{ti + 1}/{len(accounts)}）")
                    continue
                raise RuntimeError("全部 apify 账号额度耗尽") from e
            raise
        run_id, dataset_id = run["id"], run["defaultDatasetId"]
        log(f"  run {run_id} 已启动（账号 {name}），轮询中…")
        t0 = time.time()
        while True:
            time.sleep(20)
            st = _api(urllib.request.Request(
                f"{API}/actor-runs/{run_id}?token={token}"))["data"]
            status = st["status"]
            if status == "SUCCEEDED":
                cost = st.get("usageTotalUsd")
                log(f"  run {run_id} 完成（{time.time() - t0:.0f}s"
                    + (f"，官方计费 ${cost:.2f}" if cost is not None else "") + "）")
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise RuntimeError(f"run {run_id} {status}")
            if time.time() - t0 > 3600:
                raise RuntimeError(f"run {run_id} 轮询超时（1h）")
        return _api(urllib.request.Request(
            f"{API}/datasets/{dataset_id}/items?token={token}",
        ), timeout=120)


def print_stats(conn: sqlite3.Connection) -> None:
    _ensure_profile_cols(conn)
    tot = conn.execute(
        "SELECT COUNT(*) FROM fb_contacts WHERE wa_registered=1").fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM fb_contacts"
        " WHERE wa_registered=1 AND wa_profiled_at IS NOT NULL").fetchone()[0]
    print(f"已注册号 {tot}，已画像 {done}，待画像 {tot - done}")
    for row in conn.execute(
            "SELECT COALESCE(wa_gender,'(未画像)'), COUNT(*) FROM fb_contacts"
            " WHERE wa_registered=1 GROUP BY wa_gender"):
        print(f"  {row[0]}: {row[1]}")
    for row in conn.execute(
            "SELECT COALESCE(wa_avatar_category,'(无)'), COUNT(*) FROM fb_contacts"
            " WHERE wa_registered=1 AND wa_profiled_at IS NOT NULL"
            " GROUP BY wa_avatar_category"):
        print(f"  [{row[0]}]: {row[1]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Apify 批量补 WA 头像画像（性别/年龄）")
    ap.add_argument("--limit", type=int, default=0, help="最多查多少个（缺省不限）")
    ap.add_argument("--batch-size", type=int, default=1000,
                    help=f"每 run 号码数（{MIN_BATCH}~{MAX_BATCH}，缺省 1000）")
    ap.add_argument("--min-batch", type=int, default=MIN_BATCH,
                    help=f"待画像号少于此数直接退出攒批（缺省 {MIN_BATCH}=actor 下限）")
    ap.add_argument("--max-cost", type=float, default=0,
                    help="本轮估算费用上限（美元，0=不限）")
    ap.add_argument("--dry-run", action="store_true", help="只列号不调 API")
    ap.add_argument("--stats", action="store_true", help="只看画像进度")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    _ensure_profile_cols(conn)
    if args.stats:
        print_stats(conn)
        return 0
    accounts = load_accounts(conn)
    log(f"启用 apify 账号 {len(accounts)} 个（欠费自动轮换）："
        f"{'、'.join(a[1] for a in accounts)}")

    rows = conn.execute(
        "SELECT id, number FROM fb_contacts"
        " WHERE wa_registered=1 AND wa_profiled_at IS NULL ORDER BY id").fetchall()
    if args.limit:
        rows = rows[:args.limit]
    # 归一化；号段明显不可能的跳过（wa_registered=1 的号理论上不该有）
    send_rows = []
    for row_id, number in rows:
        norm = normalize_number(number)
        if norm is not None:
            send_rows.append((row_id, norm))
    rows = send_rows
    numbers = ["+" + r[1] for r in rows]
    est = len(numbers) * COST_PER_NUMBER
    log(f"待画像号 {len(numbers)} 个，预估费用 ${est:.2f}"
        f"（按实测 ${COST_PER_NUMBER * 1000:.2f}/千号）")
    if len(numbers) < args.min_batch:
        log(f"不足 --min-batch {args.min_batch}，攒批中本轮不开火")
        return 0
    if args.max_cost and est > args.max_cost:
        log(f"预估 ${est:.2f} 超 --max-cost {args.max_cost}，不开火")
        return 0
    if not numbers or args.dry_run:
        for n in numbers:
            print(" ", n)
        return 0

    batch = max(MIN_BATCH, min(args.batch_size, MAX_BATCH))
    log(f"调 actor {ACTOR}（{len(numbers)} 个号，{batch} 号/run 分批）…")
    t0 = time.time()
    tot = {"wb": 0, "g": 0, "no_av": 0, "err": 0}
    for i in range(0, len(rows), batch):
        chunk_rows = rows[i:i + batch]
        # actor 下限 500：末尾不足一批时并回上一批的尾部凑够
        if 0 < len(chunk_rows) < MIN_BATCH:
            need = MIN_BATCH - len(chunk_rows)
            chunk_rows = rows[max(0, i - need):i] + chunk_rows
        try:
            results = run_actor(conn, accounts, [r[1] for r in chunk_rows])
        except Exception as e:  # noqa: BLE001
            # 单批失败不中断整轮：跳过该块（未回写的号下轮自动补画像）
            log(f"  第 {i // batch + 1} 批失败跳过（{type(e).__name__}: {e}），"
                f"下轮补查")
            continue
        # 回写：按归一化数字匹配（chunk 内可能有上一批尾部重复的号，重复回写无害）
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        by_phone = {}
        for r in results:
            p = re.sub(r"\D+", "", str(r.get("phoneNumber", "")))
            if p:
                by_phone[p] = r
        for row_id, number in chunk_rows:
            r = by_phone.get(number)
            if not r:
                tot["err"] += 1
                continue
            age = r.get("estimatedAge")
            conn.execute(
                "UPDATE fb_contacts SET wa_gender=?, wa_age=?,"
                " wa_avatar_category=?, wa_avatar_url=?, wa_profiled_at=?,"
                " wa_profile_json=? WHERE id=?",
                (r.get("inferredGender") or "unknown",
                 age if isinstance(age, int) and age >= 0 else None,
                 r.get("profileImageCategory") or (
                     "no_avatar" if not r.get("hasAvatar") else "unknown"),
                 r.get("avatarUrl"), ts,
                 json.dumps(r, ensure_ascii=False), row_id))
            tot["wb"] += 1
            if r.get("inferredGender") in ("male", "female"):
                tot["g"] += 1
            if not r.get("hasAvatar"):
                tot["no_av"] += 1
        conn.commit()
        log(f"  已画像 {min(i + batch, len(rows))}/{len(rows)}"
            f"（{time.time() - t0:.0f}s，出性别 {tot['g']}）")
    rate = tot["g"] / tot["wb"] * 100 if tot["wb"] else 0
    log(f"回写 {tot['wb']} 行：出性别 {tot['g']}（{rate:.1f}%），"
        f"无头像 {tot['no_av']}，未匹配 {tot['err']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
