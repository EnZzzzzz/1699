#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 店铺采集脚本（生产者，多 worker 并发版 · 状态板显示）

流程:
    1. 主线程启动一个引导浏览器：打开 1688 首页提取全部类目链接，
       再进入一个具体类目页暂停，等待人工检查/过滑块并回车确认，
       确认后写回 Cookie（含新签发的安全 Cookie）再关闭（-y 可跳过确认）
    2. --workers N 个线程并发采集：每个线程独立 CloakBrowser 实例 +
       独立 ShopDB 连接，从共享类目队列中各取类目进入
    3. 按数据库 category_progress 表记录的分页进度逐页采集类目搜索
       结果：每个类目从上次采到的下一页继续（搜索分页参数 page=N），
       深页无结果时标记 exhausted，之后跳过该类目
    4. 提取页面中出现的店铺（shop*.1688.com + 公司名），
       全部存入 .cache/1688.db，status='pending' 等待联系方式抓取

联系方式抓取由 contact_fetcher.py 完成（消费者，可断点续爬）。

并发模型（一 worker 一通道，IP + Cookie 配套）:
    - --workers N 个线程（代理模式默认 = 通道数），每个线程独立
      CloakBrowser 实例 + 独立 ShopDB 连接；
    - worker i 从青果通道池独占通道 i（独立出口 IP），Cookie 按各自
      出口 IP（identity）隔离存取，互不串号；
    - 每次启动/重启浏览器都会先访问首页预热：站点为当前出口现场签发
      独立 Cookie 并立即回写该 IP 名下（见 common.warmup_cookies）；
      有头模式下首页弹滑块会停下来等手动拖动，检测通过即保存 x5sec
      并继续；

风控处置（与 contact_fetcher 同一策略，不急于换 IP）:
    第 1 次疑似风控（类目页打不开/页面是拦截页）→ 不换 IP，
        当前 IP 休息 --block-rest-min ~ --block-rest-max 秒
        （默认 600~900 = 10~15 分钟）后重试；
        headed 模式下会优先等人工在窗口里过滑块，过了立即继续；
    第 2 次 → 修复：重启浏览器拿新出口 IP（青果 IP 时效 30 分钟，
        休息时旧 IP 通常已轮换），新 IP 预热配好 Cookie 后重试；
    第 3 次 → 判定整体被风控，主动终止整个任务，避免反复请求加重风控。
    网络/代理层错误（隧道断开等）与浏览器进程死亡单独分类：
    不计入风控，直接重启浏览器退避重试（--net-retry 次）。
    青果出口 IP 每 30 分钟轮换：每轮采集前检查，轮换即重启浏览器
    按新 IP 重新配对 Cookie（预热自动完成）。

显示（状态板，不刷屏）:
    终端内运行时屏幕底部固定 N 行（每 worker 一行），实时刷新：
        [w0] 出口 123.45.67.89 | 轮 5 | 库 3200/4000 | 女装 p3 | 采集中
    重要事件（风控、休息、修复换 IP、错误）以滚动日志打在状态板上方；
    输出重定向到文件/管道时自动降级为普通日志。

会话链路一致性:
    Cookie 存 SQLite（1688.db cookies 表），按出口 IP 隔离并记录过期时间；
    代理模式的新出口 IP 不播种旧会话 —— 种子里的 cookie2 / t / cna 等
    匿名身份标识跨 IP 复制 = 「同一访客多 IP 并发」的 Cookie 重放特征，
    故以空会话启动，由 warmup 时站点为当前出口现场签发全新身份；
    每轮成功、退出/重启时自动把最新 Cookie（含 x5sec）写回该 IP 名下，
    同一出口 IP 复访才复用。

用法:
    python3 shop_crawler.py --proxy -t 1000     # 5 通道并发采到 1000 个
    python3 shop_crawler.py --proxy -t 1000 --workers 2   # 只用 2 个 worker
    python3 shop_crawler.py --category 女装      # 指定类目采下一页（单 worker）
    python3 shop_crawler.py --proxy --headed     # 有头模式（滑块手动过）
    python3 shop_crawler.py -y -t 1000 --proxy   # 跳过人工确认（无人值守）

