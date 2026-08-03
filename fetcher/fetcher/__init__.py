# -*- coding: utf-8 -*-
"""fetcher：1688 采集重构包（P0+P1）。

分层：
    core      公共协议（Scenario / ActionResult / Session / WorkerContext / 错误分级）
    net       网络层（BrowserManager / IdentityStore / 代理通道 / 种子身份池）
    atoms     原子能力层（只做动作，报告 Outcome）
    detect    场景判断层（只读状态，返回 Scenario）
    strategy  策略层（包装原子，声明式策略表）
    sites     站点插件层（1688 为第一个实现）
    db        数据存储（ShopDB，schema 与 .cache/1688.db 兼容）

重依赖（cloakbrowser / playwright / requests）全部延迟导入：
`import fetcher` 与跑单测不需要安装它们。
"""

from fetcher.core import (
    ActionResult,
    BrowserLaunchError,
    CircuitBreakerTripped,
    ExitIPError,
    FetcherError,
    LicenseSeatTimeout,
    Outcome,
    RunConfig,
    Scenario,
    Session,
    UserInterrupted,
    WorkerContext,
    browser_alive,
    classify_error,
    is_fatal_browser_error,
    is_network_error,
)
from fetcher.db import ShopDB
from fetcher.detect import Detector, SceneInspector
from fetcher.net import (
    BrowserManager,
    IdentityStore,
    SeedBurnTracker,
    fingerprint_args,
    get_exit_ip,
    load_license_key,
    load_seed_kits,
    wait_for_license_seat,
)
from fetcher.net.proxy import (
    Channel,
    DirectProvider,
    KuaiDaiLiProvider,
    ProxyProvider,
    QingGuoProvider,
)
from fetcher.sites import Alibaba1688Plugin, SitePlugin
from fetcher.strategy import (
    DEFAULT_POLICY_TABLE,
    AttemptTracker,
    Policy,
    PolicyAction,
    PolicyDecision,
    StepResult,
    Strategy,
)


def __getattr__(name):  # 控制层延迟导出（避免 import fetcher 拉起控制层依赖链）
    if name in ("CrawlLoop", "Engine", "Task", "CircuitBreaker", "StatusBoard"):
        from fetcher import control
        return getattr(control, name)
    raise AttributeError(f"module 'fetcher' has no attribute {name!r}")


__version__ = "0.2.0"

__all__ = [
    "ActionResult",
    "Alibaba1688Plugin",
    "AttemptTracker",
    "BrowserLaunchError",
    "BrowserManager",
    "Channel",
    "CircuitBreaker",
    "CircuitBreakerTripped",
    "CrawlLoop",
    "DEFAULT_POLICY_TABLE",
    "Detector",
    "DirectProvider",
    "Engine",
    "ExitIPError",
    "FetcherError",
    "IdentityStore",
    "KuaiDaiLiProvider",
    "LicenseSeatTimeout",
    "Outcome",
    "Policy",
    "PolicyAction",
    "PolicyDecision",
    "ProxyProvider",
    "QingGuoProvider",
    "RunConfig",
    "Scenario",
    "SceneInspector",
    "SeedBurnTracker",
    "Session",
    "ShopDB",
    "SitePlugin",
    "StatusBoard",
    "StepResult",
    "Strategy",
    "Task",
    "UserInterrupted",
    "WorkerContext",
    "browser_alive",
    "classify_error",
    "fingerprint_args",
    "get_exit_ip",
    "is_fatal_browser_error",
    "is_network_error",
    "load_license_key",
    "load_seed_kits",
    "wait_for_license_seat",
]
