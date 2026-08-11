#!/usr/bin/env python3
"""FB 群采集（Bright Data 群 feed 版，快脚本）。

替代 fb_group_wa.py 的「Apify 发现 + 本地 CloakBrowser 逐帖渲染」链路：
按群 URL 调 BD 数据集 gd_lz11l67o2cb3r0lkj3（trigger→progress→snapshot
三段式），一次拿群最新 N 帖正文，复用 fetcher parse_post 四桶分号，
落 fb_contacts（number UNIQUE 幂等）。

- 群来源：fb_groups 表（612 群已由 fb_posts 回填；discover_fb 会持续补充），
  按 last_crawled_at 冷却轮抓（默认 24h），never-crawled 优先。
- 增量抓取（降本核心）：重抓群带 start_date=上次采集日期，BD 只返回
  该日期后的新帖，旧帖不计费；首次采的群全量拉 --posts 帖。
  日期格式默认 MM-DD-YYYY（BD 官方文档），不生效可 --date-format iso 切换。
- 零产出群淘汰：历史零号码的群冷却 ×--zero-cooldown-factor（默认 3 倍），
  预算集中到产号群（靠 fb_contacts.group_id 计数判断，不改表结构）。
- 并发：同时挂 --conc 个 trigger，轮询收割（BD 侧异步，本地零浏览器）。
- 费用：按成功交付帖数计费（$1.5/千条），免费 5000 条/月；
  控量靠增量抓取 + 零产出淘汰 + --posts / --cooldown-hours。
- 私密群匿名抓不到，BD 快照会给 error 记录，跳过并计 fail。

用法：
  python3 scraper/fb_group_bd.py --once --max-groups 20   # 试跑
  python3 scraper/fb_group_bd.py                          # 常驻看护循环
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

from fetcher.sites.facebook.post import parse_post  # noqa: E402

BD_API = "https://api.brightdata.com/datasets/v3"
BD_DATASET_GROUP_POSTS = "gd_lz11l67o2cb3r0lkj3"  # FB posts by group URL
POLL_INTERVAL = 10
SNAPSHOT_TIMEOUT = 900  # 单群快照轮询上限（并发高时 BD 侧排队，给足余量）


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class AccountError(Exception):
    """BD 账号级错误（停用/欠费/鉴权失败），整轮中止信号。"""


class BDClient:
    def __init__(self, api_key: str):
        self.headers = {"Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"}

    def _http(self, method: str, url: str, payload=None, timeout: int = 60):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:200]
        except Exception as e:  # noqa: BLE001
            return -1, str(e)[:200]

    def trigger(self, group_url: str, num_posts: int,
                start_date: str | None = None) -> str | None:
        # start_date：增量抓取，BD 只回该日期后的新帖（旧帖不计费）
        item = {"url": group_url, "num_of_posts": num_posts}
        if start_date:
            item["start_date"] = start_date
        for attempt in range(3):
            s, body = self._http(
                "POST", f"{BD_API}/trigger?dataset_id={BD_DATASET_GROUP_POSTS}"
                        f"&include_errors=true",
                [item])
            if s // 100 == 2:
                return (body or {}).get("snapshot_id")
            # 传输层瞬断（SSL EOF 等）重试，HTTP 错误不重试
            if s == -1 and attempt < 2:
                time.sleep(5)
                continue
            log(f"  trigger 失败 {group_url}: HTTP {s} {body}")
            # 账号级错误（停用/欠费/鉴权）抛异常让整轮中止，避免全部群被误标 failed
            msg = str(body).lower()
            if s in (401, 402, 403) or "not active" in msg or "balance" in msg:
                raise AccountError(f"HTTP {s}: {body}")
            return None
        return None

    def poll(self, snapshot_id: str) -> str:
        s, body = self._http("GET", f"{BD_API}/progress/{snapshot_id}",
                             timeout=30)
        if s // 100 != 2:
            return "poll_error"
        return (body or {}).get("status") or "unknown"

    def download(self, snapshot_id: str) -> list[dict]:
        # 202（快照构建中，poll ready 存在竞态）/ 传输瞬断，退避重试 3 次
        for attempt in range(3):
            s, body = self._http("GET",
                                 f"{BD_API}/snapshot/{snapshot_id}?format=json",
                                 timeout=120)
            if s // 100 == 2 and isinstance(body, list):
                return body
            if attempt < 2:
                time.sleep(10)
                continue
            log(f"  snapshot 下载失败 {snapshot_id}: HTTP {s}")
            return []
        return []


def due_groups(db, cooldown_hours: float, max_groups: int,
               zero_factor: float) -> list[tuple[str, str, str | None]]:
    """到期待抓群：(url, group_id, last_crawled_at)，never-crawled 优先，再按最久未抓。
    零产出群（历史零号码且已采过）冷却 ×zero_factor，把预算集中到产号群。
    last_crawled_at 是北京时间字符串，cutoff 同样按北京时间拼。"""
    import datetime
    def cutoff(hours: float) -> str:
        return (datetime.datetime.now()
                - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db.conn.execute(
        "SELECT url, group_id, last_crawled_at FROM ("
        "  SELECT g.url, g.group_id, g.last_crawled_at,"
        "    (SELECT COUNT(*) FROM fb_contacts c WHERE c.group_id = g.group_id)"
        "      AS n_contacts"
        "  FROM fb_groups g WHERE g.status != 'in_progress')"
        " WHERE last_crawled_at IS NULL"
        "    OR (n_contacts > 0 AND last_crawled_at < ?)"
        "    OR (n_contacts = 0 AND last_crawled_at < ?)"
        " ORDER BY last_crawled_at IS NOT NULL, last_crawled_at",
        (cutoff(cooldown_hours), cutoff(cooldown_hours * zero_factor))
    ).fetchall()
    if max_groups > 0:
        rows = rows[:max_groups]
    return [(r[0], r[1], r[2]) for r in rows]


def to_start_date(last_crawled_at: str | None, date_format: str) -> str | None:
    """last_crawled_at（北京时间）→ BD start_date。
    官方文档格式 MM-DD-YYYY；若 BD 侧不生效可切 iso（YYYY-MM-DD）。"""
    if not last_crawled_at:
        return None
    y, m, d = last_crawled_at[:10].split("-")
    return f"{y}-{m}-{d}" if date_format == "iso" else f"{m}-{d}-{y}"


def is_cn_number(digits: str) -> bool:
    """中国号判定：裸 11 位 1 开头，或 86/0086 + 11 位（用户只要中国联系方式）。"""
    d = re.sub(r"\D+", "", digits or "")
    return bool(re.fullmatch(r"1\d{10}", d) or re.fullmatch(r"(?:00)?861\d{10}", d))


def harvest_records(db, gid: str, records: list[dict]) -> tuple[int, int]:
    """一群快照记录 → 分桶落号（非中国号直接丢弃）。返回 (有效帖数, 新增号码数)。"""
    n_posts = n_new = 0
    for rec in records:
        if not isinstance(rec, dict) or rec.get("error"):
            continue  # 私密群/死帖等 BD 侧错误记录
        n_posts += 1
        text = rec.get("content") or (rec.get("original_post") or {}).get("content") or ""
        if not text:
            continue
        author = (rec.get("user_username_raw")
                  or (rec.get("original_post") or {}).get("user_name"))
        info = parse_post(text, text)
        phones = [p for p in info["phones"] if is_cn_number(p.get("number"))]
        if phones:
            n_new += db.save_fb_contacts(rec.get("url") or "", gid,
                                         phones, author=author)
    return n_posts, n_new


def run_pass(db, bd: BDClient, args) -> dict:
    groups = due_groups(db, args.cooldown_hours, args.max_groups,
                        args.zero_cooldown_factor)
    if not groups:
        return {"groups": 0}
    n_delta = sum(1 for _, _, lc in groups if lc)
    log(f"本轮到期群 {len(groups)} 个（每群 {args.posts} 帖；"
        f"增量 {n_delta} 群 / 首次全量 {len(groups) - n_delta} 群）")
    stats = {"groups": 0, "fail": 0, "posts": 0, "new": 0}
    i = 0
    while i < len(groups):
        # 1) 挂起一批 trigger
        in_flight: dict[str, tuple[str, str, float]] = {}  # sid -> (url, gid, t0)
        while i < len(groups) and len(in_flight) < args.conc:
            url, gid, lc = groups[i]
            i += 1
            sid = bd.trigger(url, args.posts, to_start_date(lc, args.date_format))
            if sid:
                in_flight[sid] = (url, gid, time.time())
            else:
                stats["fail"] += 1
                db.mark_fb_group_failed(url)
        # 2) 轮询收割，边收边补触发
        while in_flight:
            time.sleep(POLL_INTERVAL)
            for sid in list(in_flight):
                url, gid, t0 = in_flight[sid]
                st = bd.poll(sid)
                if st == "ready":
                    recs = bd.download(sid)
                    n_posts, n_new = harvest_records(db, gid, recs)
                    db.mark_fb_group_done(url, n_posts, 1 if n_new else 0)
                    stats["groups"] += 1
                    stats["posts"] += n_posts
                    stats["new"] += n_new
                    log(f"  ✓ {url.rsplit('/', 1)[-1]}: {n_posts} 帖, 新增 {n_new} 号"
                        f"（累计 {stats['new']}）")
                    del in_flight[sid]
                elif st in ("failed", "dead") \
                        or time.time() - t0 > SNAPSHOT_TIMEOUT:
                    log(f"  ✗ {url}: snapshot {st}")
                    db.mark_fb_group_failed(url)
                    stats["fail"] += 1
                    del in_flight[sid]
            # 补触发保持满并发
            while i < len(groups) and len(in_flight) < args.conc:
                url, gid, lc = groups[i]
                i += 1
                sid = bd.trigger(url, args.posts,
                                 to_start_date(lc, args.date_format))
                if sid:
                    in_flight[sid] = (url, gid, time.time())
                else:
                    stats["fail"] += 1
                    db.mark_fb_group_failed(url)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="FB 群采集（Bright Data 群 feed）")
    ap.add_argument("--posts", type=int, default=15, help="每群抓最新帖数")
    ap.add_argument("--cooldown-hours", type=float, default=24,
                    help="同一群重抓间隔（小时）")
    ap.add_argument("--max-groups", type=int, default=0,
                    help="每轮最多抓多少群（0=不限）")
    ap.add_argument("--conc", type=int, default=10, help="并发 trigger 数")
    ap.add_argument("--zero-cooldown-factor", type=float, default=3.0,
                    help="零产出群冷却倍数（1=不淘汰）")
    ap.add_argument("--date-format", choices=["us", "iso"], default="us",
                    help="BD start_date 格式：us=MM-DD-YYYY（官方文档），"
                         "iso=YYYY-MM-DD（us 不生效时切换）")
    ap.add_argument("--once", action="store_true", help="跑一轮即退出")
    ap.add_argument("--interval", type=int, default=300,
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

    total_new = 0
    while True:
        try:
            stats = run_pass(db, bd, args)
        except AccountError as e:
            log(f"BD 账号不可用（{e}），10 分钟后重试")
            if args.once:
                return 1
            time.sleep(600)
            continue
        total_new += stats.get("new", 0)
        if stats["groups"] == 0:
            log("无到期群")
        else:
            log(f"本轮：成功 {stats['groups']} 群 / 失败 {stats['fail']}，"
                f"帖 {stats['posts']}，新增号码 {stats['new']}（累计 {total_new}）")
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
