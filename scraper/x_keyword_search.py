#!/usr/bin/env python3
# X(Twitter) 关键词直搜采号常驻脚本：xquik/x-tweet-scraper（Apify）单源，内置 X 专属词库。
"""X 关键词直搜采号（常驻快脚本）。

模式照搬 fb_keyword_search.py（memo23 源），数据源换成
xquik/x-tweet-scraper（Apify，pay-per-result $0.15/千帖，免 X 登录）：
关键词（内置 X_KEYWORDS 专属词库，英文为主 + 西/阿语；X 上英文词是深矿，
实测「whatsapp supplier」maxItems=2000 顶满返回，中文词只有几十帖）
→ X 高级搜索 Latest → 帖正文 parse_post 挖中国号 →
跨源查重（fb_contacts 已有号码跳过，86 前缀/裸 11 位兼容）→ 落 fb_contacts。

落库说明：fb_contacts 无渠道 source 列，bucket 是 parse_post 按号码类型
分的（declared_wa/cn_uncertain/overseas），X 来源靠 post_url=推文链接标识。
跨源去重：number 列有 UNIQUE 约束（save_fb_contacts 走 INSERT OR IGNORE），
但 FB 侧同号可能存 86 前缀形态、X 侧解析成裸 11 位（或反之），精确匹配
挡不住，故落库前先 SELECT 查重（后 11 位对齐），命中即跳过。

关键词轮转：--per-round 个/轮，offset 持久化 .cache/x_keyword_search_state.json
（与 FB 的 state 文件互相独立）。预算刹车：当日结果数到 --daily-results
（默认 1000 ≈ $0.15/天）即停，跨天自动清零。
402/403 欠费按 wa_check_apify 口径记 quota_exhausted_at 并轮换账号。

深度优先回扫（2026-08-22 倒序+提前收工版）：未完成回扫的词排在每轮
最前（深度优先，榨干一词再下一词），每词每轮连续扫 --windows-per-word
个窗口。窗口用 since_time:/until_time: unix 秒窗，初长 1 天，**从今天
零点倒着往历史扫**（甜区先吃）：结果顶满 maxItems 视为截断 → 窗长减半
（下限 5 分钟）原地重扫，未顶满 → 往历史推进一窗并翻倍窗长；连续
DUP_STOP_WINDOWS(5) 窗「有帖但新号 +0」即提前收工（深历史全是泛词/
早期波次采过的重复帖，不再花钱买），扫到 --backfill-days 深度下限
也收工；收工后转 since_time 增量，锚点定在开工上沿 top（跨天无空洞）。
回扫进度记 state.kw_backfill[kw]={"cursor","win","dup","floor","top"}，
旧版格式（正序游标/日期字符串）读取时废弃重来。
总预算刹车：--total-budget-usd（默认 30，按 $0.15/千帖折算行数上限），
累计用量记 state.total_results，耗尽即停机；累计新号记 state.total_new。
回扫与增量同样受 --daily-results 日预算刹车，自然摊到多天完成。

词退役（2026-08-22 起）：增量/全量首拉连续 RETIRE_ZP_SCANS(5) 次帖 0
且连击跨度 ≥ RETIRE_ZP_DAYS(3) 天 → 判真枯竭，记 state.kw_retired 并
移出轮转（词库文件不动；退役词减少后轮转周期自动缩短，活词扫得更勤）。
误判复活：删 state.kw_retired 对应键即可，下轮恢复扫描。

用法：
  python3 scraper/x_keyword_search.py --once --per-round 1 --windows-per-word 3 \
      --max-items 500 --backfill-days 365 --daily-results 2000   # 试跑
  python3 scraper/x_keyword_search.py --backfill-days 365 --max-items 2000 \
      --daily-results 20000                                       # 常驻深扫
"""
from __future__ import annotations

import argparse
import datetime
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

# ---------------------------------------------------------------- X 专属词库
# 内置关键词库（2026-08-18 全量实测策展版）：原 195 词（含第七/八波）经
# WebBridge 真实浏览器逐词验证（X 搜索 Latest，慢节奏复测排除软限流空
# 渲染），只保留实测含中国号（C>0）的 73 词 + wa.me 86（两轮 H=100%，号
# 码藏 wa.me 短链，parse_post 可从 URL 提号）。西/阿语词、无锚点角色×品
# 质词、vendor 矩阵大部分实测零产出一并清除（原 _BLOCKED 黑名单机制随之
# 废弃）。2026-08-19 按实测含号量降序重排（深度优先回扫先吃高产词），
# wa.me 86 居首。实测数据
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
RUN_TIMEOUT_SECS = 420  # 正常 run 5 分钟上下；超时的基本是死 run，别傻等

