#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 联系方式抓取脚本（消费者）

从 .cache/1688.db 中取 status='pending' 的店铺，逐个进入其
「联系方式」页解析 联系人/性别(先生女士)/电话/手机/传真/地址。

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
    下次运行自动从未抓取的店铺继续。

用法:
    python3 contact_fetcher.py              # 本批抓 10 个
    python3 contact_fetcher.py -n 30        # 本批抓 30 个
    python3 contact_fetcher.py --headed     # 有头模式
    python3 contact_fetcher.py --proxy      # 走青果住宅代理
    python3 contact_fetcher.py --retry-failed  # 先把 failed 重置回 pending 再抓
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from common import (get_exit_ip, human_pause, launch_browser, save_cookies,
                    scrape_contact)
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
    ap.add_argument("--proxy", action="store_true",
                    help="走 util/proxy_qingguo.py 的青果住宅代理；"
                         "Cookie 按出口 IP 存 SQLite（记录过期时间），"
                         "退出时自动把最新 Cookie 写回该 IP 名下")
    args = ap.parse_args()

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

    browser, page, identity, req_proxies = launch_browser(
        headless=not args.headed, use_proxy=args.proxy, db=db)
    print(f"[2] CloakBrowser 已启动 (headless={not args.headed}"
          f"{', proxy=' + identity if args.proxy else ''})")

    # 直连模式下出口 IP 固定不变，提前查好缓存
    direct_ip = None if args.proxy else (get_exit_ip() or "查询失败")

    ok = failed = empty = 0
    try:
        for i, shop in enumerate(pending, 1):
            # 每次抓取前获取当前出口 IP（代理模式可能轮转，直连复用缓存）
            if args.proxy:
                cur_ip = get_exit_ip(req_proxies) or identity
            else:
                cur_ip = direct_ip
            print(f"[{i}/{len(pending)}] {shop['name'] or shop['domain']}  提取IP：{cur_ip}")
            info = scrape_contact(page, shop["domain"], referer=shop["url"])
            if info is None:
                db.mark_shop_failed(shop["domain"])
                failed += 1
            elif not any(info[k] for k in
                         ("contact_person", "phone", "mobile", "fax", "address")):
                # 店铺未填任何联系方式：也入 contacts 表备查（含原始文本），
                # 店铺标记 no_contact 便于统计和复核
                raw = info.pop("_raw", None)
                src = info.pop("_source_url", None)
                db.save_contact(shop["domain"], info,
                                source_url=src, raw_text=raw)
                db.mark_shop_no_contact(shop["domain"], bump_attempts=False)
                empty += 1
                print(f"    - 店铺未填写联系方式，已记录空条目并标记 no_contact")
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
        # 退出前把浏览器里的最新 Cookie（含新 x5sec）写回该出口 IP 名下
        try:
            save_cookies(db, identity, page.context)
        except Exception as e:
            print(f"    [!] Cookie 回写失败: {e}")
        browser.close()

    print(f"[OK] 本批完成: 有联系方式 {ok}, 无联系方式 {empty}, 失败 {failed}")
    print(f"    数据库统计: {db.stats()}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
