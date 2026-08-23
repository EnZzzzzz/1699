# -*- coding: utf-8 -*-
"""费用记账同步：真实账单（官方 API）+ 渠道估算（单价折算）入库 cost_records。

- Apify：GET /v2/users/me/usage/monthly 拿账号级真实账单（覆盖 X/memo23/WA
  三条线——它们都是同一账号下的 actor，接口无 actor 粒度，拆账靠估算行）。
  date 存 Apify 原始 UTC 账单日期，便于与控制台对账。
- Bright Data：GET /balance 拿余额快照（需 token 开 Billing 权限，否则 403
  跳过 real 行）；另始终落 fb_serp 估算行。
- 估算：单价常量与 scraper 写死值保持一致（平台不 import scraper，有意重复，
  注明来源行号；改价时两边同步）：
    X        $0.00015/行   （scraper/x_keyword_search.py:102）
    memo23   $0.0019/结果  （scraper/fb_keyword_search.py:51）
    WA 查号  $0.004/条     （scraper/wa_check_apify.py:214）
    BD SERP  $0.0015/条   （控制台确认 Web Scraper API $1.50/1k records，
                            1 次 SERP 查询 = 1 条记录）
"""

import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import date as _date, datetime, timedelta as _td, timezone
from pathlib import Path

from app.db import DB_PATH, migrate

CACHE_DIR = Path(DB_PATH).parent
FB_STATE = CACHE_DIR / "fb_keyword_search_state.json"
X_STATE = CACHE_DIR / "x_keyword_search_state.json"

APIFY_USAGE_API = "https://api.apify.com/v2/users/me/usage/monthly"
APIFY_ME_API = "https://api.apify.com/v2/users/me"
BD_BALANCE_API = "https://api.brightdata.com/balance"

X_COST_PER_ROW = 0.00015        # scraper/x_keyword_search.py:102
MEMO23_COST_PER_RESULT = 0.0019  # scraper/fb_keyword_search.py:51
WA_COST_PER_NUMBER = 0.004       # scraper/wa_check_apify.py:214
BD_COST_PER_QUERY = 0.0015       # 控制台确认 $1.50/1k records，1 次 SERP 查询=1 条记录

BD_SNAPSHOTS_API = ("https://api.brightdata.com/datasets/v3/snapshots"
                    "?dataset_id=gd_mfz5x93lmsjjjylob&limit=1000")
# snapshots 接口无分页、最多取最新 1000 条；FB SERP 脚本每次查询产生 1 个快照

# Apify 服务项 → 用量单位（未列出的记 NULL）
_SERVICE_UNITS = {
    "PAID_ACTORS_PER_EVENT": "usd-events",
    "PAID_ACTORS_PER_RESULT": "rows",
    "ACTOR_COMPUTE_UNITS": "cu",
    "DATA_TRANSFER_EXTERNAL_GBYTES": "GB",
    "DATASET_READS": "reads",
    "DATASET_WRITES": "writes",
}


def _bj_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _upsert(conn, date, provider, channel, service, source,
            quantity, unit, usd, detail=None):
    """幂等 upsert 一条费用记录（UNIQUE(date,provider,channel,service,source)）。"""
    conn.execute(
        "INSERT INTO cost_records (date, provider, channel, service, source,"
        " quantity, unit, usd, detail_json, synced_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(date, provider, channel, service, source) DO UPDATE SET"
        " quantity=excluded.quantity, unit=excluded.unit, usd=excluded.usd,"
        " detail_json=excluded.detail_json, synced_at=excluded.synced_at",
        (date, provider, channel, service, source, quantity, unit, usd,
         json.dumps(detail, ensure_ascii=False) if detail is not None else None,
         _bj_now()))


