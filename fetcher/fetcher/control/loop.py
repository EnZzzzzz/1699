# -*- coding: utf-8 -*-
"""CrawlLoop：单 worker 核心循环「采集 → 判场景 → 执行策略」。

对应旧 _engine_worker 的完整生命周期（启动浏览器 → 批次循环 →
item 级重试循环 → 收尾清理），但风控状态机不再写死在控制流里：
场景判断走 SceneInspector，处置走 Policy 策略表，循环体只负责
编排、簿记（tmd 统计 / IP 事件 / 种子烧毁 / 熔断）与节奏
（批次休息 / 样本间隔 / 长休息 / 请求预算）。

保留的簿记（对应旧引擎逐条语义）：
    - ip_req 按 identity 计页面请求数与「距上次触发」计数，
      存于 ctx.state["ip_req"]（Session 换 IP 后自然分开累计）；
    - 风控触发时 record_ip_event + ip_stat_block + since 清零；
    - 登录墙 = 身份最高级标记：判定当下立即烧毁该 identity 的
      Cookie（避免轮换回来复活已烧毁会话），与旧引擎同点位；
    - SeedBurnTracker：首请求秒拦/登录墙记到种子头上，烧毁后
      session.seed_kit=None，后续重启按白板会话；
    - 网络层错误（NET_ERROR/BROWSER_DEAD/IP_ROTATED）不计入熔断；
    - 熔断按店计（每店首个风控类失败计 1），同一店的重试链不累计，
      防单个慢/卡店铺中止整个任务。
"""

from __future__ import annotations

import random
import time
import traceback

from fetcher.atoms.browser_ops import RelaunchBrowser
from fetcher.control.board import wait_countdown
from fetcher.control.circuit import CircuitBreaker
from fetcher.control.task import Task
from fetcher.core.errors import UserInterrupted
from fetcher.core.session import Session, is_direct
from fetcher.core.types import Outcome, Scenario
from fetcher.detect.base import SceneInspector
from fetcher.net.seeds import SeedBurnTracker
from fetcher.strategy.base import PolicyAction
from fetcher.strategy.policy import AttemptTracker, Policy

# fetch 自报 outcome 到 Scenario 的兜底映射（探测器判 OK 但 fetch
# 显式报告异常时，信 fetch —— 对应旧 scrape 返回 _blocked/_fatal/
# _net_error 标记的契约）
_OUTCOME_FALLBACK = {
    Outcome.BLOCKED: Scenario.RISK_SLIDER_PAGE,
    Outcome.NET_ERROR: Scenario.NET_ERROR,
    Outcome.FATAL: Scenario.BROWSER_DEAD,
    Outcome.EMPTY: Scenario.EMPTY,
}

# 风控事件名（record_ip_event）
_EVENT_NAMES = {
    Scenario.RISK_LOGIN: "block_login",
    Scenario.RISK_SLIDER_PAGE: "block_slider",
    Scenario.RISK_SLIDER_EMBED: "block_slider",
}

# 不计请求数（没到目标站）的场景
_NO_REQUEST_SCENARIOS = frozenset({Scenario.BROWSER_DEAD, Scenario.NET_ERROR})

# giveup kind="net" 的场景（其余为 "block"）
_NET_KIND_SCENARIOS = frozenset({Scenario.NET_ERROR, Scenario.BROWSER_DEAD})