启动时人工确认（默认开启，-y 可跳过）:
    1688 首页一般不触发风控，进具体类目页才可能出现滑块。引导浏览器先开
    首页提取类目，再进入一个具体类目页暂停等待 —— 如有滑块请手动拖动通过，
    回车确认后写回 Cookie 才启动采集 worker，绝不会一上来就直接采集。

多轮模式说明:
    每个 worker 从共享类目队列中取类目，按库中记录的页码采下一页；类目未采
    完会放回队列，多轮模式下之后继续采它的下一页（类目间轮转，摊薄单类目
    访问频率）。轮间随机延迟（默认 15~45 秒）控制频率；每采满 --rest-every
    轮（默认 3）再强制长时休息 5~10 分钟，模拟正常用户离开，防风控。
    进度以库中店铺总数为准，Ctrl+C 中断后重新运行会按库中页码续采，
    不会重复采已采过的页。
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import common
from common import (HOMEPAGE, StatusBoard, get_exit_ip, human_pause,
                    launch_browser, save_cookies, wait_countdown,
                    wait_manual_unblock)
from database import ShopDB

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]  # 项目根目录

STALE_STREAK_LIMIT = 5  # 有提取但无新增的连续轮数上限（类目枯竭，非风控）


def _compose_crawler(wid: int, f: dict) -> str:
    """shop_crawler 状态行格式（StatusBoard compose 回调）。"""
    return (f"[w{wid}] 出口 {f.get('ip', '…')} | 轮 {f.get('round', 0)} | "
            f"库 {f.get('total', 0)}/{f.get('target', 0)} | "
            f"{f.get('cat', '-')} | {f.get('state', '初始化')}")


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


def category_page_url(url: str, page_no: int) -> str:
    """给类目搜索 URL 设置分页参数（1688 搜索分页参数为 page）。

    第 1 页保持原 URL 不变；第 N 页把 query 中的 page 参数置为 N
    （首页提取的类目 URL 一般不带 page，直接新增）。
    """
    if page_no <= 1:
        return url
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query))
    q["page"] = str(page_no)
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(q), parts.fragment))


def page_blocked(page) -> bool:
    """粗判当前页是否为风控/验证页（x5sec 滑块、punish 跳转等）。

    用于区分「类目采到末页（空结果）」和「被风控（空结果）」：
    仅深页空结果且不是风控页时，才把类目标记为 exhausted。

    判定规则统一走 common.page_block_reason（URL + 文本特征 +
    内嵌滑块组件），避免滑块页被误判为类目无货/末页而错误标记
    exhausted，也避免内嵌滑块与商品列表同屏时的漏判。
    """
    try:
        return bool(common.page_block_reason(page))
    except Exception:
        return False


