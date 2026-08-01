# -*- coding: utf-8 -*-
"""
Celery task：contact_fetch 联系方式抓取（消费者，多线程 worker 模型）。

重写自 scraper/taobao_1688/contact_fetcher.py（蓝本只读，未被 import），
流程等价：原子认领 pending 店铺（claim_pending_shops）→ 联系方式页解析 →
done / no_contact / failed 标记；批次配额 + 批间强制休息；出口 IP 轮换检查
（青果 30min 轮换 → 重启浏览器绑定新 identity）；风控/网络故障分类处置。

与蓝本差异：
    - 通道经 PoolClient acquire/release；切换通道 = release 当前通道回池 +
      全池随机重抽（池侧原子，swap_channel_with_events 埋点）；
    - 每次抓取经 PoolClient.report 上报使用事件；
    - tasks.progress_json + Redis 心跳 + stop_requested 协作式停止。

params（tasks.params_json，docs/service-architecture.md §7）：
    workers     int   并发线程数（默认 1）
    channels    int   向共享池申请的通道数（默认 1）
    proxy       bool  是否走代理通道
    limit       int   本次最多抓取多少家（0 = 抓完 pending）
    headed      bool  有头模式
    start_delay_min/start_delay_max int 启动前等待秒数区间（默认 0/0；
                      相等=固定等待，不等=random.uniform 抽签；running 后、
                      申请通道前倒计时，每 10s 一条事件，期间可停止且不占资源）
    rotate_every int  每成功处理 N 个（抓取成功+no_contact）主动换通道+
                      重启浏览器换出口 IP（默认 0=关；仅代理模式生效）
    num         int   每批抓取数量（默认 10）
    batch_rest  float 批间强制休息秒（默认 900）
    max_batches int   最多批数（0 不限）
    block_retry / net_retry / ip_retry / max_consecutive_fail  重试参数
    rest_every / rest_min / rest_max  每抓 N 个长时休息及休息时长区间
"""
from __future__ import annotations

import json
import random
import threading
import time

from loguru import logger

from ..db import SessionLocal
from ..models import Task
from ..services.crawl import pages as pg
from ..services.crawl.browser import (
    BrowserUnavailable, get_exit_ip, launch_browser, save_cookies,
)
from ..services.crawl.shopdb import ShopDB
from ..services.pool_client import (
    PoolAcquireTimeout, PoolClient, swap_channel_with_events,
)
from ..services.task_runtime import TaskRuntime, start_delay_countdown
from .celery_app import celery_app


def _normalize_params(p: dict) -> dict:
    return {
        "workers": max(1, int(p.get("workers") or 1)),
        "channels": max(1, int(p.get("channels") or 1)),
        "proxy": bool(p.get("proxy")),
        "limit": int(p.get("limit") or 0),
        "headed": bool(p.get("headed")),
        "start_delay_min": int(p.get("start_delay_min") or 0),
        "start_delay_max": int(p.get("start_delay_max") or 0),
        "rotate_every": int(p.get("rotate_every") or 0),
        "num": max(1, int(p.get("num") or 10)),
        "batch_rest": float(p.get("batch_rest") or 900),
        "max_batches": int(p.get("max_batches") or 0),
        "ip_retry": int(p.get("ip_retry") or 3),
        "block_retry": int(p.get("block_retry") or 2),
        "net_retry": int(p.get("net_retry") or 5),
        "max_consecutive_fail": int(p.get("max_consecutive_fail") or 5),
        "rest_every": int(p.get("rest_every") or 20),
        "rest_min": float(p.get("rest_min") or 60),
        "rest_max": float(p.get("rest_max") or 180),
    }


def _relaunch_browser(tag, params, db, channel, pool_client,
                      old_browser, old_ctx, old_identity, stop):
    """关闭旧浏览器（先回写 Cookie），重开新实例绑定新出口 IP。"""
    if old_ctx is not None:
        try:
            save_cookies(db, old_identity, old_ctx)
        except Exception as e:
            logger.warning("{}   [!] 旧 Cookie 回写失败: {}", tag, e)
    if old_browser is not None:
        try:
            old_browser.close()
        except Exception:
            pass
    last_err = None
    for attempt in range(1, params["ip_retry"] + 1):
        if stop.is_set():
            raise RuntimeError("任务已停止")
        try:
            server, auth = pool_client.channel_proxy(channel)
            browser, page, identity, req_proxies, _ = launch_browser(
                db, headless=not params["headed"],
                proxy_server=server, proxy_auth=auth)
            logger.info("{} 浏览器已重启，新 identity={}", tag, identity)
            return browser, page, identity, req_proxies
        except (Exception, SystemExit) as e:
            last_err = e
            backoff = min(30 * attempt, 120)
            logger.warning("{}   [!] 重启浏览器第 {}/{} 次失败: {}，{}s 后重试",
                           tag, attempt, params["ip_retry"], e, backoff)
            stop.wait(backoff)
    raise RuntimeError(f"重试 {params['ip_retry']} 次仍无法重启浏览器: {last_err}")


