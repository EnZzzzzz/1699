#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 店铺采集脚本（第一步：类目 -> 店铺列表）

流程:
    1. 用 CloakBrowser（隐形 Chromium）加载 .cache/cookies_1688.json 中的 Cookie
    2. 打开 1688 首页，从「全部类目」提取全部类目链接
    3. 随机选 1 个类目进入（也可用 --category 指定关键词）
    4. 在类目搜索结果页中提取出现的店铺（shop*.1688.com + 公司名）
    5. 随机抽取 N 个店铺输出（N 通过 -n 配置）

会话链路一致性（按经验执行）:
    - 直连（不走快代理）：Cookie 是本机浏览器种下的，出口 IP 保持一致
    - UA 与导出 Cookie 的浏览器一致（Chrome 150 / macOS）
    - 单浏览器、低频率、页面间随机延迟

用法:
    python3 shop_crawler.py                 # 随机类目，抽 5 个店铺
    python3 shop_crawler.py -n 10           # 抽 10 个
    python3 shop_crawler.py --category 女装  # 指定类目
    python3 shop_crawler.py --headed        # 有头模式（更不易被检测）
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
COOKIE_JSON = BASE_DIR / ".cache" / "cookies_1688.json"
CONFIG_JSON = BASE_DIR / ".cache" / "config.json"

HOMEPAGE = "https://www.1688.com/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/150.0.0.0 Safari/537.36")


def load_license_key() -> str | None:
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text())["CLOAKBROWSER_LICENSE_KEY"]
        except Exception:
            return None
    return None


def load_cookies_pw() -> list[dict]:
    """把 CDP 导出的 Cookie 转成 Playwright 格式（仅 1688 域）。"""
    raw = json.loads(COOKIE_JSON.read_text(encoding="utf-8"))
    cookies = []
    for c in raw:
        domain = c.get("domain", "")
        if "1688.com" not in domain:
            continue
        cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path", "/") if not c.get("path", "").startswith("//") else "/",
            "secure": bool(c.get("secure", False)),
            "httpOnly": bool(c.get("httpOnly", False)),
        })
    return cookies


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


def human_pause(lo: float = 2.0, hi: float = 5.0):
    t = random.uniform(lo, hi)
    print(f"    ...随机等待 {t:.1f}s")
    time.sleep(t)


def main() -> int:
    ap = argparse.ArgumentParser(description="1688 随机类目店铺采集")
    ap.add_argument("-n", "--num-shops", type=int, default=5,
                    help="随机抽取的店铺数量（默认 5）")
    ap.add_argument("--category", default=None,
                    help="指定类目关键词（默认从首页类目中随机选 1 个）")
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感）")
    ap.add_argument("-o", "--output", default="shops_result.json",
                    help="结果输出文件（默认 shops_result.json）")
    args = ap.parse_args()

    if not COOKIE_JSON.exists():
        sys.exit(f"找不到 Cookie 文件: {COOKIE_JSON}，请先运行 verify_1688.py 流程导出")

    from cloakbrowser import launch

    cookies = load_cookies_pw()
    print(f"[1] 加载 {len(cookies)} 个 1688 Cookie")

    print(f"[2] 启动 CloakBrowser (headless={not args.headed})")
    browser = launch(
        headless=not args.headed,
        license_key=load_license_key(),
        humanize=True,
        locale="zh-CN",
        timezone="Asia/Shanghai",
    )

    try:
        ctx = browser.new_context(user_agent=UA, locale="zh-CN")
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        # ---- 首页：取类目 ----
        print(f"[3] 打开首页 {HOMEPAGE}")
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
            print(f"[4] 使用指定类目: {cat['name']}")
        else:
            cat = random.choice(categories)
            print(f"[4] 随机选中类目: {cat['name']} ({cat['keyword']})")

        # ---- 类目页：取店铺 ----
        print(f"[5] 进入类目页: {cat['url']}")
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

        picked = random.sample(shops, min(args.num_shops, len(shops)))
        print(f"[6] 随机抽取 {len(picked)} 个店铺:")
        for i, s in enumerate(picked, 1):
            print(f"    {i}. {s['name'] or '(无名)'}  ->  {s['url']}")

        result = {
            "category": cat,
            "total_shops_on_page": len(shops),
            "picked": picked,
            "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        out = BASE_DIR / args.output
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[OK] 结果已保存: {out}")
        return 0
    finally:
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
