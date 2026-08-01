# -*- coding: utf-8 -*-
"""
Celery 实例（broker/backend = 本地 Redis）。

worker 启动：
    celery -A app.workers.celery_app worker --pool=threads --concurrency=8

任务（M4）：
    crawl.shop_crawl     店铺采集（app/workers/shop_crawl.py）
    crawl.contact_fetch  联系方式抓取（app/workers/contact_fetch.py）
    crawl.flow_run       DAG 流水线通用入口（app/workers/flow_run.py，P1）

通道统一经 POST /api/pool/acquire|release 申请归还，使用事件经
POST /api/pool/events 上报，停止走 tasks.stop_requested 协作式检查。
"""
from celery import Celery

from .. import config
from ..logging_setup import setup_logging

# worker 进程内启用 loguru（业务日志走 server/logs/server.log；
# celery 自身日志仍由其 --logfile 管理，并经 InterceptHandler 桥接进 loguru）
setup_logging()

celery_app = Celery(
    "server1688",
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
    include=["app.workers.shop_crawl", "app.workers.contact_fetch",
             "app.workers.flow_run"],
)

celery_app.conf.update(
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_time_limit=6 * 3600,       # 采集任务可能长跑：硬上限 6h
    task_soft_time_limit=5.5 * 3600,
    broker_connection_retry_on_startup=True,
)
