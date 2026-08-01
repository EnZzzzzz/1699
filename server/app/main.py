# -*- coding: utf-8 -*-
"""
FastAPI 入口：lifespan 内完成 DB 迁移/seed、启动 PoolManager 与出口 IP 探测
定时器（默认 60s/通道，EXIT_IP_PROBE_ENABLED / EXIT_IP_PROBE_INTERVAL 可配），
关闭时优雅停止后台任务。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from . import config
from .db import SessionLocal, init_db
from .logging_setup import setup_logging
from .api import pool as pool_api
from .api import providers as providers_api
from .api import export as export_api
from .api import shops as shops_api
from .api import stats as stats_api
from .api import tasks as tasks_api
from .api import workers as workers_api
from .api import ws as ws_api
from .services import usage as usage_service
from .services.pool_client import read_heartbeats
from .services.proxy.manager import PoolManager

setup_logging()


async def _probe_loop(pool: PoolManager, stop: asyncio.Event) -> None:
    """出口 IP 探测定时器：每 EXIT_IP_PROBE_INTERVAL 秒逐通道探测一次。"""
    cleanup_counter = 0
    while not stop.is_set():
        try:
            results = await asyncio.to_thread(pool.probe_all)
            fails = [r for r in results if not r["ok"]]
            logger.info("出口IP探测: {} 通道, {} 失败", len(results), len(fails))
            # 每 60 轮（约 1 小时）顺带清理过期使用事件
            cleanup_counter += 1
            if cleanup_counter >= 60:
                cleanup_counter = 0
                n = await asyncio.to_thread(
                    usage_service.cleanup_old, config.USAGE_RETENTION_DAYS)
                if n:
                    logger.info("清理过期使用事件 {} 条", n)
        except Exception:  # noqa: BLE001 - 定时器循环不退出
            logger.exception("出口IP探测本轮失败")
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.EXIT_IP_PROBE_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def _reclaim_loop(pool: PoolManager, stop: asyncio.Event) -> None:
    """心跳超时回收：每 30s 读 Redis 心跳，回收崩溃 worker 残留的通道。"""
    while not stop.is_set():
        try:
            beats = await asyncio.to_thread(read_heartbeats)
            if beats:
                stale = await asyncio.to_thread(pool.reclaim_stale, beats, 90)
                if stale:
                    logger.warning("心跳超时，已回收任务通道: {}", stale)
        except Exception:  # noqa: BLE001
            logger.exception("心跳回收本轮失败")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    pool = PoolManager(SessionLocal)
    pool.ensure_direct_channel()
    app.state.pool = pool

    stop = asyncio.Event()
    bg_tasks = []
    if config.EXIT_IP_PROBE_ENABLED:
        bg_tasks.append(asyncio.create_task(_probe_loop(pool, stop)))
        logger.info("出口IP探测定时器已启动（{}s/通道）",
                    config.EXIT_IP_PROBE_INTERVAL)
    else:
        logger.info("出口IP探测定时器已禁用（EXIT_IP_PROBE_ENABLED=0）")
    if config.RECLAIM_ENABLED:
        bg_tasks.append(asyncio.create_task(_reclaim_loop(pool, stop)))
    else:
        logger.info("心跳回收循环已禁用（RECLAIM_ENABLED=0）")

    yield

    # 优雅停止：先置位再取消，避免还在跑的一轮探测阻塞退出
    stop.set()
    for t in bg_tasks:
        t.cancel()
        with suppress(asyncio.CancelledError):
            await t
    logger.info("后台任务已停止")


app = FastAPI(title="1688 采集平台后端", version="0.2.0-m5", lifespan=lifespan)

# 单机本机使用：放开 CORS 供 Vite dev 前端直连
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(providers_api.router)
app.include_router(pool_api.router)
app.include_router(stats_api.router)
app.include_router(tasks_api.router)
app.include_router(workers_api.router)
app.include_router(shops_api.router)
app.include_router(export_api.router)
app.include_router(ws_api.router)


@app.get("/")
def root():
    return {
        "name": "1688 采集平台后端",
        "version": "0.2.0-m5",
        "scope": "M1 骨架+迁移 / M2 Provider层 / M3 共享池 / M4 Celery任务 / M5 全部API",
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT)