def _check_ip_fresh(req_proxies, identity) -> tuple:
    """(need_relaunch, cur_ip, reason)：青果出口 IP 每 30 分钟轮换。"""
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


def _worker(worker_id: int, params: dict, rt: TaskRuntime,
            pool_client: PoolClient, channels: list, channel: dict,
            state: dict, lock: threading.Lock, stop: threading.Event):
    tag = f"[w{worker_id}]"
    db = ShopDB()
    browser, ctx, page = None, None, None
    identity = "direct"
    req_proxies = None
    stats = {"ok": 0, "empty": 0, "failed": 0}
    consecutive_fail = 0
    since_rotate = 0  # 成功处理计数（ok+empty，用于 rotate_every 主动换 IP）
    try:
        server, auth = pool_client.channel_proxy(channel)
        browser, page, identity, req_proxies, _ = launch_browser(
            db, headless=not params["headed"],
            proxy_server=server, proxy_auth=auth)
        ctx = page.context
        logger.info("{} 浏览器就绪 (identity={})", tag, identity)
        rt.emit("info", f"抓取 worker{worker_id} 浏览器就绪（出口 IP: {identity}）",
                {"worker": worker_id, "identity": identity})

        while not stop.is_set() and not rt.stop_requested():
            # ---- 批次配额 ----
            while True:
                with lock:
                    if state["limit"] and state["fetched"] >= state["limit"]:
                        wait_for = -1.0
                    elif state["done"] < params["num"]:
                        state["done"] += 1
                        wait_for = 0.0
                    elif (params["max_batches"]
                          and state["batch"] >= params["max_batches"]) \
                            or db.count_pending() == 0:
                        wait_for = -1.0
                    else:
                        now = time.time()
                        if state["rest_until"] <= now:
                            state["rest_until"] = now + random.uniform(
                                params["batch_rest"] * 0.9,
                                params["batch_rest"] * 1.1)
                        wait_for = state["rest_until"] - now
                if wait_for == 0.0:
                    break
                if wait_for < 0:
                    return
                logger.info("{} ⏸ 第 {} 批采满，休息 {:.1f} 分钟（防风控）",
                            tag, state["batch"], wait_for / 60)
                rt.emit("warning", f"第 {state['batch']} 批已采满 {params['num']} 个，"
                        f"批间休息 {wait_for / 60:.1f} 分钟（防风控）",
                        {"worker": worker_id, "batch": state["batch"],
                         "seconds": round(wait_for)})
                if stop.wait(wait_for) or rt.stop_requested():
                    return
                with lock:
                    if state["done"] >= params["num"]:
                        state["done"] = 0
                        state["batch"] += 1

            shops = db.claim_pending_shops(1)
            if not shops:
                rt.emit("info", "没有待抓取的店铺了", {"worker": worker_id})
                break
            shop = shops[0]
            shop_label = f"{shop['name'] or shop['domain']}（{shop['domain']}）"
            rt.emit("info", f"已认领店铺 {shop_label}，正在抓取联系方式"
                    f"（出口 IP: {identity}）",
                    {"worker": worker_id, "domain": shop["domain"],
                     "shop_id": shop["id"], "name": shop["name"],
                     "exit_ip": identity})

            # ---- 出口 IP 过期检查 ----
            if params["proxy"]:
                need, cur_ip, reason = _check_ip_fresh(req_proxies, identity)
                if need:
                    try:
                        if cur_ip is None:
                            # 隧道疑似失效：release 回池 + 全池随机重抽
                            channel = swap_channel_with_events(
                                rt, pool_client, channel, worker_id,
                                note="出口 IP 查询失败")
                        logger.info("{} 🔄 {}，重启浏览器获取新 IP", tag, reason)
                        rt.emit("warning", f"{reason}，重启浏览器绑定新出口 IP",
                                {"worker": worker_id, "old_ip": identity,
                                 "new_ip": cur_ip})
                        browser, page, identity, req_proxies = _relaunch_browser(
                            tag, params, db, channel, pool_client,
                            browser, ctx, identity, stop)
                        ctx = page.context
                    except Exception as e:
                        logger.error("{} [X] 换通道/重启浏览器失败: {}，中止任务",
                                     tag, e)
                        rt.emit("error", f"换通道或重启浏览器失败：{e}，"
                                "中止整个任务", {"worker": worker_id})
                        stop.set()
                        return

            # ---- 抓取（网络故障/风控分类处置，与蓝本一致）----
            block_retried = net_retried = 0
            while True:
                info = pg.scrape_contact(page, shop["domain"],
                                         referer=shop["url"])
                net_reason = info.pop("_net_error", None) if info else None
                block_reason = info.pop("_blocked", None) if info else None
                if info is not None and not net_reason and not block_reason:
                    pool_client.report(channel, result="ok",
                                       task_type="contact_fetch",
                                       exit_ip=identity)
                    consecutive_fail = 0
                    break

                if net_reason:
                    pool_client.report(channel, result="error",
                                       task_type="contact_fetch",
                                       exit_ip=identity)
                    net_retried += 1
                    if net_retried > params["net_retry"]:
                        db.mark_shop_failed(shop["domain"])
                        stats["failed"] += 1
                        rt.emit("error", f"{shop_label} 抓取失败：网络故障重试"
                                f" {params['net_retry']} 次仍失败，标记 failed"
                                f"（{net_reason}）（出口 IP: {identity}）",
                                {"worker": worker_id, "domain": shop["domain"],
                                 "reason": net_reason, "exit_ip": identity})
                        info = None
                        break
                    backoff = min(30 * net_retried, 180)
                    rt.emit("warning", f"{shop_label} 网络/代理故障"
                            f"（{net_reason}），第 {net_retried}/"
                            f"{params['net_retry']} 次重试（{backoff}s 后）",
                            {"worker": worker_id, "domain": shop["domain"],
                             "reason": net_reason, "retry": net_retried})
                    if params["proxy"]:
                        try:
                            channel = swap_channel_with_events(
                                rt, pool_client, channel, worker_id,
                                note="网络故障换通道")
                            browser, page, identity, req_proxies = \
                                _relaunch_browser(
                                    tag, params, db, channel, pool_client,
                                    browser, ctx, identity, stop)
                            ctx = page.context
                        except Exception as e:
                            logger.error("{} [X] 换通道重启失败: {}，中止任务",
                                         tag, e)
                            rt.emit("error", f"换通道重启浏览器失败：{e}，"
                                    "中止整个任务", {"worker": worker_id})
                            stop.set()
                            return
                    if stop.wait(backoff):
                        return
                    continue

                # 疑似风控
                pool_client.report(channel, result="blocked",
                                   task_type="contact_fetch", exit_ip=identity)
                consecutive_fail += 1
                reason = block_reason or "页面加载失败（疑似风控拦截）"
                if consecutive_fail >= params["max_consecutive_fail"]:
                    logger.error("{} [X] 连续失败 {} 次，判定被风控，"
                                 "中止任务（店铺留 in_progress）",
                                 tag, consecutive_fail)
                    rt.emit("error", f"已连续失败 {consecutive_fail} 次"
                            f"（最近：{reason}），判定被风控，中止整个任务",
                            {"worker": worker_id, "domain": shop["domain"],
                             "reason": reason})
                    stop.set()
                    return
                if block_retried < params["block_retry"]:
                    block_retried += 1
                    rt.emit("warning", f"{shop_label} 疑似被风控（{reason}），"
                            f"第 {block_retried}/{params['block_retry']} 次"
                            "换通道重试",
                            {"worker": worker_id, "domain": shop["domain"],
                             "reason": reason, "retry": block_retried})
                    if params["proxy"]:
                        try:
                            channel = swap_channel_with_events(
                                rt, pool_client, channel, worker_id,
                                note="疑似风控换通道")
                            browser, page, identity, req_proxies = \
                                _relaunch_browser(
                                    tag, params, db, channel, pool_client,
                                    browser, ctx, identity, stop)
                            ctx = page.context
                        except Exception as e:
                            logger.error("{} [X] 换 IP 失败: {}，中止任务",
                                         tag, e)
                            rt.emit("error", f"换 IP 重启浏览器失败：{e}，"
                                    "中止整个任务", {"worker": worker_id})
                            stop.set()
                            return
                    else:
                        backoff = min(60 * block_retried, 300)
                        rt.emit("warning", f"直连模式无法换 IP，退避 {backoff}s 后重试",
                                {"worker": worker_id, "seconds": backoff})
                        stop.wait(backoff)
                    continue

                db.mark_shop_failed(shop["domain"])
                stats["failed"] += 1
                rt.emit("error", f"{shop_label} 抓取失败：换 IP 重试"
                        f" {params['block_retry']} 次仍失败（{reason}），标记 failed"
                        f"（出口 IP: {identity}）",
                        {"worker": worker_id, "domain": shop["domain"],
                         "reason": reason, "exit_ip": identity})
                info = None
                break

            if info is not None:
                raw = info.pop("_raw", None)
                src = info.pop("_source_url", None)
                db.save_contact(shop["domain"], info, source_url=src,
                                raw_text=raw)
                if not (info.get("phone") or info.get("mobile")):
                    db.mark_shop_no_contact(shop["domain"], bump_attempts=False)
                    stats["empty"] += 1
                    rt.emit("info", f"{shop_label} 无有效电话（座机/手机均空），"
                            f"已记录条目并标记 no_contact（出口 IP: {identity}）",
                            {"worker": worker_id, "domain": shop["domain"],
                             "result": "no_contact", "exit_ip": identity})
                else:
                    stats["ok"] += 1
                    rt.emit("success", f"{shop_label} 抓取成功：联系人="
                            f"{info['contact_person']}（{info['gender']}）"
                            f" 电话={info['phone']} 手机={info['mobile']}"
                            f"（出口 IP: {identity}）",
                            {"worker": worker_id, "domain": shop["domain"],
                             "result": "done", "exit_ip": identity,
                             "contact_person": info["contact_person"],
                             "phone": info["phone"], "mobile": info["mobile"]})
                rt.track(1)
                since_rotate += 1
                with lock:
                    state["fetched"] += 1
                rt.set_progress(collected=state["fetched"],
                                total=state["limit"] or None,
                                pending=db.count_pending(),
                                per_minute=rt.per_minute())


            pg.human_pause(3, 7)
            done_local = sum(stats.values())
            if (params["rest_every"] > 0
                    and done_local % params["rest_every"] == 0
                    and not stop.is_set()):
                t = random.uniform(params["rest_min"], params["rest_max"])
                rt.emit("warning", f"已连续抓取 {done_local} 个，"
                        f"长时休息 {t:.0f} 秒（防风控）",
                        {"worker": worker_id, "seconds": round(t)})
                stop.wait(t)

            # ---- 主动换 IP：每成功处理 rotate_every 个，换通道 + 重启浏览器 ----
            if (params["proxy"] and params["rotate_every"] > 0
                    and since_rotate >= params["rotate_every"]
                    and not stop.is_set()
                    # limit 已达时不再多做一次无意义的轮换
                    and not (state["limit"]
                             and state["fetched"] >= state["limit"])):
                since_rotate = 0
                old_ip = identity
                try:
                    channel = swap_channel_with_events(
                        rt, pool_client, channel, worker_id,
                        note=f"每 {params['rotate_every']} 个主动换 IP")
                    browser, page, identity, req_proxies = _relaunch_browser(
                        tag, params, db, channel, pool_client,
                        browser, ctx, identity, stop)
                    ctx = page.context
                except Exception as e:
                    logger.error("{} [X] 主动换 IP 失败: {}，中止任务", tag, e)
                    rt.emit("error", f"主动换 IP 换通道或重启浏览器失败：{e}，"
                            "中止整个任务", {"worker": worker_id})
                    stop.set()
                    return
                rt.emit("warning",
                        f"已成功处理 {params['rotate_every']} 个，"
                        f"主动更换出口 IP：旧 {old_ip} → 新 {identity}",
                        {"worker": worker_id, "old_ip": old_ip,
                         "new_ip": identity})
    except BrowserUnavailable as e:
        logger.error("{} [X] {}", tag, e)
        rt.emit("error", f"浏览器不可用：{e}", {"worker": worker_id})
        with lock:
            state["fatal"] = str(e)
        stop.set()
    except Exception as e:
        logger.exception("{} [X] worker 异常退出: {}", tag, e)
        rt.emit("error", f"抓取 worker 异常退出：{e}", {"worker": worker_id})
    finally:
        if ctx is not None:
            try:
                save_cookies(db, identity, ctx)
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        db.close()


