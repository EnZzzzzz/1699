#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 联系方式抓取脚本（消费者，多 worker 并发版 · 状态板显示）

从 .cache/1688.db 中原子认领 status='pending' 的店铺，进入其
「联系方式」页解析 联系人/性别(先生女士)/电话/手机/传真/地址。

并发模型（一 worker 一通道，IP + Cookie 配套）:
    - --workers N 个线程（代理模式默认 = 通道数），每个线程独立
      CloakBrowser 实例 + 独立 ShopDB 连接；
    - worker i 从青果通道池独占通道 i（独立出口 IP），Cookie 按各自
      出口 IP（identity）隔离存取，IP + Cookie 始终配套，互不串号；
    - 店铺认领走数据库事务（claim_pending_shops），不会重复抓同一家店。

单个 worker 的完整生命周期:
    1. 从通道池领到自己的通道，启动浏览器，按出口 IP 配好 Cookie；
    2. 循环：认领店铺 → 抓取 → 样本之间随机间隔（3-7s）；
    3. 每个 worker 各自计批：采满 -n 个后各自强制大休息 --batch-rest 秒
       （默认 900 = 15 分钟，±10% 抖动），再自动开下一批；
       各 worker 批次互不同步，不会集体停工；
    4. 遇到风控不换 IP：先在当前 IP 上长时间休息
       （--block-rest-min ~ --block-rest-max，默认 10-15 分钟）后重试；
       仍被风控再修复 —— 重启浏览器拿新出口 IP（青果 IP 时效 30 分钟，
       第二次休息时旧 IP 通常已过期轮换），按新 IP 重新配对 Cookie；
       修复后仍失败才标记 failed 跳过该店。

风控处理流程（单店）:
    第 1 次被风控 → 保持当前 IP，休息 10-15 分钟 → 重试同一店铺
    第 2 次被风控 → 修复：重启浏览器（旧 IP 已轮换）→ 新 IP + 新 Cookie
                    → 重试同一店铺
    第 3 次被风控 → 标记 failed，跳过该店继续下一家
    连续失败达到 --max-consecutive-fail 次（默认 5）判定整体被风控，
    立即中止整个任务，当前店铺留在 in_progress，下次运行自动放回 pending。

网络/代理层错误（ERR_TUNNEL_CONNECTION_FAILED 等隧道断开、连接重置、
DNS 失败）与风控区分处理：不计入风控连续失败计数，在原通道上重启
浏览器并退避重试（--net-retry 次）。

显示（状态板，不刷屏）:
    终端内运行时屏幕底部固定 N 行（每 worker 一行），实时刷新：
        [w0] 出口 123.45.67.89 | 批 3 | 采 12（✓9 ○2 ✗1）| abc.1688.com | 样本等待 4.2s
    重要事件（风控、批次休息、修复换 IP、错误）以滚动日志形式打印在
    状态板上方；常规细节（Cookie/代理信息、随机等待）只进状态行。
    输出重定向到文件/管道时自动降级为普通日志。

结果处理:
    - 座机或手机至少有一个 → 写入 contacts 表，店铺标记 done
    - 座机和手机都为空（即使填了联系人/地址/传真）→ 同样写入 contacts
      表备查（含原始文本），店铺标记 no_contact，便于统计和后续复核
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
    export CLOAKBROWSER_LICENSE_KEY=cb_xxx   # 或直接写进 .cache/config.json
    python3 contact_fetcher.py --proxy              # 5 通道 5 worker 并发
    python3 contact_fetcher.py --proxy -n 100       # 每个 worker 每批 100 个
    python3 contact_fetcher.py --proxy -n 50 --max-batches 4   # 最多采 4 批
    python3 contact_fetcher.py --proxy --headed     # 有头模式（首次过滑块）
    python3 contact_fetcher.py --retry-failed       # 先把 failed 重置回 pending
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]  # 项目根目录

import common
from common import (StatusBoard, get_exit_ip, launch_browser,
                    save_cookies, scrape_contact, wait_countdown,
                    wait_manual_unblock)
from database import ShopDB


def _compose_fetcher(wid: int, f: dict) -> str:
    """contact_fetcher 状态行格式（StatusBoard compose 回调）。"""
    return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
            f"采 {f.get('n', 0)}（✓{f.get('ok', 0)} ○{f.get('empty', 0)} "
            f"✗{f.get('failed', 0)}） | {f.get('shop', '-')} | "
            f"{f.get('state', '初始化')}")


# ---------- 浏览器生命周期 ----------

