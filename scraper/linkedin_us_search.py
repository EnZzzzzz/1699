# -*- coding: utf-8 -*-
"""linkedin_us_search.py — 领英美国高净值人群采号常驻管线（目标：500 个 WA 已注册美国号）。

管线（2026-08-24 调研结论，docs/linkedin-hnw-research.md）：
  ① harvestapi~linkedin-profile-search  按 (美国大都会, 职位) 组合搜人
    （Full 模式 $4/千条 + 搜索页 $0.1/25 条）；
  ② apivault_labs~skip-trace-people-finder  按「姓名; 城市, 州缩写」查美国
    手机号/地址（$6.5/千条命中记录，查不到不收费，每批 50、max_results=3）；
  ③ 州级验证：trace 记录地址（currentAddress+previousAddresses）与领英州一致
    才采纳号码（同名错人严重，宁可漏不可错）；
  ④ SSA 官方名字-性别离线数据集推断性别（领英无性别字段）；
  ⑤ devscrapper~whatsapp-number-validator 查 WA 注册态回写 us_contacts
    （$0.004/号估算计入预算）。

表（本脚本自建，CREATE TABLE IF NOT EXISTS，不走 platform migrate）：
  us_leads    — 搜人去重 + 查号进度（linkedin_url 唯一）
  us_contacts — 号码表（number 唯一，归一化 11 位 1XXXXXXXXXX；
                wa_source/wa_registered 三态语义同 fb_contacts）

停止条件：us_contacts wa_registered=1 总数 >= --target(500) 退出 0；
          state.cost_usd >= --max-budget(80) 退出并注明；组合搜完退出提示加词。

已知约束：
  - 与 wa_check_apify 常驻循环共享 devscrapper actor 2 run/分钟限流，
    两边都靠「限流退避 70s 重试 + 批间 sleep 35s」共存，不要加快节奏；
  - 同名错人只做州级过滤，号码仍是历史号码包（不区分手机/座机），
    WA 注册态天然筛掉座机/死号；
  - 402/403 欠费记 providers.quota_exhausted_at 并轮换账号（30 天账期跳过）；
    全部耗尽只跳过本轮付费阶段，下轮再试，不把常驻循环打死；
  - 搜人 run_id 先记 state.inflight 再轮询，中断重启复用该 run 续跑不重复扣费。

用法：
    python3 scraper/linkedin_us_search.py                 # 常驻循环
    python3 scraper/linkedin_us_search.py --limit 20 --max-budget 3 --interval 0  # 单轮冒烟
    python3 scraper/linkedin_us_search.py --dry-run       # 只搜人，不查号不 WA
    python3 scraper/linkedin_us_search.py --selftest      # 离线自测（不调 Apify）
    python3 scraper/linkedin_us_search.py --stats         # 只读打印两表汇总后退出
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
import zipfile
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / ".cache" / "1688.db"
STATE_PATH = REPO_ROOT / ".cache" / "linkedin_us_search_state.json"
TEST_JSON = REPO_ROOT / ".cache" / "linkedin_hnw_test.json"
SSA_DIR = REPO_ROOT / ".cache" / "ssa_names"
SSA_CACHE = REPO_ROOT / ".cache" / "ssa_gender.json"
SSA_URL = "https://www.ssa.gov/oact/babynames/names.zip"
API = "https://api.apify.com/v2"

ACTOR_SEARCH = "harvestapi~linkedin-profile-search"
ACTOR_TRACE = "apivault_labs~skip-trace-people-finder"
ACTOR_WA = "devscrapper~whatsapp-number-validator"

WA_PRICE_PER_NUMBER = 0.004  # devscrapper 单价，估算计入 state.cost_usd

# 高净值代理职位（领英没有财富字段，用职位近似；与调研口径一致）
DEFAULT_TITLES = ["CEO", "Founder", "Owner", "President", "Managing Partner"]

# 美国大都会/大城市（搜人 locations 入参，约 30 个；与职位叉乘出 ~150 个组合）
DEFAULT_LOCATIONS = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
    "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose",
    "San Francisco", "Seattle", "Boston", "Miami", "Atlanta",
    "Denver", "Washington DC", "Austin", "Las Vegas", "Minneapolis",
    "Tampa", "Charlotte", "Nashville", "Portland", "Salt Lake City",
    "Raleigh", "Columbus", "Indianapolis", "Detroit", "Baltimore",
]

# 领英常见大都会区写法 → 「城市, 州」（复制自 util/_test_linkedin_hnw.py，不改逻辑）
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
ABBR2NAME = {v: k for k, v in US_STATES.items()}


class QuotaExhausted(Exception):
    """Apify 402/403 欠费/无权限；由调用方记 quota_exhausted_at 并轮换账号。"""


class AllAccountsExhausted(Exception):
    """全部 apify 账号额度耗尽；本轮付费阶段退出，下轮再试（不杀常驻循环）。"""


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------- state 文件 ----------

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"state 文件损坏，重置（{e}）")
    return {"searched_combos": [], "inflight": None, "cost_usd": 0.0,
            "totals": {"profiles": 0, "leads_new": 0, "traced": 0,
                       "verified": 0, "numbers": 0,
                       "wa_checked": 0, "wa_registered": 0}}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


# ---------- 数据库 ----------

def connect_db(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    else:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    """两张新表幂等自建（平台侧暂无页面读它们，不走 server migrate）。"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS us_leads (
      id INTEGER PRIMARY KEY,
      linkedin_url TEXT NOT NULL UNIQUE,
      name TEXT, headline TEXT, company TEXT,
      location_raw TEXT, city_state TEXT,
      gender TEXT,
      age INTEGER,
      traced INTEGER NOT NULL DEFAULT 0,
      trace_matched INTEGER,
      state_verified INTEGER,
      first_seen_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS us_contacts (
      id INTEGER PRIMARY KEY,
      number TEXT NOT NULL UNIQUE,
      lead_id INTEGER NOT NULL REFERENCES us_leads(id),
      wa_source TEXT,
      wa_registered INTEGER,
      wa_checked_at TEXT,
      first_seen_at TEXT NOT NULL
    );
    """)
    # 2026-08-25 补 age 列（老库防御性 ALTER，与 server migrate 同语义）
    cols = {r[1] for r in conn.execute("PRAGMA table_info(us_leads)")}
    if cols and "age" not in cols:
        conn.execute("ALTER TABLE us_leads ADD COLUMN age INTEGER")
    conn.commit()


# ---------- apify 账号轮换（复制适配自 scraper/wa_check_apify.py）----------

# 月额度账期约 30 天：quota_exhausted_at 距今不足 30 天视为仍欠费
QUOTA_CYCLE_DAYS = 30


def _ensure_quota_col(conn: sqlite3.Connection) -> None:
    """防御性探测：老库可能没跑过 server 迁移，缺列就现场补（幂等）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(providers)")}
    if "quota_exhausted_at" not in cols:
        conn.execute("ALTER TABLE providers ADD COLUMN quota_exhausted_at TEXT")
        conn.commit()


