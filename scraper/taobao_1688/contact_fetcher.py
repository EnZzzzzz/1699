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

批次与防风控:
    - 采满一批（-n 个）后所有 worker 强制休息 --batch-rest 秒
      （默认 900 = 15 分钟，±10% 抖动），然后自动开下一批，
      直到 pending 抓完或达到 --max-batches；
    - 代理模式下每个 worker 每次抓取前检查出口 IP：
      青果出口 IP 每 30 分钟轮换一次，发现 IP 已轮换或隧道失效时，
      自动重启浏览器获取新 IP（--ip-retry 次重试，退避间隔），
      新 IP 的 Cookie 按新 identity 重新绑定，避免会话错配；
    - 抓取时检测风控拦截（跳转登录/安全中心/x5sec 滑块/页面空白等），
      疑似被拦截时换 IP 重试同一店铺（--block-retry 次）；
      连续失败达到 --max-consecutive-fail 次（默认 5）判定被风控，
      立即中止整个任务，当前店铺留在 in_progress，下次运行自动放回 pending。

用法:
    python3 contact_fetcher.py              # 每批 10 个，批间休息 15 分钟
    python3 contact_fetcher.py -n 30 --batch-rest 600
    python3 contact_fetcher.py --headed     # 有头模式
    python3 contact_fetcher.py --proxy      # 走青果住宅代理（默认按通道数并发）
    python3 contact_fetcher.py --proxy -n 100 --workers 3 --channels 5
    python3 contact_fetcher.py --proxy -n 50 --max-batches 4  # 最多采 4 批
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


def relaunch_browser(tag: str, args, db: ShopDB, proxy_server: str | None,
                     old_browser, old_ctx, old_identity: str,
                     stop: threading.Event):
    """关闭旧浏览器（先回写 Cookie），重开新实例以绑定新出口 IP。

    青果出口 IP 每 30 分钟轮换一次，轮换后旧 identity 的 Cookie 与新
    出口 IP 错配，必须重启浏览器让 launch_browser 重新查询出口 IP 并
    按新 identity 加载/绑定 Cookie。最多重试 args.ip_retry 次（线性
    退避），全部失败抛 RuntimeError。
    """
    if old_ctx is not None:
        try:
            save_cookies(db, old_identity, old_ctx)
        except Exception as e:
            print(f"{tag}   [!] 旧 Cookie 回写失败: {e}")
    if old_browser is not None:
        try:
            old_browser.close()
        except Exception:
            pass

    last_err = None
    for attempt in range(1, args.ip_retry + 1):
        if stop.is_set():
            raise RuntimeError("用户中断")
        try:
            browser, page, identity, req_proxies, _ = launch_browser(
                headless=not args.headed, use_proxy=args.proxy, db=db,
                proxy_server=proxy_server, pool_size=args.channels)
            print(f"{tag} 浏览器已重启，新 identity={identity}")
            return browser, page, identity, req_proxies
        except (Exception, SystemExit) as e:
            last_err = e
            backoff = min(30 * attempt, 120)
            print(f"{tag}   [!] 获取新 IP 第 {attempt}/{args.ip_retry} 次失败: "
                  f"{e}，{backoff}s 后重试...")
            stop.wait(backoff)
    raise RuntimeError(f"重试 {args.ip_retry} 次仍无法获取新 IP: {last_err}")


def check_ip_fresh(tag: str, req_proxies: dict, identity: str) -> tuple:
    """检查当前出口 IP 是否仍有效，返回 (need_relaunch, cur_ip, reason)。

    青果出口 IP 每 30 分钟轮换一次：查询到的 IP 与 identity 不一致即
    视为已过期；查询失败先短重试 3 次确认隧道是否真的失效。
    """
    cur_ip = get_exit_ip(req_proxies)
    if cur_ip is None:
        for _ in range(3):
            time.sleep(5)
            cur_ip = get_exit_ip(req_proxies)
            if cur_ip:
                break
    if cur_ip is None:
        return True, None, "出口 IP 查询失败，隧道疑似失效"
    if cur_ip != identity:
        return True, cur_ip, f"出口 IP 已轮换（{identity} -> {cur_ip}）"
    return False, cur_ip, ""


