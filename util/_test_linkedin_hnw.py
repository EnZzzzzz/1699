# -*- coding: utf-8 -*-
"""_test_linkedin_hnw.py — 领英美国高净值人群采号管线验证（一次性小样测试）。

管线（2026-08-24 调研结论）：
  ① harvestapi~linkedin-profile-search  按地区(美国)+职位(CEO/Founder/...)
    搜人拿 profile 详情（Full 模式 $4/千条 + 搜索页 $0.1/25 条）；
  ② apivault_labs~skip-trace-people-finder  按「姓名; 城市, 州缩写」查美国
    手机号/地址（$6.5/千条命中记录，查不到不收费）；
  ③ genderize.io 免费接口按 first name 推断性别（领英无性别字段）。

验证目标：查号命中率、手机号占比、性别分布、单条全成本。
token 取自 providers 表（kind=apify），与 wa_check_apify.py 同口径。

用法：
    python3 util/_test_linkedin_hnw.py                    # 100 条全流程
    python3 util/_test_linkedin_hnw.py --limit 20         # 小样冒烟
    python3 util/_test_linkedin_hnw.py --dry-run          # 只跑第①步搜人
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / ".cache" / "1688.db"
OUT_PATH = REPO_ROOT / ".cache" / "linkedin_hnw_test.json"
API = "https://api.apify.com/v2"

ACTOR_SEARCH = "harvestapi~linkedin-profile-search"
ACTOR_TRACE = "apivault_labs~skip-trace-people-finder"

# 高净值代理职位（领英没有财富字段，用职位+公司规模近似）
DEFAULT_TITLES = ["CEO", "Founder", "Owner", "President", "Managing Partner"]

# 领英常见大都会区写法 → 「城市, 州」（实测大量位置是这种格式，解析不出城市）
METRO_MAP = {
    "new york city metropolitan area": "New York, NY",
    "san francisco bay area": "San Francisco, CA",
    "greater boston": "Boston, MA",
    "denver metropolitan area": "Denver, CO",
    "greater los angeles area": "Los Angeles, CA",
    "greater chicago area": "Chicago, IL",
    "dallas-fort worth metroplex": "Dallas, TX",
    "greater seattle area": "Seattle, WA",
    "washington dc-baltimore area": "Washington, DC",
    "greater atlanta area": "Atlanta, GA",
    "greater houston": "Houston, TX",
    "miami-fort lauderdale area": "Miami, FL",
}

# 美国州名 → 缩写（skip-trace 输入格式 "Jane Doe; Springfield, IL"）
US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_token() -> str:
    """providers 表取启用中的 apify token（只读连接，与 wa_check_apify 同口径）。"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT config_json FROM providers WHERE kind='apify' AND enabled=1"
            " ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    for cfg, in rows:
        token = json.loads(cfg).get("api_token")
        if token:
            return token
    sys.exit("[!] providers 表没有可用的 apify token")


def http_json(method: str, url: str, body: dict | None = None,
              timeout: int = 120) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"})
    last_err: Exception | None = None
    for attempt in range(4):  # 瞬断（SSL EOF 等）重试 3 次，间隔 3s
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            if e.code in (402, 403):
                sys.exit(f"[!] Apify {e.code} 欠费/无权限，停止：{detail}")
            raise RuntimeError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            last_err = e
            time.sleep(3)
    raise RuntimeError(f"网络错误重试 3 次仍失败: {last_err}")


