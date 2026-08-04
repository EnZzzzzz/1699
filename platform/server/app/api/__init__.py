# -*- coding: utf-8 -*-
"""API 路由包。"""

from fastapi import APIRouter

from app.api import dashboard, data, health, providers, tasks, wa

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(dashboard.router)
api_router.include_router(data.router)
api_router.include_router(tasks.router)
api_router.include_router(providers.router)
api_router.include_router(wa.router)
