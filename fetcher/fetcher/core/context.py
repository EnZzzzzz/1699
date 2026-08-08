# -*- coding: utf-8 -*-
"""WorkerContext / RunConfig：原子与策略执行时共享的上下文。

WorkerContext 是控制层（P2）装配好后传给 Atom/Detector/Strategy 的
唯一载体。本阶段（P0+P1）只定义结构，不起控制循环。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from fetcher.core.session import Session

if TYPE_CHECKING:
    from fetcher.net.browser import BrowserManager
    from fetcher.net.identity import IdentityStore
    from fetcher.sites.base import SitePlugin

# 包所在仓库的项目根（fetcher/ 是项目根的子目录）：
# .../<root>/fetcher/fetcher/core/context.py -> parents[3] = <root>
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = PROJECT_ROOT / ".cache"


@dataclass
class RunConfig:
    """一次采集运行的全部配置（对应旧 add_common_args 的网络层参数）。"""

    # ---- 浏览器 / 代理 ----
    headless: bool = True
    use_proxy: bool = False
    channels: int = 0               # 通道池大小；0 = 用 provider 默认
    db_path: Path | str | None = None   # None = 项目根 .cache/1688.db

    # ---- 种子身份池 ----
    seeds_dir: Path | str | None = None  # None = 项目根 .cache/seeds
    seed_x5sec: bool = False        # x5sec 免滑块 A/B 实验

    # ---- 直连模式 Cookie 种子（仅 direct 身份兜底导入用）----
    cookie_json: Path | str | None = None  # None = 项目根 .cache/cookies_1688.json

    # ---- 重试 / 休息 ----
    ip_retry: int = 3               # 重启浏览器获取新出口 IP 的重试次数
    net_retry: int = 5              # 单任务项网络层错误重试次数
    max_consecutive_fail: int = 5   # 熔断：连续失败多少次中止整个任务
    block_rest_min: float = 600     # 风控休息下限（秒）
    block_rest_max: float = 900     # 风控休息上限（秒）

    # ---- 批次与节奏（对应旧 add_common_args） ----
    batch_num: int = 10             # 每 worker 每批采集量（-n）
    batch_rest: float = 900         # 批间强制休息（秒，±10% 抖动）
    max_batches: int = 0            # 每 worker 最多批数（0=不限）
    limit: int = 0                  # 每 worker 本次最多采集量（0=不限）
    sample_min: float = 13.0        # 样本间隔下限（秒，按 worker 编号递增错峰）
    sample_max: float = 20.0        # 样本间隔上限（秒）
    rest_every: int = 20            # 每完成多少单位长休息一次（0 关闭）
    rest_min: float = 60            # 长休息下限（秒）
    rest_max: float = 180           # 长休息上限（秒）
    stagger_min: float = 15.0       # worker 启动错开下限（秒）
    stagger_max: float = 60.0       # worker 启动错开上限（秒）
    workers: int = 0                # 并发 worker 数（0=按通道数/直连 1）

    # ---- 席位等待 ----
    license_seat_timeout: float = 600.0

    # ---- 行为开关 ----
    auto_solve_slider: bool = True  # 是否启用轨迹回放自动过证

    def resolved_db_path(self) -> Path:
        return Path(self.db_path) if self.db_path else DEFAULT_CACHE_DIR / "1688.db"

    def resolved_seeds_dir(self) -> Path:
        return Path(self.seeds_dir) if self.seeds_dir else DEFAULT_CACHE_DIR / "seeds"

    def resolved_cookie_json(self) -> Path:
        return (Path(self.cookie_json) if self.cookie_json
                else DEFAULT_CACHE_DIR / "cookies_1688.json")


@dataclass
class WorkerContext:
    """单个 worker 的运行上下文（Atom/Detector/Strategy 的 ctx 参数）。

    字段全部为可空装配：单测里可以只填需要的部分（如只给 session
    一个 mock page 跑 Detector）。
    """

    config: RunConfig = field(default_factory=RunConfig)
    session: Session | None = None
    browser_manager: "BrowserManager | None" = None
    store: "IdentityStore | None" = None
    site: "SitePlugin | None" = None
    stop: threading.Event = field(default_factory=threading.Event)
    log: Callable[[str], None] = print
    # 状态行更新（控制层装配；无状态板时为 noop）。任务层经它更新状态板字段
    set_status: Callable[..., None] = lambda **kw: None
    wid: int = 0
    tag: str = ""

    # 最近一次抓取抛出的异常（Detector 分级 NET_ERROR/NET_STALL/
    # BROWSER_DEAD 的输入；由抓取原子/控制层写入）
    last_error: BaseException | None = None
    # 最近一次抓取的业务结果（抓取原子写回，persist 用）
    last_result: Any = None
    # 控制层/策略层暂存（如 AttemptTracker）
    state: dict = field(default_factory=dict)
    # 冷却截止时间登记处：site 注册名 → 到期时刻（time.time()+seconds）。
    # 唯一写入者是 loop 的 chokepoint（有 active_site 时才登记）；
    # 查询者是 queue_router 的 eligible_queues 与 QueueRouter 的冷却过滤。
    cooldown_until: dict[str, float] = field(default_factory=dict)
    # 消费者持有的资源集（供 eligible_queues 过滤用）；daemon 消费者
    # 天然持有 {"channel", "browser"}（与 SPEC §4.2 BrowserConsumer 一致）
    resources: set[str] = field(default_factory=lambda: {"channel", "browser"})
    # daemon 可观测：消费者状态写入口（ConsumerStatusStore，P4）。
    # 由 QueueRouter.acquire_item 装配注入（router 持有同一 store）；
    # loop._cooldown 冷却登记时经它 upsert cooldowns_json。None=关闭上报。
    status_store: object | None = None
    # 消费者类型标识（browser / local），写 consumer_status.kind 用。
    # daemon 装配时按消费者类型设定；默认 browser（现状消费者）。
    consumer_kind: str = "browser"

    # ---- 便捷访问 ----
    @property
    def page(self):
        return self.session.page if self.session else None

    @property
    def identity(self) -> str:
        return self.session.identity if self.session else "direct"

    @property
    def headed(self) -> bool:
        return not self.config.headless

    def stopped(self) -> bool:
        return self.stop.is_set()

    def wait(self, seconds: float) -> bool:
        """可中断等待；返回 True 表示被停止信号中断。"""
        return self.stop.wait(seconds)
