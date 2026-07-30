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
    - 直连（不走快代理）：Cookie 是本机浏览器种下的，出口 IP 保持一致
    - UA 与导出 Cookie 的浏览器一致（Chrome 150 / macOS）
    - 单浏览器、低频率、页面间随机延迟

用法:
    python3 shop_crawler.py                 # 随机类目采集入库
    python3 shop_crawler.py --category 女装 # 指定类目
    python3 shop_crawler.py --headed        # 有头模式（更不易被检测）
"""

import argparse
import random
import sys
import time

from common import (COOKIE_JSON, HOMEPAGE, human_pause, launch_browser)
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
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感）")
    args = ap.parse_args()

    if not COOKIE_JSON.exists():
        sys.exit(f"找不到 Cookie 文件: {COOKIE_JSON}，请先导出 Cookie")

    db = ShopDB()
    browser, page = launch_browser(headless=not args.headed)
    print(f"[1] CloakBrowser 已启动 (headless={not args.headed})")

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

        if args.category:
            cat = next((c for c in categories if c["keyword"] == args.category),
                       {"name": args.category, "keyword": args.category,
                        "url": f"https://s.1688.com/selloffer/offer_search.htm"
                               f"?charset=utf8&keywords={args.category}"})
            print(f"[3] 使用指定类目: {cat['name']}")
        else:
            cat = random.choice(categories)
            print(f"[3] 随机选中类目: {cat['name']} ({cat['keyword']})")

        # ---- 类目页：取店铺 ----
        print(f"[4] 进入类目页: {cat['url']}")
        page.goto(cat["url"], wait_until="domcontentloaded", timeout=60000,
                  referer=HOMEPAGE)
        human_pause(4, 8)

        # 模拟滚动加载更多结果
        for _ in range(3):
            page.mouse.wheel(0, random.randint(600, 1200))
            time.sleep(random.uniform(1.0, 2.0))

        shops = extract_shops(page)
        print(f"    本页提取到 {len(shops)} 个店铺")
        if not shops:
            sys.exit("[X] 类目页未提取到店铺，可能被风控或页面结构变化")

        # ---- 入库（status=pending）----
        run_id = db.start_run(cat["name"], cat["keyword"])
        inserted = db.upsert_shops(shops, run_id=run_id,
                                   category_keyword=cat["keyword"])
        db.finish_run(run_id, shops_found=len(shops),
                      note=f"new={inserted}")
        print(f"[5] 入库完成: 本页 {len(shops)} 个，其中新增 {inserted} 个 "
              f"(run_id={run_id})")
        print(f"    数据库统计: {db.stats()}")
        print(f"[OK] 店铺已入队等待联系方式抓取，运行 contact_fetcher.py 继续")
        return 0
    finally:
        browser.close()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
