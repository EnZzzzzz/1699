# -*- coding: utf-8 -*-
"""全局配置：路径、出口 IP 探测、使用事件保留期等（均可环境变量覆盖）。"""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]          # 项目根 1699/
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT_DIR / ".cache" / "1688.db")))

# 出口 IP 探测：默认开启，每 60s 逐通道经代理请求 PROBE_URL
EXIT_IP_PROBE_ENABLED = os.getenv("EXIT_IP_PROBE_ENABLED", "1").lower() not in ("0", "false", "no", "off")
EXIT_IP_PROBE_INTERVAL = int(os.getenv("EXIT_IP_PROBE_INTERVAL", "60"))
EXIT_IP_PROBE_URL = os.getenv("EXIT_IP_PROBE_URL", "https://ipinfo.io/json")
EXIT_IP_PROBE_TIMEOUT = int(os.getenv("EXIT_IP_PROBE_TIMEOUT", "30"))

# proxy_usage_events 保留天数（定时清理旧数据）
USAGE_RETENTION_DAYS = int(os.getenv("USAGE_RETENTION_DAYS", "7"))

# 心跳超时回收循环（多实例共用一库时，可对外来实例关闭以防误回收）
RECLAIM_ENABLED = os.getenv("RECLAIM_ENABLED", "1").lower() not in ("0", "false", "no", "off")

# Celery（M4 使用，先在此统一定义）
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

# API 服务
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8765"))


def now_str() -> str:
    """与现有库一致的时间字符串格式（本地时间）。"""
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")
