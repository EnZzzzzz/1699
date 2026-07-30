#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 联系方式抓取脚本（消费者，多 worker 并发版）

从 .cache/1688.db 中原子认领 status='pending' 的店铺，进入其
「联系方式」页解析 联系人/性别(先生女士)/电话/手机/传真/地址。

并发模型:
    - --workers N 个线程，每个线程独立 CloakBrowser 实例 + 独立 ShopDB 连接；
    - 走代理（--proxy）时每个 worker 从青果通道池各领一个通道
      （独立出口 IP，Cookie 按各自出口 IP 隔离，互不串号）；
    - 通道数用 --channels 配置（默认取 proxy_qingguo.CONFIG["channels"]）；
    - 店铺认领走数据库事务（claim_pending_shops），不会重复抓同一家店。

结果处理:
    - 有任何实际字段 → 写入 contacts 表，店铺标记 done
    - 字段全部为空（店铺没填）→ 同样写入 contacts 表备查（含原始文本），
      店铺标记 no_contact，便于统计和后续复核
    - 抓取失败 → 店铺标记 failed（--retry-failed 可重置）

会话链路:
    Cookie 存 SQLite（1688.db cookies 表），按出口 IP 隔离并记录过期时间；
    --proxy 走青果住宅代理时，首次 --proxy --headed 在代理下登录/过滑块，
    退出时自动把最新 Cookie 写回该 IP 名下，保持 Cookie / x5sec / UA /
    出口 IP 一致。

断点续爬:
    进度全部记录在 shops.status，随时 Ctrl+C 或重启脚本，
    下次运行自动把中断残留的 in_progress 重置回 pending 后继续。

用法:
    python3 contact_fetcher.py              # 本批抓 10 个
    python3 contact_fetcher.py -n 30        # 本批抓 30 个
    python3 contact_fetcher.py --headed     # 有头模式
    python3 contact_fetcher.py --proxy      # 走青果住宅代理（默认按通道数并发）
    python3 contact_fetcher.py --proxy -n 100 --workers 3 --channels 5
    python3 contact_fetcher.py --retry-failed  # 先把 failed 重置回 pending 再抓
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]  # 项目根目录

from common import (get_exit_ip, human_pause, launch_browser, save_cookies,
                    scrape_contact)
from database import ShopDB


