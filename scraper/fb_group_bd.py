#!/usr/bin/env python3
"""FB 群采集（Bright Data 群 feed 版，快脚本）。

替代 fb_group_wa.py 的「Apify 发现 + 本地 CloakBrowser 逐帖渲染」链路：
按群 URL 调 BD 数据集 gd_lz11l67o2cb3r0lkj3（trigger→progress→snapshot
三段式），一次拿群最新 N 帖正文，复用 fetcher parse_post 四桶分号，
落 fb_contacts（number UNIQUE 幂等）。

- 群来源：fb_groups 表（612 群已由 fb_posts 回填；discover_fb 会持续补充），
  按 last_crawled_at 冷却轮抓（默认 24h），never-crawled 优先。
- 两段式群质量筛选（2026-08-11 定案）：首采只画像 --probe-posts 帖（默认
  1 帖，~2.9 credits/群）——BD 记录自带 group_members/真实群名/最新帖
  日期，回填 fb_groups.members + last_post_at；--min-members（默认 100）
  跳过已知低成员小群，--max-stale-days（默认 30）跳过死群（NULL=未知
  不过滤），过关群重抓轮才按 --posts 增量捞帖。首采画像顺带挖最新帖的号。
- 增量抓取（降本核心）：重抓群带 start_date=上次采集日期，BD 只返回
  该日期后的新帖，旧帖不计费（无新帖的群返回 dead_page 错误记录）。
  日期格式默认 MM-DD-YYYY（BD 官方文档），不生效可 --date-format iso 切换。
- 零产出群淘汰：历史零号码的群冷却 ×--zero-cooldown-factor（默认 3 倍），
  预算集中到产号群（靠 fb_contacts.group_id 计数判断，不改表结构）。
- 批量 trigger（2026-08-11 改造）：一次 trigger 塞 --batch-size 个群 URL
  （官方上限 5000/批、输入 1GB；官方 429 排障建议即「合并大批次」），
  同批记录混在一个 snapshot，按帖 permalink 的 /groups/{gid} 段归群；
  同时挂 --conc 个批次轮询收割。计费口径不变：按交付帖数算，与
  trigger 次数无关（官方 FAQ "you only pay for what you get"），
  批量只省请求/轮询开销，不省钱。
- 费用：按成功交付帖数计费（实测 ~2.9 credits/帖 ≈ $2.5/千帖），
  免费 5000 credits/月；控量靠增量抓取 + 零产出淘汰 + --posts /
  --cooldown-hours。
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
BATCH_TIMEOUT = 1800  # 批次快照轮询上限（批次进度按最慢的群算，给足余量）


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

    def trigger(self, items: list[dict]) -> str | None:
        # items：一批群各带各的 url/num_of_posts/start_date（官方示例支持
        # 每 URL 独立参数）；start_date 增量抓取，BD 只回该日期后的新帖
        # （旧帖不计费）。一批一个 snapshot，结果混回、按帖 URL 归群。
        for attempt in range(3):
            s, body = self._http(
                "POST", f"{BD_API}/trigger?dataset_id={BD_DATASET_GROUP_POSTS}"
                        f"&include_errors=true",
                items)
            if s // 100 == 2:
                return (body or {}).get("snapshot_id")
            # 传输层瞬断（SSL EOF 等）重试，HTTP 错误不重试
            if s == -1 and attempt < 2:
                time.sleep(5)
                continue
            log(f"  trigger 失败（{len(items)} 群批次）: HTTP {s} {body}")
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
               zero_factor: float, min_members: int = 0,
               max_stale_days: float = 0) -> list[tuple[str, str, str | None]]:
    """到期待抓群：(url, group_id, last_crawled_at)，never-crawled 优先，再按最久未抓。
    零产出群（历史零号码且已采过）冷却 ×zero_factor，把预算集中到产号群。
    min_members>0 时跳过已知成员数不足的小群；max_stale_days>0 时跳过最新帖
    早于该天数的死群（members/last_post_at 来自 BD 记录回填，NULL=未知不过滤）。
    last_crawled_at 是北京时间字符串，cutoff 同样按北京时间拼。"""
    import datetime
    def cutoff(hours: float) -> str:
        return (datetime.datetime.now()
                - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    sql = (
        "SELECT url, group_id, last_crawled_at FROM ("
        "  SELECT g.url, g.group_id, g.last_crawled_at, g.members, g.last_post_at,"
        "    (SELECT COUNT(*) FROM fb_contacts c WHERE c.group_id = g.group_id)"
        "      AS n_contacts"
        "  FROM fb_groups g WHERE g.status != 'in_progress')"
        " WHERE (last_crawled_at IS NULL"
        "    OR (n_contacts > 0 AND last_crawled_at < ?)"
        "    OR (n_contacts = 0 AND last_crawled_at < ?))")
    params: list = [cutoff(cooldown_hours), cutoff(cooldown_hours * zero_factor)]
    if min_members > 0:
        sql += " AND (members IS NULL OR members >= ?)"
        params.append(min_members)
    if max_stale_days > 0:
        sql += " AND (last_post_at IS NULL OR last_post_at >= ?)"
        params.append(cutoff(max_stale_days * 24))
    sql += " ORDER BY last_crawled_at IS NOT NULL, last_crawled_at"
    rows = db.conn.execute(sql, params).fetchall()
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


def _to_beijing(iso_utc: str) -> str | None:
    """BD date_posted（ISO UTC，如 2026-08-11T04:03:11.000Z）→ 北京时间字符串。"""
    import datetime
    try:
        dt = datetime.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        return (dt + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def harvest_batch(db, batch: list[tuple[str, str]], records: list[dict],
                  stats: dict) -> None:
    """一批群的混合快照记录 → 按帖 permalink 的 /groups/{gid} 段归群，逐群
    分桶落号并 mark done。BD 对批次内每个输入 URL 都会给记录（数据或
    error），error-only 的群（私密/无新帖 dead_page，不计费）记 0 帖 done。
    batch: [(url, gid), ...]"""
    by_gid: dict[str, list[dict]] = {gid: [] for _, gid in batch}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        m = re.search(r"/groups/([^/?#]+)", rec.get("url") or "")
        if m and m.group(1) in by_gid:
            by_gid[m.group(1)].append(rec)
        elif not rec.get("error"):
            # 有效帖却无法归群（如 vanity 群名被 BD 归一成数字 ID），丢号要告警
            log(f"  ⚠ 记录无法归群: {(rec.get('url') or '?')[:100]}")
    for url, gid in batch:
        recs = by_gid[gid]
        # BD 记录自带群元数据（group_name/group_members/date_posted），顺手
        # 回填：members 供 --min-members 精确过滤，last_post_at 供死群过滤
        meta = next((r for r in recs
                     if isinstance(r, dict) and r.get("group_members") is not None),
                    None)
        dates = [d for r in recs if isinstance(r, dict)
                 for d in [_to_beijing(r.get("date_posted") or "")] if d]
        if meta or dates:
            db.update_fb_group_meta(
                url,
                name=meta.get("group_name") if meta else None,
                members=meta.get("group_members") if meta else None,
                last_post_at=max(dates) if dates else None)
        n_posts, n_new = harvest_records(db, gid, recs)
        db.mark_fb_group_done(url, n_posts, 1 if n_new else 0)
        stats["groups"] += 1
        stats["posts"] += n_posts
        stats["new"] += n_new
        log(f"  ✓ {url.rsplit('/', 1)[-1]}: {n_posts} 帖, 新增 {n_new} 号"
            f"（累计 {stats['new']}）")


def run_pass(db, bd: BDClient, args) -> dict:
    groups = due_groups(db, args.cooldown_hours, args.max_groups,
                        args.zero_cooldown_factor, args.min_members,
                        args.max_stale_days)
    if not groups:
        return {"groups": 0}
    n_delta = sum(1 for _, _, lc in groups if lc)
    batches = [groups[i:i + args.batch_size]
               for i in range(0, len(groups), args.batch_size)]
    log(f"本轮到期群 {len(groups)} 个（画像 {len(groups) - n_delta} 群 × "
        f"{min(args.posts, args.probe_posts)} 帖 / 增量 {n_delta} 群 × "
        f"{args.posts} 帖；{len(batches)} 批 × ≤{args.batch_size} 群）")
    stats = {"groups": 0, "fail": 0, "posts": 0, "new": 0}

    def fire(batch) -> str | None:
        items = []
        for url, _gid, lc in batch:
            # 两段式（2026-08-11 定案）：首采只画像 probe_posts 帖（默认 1，
            # 拿 group_members/last_post_at + 顺带挖最新帖的号），members/
            # 死群过滤后，过关群重抓轮才按 --posts 增量捞帖
            n_posts = args.posts if lc else min(args.posts, args.probe_posts)
            item = {"url": url, "num_of_posts": n_posts}
            sd = to_start_date(lc, args.date_format)
            if sd:
                item["start_date"] = sd
            items.append(item)
        return bd.trigger(items)

    bi = 0
    while bi < len(batches):
        # 1) 挂起一批 trigger（一个批次 = 一次 trigger = 一个 snapshot）
        in_flight: dict[str, tuple[list, float]] = {}  # sid -> (batch, t0)
        while bi < len(batches) and len(in_flight) < args.conc:
            batch = batches[bi]
            bi += 1
            sid = fire(batch)
            if sid:
                in_flight[sid] = (batch, time.time())
            else:
                stats["fail"] += len(batch)
                for url, _gid, _lc in batch:
                    db.mark_fb_group_failed(url)
        # 2) 轮询收割，边收边补触发
        while in_flight:
            time.sleep(POLL_INTERVAL)
            for sid in list(in_flight):
                batch, t0 = in_flight[sid]
                st = bd.poll(sid)
                if st == "ready":
                    recs = bd.download(sid)
                    log(f"  批次快照就绪：{len(batch)} 群 / {len(recs)} 条记录")
                    harvest_batch(db, [(u, g) for u, g, _ in batch], recs, stats)
                    del in_flight[sid]
                elif st in ("failed", "dead") \
                        or time.time() - t0 > args.batch_timeout:
                    log(f"  ✗ 批次（{len(batch)} 群）snapshot {st or 'timeout'}，"
                        f"整批置 failed 下轮重试")
                    for url, _gid, _lc in batch:
                        db.mark_fb_group_failed(url)
                    stats["fail"] += len(batch)
                    del in_flight[sid]
            # 补触发保持满并发
            while bi < len(batches) and len(in_flight) < args.conc:
                batch = batches[bi]
                bi += 1
                sid = fire(batch)
                if sid:
                    in_flight[sid] = (batch, time.time())
                else:
                    stats["fail"] += len(batch)
                    for url, _gid, _lc in batch:
                        db.mark_fb_group_failed(url)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="FB 群采集（Bright Data 群 feed）")
    ap.add_argument("--posts", type=int, default=15, help="增量重抓每群抓最新帖数")
    ap.add_argument("--probe-posts", type=int, default=1,
                    help="首采画像帖数（默认 1：拿 group_members/last_post_at + "
                         "顺带挖最新帖的号；过关群重抓轮才按 --posts 增量捞）")
    ap.add_argument("--min-members", type=int, default=100,
                    help="跳过已知成员数低于此值的群（members 来自 BD 记录回填/"
                         "SERP 解析；NULL=未知不过滤；0=关闭过滤）")
    ap.add_argument("--max-stale-days", type=float, default=30,
                    help="跳过最新帖早于该天数的死群（last_post_at 来自 BD 回填；"
                         "NULL=未知不过滤；0=关闭过滤）")
    ap.add_argument("--cooldown-hours", type=float, default=24,
                    help="同一群重抓间隔（小时）")
    ap.add_argument("--max-groups", type=int, default=0,
                    help="每轮最多抓多少群（0=不限）")
    ap.add_argument("--conc", type=int, default=2, help="并发批次数（在飞 snapshot 数）")
    ap.add_argument("--batch-size", type=int, default=50,
                    help="一次 trigger 塞多少群（官方上限 5000/批；"
                         "批次进度按最慢的群算，别贪大）")
    ap.add_argument("--batch-timeout", type=int, default=BATCH_TIMEOUT,
                    help="批次快照轮询超时秒数（超时整批置 failed 下轮重试）")
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