def run_contact_fetch(task_id: int, celery_id: str | None = None) -> dict:
    rt = TaskRuntime(task_id)
    pool_client = PoolClient(task_id)
    try:
        with SessionLocal() as db:
            t = db.get(Task, task_id)
            if t is None:
                return {"ok": False, "error": f"task {task_id} 不存在"}
            params = _normalize_params(json.loads(t.params_json))
            if celery_id:
                t.celery_id = celery_id
                db.commit()
        rt.set_status("running", celery_id=celery_id)
        rt.start_heartbeat()

        # ---- 启动前等待（在申请通道之前，不占用任何资源）----
        if not start_delay_countdown(rt, params["start_delay_min"],
                                     params["start_delay_max"]):
            rt.set_status("stopped")
            return {"ok": False, "stopped": True}

        # ---- 申请通道（实际占用 min(channels, workers)，超出截断）----
        workers = params["workers"]
        n_channels = min(params["channels"], workers) if params["proxy"] else 1
        if params["proxy"] and params["channels"] > n_channels:
            rt.emit("info", f"通道数 {params['channels']} 超过并发数"
                    f" {workers}，实际占用 {n_channels} 条",
                    {"requested": params["channels"], "workers": workers,
                     "effective": n_channels})
        rt.emit("info", f"正在向共享池申请 {n_channels} 条"
                f"{'代理' if params['proxy'] else '直连'}通道",
                {"n": n_channels, "use_proxy": params["proxy"]})
        try:
            channels = pool_client.acquire(
                n_channels, use_proxy=params["proxy"],
                should_stop=rt.stop_requested)
        except PoolAcquireTimeout as e:
            rt.set_status("stopped", error=str(e))
            return {"ok": False, "stopped": True}
        rt.emit("info", f"申请到 {len(channels)} 条通道："
                + "、".join(f"#{c['id']}({c.get('exit_ip') or c.get('tunnel') or '本机IP'})"
                            for c in channels),
                {"channels": [{"id": c["id"], "tunnel": c.get("tunnel"),
                               "exit_ip": c.get("exit_ip")} for c in channels]})

        db0 = ShopDB()
        try:
            n = db0.reset_in_progress()  # 上次中断残留的认领放回 pending
            if n:
                logger.info("[task {}] {} 个残留 in_progress 店铺已重置回 pending",
                            task_id, n)
                rt.emit("info", f"{n} 个中端残留的 in_progress 店铺已重置回 pending",
                        {"count": n})
            if db0.count_pending() == 0:
                rt.set_status("done", error="没有待抓取店铺")
                return {"ok": True, "note": "no pending"}

            state = {"done": 0, "batch": 1, "rest_until": 0.0,
                     "fetched": 0, "limit": params["limit"], "fatal": None}
            lock = threading.Lock()
            stop = threading.Event()
            rt.set_progress(collected=0, total=params["limit"] or None,
                            pending=db0.count_pending(), per_minute=0)
            rt.emit("info", f"待抓取 {db0.count_pending()} 个店铺，"
                    f"启动 {workers} 个抓取 worker"
                    + (f"（本任务限抓 {params['limit']} 个）" if params["limit"] else ""),
                    {"pending": db0.count_pending(), "workers": workers,
                     "limit": params["limit"]})

            threads = []
            for i in range(workers):
                channel = channels[i % len(channels)]
                th = threading.Thread(
                    target=_worker,
                    args=(i, params, rt, pool_client, channels, channel,
                          state, lock, stop),
                    name=f"fetch-{task_id}-{i}", daemon=True)
                threads.append(th)
            for th in threads:
                th.start()
                time.sleep(1.0)

            while any(th.is_alive() for th in threads):
                if rt.stop_requested():
                    stop.set()
                rt.set_progress(collected=state["fetched"],
                                total=params["limit"] or None,
                                pending=db0.count_pending(),
                                per_minute=rt.per_minute())
                time.sleep(10)
            for th in threads:
                th.join(timeout=90)

            if state.get("fatal"):
                rt.set_status("failed", error=state["fatal"])
                return {"ok": False, "error": state["fatal"]}
            if rt.stop_requested():
                rt.emit("warning", "任务被停止，通道已释放",
                        {"fetched": state["fetched"]})
                rt.set_status("stopped")
                return {"ok": True, "stopped": True}
            rt.emit("success", f"抓取收尾完成：本任务共处理 {state['fetched']} 个店铺",
                    {"fetched": state["fetched"]})
            rt.set_status("done")
            return {"ok": True, "fetched": state["fetched"]}
        finally:
            db0.close()
            pool_client.flush_events()
            pool_client.release()
    except Exception as e:  # noqa: BLE001
        rt.set_status("failed", error=str(e))
        return {"ok": False, "error": str(e)}
    finally:
        rt.close()


@celery_app.task(name="crawl.contact_fetch", bind=True)
def contact_fetch_task(self, task_id: int) -> dict:
    return run_contact_fetch(task_id, celery_id=self.request.id)
