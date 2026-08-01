# -*- coding: utf-8 -*-
"""loguru 全局日志配置 + 标准 logging 桥接。

- 彩色 stderr 输出（终端 / celery.log 友好）
- 滚动文件 server/logs/server.log：50 MB 滚动、保留 14 天、enqueue=True
  （线程安全；uvicorn 主进程与 celery worker 进程各自初始化，多进程写
  同一文件由 loguru 内部序列化保证不交错）
- uvicorn / celery / 第三方库的标准 logging 经 InterceptHandler 桥接到
  loguru（原 logger 名与级别保留；celery 自己的 --logfile 不受影响）

用法：进程入口（app.main / app.workers.celery_app）import 后调用一次
setup_logging()；业务模块直接 `from loguru import logger`。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "server.log"

_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} | {message}"
)
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"
)

# 桥接时这些标准 logger 自带 handler（uvicorn/celery 自己的控制台/文件），
# 保留原样只确保 propagate 到 root -> InterceptHandler
_KEEP_OWN_HANDLERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "celery")


class InterceptHandler(logging.Handler):
    """把标准 logging 记录转发给 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage())


def setup_logging(level: str = "INFO") -> None:
    """初始化 loguru 并桥接标准 logging；幂等（重复调用安全）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True,
               format=_CONSOLE_FORMAT, backtrace=False, diagnose=False)
    logger.add(str(LOG_FILE), level=level, format=_FILE_FORMAT,
               rotation="50 MB", retention="14 days",
               enqueue=True, encoding="utf-8")

    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(level)
    for name in _KEEP_OWN_HANDLERS:
        std = logging.getLogger(name)
        std.propagate = True
