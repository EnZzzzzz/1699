# -*- coding: utf-8 -*-
"""
Celery task：shop_crawl 店铺采集（生产者，多线程 worker 模型）。

重写自 scraper/taobao_1688/shop_crawler.py（蓝本只读，未被 import），
流程等价：引导浏览器提取类目 → （headed 时人工确认）→ 多线程按
category_progress 分页采集 → 店铺入库 pending。

与蓝本差异：
    - 通道经 PoolClient 向共享池 acquire/release（不直连青果 API）；
    - 每轮请求经 PoolClient.report 上报 proxy_usage_events；
    - 周期更新 tasks.progress_json + Redis 心跳；每轮检查 stop_requested；
    - 人工确认从终端 input() 改为 POST /api/tasks/{id}/confirm（Redis 标记），
      params.yes=True 跳过。

params（tasks.params_json，docs/service-architecture.md §7）：
    target      int   本任务新增店铺数目标（服务端语义；0 = 每个 worker 采 1 轮。
                      与 board.collected 口径一致：first_seen_at >= started_at）
    category    str?  指定类目关键词（指定后单 worker 只采该类目下一页）
    workers     int   并发线程数（默认 1；指定 category 时强制 1）
    channels    int   向共享池申请的通道数（默认 1）
    proxy       bool  是否走代理通道（False = 直连本机 IP）
    headed      bool  有头模式（含人工确认流程，yes=True 跳过确认）
    yes         bool  跳过人工确认（无人值守）
    start_delay_min/start_delay_max int 启动前等待秒数区间（默认 0/0；
                      相等=固定等待，不等=random.uniform 抽签；running 后、
                      申请通道前倒计时，每 10s 一条事件，期间可停止且不占资源）
    rotate_every int  每成功采 N 轮（页）主动换通道+重启浏览器换出口 IP
                      （默认 0=关；仅代理模式生效）
    rest_every  int   每 worker 每 N 轮长时休息（0 关闭）
    delay_min/delay_max  轮间随机延迟秒
    rest_min/rest_max    长时休息秒数区间
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
    wait_for_license_seat,
)
from ..services.crawl.shopdb import ShopDB
from ..services.pool_client import (
    PoolAcquireTimeout, PoolClient, swap_channel_with_events, wait_confirmation,
)
from ..services.task_runtime import TaskRuntime, start_delay_countdown
from .celery_app import celery_app

RISK_STREAK_THRESHOLD = 2  # 连续空轮达到该值即判定疑似风控，主动终止
STALE_STREAK_LIMIT = 5     # 有提取但无新增的连续轮数上限（类目枯竭）


def _target_reached(state: dict) -> bool:
    """目标达成判定（服务端语义）：本任务新增店铺数达到 target。

    与旧 CLI 的区别：旧语义是"库中累计 N 个"（库已有几千个时会瞬间满足），
    服务端语义是"本任务启动后新增 N 个"（state["collected"]，与
    GET /api/tasks/{id} 的 board.collected 口径一致）。
    target=0（state["target_new"] 为 None）时退化为旧默认行为：
    每个 worker 采 1 轮即收工（state["rounds"] >= workers）。
    """
    target_new = state["target_new"]
    if target_new is not None:
        return state["collected"] >= target_new
    return state["rounds"] >= state["workers"]


def _worker(worker_id: int, params: dict, rt: TaskRuntime,
            pool_client: PoolClient, channel: dict,
            state: dict, lock: threading.Lock, stop: threading.Event):
    """单个采集 worker：独立浏览器 + 独立 DB 连接，从共享类目队列取类目。"""
    tag = f"[w{worker_id}]"
    db = ShopDB()
    browser, ctx, page = None, None, None
    identity = "direct"
    req_proxies = None
    cur_ip = None

    def refresh_ip():
        nonlocal cur_ip
        ip = get_exit_ip(req_proxies)
        if ip:
            cur_ip = ip
        return cur_ip

    def close_browser():
        nonlocal browser, ctx
        if ctx is not None:
            try:
                save_cookies(db, identity, ctx)
            except Exception as e:
                logger.warning("{}   [!] Cookie 回写失败: {}", tag, e)
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        browser, ctx = None, None

    def reopen_browser(new_channel) -> bool:
        """关旧浏览器（回写 Cookie）并绑定新通道重启。返回是否成功。"""
        nonlocal browser, ctx, page, identity, req_proxies, cur_ip
        close_browser()
        if not wait_for_license_seat(tag=f"{tag} ", timeout=180.0):
            logger.error("{} [X] CloakBrowser 会话席位超时未释放", tag)
            return False
        server, auth = pool_client.channel_proxy(new_channel)
        browser, page, identity, req_proxies, _ = launch_browser(
            db, headless=not params["headed"],
            proxy_server=server, proxy_auth=auth)
        ctx = page.context
        cur_ip = None
        logger.info("{} 浏览器已重启绑定新通道 (identity={})", tag, identity)
        return True

    def on_suspected_block(reason: str):
        with lock:
            state["empty_streak"] += 1
            streak = state["empty_streak"]
        logger.warning("{}   [!] {}（全局连续 {} 轮），可能被风控",
                       tag, reason, streak)
        rt.emit("warning", f"{reason}（全局连续 {streak} 轮），疑似被风控",
                {"worker": worker_id, "streak": streak})
        if stop.is_set() or streak < RISK_STREAK_THRESHOLD:
            return
        logger.warning("{}   [主动终止] 连续 {} 轮为空，停止采集防加重风控",
                       tag, streak)
        rt.emit("warning", f"连续 {streak} 轮为空，判定疑似风控，主动终止采集"
                "（避免反复请求加重风控，可隔段时间再跑续采）",
                {"worker": worker_id, "streak": streak})
        stop.set()

    try:
        if not wait_for_license_seat(tag=f"{tag} ", timeout=180.0):
            logger.error("{} [X] CloakBrowser 会话席位超时未释放，worker 退出",
                         tag)
            rt.emit("error", "CloakBrowser 会话席位超时未释放，采集 worker 退出",
                    {"worker": worker_id})
            return
        server, auth = pool_client.channel_proxy(channel)
        browser, page, identity, req_proxies, _ = launch_browser(
            db, headless=not params["headed"],
            proxy_server=server, proxy_auth=auth)
        ctx = page.context
        logger.info("{} 浏览器就绪 (identity={})", tag, identity)
        rt.emit("info", f"采集 worker{worker_id} 浏览器就绪（出口 IP: {identity}）",
                {"worker": worker_id, "identity": identity})

        rounds_since_rest = 0
        rounds_since_rotate = 0  # 成功采页计数（用于 rotate_every 主动换 IP）
        while not stop.is_set() and not rt.stop_requested():
            # ---- 从共享队列取一个未采完的类目 ----
            cat, page_no = None, 1
            while not stop.is_set():
                with lock:
                    if _target_reached(state) or not state["queue"]:
                        break
                    candidate = state["queue"].pop()
                prog = db.get_category_progress(candidate["keyword"])
                if prog and prog["exhausted"]:
                    continue
                cat = candidate
                page_no = prog["next_page"] if prog else 1
                with lock:
                    state["rounds"] += 1
                break
            if cat is None:
                break

            url = pg.category_page_url(cat["url"], page_no)
            cur = refresh_ip()
            logger.info("{} 类目: {} 第 {} 页 (IP: {}，本任务新增 {}/{})",
                        tag, cat["name"], page_no, cur or "?",
                        state["collected"], state["target_new"] or "∞")
            rt.emit("info", f"正在采集类目「{cat['name']}」第 {page_no} 页"
                    f"（出口 IP: {cur or '查询失败'}）",
                    {"worker": worker_id, "category": cat["name"],
                     "keyword": cat["keyword"], "page": page_no,
                     "url": url, "exit_ip": cur})
            try:
                page.goto(url, wait_until="domcontentloaded",
                          timeout=60000, referer=pg.HOMEPAGE)
            except Exception as e:
                pool_client.report(channel, result="error",
                                   task_type="shop_crawl", exit_ip=cur_ip)
                on_suspected_block(f"类目页打开失败: {e}")
                continue
            pg.human_pause(4, 8)

            for _ in range(3):
                page.mouse.wheel(0, random.randint(600, 1200))
                time.sleep(random.uniform(1.0, 2.0))

            shops = pg.extract_shops(page)
            blocked = pg.page_blocked(page) if not shops else False
            pool_client.report(
                channel,
                result="blocked" if blocked else ("error" if not shops else "ok"),
                task_type="shop_crawl", exit_ip=cur_ip)
            logger.info("{}   第 {} 页提取到 {} 个店铺",
                        tag, page_no, len(shops))
            if not shops:
                if page_no > 1 and not blocked:
                    db.mark_category_exhausted(cat["keyword"], cat["name"])
                    rt.emit("info", f"类目「{cat['name']}」第 {page_no} 页无结果，"
                            "标记为已采完（exhausted）",
                            {"worker": worker_id, "category": cat["name"],
                             "keyword": cat["keyword"], "page": page_no})
                else:
                    on_suspected_block("未提取到店铺")
                continue

            run_id = db.start_run(cat["name"], cat["keyword"])
            # ---- 整页入库（超采语义）：提取的店铺全部 upsert，本页采完后再
            # 由 _target_reached 判停。upsert 不进锁（DB 事务自身原子），
            # 锁只保护 collected / queue / empty_streak 计数。
            inserted = db.upsert_shops(shops, run_id=run_id,
                                       category_keyword=cat["keyword"])
            with lock:
                state["collected"] += inserted
                if not params["category"]:
                    state["queue"].insert(0, cat)
                if inserted == 0:
                    # 提取正常但无新增：类目枯竭，不算风控
                    state["empty_streak"] += 1
                    if state["empty_streak"] >= STALE_STREAK_LIMIT:
                        stop.set()
                else:
                    state["empty_streak"] = 0
            db.finish_run(run_id, shops_found=len(shops),
                          note=f"new={inserted} page={page_no} task={rt.task_id}")
            db.advance_category_page(cat["keyword"], cat["name"],
                                     shops_found=len(shops))
            rt.track(inserted)
            rt.set_progress(collected=state["collected"],
                            total=state["target_new"],
                            per_minute=rt.per_minute())
            rt.emit(
                "success" if inserted > 0 else "info",
                f"类目「{cat['name']}」第 {page_no} 页：提取 {len(shops)} 个店铺，"
                f"新增入库 {inserted} 个"
                + (f"（累计 {state['collected']} / 目标 {state['target_new']}）"
                   if state["target_new"] is not None else ""),
                {"worker": worker_id, "category": cat["name"],
                 "keyword": cat["keyword"], "page": page_no,
                 "extracted": len(shops), "inserted": inserted,
                 "collected": state["collected"], "target": state["target_new"]})

            # ---- 节奏控制：每采满 rest_every 轮长时休息 ----
            rounds_since_rest += 1
            rounds_since_rotate += 1
            if (params["rest_every"] > 0
                    and rounds_since_rest >= params["rest_every"]
                    and not _target_reached(state) and not stop.is_set()):
                rounds_since_rest = 0
                t = random.uniform(params["rest_min"], params["rest_max"])
                logger.info("{}   [休息] 静默 {:.1f} 分钟（防风控）",
                            tag, t / 60)
                rt.emit("warning", f"已连续采集 {params['rest_every']} 轮，"
                        f"长时休息 {t / 60:.1f} 分钟（防风控）",
                        {"worker": worker_id, "seconds": round(t)})
                stop.wait(t)

            if not _target_reached(state) and not stop.is_set():
                t = random.uniform(params["delay_min"], params["delay_max"])
                rt.emit("info", f"轮间休息 {t:.0f} 秒（控频）",
                        {"worker": worker_id, "seconds": round(t)})
                stop.wait(t)

            # ---- 主动换 IP：每采满 rotate_every 轮，换通道 + 重启浏览器 ----
            if (params["proxy"] and params["rotate_every"] > 0
                    and rounds_since_rotate >= params["rotate_every"]
                    and not _target_reached(state) and not stop.is_set()):
                rounds_since_rotate = 0
                old_ip = identity
                try:
                    channel = swap_channel_with_events(
                        rt, pool_client, channel, worker_id,
                        note=f"每 {params['rotate_every']} 轮主动换 IP")
                    ok = reopen_browser(channel)
                except Exception as e:
                    ok = False
                    logger.error("{} [X] 主动换 IP 失败: {}", tag, e)
                if not ok:
                    rt.emit("error", "主动换 IP 换通道或重启浏览器失败，中止任务",
                            {"worker": worker_id})
                    with lock:
                        state["fatal"] = "主动换 IP 重启浏览器失败"
                    stop.set()
                    break
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
        rt.emit("error", f"采集 worker 异常退出：{e}", {"worker": worker_id})
    finally:
        close_browser()
        db.close()


def run_shop_crawl(task_id: int, celery_id: str | None = None) -> dict:
    rt = TaskRuntime(task_id)
    pool_client = PoolClient(task_id)
    params = {}
    try:
        with SessionLocal() as db:
            t = db.get(Task, task_id)
            if t is None:
                return {"ok": False, "error": f"task {task_id} 不存在"}
            params = json.loads(t.params_json)
            if celery_id:
                t.celery_id = celery_id
                db.commit()
        params = _normalize_params(params)
        rt.set_status("running", celery_id=celery_id)
        rt.start_heartbeat()

        # ---- 启动前等待（在申请通道之前，不占用任何资源）----
        if not start_delay_countdown(rt, params["start_delay_min"],
                                     params["start_delay_max"]):
            rt.set_status("stopped")
            return {"ok": False, "stopped": True}

        # ---- 申请通道（实际占用 min(channels, workers)，超出截断）----
        workers = 1 if params["category"] else params["workers"]
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
            baseline = db0.count_shops()
            # 服务端语义：target = 本任务新增 N 个（不再用库中累计判定，
            # 否则库已有几千个店铺时任务会瞬间"已达目标"退出）
            target_new = params["target"] if params["target"] > 0 else None
            logger.info("[task {}] 库中现有 {} 个店铺，本任务目标新增 {}，"
                        "started_at 已先于任何采集动作记录",
                        task_id, baseline, target_new or "每 worker 1 轮")
            rt.emit("info", f"库中现有 {baseline} 个店铺，本任务目标新增"
                    f" {target_new or '每 worker 1 轮'}，{workers} 个 worker",
                    {"baseline": baseline, "target": target_new,
                     "workers": workers})

            # ---- 引导浏览器：提取类目 + （headed 时）人工确认 ----
            if not wait_for_license_seat(tag="    "):
                rt.set_status("failed", error="CloakBrowser 会话席位超时未释放")
                return {"ok": False, "error": "license seat timeout"}
            server, auth = pool_client.channel_proxy(channels[0])
            bootstrap_headless = params["yes"] and not params["headed"]
            rt.emit("info", "引导浏览器已启动"
                    f"（{'无头' if bootstrap_headless else '有头'}模式），"
                    "正在打开 1688 首页提取类目",
                    {"headless": bootstrap_headless})
            browser, page, identity, _, _ = launch_browser(
                db0, headless=bootstrap_headless,
                proxy_server=server, proxy_auth=auth)
            try:
                page.goto(pg.HOMEPAGE, wait_until="domcontentloaded",
                          timeout=60000)
                pg.human_pause(3, 6)
                categories = pg.extract_categories(page)
                if not categories:
                    rt.set_status("failed", error="首页未提取到类目，可能被风控")
                    return {"ok": False, "error": "no categories"}
                rt.emit("info", f"首页提取到 {len(categories)} 个类目",
                        {"count": len(categories)})
                warmup = (next((c for c in categories
                                if c["keyword"] == params["category"]), None)
                          or random.choice(categories))
                try:
                    page.goto(warmup["url"], wait_until="domcontentloaded",
                              timeout=60000, referer=pg.HOMEPAGE)
                    pg.human_pause(4, 8)
                except Exception as e:
                    logger.warning("    [!] 类目页打开失败: {}", e)
                if params["yes"]:
                    logger.info("    [yes] 跳过人工确认")
                    rt.emit("info", "按参数跳过人工确认，直接开始采集")
                else:
                    rt.set_progress(phase="waiting_confirm")
                    rt.emit("info", f"引导浏览器已打开类目页「{warmup['name']}」，"
                            "等待人工确认（如有滑块请在浏览器中拖动通过，"
                            "然后在前端点击确认）",
                            {"warmup_category": warmup["name"]})
                    ok = wait_confirmation(task_id, should_stop=rt.stop_requested)
                    if not ok:
                        rt.set_status("stopped", error="人工确认超时或被停止")
                        return {"ok": False, "stopped": True}
                    rt.emit("success", "已收到人工确认，开始采集")
                rt.set_progress(phase="crawling")
                save_cookies(db0, identity, page.context)
            finally:
                try:
                    save_cookies(db0, identity, page.context)
                except Exception:
                    pass
                browser.close()

            # ---- 组装类目队列 ----
            if params["category"]:
                cat = next(
                    (c for c in categories if c["keyword"] == params["category"]),
                    {"name": params["category"], "keyword": params["category"],
                     "url": "https://s.1688.com/selloffer/offer_search.htm"
                            f"?charset=utf8&keywords={params['category']}"})
                queue = [cat]
            else:
                queue = categories[:]
                random.shuffle(queue)
                queue = [c for c in queue
                         if not ((p := db0.get_category_progress(c["keyword"]))
                                 and p["exhausted"])]
                if not queue:
                    rt.set_status("done", error="所有类目均已采到末页")
                    return {"ok": True, "note": "all exhausted"}

            rt.emit("info", f"类目队列就绪：{len(queue)} 个可采类目，"
                    f"启动 {workers} 个采集 worker",
                    {"queue_size": len(queue), "workers": workers})
            state = {"queue": queue, "baseline": baseline,
                     "target_new": target_new, "workers": workers,
                     "rounds": 0, "empty_streak": 0, "collected": 0,
                     "fatal": None}
            lock = threading.Lock()
            stop = threading.Event()
            rt.set_progress(collected=0, total=target_new, per_minute=0,
                            pending=db0.count_pending())

            threads = []
            for i in range(workers):
                channel = channels[i % len(channels)]
                th = threading.Thread(
                    target=_worker,
                    args=(i, params, rt, pool_client, channel, state, lock, stop),
                    name=f"crawl-{task_id}-{i}", daemon=True)
                threads.append(th)
            for th in threads:
                th.start()
                time.sleep(1.0)

            # ---- 监控循环：进度 + 停止 ----
            while any(th.is_alive() for th in threads):
                if rt.stop_requested():
                    stop.set()
                rt.set_progress(collected=state["collected"],
                                total=state["target_new"],
                                per_minute=rt.per_minute(),
                                pending=db0.count_pending())
                time.sleep(10)
            for th in threads:
                th.join(timeout=90)

            if state.get("fatal"):
                rt.set_status("failed", error=state["fatal"])
                return {"ok": False, "error": state["fatal"]}
            if rt.stop_requested():
                rt.emit("warning", "任务被停止，通道已释放",
                        {"collected": state["collected"]})
                rt.set_status("stopped")
                return {"ok": True, "stopped": True}
            if target_new is not None and state["collected"] >= target_new:
                rt.emit("success",
                        f"已达目标：本任务新增 {state['collected']} 个店铺"
                        f"（target={target_new}）",
                        {"collected": state["collected"], "target": target_new})
            rt.emit("info", "采集收尾：Cookie 已写回、使用事件已上报、通道已释放",
                    {"collected": state["collected"]})
            rt.set_status("done")
            return {"ok": True, "collected": state["collected"]}
        finally:
            db0.close()
            pool_client.flush_events()
            pool_client.release()
    except Exception as e:  # noqa: BLE001 - 任务级兜底
        rt.set_status("failed", error=str(e))
        return {"ok": False, "error": str(e)}
    finally:
        rt.close()


def _normalize_params(p: dict) -> dict:
    return {
        "target": int(p.get("target") or 0),
        "category": p.get("category") or None,
        "workers": max(1, int(p.get("workers") or 1)),
        "channels": max(1, int(p.get("channels") or 1)),
        "proxy": bool(p.get("proxy")),
        "headed": bool(p.get("headed")),
        "yes": bool(p.get("yes", True)),
        "start_delay_min": int(p.get("start_delay_min") or 0),
        "start_delay_max": int(p.get("start_delay_max") or 0),
        "rotate_every": int(p.get("rotate_every") or 0),
        "rest_every": int(p.get("rest_every") or 0),
        "delay_min": float(p.get("delay_min") or 15.0),
        "delay_max": float(p.get("delay_max") or 45.0),
        "rest_min": float(p.get("rest_min") or 300.0),
        "rest_max": float(p.get("rest_max") or 600.0),
    }


@celery_app.task(name="crawl.shop_crawl", bind=True)
def shop_crawl_task(self, task_id: int) -> dict:
    return run_shop_crawl(task_id, celery_id=self.request.id)
