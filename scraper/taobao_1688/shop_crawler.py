#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 店铺采集脚本（生产者，多 worker 并发版）

流程:
    1. 主线程启动一个引导浏览器，打开 1688 首页提取全部类目链接后关闭
    2. --workers N 个线程并发采集：每个线程独立 CloakBrowser 实例 +
       独立 ShopDB 连接，从共享类目队列中各取类目进入
    3. 在类目搜索结果页中提取出现的店铺（shop*.1688.com + 公司名）
    4. 全部存入 .cache/1688.db，status='pending' 等待联系方式抓取

联系方式抓取由 contact_fetcher.py 完成（消费者，可断点续爬）。

并发模型:
    - 走代理（--proxy）时每个 worker 从青果通道池各领一个通道
      （独立出口 IP，Cookie 按各自出口 IP 隔离，互不串号）；
    - 通道数用 --channels 配置（默认取 proxy_qingguo.CONFIG["channels"]）；
    - 类目队列、入库计数、空轮计数均为线程安全共享状态。

会话链路一致性（按经验执行）:
    - 直连（不走代理）：Cookie 是本机浏览器种下的，出口 IP 保持一致
    - 代理（--proxy）：走青果住宅代理；Cookie 存 SQLite（1688.db cookies 表），
      按出口 IP 隔离并记录过期时间，首次 --proxy --headed 登录/过滑块后
      退出时自动写回该 IP 名下，保持 Cookie / x5sec / UA / 出口 IP 一致
    - UA 与导出 Cookie 的浏览器一致（Chrome 150 / macOS）
    - 低频率、页面间随机延迟

用法:
    python3 shop_crawler.py                  # 随机类目采集入库（每个 worker 1 轮）
    python3 shop_crawler.py -t 1000          # 多轮随机类目，直到库中累计 1000 个
    python3 shop_crawler.py -t 1000 --delay-min 30 --delay-max 90  # 更慢的控频
    python3 shop_crawler.py --category 女装  # 指定类目（只采 1 轮，单 worker）
    python3 shop_crawler.py --headed         # 有头模式（更不易被检测）
    python3 shop_crawler.py --proxy          # 走青果住宅代理（默认按通道数并发）
    python3 shop_crawler.py --proxy -t 2000 --workers 3 --channels 5
    python3 shop_crawler.py --proxy --headed # 首次代理运行：登录/过滑块并保存代理 Cookie

多轮模式说明:
    每个 worker 从共享类目队列中取未采过的类目，轮间随机延迟（默认 15~45 秒）
    控制频率；进度以库中店铺总数为准，Ctrl+C 中断后重新运行会接着补充；
    全局连续 5 轮无新增（疑似被风控）自动停止。
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from pathlib import Path

from common import (HOMEPAGE, get_exit_ip, human_pause, launch_browser,
                    save_cookies)
from database import ShopDB

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]  # 项目根目录