def _open_write():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def sync_apify(account: str | None = None) -> dict:
    """同步 Apify 账号级真实账单（dailyServiceUsages 逐日逐服务 upsert）。

    多账号时 channel 记为 account:<name> 区分。失败不抛，返回 error。
    account 传入时只同步该账号（供应商卡片单独刷新用）。
    """
    conn = _open_write()
    try:
        provs = conn.execute(
            "SELECT name, config_json FROM providers"
            " WHERE kind='apify' AND enabled=1").fetchall()
        if account is not None:
            provs = [p for p in provs if p[0] == account]
        if not provs:
            return {"ok": False, "error": "providers 表无 enabled 的 apify 账号"}
        results = []
        for name, cfg in provs:
            token = (json.loads(cfg) or {}).get("api_token")
            if not token:
                results.append({"account": name, "ok": False,
                                "error": "config_json 缺 api_token"})
                continue
            n = 0
            failed: str | None = None
            # 逐账期回溯历史账单：当前账期 → 按 usageCycle.startAt 往前逐期查，
            # 直到某账期无任何用量或达到上限（防无限回溯）
            query_date: str | None = None  # None=当前账期
            cur_cycle: dict | None = None   # 当前账期响应（用于 USAGE_CYCLE 快照）
            for _ in range(4):
                url = APIFY_USAGE_API + (f"?date={query_date}" if query_date else "")
                try:
                    data = _get_json(url, token).get("data", {})
                except (urllib.error.URLError, OSError, ValueError) as e:
                    failed = str(e)
                    break
                if query_date is None:
                    cur_cycle = data
                days = data.get("dailyServiceUsages", [])
                for day in days:
                    date = str(day.get("date", ""))[:10]  # 原始 UTC 账单日期
                    if not date:
                        continue
                    for service, usage in (day.get("serviceUsage") or {}).items():
                        _upsert(
                            conn, date, "apify", f"account:{name}", service,
                            "real", usage.get("quantity"),
                            _SERVICE_UNITS.get(service),
                            float(usage.get("baseAmountUsd") or 0))
                        n += 1
                start_at = str((data.get("usageCycle") or {}).get("startAt", ""))
                if not days or not start_at:
                    break  # 空账期 = 更早没有历史了
                # 下一轮回溯：本账期开始前一天
                query_date = (_date.fromisoformat(start_at[:10])
                              - _td(days=1)).isoformat()
            # 账期用量快照（date 存北京快照日，与上面的 UTC 账单日期口径不同）：
            # Apify 是订阅+后付费，无充值余额；记录当前账期累计用量，
            # 套餐额度/月度上限放 detail（取自 /v2/users/me 的 plan）
            if failed is None and cur_cycle:
                plan: dict = {}
                try:
                    me = _get_json(APIFY_ME_API, token)
                    plan = ((me.get("data") or {}).get("plan") or {})
                except (urllib.error.URLError, OSError, ValueError):
                    pass  # plan 拿不到就只记用量
                _upsert(
                    conn, time.strftime("%Y-%m-%d"), "apify",
                    f"account:{name}", "USAGE_CYCLE", "real", None, "usd",
                    float(cur_cycle.get(
                        "totalUsageCreditsUsdAfterVolumeDiscount") or 0),
                    detail={
                        "usageCycle": cur_cycle.get("usageCycle"),
                        "monthlyUsageCreditsUsd":
                            plan.get("monthlyUsageCreditsUsd"),
                        "maxMonthlyUsageUsd": plan.get("maxMonthlyUsageUsd"),
                    })
            if failed:
                results.append({"account": name, "ok": False, "error": failed})
            else:
                results.append({"account": name, "ok": True, "rows": n})
        conn.commit()
        return {"ok": all(r.get("ok") for r in results), "accounts": results}
    finally:
        conn.close()


