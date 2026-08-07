# -*- coding: utf-8 -*-
"""Engine：多 worker 编排（迁移 run_workers）。

职责：通道分配（一 worker 一通道）→ 种子身份池独占认领 → 状态板 →
信号处理 → 错开启动 → 汇总。每个 worker 线程持有独立的 ShopDB 连接、
BrowserManager、WorkerContext 与 CrawlLoop；Task 对象跨 worker 共享
（其内部池如 CategoryPool 自带互斥，与旧引擎一致）。
"""

from __future__ import annotations

import random
import re
import signal
import threading
import time

from fetcher.control.board import StatusBoard
from fetcher.control.loop import CrawlLoop
from fetcher.core.context import RunConfig, WorkerContext
from fetcher.db import ShopDB
from fetcher.net.browser import BrowserManager
from fetcher.net.identity import IdentityStore
from fetcher.net.seeds import load_seed_kits
from fetcher.strategy.policy import Policy


class Engine:
    """多 worker 采集引擎。

    用法：
        engine = Engine(config, task, site=site, provider=QingGuoProvider())
        rc = engine.run()
    """

    def __init__(self, config: RunConfig, task, site=None, provider=None,
                 policy: Policy | None = None, board=None,
                 store_factory=None, browser_manager_factory=None,
                 loop_factory=None,
                 site_name: str | None = None):
        if site is not None and site_name is None:
            raise RuntimeError(
                "site_name 必传（CLI/daemon 传入注册名），"
                "不可在指定 site 时遗漏")
        self.config = config
        self.task = task
        self.site = site
        self.provider = provider
        self.policy = policy
        self.board = board
        self.site_name = site_name
        # 可注入工厂（测试用；默认每 worker 独立 ShopDB / BrowserManager /
        # CrawlLoop）
        self.store_factory = store_factory or (
            lambda wid: IdentityStore(ShopDB(config.resolved_db_path()),
                                      domain=getattr(site, "cookie_domain",
                                                     "1688.com")))
        self.browser_manager_factory = browser_manager_factory
        self.loop_factory = loop_factory or CrawlLoop
        self.state = {"stats": {}}
        self.lock = threading.Lock()
        self.stop = threading.Event()

    # ---- worker 装配 ----

    def _alloc_workers(self) -> tuple[int, list]:
        """并发度与通道分配（一 worker 一通道，IP + Cookie 配套）。"""
        cfg = self.config
        if cfg.use_proxy:
            if self.provider is None:
                raise RuntimeError("use_proxy=True 但未配置 ProxyProvider")
            n_channels = len(self.provider.servers())
            workers = cfg.workers or n_channels
            if workers > n_channels:
                print(f"[!] workers({workers}) > 通道数({n_channels})，"
                      f"部分 worker 将共用通道（共享出口 IP），不建议")
            channels = [self.provider.acquire() for _ in range(workers)]
        else:
            workers = cfg.workers or 1
            channels = [None] * workers
            if workers > 1:
                print(f"[!] 直连模式多 worker 共用本机 IP 和同一份 Cookie，"
                      f"可能触发风控；建议 --proxy 走多通道")
        return workers, channels

    def _alloc_seed_kits(self, workers: int) -> list:
        """种子身份池：每 worker 独占认领一份（一对一，防 Cookie 重放）。

        --seed-x5sec：A/B 实验，偶数 worker 用含 x5sec 的种子（A 组），
        奇数 worker 用不含的（B 组对照）。
        """
        cfg = self.config
        if not cfg.use_proxy:
            return [None] * workers
        seeds_dir = cfg.resolved_seeds_dir()
        domain = getattr(self.site, "cookie_domain", "1688.com")
        kits = load_seed_kits(seeds_dir, domain=domain)
        kits_x5 = (load_seed_kits(seeds_dir, keep_x5sec=True, domain=domain)
                   if cfg.seed_x5sec else [])
        if kits:
            print(f"[seed] 种子身份池 {len(kits)} 份: "
                  f"{', '.join(k['name'] for k in kits)}")
            if workers > len(kits):
                print(f"[!] worker 数({workers}) > 种子数({len(kits)})，"
                      f"超出部分按白板会话启动（建议种子数 ≥ worker 数）")
            if cfg.seed_x5sec:
                n_x5 = sum(1 for k in kits_x5 if k["x5sec"])
                print(f"[seed] --seed-x5sec 实验: 偶数 worker 为 A 组"
                      f"（含 x5sec，{n_x5}/{len(kits_x5)} 份有有效 x5sec），"
                      f"奇数 worker 为 B 组对照（不含）")
        else:
            print(f"[seed] {seeds_dir} 下没有可用种子身份，"
                  f"全部 worker 按白板会话启动")
        if cfg.seed_x5sec and kits_x5:
            return [(kits_x5[i] if i % 2 == 0 else kits[i])
                    if i < len(kits) else None for i in range(workers)]
        return [kits[i] if i < len(kits) else None for i in range(workers)]

    def _make_browser_manager(self, store, channel=None) -> BrowserManager:
        if self.browser_manager_factory is not None:
            return self.browser_manager_factory(store)
        auto_solve = None
        if self.config.auto_solve_slider:
            from fetcher.atoms.slider import make_auto_solve  # 延迟导入
            auto_solve = make_auto_solve(max_attempts=5)
        return BrowserManager(self.config, store,
                              site_name=(self.site_name
                                         if self.site_name else "unknown"),
                              provider=self.provider,
                              auto_solve=auto_solve,
                              homepage=getattr(self.site, "homepage", None),
                              channel=channel)

    def _worker(self, wid: int, channel, seed_kit, board):
        """worker 线程入口：独立 DB 连接 / BrowserManager / ctx / loop。

        channel 是本 worker 独占的隧道（一 worker 一通道）：透传给
        BrowserManager，保证 launch/relaunch 都走同一隧道，不重新从
        通道池轮询跳隧道。
        """
        tag = f"[w{wid}]"
        store = self.store_factory(wid)
        mgr = self._make_browser_manager(store, channel)

        def log(msg: str):
            text = (msg or "").strip()
            if not text:
                return
            if board is not None:
                # 错误/警告进滚动日志，常规细节进状态行
                if "[X]" in text or "[!]" in text or "[license]" in text:
                    board.log(text)
                else:
                    board.set(wid, detail=text[:80])
            else:
                print(text, flush=True)

        ctx = WorkerContext(config=self.config, store=store,
                            browser_manager=mgr, site=self.site,
                            stop=self.stop, log=log, wid=wid, tag=tag)
        if board is not None:
            ctx.set_status = lambda **kw: board.set(wid, **kw)
        loop = self.loop_factory(ctx, self.task, policy=self.policy,
                                 board=board, seed_kit=seed_kit)
        stats = loop.run()
        with self.lock:
            self.state["stats"][wid] = stats

    # ---- main 编排 ----

    def run(self) -> int:
        cfg = self.config
        workers, channels = self._alloc_workers()
        worker_kits = self._alloc_seed_kits(workers)
        print(f"[2] 启动 {workers} 个 worker"
              f"（{'代理通道: ' + ', '.join(c.server for c in channels)
                  if cfg.use_proxy else '直连'}）")

        board = self.board
        if board is None and workers > 0:
            board = StatusBoard(workers, compose=self.task.compose)
        if board is not None:
            board.start()

        # 直接关终端窗口(SIGHUP)或被 kill(SIGTERM)时也走正常清理流程：
        # 各 worker 关闭浏览器，服务端会话租约立即释放
        def _graceful_exit(signum, frame):
            (board.log if board else print)(
                f"[!] 收到信号 {signum}，通知各 worker 清理后退出...")
            self.stop.set()

        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, _graceful_exit)
            except (OSError, ValueError):
                pass  # 平台不支持该信号时跳过

        threads = [
            threading.Thread(target=self._worker,
                             args=(i, channels[i], worker_kits[i], board),
                             name=f"worker-{i}", daemon=True)
            for i in range(workers)
        ]
        for i, t in enumerate(threads):
            t.start()
            if i < len(threads) - 1:
                # 启动时间打散：多会话同一分钟内出生、同节奏访问是集群特征
                d = random.uniform(cfg.stagger_min, cfg.stagger_max)
                print(f"    错开启动：{d:.0f}s 后启动下一个 worker ...")
                time.sleep(d)

        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            (board.log if board else print)(
                "[!] 用户中断，等待各 worker 完成当前任务后退出...")
            self.stop.set()
            for t in threads:
                t.join(timeout=90)
            (board.log if board else print)("[!] 进度已保存，下次运行自动续爬")

        print(f"[OK] {self.task.summary(self.state['stats'])}")
        return 0
