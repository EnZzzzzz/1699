#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 店铺采集脚本（生产者）

流程:
    1. 用 CloakBrowser（隐形 Chromium）加载 .cache/cookies_1688.json 中的 Cookie
    2. 打开 1688 首页，从「全部类目」提取全部类目链接
    3. 随机选 1 个类目进入（也可用 --category 指定关键词）
    4. 在类目搜索结果页中提取出现的店铺（shop*.1688.com + 公司名）
    5. 全部存入 .cache/1688.db，status='pending' 等待联系方式抓取

联系方式抓取由 contact_fetcher.py 完成（消费者，可断点续爬）。

会话链路一致性（按经验执行）:
    - 直连（不走代理）：Cookie 是本机浏览器种下的，出口 IP 保持一致
    - 代理（--proxy）：走青果住宅代理；Cookie 存 SQLite（1688.db cookies 表），
      按出口 IP 隔离并记录过期时间，首次 --proxy --headed 登录/过滑块后
      退出时自动写回该 IP 名下，保持 Cookie / x5sec / UA / 出口 IP 一致
    - UA 与导出 Cookie 的浏览器一致（Chrome 150 / macOS）
    - 单浏览器、低频率、页面间随机延迟

用法:
    python3 shop_crawler.py                  # 随机 1 个类目采集入库
    python3 shop_crawler.py -t 1000          # 多轮随机类目，直到库中累计 1000 个
    python3 shop_crawler.py -t 1000 --delay-min 30 --delay-max 90  # 更慢的控频
    python3 shop_crawler.py --category 女装  # 指定类目（只采 1 轮）
    python3 shop_crawler.py --headed         # 有头模式（更不易被检测）
    python3 shop_crawler.py --proxy          # 走青果住宅代理
    python3 shop_crawler.py --proxy --headed # 首次代理运行：登录/过滑块并保存代理 Cookie

多轮模式说明:
    每轮随机选一个未采过的类目，轮间随机延迟（默认 15~45 秒）控制频率；
    进度以库中店铺总数为准，Ctrl+C 中断后重新运行会接着补充；
    连续 5 轮无新增（疑似被风控）自动停止。
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from common import (HOMEPAGE, get_exit_ip, human_pause, launch_browser,
                    save_cookies)
from database import ShopDB


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


def main() -> int:
    ap = argparse.ArgumentParser(description="1688 类目店铺采集（入库 pending）")
    ap.add_argument("--category", default=None,
                    help="指定类目关键词（默认从首页类目中随机选 1 个）")
    ap.add_argument("-t", "--target", type=int, default=0,
                    help="目标店铺总数（按库中累计数计算）。0=只采 1 个类目；"
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
    args = ap.parse_args()

    db = ShopDB()
    browser, page, identity, _ = launch_browser(headless=not args.headed,
                                                use_proxy=args.proxy, db=db)
    print(f"[1] CloakBrowser 已启动 (headless={not args.headed}"
          f"{', proxy=' + identity if args.proxy else ''})")
    # 打印当前出口 IP（代理模式下 identity 即出口 IP，直连模式实时查询）
    cur_ip = identity if args.proxy else (get_exit_ip() or "查询失败")
    print(f"    [ip] 当前出口 IP: {cur_ip}")

    try:
        # ---- 首页：取类目 ----
        print(f"[2] 打开首页 {HOMEPAGE}")
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        human_pause(3, 6)

        categories = extract_categories(page)
        if not categories:
            sys.exit("[X] 首页未提取到类目，可能被风控，请检查")
        print(f"    提取到 {len(categories)} 个类目: "
              f"{[c['name'] for c in categories[:8]]}...")

        # ---- 多轮采集循环（--target 控制总量，控频慢慢补充）----
        total = db.stats()["shops"]
        target = args.target or (total + 1)  # 不指定则只跑 1 轮
        print(f"[3] 当前库中 {total} 个店铺，目标 {target} 个")
        if total >= target:
            print(f"[OK] 已达到目标，无需采集")
            return 0

        round_no = 0
        empty_streak = 0  # 连续无新增轮数，防死循环
        used_keywords = set()
        try:
            while total < target and empty_streak < 5:
                round_no += 1
                if args.category:
                    cat = next((c for c in categories
                                if c["keyword"] == args.category),
                               {"name": args.category, "keyword": args.category,
                                "url": f"https://s.1688.com/selloffer/offer_search.htm"
                                       f"?charset=utf8&keywords={args.category}"})
                    if round_no > 1:
                        break  # 指定类目只采一轮
                else:
                    # 随机选没用过的类目
                    pool = [c for c in categories
                            if c["keyword"] not in used_keywords]
                    if not pool:
                        print("[!] 类目已用完")
                        break
                    cat = random.choice(pool)
                    used_keywords.add(cat["keyword"])

                print(f"[轮次 {round_no}] 类目: {cat['name']}  "
                      f"(进度 {total}/{target})")
                try:
                    page.goto(cat["url"], wait_until="domcontentloaded",
                              timeout=60000, referer=HOMEPAGE)
                except Exception as e:
                    print(f"    [X] 类目页打开失败: {e}，跳过")
                    empty_streak += 1
                    continue
                human_pause(4, 8)

                # 模拟滚动加载更多结果
                for _ in range(3):
                    page.mouse.wheel(0, random.randint(600, 1200))
                    time.sleep(random.uniform(1.0, 2.0))

                shops = extract_shops(page)
                print(f"    本页提取到 {len(shops)} 个店铺")
                if not shops:
                    empty_streak += 1
                    print(f"    [!] 未提取到店铺（连续 {empty_streak} 轮），"
                          f"可能被风控")
                    continue

                run_id = db.start_run(cat["name"], cat["keyword"])
                inserted = db.upsert_shops(shops, run_id=run_id,
                                           category_keyword=cat["keyword"])
                db.finish_run(run_id, shops_found=len(shops),
                              note=f"new={inserted}")
                total = db.stats()["shops"]
                print(f"    入库: 新增 {inserted}，库中累计 {total}/{target}")

                if inserted == 0:
                    empty_streak += 1
                else:
                    empty_streak = 0

                # 轮间控频：长随机延迟，模拟正常浏览节奏
                if total < target:
                    t = random.uniform(args.delay_min, args.delay_max)
                    print(f"    ...轮间等待 {t:.0f}s（控频）")
                    time.sleep(t)
        except KeyboardInterrupt:
            print("\n[!] 用户中断，已入库数据不受影响，可随时再跑继续补充")

        print(f"[OK] 采集结束: 共 {round_no} 轮，库中 {total} 个店铺")
        print(f"    数据库统计: {db.stats()}")
        print(f"    运行 contact_fetcher.py 抓取联系方式")
        return 0
    finally:
        # 退出前把浏览器里的最新 Cookie（含新 x5sec）写回该出口 IP 名下
        try:
            save_cookies(db, identity, page.context)
        except Exception as e:
            print(f"    [!] Cookie 回写失败: {e}")
        browser.close()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
