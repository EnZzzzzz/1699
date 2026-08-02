#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""x5sec 粘性验证脚本（x5sec_sticky_test.py）

回答两个决定架构走向的问题：

1. replay 模式（几分钟出结果）：
   x5sec 是否严格绑 IP？—— 取库里一枚仍有效的 x5sec，从**本机直连**
   （与签发时完全不同的网络出口）带全套 Cookie 访问联系方式页：
     - 通过 → x5sec 不绑 IP（至少不严格绑），跨 IP 迁移可行
     - 被拦 → 绑 IP 或绑会话/指纹（注意本模式是指纹复现的，排除指纹干扰）
   ⚠️ 风险：被测令牌可能正被生产 worker 使用，跨 IP 并发重放有烧令牌
   风险。默认自动挑选「剩余寿命最短」的活令牌（反正快死，损失最小），
   只访问一次页面。建议在 worker 换 IP 的空窗期跑。

2. survive 模式（约 30~40 分钟，最有价值）：
   会话能否撑过青果 30 分钟强制轮换？—— 自起一个浏览器走一条**空闲**
   青果通道，headed 模式人工过证后保持会话：
     - 每 3 分钟轻量访问店铺首页，触发 x5sec 滚动续期；
     - 每 60 秒查一次出口 IP；
     - 检测到 IP 轮换后，立刻用**同一会话**再访问联系方式页。
   结果直接决定工程方案：
     - 轮换后仍通过 → 「IP 稳定运行」不需要换代理产品，只需让引擎在
       检测到轮换后**不 relaunch、继续用原会话**即可；
     - 轮换后必被拦 → x5sec 严格绑 IP，只能换长时驻留代理
       （独享代理 0~24h / 长效静态 IP 1 天起）。

用法：
    python3 x5sec_sticky_test.py list                 # 看库里活令牌（只读）
    python3 x5sec_sticky_test.py replay [--identity X.X.X.X] [--url SHOP_URL]
    python3 x5sec_sticky_test.py survive [--server tunpool-xxx.qg.net:port]
                                        [--keepalive-min 3] [--max-min 45]

报告写入 .cache/x5sec_sticky_test_<时间戳>.json
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cloakbrowser import launch  # noqa: E402

from common import (  # noqa: E402
    HOMEPAGE,
    _fingerprint_args,
    _log,
    get_exit_ip,
    load_license_key,
    page_block_reason,
    save_cookies,
)
from database import ShopDB  # noqa: E402

CACHE_DIR = HERE.parent.parent / ".cache"
TEST_CONTACT_URL = "https://shop317093590i710.1688.com/page/contactinfo.htm"


# ---------------------------------------------------------------- 工具

def _live_x5sec(db: ShopDB) -> list[dict]:
    """库里仍有效的 x5sec 令牌，按剩余寿命升序（快死的排前面）。"""
    now = time.time()
    rows = []
    for r in db.conn.execute(
            "SELECT identity, value, expires, updated_at FROM cookies"
            " WHERE name='x5sec' AND expires > ?", (now,)):
        rows.append({"identity": r[0], "value": r[1], "expires": r[2],
                     "updated_at": r[3], "remain_min": (r[2] - now) / 60})
    rows.sort(key=lambda x: x["remain_min"])
    return rows


def _kit_of(db: ShopDB, identity: str) -> str | None:
    """查该 identity 最近一次播种用的种子名（指纹要与身份配套）。"""
    r = db.conn.execute(
        "SELECT detail FROM ip_events WHERE identity=? AND event='seed'"
        " ORDER BY id DESC LIMIT 1", (identity,)).fetchone()
    if r and "kit=" in r[0]:
        return r[0].split("kit=")[1].split()[0]
    return None


def _report(name: str, data: dict):
    CACHE_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = CACHE_DIR / f"x5sec_sticky_test_{name}_{ts}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"\n[report] 已写入 {path}")


def _x5sec_of(ctx) -> dict | None:
    for c in ctx.cookies(["https://www.1688.com"]):
        if c["name"] == "x5sec":
            return c
    return None


def _visit_and_judge(page, url: str) -> tuple[str, str]:
    """访问 URL，返回 (判定, 详情)。判定: PASS / BLOCKED / ERROR"""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
    except Exception as e:
        return "ERROR", str(e).splitlines()[0][:150]
    reason = page_block_reason(page)
    if reason:
        return "BLOCKED", reason
    return "PASS", page.url


# ---------------------------------------------------------------- 模式

def mode_list(db: ShopDB):
    rows = _live_x5sec(db)
    if not rows:
        print("库里没有仍有效的 x5sec（全部过期）。")
        return
    print(f"共 {len(rows)} 枚活令牌：")
    for r in rows:
        kit = _kit_of(db, r["identity"])
        print(f"  {r['identity']:<16} 剩余 {r['remain_min']:5.1f} 分钟"
              f"  更新于 {r['updated_at']}  种子 {kit or '未知'}")


