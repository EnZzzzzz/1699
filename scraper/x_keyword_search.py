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

用法：
  python3 scraper/x_keyword_search.py --once --per-round 2 --daily-results 50  # 试跑
  python3 scraper/x_keyword_search.py                                          # 常驻
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
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
# 废弃）。实测数据 docs/channel-research/kw-verify-2026-08-18/x_*.jsonl + x_retest.jsonl
X_KEYWORDS: list[str] = [
    "whatsapp factory", "whatsapp wholesale", "whatsapp manufacturer",
    "whatsapp china supplier", "whatsapp china factory", "whatsapp wholesale supplier",
    "whatsapp supplier shoes", "whatsapp supplier jewelry", "whatsapp supplier furniture",
    "whatsapp supplier toys", "whatsapp factory bags", "whatsapp factory jewelry",
    "whatsapp factory LED", "whatsapp factory gym equipment", "whatsapp factory pet supplies",
    "whatsapp wholesale shoes", "whatsapp wholesale clothing", "whatsapp wholesale phone cases",
    "whatsapp wholesale hair", "whatsapp china toys", "whatsapp china wigs",
    "whatsapp china auto parts", "whatsapp china machinery", "whatsapp +86",
    "whatsapp 0086", "pm whatsapp wholesale", "add whatsapp supplier",
    "whatsapp group wholesale", "wechat supplier", "wechat wholesale",
    "wechat factory", "whatsapp mayorista china whatsapp", "whatsapp wechat",
    "wechat manufacturer", "whatsapp wechat supplier", "whatsapp +86 supplier",
    "whatsapp +86 factory", "whatsapp +86 wholesale", "whatsapp +86 shoes",
    "whatsapp +86 hair", "whatsapp +86 clothing", "whatsapp +86 bags",
    "whatsapp +86 electronics", "whatsapp +86 furniture", "whatsapp +86 solar",
    "whatsapp +86 toys", "whatsapp +86 cosmetics", "whatsapp vendor bags",
    "whatsapp vendor LED", "wechat supplier shoes", "wechat supplier hair",
    "wechat supplier clothing", "wechat supplier bags", "wechat supplier electronics",
    "wechat supplier furniture", "whatsapp carpet factory", "whatsapp artificial flowers factory",
    "whatsapp remote control factory", "whatsapp artificial flowers supplier", "factory direct whatsapp",
    "odm whatsapp", "oem whatsapp", "wechat +86",
    "wechat 86", "tel wechat whatsapp", "factory price whatsapp",
    "whatsapp +86 1", "fob whatsapp", "guangzhou whatsapp",
    "china wholesale whatsapp", "in stock whatsapp +86", "whatsapp wechat +86",
    "oem available whatsapp", "wa.me 86",
]

# ---- xquik/x-tweet-scraper（Apify）----
X_ACTOR = "xquik~x-tweet-scraper"
APIFY_API = "https://api.apify.com/v2"
X_COST_PER_RESULT = 0.00015  # $0.15/千帖，按交付行计费（重复帖 actor 侧已去重）
RUN_POLL_SECS = 10
RUN_TIMEOUT_SECS = 420  # 正常 run 5 分钟上下；超时的基本是死 run，别傻等


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class AccountError(Exception):
    """账号级错误（Apify 全部耗尽），整轮中止信号。"""


# ---------------------------------------------------------------- 状态文件

def load_state() -> dict:
    """关键词轮转 offset + 按北京日期的当日用量（机器本地时区即北京）。"""
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text())
            st.setdefault("offset", 0)
            st.setdefault("daily", {})
            return st
        except Exception:
            pass
    return {"offset": 0, "daily": {}}


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=1))


def today_usage(st: dict) -> dict:
    day = time.strftime("%Y-%m-%d")
    return st["daily"].setdefault(day, {"x_results": 0})


# ---------------------------------------------------------------- xquik 搜索

def x_search(conn, accounts: list, kw: str, max_items: int) -> list[dict]:
    """异步 run + 轮询跑一个关键词（Latest 排序），返回 dataset items。
    402/403 欠费记 quota_exhausted_at 并从 accounts 就地移除后换号重试；
    run 超时/FAILED 重试且 maxItems 逐次减半（大词拉全量慢，降量保底），
    仍失败返回 []（留到下轮）。"""
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
            return items if isinstance(items, list) else []
        except Exception as e:  # noqa: BLE001
            log(f"  xquik 取结果异常「{kw}」（第{attempt + 1}/3次）: {e}")
    log(f"  xquik「{kw}」3 次均失败，留到下轮")
    return []


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
        phones = [p for p in info["phones"] if is_cn_number(p.get("number"))]
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

def run_round(db, accounts: list, keywords: list[str], args, st: dict) -> dict:
    """跑一轮：从 offset 取 per-round 个词逐词搜索挖号。"""
    usage = today_usage(st)
    n = len(keywords)
    batch = [keywords[(st["offset"] + i) % n] for i in range(args.per_round)]
    st["offset"] = (st["offset"] + args.per_round) % n
    save_state(st)
    stats = {"results": 0, "posts": 0, "new": 0}

    for kw in batch:
        if not accounts:
            raise AccountError("全部 apify 账号额度耗尽")
        if usage["x_results"] >= args.daily_results:
            log(f"  当日结果达顶 {args.daily_results}，本轮剩余词跳过")
            break
        # 预算刹车粒度：单词 maxItems 不超过当日剩余额度
        max_items = min(args.max_items, args.daily_results - usage["x_results"])
        items = x_search(conn=db.conn, accounts=accounts, kw=kw,
                         max_items=max_items)
        usage["x_results"] += len(items)
        stats["results"] += len(items)
        save_state(st)
        n_posts, n_new = harvest_tweets(db, items)
        stats["posts"] += n_posts
        stats["new"] += n_new
        log(f"  [x]「{kw}」: 帖 {n_posts}，新号 +{n_new}"
            f"（当日 {usage['x_results']}/{args.daily_results}）")
        time.sleep(args.delay)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="X 关键词直搜采号（xquik/x-tweet-scraper 常驻）")
    ap.add_argument("--keywords-file",
                    help="覆盖内置 X_KEYWORDS 词库（一行一个关键词）")
    ap.add_argument("--per-round", type=int, default=5, help="每轮关键词数")
    ap.add_argument("--interval", type=int, default=600, help="两轮间隔秒数")
    ap.add_argument("--daily-results", type=int, default=1000,
                    help="当日结果数上限（缺省 1000 ≈ $0.15/天）")
    ap.add_argument("--max-items", type=int, default=40, help="每词 maxItems")
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
    # 词库换代后旧 offset 可能越界：对 len(keywords) 取模归一（run_round
    # 取词时也有 % n，这里双保险，避免 state 里残留大 offset 值）
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
        log(f"本轮：{args.per_round} 词，结果 {stats['results']} 条"
            f"（有效帖 {stats['posts']}），新号 +{stats['new']}，"
            f"当日用量 {today_usage(st)['x_results']}/{args.daily_results}"
            f"（花费≈${stats['results'] * X_COST_PER_RESULT:.4f}）")
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