def run_actor(token: str, actor: str, payload: dict,
              poll_interval: int = 10, max_wait: int = 1800,
              resume_run_id: str | None = None) -> tuple[list, dict]:
    """异步跑 actor 并轮询到结束，返回 (dataset items, run 对象)。

    resume_run_id：复用已启动的 run（脚本中断后不重跑扣费，直接挂回去等结果）。"""
    if resume_run_id:
        run_id = resume_run_id
        log(f"  复用已有 run {run_id}，等待完成…")
    else:
        run = http_json("POST", f"{API}/acts/{actor}/runs?token={token}", payload)
        run_id = run["data"]["id"]
        log(f"  run {run_id} 已启动，等待完成…")
    deadline = time.time() + max_wait
    while True:
        time.sleep(poll_interval)
        info = http_json("GET", f"{API}/actor-runs/{run_id}?token={token}")["data"]
        status = info["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        if time.time() > deadline:
            sys.exit(f"[!] run {run_id} 超时未结束（status={status}）")
    cost = info.get("usageTotalUsd")
    log(f"  run 结束：{status}，官方计费 ${cost}")
    if status != "SUCCEEDED":
        sys.exit(f"[!] actor 运行失败（{status}），去 Apify 控制台看 run {run_id}")
    items = http_json(
        "GET",
        f"{API}/actor-runs/{run_id}/dataset/items?token={token}&clean=true")
    return items, info


# ---------- ① 搜人 ----------

def stage_search(token: str, limit: int, titles: list[str],
                 location: str, resume_run_id: str | None = None
                 ) -> tuple[list, float]:
    log(f"① 搜人：{location} / 职位 {titles} / 上限 {limit} 条（Full 模式）")
    payload = {
        "profileScraperMode": "Full",
        "locations": [location],
        "currentJobTitles": titles,
        "maxItems": limit,
        "takePages": max(1, -(-limit // 25)),  # 每页 25 条，封顶页数
    }
    items, run = run_actor(token, ACTOR_SEARCH, payload,
                           resume_run_id=resume_run_id)
    log(f"  拿到 profile {len(items)} 条")
    if items:
        log(f"  字段示例：{sorted(items[0].keys())}")
    return items, run.get("usageTotalUsd") or 0.0


def pick_location(item: dict) -> str | None:
    """从 profile 里尽力取位置字符串（不同 actor 版本字段不一，防御性探测）。"""
    loc = item.get("location")
    if isinstance(loc, dict):
        for k in ("linkedinText", "parsed", "text", "fullName"):
            v = loc.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        if isinstance(loc.get("parsed"), dict):
            p = loc["parsed"]
            parts = [p.get("city"), p.get("state"), p.get("countryFull")]
            s = ", ".join(x for x in parts if x)
            if s:
                return s
        return None
    if isinstance(loc, str) and loc.strip():
        return loc.strip()
    for k in ("addressWithCountry", "addressWithoutCountry"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def parse_us_city_state(loc: str | None) -> str | None:
    """把领英位置串（如 'Dallas, Texas, United States'）解析成 'Dallas, TX'。

    'Greater X Area' / 'X Metropolitan Area' / 仅国家名 等无法精确定位的
    返回 None（查号时只传姓名，歧义会增多，统计里单列）。"""
    if not loc:
        return None
    metro = METRO_MAP.get(loc.strip().lower())
    if metro:
        return metro
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    state_abbr = None
    state_idx = -1
    for i, p in enumerate(parts):
        abbr = US_STATES.get(p.lower())
        if abbr:
            state_abbr, state_idx = abbr, i
        elif len(p) == 2 and p.upper() in US_STATES.values():
            state_abbr, state_idx = p.upper(), i
    if not state_abbr or state_idx == 0:
        return None
    city = parts[state_idx - 1]
    for noise in ("Greater", "Area", "Metropolitan", "Metro", "Bay"):
        city = city.replace(noise, "").strip()
    if not city:
        return None
    return f"{city}, {state_abbr}"


def full_name(item: dict) -> str:
    """拼接姓名并剥掉头衔后缀（'James Blackwell, PhD' → 'James Blackwell'）。

    头衔会显著拉低查号匹配率；逗号也会干扰 'Name; City, ST' 格式。
    另外去掉单字母中间名缩写（'Richard L. Douglass' → 'Richard Douglass'），
    skip-trace actor 的名字校验会直接拒绝带 'X.' 的输入（2026-08-24 实测）。"""
    name = " ".join(x for x in (item.get("firstName"), item.get("lastName")) if x)
    name = name.strip() or (item.get("fullName") or "").strip()
    name = name.split(",")[0].strip()
    tokens = [t for t in name.split() if not re.fullmatch(r"[A-Za-z]\.?", t)]
    return " ".join(tokens) if len(tokens) >= 2 else name


# ---------- ② 查号 ----------

def stage_trace(token: str, leads: list[dict]) -> tuple[list, float]:
    """分批送查（每批 50）：actor 单 run 有时间预算，实测 99 条/批会有
    约 1/3 输入报 'not processed before run time budget' 被截断。"""
    queries = []
    for ld in leads:
        q = ld["name"]
        if ld.get("city_state"):
            q += f"; {ld['city_state']}"
        queries.append(q)
    log(f"② 查号：{len(queries)} 个姓名送 skip-trace（每批 50，每条最多 3 个匹配人）")
    all_items: list[dict] = []
    total_cost = 0.0
    for i in range(0, len(queries), 50):
        batch = queries[i:i + 50]
        log(f"  批次 {i // 50 + 1}：{len(batch)} 条")
        payload = {
            "name": batch,
            "max_results": 3,
            "source": "auto",
            "flatOutput": True,
            "verifyEmails": False,
        }
        items, run = run_actor(token, ACTOR_TRACE, payload,
                               poll_interval=15, max_wait=3600)
        all_items.extend(items)
        total_cost += run.get("usageTotalUsd") or 0.0
    log(f"  返回记录 {len(all_items)} 条")
    return all_items, total_cost


# ---------- ③ 性别 ----------

def stage_gender(leads: list[dict]) -> None:
    """genderize.io 免费额度按 first name 批量推断；失败一律 unknown 不阻塞。"""
    firsts = sorted({ld["name"].split()[0] for ld in leads if ld["name"]})
    if not firsts:
        return
    log(f"③ 性别推断：{len(firsts)} 个去重 first name 走 genderize.io")
    guess: dict[str, str] = {}
    for i in range(0, len(firsts), 10):  # 官方批量接口单请求最多 10 个
        chunk = firsts[i:i + 10]
        qs = "&".join(f"name[]={urllib.parse.quote(n)}" for n in chunk)
        try:
            with urllib.request.urlopen(
                    f"https://api.genderize.io?{qs}", timeout=20) as resp:
                for row in json.loads(resp.read().decode()):
                    guess[row["name"]] = row.get("gender") or "unknown"
        except urllib.error.HTTPError as e:
            if e.code == 429:  # 免费限流：等 5s 重试一次，仍失败则标 unknown
                time.sleep(5)
                try:
                    with urllib.request.urlopen(
                            f"https://api.genderize.io?{qs}", timeout=20) as resp:
                        for row in json.loads(resp.read().decode()):
                            guess[row["name"]] = row.get("gender") or "unknown"
                except Exception as e2:
                    log(f"  genderize 重试仍失败（{e2}），剩余名字标 unknown")
                    break
            else:
                log(f"  genderize 失败（{e}），剩余名字标 unknown")
                break
        except Exception as e:
            log(f"  genderize 失败（{e}），剩余名字标 unknown")
            break
        time.sleep(2)
    for ld in leads:
        ld["gender"] = guess.get(ld["name"].split()[0], "unknown")


# ---------- 主流程 ----------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="搜人上限")
    ap.add_argument("--titles", default=",".join(DEFAULT_TITLES),
                    help="逗号分隔的职位过滤")
    ap.add_argument("--location", default="United States")
    ap.add_argument("--dry-run", action="store_true", help="只跑搜人，不查号")
    ap.add_argument("--search-run-id", default=None,
                    help="复用已启动的搜人 run（中断续跑，不重复扣费）")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()
    titles = [t.strip() for t in args.titles.split(",") if t.strip()]

    token = load_token()
    total_cost = 0.0

    profiles, cost1 = stage_search(token, args.limit, titles, args.location,
                                   resume_run_id=args.search_run_id)
    total_cost += cost1

    leads = []
    for it in profiles:
        loc = pick_location(it)
        leads.append({
            "name": full_name(it),
            "headline": it.get("headline") or "",
            "linkedin_url": it.get("linkedinUrl") or it.get("url") or "",
            "location_raw": loc,
            "city_state": parse_us_city_state(loc),
            "company": (it.get("companyName")
                        or ((it.get("currentPosition") or [{}])[0].get("companyName"))
                        or ((it.get("experience") or [{}])[0].get("companyName"))
                        or ""),
        })
    leads = [ld for ld in leads if ld["name"]]
    parsed = sum(1 for ld in leads if ld["city_state"])
    log(f"  有效姓名 {len(leads)}，位置可解析到城市+州 {parsed} 条")

    trace_items, cost2 = [], 0.0
    if not args.dry_run and leads:
        trace_items, cost2 = stage_trace(token, leads)
        total_cost += cost2

    # 按输入姓名归组统计（一人最多 3 条匹配记录，记录数≠人数）
    from collections import defaultdict
    by_input: dict[str, list] = defaultdict(list)
    for r in trace_items:
        if isinstance(r, dict):
            q = (r.get("inputGiven") or "").split(";")[0].strip()
            by_input[q].append(r)
    n_matched = sum(1 for rs in by_input.values()
                    if any(r.get("success") for r in rs))
    n_with_phone = sum(1 for rs in by_input.values()
                       if any(r.get("success") and r.get("phones") for r in rs))
    fail_notes: dict[str, int] = {}
    for r in trace_items:
        if isinstance(r, dict) and not r.get("success"):
            n0 = r.get("note") or "?"
            fail_notes[n0] = fail_notes.get(n0, 0) + 1

    stage_gender(leads)

    # 汇总统计
    n = len(leads)
    gender_dist: dict[str, int] = {}
    for ld in leads:
        gender_dist[ld.get("gender", "unknown")] = \
            gender_dist.get(ld.get("gender", "unknown"), 0) + 1

    print("\n========== 验证结果 ==========")
    print(f"profile 采集      : {len(profiles)} 条（有效姓名 {n}）")
    print(f"位置可解析        : {parsed}/{n}")
    print(f"skip-trace 返回   : {len(trace_items)} 条记录 / {len(by_input)} 个输入")
    print(f"查到人            : {n_matched}/{len(by_input)} 个输入")
    print(f"查到人且带电话    : {n_with_phone}/{len(by_input)}"
          f"（人均命中率 {n_with_phone / max(len(by_input), 1) * 100:.0f}%）")
    if fail_notes:
        print(f"失败原因分布      : {fail_notes}")
    print(f"性别分布          : {gender_dist}")
    print(f"Apify 官方计费    : 搜人 ${cost1} + 查号 ${cost2} = ${total_cost}")
    if n_with_phone:
        print(f"单个带号线索成本  : ${total_cost / n_with_phone:.3f}")

    out = {
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "params": vars(args),
        "cost_usd": {"search": cost1, "trace": cost2, "total": total_cost},
        "leads": leads,
        "trace_raw": trace_items,
    }
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"明细已写 {args.out}")


if __name__ == "__main__":
    main()