# ---- 回扫自适应切窗 ----
MIN_WINDOW_SEC = 300    # 窗口下限（5 分钟）
MAX_WINDOW_SEC = 86400  # 窗口上限/初长（1 天）


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class AccountError(Exception):
    """账号级错误（Apify 全部耗尽），整轮中止信号。"""


# ---------------------------------------------------------------- 状态文件

def load_state() -> dict:
    """关键词轮转 offset + 按北京日期的当日用量（机器本地时区即北京）
    + kw_since 每词增量锚点（上次成功抓取的 unix 时刻）
    + kw_backfill 每词回扫窗口进度（"done" 或倒序游标
      {"cursor","win","dup","floor","top"}，语义见 get_backfill）
    + total_results / total_new 累计行数 / 累计新号（总预算记账）
    + kw_stats 每词采集表现（q/posts/new/first_at/last_q_at/last_new_at/
      zero_streak/zp/zp_since，kw_stats.py 报表据此推导老化状态）
    + kw_retired 已退役词（增量长期帖 0 判真枯竭，移出轮转不再扫，
      复活：删该键即可）。"""
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text())
            st.setdefault("offset", 0)
            st.setdefault("daily", {})
            st.setdefault("kw_since", {})
            st.setdefault("kw_backfill", {})
            st.setdefault("total_results", 0)
            st.setdefault("total_new", 0)
            st.setdefault("kw_stats", {})
            st.setdefault("kw_retired", {})
            return st
        except Exception:
            pass
    return {"offset": 0, "daily": {}, "kw_since": {}, "kw_backfill": {},
            "total_results": 0, "total_new": 0, "kw_stats": {},
            "kw_retired": {}}


# 词退役判据：非回扫查询（增量/全量首拉）连续 RETIRE_ZP_SCANS 次帖 0
# 且连击跨度 ≥ RETIRE_ZP_DAYS 天 → 判真枯竭（不是一时没帖），移入
# state.kw_retired 退出轮转。词库里词多时一轮要 ~9 小时才轮到一词，
# 所以 5 次天然跨约 2 天，跨度下限再兜一道防小词库高频误杀。
RETIRE_ZP_SCANS = 5
RETIRE_ZP_DAYS = 3


def record_kw_stat(st: dict, kw: str, n_posts: int, n_new: int,
                   mode: str) -> None:
    """每词每次查询后记账：累计查询/帖/新号，维护 last_new_at 与连续+0
    次数（zero_streak，出新号即清零）；非回扫查询另维护连续帖0连击
    （zp/zp_since），满退役判据则移入 kw_retired 退出轮转。
    时间戳为北京时间字符串。"""
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
    else:
        s["zero_streak"] += 1
    if mode.startswith("回扫"):  # 回扫空窗正常（老时间段本就没帖），不计
        return
    if n_posts > 0:
        s["zp"] = 0
        s["zp_since"] = None
        s["last_post_at"] = now
        return
    s["zp"] = s.get("zp", 0) + 1
    if not s.get("zp_since"):
        s["zp_since"] = now
    span_days = (time.time() -
                 time.mktime(time.strptime(s["zp_since"],
                                           "%Y-%m-%d %H:%M:%S"))) / 86400
    retired = st.setdefault("kw_retired", {})
    if (s["zp"] >= RETIRE_ZP_SCANS and span_days >= RETIRE_ZP_DAYS
            and kw not in retired):
        retired[kw] = {"at": now, "zp": s["zp"], "q": s["q"]}
        log(f"  ☠「{kw}」连续 {s['zp']} 次（{span_days:.1f} 天）增量帖 0，"
            f"判定枯竭退役，移出轮转")


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=1))


def today_usage(st: dict) -> dict:
    day = time.strftime("%Y-%m-%d")
    return st["daily"].setdefault(day, {"x_results": 0})


# ---------------------------------------------------------------- xquik 搜索

