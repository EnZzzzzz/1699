#!/usr/bin/env python3
# X(Twitter) 关键词直搜采号常驻脚本：xquik/x-tweet-scraper（Apify）单源。
"""X 关键词直搜采号（常驻，「牧场」模型，2026-08-22 重写）。

老版（回扫/增量双模式、自适应切窗）已废弃删除——历史回扫烧预算采一堆
早就被泛词采过的旧帖，性价比极低。新版策略极简，所有词一视同仁：

  每个词到期（距上次采集 ≥ SCAN_INTERVAL_DAYS 天，默认 3 天）就开一次
  采集会话：先刺探最新 PROBE_ITEMS(50) 帖（Latest 排序）：
  - 首批 50 帖挖到新号 → 按 until_time 往历史翻页续挖（每批 50），
    直到某批新号 +0 / 帖空 / 批数到顶 MAX_BATCHES_PER_WORD(20) 才换词；
  - 整会话一个新号都没有 → 连击 +1；
  - 连续 RETIRE_STRIKES(3) 次会话无新号（≈9 天没长出新帖）→ 判枯竭
    退役，记 state.kw_retired 永久移出轮转（词库文件不动，留 3 天间隔
    就是给词「长新帖」的时间）。
  运营方式：持续往词库加验证过的新词（AGENTS.md 换词流程），之后全自动。

数据源：xquik/x-tweet-scraper（Apify，pay-per-result $0.15/千帖，免 X 登录）
→ 帖正文 parse_post 挖中国号 → 跨源查重（fb_contacts 已有号码跳过，
86 前缀/裸 11 位兼容）→ 落 fb_contacts。

落库说明：fb_contacts 无渠道 source 列，bucket 是 parse_post 按号码类型
分的（declared_wa/cn_uncertain/overseas），X 来源靠 post_url=推文链接标识。
跨源去重：number 列有 UNIQUE 约束（save_fb_contacts 走 INSERT OR IGNORE），
但 FB 侧同号可能存 86 前缀形态、X 侧解析成裸 11 位（或反之），精确匹配
挡不住，故落库前先 SELECT 查重（后 11 位对齐），命中即跳过。

成本量级：每词每次 ≤50 帖 ≈ $0.0075；276 词每 3 天一轮 ≈ 92 次/天，
顶格 ≈ $0.7/天。预算刹车：当日结果数到 --daily-results 即停（跨天自动
清零）；总预算 --total-budget-usd 耗尽即停机。
402/403 欠费按 wa_check_apify 口径记 quota_exhausted_at 并轮换账号。

状态文件 .cache/x_keyword_search_state.json（与 FB 的 state 互相独立）：
  offset        轮转游标（取词起点，扫过的词 3 天内自然不再到期）
  daily         按北京日期的当日结果数（机器本地时区即北京）
  total_results / total_new  累计行数（总预算记账）/ 累计新号
  kw_stats      每词 q/posts/new/first_at/last_q_at/last_new_at/zero_streak
                （zero_streak=连续无新号次数，满 3 退役；kw_stats.py 报表用）
  kw_retired    已退役词 {词: {at, strikes, q}}；误判复活：删对应键即可
  （老版 kw_since/kw_backfill 键残留无害，不再读取）

用法：
  python3 scraper/x_keyword_search.py --once                 # 试跑一轮
  python3 scraper/x_keyword_search.py --keywords-file .cache/x_keywords_all.txt \
      --per-round 5 --interval 600 --delay 3 --daily-results 5000   # 常驻
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "fetcher"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetcher.sites.facebook.post import parse_post  # noqa: E402
from fb_group_bd import is_cn_number  # noqa: E402
from wa_check_apify import load_accounts, mark_exhausted  # noqa: E402

STATE_PATH = REPO_ROOT / ".cache" / "x_keyword_search_state.json"

# ---------------------------------------------------------------- 策略参数
SCAN_INTERVAL_SEC = 3 * 86400  # 每词最小采集间隔：给词 3 天长新帖
RETIRE_STRIKES = 3             # 连续 3 次（≈9 天）无新号 → 退役
PROBE_ITEMS = 50               # 每批取 50 帖：首批刺探，有新号就往历史翻页
MAX_BATCHES_PER_WORD = 20      # 单词单次会话最多 20 批（≈1000 帖 ≈ $0.15 封顶）

# ---------------------------------------------------------------- X 专属词库
# 内置关键词库（2026-08-18 全量实测策展版）：经 WebBridge 真实浏览器逐词
# 验证（X 搜索 Latest），只保留实测含中国号的 73 词 + wa.me 86（号码藏
# wa.me 短链，parse_post 可从 URL 提号）。实测数据
# docs/channel-research/kw-verify-2026-08-18/x_*.jsonl + x_retest.jsonl
X_KEYWORDS: list[str] = [
    "wa.me 86", "whatsapp +86 furniture", "whatsapp +86 wholesale",
    "whatsapp factory gym equipment", "whatsapp wholesale phone cases", "whatsapp 0086",
    "wechat factory", "whatsapp wechat supplier", "whatsapp +86 factory",
    "whatsapp +86 shoes", "whatsapp +86 bags", "whatsapp +86 toys",
    "whatsapp +86 cosmetics", "wechat supplier furniture", "whatsapp carpet factory",
    "whatsapp artificial flowers supplier", "wechat +86", "wechat 86",
    "tel wechat whatsapp", "oem available whatsapp", "whatsapp manufacturer",
    "whatsapp china supplier", "whatsapp factory LED", "whatsapp china machinery",
    "pm whatsapp wholesale", "wechat wholesale", "wechat manufacturer",
    "whatsapp +86 supplier", "whatsapp +86 hair", "whatsapp +86 clothing",
    "wechat supplier shoes", "wechat supplier bags", "factory direct whatsapp",
    "oem whatsapp", "fob whatsapp", "guangzhou whatsapp",
    "in stock whatsapp +86", "whatsapp wechat +86", "whatsapp china factory",
    "whatsapp supplier shoes", "whatsapp supplier jewelry", "whatsapp supplier furniture",
    "whatsapp supplier toys", "whatsapp wholesale shoes", "whatsapp wholesale hair",
    "whatsapp +86", "whatsapp group wholesale", "whatsapp wechat",
    "whatsapp +86 electronics", "whatsapp +86 solar", "wechat supplier electronics",
    "whatsapp remote control factory", "factory price whatsapp", "whatsapp +86 1",
    "china wholesale whatsapp", "whatsapp factory", "whatsapp wholesale",
    "whatsapp wholesale supplier", "whatsapp factory bags", "whatsapp factory jewelry",
    "whatsapp factory pet supplies", "whatsapp wholesale clothing", "whatsapp china toys",
    "whatsapp china wigs", "whatsapp china auto parts", "add whatsapp supplier",
    "wechat supplier", "whatsapp mayorista china whatsapp", "whatsapp vendor bags",
    "whatsapp vendor LED", "wechat supplier hair", "wechat supplier clothing",
    "whatsapp artificial flowers factory", "odm whatsapp",
]

# ---- xquik/x-tweet-scraper（Apify）----
X_ACTOR = "xquik~x-tweet-scraper"
APIFY_API = "https://api.apify.com/v2"
X_COST_PER_RESULT = 0.00015  # $0.15/千帖，按交付行计费（重复帖 actor 侧已去重）
RUN_POLL_SECS = 10
RUN_TIMEOUT_SECS = 120  # 50 帖刺探正常 20 秒内返回，超 2 分钟基本是死 run，早掐早重试


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class AccountError(Exception):
    """账号级错误（Apify 全部耗尽），整轮中止信号。"""


# ---------------------------------------------------------------- 状态文件

def load_state() -> dict:
    """读 state JSON，缺键补默认值；老版残留键（kw_since/kw_backfill）
    原样保留但不读取。一次性迁移：旧连击是高频扫描时代累计的，与现行
    3 天 cadence 语义不同，首次加载清零 zero_streak（probe_v2 旗标）。"""
    st: dict = {}
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text())
        except Exception:
            st = {}
    st.setdefault("offset", 0)
    st.setdefault("daily", {})
    st.setdefault("total_results", 0)
    st.setdefault("total_new", 0)
    st.setdefault("kw_stats", {})
    st.setdefault("kw_retired", {})
    if not st.get("probe_v2"):
        for s in st["kw_stats"].values():
            s["zero_streak"] = 0
        st["probe_v2"] = True
    return st


def record_kw_stat(st: dict, kw: str, n_posts: int, n_new: int) -> None:
    """每词每次采集后记账：累计查询/帖/新号，维护 last_new_at 与连击
    （zero_streak=连续无新号次数）；连击满 RETIRE_STRIKES 移入
    kw_retired 退出轮转。时间戳为北京时间字符串。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    s = st["kw_stats"].setdefault(kw, {"q": 0, "posts": 0, "new": 0,
                                       "first_at": now, "last_q_at": None,
                                       "last_new_at": None, "zero_streak": 0})
    s["q"] += 1
    s["posts"] += n_posts
    s["new"] += n_new
    s["last_q_at"] = now
    if n_new > 0:
        s["last_new_at"] = now
        s["zero_streak"] = 0
        return
    s["zero_streak"] += 1
    retired = st.setdefault("kw_retired", {})
    if s["zero_streak"] >= RETIRE_STRIKES and kw not in retired:
        retired[kw] = {"at": now, "strikes": s["zero_streak"], "q": s["q"]}
        log(f"  ☠「{kw}」连续 {s['zero_streak']} 次无新号"
            f"（≈{s['zero_streak'] * SCAN_INTERVAL_SEC // 86400} 天无产出），"
            f"判定枯竭退役，移出轮转")


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=1))


