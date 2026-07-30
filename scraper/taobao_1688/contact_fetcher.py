#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 联系方式抓取脚本（消费者）

从 .cache/1688.db 中取 status='pending' 的店铺，逐个进入其
「联系方式」页解析 联系人/性别(先生女士)/电话/手机/传真/地址。

结果处理:
    - 有任何实际字段 → 写入 contacts 表，店铺标记 done
    - 字段全部为空（店铺没填）→ 不入 contacts，店铺标记 no_contact
    - 抓取失败 → 店铺标记 failed（--retry-failed 可重置）

断点续爬:
    进度全部记录在 shops.status，随时 Ctrl+C 或重启脚本，
    下次运行自动从未抓取的店铺继续。

用法:
    python3 contact_fetcher.py              # 本批抓 10 个
    python3 contact_fetcher.py -n 30        # 本批抓 30 个
    python3 contact_fetcher.py --headed     # 有头模式
    python3 contact_fetcher.py --retry-failed  # 先把 failed 重置回 pending 再抓
"""

import argparse
import random
import sys
import time

from common import COOKIE_JSON, human_pause, launch_browser, scrape_contact
from database import ShopDB


def main() -> int:
    ap = argparse.ArgumentParser(description="1688 店铺联系方式抓取（断点续爬）")
    ap.add_argument("-n", "--num", type=int, default=10,
                    help="本批次抓取的店铺数量（默认 10）")
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感）")
    ap.add_argument("--retry-failed", action="store_true",
                    help="先把 failed 店铺重置为 pending 再开始抓取")
    ap.add_argument("--rest-every", type=int, default=20,
                    help="每抓取多少个店铺后长休息一次（默认 20，0 关闭）")
    ap.add_argument("--rest-min", type=float, default=60,
                    help="长休息随机时长的下限秒数（默认 60）")
    ap.add_argument("--rest-max", type=float, default=180,
                    help="长休息随机时长的上限秒数（默认 180）")
    args = ap.parse_args()

    if not COOKIE_JSON.exists():
        sys.exit(f"找不到 Cookie 文件: {COOKIE_JSON}，请先导出 Cookie")

    db = ShopDB()
    if args.retry_failed:
        n = db.reset_failed()
        print(f"[0] 已把 {n} 个 failed 店铺重置回 pending")

    pending = db.get_pending_shops(limit=args.num)
    if not pending:
        print(f"[OK] 没有待抓取的店铺。统计: {db.stats()}")
        print("    先运行 shop_crawler.py 采集更多店铺")
        return 0

    total_pending = db.count_pending()
    print(f"[1] 待抓取 {total_pending} 个，本批处理 {len(pending)} 个")

    browser, page = launch_browser(headless=not args.headed)
    print(f"[2] CloakBrowser 已启动 (headless={not args.headed})")

    ok = failed = empty = 0
    try:
        for i, shop in enumerate(pending, 1):
            print(f"[{i}/{len(pending)}] {shop['name'] or shop['domain']}")
            info = scrape_contact(page, shop["domain"], referer=shop["url"])
            if info is None:
                db.mark_shop_failed(shop["domain"])
                failed += 1
            elif not any(info[k] for k in
                         ("contact_person", "phone", "mobile", "fax", "address")):
                # 店铺未填任何联系方式：不入 contacts，标记 no_contact
                db.mark_shop_no_contact(shop["domain"])
                empty += 1
                print(f"    - 店铺未填写联系方式，标记 no_contact")
            else:
                raw = info.pop("_raw", None)
                src = info.pop("_source_url", None)
                db.save_contact(shop["domain"], info,
                                source_url=src, raw_text=raw)
                ok += 1
                print(f"    ✓ 联系人={info['contact_person']}"
                      f"({info['gender']}) 电话={info['phone']} "
                      f"手机={info['mobile']} 地址={info['address']}")
            human_pause(3, 7)  # 控制节奏，降低风控概率
            # 每隔一定轮次随机长休息一次，模拟真人连续浏览后的停顿
            if (args.rest_every > 0 and i % args.rest_every == 0
                    and i < len(pending)):
                t = random.uniform(args.rest_min, args.rest_max)
                print(f"    ☕ 已连续抓取 {i} 个，随机长休息 {t:.0f}s ...")
                time.sleep(t)
    except KeyboardInterrupt:
        print("\n[!] 用户中断，进度已保存在数据库，下次运行自动续爬")
    finally:
        browser.close()

    print(f"[OK] 本批完成: 有联系方式 {ok}, 无联系方式 {empty}, 失败 {failed}")
    print(f"    数据库统计: {db.stats()}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