def mode_replay(db: ShopDB, args):
    """跨 IP 重放：带活 x5sec 从本机直连访问联系方式页。"""
    rows = _live_x5sec(db)
    if args.identity:
        rows = [r for r in rows if r["identity"] == args.identity]
    if not rows:
        sys.exit("[X] 没有可用的活 x5sec（或指定 identity 无活令牌）")
    target = rows[0]  # 剩余寿命最短，烧掉损失最小
    identity = target["identity"]
    kit = _kit_of(db, identity)
    print(f"[*] 被测令牌: identity={identity}，剩余 {target['remain_min']:.1f}"
          f" 分钟，配套种子 {kit or '未知（按 identity 取指纹）'}")
    print(f"[*] 测试出口: 本机直连（{get_exit_ip(None) or '查询失败'}）"
          f" —— 与签发出口 {identity} 完全不同的网络")

    cookies = db.load_cookies(identity)
    if not any(c["name"] == "x5sec" for c in cookies):
        sys.exit("[X] load_cookies 返回的 Cookie 里没有 x5sec（可能刚过期）")
    print(f"[*] 已加载 {len(cookies)} 个 Cookie（含 x5sec）")

    browser = launch(headless=False, license_key=load_license_key(),
                     humanize=True, locale="zh-CN", timezone="Asia/Shanghai",
                     stealth_args=False,
                     args=_fingerprint_args(kit or identity))
    try:
        ctx = browser.new_context(locale="zh-CN")
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        # 先逛首页模拟真实轨迹（直接深链是爬虫特征）
        print(f"[*] 预热首页 {HOMEPAGE} ...")
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
        warm_block = page_block_reason(page)
        print(f"[*] 首页判定: {'命中风控 ' + warm_block if warm_block else '正常'}")

        url = args.url or TEST_CONTACT_URL
        print(f"[*] 访问联系方式页 {url} ...")
        verdict, detail = _visit_and_judge(page, url)
        print(f"\n===== 结果: {verdict} =====")
        if verdict == "PASS":
            print("→ x5sec 在本机直连（完全不同出口）下仍被认可："
                    "不严格绑 IP。顺序跨 IP 迁移（轮换场景）大概率可行。")
        elif verdict == "BLOCKED":
            print(f"→ 被拦（{detail}）。注意排除干扰项：指纹已按种子复现，"
                    "所以大概率是「绑 IP」或「跨 IP 并发重放被检测」。"
                    "可在 worker 换 IP 空窗期（旧令牌未被并发使用时）复测确认。")
        _report("replay", {"identity": identity, "kit": kit,
                           "exit": "direct", "url": url,
                           "warmup_block": warm_block,
                           "verdict": verdict, "detail": detail})
    finally:
        browser.close()


def _pick_free_tunnel(db: ShopDB) -> str | None:
    """从通道缓存里挑一条最近 10 分钟没被生产 worker 使用的隧道。"""
    cache_file = CACHE_DIR / "qingguo_tunnel.json"
    try:
        servers = json.loads(cache_file.read_text())["servers"]
    except Exception:
        return None
    busy = {r[0] for r in db.conn.execute(
        "SELECT detail FROM ip_events WHERE event='launch'"
        " AND created_at > datetime('now','localtime','-10 minutes')")}
    free = [s for s in servers if s not in busy]
    return free[0] if free else None


