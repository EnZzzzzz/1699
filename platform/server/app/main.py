# -*- coding: utf-8 -*-
"""采集平台管理系统后端（看板 / 数据浏览 / 供应商 / health）。

启动（在 platform/server 目录下）：
    .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
"""

import threading
import time
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import costs
from app.api import api_router

app = FastAPI(title="采集平台管理系统 API", version="0.2.0")

# 费用自动同步间隔（秒）：半小时跑一次 sync_all（Apify 真实账单 + BD 余额 + 渠道估算）
COST_SYNC_INTERVAL = 1800

# 允许本地开发前端（任意 localhost 端口）
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://localhost(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


def _cost_sync_loop():
    """常驻费用同步线程：启动即跑一轮，之后每 COST_SYNC_INTERVAL 秒一轮。

    sync_all 幂等 upsert、单源失败不影响其他源；整轮异常只记日志不退出，
    保证线程常驻（uvicorn 无 reload，单实例运行，无线程重复问题）。
    """
    while True:
        try:
            costs.sync_all()
        except Exception:  # noqa: BLE001 - 兜底，线程不能死
            traceback.print_exc()
        time.sleep(COST_SYNC_INTERVAL)


@app.on_event("startup")
def _start_cost_sync():
    threading.Thread(
        target=_cost_sync_loop, daemon=True, name="cost-sync").start()