def check_ip_fresh(req_proxies: dict, identity: str) -> tuple:
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
           board: StatusBoard, state: dict, lock: threading.Lock,
           stop: threading.Event):
    """单个采集 worker：独立浏览器 + 独立 DB 连接 + 独占代理通道。

    风控策略（与 contact_fetcher 一致）：疑似风控先在当前 IP 上休息
    （headed 优先等人工过滑块），再修复换 IP，仍失败才主动终止任务。
    """
    tag = f"[w{worker_id}]"
    common.set_tag(tag)  # common 内部日志按本 worker 路由到状态板
    db = ShopDB()
    browser = None
    page = None
    identity = "direct"
    ctx = None
    req_proxies = None
    block_stage = 0   # 0 正常 / 1 已休息过一次 / 2 已修复换过 IP
    net_retried = 0

    def set_status(**kw):
        board.set(worker_id, **kw)

    def close_browser():
        """把当前 identity 的 Cookie 写回数据库并关闭浏览器（幂等）。"""
        nonlocal browser, ctx
        if ctx is not None:
            try:
                save_cookies(db, identity, ctx)
            except Exception as e:
                board.log(f"{tag}   [!] Cookie 回写失败: {e}")
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        browser, ctx = None, None

    def relaunch(reason: str) -> bool:
        """重启浏览器绑定新出口 IP（预热自动配 Cookie）。失败返回 False。"""
        nonlocal browser, page, identity, ctx, req_proxies
        board.log(f"{tag} 🔄 {reason}，重启浏览器 ...")
        close_browser()
        set_status(state="重启浏览器获取新 IP…", force=True)
        for attempt in range(1, args.ip_retry + 1):
            if stop.is_set():
                return False
            try:
                browser, page, identity, req_proxies, _ = launch_browser(
                    headless=not args.headed, use_proxy=args.proxy, db=db,
                    proxy_server=proxy_server,
                    pool_size=args.channels or None,
                    stop=stop)
                ctx = page.context
                set_status(ip=identity, state="浏览器已重启", force=True)
                board.log(f"{tag} 浏览器已重启，新出口 IP={identity}")
                return True
            except (Exception, SystemExit) as e:
                backoff = min(30 * attempt, 120)
                board.log(f"{tag}   [!] 重启第 {attempt}/{args.ip_retry} "
                          f"次失败: {e}，{backoff}s 后重试...")
                if wait_countdown(board, worker_id, stop, backoff, "重启退避"):
                    return False
        board.log(f"{tag} [X] 重启 {args.ip_retry} 次仍失败")
        return False

    def on_block(reason: str) -> bool:
        """疑似风控三级处置。返回 False 表示应终止任务/退出。"""
        nonlocal block_stage
        # 记录该出口 IP 的风控遭遇；登录墙是更高一级的风控（会话被要求
        # 强制登录），原地休息/手动滑块都无意义，直接进修复换 IP 阶段
        login_wall = "login.1688.com" in reason
        db.record_ip_event(identity,
                           "block_login" if login_wall else "block_slider",
                           reason)
        if login_wall and block_stage == 0:
            block_stage = 1
            board.log(f"{tag} ⚠ 触发登录墙（{reason}），出口 {identity} "
                      f"已被高风险标记，不原地休息，直接修复换 IP")
        if block_stage == 0:
            # 第一次：不换 IP，当前 IP 长时间休息后再试
            block_stage = 1
            rest = random.uniform(args.block_rest_min, args.block_rest_max)
            board.log(f"{tag} ⚠ {reason} → 保持当前 IP {identity}，"
                      f"休息 {rest / 60:.1f} 分钟后重试")
            if args.headed:
                board.log(f"{tag}   👉 请在 {identity} 的浏览器窗口里"
                          f"手动完成验证，脚本每 15s 自动检测"
                          f"（最长 {rest / 60:.1f} 分钟）...")
                if wait_manual_unblock(board, worker_id, stop, page, rest):
                    board.log(f"{tag} ✓ 检测到验证已通过，"
                              f"Cookie 写回 {identity}，立即继续采集")
                    try:
                        save_cookies(db, identity, ctx)
                    except Exception as e:
                        board.log(f"{tag}   [!] Cookie 回写失败: {e}")
                    block_stage = 0  # 人工过证视为恢复
                    return True
                if stop.is_set():
                    return False
                board.log(f"{tag}   未检测到手动验证通过，按原计划休息后重试")
            if wait_countdown(board, worker_id, stop, rest, "风控休息(1)"):
                return False  # 用户中断
            return True
        if block_stage == 1:
            # 休息后仍被风控 → 修复：重启浏览器（青果 30 分钟时效，
            # 旧 IP 通常已轮换），新 IP 预热自动配好 Cookie
            block_stage = 2
            board.log(f"{tag} ⚠ 休息后仍被风控（{reason}）"
                      f" → 修复：重启浏览器获取新出口 IP 并重新配对 Cookie")
            return relaunch("风控修复")
        # 修复后仍失败：判定整体被风控，主动终止，避免反复请求加重风控
        board.log(f"{tag} [X] 休息与修复后仍被风控（{reason}），"
                  f"主动终止整个采集任务（可隔段时间再跑续采）")
        stop.set()
        return False

    try:
        # ---- 启动浏览器（带重试；席位等待已在 launch_browser 内处理）----
        set_status(state="启动浏览器…",
                   total=state["total"], target=state["target"], force=True)
        last_err = None
        for attempt in range(1, args.ip_retry + 1):
            if stop.is_set():
                return
            try:
                browser, page, identity, req_proxies, _ = launch_browser(
                    headless=not args.headed, use_proxy=args.proxy, db=db,
                    proxy_server=proxy_server,
                    pool_size=args.channels or None,
                    stop=stop)
                break
            except (Exception, SystemExit) as e:
                last_err = e
                backoff = min(30 * attempt, 120)
                board.log(f"{tag}   [!] 启动浏览器第 {attempt}/{args.ip_retry} "
                          f"次失败: {e}，{backoff}s 后重试...")
                if wait_countdown(board, worker_id, stop, backoff, "启动退避"):
                    return
        else:
            raise RuntimeError(f"启动浏览器重试 {args.ip_retry} "
                               f"次仍失败: {last_err}")
        ctx = page.context
        set_status(ip=identity, state="就绪", force=True)

        rounds_since_rest = 0  # 距上次长时休息以来已采的轮数
        while not stop.is_set():
            # ---- 从共享队列取一个未采完的类目（已采到末页的跳过）----
            cat, page_no = None, 1
            while not stop.is_set():
                with lock:
                    if state["total"] >= state["target"] or not state["queue"]:
                        break
                    candidate = state["queue"].pop()
                prog = db.get_category_progress(candidate["keyword"])
                if prog and prog["exhausted"]:
                    board.log(f"{tag}   [~] 类目「{candidate['name']}」已采到末页"
                              f"（共 {prog['pages_crawled']} 页），跳过")
                    continue
                cat = candidate
                page_no = prog["next_page"] if prog else 1
                with lock:
                    state["rounds"] += 1
                    round_no = state["rounds"]
                break
            if cat is None:
                break

            set_status(round=round_no, cat=f"{cat['name']} p{page_no}",
                       state="检查出口 IP…")

            # ---- 出口 IP 过期检查（青果每 30 分钟轮换一次出口）----
            if args.proxy:
                need, cur_ip, reason = check_ip_fresh(req_proxies, identity)
                if need:
                    if not relaunch(reason):
                        stop.set()
                        return

            # ---- 打开类目页（网络/浏览器故障与风控分类处置）----
            url = category_page_url(cat["url"], page_no)
            set_status(state="采集中")
            try:
                page.goto(url, wait_until="domcontentloaded",
                          timeout=60000, referer=HOMEPAGE)
                net_retried = 0
            except Exception as e:
                reason = str(e).splitlines()[0][:200]
                # 浏览器进程死亡/被服务端关闭：直接重启，不计风控
                if common.is_fatal_browser_error(e) \
                        or not common.browser_alive(page):
                    board.log(f"{tag} [X] 浏览器会话终止（{reason}），"
                              f"重启浏览器（不计入风控）")
                    if not relaunch("浏览器会话终止"):
                        stop.set()
                        return
                    continue
                # 网络/代理层错误：与风控无关，退避重试
                if common.is_network_error(e):
                    net_retried += 1
                    if net_retried > args.net_retry:
                        board.log(f"{tag} [X] 网络故障重试 {args.net_retry} "
                                  f"次仍失败（{reason}），主动终止任务")
                        stop.set()
                        return
                    backoff = min(30 * net_retried, 180)
                    board.log(f"{tag} ⚠ 网络/代理故障（{reason}），"
                              f"第 {net_retried}/{args.net_retry} 次重试"
                              f"（{backoff}s 后，不计入风控）...")
                    if args.proxy:
                        if not relaunch("网络/代理故障"):
                            stop.set()
                            return
                    if wait_countdown(board, worker_id, stop, backoff,
                                      "网络故障退避"):
                        return
                    continue
                # 其他异常（goto 超时等）：按疑似风控处置
                if not on_block(f"类目页打开失败（{reason}）"):
                    return
                with lock:  # 类目放回队首，休息/修复后重试同一页
                    state["queue"].insert(0, cat)
                continue

            human_pause(4, 8)

            # 模拟滚动加载更多结果
            for _ in range(3):
                page.mouse.wheel(0, random.randint(600, 1200))
                time.sleep(random.uniform(1.0, 2.0))

            shops = extract_shops(page)
            # 内嵌滑块与商品列表同屏：提取正常也不能算过，
            # 先等手动过证/风控处置，避免带着未验证会话继续请求
            embedded = common.detect_embedded_slider(page)
            if embedded:
                if not on_block(f"页面内嵌滑块验证（{embedded}）"):
                    return
                with lock:  # 类目放回队首，过证/修复后重试同一页
                    state["queue"].insert(0, cat)
                continue
            if not shops:
                if page_blocked(page):
                    if not on_block("页面命中风控（滑块/验证页）"):
                        return
                    with lock:  # 类目放回队首，休息/修复后重试同一页
                        state["queue"].insert(0, cat)
                elif page_no > 1:
                    # 深页无结果且非风控页：类目采到末页，标记后不再采
                    db.mark_category_exhausted(cat["keyword"], cat["name"])
                    board.log(f"{tag}   [~] 类目「{cat['name']}」第 {page_no} "
                              f"页无结果，标记为已采完")
                    block_stage = 0
                else:
                    # 首页无结果且非风控页：类目本身无货，按无新增计数
                    board.log(f"{tag}   [~] 类目「{cat['name']}」第 1 页"
                              f"未提取到店铺（非风控页），跳过")
                    block_stage = 0
                    with lock:
                        state["stale_streak"] += 1
                        if state["stale_streak"] >= STALE_STREAK_LIMIT:
                            board.log(f"{tag}   [~] 连续 {STALE_STREAK_LIMIT} "
                                      f"轮无新增，类目枯竭，停止采集")
                            stop.set()
                continue

            # ---- 提取成功：入库并推进类目进度 ----
            block_stage = 0  # 风控状态恢复
            run_id = db.start_run(cat["name"], cat["keyword"])
            inserted = db.upsert_shops(shops, run_id=run_id,
                                       category_keyword=cat["keyword"])
            db.finish_run(run_id, shops_found=len(shops),
                          note=f"new={inserted} page={page_no} worker={worker_id}")
            next_page = db.advance_category_page(cat["keyword"], cat["name"],
                                                 shops_found=len(shops))
            with lock:
                state["total"] = db.stats()["shops"]
                # 类目未采完则放回队首，多轮模式下之后轮转回来采下一页
                # （--category 单类目模式只采 1 页，不放回）
                if not args.category:
                    state["queue"].insert(0, cat)
                if inserted == 0:
                    # 提取正常但无新增：类目枯竭，不算风控
                    state["stale_streak"] += 1
                    stale = state["stale_streak"]
                    if stale >= STALE_STREAK_LIMIT:
                        board.log(f"{tag}   [~] 连续 {STALE_STREAK_LIMIT} 轮"
                                  f"无新增，类目枯竭，停止采集")
                        stop.set()
                else:
                    state["stale_streak"] = 0
                    stale = 0
            set_status(total=state["total"], state=f"✓ 新增 {inserted}")
            if inserted == 0:
                board.log(f"{tag}   [~] {cat['name']} p{page_no} 提取 "
                          f"{len(shops)} 个但全部已入库"
                          f"（连续无新增 {stale} 轮）")
            else:
                board.log(f"{tag} ✓ {cat['name']} p{page_no} 提取 "
                          f"{len(shops)} 个，新增 {inserted}，库中累计 "
                          f"{state['total']}/{state['target']}"
                          f"（该类目下次采第 {next_page} 页）")

            # 每轮成功后把浏览器里的最新 Cookie（含可能轮换的 x5sec、
            # 以及手动过证后新签发的安全 Cookie）写回该出口 IP 名下 ——
            # 进程意外退出也不丢信任链，同 IP 复访直接复用
            try:
                save_cookies(db, identity, ctx)
            except Exception:
                pass

            # ---- 节奏控制：每采满 rest_every 轮强制长时休息（5~10 分钟）----
            rounds_since_rest += 1
            if (args.rest_every > 0 and rounds_since_rest >= args.rest_every
                    and state["total"] < state["target"] and not stop.is_set()):
                rounds_since_rest = 0
                t = random.uniform(args.rest_min, args.rest_max)
                board.log(f"{tag}   ☕ 已连续采集 {args.rest_every} 轮，"
                          f"静默 {t / 60:.1f} 分钟后继续（长时控频防风控）")
                if wait_countdown(board, worker_id, stop, t, "长时休息"):
                    return  # 用户中断

            # 轮间控频：长随机延迟，模拟正常浏览节奏；各 worker 按编号
            # 递增基准延迟，避免多 worker 同频齐步请求形成集群特征
            if state["total"] < state["target"] and not stop.is_set():
                t = random.uniform(args.delay_min + worker_id * 5,
                                   args.delay_max + worker_id * 8)
                if wait_countdown(board, worker_id, stop, t, "轮间等待"):
                    return  # 用户中断
        set_status(state="已完成，退出")
    except Exception as e:
        board.log(f"{tag} [X] worker 异常退出: {e}")
    finally:
        # 退出前把浏览器里的最新 Cookie 写回该出口 IP 名下
        close_browser()
        set_status(state="已退出", force=True)
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="1688 类目店铺采集（多 worker 并发，状态板显示，入库 pending）")
    ap.add_argument("--category", default=None,
                    help="指定类目关键词（默认从首页类目中随机选；指定后单 worker "
                         "只采该类目进度中的下一页，采完即退出）")
    ap.add_argument("-t", "--target", type=int, default=0,
                    help="目标店铺总数（按库中累计数计算）。0=每个 worker 只采 1 个类目；"
                         "例如 -t 1000 会持续多轮随机类目采集，直到库中达到 1000")
    ap.add_argument("--delay-min", type=float, default=15.0,
                    help="多轮模式轮间最小延迟秒数（默认 15）")
    ap.add_argument("--delay-max", type=float, default=45.0,
                    help="多轮模式轮间最大延迟秒数（默认 45）")
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感；"
                         "风控时可在窗口手动过滑块，脚本自动检测并继续）")
    ap.add_argument("--proxy", action="store_true",
                    help="走 util/proxy_qingguo.py 的青果住宅代理；"
                         "Cookie 按出口 IP 存 SQLite，新 IP 启动时自动"
                         "访问首页预热，由站点现场签发配套 Cookie")
    ap.add_argument("--channels", type=int, default=0,
                    help="青果通道池大小（默认取 proxy_qingguo.CONFIG['channels']）")
    ap.add_argument("--workers", type=int, default=0,
                    help="并发 worker 数；代理模式默认=通道数，直连模式默认 1")
    ap.add_argument("--ip-retry", type=int, default=3,
                    help="启动/重启浏览器获取新出口 IP 的重试次数（默认 3）")
    ap.add_argument("--block-rest-min", type=float, default=600,
                    help="疑似风控后保持当前 IP 的休息下限秒数（默认 600=10 分钟）")
    ap.add_argument("--block-rest-max", type=float, default=900,
                    help="疑似风控后保持当前 IP 的休息上限秒数（默认 900=15 分钟）")
    ap.add_argument("--net-retry", type=int, default=5,
                    help="网络/代理层错误（隧道断开等，非风控）的重试上限"
                         "（默认 5，超限主动终止任务）")
    ap.add_argument("--rest-every", type=int, default=3,
                    help="节奏控制：每个 worker 每采满 N 轮强制长时休息"
                         "（默认 3，0=关闭长时休息）")
    ap.add_argument("--rest-min", type=float, default=300.0,
                    help="长时休息最短秒数（默认 300 = 5 分钟）")
    ap.add_argument("--rest-max", type=float, default=600.0,
                    help="长时休息最长秒数（默认 600 = 10 分钟）")
    ap.add_argument("--stagger-min", type=float, default=15.0,
                    help="worker 启动错开的最小秒数（默认 15；多会话同分钟出生、"
                         "同节奏访问是集群特征，启动时间必须打散）")
    ap.add_argument("--stagger-max", type=float, default=60.0,
                    help="worker 启动错开的最大秒数（默认 60）")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="跳过启动时的人工确认（无人值守重跑用）；"
                         "默认会先打开一个具体类目页等待人工检查/过滑块，"
                         "回车确认并写回 Cookie 后才开始采集")
    args = ap.parse_args()

    # ---- 并发度与通道分配（一 worker 一通道，IP + Cookie 配套）----
    if args.proxy:
        sys.path.insert(0, str(ROOT_DIR / "util"))
        import proxy_qingguo
        pool = proxy_qingguo.get_pool(args.channels or None)
        n_channels = len(pool.servers())
        workers = 1 if args.category else (args.workers or n_channels)
        if workers > n_channels:
            print(f"[!] workers({workers}) > 通道数({n_channels})，"
                  f"部分 worker 将共用通道（共享出口 IP），不建议")
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

    # ---- 状态板与日志路由（bootstrap 阶段的日志走普通打印）----
    board = StatusBoard(workers, compose=_compose_crawler)

    def _sink(tag: str, msg: str):
        """common 内部日志路由：错误/警告进滚动日志，常规细节进状态行。"""
        text = (msg or "").strip()
        if not text:
            return
        m = re.match(r"\[w(\d+)\]", tag or "")
        if "[X]" in text or "[!]" in text or "[license]" in text:
            board.log(f"{tag} {text}" if tag else text)
        elif m and int(m.group(1)) < workers:
            board.set(int(m.group(1)), detail=text[:80])
        else:
            board.log(f"{tag} {text}" if tag else text)

    common.set_log_sink(_sink)

    # ---- 引导浏览器：首页提取类目 + 类目页人工确认（用完即关） ----
    # 1688 首页一般不触发风控，进具体类目页才可能出现滑块；因此引导浏览器
    # 始终以有头模式运行：先开首页提取类目，再进入一个具体类目页等待人工
    # 确认（有滑块请手动拖动），回车后写回 Cookie 再启动 worker。
    # -y 跳过人工确认，此时引导浏览器按 --headed 设置运行（可 headless）。
    # launch_browser 启动时会自动访问首页预热（站点为当前出口签发 Cookie）。
    bootstrap_headless = args.yes and not args.headed
    try:
        browser, page, identity, boot_proxies, _ = launch_browser(
            headless=bootstrap_headless, use_proxy=args.proxy, db=db,
            proxy_server=proxy_servers[0],
            pool_size=args.channels or None)
    except Exception as e:
        print(f"[X] 引导浏览器启动失败: {e}")
        db.close()
        return 1
    print(f"[2] 引导浏览器已启动 (headless={bootstrap_headless}"
          f"{', proxy=' + identity if args.proxy else ''}，"
          f"出口 IP: {identity})，打开首页 {HOMEPAGE}")
    try:
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        human_pause(3, 6)
        categories = extract_categories(page)
        if not categories:
            print("[X] 首页未提取到类目，可能被风控，请检查")
            return 1
        print(f"    提取到 {len(categories)} 个类目: "
              f"{[c['name'] for c in categories[:8]]}...")

        # ---- 人工确认阶段：进入具体类目页（首页不触发风控，类目页才可能出滑块）----
        if args.category:
            warmup_cat = next(
                (c for c in categories if c["keyword"] == args.category),
                {"name": args.category, "keyword": args.category,
                 "url": f"https://s.1688.com/selloffer/offer_search.htm"
                        f"?charset=utf8&keywords={args.category}"})
        else:
            warmup_cat = random.choice(categories)
        print(f"[3] 打开类目页「{warmup_cat['name']}」进行采集前检查")
        try:
            page.goto(warmup_cat["url"], wait_until="domcontentloaded",
                      timeout=60000, referer=HOMEPAGE)
            human_pause(4, 8)
            n_probe = len(extract_shops(page))
            print(f"    类目页提取到 {n_probe} 个店铺"
                  + ("" if n_probe else "（为 0，页面可能有滑块/验证，请在浏览器中检查）"))
        except Exception as e:
            print(f"    [!] 类目页打开失败: {e}（请在浏览器中检查页面状态）")

        if args.yes:
            print("    [-y] 跳过人工确认，直接开始采集")
        else:
            print("    ┌─────────────────────────────────────────────")
            print("    │ 请在浏览器窗口中检查类目页：")
            print("    │   1. 如出现滑块 / 验证码，请手动拖动通过；")
            print("    │   2. 确认页面已正常显示商品列表；")
            print("    │   3. 回到本终端按【回车】，脚本保存 Cookie 后才开始采集。")
            print("    └─────────────────────────────────────────────")
            try:
                input("    >>> 确认无误后按回车开始采集（Ctrl+C 取消）...")
            except (EOFError, KeyboardInterrupt):
                print("\n[!] 未确认，取消采集（Cookie 仍会写回数据库）")
                return 1
        # 人工确认后立刻写回 Cookie（含刚签发的安全 Cookie），worker 启动即复用
        save_cookies(db, identity, page.context)
    finally:
        try:
            save_cookies(db, identity, page.context)
        except Exception as e:
            print(f"    [!] Cookie 回写失败: {e}")
        browser.close()

    # ---- 组装共享类目队列（过滤已采到末页的类目） ----
    if args.category:
        cat = next((c for c in categories if c["keyword"] == args.category),
                   {"name": args.category, "keyword": args.category,
                    "url": f"https://s.1688.com/selloffer/offer_search.htm"
                           f"?charset=utf8&keywords={args.category}"})
        queue = [cat]
    else:
        queue = categories[:]
        random.shuffle(queue)
        n_all = len(queue)
        queue = [c for c in queue
                 if not ((p := db.get_category_progress(c["keyword"]))
                         and p["exhausted"])]
        if n_all - len(queue):
            print(f"    {n_all - len(queue)} 个类目已采到末页，本轮跳过"
                  f"（剩余 {len(queue)} 个）")
        if not queue:
            print(f"[OK] 所有类目均已采到末页，无需采集")
            db.close()
            return 0

    state = {
        "queue": queue,
        "total": total,
        "target": target,
        "rounds": 0,
        "stale_streak": 0,  # 全局连续无新增轮数（类目枯竭），防死循环
    }
    lock = threading.Lock()
    stop = threading.Event()

    # 直接关终端窗口(SIGHUP)或被 kill(SIGTERM)时也走正常清理流程：
    # 各 worker 关闭浏览器，服务端会话租约立即释放
    import signal

    def _graceful_exit(signum, frame):
        board.log(f"[!] 收到信号 {signum}，通知各 worker 清理后退出...")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _graceful_exit)
        except (OSError, ValueError):
            pass  # 平台不支持该信号时跳过

    board.start()
    threads = [
        threading.Thread(target=worker,
                         args=(i, args, proxy_servers[i], board,
                               state, lock, stop),
                         name=f"crawler-{i}", daemon=True)
        for i in range(workers)
    ]
    print(f"[4] 启动 {workers} 个采集 worker"
          f"（{'代理通道: ' + ', '.join(proxy_servers) if args.proxy else '直连'}）")
    if args.rest_every > 0:
        print(f"    节奏控制: 每个 worker 每 {args.rest_every} 轮休息 "
              f"{args.rest_min / 60:.0f}~{args.rest_max / 60:.0f} 分钟")
    for i, t in enumerate(threads):
        t.start()
        if i < len(threads) - 1:
            # 启动时间打散（默认 15~60s/个）：多会话同一分钟内出生、
            # 同一节奏访问同一端点，是风控识别爬虫集群的强特征
            d = random.uniform(args.stagger_min, args.stagger_max)
            print(f"    错开启动：{d:.0f}s 后启动下一个 worker ...")
            time.sleep(d)

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        board.log("[!] 用户中断，等待各 worker 完成当前轮次后退出...")
        stop.set()
        for t in threads:
            t.join(timeout=90)
        board.log("[!] 已入库数据不受影响，可随时再跑继续补充")

    final_total = db.stats()["shops"]
    print(f"[OK] 采集结束: 共 {state['rounds']} 轮，库中 {final_total} 个店铺")
    print(f"    数据库统计: {db.stats()}")
    print(f"    运行 contact_fetcher.py 抓取联系方式")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