def today_usage(st: dict) -> dict:
    day = time.strftime("%Y-%m-%d")
    return st["daily"].setdefault(day, {"x_results": 0})


# ---------------------------------------------------------------- xquik 搜索

def x_search(conn, accounts: list, kw: str,
             max_items: int) -> list[dict] | None:
    """异步 run + 轮询跑一个查询词（Latest 排序），返回 dataset items。
    kw 原样透传（可带 X 高级搜索语法）。402/403 欠费记 quota_exhausted_at
    并从 accounts 就地移除后换号重试；run 超时/FAILED 重试且 maxItems
    逐次减半保底。仍失败返回 None，调用方不记账、该词下轮仍是到期状态。"""
    mi = max_items
    for attempt in range(3):
        body = json.dumps({"searchTerms": [kw], "maxItems": mi,
                           "queryType": "Latest"}).encode()
        if not accounts:
            raise AccountError("全部 apify 账号额度耗尽")
        pid, name, token = accounts[0]
        try:
            req = urllib.request.Request(
                f"{APIFY_API}/acts/{X_ACTOR}/runs?token={token}",
                data=body, headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                run = json.loads(r.read().decode())["data"]
            run_id, ds_id = run["id"], run["defaultDatasetId"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code in (402, 403):  # 欠费/月硬顶：记耗尽换号
                mark_exhausted(conn, pid, name)
                accounts.pop(0)
                if accounts:
                    log(f"切换下一个 apify 账号：{accounts[0][1]}")
                continue
            log(f"  xquik 建 run 失败「{kw}」: HTTP {e.code} {detail}"
                f"（第{attempt + 1}/3次）")
            time.sleep(min(2 ** attempt * 5, 20))
            continue
        except Exception as e:  # noqa: BLE001
            log(f"  xquik 建 run 异常「{kw}」（第{attempt + 1}/3次）: {e}")
            time.sleep(min(2 ** attempt * 5, 20))
            continue

        deadline = time.time() + RUN_TIMEOUT_SECS
        status = "RUNNING"
        while time.time() < deadline:
            time.sleep(RUN_POLL_SECS)
            try:
                with urllib.request.urlopen(
                        f"{APIFY_API}/actor-runs/{run_id}?token={token}",
                        timeout=30) as r:
                    status = json.loads(r.read().decode())["data"]["status"]
            except Exception:  # noqa: BLE001
                continue  # 轮询瞬断不算失败，等下一拍
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
        if status == "RUNNING":  # 轮询超时：掐死僵尸 run，别留在平台上计费
            try:
                urllib.request.urlopen(urllib.request.Request(
                    f"{APIFY_API}/actor-runs/{run_id}/abort?token={token}",
                    data=b"", method="POST"), timeout=30)
            except Exception:  # noqa: BLE001
                pass
        if status != "SUCCEEDED":
            old = mi
            mi = max(10, mi // 2)  # 降量重试保底
            log(f"  xquik run「{kw}」状态 {status}（第{attempt + 1}/3次），"
                f"maxItems {old}→{mi} 重试")
            continue
        try:
            with urllib.request.urlopen(
                    f"{APIFY_API}/datasets/{ds_id}/items?token={token}",
                    timeout=60) as r:
                items = json.loads(r.read().decode())
            return items if isinstance(items, list) else []
        except Exception as e:  # noqa: BLE001
            log(f"  xquik 取结果异常「{kw}」（第{attempt + 1}/3次）: {e}")
    log(f"  xquik「{kw}」3 次均失败，留到下轮")
    return None


# ---------------------------------------------------------------- 落库

def _number_variants(digits: str) -> set[str]:
    """号码规范化候选：纯数字本身 + 86 前缀互转（库里中国号两种形态并存）。"""
    d = re.sub(r"\D+", "", digits or "")
    out = {d}
    if d.startswith("86") and len(d) == 13:
        out.add(d[2:])
    elif re.fullmatch(r"1\d{10}", d):
        out.add("86" + d)
    return out


def filter_known_numbers(conn, phones: list[dict]) -> list[dict]:
    """跨源查重：号码（含 86 变体）已存在 fb_contacts 的剔除，返回新号列表。"""
    fresh = []
    for p in phones:
        variants = _number_variants(p.get("number") or "")
        if not variants:
            continue
        q = ",".join("?" * len(variants))
        row = conn.execute(
            f"SELECT 1 FROM fb_contacts WHERE number IN ({q}) LIMIT 1",
            tuple(variants)).fetchone()
        if row is None:
            fresh.append(p)
    return fresh


def harvest_tweets(db, items: list[dict],
                   seen_urls: set[str] | None = None) -> tuple[int, int]:
    """tweet 正文 parse_post 挖中国号落 fb_contacts（group_id=NULL）。
    返回 (有效帖数, 新增号码数)。诊断行（resultType=diagnostic）跳过。
    seen_urls 可跨批传入（深挖翻页时 until_time 边界帖会重复出现）。"""
    if seen_urls is None:
        seen_urls = set()
    n_posts = n_new = 0
    for it in items:
        if not isinstance(it, dict) or it.get("resultType") == "diagnostic":
            continue
        text = it.get("text") or ""
        url = it.get("url") or it.get("tweetUrl") or ""
        if not text or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        n_posts += 1
        info = parse_post(text, text)
        phones = [p for p in info["phones"]
                  if p.get("bucket") != "overseas"
                  and is_cn_number(p.get("number"), p.get("source"))]
        if not phones:
            continue
        phones = filter_known_numbers(db.conn, phones)
        if not phones:
            continue
        author = (it.get("author") or {}).get("name") \
            or (it.get("author") or {}).get("username")
        n_new += db.save_fb_contacts(url, None, phones, author=author)
    return n_posts, n_new


# ---------------------------------------------------------------- 主流程

def pick_due(st: dict, keywords: list[str], limit: int) -> list[str]:
    """从轮转游标起扫一圈，挑出到期词（未退役 且 从未采集或距上次
    ≥ SCAN_INTERVAL_SEC），最多 limit 个；游标推进到最后一个入选词
    之后（一圈都没选到则游标不动）。"""
    n = len(keywords)
    retired = st["kw_retired"]
    now = time.time()
    due, last_i = [], -1
    for i in range(n):
        kw = keywords[(st["offset"] + i) % n]
        if kw in retired:
            continue
        last_q = st["kw_stats"].get(kw, {}).get("last_q_at")
        last_ts = 0.0
        if last_q:
            try:
                last_ts = time.mktime(
                    time.strptime(last_q, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                last_ts = 0.0
        if now - last_ts < SCAN_INTERVAL_SEC:
            continue
        due.append(kw)
        last_i = i
        if len(due) >= limit:
            break
    if last_i >= 0:
        st["offset"] = (st["offset"] + last_i + 1) % n
    return due


def _oldest_ts(items: list[dict]) -> int | None:
    """本批帖子里最老的 createdAt（unix 秒），作下一批 until_time 翻页锚点。"""
    oldest = None
    for it in items:
        if not isinstance(it, dict):
            continue
        ca = it.get("createdAt")
        if not ca:
            continue
        try:
            t = int(parsedate_to_datetime(ca).timestamp())
        except Exception:  # noqa: BLE001
            continue
        oldest = t if oldest is None else min(oldest, t)
    return oldest


def dig_word(db, accounts: list, kw: str, args, st: dict,
             usage: dict, stats: dict) -> bool | None:
    """到期词的完整采集会话：先刺探最新 50 帖；挖到新号就按 until_time
    往历史翻页续挖（每批 50），直到某批新号 +0 / 帖空 / 批数到顶才换词。
    返回 True=会话完成（已记账），None=首批 run 失败（不记账，下轮重试）。
    会话按整体记账：有新号则连击清零，整会话 +0 才记一击。"""
    seen_urls: set[str] = set()
    until: int | None = None
    n_posts = n_new = 0
    for batch_no in range(1, MAX_BATCHES_PER_WORD + 1):
        if not accounts:
            raise AccountError("全部 apify 账号额度耗尽")
        if batch_no > 1:  # 首批预算由 run_round 把关；翻页途中到顶即中止
            if usage["x_results"] >= args.daily_results:
                log(f"  当日结果达顶 {args.daily_results}，「{kw}」深挖中止")
                break
            if st["total_results"] >= args.total_rows_cap:
                stats["budget_out"] = True
                break
        term = f"{kw} until_time:{until}" if until else kw
        items = x_search(db.conn, accounts, term, PROBE_ITEMS)
        if items is None:  # 首批失败整词不算；翻页中断则已采部分照记
            return None if batch_no == 1 else True
        p, n = harvest_tweets(db, items, seen_urls)
        usage["x_results"] += len(items)
        st["total_results"] += len(items)
        st["total_new"] += n
        stats["results"] += len(items)
        stats["posts"] += p
        stats["new"] += n
        n_posts += p
        n_new += n
        tag = "刺探" if batch_no == 1 else f"深翻{batch_no}"
        log(f"  [x][{tag}]「{kw}」: 帖 {p}，新号 +{n}"
            f"（当日 {usage['x_results']}/{args.daily_results}）")
        if n == 0 or not items:
            break  # 这批没挖到新号（或帖空）：挖干了，换下一个词
        nxt = _oldest_ts(items)
        if nxt is None or (until is not None and nxt >= until):
            break  # 拿不到更早的时间锚点，无法继续翻页
        until = nxt
        time.sleep(args.delay)
    else:
        log(f"  「{kw}」深挖达批数上限 {MAX_BATCHES_PER_WORD}，"
            f"剩余历史留到下周期")
    record_kw_stat(st, kw, n_posts, n_new)
    save_state(st)
    log(f"  [x]「{kw}」会话结束：帖 {n_posts}，新号 +{n_new}，"
        f"连击 {st['kw_stats'][kw]['zero_streak']}/{RETIRE_STRIKES}")
    return True


def run_round(db, accounts: list, keywords: list[str], args, st: dict) -> dict:
    """跑一轮：取最多 per-round 个到期词，逐词开采集会话（刺探+深挖）。
    stats["budget_out"] 为 True 表示总预算耗尽，调用方应停机。"""
    usage = today_usage(st)
    stats = {"results": 0, "posts": 0, "new": 0, "budget_out": False}
    batch = pick_due(st, keywords, args.per_round)
    if not batch:
        return stats

    for kw in batch:
        if usage["x_results"] >= args.daily_results:
            log(f"  当日结果达顶 {args.daily_results}，本轮提前结束")
            return stats
        if st["total_results"] >= args.total_rows_cap:
            stats["budget_out"] = True
        ok = dig_word(db, accounts, kw, args, st, usage, stats)
        if ok is None:  # run 失败：不记账，该词下轮仍到期重试
            time.sleep(args.delay)
            continue
        if stats["budget_out"]:
            log(f"  总预算耗尽（累计 {st['total_results']} 行 ≈ "
                f"${st['total_results'] * X_COST_PER_RESULT:.2f}）")
            return stats
        time.sleep(args.delay)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="X 关键词直搜采号（xquik/x-tweet-scraper 常驻，刺探模式）")
    ap.add_argument("--keywords-file",
                    help="覆盖内置 X_KEYWORDS 词库（一行一个关键词）")
    ap.add_argument("--per-round", type=int, default=5,
                    help="每轮最多采集几个到期词")
    ap.add_argument("--interval", type=int, default=600, help="两轮间隔秒数")
    ap.add_argument("--daily-results", type=int, default=5000,
                    help="当日结果数上限（缺省 5000 ≈ $0.75/天，远用不满）")
    ap.add_argument("--total-budget-usd", type=float, default=30,
                    help="总预算美元（缺省 30 ≈ 20 万行），累计到顶即停机")
    ap.add_argument("--delay", type=float, default=5, help="查询间隔秒数")
    ap.add_argument("--once", action="store_true", help="跑一轮即退出")
    args = ap.parse_args()

    if args.keywords_file:
        keywords = [ln.strip() for ln in
                    Path(args.keywords_file).read_text().splitlines()
                    if ln.strip()]
        log(f"使用 --keywords-file 覆盖词库：{len(keywords)} 个")
    else:
        keywords = list(X_KEYWORDS)
    log(f"关键词库 {len(keywords)} 个，每词间隔 "
        f"{SCAN_INTERVAL_SEC // 86400} 天，每轮最多 {args.per_round} 个到期词")

    from fetcher.db import ShopDB  # 延迟导入（WAL + busy_timeout 30s）
    db = ShopDB()

    # apify 账号（与 wa_check 共用额度，402/403 自动轮换）
    try:
        accounts = load_accounts(db.conn)
        log(f"启用 apify 账号 {len(accounts)} 个："
            f"{'、'.join(a[1] for a in accounts)}")
    except SystemExit:
        log("无可用 apify 账号，退出")
        return 1

    st = load_state()
    args.total_rows_cap = int(args.total_budget_usd / X_COST_PER_RESULT)
    log(f"总预算 ${args.total_budget_usd}（≈{args.total_rows_cap} 行），"
        f"已用 {st['total_results']} 行 ≈ "
        f"${st['total_results'] * X_COST_PER_RESULT:.2f}，"
        f"累计新号 {st['total_new']}")
    if st["kw_retired"]:
        log(f"已退役词 {len(st['kw_retired'])} 个（state.kw_retired），"
            f"不参与轮转")
    if st["total_results"] >= args.total_rows_cap:
        log("总预算已耗尽，直接退出")
        return 0
    # 词库换代后旧 offset 可能越界：对 len(keywords) 取模归一
    if keywords:
        st["offset"] %= len(keywords)
    while True:
        try:
            stats = run_round(db, accounts, keywords, args, st)
        except AccountError as e:
            log(f"账号不可用（{e}），10 分钟后重试")
            if args.once:
                return 1
            time.sleep(600)
            continue
        except Exception as e:  # noqa: BLE001
            log(f"本轮异常（{type(e).__name__}: {e}），下轮继续")
            if args.once:
                return 1
            time.sleep(args.interval)
            continue
        if stats["results"] or stats["new"]:
            log(f"本轮：{args.per_round} 词，结果 {stats['results']} 条"
                f"（有效帖 {stats['posts']}），新号 +{stats['new']}，"
                f"当日用量 {today_usage(st)['x_results']}/{args.daily_results}；"
                f"累计 {st['total_results']}/{args.total_rows_cap} 行 ≈ "
                f"${st['total_results'] * X_COST_PER_RESULT:.2f}，"
                f"累计新号 {st['total_new']}")
        if stats.get("budget_out"):
            log("总预算耗尽，停机")
            return 0
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