def sync_brightdata() -> dict:
    """同步 Bright Data：余额快照（real，需 Billing 权限）+ fb_serp 估算行。"""
    conn = _open_write()
    try:
        row = conn.execute(
            "SELECT config_json FROM providers"
            " WHERE kind='brightdata' AND enabled=1 LIMIT 1").fetchone()
        if not row:
            return {"ok": False, "error": "providers 表无 enabled 的 brightdata 账号"}
        api_key = (json.loads(row[0]) or {}).get("api_key")
        res: dict = {"ok": True, "need_permission": False, "real_rows": 0}
        if api_key:
            try:
                body = _get_json(BD_BALANCE_API, api_key)
                today = time.strftime("%Y-%m-%d")  # 快照日（北京日期）
                balance = body.get("balance")
                _upsert(conn, today, "brightdata", "account", "BALANCE",
                        "real", None, "usd",
                        float(balance) if balance is not None else 0.0,
                        detail=body)
                res["real_rows"] = 1
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    # token 缺 Billing 权限：
                    # https://brightdata.com/cp/setting/users 开通后自动生效
                    res["need_permission"] = True
                else:
                    res["ok"] = False
                    res["error"] = f"HTTP {e.code}"
            except (urllib.error.URLError, OSError, ValueError) as e:
                res["ok"] = False
                res["error"] = str(e)
            # fb_serp 按快照记录数校准（覆盖 sync_estimates 的查询数口径）：
            # 最新 1000 个快照按北京日期聚合 dataset_size（ready 才计费），
            # × $1.50/1k records；早于快照覆盖范围的日期保留查询数口径
            try:
                snaps = _get_json(BD_SNAPSHOTS_API, api_key)
                per_day: dict = {}
                for sn in snaps:
                    if sn.get("status") != "ready":
                        continue
                    # created 为 UTC ISO，转北京日期（+8h）
                    dt = datetime.fromisoformat(
                        str(sn["created"]).replace("Z", "+00:00"))
                    day = dt.astimezone(timezone(_td(hours=8)))
                    day = day.strftime("%Y-%m-%d")
                    per_day[day] = per_day.get(day, 0) + int(
                        sn.get("dataset_size") or 0)
                for day, records in per_day.items():
                    _upsert(conn, day, "brightdata", "fb_serp", "", "estimate",
                            records, "records", records * BD_COST_PER_QUERY,
                            detail={"basis": "snapshots"})
                res["snapshot_days"] = len(per_day)
            except (urllib.error.URLError, OSError, ValueError,
                    KeyError, TypeError) as e:
                res["snapshot_error"] = str(e)
        conn.commit()
        return res
    finally:
        conn.close()


def sync_estimates() -> dict:
    """同步渠道估算行：state JSON 日用量 × 写死单价 + WA 查号条数折算。"""
    n = 0
    conn = _open_write()
    try:
        # FB：memo23 结果 + SERP 查询
        if FB_STATE.exists():
            daily = (json.loads(FB_STATE.read_text()) or {}).get("daily", {})
            for day, u in daily.items():
                _upsert(conn, day, "apify", "fb_memo23", "", "estimate",
                        u.get("memo23_results"), "results",
                        (u.get("memo23_results") or 0) * MEMO23_COST_PER_RESULT)
                _upsert(conn, day, "brightdata", "fb_serp", "", "estimate",
                        u.get("serp_queries"), "queries",
                        (u.get("serp_queries") or 0) * BD_COST_PER_QUERY)
                n += 2
        # X：结果行数
        if X_STATE.exists():
            daily = (json.loads(X_STATE.read_text()) or {}).get("daily", {})
            for day, u in daily.items():
                _upsert(conn, day, "apify", "x_keyword", "", "estimate",
                        u.get("x_results"), "rows",
                        (u.get("x_results") or 0) * X_COST_PER_ROW)
                n += 1
        # WA 查号：按 wa_checked_at 分北京日期计数（近 40 天，防御缺列/缺表）
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "fb_contacts" in tables:
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(fb_contacts)")}
            if "wa_checked_at" in cols:
                rows = conn.execute(
                    "SELECT substr(wa_checked_at, 1, 10) AS day, COUNT(*)"
                    " FROM fb_contacts"
                    " WHERE wa_checked_at >= date('now', 'localtime', '-40 days')"
                    " GROUP BY day").fetchall()
                for day, cnt in rows:
                    _upsert(conn, day, "apify", "wa_check", "", "estimate",
                            cnt, "numbers", cnt * WA_COST_PER_NUMBER)
                    n += 1
        conn.commit()
        return {"ok": True, "rows": n}
    finally:
        conn.close()


def sync_all() -> dict:
    """顺序同步全部来源，单源失败不影响其他源。"""
    migrate()  # 幂等：确保 cost_records 表存在
    return {
        "synced_at": _bj_now(),
        "apify": sync_apify(),
        "estimates": sync_estimates(),
        # brightdata 最后跑：快照记录数口径覆盖 estimates 的 fb_serp 查询数口径
        "brightdata": sync_brightdata(),
    }
