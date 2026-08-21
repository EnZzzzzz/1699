# -*- coding: utf-8 -*-
"""采集平台管理系统后端（看板 / 数据浏览 / 供应商 / health）。

启动（在 platform/server 目录下）：
    .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router

app = FastAPI(title="采集平台管理系统 API", version="0.2.0")

# 允许本地开发前端（任意 localhost 端口）
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://localhost(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