def mode_survive(db: ShopDB, args):
    """跨轮换存活：同一会话撑过青果 30 分钟轮换。"""
    server = args.server or _pick_free_tunnel(db)
    if not server:
        sys.exit("[X] 找不到空闲通道（所有隧道近 10 分钟都有 worker 在用）。"
                 "请用 --server 显式指定一条空闲隧道，或停生产后再跑。")
    print(f"[*] 使用隧道: {server}")

    sys.path.insert(0, str(HERE.parent.parent / "util"))
    import proxy_qingguo
    from urllib.parse import urlparse
    url = proxy_qingguo.get_pool().make_proxies(server)["https"]
    p = urlparse(url)
    proxy_conf = {"server": f"{p.scheme}://{p.hostname}:{p.port}",
                  "username": p.username, "password": p.password}
    req_proxies = {"http": url, "https": url}

    exit_ip = get_exit_ip(req_proxies)
    if not exit_ip:
        sys.exit("[X] 查询出口 IP 失败，隧道疑似不可用")
    identity = exit_ip
    print(f"[*] 当前出口 IP: {identity}")

    browser = launch(headless=False, license_key=load_license_key(),
                     humanize=True, locale="zh-CN", timezone="Asia/Shanghai",
                     stealth_args=False, args=_fingerprint_args(identity),
                     proxy=proxy_conf, geoip=True)
    t0 = time.time()
    log_lines = []

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line)
        log_lines.append(line)

    try:
        ctx = browser.new_context(locale="zh-CN")
        page = ctx.new_page()

        # ---- 阶段 1: 白板启动 + 人工过证 ----
        log(f"预热首页（白板会话，大概率弹滑块）…")
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        if page_block_reason(page):
            log("👉 命中风控，请在浏览器窗口手动拖滑块（每 5s 检测，"
                "最长等 15 分钟）…")
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                time.sleep(5)
                try:
                    if page_block_reason(page) is None:
                        break
                except Exception:
                    sys.exit("[X] 浏览器异常退出")
            else:
                sys.exit("[X] 15 分钟内未过证，放弃")
        x5 = _x5sec_of(ctx)
        if not x5:
            sys.exit("[X] 过证后会话里没有 x5sec，无法继续实验")
        save_cookies(db, identity, ctx)
        log(f"✓ 已持有 x5sec（过期时间 {time.strftime('%H:%M:%S', time.localtime(x5['expires']))}），"
            f"进入保活阶段，等待青果轮换…")

        # ---- 阶段 2: 保活 + 监控轮换 ----
        keepalive_url = args.url or TEST_CONTACT_URL
        rotations = []
        last_keepalive = 0.0
        deadline = t0 + args.max_min * 60
        cur_ip = identity
        while time.time() < deadline:
            time.sleep(60)
            # 每分钟查出口 IP
            new_ip = get_exit_ip(req_proxies)
            if new_ip and new_ip != cur_ip:
                log(f"🔄 检测到出口轮换: {cur_ip} → {new_ip}")
                x5_before = _x5sec_of(ctx)
                verdict, detail = _visit_and_judge(page, keepalive_url)
                x5_after = _x5sec_of(ctx)
                rotations.append({
                    "from": cur_ip, "to": new_ip,
                    "at": time.strftime("%H:%M:%S"),
                    "x5sec_before": x5_before, "x5sec_after": x5_after,
                    "verdict": verdict, "detail": detail})
                log(f"    轮换后同会话访问联系方式页: {verdict}（{detail}）")
                if x5_after and x5_before:
                    log(f"    x5sec 值变化: "
                        f"{'变了' if x5_after['value'] != x5_before['value'] else '没变'}")
                cur_ip = new_ip
                identity = new_ip
                save_cookies(db, identity, ctx)
                if verdict == "BLOCKED":
                    log("⚠ 轮换后立刻被拦 —— 停止实验（再继续也是烧 IP）")
                    break
            # 每 keepalive_min 分钟轻量访问，触发滚动续期
            if time.time() - last_keepalive > args.keepalive_min * 60:
                v, d = _visit_and_judge(page, keepalive_url)
                x5 = _x5sec_of(ctx)
                exp = (time.strftime('%H:%M:%S', time.localtime(x5['expires']))
                       if x5 else "无 x5sec")
                log(f"保活访问: {v}，x5sec 有效期至 {exp}")
                save_cookies(db, cur_ip, ctx)
                last_keepalive = time.time()
                if v == "BLOCKED":
                    log("⚠ 保活期间被拦（未轮换也被拦 = 令牌自然死亡/复验），"
                        "记录并继续观察")
                    if page_block_reason(page):
                        log("👉 可在窗口手动过证，脚本继续监控…")

        # ---- 汇总 ----
        print("\n===== 实验汇总 =====")
        if not rotations:
            print(f"运行 {(time.time() - t0) / 60:.0f} 分钟内未发生轮换"
                  f"（青果未到 30 分钟周期？），建议 --max-min 加大重跑")
        for i, r in enumerate(rotations, 1):
            print(f"第 {i} 次轮换 {r['from']} → {r['to']}: {r['verdict']}")
        if rotations:
            passed = sum(1 for r in rotations if r["verdict"] == "PASS")
            if passed == len(rotations):
                print("→ 结论: 会话可跨轮换存活！工程上把「检测到 IP 轮换后"
                        " relaunch 换会话」改为「保留原会话继续用」即可，"
                        "不需要换代理产品。")
            elif passed == 0:
                print("→ 结论: x5sec 严格绑 IP，轮换即死。只能靠长时驻留代理"
                        "（独享代理 0~24h 可调 / 长效静态 IP 1 天起）。")
            else:
                print(f"→ 结论: {passed}/{len(rotations)} 次轮换后存活，"
                        "部分存活，需更多样本（可能与轮换间隔/活跃度有关）。")
        _report("survive", {"server": server, "first_ip": exit_ip,
                            "rotations": rotations, "log": log_lines})
    finally:
        browser.close()


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["list", "replay", "survive"])
    ap.add_argument("--identity", help="replay: 指定用哪个 identity 的活令牌")
    ap.add_argument("--url", help="联系方式页 URL（默认用最近抓过的店铺）")
    ap.add_argument("--server", help="survive: 指定隧道入口 host:port")
    ap.add_argument("--keepalive-min", type=float, default=3.0,
                    help="survive: 保活访问间隔（分钟，默认 3）")
    ap.add_argument("--max-min", type=float, default=45.0,
                    help="survive: 最长运行时间（分钟，默认 45）")
    args = ap.parse_args()

    db = ShopDB()
    if args.mode == "list":
        mode_list(db)
    elif args.mode == "replay":
        mode_replay(db, args)
    else:
        mode_survive(db, args)


if __name__ == "__main__":
    main()