class CrawlLoop:
    """单 worker 采集循环。

    用法：
        ctx = WorkerContext(config=cfg, store=store, browser_manager=mgr,
                            site=site, stop=stop, log=log)
        loop = CrawlLoop(ctx, task, policy=policy, board=board, seed_kit=kit)
        stats = loop.run()
    """

    def __init__(self, ctx, task: Task, policy: Policy | None = None,
                 inspector: SceneInspector | None = None, board=None,
                 seed_kit: dict | None = None,
                 sites: dict[str, object] | None = None,
                 per_site_kits: dict[str, dict | None] | None = None,
                 policies: dict[str, Policy] | None = None):
        self.ctx = ctx
        self.task = task
        self.policy = policy or Policy(
            max_consecutive_fail=ctx.config.max_consecutive_fail)
        self.sites = sites
        self.per_site_kits = per_site_kits
        self.policies = policies
        if sites is not None:
            # daemon 多站点路径：inspector 延迟建，首个 item 绑定后建立
            self._bound_site = None
            self.inspector = inspector  # daemon 传 None
        else:
            # CLI 单站点路径：inspector 按 ctx.site 立即装配
            self._bound_site = getattr(ctx.site, 'name', None) if ctx.site else None
            self.inspector = inspector or SceneInspector.for_site(ctx.site)
        self.board = board
        self.seed_tracker = SeedBurnTracker(seed_kit)
        self.circuit = CircuitBreaker(ctx.config.max_consecutive_fail)
        self.tracker = AttemptTracker()
        self.stats = task.make_stats()
        # 任务层暂存（对应旧 wctx，含 stats）
        self.ctx.state.setdefault("task", {})["stats"] = self.stats
        self.wctx = self.ctx.state["task"]
        # tmd：按出口 IP 计页面请求数与「距上次触发」计数
        self.ip_req: dict = self.ctx.state.setdefault("ip_req", {})
        self.budget_stuck: set = set()
        self.batch_no = 1
        self.done_in_batch = 0
        self.total_done = 0

    # ---- 日志 / 状态行 ----

    @property
    def tag(self) -> str:
        return f"[w{self.ctx.wid}]"

    def log(self, msg: str):
        self.ctx.log(f"{self.tag} {msg}")

    # ---- 冷却 chokepoint（SPEC §3.3：唯一等待执行点）----

    def _cooldown(self, seconds: float, reason: str,
                  prefix: str | None = None, yield_: bool = False) -> bool:
        """登记冷却截止时间 + 执行可中断等待。返回 True=被 stop 中断。

        P3 让出型 / 原地型分流：
        - yield_=True（让出型）：登记 site 键后立即返回 False 不等待——
          等待由下一轮 acquire_item 的 condvar timeout 执行（冷却期间
          该站点队列对本消费者不可见 → 多队列时自然转取其他队列）。
        - yield_=False（原地型，默认）：登记后原地等待（秒级/装配中途
          等待用，如 launch_backoff；策略冷却待 P3-3 router 接 release
          后改让出）。

        cooldown_until 按 site 注册名登记（有 active_site 时才写入）；
        reason 参数保留，仅用于日志/展示。无 active_site 时不登记（如
        launch_backoff 在 acquire 前，active_site 未设置时天然跳过）。

        展示两路径仅原地型使用：prefix 非空走 wait_countdown（秒级倒计
        时状态行，长等待用）；prefix=None 走 ctx.wait（静默，短等待用）。
        让出型不展示倒计时状态行（P3-3 后由 board 的「等货/等冷却」取代）。
        """
        active_site = self.ctx.state.get("active_site")
        if active_site is not None:
            self.ctx.cooldown_until[active_site] = time.time() + seconds
        # P4 daemon 可观测：冷却登记即时上报（cooldowns_json）。
        # 仅让出型登记后上报（原地型等待结束再上报等价，避免重复写）；
        # status_store 由 QueueRouter 装配注入，CLI 路径为 None 无操作。
        if yield_ and self.ctx.status_store is not None:
            try:
                self.ctx.status_store.upsert(
                    f"w{self.ctx.wid}", self.ctx.consumer_kind,
                    cooldowns=self.ctx.cooldown_until)
            except Exception as e:  # noqa: BLE001
                self.ctx.log(f"[!] 冷却状态上报失败: {e}")
        if yield_:
            return False
        if prefix is None:
            return self.ctx.wait(seconds)
        return wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
                              seconds, prefix,
                              set_status=self.ctx.set_status)

    # ---- 主流程 ----

    def run(self) -> dict:
        """worker 完整生命周期；返回本 worker 的统计字典。"""
        cfg = self.ctx.config
        self.ctx.state["warm"] = True  # 新会话冷启动软着陆标记
        try:
            self.ctx.set_status(state="启动浏览器…", force=True)
            self._launch_with_retry()
            self.log(f"浏览器就绪，出口 IP={self.ctx.identity}"
                     f"（{'通道 ' + self.ctx.session.channel.server
                         if self.ctx.session.channel else '直连'}）")
            self.ctx.set_status(ip=self.ctx.identity, batch=1,
                                state="就绪", force=True)

            while not self.ctx.stopped():
                # ---- 批次配额：采满 batch_num 强制大休息（±10% 抖动），
                #      max_batches 到顶收工 ----
                if self.done_in_batch >= cfg.batch_num:
                    if cfg.max_batches and self.batch_no >= cfg.max_batches:
                        self.log(f"第 {self.batch_no} 批采满，"
                                 f"已达批次上限（--max-batches），收工")
                        self.ctx.set_status(state="收工")
                        return self.stats
                    rest = random.uniform(cfg.batch_rest * 0.9,
                                          cfg.batch_rest * 1.1)
                    self.log(f"⏸ 第 {self.batch_no} 批已采满 "
                             f"{cfg.batch_num} 个{self.task.batch_unit}，"
                             f"强制休息 {rest / 60:.1f} 分钟（防风控）...")
                    if self._cooldown(rest, "batch_rest", prefix="批次休息",
                                      yield_=True):
                        # yield_=True 恒返回 False，此分支不可达；
                        # stop 由 acquire_item 的 condvar 处理
                        return self.stats
                    self.batch_no += 1
                    self.done_in_batch = 0
                    self.log(f"▶ 休息结束，开始第 {self.batch_no} 批")
                    self.ctx.set_status(batch=self.batch_no, state="采集中")

                # ---- 冷启动（acquire 前的任务，如先逛首页填类目池）----
                if self.task.cold_start_before_acquire and self._take_warm():
                    self.ctx.set_status(state="冷启动软着陆…")
                    self.task.cold_start(self.ctx, None)

                # ---- 认领任务项 ----
                item = self.task.acquire_item(self.ctx)
                if item is None:
                    self.log(self.task.empty_message())
                    self.ctx.set_status(state="无待做任务，退出")
                    break
                self._bind_item_site()
                self.ctx.state["item"] = item
                self.ctx.set_status(shop=self.task.label(item),
                                    state="检查出口 IP…")

                # ---- 出口 IP 保鲜检查（青果 30 分钟轮换）；relaunch 失败
                #      不退出 worker，记日志继续用当前会话，由 fetch 兜底 ----
                if cfg.use_proxy:
                    self._ensure_fresh_ip()

                # ---- 冷启动（acquire 后的任务，如先逛店铺首页）----
                if self._take_warm():
                    self.ctx.set_status(state="冷启动软着陆…")
                    self.task.cold_start(self.ctx, item)

                # ---- item 级重试循环（策略表驱动）----
                kind, count = self._process_item(item)
                if kind in ("abort", "stop"):
                    return self.stats
                if kind == "release":
                    # 策略冷却让出：释放 item 回 pending（attempts 熔断），
                    # 冷却到期重领时策略链从头开始（SPEC §3.4）
                    self.task.release_item(self.ctx)
                    self.task.after_item(self.ctx, item)
                    # stop 由下一轮 acquire 的 condvar 检查处理
                    continue
                self.done_in_batch += count
                self.total_done += count
                if kind == "success":
                    # 每次成功后回写最新 Cookie（含轮换的 x5sec）——
                    # 进程意外退出也不丢信任链
                    try:
                        self.ctx.browser_manager.save_cookies(self.ctx.session)
                    except Exception:  # noqa: BLE001
                        pass

                # 当前任务项处理完毕（含放弃），任务层收尾
                self.task.after_item(self.ctx, item)

                # ---- 每 IP 请求预算：采满预算主动换 IP 规避配额墙 ----
                if kind == "success" and not self._check_budget():
                    return self.stats

                if cfg.limit and self.total_done >= cfg.limit:
                    self.log(f"已达本次采集上限（--limit {cfg.limit}），收工")
                    self.ctx.set_status(state="收工")
                    return self.stats

                # ---- 样本间隔（按 worker 编号递增错峰，避免集群同频）----
                lo = cfg.sample_min + self.ctx.wid * 1.5
                hi = cfg.sample_max + self.ctx.wid * 2.5
                t = random.uniform(lo, hi)
                self.ctx.set_status(state=f"{self.task.unit}间隔 {t:.1f}s")
                if self._cooldown(t, "sample_interval", yield_=True):
                    # yield_=True 恒返回 False，此分支不可达；
                    # stop 由 acquire_item 的 condvar 处理
                    return self.stats

                # ---- 周期性随机长休息（模拟真人连续浏览后的停顿）----
                n_rest = self.task.rest_counter(self.stats)
                if (cfg.rest_every > 0 and n_rest > 0
                        and n_rest % cfg.rest_every == 0
                        and not self.ctx.stopped()):
                    t = random.uniform(cfg.rest_min, cfg.rest_max)
                    self.log(f"☕ 已连续抓取 {n_rest} 个{self.task.unit}，"
                             f"随机长休息 {t / 60:.1f} 分钟 ...")
                    if self._cooldown(t, "periodic_rest", prefix="长休息",
                                      yield_=True):
                        # yield_=True 恒返回 False，此分支不可达；
                        # stop 由 acquire_item 的 condvar 处理
                        return self.stats
        except UserInterrupted:
            pass
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            self.log(f"[X] worker 异常退出: {e}\n{tb[-5000:]}")
        finally:
            self._cleanup()
        return self.stats

    # ---- 启动 / 收尾 ----

    def _take_warm(self) -> bool:
        """取走冷启动标记（RelaunchBrowser 原子在换 IP 后重新置位）。"""
        return bool(self.ctx.state.pop("warm", False))

    def _launch_with_retry(self):
        cfg = self.ctx.config
        last_err = None
        for attempt in range(1, cfg.ip_retry + 1):
            if self.ctx.stopped():
                raise UserInterrupted("用户中断")
            try:
                self.ctx.session = self.ctx.browser_manager.launch(
                    seed_kit=self.seed_tracker.kit, stop=self.ctx.stop)
                self.seed_tracker.kit = self.ctx.session.seed_kit
                return
            except UserInterrupted:
                raise
            except (Exception, SystemExit) as e:  # noqa: BLE001
                last_err = e
                backoff = min(30 * attempt, 120)
                self.log(f"  [!] 启动浏览器第 {attempt}/{cfg.ip_retry} "
                         f"次失败: {e}，{backoff}s 后重试...")
                # 装配中途、秒级退避，换队列无意义——原地等待（默认）
                if self._cooldown(backoff, "launch_backoff", prefix="启动退避"):
                    raise UserInterrupted("用户中断") from e
        raise RuntimeError(f"启动浏览器重试 {cfg.ip_retry} 次仍失败: {last_err}")

    def _cleanup(self):
        """退出前回写 Cookie、关浏览器（任何路径都走这里）。"""
        session = self.ctx.session
        if session is not None:
            session.close(store=self.ctx.store, log=self.ctx.log)
            self.ctx.session.browser = None
        self.ctx.set_status(state="已退出", force=True)
        if self.ctx.store is not None:
            try:
                self.ctx.store.db.close()
            except Exception:  # noqa: BLE001
                pass

    # ---- 出口 IP 保鲜 / 请求预算 ----

    def _relaunch(self) -> bool:
        """重启浏览器（经 RelaunchBrowser 原子）；成功返回 True。"""
        result = RelaunchBrowser().run(self.ctx, {})
        if result.outcome is Outcome.OK:
            self.ctx.set_status(ip=self.ctx.identity, state="浏览器已重启",
                                force=True)
            return True
        if result.outcome is Outcome.SKIPPED:
            return False
        self.log(f"[X] 重启浏览器失败: {result.detail}")
        return False

    def _ensure_fresh_ip(self) -> bool:
        """青果出口 30 分钟轮换：不一致即重启浏览器重绑 Cookie。

        relaunch 失败不中止 worker：记日志继续用当前会话（可能仍可用），
        避免一个瞬时扰动（IP 查询抖动、隧道临时抽风）静默打死整个 worker。
        会话若真死了，下次 fetch 走 BROWSER_DEAD/NET_ERROR 链处置。
        """
        need, _cur, reason = self.ctx.browser_manager.check_ip_fresh(
            self.ctx.session)
        if not need:
            return True
        self.log(f"🔄 {reason}，重启浏览器绑定新 IP ...")
        if not self._relaunch():
            self.log("[X] 出口 IP 保鲜 relaunch 失败，本次跳过，继续使用当前会话")
        return True

    def _check_budget(self) -> bool:
        """每 IP 请求预算：采满主动换 IP；IP 未轮换则放行（budget_stuck）。"""
        cfg = self.ctx.config
        budget = self.task.budget_for(self.ctx)
        identity = self.ctx.identity
        if not (budget and cfg.use_proxy
                and self.ip_req.get(identity, {}).get("n", 0) >= budget
                and identity not in self.budget_stuck):
            return True
        old_identity = identity
        self.log(f"📦 出口 {identity} 已达请求预算 "
                 f"（{self.ip_req[identity]['n']}/{budget} 次），"
                 f"主动换 IP 规避配额墙")
        if not self._relaunch():
            self.log("[X] 预算换 IP 失败，中止整个任务")
            self.ctx.stop.set()
            return False
        if self.ctx.identity == old_identity:
            self.budget_stuck.add(identity)
            self.log("  [!] 出口 IP 尚未轮换，本次预算放行（等青果自然轮换）")
        return True

    # ---- item 级重试循环（核心：采集 → 判场景 → 执行策略） ----

    def _process_item(self, item) -> tuple[str, int]:
        """返回 (kind, count)：kind ∈ success/giveup/abort/stop。"""
        ctx = self.ctx
        # 熔断按店计非按次：同一店铺的重试链无论多长只计一次，单个慢/卡
        # 店铺不会烧穿熔断中止整个任务（旧引擎同店铺最多 3 段升级后放弃）
        self._bind_item_site()
        counted = False
        while not ctx.stopped():
            ctx.set_status(state="采集中")
            ctx.last_error = None
            result = self.task.fetch(ctx, item)
            scenario = self.inspector.inspect(ctx)
            if scenario is Scenario.OK:
                if result is None:
                    # fetch 未返回结果（对应旧 scrape 返回 None，按风控处理）
                    scenario = Scenario.RISK_SLIDER_PAGE
                else:
                    # 探测器判 OK 但 fetch 自报异常时信 fetch（旧 _blocked/
                    # _fatal/_net_error 标记契约）
                    scenario = _OUTCOME_FALLBACK.get(result.outcome,
                                                     Scenario.OK)
                    if scenario is Scenario.OK \
                            and not self.task.validate(ctx, item, result):
                        # 结构化校验失败（软拦截/跳转错页）：按 EMPTY 处置，
                        # EmptyPageDetector 的文本阈值只是兜底
                        scenario = Scenario.EMPTY
            self._bookkeep_request(scenario)

            # ---- 成功 ----
            if scenario is Scenario.OK:
                self.circuit.note_success()
                self.tracker.note_success()
                count = self.task.on_success(ctx, item, result)
                return "success", count

            # ---- 失败：簿记（IP 事件 / 种子烧毁 / 登录墙烧毁）----
            reason = self._bookkeep_block(scenario, result)

            # ---- 熔断（按店计）：本店首个风控类失败才计数，重试同一店
            #      不再累计；连续 N 个店铺都失败（熔断上限）判定被风控 ----
            if not counted and self.circuit.counts(scenario):
                counted = True
                if self.circuit.note_failure(scenario):
                    self.log(f"[X] 已连续失败 {self.circuit.count} 次"
                             f"（最近一次: {reason}），判定被风控，中止整个任务")
                    extra = self.task.on_abort(ctx, item)
                    if extra:
                        self.log(f"    {extra}")
                    ctx.stop.set()
                    return "abort", 0

            # ---- 策略表决策 ----
            decision = self.policy.decide(scenario, self.tracker)
            if decision.action is PolicyAction.ABORT:
                self.log(f"[X] 策略链中止: {decision.detail}")
                extra = self.task.on_abort(ctx, item)
                if extra:
                    self.log(f"    {extra}")
                ctx.stop.set()
                return "abort", 0
            if decision.action is PolicyAction.GIVE_UP:
                kind = ("net" if scenario in _NET_KIND_SCENARIOS else "block")
                phrase = self.task.on_giveup(ctx, item, reason, kind)
                self.tracker.note_failure()
                self.log(f"  [X] {decision.detail}，{phrase}（{reason}）")
                return "giveup", self.task.giveup_cost(item)

            # ---- 执行策略后重试同一任务项 ----
            strategy = self.policy.strategies[decision.strategy]
            ctx.state["attempt"] = decision.attempt
            ctx.set_status(state=f"处置: {decision.strategy}"
                                 f"（{decision.attempt} 次）")
            self.log(f"⚠ {reason} → 策略 {decision.strategy}"
                     f"（第 {decision.attempt} 次）")
            step = strategy.run(ctx)
            if step.solved:
                self.log(f"✓ 策略 {decision.strategy} 完成: {step.detail}")
            # 策略冷却统一让出 + release（P3 SPEC §3.4）：冷却期间该
            # 站点队列不可见，item 释放回 pending（attempts 熔断），
            # 冷却到期重领（策略链从头开始）。
            # 守护：solved=True 时不 release（防御未来策略同时返回
            # solved+cooldown 的场景，此时 cooldown 仅作冷却建议不计）。
            if step.cooldown and not step.solved:
                if self._cooldown(step.cooldown,
                                  f"strategy:{decision.strategy}",
                                  yield_=True):
                    return "stop", 0
                return "release", 0
        return "stop", 0

    def _bind_item_site(self):
        """daemon 多站点路径：按 ctx.state["active_site"] 切换
        ctx.site / inspector / policy，并懒建跨站 view（SPEC §3.6）。
        CLI 路径（sites=None）无操作。"""
        if self.sites is None:
            return
        site_name = self.ctx.state.get("active_site")
        if site_name is None or site_name == self._bound_site:
            return
        plugin = self.sites.get(site_name)
        if plugin is not None:
            self.ctx.site = plugin
            # 跨站 view 懒建（SPEC §3.6）：无 view 则建，路由活动站点
            if (self.ctx.session is not None
                    and self.ctx.browser_manager is not None):
                try:
                    # P3 SPEC §3.6：跨站 ensure_site 播种用该
                    # (worker, site) 的 seed_kit；无 kit 时保持现状白板语义
                    site_seed_kit = (
                        self.per_site_kits.get(site_name)
                        if self.per_site_kits else None)
                    self.ctx.browser_manager.ensure_site(
                        self.ctx.session, site_name, plugin.cookie_domain,
                        seed_kit=site_seed_kit)
                    self.ctx.session.set_active_site(site_name)
                except Exception as e:
                    self.log(f"[!] ensure_site({site_name}) 失败: {e}，"
                             f"继续处理 item（fetch 兜底）")
            self.inspector = SceneInspector.for_site(plugin)
            new_policy = self.policies.get(site_name) if self.policies else None
            if new_policy is not None:
                self.policy = new_policy
        # C1 修复：无论 plugin 是否在 sites dict 中，
        # 都记录本次绑定，防止每次 item 都重复查找
        self._bound_site = site_name

    # ---- 簿记 ----

    def _bookkeep_request(self, scenario: Scenario):
        """tmd 计数：请求到了目标站才计（网络层错误不算）。"""
        if scenario in _NO_REQUEST_SCENARIOS or self.ctx.store is None:
            return
        identity = self.ctx.identity
        ctr = self.ip_req.setdefault(identity, {"n": 0, "since": 0})
        ctr["n"] += 1
        ctr["since"] += 1
        self.ctx.store.stat_request(identity, ok=scenario is Scenario.OK)
        self.ctx.set_status(ip_n=ctr["n"])

    def _bookkeep_block(self, scenario: Scenario, result) -> str:
        """风控簿记：IP 事件 + 触发统计 + since 清零 + 种子烧毁 +
        登录墙身份烧毁。返回原因串（日志用）。"""
        ctx = self.ctx
        reason = (result.detail if result is not None and result.detail
                  else f"场景 {scenario.value}（疑似风控拦截）")
        if scenario in _NO_REQUEST_SCENARIOS or scenario is Scenario.NET_ERROR:
            return reason
        identity = ctx.identity
        ctr = self.ip_req.setdefault(identity, {"n": 0, "since": 0})
        since = ctr["since"]
        login_wall = scenario is Scenario.RISK_LOGIN
        if ctx.store is not None:
            ctx.store.record_event(identity,
                                   _EVENT_NAMES.get(scenario, "block_other"),
                                   reason, req_since_block=since)
            ctx.store.stat_block(identity)
        ctr["since"] = 0
        self.log(f"  [tmd] 出口 {identity} 在 {since} 次请求后"
                 f"触发反爬（本 IP 累计 {ctr['n']} 次请求）")

        # 登录墙 = 会话身份最高级标记：判定当下立即烧毁该 IP 名下的
        # Cookie（避免轮换回来复活已烧毁会话）——与旧引擎同点位
        if login_wall and not is_direct(identity) and ctx.store is not None:
            try:
                n = ctx.store.burn(identity)
                self.log(f"  🧹 登录墙标记：已清空 {identity} 名下的 {n} 条"
                         f" Cookie（此 IP 轮换回来时按全新身份重建）")
            except Exception as e:  # noqa: BLE001
                self.log(f"  [!] 清空登录墙 IP Cookie 失败: {e}")

        # 种子烧毁判定：首请求秒拦/登录墙记到种子头上
        if self.seed_tracker.note_block(identity, since, login_wall,
                                        log=self.log):
            if ctx.session is not None:
                ctx.session.seed_kit = None  # 后续重启按白板会话
        return reason