def x_search(conn, accounts: list, kw: str, max_items: int) -> tuple[list[dict], int] | None:
    """异步 run + 轮询跑一个查询词（Latest 排序），返回 (dataset items, 实际生效的
    maxItems)。kw 可带 X 高级搜索语法（since:/until:/since_time:/until_time:
    等），原样透传。402/403 欠费记 quota_exhausted_at 并从 accounts 就地移除
    后换号重试；run 超时/FAILED 重试且 maxItems 逐次减半（大词拉全量慢，降量
    保底）——返回值第二元是最终生效的 maxItems，调用方用它判截断（重试降量
    后返回数会小于原始 maxItems，用原值判会把截断窗误判为扫完）。仍失败返回
    None，调用方不得推进窗口进度。"""
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
            mi = max(100, mi // 2)  # 降量重试：大词全量拉不动就少拉点
            log(f"  xquik run「{kw}」状态 {status}（第{attempt + 1}/3次），"
                f"maxItems {old}→{mi} 重试")
            continue
        try:
            with urllib.request.urlopen(
                    f"{APIFY_API}/datasets/{ds_id}/items?token={token}",
                    timeout=60) as r:
                items = json.loads(r.read().decode())
            return (items if isinstance(items, list) else []), mi
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


def harvest_tweets(db, items: list[dict]) -> tuple[int, int]:
    """tweet 正文 parse_post 挖中国号落 fb_contacts（group_id=NULL）。
    返回 (有效帖数, 新增号码数)。诊断行（resultType=diagnostic）跳过。"""
    n_posts = n_new = 0
    seen_urls: set[str] = set()
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

def _ymd(days_ago: int = 0) -> str:
    """北京日期（机器本地时区）往前推 days_ago 天的 YYYY-MM-DD。"""
    return time.strftime("%Y-%m-%d",
                         time.localtime(time.time() - days_ago * 86400))


def backfill_end_ts() -> int:
    """回扫终点：今天 00:00（本地/北京时区）的 unix 时刻。今日内的新帖
    由增量模式（since_time 锚点）负责，回扫只覆盖 [起点, 今天零点)。"""
    lt = time.localtime()
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                            0, 0, 0, 0, 0, -1)))


def get_backfill(st: dict, kw: str, backfill_days: int) -> dict | str:
    """该词回扫状态："done" 或 {"cursor","win","dup","floor","top"}——
    倒序回扫：cursor=下一待扫窗口终点 unix 时刻（从今天零点往历史扫），
    floor=深度下限（N 天前零点，扫到即完成），top=开工上沿（收工后增量
    锚点定在这里，跨天回扫也不会留空洞），dup=连续「有帖但新号+0」窗数。
    未开始的词现场生成；旧版格式（正序游标 dict / 日期字符串）语义已
    废弃，一律按全新倒序回扫重新开始（已扫过的多为空窗，重扫成本极低）。"""
    v = st["kw_backfill"].get(kw)
    if v == "done":
        return "done"
    if isinstance(v, dict) and "dup" in v:
        return v
    d = datetime.date.fromisoformat(_ymd(backfill_days))
    top = backfill_end_ts()
    return {"cursor": top, "win": MAX_WINDOW_SEC, "dup": 0,
            "floor": int(time.mktime(d.timetuple())), "top": top}


def _fmt_span(sec: int) -> str:
    if sec >= 86400 and sec % 86400 == 0:
        return f"{sec // 86400}d"
    if sec >= 3600 and sec % 3600 == 0:
        return f"{sec // 3600}h"
    return f"{sec // 60}m"


def build_query(st: dict, kw: str, args) -> tuple[str, str, int | None, int | None]:
    """构造该词本次查询，返回 (查询词, 模式, start, end)（增量模式后两者
    为 None）。回扫优先：kw_backfill 非 done 时扫 since_time:/until_time:
    窗口 [cursor-win, cursor)，从今天零点倒着往历史扫（甜区先吃，
    连续有帖无新号即提前收工，见 advance）；否则走增量：有锚点拼
    since_time:<ts> 只拉新帖，无锚点全量首拉。"""
    if args.backfill_days > 0:
        bf = get_backfill(st, kw, args.backfill_days)
        if bf != "done":
            end = bf["cursor"]
            start = max(end - bf["win"], bf["floor"])
            mode = (f"回扫{_fmt_span(end - start)}@"
                    f"{time.strftime('%m-%d %H:%M', time.localtime(start))}")
            return f"{kw} since_time:{start} until_time:{end}", mode, start, end
    ts = st["kw_since"].get(kw)
    if ts:
        return f"{kw} since_time:{ts}", "增量", None, None
    return kw, "全量首拉", None, None