def load_accounts(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """有额度的启用账号 [(id, name, token)]（新的在前），402/403 欠费时按序轮换。
    quota_exhausted_at 在 30 天账期内的账号跳过并提示预计恢复日期。
    与 wa_check_apify 的差异：没有可用账号时返回 [] 由调用方跳过本轮，
    不 sys.exit（常驻循环不能被打死）。"""
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
    return accounts


def mark_exhausted(conn: sqlite3.Connection, pid: int, name: str) -> None:
    """记录额度耗尽时间（北京时间），恢复日 ≈ +30 天账期。"""
    ts = now_str()
    recover = time.strftime("%Y-%m-%d", time.localtime(
        time.time() + QUOTA_CYCLE_DAYS * 86400))
    conn.execute("UPDATE providers SET quota_exhausted_at=? WHERE id=?",
                 (ts, pid))
    conn.commit()
    log(f"{name} 额度耗尽，已记录 {ts}，预计 {recover} 恢复")


# ---------- apify 异步 run（复制自 util/_test_linkedin_hnw.py）----------
# 与原版的差异：402/403 改抛 QuotaExhausted、超时/失败改抛 RuntimeError，
# 由常驻循环捕获后轮换账号/结束本轮，不 sys.exit。

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
                raise QuotaExhausted(f"Apify {e.code} 欠费/无权限：{detail}") from e
            raise RuntimeError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            last_err = e
            time.sleep(3)
    raise RuntimeError(f"网络错误重试 3 次仍失败: {last_err}")


def run_actor(token: str, actor: str, payload: dict,
              poll_interval: int = 10, max_wait: int = 1800,
              resume_run_id: str | None = None,
              on_started=None) -> tuple[list, dict]:
    """异步跑 actor 并轮询到结束，返回 (dataset items, run 对象)。

    resume_run_id：复用已启动的 run（脚本中断后不重跑扣费，直接挂回去等结果）。
    on_started：新 run 启动后回调（调用方立刻把 run_id 记进 state 再轮询）。"""
    if resume_run_id:
        run_id = resume_run_id
        log(f"  复用已有 run {run_id}，等待完成…")
    else:
        run = http_json("POST", f"{API}/acts/{actor}/runs?token={token}", payload)
        run_id = run["data"]["id"]
        log(f"  run {run_id} 已启动，等待完成…")
        if on_started:
            on_started(run_id)
    deadline = time.time() + max_wait
    while True:
        time.sleep(poll_interval)
        info = http_json("GET", f"{API}/actor-runs/{run_id}?token={token}")["data"]
        status = info["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        if time.time() > deadline:
            raise RuntimeError(f"run {run_id} 超时未结束（status={status}）")
    cost = info.get("usageTotalUsd")
    log(f"  run 结束：{status}，官方计费 ${cost}")
    if status != "SUCCEEDED":
        raise RuntimeError(f"actor 运行失败（{status}），去 Apify 控制台看 run {run_id}")
    items = http_json(
        "GET",
        f"{API}/actor-runs/{run_id}/dataset/items?token={token}&clean=true")
    return items, info


def run_actor_rotated(conn: sqlite3.Connection,
                      accounts: list[tuple[int, str, str]],
                      actor: str, payload: dict,
                      resume_run_id: str | None = None,
                      on_started=None, **kw) -> tuple[list, dict]:
    """带账号轮换的 run_actor：402/403 记 exhausted 换下一个账号；
    续跑时 run 归属账号未知，逐个账号试（404 换下一个）。"""
    last_err: Exception | None = None
    for pid, name, token in accounts:
        try:
            return run_actor(token, actor, payload,
                             resume_run_id=resume_run_id,
                             on_started=on_started, **kw)
        except QuotaExhausted:
            mark_exhausted(conn, pid, name)
            last_err = QuotaExhausted(f"{name} 欠费")
            continue
        except RuntimeError as e:
            # 续跑的 run 不属于本账号（404）时换账号再试；新起的 run 404 同理无害
            if resume_run_id and "404" in str(e):
                last_err = e
                continue
            raise
    raise AllAccountsExhausted(f"全部 apify 账号不可用：{last_err}")


# ---------- WA 查号（复制适配自 scraper/wa_check_apify.py）----------
# 注意：与 wa_check_apify 常驻循环共享 devscrapper actor 2 run/分钟限流，
# 两边都靠限流退避重试共存，批间固定 sleep 35s，不要加快。

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


def wa_run_actor(conn: sqlite3.Connection,
                 accounts: list[tuple[int, str, str]],
                 numbers: list[str], timeout: int = 600) -> list[dict]:
    """同步调 devscrapper actor，返回 [{"phone","exists","status",...}...]。

    actor 限制 2 次/分钟（超限 run 直接 FAILED，API 返回 400），
    遇到限流按提示秒数退避重试；402/403 欠费记录耗尽时间并换下一个账号。
    与 wa_check_apify 的差异：全部耗尽抛 AllAccountsExhausted 由本轮跳过。"""
    body = json.dumps({"phoneNumbers": numbers}).encode()
    ti = 0
    for attempt in range(6 + len(accounts)):
        pid, name, token = accounts[ti]
        url = (f"{API}/acts/{ACTOR_WA}/run-sync-get-dataset-items"
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
                raise AllAccountsExhausted("全部 apify 账号额度耗尽") from e
            # 400 体里只有 run ID，限流原因要查 run 的 statusMessage
            if e.code in (400, 429):
                if _is_rate_limited(token, detail):
                    wait = 70
                    log(f"actor 限流（2 次/分钟），退避 {wait}s 后重试…")
                    time.sleep(wait)
                    continue
                # 非限流 400（多为 run FAILED：actor 崩溃/内存等瞬时原因），
                # 记录详情并重试，仍失败才抛出（由调用方按批跳过）
                log(f"actor 400 非限流（第{attempt + 1}次）：{detail[:300]}")
                if attempt < 2:
                    time.sleep(30)
                    continue
            raise
    raise RuntimeError("actor 持续限流/欠费，重试仍失败")


# ---------- ① 搜人（解析函数复制自 util/_test_linkedin_hnw.py，不改逻辑） ----------

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


def extract_company(item: dict) -> str:
    """公司名防御性探测（与测试脚本 main 里的口径一致）。"""
    return (item.get("companyName")
            or ((item.get("currentPosition") or [{}])[0].get("companyName"))
            or ((item.get("experience") or [{}])[0].get("companyName"))
            or "")


def parse_lead(item: dict) -> dict | None:
    """profile → lead 字段；无姓名/无 linkedin_url 的丢弃。"""
    name = full_name(item)
    url = item.get("linkedinUrl") or item.get("url") or ""
    if not name or not url:
        return None
    loc = pick_location(item)
    return {
        "name": name,
        "headline": item.get("headline") or "",
        "linkedin_url": url,
        "location_raw": loc,
        "city_state": parse_us_city_state(loc),
        "company": extract_company(item),
    }


# ---------- ③ 州级验证 + 号码归一化 ----------

def state_match(text: str, abbr: str) -> bool:
    """地址文本是否提到该州（词边界正则，宁可漏不可错）。

    - 州全名：\\b 忽略大小写（地址里多为全名，如 'Spring Hill, Tennessee, 37174'）；
    - 州缩写：两字母极易误命中（如 '875 NE 48Th St' 的 NE 是 Northeast），
      仅接受 ①大写 \\bXX\\b（地址里州缩写惯例大写，如 'Odessa, FL, 33556'），
      ②小写缩写后紧跟逗号/zip（如 'clermont, fl 34711'）。"""
    name = ABBR2NAME.get(abbr, "")
    if name and re.search(r"\b" + re.escape(name) + r"\b", text, re.I):
        return True
    if re.search(r"\b" + abbr + r"\b", text):
        return True
    if re.search(r"\b" + abbr.lower() + r"\b(?=\s*,?\s*\d{5})", text):
        return True
    return False


def _record_addr_text(rec: dict) -> str:
    """currentAddress + previousAddresses 拼成一段文本。"""
    return "; ".join(x for x in (rec.get("currentAddress"),
                                 rec.get("previousAddresses")) if x)


def normalize_us_number(raw: str) -> str | None:
    """美国号归一化：去非数字；10 位补 '1'；11 位且 '1' 开头直收；其他丢弃。"""
    d = re.sub(r"\D+", "", raw or "")
    if len(d) == 10:
        return "1" + d
    if len(d) == 11 and d.startswith("1"):
        return d
    return None


def extract_phones(rec: dict) -> list[str]:
    """从一条 trace 记录取出全部归一化号码（phones 字段有 str/list 两种形态，
    str 为 '; ' 分隔；实测 list 形态只出现空列表，防御性兼容）。"""
    ph = rec.get("phones")
    raw = ph if isinstance(ph, list) else re.split(r"[;]", ph or "")
    out = []
    for p in raw:
        n = normalize_us_number(str(p))
        if n:
            out.append(n)
    return out


def verify_lead(records: list[dict], city_state: str
                ) -> tuple[bool, list[str], dict | None]:
    """州级验证，返回 (是否通过, 采纳的号码列表, 采纳的 trace 记录)。

    通过口径（lead 级）：该 lead 的 trace 记录里 ①任一 success 记录地址文本
    命中 lead 州（说明人对得上），且 ②至少有一条带号记录（无号可采的标 0，
    对管线无意义）。号码采纳口径更严（记录级）：只取「州命中且带号」的
    第一条记录的 phones——州不匹配记录里的号是同名错人/亲属的，不收。
    （100 条小样此口径通过 37 条，其中 33 条采到号；调研口径 39。）"""
    abbr = city_state.rsplit(",", 1)[-1].strip()
    succ = [r for r in records if isinstance(r, dict) and r.get("success")]
    any_match = any(state_match(_record_addr_text(r), abbr)
                    for r in succ if _record_addr_text(r))
    any_phone = any(extract_phones(r) for r in succ)
    adopted_rec = None
    for r in succ:
        phones = extract_phones(r)
        if phones and state_match(_record_addr_text(r), abbr):
            adopted_rec = r
            break
    return (any_match and any_phone,
            extract_phones(adopted_rec) if adopted_rec else [],
            adopted_rec)


def extract_age(rec: dict | None) -> int | None:
    """从采纳的 trace 记录推断年龄：优先 age 字段，否则 born（出生年/完整
    日期）换算。数据经纪来源，本就约 39% 记录有值；sanity 区间 18~100。"""
    if not rec:
        return None
    try:
        age = int(str(rec.get("age") or "").strip())
        if 18 <= age <= 100:
            return age
    except ValueError:
        pass
    m = re.match(r"(\d{4})", str(rec.get("born") or "").strip())
    if m:
        age = int(time.strftime("%Y")) - int(m.group(1))
        if 18 <= age <= 100:
            return age
    return None


# ---------- ④ SSA 性别离线数据集 ----------

def ensure_ssa_cache(names_hint: list[str] | None = None) -> dict[str, str]:
    """返回 {小写 first name: 'male'/'female'} 缓存；没有就现场构建。

    首次运行下载 SSA 官方 names.zip 解压到 .cache/ssa_names/，汇总所有
    yob*.txt 按 first name 计数多数性别，缓存为 .cache/ssa_gender.json
    （一次构建永久复用）。下载/构建失败不阻塞：返回空表，调用方全 unknown。"""
    if SSA_CACHE.exists():
        try:
            return json.loads(SSA_CACHE.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"SSA 缓存损坏，重建（{e}）")
    try:
        if not SSA_DIR.exists() or not list(SSA_DIR.glob("yob*.txt")):
            log(f"下载 SSA 名字数据集 {SSA_URL} …")
            SSA_DIR.mkdir(parents=True, exist_ok=True)
            zip_path = SSA_DIR / "names.zip"
            req = urllib.request.Request(SSA_URL, headers={
                "User-Agent": "Mozilla/5.0 (compatible; keyword-research)"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                zip_path.write_bytes(resp.read())
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(SSA_DIR)
            zip_path.unlink()
        tally: dict[str, dict[str, int]] = defaultdict(
            lambda: {"F": 0, "M": 0})
        for f in SSA_DIR.glob("yob*.txt"):  # 每行 'Mary,F,7065'
            for line in f.read_text(encoding="utf-8").splitlines():
                parts = line.split(",")
                if len(parts) != 3:
                    continue
                name, sex, cnt = parts[0].strip().lower(), parts[1], parts[2]
                if sex in ("F", "M"):
                    tally[name][sex] += int(cnt)
        table = {n: ("female" if c["F"] >= c["M"] else "male")
                 for n, c in tally.items()}
        SSA_CACHE.write_text(json.dumps(table), encoding="utf-8")
        log(f"SSA 性别表构建完成：{len(table)} 个名字 → {SSA_CACHE}")
        return table
    except Exception as e:  # noqa: BLE001
        log(f"SSA 性别表构建失败（{type(e).__name__}: {e}），性别全部 unknown")
        return {}


def infer_gender(table: dict[str, str], name: str) -> str:
    """按 first name 查 SSA 表；查不到 'unknown'。"""
    if not table or not name:
        return "unknown"
    return table.get(name.split()[0].lower(), "unknown")


# ---------- 常驻循环各阶段 ----------

def next_combo(state: dict, locations: list[str], titles: list[str]
               ) -> list[str] | None:
    """按序取第一个未搜过的 (location, title) 组合；全部搜完返回 None。"""
    done = {tuple(c) for c in state.get("searched_combos", [])}
    for loc in locations:
        for t in titles:
            if (loc, t) not in done:
                return [loc, t]
    return None


def stage_search(conn: sqlite3.Connection, state: dict,
                 accounts: list[tuple[int, str, str]],
                 locations: list[str], titles: list[str],
                 limit: int, gender_table: dict[str, str]) -> str:
    """搜人阶段。返回 'ok' / 'done'（组合搜完）。欠费/失败抛异常由主循环结束本轮。"""
    inflight = state.get("inflight")
    if inflight and inflight.get("run_id"):
        combo = inflight["combo"]
        resume_run_id = inflight["run_id"]
        log(f"① 搜人：检测到中断的 run {resume_run_id}"
            f"（{combo[0]} / {combo[1]}），续跑不重复扣费")
    else:
        combo = next_combo(state, locations, titles)
        if not combo:
            return "done"
        resume_run_id = None
        log(f"① 搜人：{combo[0]} / 职位 {combo[1]} / 上限 {limit} 条（Full 模式）")

    payload = {
        "profileScraperMode": "Full",
        "locations": [combo[0]],
        "currentJobTitles": [combo[1]],
        "maxItems": limit,
        "takePages": max(1, -(-limit // 25)),  # 每页 25 条，封顶页数
    }

    def _on_started(run_id: str) -> None:
        # run_id 先记 state 再轮询：此时中断，重启复用该 run 续跑
        state["inflight"] = {"actor": ACTOR_SEARCH, "run_id": run_id,
                             "combo": combo}
        save_state(state)

    items, run = run_actor_rotated(
        conn, accounts, ACTOR_SEARCH, payload,
        resume_run_id=resume_run_id, on_started=_on_started)
    cost = run.get("usageTotalUsd") or 0.0
    log(f"  拿到 profile {len(items)} 条，官方计费 ${cost}")

    # 组合标记已搜 + 清 inflight（先落 state 再入库，重启不重复搜该组合）
    state["searched_combos"].append(combo)
    state["inflight"] = None
    state["cost_usd"] = round(state.get("cost_usd", 0.0) + cost, 4)
    state["totals"]["profiles"] += len(items)

    ts = now_str()
    n_new = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        ld = parse_lead(it)
        if not ld:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO us_leads"
            " (linkedin_url, name, headline, company, location_raw,"
            "  city_state, gender, first_seen_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (ld["linkedin_url"], ld["name"], ld["headline"], ld["company"],
             ld["location_raw"], ld["city_state"],
             infer_gender(gender_table, ld["name"]), ts))
        n_new += cur.rowcount
    conn.commit()
    state["totals"]["leads_new"] += n_new
    save_state(state)
    log(f"  新 lead 入库 {n_new} 条（累计 cost ${state['cost_usd']:.2f}）")
    return "ok"


def stage_trace(conn: sqlite3.Connection, state: dict,
                accounts: list[tuple[int, str, str]]) -> None:
    """查号 + 州级验证 + 号码入库。每批 50（actor 单 run 有时间预算，
    实测 99 条/批约 1/3 输入被 'not processed before run time budget' 截断）。"""
    rows = conn.execute(
        "SELECT id, name, city_state FROM us_leads"
        " WHERE traced=0 AND city_state IS NOT NULL ORDER BY id").fetchall()
    if not rows:
        log("② 查号：无待查 lead，跳过")
        return
    log(f"② 查号：{len(rows)} 个 lead 送 skip-trace（每批 50，每条最多 3 个匹配人）")
    for i in range(0, len(rows), 50):
        batch = rows[i:i + 50]
        log(f"  批次 {i // 50 + 1}：{len(batch)} 条")
        queries = [f"{name}; {cs}" for _, name, cs in batch]
        payload = {
            "name": queries,
            "max_results": 3,
            "source": "auto",
            "flatOutput": True,
            "verifyEmails": False,
        }
        items, run = run_actor_rotated(
            conn, accounts, ACTOR_TRACE, payload,
            poll_interval=15, max_wait=3600)
        cost = run.get("usageTotalUsd") or 0.0
        state["cost_usd"] = round(state.get("cost_usd", 0.0) + cost, 4)

        # 按输入姓名归组（一人最多 3 条匹配记录，记录数≠人数）
        by_name: dict[str, list] = defaultdict(list)
        for r in items:
            if isinstance(r, dict):
                q = (r.get("inputGiven") or "").split(";")[0].strip()
                by_name[q].append(r)

        ts = now_str()
        n_matched = n_verified = n_numbers = 0
        for lead_id, name, cs in batch:
            recs = by_name.get(name, [])
            matched = any(isinstance(r, dict) and r.get("success") for r in recs)
            if not matched:
                conn.execute(
                    "UPDATE us_leads SET traced=1, trace_matched=0 WHERE id=?",
                    (lead_id,))
                continue
            n_matched += 1
            verified, phones, adopted_rec = verify_lead(recs, cs)
            if verified:
                n_verified += 1
                for num in phones:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO us_contacts"
                        " (number, lead_id, first_seen_at) VALUES (?,?,?)",
                        (num, lead_id, ts))
                    n_numbers += cur.rowcount
            conn.execute(
                "UPDATE us_leads SET traced=1, trace_matched=1,"
                " state_verified=?, age=? WHERE id=?",
                (1 if verified else 0, extract_age(adopted_rec), lead_id))
        conn.commit()
        state["totals"]["traced"] += len(batch)
        state["totals"]["verified"] += n_verified
        state["totals"]["numbers"] += n_numbers
        save_state(state)
        log(f"  本批：查到人 {n_matched}/{len(batch)}，州级验证通过 {n_verified}，"
            f"新号码 {n_numbers}（官方计费 ${cost}，累计 ${state['cost_usd']:.2f}）")


def stage_wa(conn: sqlite3.Connection, state: dict,
             accounts: list[tuple[int, str, str]]) -> None:
    """WA 查号：取未查号每批 50 送 devscrapper actor，回写三态字段。
    回写语义与 wa_check_apify 一致：'checked'（注册 1/0）/ 'invalid'
    （运营商拒绝的号永远查不出，标记防重查浪费额度）。"""
    rows = conn.execute(
        "SELECT id, number FROM us_contacts"
        " WHERE wa_registered IS NULL AND wa_source IS NULL ORDER BY id"
    ).fetchall()
    if not rows:
        log("⑤ WA 查号：无待查号码，跳过")
        return
    log(f"⑤ WA 查号：{len(rows)} 个号，预估费用 "
        f"${len(rows) * WA_PRICE_PER_NUMBER:.3f}")
    batch = 50  # 实测 100 号/run 必现 run-failed，50 号稳定秒回
    t0 = time.time()
    tot = {"reg": 0, "not": 0, "err": 0, "inv": 0}
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        try:
            results = wa_run_actor(conn, accounts, [n for _, n in chunk])
        except AllAccountsExhausted:
            raise  # 欠费：整轮退出下轮再试
        except Exception as e:  # noqa: BLE001
            # 单批失败不中断整轮：跳过该块（未回写的号下轮自动补查）
            log(f"  第 {i // batch + 1} 批失败跳过（{type(e).__name__}: {e}），"
                f"下轮补查")
            time.sleep(60)
            continue
        # 估算费用入账（actor 同步调用拿不到 usageTotalUsd，按单价折算）
        state["cost_usd"] = round(
            state.get("cost_usd", 0.0) + len(chunk) * WA_PRICE_PER_NUMBER, 4)
        ts = now_str()
        by_phone = {}
        for r in results:
            p = re.sub(r"\D+", "", str(r.get("phone", "")))
            if p.startswith("00"):
                p = p[2:]
            by_phone[p] = r
        for row_id, number in chunk:
            r = by_phone.get(number)
            if not r:
                tot["err"] += 1
                continue
            if r.get("exists") is None:
                if r.get("status") == "invalid":
                    conn.execute(
                        "UPDATE us_contacts SET wa_checked_at=?,"
                        " wa_source='invalid' WHERE id=?", (ts, row_id))
                    tot["inv"] += 1
                else:
                    tot["err"] += 1
                continue
            reg = 1 if r["exists"] else 0
            conn.execute(
                "UPDATE us_contacts SET wa_registered=?, wa_checked_at=?,"
                " wa_source='checked' WHERE id=?", (reg, ts, row_id))
            tot["reg"] += reg
            tot["not"] += (1 - reg)
        conn.commit()
        save_state(state)
        log(f"  已查 {min(i + batch, len(rows))}/{len(rows)}"
            f"（{time.time() - t0:.0f}s，已注册 {tot['reg']}）")
        if i + batch < len(rows):
            time.sleep(35)  # 2 run/分钟节奏
    # tot 是整轮累计值，只能在循环结束后入账一次（此前在批内 += 会重复累计）
    state["totals"]["wa_checked"] += tot["reg"] + tot["not"]
    state["totals"]["wa_registered"] += tot["reg"]
    save_state(state)
    log(f"  WA 回写：已注册 {tot['reg']}，未注册 {tot['not']}，"
        f"无效号 {tot['inv']}，查询失败 {tot['err']}")


# ---------- 离线自测（不调任何 Apify API） ----------

def selftest() -> int:
    """用 .cache/linkedin_hnw_test.json（100 条真实样本）跑全流程纯函数：
    lead 解析入库去重、trace 按 inputGiven 分号前姓名归组、州级验证、
    号码归一化入 us_contacts、SSA 性别。断言州级验证通过数在 35~45
    （调研口径 39）。sqlite3 :memory: 建表，不落盘。"""
    log("加载测试样本 .cache/linkedin_hnw_test.json …")
    data = json.loads(TEST_JSON.read_text(encoding="utf-8"))
    leads, trace_raw = data["leads"], data["trace_raw"]

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA busy_timeout=30000")
    create_tables(conn)

    # ① lead 解析入库（按 linkedin_url 去重；样本已是解析后的字段，直接入）
    ts = now_str()
    n_leads = 0
    for ld in leads:
        cur = conn.execute(
            "INSERT OR IGNORE INTO us_leads"
            " (linkedin_url, name, headline, company, location_raw,"
            "  city_state, first_seen_at) VALUES (?,?,?,?,?,?,?)",
            (ld["linkedin_url"], ld["name"], ld["headline"], ld["company"],
             ld["location_raw"], ld["city_state"], ts))
        n_leads += cur.rowcount
    conn.commit()
    n_dup = len(leads) - n_leads

    # ② trace 归组：inputGiven 分号前姓名匹配 lead.name
    by_name: dict[str, list] = defaultdict(list)
    for r in trace_raw:
        if isinstance(r, dict):
            by_name[(r.get("inputGiven") or "").split(";")[0].strip()].append(r)

    # ③ 州级验证 + ④ 号码归一化入 us_contacts
    n_matched = n_verified = n_with_phones = n_numbers = 0
    lead_ids = {}
    for row_id, name, cs in conn.execute(
            "SELECT id, name, city_state FROM us_leads").fetchall():
        lead_ids[name] = row_id
        recs = by_name.get(name, [])
        matched = any(isinstance(r, dict) and r.get("success") for r in recs)
        conn.execute(
            "UPDATE us_leads SET traced=1, trace_matched=? WHERE id=?",
            (1 if matched else 0, row_id))
        if not matched:
            continue
        n_matched += 1
        if not cs:
            conn.execute(
                "UPDATE us_leads SET state_verified=0 WHERE id=?", (row_id,))
            continue
        verified, phones, adopted_rec = verify_lead(recs, cs)
        conn.execute(
            "UPDATE us_leads SET state_verified=?, age=? WHERE id=?",
            (1 if verified else 0, extract_age(adopted_rec), row_id))
        if not verified:
            continue
        n_verified += 1
        if phones:
            n_with_phones += 1
        for num in phones:
            cur = conn.execute(
                "INSERT OR IGNORE INTO us_contacts"
                " (number, lead_id, first_seen_at) VALUES (?,?,?)",
                (num, row_id, ts))
            n_numbers += cur.rowcount
    conn.commit()

    # ⑤ SSA 性别：缓存不存在则用样本 lead 的名字触发现场构建；
    # 构建失败（如 ssa.gov 拒连）不阻塞，跳过性别断言
    gender_table = ensure_ssa_cache([ld["name"] for ld in leads])
    genders = {"male": 0, "female": 0, "unknown": 0}
    for ld in leads:
        g = infer_gender(gender_table, ld["name"])
        assert g in genders, f"非法性别值 {g}"
        genders[g] += 1
        conn.execute("UPDATE us_leads SET gender=? WHERE id=?",
                     (g, lead_ids[ld["name"]]))
    conn.commit()

    n_contacts = conn.execute("SELECT COUNT(*) FROM us_contacts").fetchone()[0]
    bad_numbers = conn.execute(
        "SELECT COUNT(*) FROM us_contacts WHERE length(number)!=11"
        " OR number NOT LIKE '1%'").fetchone()[0]
    n_age = conn.execute(
        "SELECT COUNT(*) FROM us_leads WHERE age IS NOT NULL").fetchone()[0]

    print("\n========== selftest 结果 ==========")
    print(f"lead 入库           : {n_leads}（去重拦截 {n_dup}）")
    print(f"trace 归组          : {len(by_name)} 个输入 / {len(trace_raw)} 条记录")
    print(f"查到人              : {n_matched}/100")
    print(f"州级验证通过        : {n_verified}（其中采到号 {n_with_phones}）")
    print(f"号码入 us_contacts  : {n_numbers}（表内 {n_contacts} 行，"
          f"非标号码 {bad_numbers}）")
    print(f"性别分布            : {genders}"
          + ("" if gender_table else "（SSA 缓存构建失败，全部 unknown）"))
    print(f"年龄覆盖            : {n_age}/{n_verified}（采纳记录 age/born 推断）")

    # 断言
    assert n_leads == 100, f"lead 入库 {n_leads} != 100"
    assert n_matched >= 80, f"查到人 {n_matched} 异常偏低"
    assert 35 <= n_verified <= 45, \
        f"州级验证通过 {n_verified} 不在 35~45（调研口径 39）"
    assert n_numbers > 0 and bad_numbers == 0, "号码归一化异常"
    assert 5 <= n_age <= 25, \
        f"年龄覆盖 {n_age} 异常（小样实测 13，口径约 39% 的采纳记录有值）"
    if gender_table:
        assert genders["male"] + genders["female"] > 0, "SSA 性别全 unknown"
    print("断言全部通过 ✅")
    conn.close()
    return 0


# ---------- 只读统计 ----------

def show_stats() -> int:
    """--stats：只读打印 us_leads / us_contacts 汇总 + state 费用后退出。"""
    state = load_state()
    if not DB_PATH.exists():
        print("库不存在（尚未跑过正式管线）")
        print(f"state: 已搜组合 {len(state.get('searched_combos', []))}，"
              f"cost ${state.get('cost_usd', 0):.2f}")
        return 0
    conn = connect_db(readonly=True)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "us_leads" not in tables:
        print("us_leads / us_contacts 尚未建表（尚未跑过正式管线）")
        print(f"state: 已搜组合 {len(state.get('searched_combos', []))}，"
              f"cost ${state.get('cost_usd', 0):.2f}")
        conn.close()
        return 0

    def q1(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    print("========== us_leads ==========")
    print(f"总 lead        : {q1('SELECT COUNT(*) FROM us_leads')}")
    print(f"位置可解析     : {q1('SELECT COUNT(*) FROM us_leads WHERE city_state IS NOT NULL')}")
    print(f"已送查号       : {q1('SELECT COUNT(*) FROM us_leads WHERE traced=1')}")
    print(f"查到人         : {q1('SELECT COUNT(*) FROM us_leads WHERE trace_matched=1')}")
    print(f"州级验证通过   : {q1('SELECT COUNT(*) FROM us_leads WHERE state_verified=1')}")
    print("性别分布       : " + ", ".join(
        f"{g or 'null'}={n}" for g, n in conn.execute(
            "SELECT gender, COUNT(*) FROM us_leads GROUP BY gender")))
    n_v = q1('SELECT COUNT(*) FROM us_leads WHERE state_verified=1')
    n_a = q1('SELECT COUNT(*) FROM us_leads WHERE age IS NOT NULL')
    print(f"年龄覆盖       : {n_a}/{n_v}（州级验证通过中推断出年龄的条数）")
    print("========== us_contacts ==========")
    print(f"总号码         : {q1('SELECT COUNT(*) FROM us_contacts')}")
    print(f"WA 已注册      : {q1('SELECT COUNT(*) FROM us_contacts WHERE wa_registered=1')}")
    print(f"WA 未注册      : {q1('SELECT COUNT(*) FROM us_contacts WHERE wa_registered=0')}")
    n_pending = q1("SELECT COUNT(*) FROM us_contacts WHERE wa_registered IS NULL")
    n_invalid = q1("SELECT COUNT(*) FROM us_contacts WHERE wa_source='invalid'")
    print(f"待审核         : {n_pending}（其中无效号 {n_invalid}）")
    print("========== state ==========")
    print(f"已搜组合       : {len(state.get('searched_combos', []))}")
    print(f"inflight       : {state.get('inflight')}")
    print(f"累计费用       : ${state.get('cost_usd', 0):.2f}")
    print(f"totals         : {state.get('totals')}")
    conn.close()
    return 0


# ---------- 主流程 ----------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="领英美国高净值人群采号常驻管线")
    ap.add_argument("--target", type=int, default=500,
                    help="停止目标：us_contacts WA 已注册号达到此数退出（缺省 500）")
    ap.add_argument("--max-budget", type=float, default=80,
                    help="预算刹车：state 累计费用达到此值（美元）退出（缺省 80）")
    ap.add_argument("--interval", type=int, default=300,
                    help="每轮间隔秒数；0 = 只跑一轮就退出（冒烟用，缺省 300）")
    ap.add_argument("--limit", type=int, default=100,
                    help="单轮搜人上限 maxItems（缺省 100，冒烟可调小）")
    ap.add_argument("--titles", default=",".join(DEFAULT_TITLES),
                    help="逗号分隔职位列表，覆盖默认 5 个")
    ap.add_argument("--locations", default=",".join(DEFAULT_LOCATIONS),
                    help="逗号分隔地点列表，覆盖默认 30 个")
    ap.add_argument("--dry-run", action="store_true",
                    help="只搜人，不查号不 WA（搜人本身计费，慎用）")
    ap.add_argument("--selftest", action="store_true",
                    help="离线自测（读 .cache/linkedin_hnw_test.json，不调 Apify）")
    ap.add_argument("--stats", action="store_true",
                    help="只读打印两表汇总后退出")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.stats:
        return show_stats()

    titles = [t.strip() for t in args.titles.split(",") if t.strip()]
    locations = [t.strip() for t in args.locations.split(",") if t.strip()]
    total_combos = len(titles) * len(locations)

    conn = connect_db()
    create_tables(conn)
    state = load_state()
    gender_table = ensure_ssa_cache()
    log(f"启动：target={args.target} max_budget=${args.max_budget}"
        f" interval={args.interval}s 组合 {len(locations)}地点×{len(titles)}职位"
        f"={total_combos} 个，已搜 {len(state.get('searched_combos', []))}，"
        f"累计费用 ${state.get('cost_usd', 0):.2f}")

    while True:
        # 停止判定（每轮开头先查）
        registered = conn.execute(
            "SELECT COUNT(*) FROM us_contacts WHERE wa_registered=1"
        ).fetchone()[0]
        if registered >= args.target:
            log(f"🎉 目标达成：WA 已注册 {registered} >= {args.target}，"
                f"总费用 ${state.get('cost_usd', 0):.2f}，退出")
            conn.close()
            return 0
        if state.get("cost_usd", 0.0) >= args.max_budget:
            log(f"预算刹车：累计费用 ${state['cost_usd']:.2f}"
                f" >= --max-budget {args.max_budget}，退出"
                f"（WA 已注册 {registered}/{args.target}）")
            conn.close()
            return 3

        accounts = load_accounts(conn)
        if not accounts:
            log("没有可用额度的 apify 账号，本轮付费阶段全部跳过，下轮再试")
        else:
            try:
                r = stage_search(conn, state, accounts, locations, titles,
                                 args.limit, gender_table)
                if r == "done":
                    log(f"全部 {total_combos} 个 (地点, 职位) 组合已搜完，"
                        f"请加 --locations/--titles 新词后重启；"
                        f"WA 已注册 {registered}/{args.target}，退出")
                    conn.close()
                    return 0
                if args.dry_run:
                    log("--dry-run：跳过查号与 WA 阶段")
                else:
                    stage_trace(conn, state, accounts)
                    stage_wa(conn, state, accounts)
            except AllAccountsExhausted as e:
                # 欠费：本轮退出下轮重试，不把常驻循环打死
                log(f"本轮付费阶段因欠费退出（{e}），下轮再试")
            except (QuotaExhausted, RuntimeError) as e:
                log(f"本轮异常退出（{type(e).__name__}: {e}），下轮重试")

        if args.interval <= 0:
            log("--interval 0：单轮结束退出")
            conn.close()
            return 0
        log(f"本轮结束，sleep {args.interval}s 后下一轮…")
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
