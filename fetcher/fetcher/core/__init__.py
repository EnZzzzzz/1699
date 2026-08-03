# -*- coding: utf-8 -*-
"""core：公共协议层（类型 / 会话 / 上下文 / 错误分级）。"""

from fetcher.core.context import PROJECT_ROOT, RunConfig, WorkerContext
from fetcher.core.errors import (
    BrowserLaunchError,
    CircuitBreakerTripped,
    ExitIPError,
    FetcherError,
    LicenseSeatTimeout,
    UserInterrupted,
    browser_alive,
    classify_error,
    is_fatal_browser_error,
    is_network_error,
)
from fetcher.core.session import Session
from fetcher.core.types import ActionResult, Outcome, Scenario

__all__ = [
    "ActionResult",
    "BrowserLaunchError",
    "CircuitBreakerTripped",
    "ExitIPError",
    "FetcherError",
    "LicenseSeatTimeout",
    "Outcome",
    "PROJECT_ROOT",
    "RunConfig",
    "Scenario",
    "Session",
    "UserInterrupted",
    "WorkerContext",
    "browser_alive",
    "classify_error",
    "is_fatal_browser_error",
    "is_network_error",
]