# 倒序回扫提前收工阈值：连续 N 个窗口有帖但新号 +0，视为深历史全是
# 已被泛词/早期波次采过的重复帖，不再花钱买（词保留在增量轮转里）
DUP_STOP_WINDOWS = 5


def advance(st: dict, kw: str, args, mode: str,
            start: int | None, end: int | None,
            n_items: int, mi_used: int, n_posts: int, n_new: int) -> str | None:
    """查询成功后推进进度，返回备注（截断缩窗/回扫完成/提前收工/None）。
    回扫（倒序，窗口 [start, end)）：返回数顶满实际生效 maxItems 视为截断
    → 窗长减半、end 原地不动重扫（已到下限仍顶满则有损前进并告警）；
    未顶满 → 下一窗往历史推进（end=start）、窗长翻倍（上限 1 天），并按
    n_posts/n_new 维护 dup 连击（空窗不计）。dup 满 DUP_STOP_WINDOWS 或
    扫到 floor 即置 done，增量锚点定在开工上沿 top（不是收工时刻——
    回扫可能跨天，[top, 收工时刻) 的帖子由增量覆盖，2026-08-19 空洞
    修复的语义在倒序下由 top 承担）。
    增量/全量：锚点推到当前时刻再回拨 1 小时重叠带——X 搜索有索引延迟，
    发布后未及时入索引的帖会被 since_time 永久跳过，重叠带的重复帖靠
    落库号码去重消化（2026-08-19 实测诊断确认此漏检）。
    想重扫删 state.kw_backfill 对应键。"""
    if mode.startswith("回扫"):
        bf = get_backfill(st, kw, args.backfill_days)
        win, dup = bf["win"], bf.get("dup", 0)
        floor, top = bf["floor"], bf["top"]
        if n_items >= mi_used:
            if win > MIN_WINDOW_SEC:
                new_win = max(win // 2, MIN_WINDOW_SEC)
                st["kw_backfill"][kw] = {"cursor": end, "win": new_win,
                                         "dup": dup, "floor": floor,
                                         "top": top}
                return f"截断缩窗 {_fmt_span(win)}→{_fmt_span(new_win)}"
            st["kw_backfill"][kw] = {"cursor": start, "win": MIN_WINDOW_SEC,
                                     "dup": dup, "floor": floor, "top": top}
            return f"最小窗仍顶满 {n_items}，有损前进"
        if n_new > 0:
            dup = 0
        elif n_posts > 0:
            dup += 1
        if dup >= DUP_STOP_WINDOWS:
            st["kw_backfill"][kw] = "done"
            st["kw_since"][kw] = top
            return f"回扫提前收工：连续 {dup} 窗有帖无新号"
        if start <= floor:
            st["kw_backfill"][kw] = "done"
            st["kw_since"][kw] = top
            return "回扫完成"
        st["kw_backfill"][kw] = {"cursor": start,
                                 "win": min(win * 2, MAX_WINDOW_SEC),
                                 "dup": dup, "floor": floor, "top": top}
        return None
    st["kw_since"][kw] = int(time.time()) - 3600  # 1 小时重叠带，抗索引延迟
    return None


def count_out_of_window(items: list[dict], cursor: int, end: int) -> tuple[int, int]:
    """校验返回帖 createdAt 是否落在 [cursor, end) 内（防 until_time 静默
    失效：一旦失效 Latest 排序返回的是全站新帖，窗口会被错误标完成）。
    返回 (可解析时间戳的帖数, 窗外帖数)。"""
    n_ts = n_out = 0
    for it in items:
        if not isinstance(it, dict) or it.get("resultType") == "diagnostic":
            continue
        ca = it.get("createdAt")
        if not ca:
            continue
        try:
            ts = parsedate_to_datetime(ca).timestamp()
        except Exception:  # noqa: BLE001
            continue
        n_ts += 1
        if not (cursor <= ts < end):
            n_out += 1
    return n_ts, n_out


def run_round(db, accounts: list, keywords: list[str], args, st: dict) -> dict:
    """跑一轮。深度优先：回扫未完成的词按词库顺序排最前（每轮只取前
    per-round 个，榨干一词再轮到下一词），每词连续扫 windows-per-word
    个窗口；全部词回扫完成后退化为原轮转增量维护。stats["budget_out"]
    为 True 表示总预算耗尽，调用方应停机。"""
    usage = today_usage(st)
    retired = st.get("kw_retired", {})
    if retired:  # 退役词移出轮转：少扫死词，轮转周期随之缩短
        keywords = [kw for kw in keywords if kw not in retired]
    n = len(keywords)
    stats = {"results": 0, "posts": 0, "new": 0, "budget_out": False}
    if not keywords:
        log("  词库全部退役，无词可扫")
        return stats

    pending = []
    if args.backfill_days > 0:
        pending = [kw for kw in keywords
                   if get_backfill(st, kw, args.backfill_days) != "done"]
    if pending:
        batch = pending[:args.per_round]
        backfilling = True
    else:
        batch = [keywords[(st["offset"] + i) % n] for i in range(args.per_round)]
        st["offset"] = (st["offset"] + args.per_round) % n
        save_state(st)
        backfilling = False

    for kw in batch:
        for _ in range(args.windows_per_word if backfilling else 1):
            if not accounts:
                raise AccountError("全部 apify 账号额度耗尽")
            if usage["x_results"] >= args.daily_results:
                log(f"  当日结果达顶 {args.daily_results}，本轮提前结束")
                return stats
            if st["total_results"] >= args.total_rows_cap:
                log(f"  总预算耗尽（累计 {st['total_results']} 行 ≈ "
                    f"${st['total_results'] * X_COST_PER_RESULT:.2f}）")
                stats["budget_out"] = True
                return stats
            term, mode, start, end = build_query(st, kw, args)
            got = x_search(conn=db.conn, accounts=accounts, kw=term,
                           max_items=args.max_items)
            if got is None:  # run 失败：进度不推进，下轮重试该词同一窗口
                time.sleep(args.delay)
                break
            items, mi_used = got
            n_posts, n_new = harvest_tweets(db, items)
            note = advance(st, kw, args, mode, start, end,
                           len(items), mi_used, n_posts, n_new)
            usage["x_results"] += len(items)
            st["total_results"] += len(items)
            stats["results"] += len(items)
            st["total_new"] += n_new
            stats["posts"] += n_posts
            stats["new"] += n_new
            record_kw_stat(st, kw, n_posts, n_new, mode)
            save_state(st)
            if start is not None:
                n_ts, n_out = count_out_of_window(items, start, end)
                if n_ts and n_out / n_ts > 0.2:
                    log(f"  ⚠「{kw}」{n_out}/{n_ts} 帖在窗口外，"
                        f"until_time 可能未生效，请人工核查")
            log(f"  [x][{mode}]「{kw}」: 帖 {n_posts}，新号 +{n_new}"
                f"{('，' + note) if note else ''}"
                f"（当日 {usage['x_results']}/{args.daily_results}）")
            if note and note.startswith(("回扫完成", "回扫提前收工")):
                break
            time.sleep(args.delay)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="X 关键词直搜采号（xquik/x-tweet-scraper 常驻）")
    ap.add_argument("--keywords-file",
                    help="覆盖内置 X_KEYWORDS 词库（一行一个关键词）")
    ap.add_argument("--per-round", type=int, default=5,
                    help="每轮关键词数（深度优先：回扫期取词库前 N 个未完成词）")
    ap.add_argument("--interval", type=int, default=600, help="两轮间隔秒数")
    ap.add_argument("--daily-results", type=int, default=1000,
                    help="当日结果数上限（缺省 1000 ≈ $0.15/天）")
    ap.add_argument("--total-budget-usd", type=float, default=30,
                    help="总预算美元（缺省 30 ≈ 20 万行），累计到顶即停机")
    ap.add_argument("--max-items", type=int, default=40, help="每词 maxItems")
    ap.add_argument("--windows-per-word", type=int, default=10,
                    help="回扫期每词每轮最多连续扫几个窗口")
    ap.add_argument("--backfill-days", type=int, default=0,
                    help="历史回扫天数：>0 时每词从 N 天前自适应切窗扫到"
                         "今天零点（截断窗自动对半拆分），扫完自动转增量")
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
    log(f"关键词库 {len(keywords)} 个，每轮 {args.per_round} 个轮转")

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
    if st["total_results"] >= args.total_rows_cap:
        log("总预算已耗尽，直接退出")
        return 0
    # 词库换代后旧 offset 可能越界：对 len(keywords) 取模归一（run_round
    # 取词时也有 % n，这里双保险，避免 state 里残留大 offset 值）
    if keywords:
        st["offset"] %= len(keywords)
    if st.get("kw_retired"):
        log(f"已退役词 {len(st['kw_retired'])} 个（state.kw_retired），"
            f"不参与轮转")
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