def relaunch_browser(board: StatusBoard, tag: str, wid: int, args,
                     db: ShopDB, proxy_server: str | None,
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
            board.log(f"{tag}   [!] 旧 Cookie 回写失败: {e}")
    if old_browser is not None:
        try:
            old_browser.close()
        except Exception:
            pass

    board.set(wid, state="重启浏览器获取新 IP…", force=True)
    last_err = None
    for attempt in range(1, args.ip_retry + 1):
        if stop.is_set():
            raise RuntimeError("用户中断")
        try:
            browser, page, identity, req_proxies, _ = launch_browser(
                headless=not args.headed, use_proxy=args.proxy, db=db,
                proxy_server=proxy_server, pool_size=args.channels or None,
                stop=stop)
            board.set(wid, ip=identity, state="浏览器已重启", force=True)
            board.log(f"{tag} 浏览器已重启，新出口 IP={identity}")
            return browser, page, identity, req_proxies
        except (Exception, SystemExit) as e:
            last_err = e
            backoff = min(30 * attempt, 120)
            board.log(f"{tag}   [!] 获取新 IP 第 {attempt}/{args.ip_retry} "
                      f"次失败: {e}，{backoff}s 后重试...")
            if wait_countdown(board, wid, stop, backoff, "重启退避"):
                raise RuntimeError("用户中断")
    raise RuntimeError(f"重试 {args.ip_retry} 次仍无法获取新 IP: {last_err}")


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


# ---------- worker ----------

def worker(worker_id: int, args, proxy_server: str | None,
           board: StatusBoard, state: dict, lock: threading.Lock,
           stop: threading.Event):
    """单个抓取 worker：独立浏览器 + 独立 DB 连接 + 独占代理通道。

    生命周期：领通道 → 启动浏览器按出口 IP 配 Cookie → 认领/抓取循环
    （样本间随机间隔，批次间大休息）→ 风控先休息当前 IP，再修复换 IP。
    """
    tag = f"[w{worker_id}]"
    common.set_tag(tag)  # common 内部日志按本 worker 路由到状态板
    db = ShopDB()
    browser = None
    stats = {"ok": 0, "empty": 0, "failed": 0}
    consecutive_fail = 0  # 连续风控失败计数，超限中止整个任务
    identity = "direct"
    ctx = None
    req_proxies = None

    def set_status(**kw):
        board.set(worker_id, **kw)

    try:
        set_status(state="启动浏览器…", force=True)
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
                    return  # 用户中断
        else:
            raise RuntimeError(f"启动浏览器重试 {args.ip_retry} "
                               f"次仍失败: {last_err}")
        ctx = page.context
        batch_no = 1
        done_in_batch = 0  # 本 worker 当前批次已采数量（-n 按 worker 各自计）
        warm_shop = True   # 新会话冷启动：首个店铺先逛首页再进联系方式页
        set_status(ip=identity, batch=batch_no, state="就绪", force=True)

        while not stop.is_set():
            # ---- 批次配额（每个 worker 各自计数）：本 worker 采满 -n 个后
            #      各自强制大休息（±10% 抖动），再自动开下一批；
            #      各 worker 批次互不同步，避免集体停工 ----
            if done_in_batch >= args.num:
                if args.max_batches and batch_no >= args.max_batches:
                    board.log(f"{tag} 第 {batch_no} 批采满，"
                              f"已达批次上限（--max-batches），收工")
                    set_status(state="收工")
                    return  # finally 会保存 Cookie、关闭浏览器
                rest = random.uniform(args.batch_rest * 0.9,
                                      args.batch_rest * 1.1)
                board.log(f"{tag} ⏸ 第 {batch_no} 批已采满 {args.num} 个，"
                          f"强制休息 {rest / 60:.1f} 分钟（防风控）...")
                if wait_countdown(board, worker_id, stop, rest, "批次休息"):
                    return  # 用户中断
                batch_no += 1
                done_in_batch = 0
                board.log(f"{tag} ▶ 休息结束，开始第 {batch_no} 批")
                set_status(batch=batch_no, state="采集中")

            shops = db.claim_pending_shops(1)
            if not shops:
                board.log(f"{tag} 没有待抓取的店铺了")
                set_status(state="无待抓店铺，退出")
                break
            shop = shops[0]
            shop_label = shop["name"] or shop["domain"]
            set_status(shop=shop_label, state="检查出口 IP…")

            # ---- 出口 IP 过期检查（青果每 30 分钟轮换一次出口）----
            if args.proxy:
                need_relaunch, cur_ip, reason = check_ip_fresh(
                    req_proxies, identity)
                if need_relaunch:
                    board.log(f"{tag} 🔄 {reason}，重启浏览器绑定新 IP ...")
                    browser, page, identity, req_proxies = relaunch_browser(
                        board, tag, worker_id, args, db, proxy_server,
                        browser, ctx, identity, stop)
                    ctx = page.context
                    warm_shop = True  # 新会话重新冷启动软着陆

            # ---- 会话冷启动软着陆：新浏览器会话的第一个店铺，先逛店铺
            #      首页留下真实浏览轨迹，再进联系方式页 —— 新会话一上来
            #      就深链 contactinfo.htm 是明显的爬虫特征 ----
            if warm_shop:
                set_status(state="冷启动先逛店铺首页…")
                try:
                    page.goto(f"https://{shop['domain']}/",
                              wait_until="domcontentloaded", timeout=45000)
                    time.sleep(random.uniform(2.0, 5.0))
                except Exception:
                    pass  # 首页打不开不阻断，照常走抓取流程
                warm_shop = False

            # ---- 抓取（网络故障原通道退避重试，不计入风控计数；
            #      风控：先休息当前 IP → 再修复换 IP → 仍失败标 failed）----
            block_stage = 0   # 0 未触发 / 1 已休息过一次 / 2 已修复换过 IP
            net_retried = 0
            while True:
                set_status(state="采集中")
                info = scrape_contact(page, shop["domain"], referer=shop["url"])
                fatal_reason = info.pop("_fatal", None) if info else None
                net_reason = info.pop("_net_error", None) if info else None
                block_reason = info.pop("_blocked", None) if info else None
                if info is not None and not fatal_reason \
                        and not net_reason and not block_reason:
                    consecutive_fail = 0  # 抓到了，连续失败清零
                    break

                # ---- 浏览器进程死亡/被服务端关闭：与风控无关，
                #      直接重启浏览器重试（走网络故障同一条退避路径）----
                if fatal_reason:
                    net_reason = f"浏览器会话终止（{fatal_reason}）"

                # ---- 网络/代理层错误：与风控无关，不计入风控连续失败计数 ----
                if net_reason:
                    net_retried += 1
                    if net_retried > args.net_retry:
                        board.log(f"{tag}   [X] 网络故障重试 {args.net_retry} "
                                  f"次仍失败，标记 failed 跳过（{net_reason}）")
                        db.mark_shop_failed(shop["domain"])
                        stats["failed"] += 1
                        info = None
                        break
                    backoff = min(30 * net_retried, 180)
                    board.log(f"{tag} ⚠ 网络/代理故障（{net_reason}），"
                              f"不计入风控计数，第 {net_retried}/{args.net_retry} "
                              f"次重试（{backoff}s 后）...")
                    if args.proxy:
                        try:
                            browser, page, identity, req_proxies = \
                                relaunch_browser(
                                    board, tag, worker_id, args, db,
                                    proxy_server, browser, ctx, identity, stop)
                            ctx = page.context
                            warm_shop = True  # 新会话重新冷启动软着陆
                        except RuntimeError as e:
                            board.log(f"{tag} [X] 原通道重启浏览器失败: {e}，"
                                      f"中止整个任务")
                            stop.set()
                            return
                    if wait_countdown(board, worker_id, stop, backoff,
                                      "网络故障退避"):
                        return  # 用户中断
                    continue  # 重试同一店铺

                # ---- 抓取失败或疑似被风控拦截 ----
                consecutive_fail += 1
                reason = block_reason or "页面加载失败（疑似风控拦截）"
                # 记录该出口 IP 的风控遭遇（评估代理 IP 质量用）；
                # 登录墙是更高一级的风控（会话被要求强制登录），
                # 原地休息/手动滑块都无意义，直接进修复换 IP 阶段
                login_wall = "login.1688.com" in reason
                db.record_ip_event(
                    identity,
                    "block_login" if login_wall else
                    ("block_slider" if block_reason else "block_other"),
                    reason)
                if login_wall and block_stage == 0:
                    block_stage = 1
                    board.log(f"{tag} ⚠ 触发登录墙（{reason}），出口 {identity} "
                              f"已被高风险标记，不原地休息，直接修复换 IP")
                if consecutive_fail >= args.max_consecutive_fail:
                    board.log(f"{tag} [X] 已连续失败 {consecutive_fail} 次"
                              f"（最近一次: {reason}），判定被风控，中止整个任务")
                    board.log(f"{tag}     店铺 {shop['domain']} 留在 "
                              f"in_progress，下次运行自动放回 pending")
                    stop.set()
                    return  # finally 会保存 Cookie、关闭浏览器

                if block_stage == 0:
                    # 第一次被风控：不换 IP，当前 IP 上长时间休息后再试
                    block_stage = 1
                    rest = random.uniform(args.block_rest_min,
                                          args.block_rest_max)
                    board.log(f"{tag} ⚠ {reason}（连续失败 "
                              f"{consecutive_fail}/{args.max_consecutive_fail}）"
                              f" → 保持当前 IP {identity}，"
                              f"休息 {rest / 60:.1f} 分钟后重试")
                    if args.headed:
                        # 有头模式：优先等用户手动过滑块，过了立即继续，
                        # 并把新下发的 x5sec 等 Cookie 写回该出口 IP 名下
                        board.log(f"{tag}   👉 请在 {identity} 的浏览器窗口里"
                                  f"手动完成验证，脚本每 15s 自动检测"
                                  f"（最长 {rest / 60:.1f} 分钟）...")
                        if wait_manual_unblock(board, worker_id, stop,
                                               page, rest):
                            board.log(f"{tag} ✓ 检测到验证已通过，"
                                      f"Cookie 写回 {identity}，立即继续采集")
                            try:
                                save_cookies(db, identity, ctx)
                            except Exception as e:
                                board.log(f"{tag}   [!] Cookie 回写失败: {e}")
                            continue  # 同一 IP 重试同一店铺
                        if stop.is_set():
                            return
                        board.log(f"{tag}   未检测到手动验证通过，"
                                  f"按原计划休息后重试")
                    if wait_countdown(board, worker_id, stop, rest,
                                      f"风控休息(1)"):
                        return  # 用户中断
                    continue  # 同一 IP 重试同一店铺

                if block_stage == 1:
                    # 休息后仍被风控 → 修复：重启浏览器拿新出口 IP。
                    # 青果 IP 时效 30 分钟，此时旧 IP 通常已过期轮换，
                    # launch_browser 会按新 IP 重新配对 Cookie。
                    block_stage = 2
                    board.log(f"{tag} ⚠ 休息后仍被风控（{reason}）"
                              f" → 修复：重启浏览器获取新出口 IP 并重新配对 Cookie")
                    old_identity = identity
                    try:
                        browser, page, identity, req_proxies = \
                            relaunch_browser(
                                board, tag, worker_id, args, db,
                                proxy_server, browser, ctx, identity, stop)
                        ctx = page.context
                        warm_shop = True  # 新会话重新冷启动软着陆
                    except RuntimeError as e:
                        board.log(f"{tag} [X] 修复换 IP 失败: {e}，中止整个任务")
                        stop.set()
                        return
                    if args.proxy and identity == old_identity:
                        # 出口还没轮换（休息不足 30 分钟）：再等一轮让青果轮换
                        rest = random.uniform(args.block_rest_min,
                                              args.block_rest_max)
                        board.log(f"{tag}   [!] 出口 IP 尚未轮换（青果 30 分钟时效），"
                                  f"再休息 {rest / 60:.1f} 分钟等其过期后重试")
                        if wait_countdown(board, worker_id, stop, rest,
                                          "等 IP 轮换"):
                            return
                        try:
                            browser, page, identity, req_proxies = \
                                relaunch_browser(
                                    board, tag, worker_id, args, db,
                                    proxy_server, browser, ctx, identity, stop)
                            ctx = page.context
                            warm_shop = True  # 新会话重新冷启动软着陆
                        except RuntimeError as e:
                            board.log(f"{tag} [X] 二次修复仍失败: {e}，"
                                      f"中止整个任务")
                            stop.set()
                            return
                    continue  # 新 IP + 新 Cookie 重试同一店铺

                # 修复换 IP 后仍失败：标记 failed，放过这家继续下一家
                board.log(f"{tag}   [X] 休息与修复后仍失败，"
                          f"标记 failed 跳过（{reason}）")
                db.mark_shop_failed(shop["domain"])
                stats["failed"] += 1
                info = None
                break

            if info is None:
                pass  # 上面已标记 failed
            elif not (info.get("phone") or info.get("mobile")):
                # 座机和手机都为空即视为无有效联系方式（只填联系人/地址/传真
                # 也不算）：仍入 contacts 表备查（含地址、原始文本等），
                # 但店铺标记 no_contact 而不是 done，便于统计和复核
                raw = info.pop("_raw", None)
                src = info.pop("_source_url", None)
                db.save_contact(shop["domain"], info,
                                source_url=src, raw_text=raw)
                db.mark_shop_no_contact(shop["domain"], bump_attempts=False)
                stats["empty"] += 1
                set_status(state="无有效电话，标记 no_contact")
            else:
                raw = info.pop("_raw", None)
                src = info.pop("_source_url", None)
                db.save_contact(shop["domain"], info,
                                source_url=src, raw_text=raw)
                stats["ok"] += 1
                set_status(state=f"✓ {info['contact_person'] or '-'}"
                                 f"({info['gender'] or '-'}) "
                                 f"电话={info['phone'] or '-'} "
                                 f"手机={info['mobile'] or '-'}")

            # 本店处理完毕（含标记 failed），计入本 worker 当前批次配额
            done_in_batch += 1

            # 每次成功后把浏览器里的最新 Cookie（含可能轮换的 x5sec、
            # 以及手动过证后新签发的安全 Cookie）写回该出口 IP 名下 ——
            # 进程意外退出也不丢信任链，同 IP 复访直接复用
            if info is not None:
                try:
                    save_cookies(db, identity, ctx)
                except Exception:
                    pass

            n_local = sum(stats.values())
            set_status(n=n_local, ok=stats["ok"], empty=stats["empty"],
                       failed=stats["failed"])

            # 样本之间的随机间隔（防风控）；各 worker 按编号递增基准
            # 间隔，避免多 worker 同频齐步请求形成集群特征
            lo = args.sample_min + worker_id * 1.5
            hi = args.sample_max + worker_id * 2.5
            t = random.uniform(lo, hi)
            set_status(state=f"样本间隔 {t:.1f}s")
            if stop.wait(t):
                return
            # 每隔一定轮次随机长休息一次，模拟真人连续浏览后的停顿
            if (args.rest_every > 0 and n_local % args.rest_every == 0
                    and not stop.is_set()):
                t = random.uniform(args.rest_min, args.rest_max)
                board.log(f"{tag} ☕ 已连续抓取 {n_local} 个，"
                          f"随机长休息 {t / 60:.1f} 分钟 ...")
                if wait_countdown(board, worker_id, stop, t, "长休息"):
                    return  # 用户中断
    except Exception as e:
        board.log(f"{tag} [X] worker 异常退出: {e}")
    finally:
        # 退出前把浏览器里的最新 Cookie（含新 x5sec）写回该出口 IP 名下
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
        set_status(state="已退出", force=True)
        with lock:
            state["stats"][worker_id] = stats
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="1688 店铺联系方式抓取（多 worker 并发，状态板显示，断点续爬）")
    ap.add_argument("-n", "--num", type=int, default=10,
                    help="每个 worker 每批抓取的店铺数量（默认 10）；"
                         "采满一批后各自强制休息再开下一批")
    ap.add_argument("--batch-rest", type=float, default=900,
                    help="每批采满后的强制休息秒数（默认 900=15 分钟，±10%% 抖动）")
    ap.add_argument("--max-batches", type=int, default=0,
                    help="每个 worker 最多采集多少批（默认 0=不限，抓完 pending 为止）")
    ap.add_argument("--ip-retry", type=int, default=3,
                    help="重启浏览器获取新出口 IP 的重试次数（默认 3）")
    ap.add_argument("--block-rest-min", type=float, default=600,
                    help="风控后保持当前 IP 的休息时长下限秒数（默认 600=10 分钟）")
    ap.add_argument("--block-rest-max", type=float, default=900,
                    help="风控后保持当前 IP 的休息时长上限秒数（默认 900=15 分钟）")
    ap.add_argument("--net-retry", type=int, default=5,
                    help="单店遇到网络/代理层错误（隧道断开等，非风控）时的"
                         "重试次数（默认 5，不计入风控连续失败计数）")
    ap.add_argument("--max-consecutive-fail", type=int, default=5,
                    help="连续失败多少次后判定被风控并中止整个任务（默认 5）")
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感）")
    ap.add_argument("--retry-failed", action="store_true",
                    help="先把 failed 店铺重置为 pending 再开始抓取")
    ap.add_argument("--rest-every", type=int, default=20,
                    help="每个 worker 每抓取多少个店铺后长休息一次（默认 20，0 关闭）")
    ap.add_argument("--sample-min", type=float, default=13.0,
                    help="样本之间随机间隔的下限秒数（默认 13）")
    ap.add_argument("--sample-max", type=float, default=20.0,
                    help="样本之间随机间隔的上限秒数（默认 20）")
    ap.add_argument("--rest-min", type=float, default=60,
                    help="长休息随机时长的下限秒数（默认 60）")
    ap.add_argument("--rest-max", type=float, default=180,
                    help="长休息随机时长的上限秒数（默认 180）")
    ap.add_argument("--stagger-min", type=float, default=15.0,
                    help="worker 启动错开的最小秒数（默认 15；多会话同分钟出生、"
                         "同节奏访问是集群特征，启动时间必须打散）")
    ap.add_argument("--stagger-max", type=float, default=60.0,
                    help="worker 启动错开的最大秒数（默认 60）")
    ap.add_argument("--proxy", action="store_true",
                    help="走 util/proxy_qingguo.py 的青果住宅代理；"
                         "Cookie 按出口 IP 存 SQLite（记录过期时间），"
                         "退出时自动把最新 Cookie 写回该 IP 名下")
    ap.add_argument("--channels", type=int, default=0,
                    help="青果通道池大小（默认取 proxy_qingguo.CONFIG['channels']）")
    ap.add_argument("--workers", type=int, default=0,
                    help="并发 worker 数；代理模式默认=通道数，直连模式默认 1")
    args = ap.parse_args()

    db = ShopDB()
    if args.retry_failed:
        n = db.reset_failed()
        print(f"[0] 已把 {n} 个 failed 店铺重置回 pending")
    # 上次中断残留的 in_progress 全部放回 pending
    n = db.reset_in_progress()
    if n:
        print(f"[0] 已把 {n} 个中断残留的 in_progress 店铺重置回 pending")

    total_pending = db.count_pending()
    if total_pending == 0:
        print(f"[OK] 没有待抓取的店铺。统计: {db.stats()}")
        print("    先运行 shop_crawler.py 采集更多店铺")
        db.close()
        return 0
    print(f"[1] 待抓取 {total_pending} 个，每个 worker 每批 {args.num} 个"
          f"（{'最多 ' + str(args.max_batches) + ' 批' if args.max_batches else '不限批数，抓完 pending 为止'}），"
          f"批间强制休息 {args.batch_rest / 60:.0f} 分钟")

    # ---- 并发度与通道分配（一 worker 一通道，IP + Cookie 配套）----
    proxy_servers: list = [None]
    if args.proxy:
        sys.path.insert(0, str(ROOT_DIR / "util"))
        import proxy_qingguo
        pool = proxy_qingguo.get_pool(args.channels or None)
        n_channels = len(pool.servers())
        workers = args.workers or n_channels
        if workers > n_channels:
            print(f"[!] workers({workers}) > 通道数({n_channels})，"
                  f"部分 worker 将共用通道（共享出口 IP），不建议")
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

    # ---- 状态板：common 内部日志按线程标签路由进来 ----
    board = StatusBoard(workers, compose=_compose_fetcher)

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
    board.start()

    state = {"stats": {}}
    lock = threading.Lock()
    stop = threading.Event()

    # 直接关终端窗口(SIGHUP)或被 kill(SIGTERM)时也走正常清理流程：
    # 各 worker 关闭浏览器，服务端会话租约立即释放，
    # 否则残留租约要等 ~10 分钟才过期，会堵住下次启动的席位
    import signal

    def _graceful_exit(signum, frame):
        board.log(f"[!] 收到信号 {signum}，通知各 worker 清理后退出...")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _graceful_exit)
        except (OSError, ValueError):
            pass  # 平台不支持该信号时跳过

    threads = [
        threading.Thread(target=worker,
                         args=(i, args, proxy_servers[i], board,
                               state, lock, stop),
                         name=f"fetcher-{i}", daemon=True)
        for i in range(workers)
    ]
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
        board.log("[!] 用户中断，等待各 worker 完成当前店铺后退出...")
        stop.set()
        for t in threads:
            t.join(timeout=90)
        board.log("[!] 进度已保存在数据库，下次运行自动续爬")

    ok = sum(s["ok"] for s in state["stats"].values())
    empty = sum(s["empty"] for s in state["stats"].values())
    failed = sum(s["failed"] for s in state["stats"].values())
    print(f"[OK] 本次完成: 有联系方式 {ok}, 无联系方式 {empty}, 失败 {failed}")
    print(f"    数据库统计: {db.stats()}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
