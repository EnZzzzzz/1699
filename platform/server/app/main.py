# -*- coding: utf-8 -*-
"""采集平台管理系统后端（P0 + P1 任务监督器）。

启动（在 platform/server 目录下）：
    .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.runner import runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：清理 DB 里遗留的 running 孤儿任务
    runner.startup()
    yield
    # 关闭：终止仍在跑的子进程，避免留下孤儿
    runner.shutdown()


app = FastAPI(title="采集平台管理系统 API", version="0.2.0", lifespan=lifespan)

# 允许本地开发前端（任意 localhost 端口）
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://localhost(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
