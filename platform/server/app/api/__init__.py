# -*- coding: utf-8 -*-
"""API 路由包。"""

from fastapi import APIRouter

from app.api import costs, dashboard, data, health, providers

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(dashboard.router)
api_router.include_router(data.router)
api_router.include_router(providers.router)
api_router.include_router(costs.router)