def worker(worker_id: int, args, proxy_server: str | None,
           state: dict, lock: threading.Lock, stop: threading.Event):
    """单个抓取 worker：独立浏览器 + 独立 DB 连接，认领-抓取-标记循环。"""
    tag = f"[w{worker_id}]"
    db = ShopDB()
    browser = None
    stats = {"ok": 0, "empty": 0, "failed": 0}
    consecutive_fail = 0  # 连续失败计数（含换 IP 重试），超限中止整个任务
    identity = "direct"
    ctx = None
    req_proxies = None
    try:
        browser, page, identity, req_proxies, _ = launch_browser(
            headless=not args.headed, use_proxy=args.proxy, db=db,
            proxy_server=proxy_server, pool_size=args.channels)
        ctx = page.context
        print(f"{tag} 浏览器就绪 (identity={identity})")

        while not stop.is_set():
            # ---- 批次配额：采满一批后强制休息，再自动开下一批 ----
            while True:
                with lock:
                    if state["done"] < args.num:
                        state["done"] += 1
                        wait_for = 0.0
                        batch_no = state["batch"]
                    elif (args.max_batches and state["batch"] >= args.max_batches) \
                            or db.count_pending() == 0:
                        wait_for = -1.0  # 达到批次上限或没有剩余店铺，收工
                        batch_no = state["batch"]
                    else:
                        now = time.time()
                        if state["rest_until"] <= now:
                            # 第一个发现配额满的 worker 决定本次休息时长（±10% 抖动）
                            state["rest_until"] = now + random.uniform(
                                args.batch_rest * 0.9, args.batch_rest * 1.1)
                        wait_for = state["rest_until"] - now
                        batch_no = state["batch"]
                if wait_for == 0.0:
                    break
                if wait_for < 0:
                    print(f"{tag} 第 {batch_no} 批采满，"
                          f"已达批次上限或没有剩余店铺，收工")
                    return  # finally 会保存 Cookie、关闭浏览器
                print(f"{tag} ⏸ 第 {batch_no} 批已采满 {args.num} 个，"
                      f"强制休息 {wait_for / 60:.1f} 分钟（防风控）...")
                if stop.wait(wait_for):
                    return  # 用户中断
                with lock:
                    if state["done"] >= args.num:  # 由第一个醒来的 worker 开新批次
                        state["done"] = 0
                        state["batch"] += 1
                    batch_no = state["batch"]
                print(f"{tag} ▶ 休息结束，开始第 {batch_no} 批")

            shops = db.claim_pending_shops(1)
            if not shops:
                print(f"{tag} 没有待抓取的店铺了")
                break
            shop = shops[0]

            # ---- 出口 IP 过期检查（青果每 30 分钟轮换一次出口）----
            if args.proxy:
                need_relaunch, cur_ip, reason = check_ip_fresh(
                    tag, req_proxies, identity)
                if need_relaunch:
                    print(f"{tag} 🔄 {reason}，重启浏览器获取新 IP ...")
                    browser, page, identity, req_proxies = relaunch_browser(
                        tag, args, db, proxy_server, browser, ctx, identity, stop)
                    ctx = page.context
                print(f"{tag} {shop['name'] or shop['domain']}  提取IP：{identity}")
            else:
                print(f"{tag} {shop['name'] or shop['domain']}  提取IP：{identity}")

            # ---- 抓取（疑似风控时换 IP 重试；连续失败超限则中止任务）----
            block_retried = 0
            while True:
                info = scrape_contact(page, shop["domain"], referer=shop["url"])
                block_reason = info.pop("_blocked", None) if info else None
                if info is not None and not block_reason:
                    consecutive_fail = 0  # 抓到了，连续失败清零
                    break

                # 失败或疑似被风控拦截
                consecutive_fail += 1
                reason = block_reason or "页面加载失败（疑似风控拦截）"
                if consecutive_fail >= args.max_consecutive_fail:
                    print(f"{tag} [X] 已连续失败 {consecutive_fail} 次"
                          f"（最近一次: {reason}），判定被风控，中止整个任务")
                    print(f"{tag}     店铺 {shop['domain']} 留在 in_progress，"
                          f"下次运行自动放回 pending")
                    stop.set()
                    return  # finally 会保存 Cookie、关闭浏览器

                if block_retried < args.block_retry:
                    block_retried += 1
                    print(f"{tag} ⚠ {reason}（连续失败 "
                          f"{consecutive_fail}/{args.max_consecutive_fail}），"
                          f"第 {block_retried}/{args.block_retry} 次换 IP 重试...")
                    if args.proxy:
                        try:
                            browser, page, identity, req_proxies = \
                                relaunch_browser(
                                    tag, args, db, proxy_server,
                                    browser, ctx, identity, stop)
                            ctx = page.context
                        except RuntimeError as e:
                            print(f"{tag} [X] 换 IP 失败: {e}，中止整个任务")
                            stop.set()
                            return
                    else:
                        # 直连模式无法换 IP，退避等待后重试
                        backoff = min(60 * block_retried, 300)
                        print(f"{tag}   直连模式无法换 IP，退避 {backoff}s 后重试...")
                        stop.wait(backoff)
                    continue  # 重试同一店铺

                # 换 IP 重试仍失败：标记 failed，放过这家继续下一家
                print(f"{tag}   [X] 换 IP 重试 {args.block_retry} 次仍失败，"
                      f"标记 failed 跳过（{reason}）")
                db.mark_shop_failed(shop["domain"])
                stats["failed"] += 1
                info = None
                break

            if info is None:
                pass  # 上面已标记 failed
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
                    help="每批抓取的店铺数量（默认 10）；采满一批后强制休息再开下一批")
    ap.add_argument("--batch-rest", type=float, default=900,
                    help="每批采满后的强制休息秒数（默认 900=15 分钟，±10%% 抖动）")
    ap.add_argument("--max-batches", type=int, default=0,
                    help="最多采集多少批（默认 0=不限，抓完 pending 为止）")
    ap.add_argument("--ip-retry", type=int, default=3,
                    help="代理出口 IP 过期后重启浏览器获取新 IP 的重试次数（默认 3）")
    ap.add_argument("--block-retry", type=int, default=2,
                    help="单店疑似被风控拦截时换 IP 重试的次数（默认 2）")
    ap.add_argument("--max-consecutive-fail", type=int, default=5,
                    help="连续失败多少次后判定被风控并中止整个任务（默认 5）")
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
    ap.add_argument("--channels", type=int, default=1,
                    help="青果通道池大小（默认取 proxy_qingguo.CONFIG['channels']）")
    ap.add_argument("--workers", type=int, default=1,
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
    est_batches = -(-total_pending // args.num)  # 向上取整
    if args.max_batches:
        est_batches = min(est_batches, args.max_batches)
    print(f"[1] 待抓取 {total_pending} 个，每批 {args.num} 个"
          f"（约 {est_batches} 批），批间强制休息 {args.batch_rest / 60:.0f} 分钟")

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

    state = {"done": 0, "batch": 1, "rest_until": 0.0, "stats": {}}
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
