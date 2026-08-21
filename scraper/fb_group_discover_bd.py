#!/usr/bin/env python3
# FB 群发现（Bright Data Google SERP 版，快脚本）。
"""FB 群发现（Bright Data Google SERP 版，快脚本）。

补 fb_group_bd.py 的群来源：BD Facebook 数据集全是 collect-by-URL，没有
群发现端点；改用 BD Google SERP 数据集 gd_mfz5x93lmsjjjylob 查询
`site:facebook.com/groups <关键词>`（一次返回最多 100 条有机结果），
复用 fetcher classify_fb_url 提取群主页/帖派生群，落 fb_groups
（url UNIQUE 幂等，source='bd_serp'）；SERP description 解析群成员数
落 fb_groups.members（采集侧 --min-members 过滤低成员群）。

- 预览挖号（零边际成本）：发现查询词带 whatsapp/微信，SERP 标题/摘要
  常直接含中国号（存量标题实测 10% 带号、63% 是新号）——记录已为
  群发现付费，顺手 parse_post 分桶落 fb_contacts，不替代群采集。
- 关键词：--keywords 指定（自动补 site: 前缀）；缺省复用 work_items
  (discover_fb) 的历史查询词（已带 site: 前缀，直接用）。
- 调用：sync /scrape 单查询一次一条记录（SERP 按记录计费，费用极低），
  串行 + --delay 间隔即可，发现层无需并发。
- 翻页：--pages N 追加 start=10/20... 继续抓（num=100 时首页已够，
  缺省 1 页）。

用法：
  python3 scraper/fb_group_discover_bd.py --once --max-keywords 3   # 试跑
  python3 scraper/fb_group_discover_bd.py --keywords "货代 微信" "外贸 whatsapp"
  python3 scraper/fb_group_discover_bd.py                            # 常驻看护循环
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "fetcher"))

from fetcher.sites.facebook.discover import classify_fb_url  # noqa: E402
from fetcher.sites.facebook.discover_task import _clean_title  # noqa: E402
from fetcher.sites.facebook.post import parse_post  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fb_group_bd import is_cn_number  # noqa: E402

BD_API = "https://api.brightdata.com/datasets/v3"
BD_DATASET_GOOGLE_SERP = "gd_mfz5x93lmsjjjylob"  # Google SERP 100 results
SITE_PREFIX = "site:facebook.com/groups"
SCRAPE_TIMEOUT = 120  # sync scrape 上限（BD 侧 1 分钟内返回，留余量）

# 群 id 黑名单：groups/ 下的功能页不是群
_NON_GROUP_GIDS = {"feed", "discover", "search", "join", "create", "recommended"}

# SERP description 里的成员数（FB 群主页 meta 描述常见格式）：
# "Public group · 12K members" / "5,234 members" / "1.2 万位成员" / "86 位成员"
_MEMBERS_RE = re.compile(
    r"([\d,.]+)\s*([KkMm万])?\s*(?:members|位成员|名成员|个成员)", re.I)
_MEMBERS_MULT = {"k": 1_000, "m": 1_000_000, "万": 10_000}


def parse_members(text: str) -> int | None:
    """SERP description → 群成员数（取第一个匹配，解析不出返回 None）。"""
    m = _MEMBERS_RE.search(text or "")
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = _MEMBERS_MULT.get((m.group(2) or "").lower(), 1)
    return int(num * mult)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class AccountError(Exception):
    """BD 账号级错误（停用/欠费/鉴权失败），整轮中止信号。"""


class BDClient:
    def __init__(self, api_key: str):
        self.headers = {"Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"}

    def scrape_serp(self, query: str, page: int, num: int) -> list[dict]:
        """同步抓一页 Google SERP，返回该页记录列表（0 或 1 条）。"""
        start = (page - 1) * num
        search_url = (f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                      f"&num={num}&hl=zh-CN&start={start}")
        payload = [{"url": search_url, "keyword": query, "language": "zh-CN"}]
        req = urllib.request.Request(
            f"{BD_API}/scrape?dataset_id={BD_DATASET_GOOGLE_SERP}&format=json",
            data=json.dumps(payload).encode(), method="POST",
            headers=self.headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=SCRAPE_TIMEOUT) as r:
                    body = json.loads(r.read().decode() or "[]")
                    return body if isinstance(body, list) else []
            except urllib.error.HTTPError as e:
                msg = e.read().decode()[:200]
                log(f"  scrape 失败「{query}」第{page}页: HTTP {e.code} {msg}")
                if e.code in (401, 402, 403) or "not active" in msg.lower() \
                        or "balance" in msg.lower():
                    raise AccountError(f"HTTP {e.code}: {msg}") from e
                return []
            except Exception as e:  # noqa: BLE001
                # 瞬时网络错误（SSL EOF/连接被断），退避后重试
                log(f"  scrape 异常「{query}」第{page}页（第{attempt + 1}/3次）: {e}")
                time.sleep(min(2 ** attempt * 5, 20))
        return []


def default_queries(db) -> list[str]:
    """缺省关键词：复用 discover_fb 历史查询词（已带 site: 前缀）。"""
    rows = db.conn.execute(
        "SELECT DISTINCT json_extract(payload_json, '$.query')"
        " FROM work_items WHERE queue='discover_fb'").fetchall()
    return [r[0] for r in rows
            if r[0] and isinstance(r[0], str) and "facebook.com" in r[0]]


def extract_groups(records: list[dict]) -> list[dict]:
    """SERP 记录 → 群条目（url/group_id/name 去重，帖 permalink 派生群主页）。"""
    seen: dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict) or rec.get("error"):
            continue
        for item in rec.get("organic") or []:
            link = item.get("link") or ""
            cls = classify_fb_url(link)
            if cls is None:
                continue
            _, gid, group_url = cls
            if gid in _NON_GROUP_GIDS:
                continue
            seen.setdefault(group_url, {
                "url": group_url, "group_id": gid,
                "name": _clean_title(item.get("title")),
                "members": parse_members(item.get("description")),
                "source": "bd_serp",
            })
    return list(seen.values())


def harvest_serp_contacts(db, records: list[dict]) -> int:
    """SERP 预览（标题+摘要）直接挖中国号：发现查询词带 whatsapp/微信，
    Google 索引的帖摘要常含联系方式——这些记录已为群发现付过费，
    挖掘是零边际成本（2026-08-11：存量标题实测 10% 带号，63% 是新号）。
    摘要截断导致的残号靠 wa_check 查号环节自然筛掉。返回新增号码数。"""
    n_new = 0
    for rec in records:
        if not isinstance(rec, dict) or rec.get("error"):
            continue
        for item in rec.get("organic") or []:
            link = item.get("link") or ""
            cls = classify_fb_url(link)
            if cls is None:
                continue
            _, gid, _group_url = cls
            if gid in _NON_GROUP_GIDS:
                continue
            text = f"{item.get('title') or ''}\n{item.get('description') or ''}"
            info = parse_post(text, text)
            phones = [p for p in info["phones"] if is_cn_number(p.get("number"))]
            if phones:
                n_new += db.save_fb_contacts(link, gid, phones)
    return n_new


def run_pass(db, bd: BDClient, queries: list[str], args) -> dict:
    stats = {"queries": 0, "groups_found": 0, "groups_new": 0, "contacts": 0}
    for qi, query in enumerate(queries):
        for page in range(1, args.pages + 1):
            records = bd.scrape_serp(query, page, num=100)
            stats["queries"] += 1
            if not records:
                break  # 空页/失败不再翻页
            groups = extract_groups(records)
            n_new = db.upsert_fb_groups(groups) if groups else 0
            n_members = sum(1 for g in groups if g.get("members") is not None)
            n_contacts = harvest_serp_contacts(db, records)
            stats["groups_found"] += len(groups)
            stats["groups_new"] += n_new
            stats["contacts"] += n_contacts
            log(f"  「{query}」第{page}页: {len(groups)} 群（新增 {n_new}，"
                f"成员数识别 {n_members}/{len(groups)}），"
                f"预览挖号 +{n_contacts}（累计群 {stats['groups_new']}，"
                f"累计号 {stats['contacts']}）")
            if qi < len(queries) - 1 or page < args.pages:
                time.sleep(args.delay)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="FB 群发现（Bright Data Google SERP）")
    ap.add_argument("--keywords", nargs="+",
                    help="关键词（可多个，自动补 site:facebook.com/groups 前缀；"
                         "缺省复用 discover_fb 历史查询词）")
    ap.add_argument("--pages", type=int, default=1, help="每关键词抓几页")
    ap.add_argument("--max-keywords", type=int, default=0,
                    help="每轮最多跑多少关键词（0=不限）")
    ap.add_argument("--delay", type=float, default=5,
                    help="查询间隔秒数（礼貌节奏）")
    ap.add_argument("--once", action="store_true", help="跑一轮即退出")
    ap.add_argument("--interval", type=int, default=3600,
                    help="常驻模式两轮间隔秒数")
    args = ap.parse_args()

    from fetcher.db import ShopDB  # 延迟导入（WAL + busy_timeout 30s）
    db = ShopDB()
    row = db.conn.execute(
        "SELECT config_json FROM providers WHERE kind='brightdata' AND enabled=1"
    ).fetchone()
    if not row:
        log("providers 表无 brightdata 凭证，退出")
        return 1
    bd = BDClient(json.loads(row[0])["api_key"])

    queries = []
    if args.keywords:
        queries = [k if SITE_PREFIX in k else f"{SITE_PREFIX} {k}"
                   for k in args.keywords]
    # 与 discover_fb 历史查询词合并去重（CLI 优先）
    queries += [q for q in default_queries(db) if q not in queries]
    if not queries:
        log("无关键词（--keywords 未给且 discover_fb 无历史查询），退出")
        return 1
    if args.max_keywords > 0:
        queries = queries[:args.max_keywords]
    log(f"关键词 {len(queries)} 个，每个 {args.pages} 页")

    total_new = 0
    while True:
        try:
            stats = run_pass(db, bd, queries, args)
        except AccountError as e:
            log(f"BD 账号不可用（{e}），10 分钟后重试")
            if args.once:
                return 1
            time.sleep(600)
            continue
        total_new += stats["groups_new"]
        log(f"本轮：查询 {stats['queries']} 次，发现群 {stats['groups_found']}，"
            f"新增 {stats['groups_new']}（累计新增 {total_new}），"
            f"预览挖号 {stats['contacts']}")
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