def worker(worker_id: int, args, proxy_server: str | None,
           state: dict, lock: threading.Lock, stop: threading.Event):
    """单个抓取 worker：独立浏览器 + 独立 DB 连接，认领-抓取-标记循环。"""
    tag = f"[w{worker_id}]"
    db = ShopDB()
    browser = None
    stats = {"ok": 0, "empty": 0, "failed": 0}
    identity = "direct"
    ctx = None
    try:
        browser, page, identity, req_proxies, _ = launch_browser(
            headless=not args.headed, use_proxy=args.proxy, db=db,
            proxy_server=proxy_server, pool_size=args.channels)
        ctx = page.context
        print(f"{tag} 浏览器就绪 (identity={identity})")

        while not stop.is_set():
            # 全批次配额控制：达到 -n 即停
            with lock:
                if state["done"] >= args.num:
                    break
                state["done"] += 1

            shops = db.claim_pending_shops(1)
            if not shops:
                print(f"{tag} 没有待抓取的店铺了")
                break
            shop = shops[0]

            cur_ip = (get_exit_ip(req_proxies) or identity) if args.proxy else identity
            print(f"{tag} {shop['name'] or shop['domain']}  提取IP：{cur_ip}")

            info = scrape_contact(page, shop["domain"], referer=shop["url"])
            if info is None:
                db.mark_shop_failed(shop["domain"])
                stats["failed"] += 1
            elif not any(info[k] for k in
                         ("contact_person", "phone", "mobile", "fax", "address")):
                # 店铺未填任何联系方式：也入 contacts 表备查（含原始文本），
                # 店铺标记 no_contact 便于统计和复核
                raw = info.pop("_raw", None)
                src = info.pop("_source_url", None)
                db.save_contact(shop["domain"], info,
                                source_url=src, raw_text=raw)
                db.mark_shop_no_contact(shop["domain"], bump_attempts=False)
                stats["empty"] += 1
                print(f"{tag}   - 店铺未填写联系方式，已记录空条目并标记 no_contact")
            else:
                raw = info.pop("_raw", None)
                src = info.pop("_source_url", None)
                db.save_contact(shop["domain"], info,
                                source_url=src, raw_text=raw)
                stats["ok"] += 1
                print(f"{tag}   ✓ 联系人={info['contact_person']}"
                      f"({info['gender']}) 电话={info['phone']} "
                      f"手机={info['mobile']} 地址={info['address']}")

            human_pause(3, 7)  # 控制节奏，降低风控概率
            # 每隔一定轮次随机长休息一次，模拟真人连续浏览后的停顿
            done_local = sum(stats.values())
            if (args.rest_every > 0 and done_local % args.rest_every == 0
                    and not stop.is_set()):
                t = random.uniform(args.rest_min, args.rest_max)
                print(f"{tag}   ☕ 已连续抓取 {done_local} 个，随机长休息 {t:.0f}s ...")
                stop.wait(t)  # 可被 Ctrl+C 提前唤醒
    except Exception as e:
        print(f"{tag} [X] worker 异常退出: {e}")
    finally:
        # 退出前把浏览器里的最新 Cookie（含新 x5sec）写回该出口 IP 名下
        if ctx is not None:
            try:
                save_cookies(db, identity, ctx)
            except Exception as e:
                print(f"{tag}   [!] Cookie 回写失败: {e}")
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        with lock:
            state["stats"][worker_id] = stats
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="1688 店铺联系方式抓取（多 worker 并发，断点续爬）")
    ap.add_argument("-n", "--num", type=int, default=10,
                    help="本批次抓取的店铺数量（默认 10）")
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感）")
    ap.add_argument("--retry-failed", action="store_true",
                    help="先把 failed 店铺重置为 pending 再开始抓取")
    ap.add_argument("--rest-every", type=int, default=20,
                    help="每个 worker 每抓取多少个店铺后长休息一次（默认 20，0 关闭）")
    ap.add_argument("--rest-min", type=float, default=60,
                    help="长休息随机时长的下限秒数（默认 60）")
    ap.add_argument("--rest-max", type=float, default=180,
                    help="长休息随机时长的上限秒数（默认 180）")
    ap.add_argument("--proxy", action="store_true",
                    help="走 util/proxy_qingguo.py 的青果住宅代理；"
                         "Cookie 按出口 IP 存 SQLite（记录过期时间），"
                         "退出时自动把最新 Cookie 写回该 IP 名下")
    ap.add_argument("--channels", type=int, default=None,
                    help="青果通道池大小（默认取 proxy_qingguo.CONFIG['channels']）")
    ap.add_argument("--workers", type=int, default=None,
                    help="并发 worker 数；代理模式默认=通道数，直连模式默认 1")
    args = ap.parse_args()

    db = ShopDB()
    if args.retry_failed:
        n = db.reset_failed()
        print(f"[0] 已把 {n} 个 failed 店铺重置回 pending")
    # 上次中断残留的 in_progress 全部放回 pending
    n = db.reset_in_progress()
    if n:
        print(f"[0] 已把 {n} 个中端残留的 in_progress 店铺重置回 pending")

    total_pending = db.count_pending()
    if total_pending == 0:
        print(f"[OK] 没有待抓取的店铺。统计: {db.stats()}")
        print("    先运行 shop_crawler.py 采集更多店铺")
        db.close()
        return 0
    batch = min(args.num, total_pending)
    print(f"[1] 待抓取 {total_pending} 个，本批处理 {batch} 个")

    # ---- 并发度与通道分配 ----
    proxy_servers: list = [None]
    if args.proxy:
        sys.path.insert(0, str(ROOT_DIR / "util"))
        import proxy_qingguo
        pool = proxy_qingguo.get_pool(args.channels)
        n_channels = len(pool.servers())
        workers = args.workers or n_channels
        if workers > n_channels:
            print(f"[!] workers({workers}) > 通道数({n_channels})，"
                  f"部分 worker 将共用通道（共享出口 IP）")
        # 轮询取通道：workers <= 通道数时每个 worker 独占一个通道
        proxy_servers = [pool.acquire() for _ in range(workers)]
    else:
        workers = args.workers or 1
        proxy_servers = [None] * workers
        if workers > 1:
            print(f"[!] 直连模式多 worker 共用本机 IP 和同一份 Cookie，"
                  f"可能触发风控；建议 --proxy 走多通道")

    print(f"[2] 启动 {workers} 个 worker"
          f"（{'代理通道: ' + ', '.join(proxy_servers) if args.proxy else '直连'}）")
    if workers > 1:
        print(f"[!] 注意：CloakBrowser Free  license 仅允许 1 个并发会话，"
              f"超出部分的浏览器会被服务端强制关闭；"
              f"多 worker 需要 Pro license（https://cloakbrowser.dev）")

    state = {"done": 0, "stats": {}}
    lock = threading.Lock()
    stop = threading.Event()
    threads = [
        threading.Thread(target=worker,
                         args=(i, args, proxy_servers[i], state, lock, stop),
                         name=f"fetcher-{i}", daemon=True)
        for i in range(workers)
    ]
    for t in threads:
        t.start()
        time.sleep(1.0)  # 错开浏览器启动，避免资源争抢

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\n[!] 用户中断，等待各 worker 完成当前店铺后退出...")
        stop.set()
        for t in threads:
            t.join(timeout=90)
        print("[!] 进度已保存在数据库，下次运行自动续爬")

    ok = sum(s["ok"] for s in state["stats"].values())
    empty = sum(s["empty"] for s in state["stats"].values())
    failed = sum(s["failed"] for s in state["stats"].values())
    print(f"[OK] 本批完成: 有联系方式 {ok}, 无联系方式 {empty}, 失败 {failed}")
    print(f"    数据库统计: {db.stats()}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