def extract_categories(page) -> list[dict]:
    """从首页提取类目链接（全部类目侧边栏）。"""
    return page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('a[href*="offer_search.htm"]').forEach(a => {
                const m = a.href.match(/keywords=([^&]+)/);
                if (m && a.textContent.trim()) {
                    out.push({name: a.textContent.trim(),
                              keyword: decodeURIComponent(m[1]),
                              url: a.href});
                }
            });
            // 去重
            const seen = new Set();
            return out.filter(c => !seen.has(c.url) && seen.add(c.url));
        }"""
    )


def extract_shops(page) -> list[dict]:
    """从类目搜索结果页提取店铺（shop 域名 + 公司名）。"""
    return page.evaluate(
        """() => {
            const shops = new Map();
            document.querySelectorAll('a[href*="//shop"]').forEach(a => {
                const m = a.href.match(/\\/\\/(shop[0-9a-z]+\\.1688\\.com)/);
                if (m) {
                    const name = a.textContent.trim();
                    const prev = shops.get(m[1]);
                    if (!prev || (name && name.length > prev.length)) {
                        if (name) shops.set(m[1], name);
                    }
                }
            });
            return [...shops.entries()].map(([domain, name]) => ({
                domain, name, url: 'https://' + domain
            }));
        }"""
    )


def worker(worker_id: int, args, proxy_server: str | None, categories: list,
           state: dict, lock: threading.Lock, stop: threading.Event):
    """单个采集 worker：独立浏览器 + 独立 DB 连接，从共享类目队列取类目采集。"""
    tag = f"[w{worker_id}]"
    db = ShopDB()
    browser = None
    identity = "direct"
    ctx = None
    try:
        browser, page, identity, req_proxies, _ = launch_browser(
            headless=not args.headed, use_proxy=args.proxy, db=db,
            proxy_server=proxy_server, pool_size=args.channels)
        ctx = page.context
        cur_ip = (get_exit_ip(req_proxies) or identity) if args.proxy else identity
        print(f"{tag} 浏览器就绪 (identity={identity}，出口 IP: {cur_ip})")

        round_no = 0
        while not stop.is_set():
            # ---- 从共享队列取一个未采过的类目 ----
            with lock:
                if state["total"] >= state["target"]:
                    break
                if not state["queue"]:
                    break
                cat = state["queue"].pop()
                state["rounds"] += 1
                round_no = state["rounds"]

            print(f"{tag} [轮次 {round_no}] 类目: {cat['name']}  "
                  f"(进度 {state['total']}/{state['target']})")
            try:
                page.goto(cat["url"], wait_until="domcontentloaded",
                          timeout=60000, referer=HOMEPAGE)
            except Exception as e:
                print(f"{tag}   [X] 类目页打开失败: {e}，跳过")
                with lock:
                    state["empty_streak"] += 1
                    if state["empty_streak"] >= 5:
                        stop.set()
                continue
            human_pause(4, 8)

            # 模拟滚动加载更多结果
            for _ in range(3):
                page.mouse.wheel(0, random.randint(600, 1200))
                time.sleep(random.uniform(1.0, 2.0))

            shops = extract_shops(page)
            print(f"{tag}   本页提取到 {len(shops)} 个店铺")
            if not shops:
                with lock:
                    state["empty_streak"] += 1
                    streak = state["empty_streak"]
                    if streak >= 5:
                        stop.set()
                print(f"{tag}   [!] 未提取到店铺（全局连续 {streak} 轮），可能被风控")
                continue

            run_id = db.start_run(cat["name"], cat["keyword"])
            inserted = db.upsert_shops(shops, run_id=run_id,
                                       category_keyword=cat["keyword"])
            db.finish_run(run_id, shops_found=len(shops),
                          note=f"new={inserted} worker={worker_id}")
            with lock:
                state["total"] = db.stats()["shops"]
                if inserted == 0:
                    state["empty_streak"] += 1
                    if state["empty_streak"] >= 5:
                        stop.set()
                else:
                    state["empty_streak"] = 0
            print(f"{tag}   入库: 新增 {inserted}，库中累计 "
                  f"{state['total']}/{state['target']}")

            # 轮间控频：长随机延迟，模拟正常浏览节奏
            if state["total"] < state["target"] and not stop.is_set():
                t = random.uniform(args.delay_min, args.delay_max)
                print(f"{tag}   ...轮间等待 {t:.0f}s（控频）")
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
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="1688 类目店铺采集（多 worker 并发，入库 pending）")
    ap.add_argument("--category", default=None,
                    help="指定类目关键词（默认从首页类目中随机选；指定后单 worker 只采 1 轮）")
    ap.add_argument("-t", "--target", type=int, default=0,
                    help="目标店铺总数（按库中累计数计算）。0=每个 worker 只采 1 个类目；"
                         "例如 -t 1000 会持续多轮随机类目采集，直到库中达到 1000")
    ap.add_argument("--delay-min", type=float, default=15.0,
                    help="多轮模式轮间最小延迟秒数（默认 15）")
    ap.add_argument("--delay-max", type=float, default=45.0,
                    help="多轮模式轮间最大延迟秒数（默认 45）")
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感）")
    ap.add_argument("--proxy", action="store_true",
                    help="走 util/proxy_qingguo.py 的青果住宅代理；"
                         "Cookie 按出口 IP 存 SQLite（记录过期时间），"
                         "该 IP 无记录时从本机 Cookie 种子导入并警告错配风险，"
                         "退出时自动把最新 Cookie 写回该 IP 名下")
    ap.add_argument("--channels", type=int, default=None,
                    help="青果通道池大小（默认取 proxy_qingguo.CONFIG['channels']）")
    ap.add_argument("--workers", type=int, default=None,
                    help="并发 worker 数；代理模式默认=通道数，直连模式默认 1")
    args = ap.parse_args()

    # ---- 并发度与通道分配 ----
    if args.proxy:
        sys.path.insert(0, str(ROOT_DIR / "util"))
        import proxy_qingguo
        pool = proxy_qingguo.get_pool(args.channels)
        n_channels = len(pool.servers())
        workers = 1 if args.category else (args.workers or n_channels)
        if workers > n_channels:
            print(f"[!] workers({workers}) > 通道数({n_channels})，"
                  f"部分 worker 将共用通道（共享出口 IP）")
        proxy_servers = [pool.acquire() for _ in range(workers)]
    else:
        workers = 1 if args.category else (args.workers or 1)
        proxy_servers = [None] * workers
        if workers > 1:
            print(f"[!] 直连模式多 worker 共用本机 IP 和同一份 Cookie，"
                  f"可能触发风控；建议 --proxy 走多通道")

    db = ShopDB()
    total = db.stats()["shops"]
    # 不指定 -t 时每个 worker 采 1 轮（目标按经验值每轮约 30 个估算下限）
    target = args.target or (total + workers)
    print(f"[1] 当前库中 {total} 个店铺，目标 {target} 个，{workers} 个 worker")
    if total >= target:
        print(f"[OK] 已达到目标，无需采集")
        db.close()
        return 0

    # ---- 引导浏览器：打开首页提取类目（用完即关） ----
    browser, page, identity, _, _ = launch_browser(
        headless=not args.headed, use_proxy=args.proxy, db=db,
        proxy_server=proxy_servers[0], pool_size=args.channels)
    print(f"[2] 引导浏览器已启动 (headless={not args.headed}"
          f"{', proxy=' + identity if args.proxy else ''})，打开首页 {HOMEPAGE}")
    try:
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        human_pause(3, 6)
        categories = extract_categories(page)
        if not categories:
            print("[X] 首页未提取到类目，可能被风控，请检查")
            return 1
        print(f"    提取到 {len(categories)} 个类目: "
              f"{[c['name'] for c in categories[:8]]}...")
    finally:
        try:
            save_cookies(db, identity, page.context)
        except Exception as e:
            print(f"    [!] Cookie 回写失败: {e}")
        browser.close()

    # ---- 组装共享类目队列 ----
    if args.category:
        cat = next((c for c in categories if c["keyword"] == args.category),
                   {"name": args.category, "keyword": args.category,
                    "url": f"https://s.1688.com/selloffer/offer_search.htm"
                           f"?charset=utf8&keywords={args.category}"})
        queue = [cat]
    else:
        queue = categories[:]
        random.shuffle(queue)

    state = {
        "queue": queue,
        "total": total,
        "target": target,
        "rounds": 0,
        "empty_streak": 0,  # 全局连续无新增轮数，防死循环
    }
    lock = threading.Lock()
    stop = threading.Event()
    threads = [
        threading.Thread(target=worker,
                         args=(i, args, proxy_servers[i], categories,
                               state, lock, stop),
                         name=f"crawler-{i}", daemon=True)
        for i in range(workers)
    ]
    print(f"[3] 启动 {workers} 个采集 worker"
          f"（{'代理通道: ' + ', '.join(proxy_servers) if args.proxy else '直连'}）")
    if workers > 1:
        print(f"[!] 注意：CloakBrowser Free  license 仅允许 1 个并发会话，"
              f"超出部分的浏览器会被服务端强制关闭；"
              f"多 worker 需要 Pro license（https://cloakbrowser.dev）")
    for t in threads:
        t.start()
        time.sleep(1.0)  # 错开浏览器启动，避免资源争抢

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\n[!] 用户中断，等待各 worker 完成当前轮次后退出...")
        stop.set()
        for t in threads:
            t.join(timeout=90)
        print("[!] 已入库数据不受影响，可随时再跑继续补充")

    final_total = db.stats()["shops"]
    print(f"[OK] 采集结束: 共 {state['rounds']} 轮，库中 {final_total} 个店铺")
    print(f"    数据库统计: {db.stats()}")
    print(f"    运行 contact_fetcher.py 抓取联系方式")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
