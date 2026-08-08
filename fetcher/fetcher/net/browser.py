# -*- coding: utf-8 -*-
"""BrowserManager：CloakBrowser 启动 / 预热 / 重启（迁移自
scraper/taobao_1688/common.py 的浏览器段，行为全部保留）。

保留的现有行为：
    - Cookie 按出口 IP 隔离存取（identity = 出口 IP，直连记 'direct'）；
      直连模式库里没有时用 cookie_json 种子导入一次；代理模式新出口
      IP 不播种（空会话白板）或用独占种子身份；
    - warmup：新 IP 访问首页让站点现场签发独立 Cookie 并立即回写；
      有头模式首页弹滑块时等手动/自动过证；
    - CloakBrowser GeoIP 探测超时放宽到 20s（环境变量可覆盖）；
    - license 席位等待（残留租约释放后再放行）；
    - launch watchdog（240s 未返回打警告，纯观察不跨线程中止）；
    - 指纹参数按 identity（或种子名）固定，同 IP 重启指纹不变；
    - 青果出口 IP 30 分钟轮换检测（check_ip_fresh）。

重依赖全部延迟导入：import 本模块不需要 cloakbrowser / playwright /
requests。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import threading
import time
from pathlib import Path

from fetcher.core.context import RunConfig
from fetcher.core.errors import (
    BrowserLaunchError,
    ExitIPError,
    LicenseSeatTimeout,
    UserInterrupted,
)
from fetcher.core.session import Session, SiteView, bare_identity
from fetcher.net.identity import IdentityStore

# ---------- 配置加载 ----------

# 各套餐的并发会话席位上限（服务端强制，超限的 launch 会以退出码 76
# 拒绝；此处仅用于启动前主动等待，上限未知的套餐不阻塞直接放行）
PLAN_SEATS = {"free": 1, "solo": 5}


def load_license_key(config_json: Path | None = None) -> str | None:
    """环境变量优先（CLOAKBROWSER_LICENSE_KEY），config.json 兜底。"""
    key = os.environ.get("CLOAKBROWSER_LICENSE_KEY")
    if key:
        return key
    if config_json is None:
        config_json = Path(__file__).resolve().parents[3] / ".cache" / "config.json"
    if Path(config_json).exists():
        try:
            return json.loads(Path(config_json).read_text())["CLOAKBROWSER_LICENSE_KEY"]
        except Exception:  # noqa: BLE001
            return None
    return None


def wait_for_license_seat(log=print, timeout: float = 600.0,
                          interval: float = 20.0,
                          max_seats: int | None = None,
                          config_json: Path | None = None) -> bool:
    """启动浏览器前检查 CloakBrowser 会话席位是否还有空余。

    背景：会话席位由二进制向服务端租约。上次运行异常退出时租约不会
    立即释放，残留期间新启动的二进制会被服务端拒绝（退出码 76）或
    launch 后自行退出，表现为不透明的 TargetClosedError。这里启动前
    主动轮询，等残留租约过期释放后再放行。

    查询失败（无 key / 网络问题）不阻塞，直接放行。
    """
    key = load_license_key(config_json)
    if not key:
        return True
    from cloakbrowser.license import (get_active_session_count,  # 延迟导入
                                      validate_license)
    try:
        info = validate_license(key)
    except Exception:  # noqa: BLE001
        return True
    seats = max_seats or (PLAN_SEATS.get(info.plan) if info else None)
    if not seats:
        return True  # 套餐席位上限未知，不阻塞
    deadline = time.time() + timeout
    while True:
        n = get_active_session_count(key)
        if n is None or n < seats:
            return True
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        wait = min(interval, remaining)
        log(f"[license] 服务端 {n}/{seats} 个会话席位被占用"
            f"（多为上次异常退出的残留租约，等其过期释放），"
            f"{wait:.0f}s 后重查...")
        time.sleep(wait)


def fingerprint_args(identity: str) -> list[str]:
    """按 identity 生成稳定的 CloakBrowser 指纹参数（替代默认的随机种子）。

    同一出口 IP 重启指纹不变（与库中 Cookie 配套，cna 等按设备签发）；
    不同 IP 指纹不同（避免跨 IP 的设备关联）。种子空间与官方默认一致
    （10000-99999）。不硬编码 UA，由二进制原生指纹自报（UA 与 UA-CH
    错配是风控识别"UA 被篡改"的典型信号）。
    """
    seed = int(hashlib.md5(identity.encode()).hexdigest()[:8], 16) % 90000 + 10000
    plat = ("--fingerprint-platform=macos" if platform.system() == "Darwin"
            else "--fingerprint-platform=windows")
    return ["--no-sandbox", f"--fingerprint={seed}", plat,
            # 多窗口 headed 并发时，被遮挡/后台窗口会被 Chrome 节流，
            # 滑块拖动的鼠标事件与页面计时被打断（卡顿/跳段）
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding"]


def get_exit_ip(proxies: dict = None, timeout: int = 10) -> str | None:
    """查询当前出口 IP（代理模式下经代理查询），失败返回 None。"""
    import requests  # 延迟导入
    try:
        r = requests.get("https://ipinfo.io/json", proxies=proxies,
                         timeout=timeout)
        return r.json().get("ip")
    except Exception:  # noqa: BLE001
        return None


class BrowserManager:
    """CloakBrowser 生命周期管理（一 worker 一个实例）。

    用法：
        cfg = RunConfig(use_proxy=True)
        mgr = BrowserManager(cfg, store, site_name="1688",
                             provider=QingGuoProvider())
        session = mgr.launch(seed_kit=kit)
        ...
        need, cur, reason = mgr.check_ip_fresh(session)
        if need:
            session = mgr.relaunch(session)
    """

    def __init__(self, config: RunConfig, store: IdentityStore,
                 site_name: str,
                 provider=None, log=print, auto_solve=None,
                 homepage: str | None = None,
                 channel=None):
        """
        provider:  ProxyProvider 实例（use_proxy=True 时必传；
                   支持 str server 入参的兼容用法见 launch()）。
        auto_solve: 可选的自动过证回调 fn(page) -> bool（轨迹回放滑块，
                   见 atoms/slider.py）；None 时退化为纯人工过证流程。
        homepage:  新会话 warmup 预热的落地页；None 用 warmup 默认值
                   （1688 首页，兼容旧调用）。
        channel: 本 worker 独占的隧道（一 worker 一通道）；launch() 未
                   显式指定时用它，relaunch 沿用 session.channel。None 时
                   launch 从 provider 通道池轮询取（旧版兼容）。
        site_name: 站点注册名（如 "1688"），用于 identity 前缀分桶；
                   必传（CLI/daemon 传入）。
        """
        self.config = config
        self.store = store
        self.provider = provider
        self.log = log
        self.auto_solve = auto_solve
        self.homepage = homepage
        self.channel = channel
        self.site_name = site_name

    # ---- 出口 IP ----

    def _query_exit_ip_with_retry(self, req_proxies: dict,
                                  retries: int = 3) -> str | None:
        """查出口 IP，失败短重试（行为与旧 launch_browser 一致）。"""
        exit_ip = get_exit_ip(req_proxies)
        if exit_ip is None:
            for _ in range(retries):
                time.sleep(5)
                exit_ip = get_exit_ip(req_proxies)
                if exit_ip:
                    break
        return exit_ip

    def check_ip_fresh(self, session: Session) -> tuple[bool, str | None, str]:
        """检查当前出口 IP 是否仍有效，返回 (need_relaunch, cur_ip, reason)。

        青果出口 IP 每 30 分钟轮换一次：查询到的 IP 与 identity 不一致
        即视为已过期；查询失败先短重试 3 次确认隧道是否真的失效。
        查询仍失败时不强制 relaunch —— 重启同样依赖该查询，查询挂时重启
        大概率也失败；跳过本轮检查，交给 fetch 的 BROWSER_DEAD/NET_ERROR
        处置兜底，避免一个瞬时查询故障打死整个 worker。
        """
        cur_ip = self._query_exit_ip_with_retry(session.req_proxies)
        if cur_ip is None:
            return False, None, "出口 IP 查询失败（跳过本轮保鲜检查）"
        if cur_ip != bare_identity(session.identity):
            return True, cur_ip, f"出口 IP 已轮换（{session.identity} -> {cur_ip}）"
        return False, cur_ip, ""

    # ---- 启动 ----

    def launch(self, channel=None, seed_kit: dict = None,
               stop: threading.Event | None = None) -> Session:
        """启动 CloakBrowser 并注入 Cookie，返回 Session。

        channel: Channel 实例，或旧版兼容的 "host:port" 字符串
        （内部经 provider.acquire() 之外的指定通道）。
        """
        from cloakbrowser import launch as cloak_launch  # 延迟导入

        # GeoIP 探测默认总预算只有 5s，青果住宅隧道 RTT 高经常全部超时
        # （只是 warning，但会话会缺失 GeoIP 定位）；放宽到 20s
        os.environ.setdefault("CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS", "20")

        cfg = self.config
        proxy_conf = None
        req_proxies = None

        if cfg.use_proxy:
            # 本 worker 独占通道优先（一 worker 一通道，relaunch 也走
            # session.channel）；未指定时从通道池轮询取（旧版兼容）
            ch = self._resolve_channel(
                channel if channel is not None else self.channel)
            proxy_conf = ch.playwright_proxy()
            req_proxies = ch.requests_proxies()
            # 出口 IP 是 Cookie 隔离的 identity 基准，查不到就不能继续 ——
            # 用伪 identity 会让 Cookie 绑错对象，且真实 Cookie 无法沉淀
            exit_ip = self._query_exit_ip_with_retry(req_proxies)
            if exit_ip is None:
                raise ExitIPError(f"经通道 {ch.server} 查询出口 IP 失败，"
                                  f"隧道疑似不可用，无法绑定 Cookie identity")
            channel = ch
            self.log(f"    [proxy] 青果住宅代理: {ch.server}，出口 IP: {exit_ip}")

        # Cookie 装载已移入 ensure_site（per-view），此处不再重复。
        # 指纹身份：种子名优先，否则裸 IP（直连直接传 'direct'）。
        fp_id = (seed_kit["name"] if seed_kit
                 else (exit_ip if cfg.use_proxy else "direct"))

        # ---- 席位等待 ----
        self.log(f"    [launch] 检查 CloakBrowser 会话席位…")
        if not wait_for_license_seat(log=self.log,
                                     timeout=cfg.license_seat_timeout):
            raise LicenseSeatTimeout(
                f"等待 {cfg.license_seat_timeout:.0f}s 后 CloakBrowser "
                f"会话席位仍满员，请检查是否有残留会话未释放")

        # ---- launch（watchdog 纯观察，不跨线程触碰 playwright 对象）----
        self.log(f"    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…")
        launch_done = threading.Event()

        def _watchdog():
            if not launch_done.wait(240):
                self.log(f"    [X] launch() 已超过 240s 未返回，疑似库内部卡死"
                         f"（GeoIP 探测/二进制校验/代理配置解析）；"
                         f"无法安全跨线程中止，请人工观察处理")

        threading.Thread(target=_watchdog, daemon=True,
                         name="launch-watchdog").start()
        try:
            browser = cloak_launch(
                headless=cfg.headless,
                license_key=load_license_key(),
                humanize=True,
                locale="zh-CN",
                timezone="Asia/Shanghai",
                stealth_args=False,
                args=fingerprint_args(fp_id),
                **({"proxy": proxy_conf, "geoip": True} if proxy_conf else {}),
            )
        except SystemExit as e:
            raise BrowserLaunchError(
                f"CloakBrowser 二进制退出（code={e.code}，"
                f"多为会话席位被占或 License 校验失败）") from e
        finally:
            launch_done.set()

        self.log(f"    [launch] 浏览器进程已启动，创建初始 view…")
        session = Session(browser=browser,
                          channel=channel, req_proxies=req_proxies,
                          seed_kit=seed_kit)
        # 懒建初始 view（含 Cookie 装载 + 上下文创建 + warmup）
        site_domain = getattr(self.store, "domain", "")
        self.ensure_site(session, self.site_name, site_domain,
                         seed_kit=seed_kit, stop=stop)
        if cfg.use_proxy:
            self.store.record_event(
                session.identity, "launch", channel.server if channel else "")
        return session

    def _resolve_channel(self, channel):
        """把 launch(channel=...) 入参统一为 Channel 实例。"""
        from fetcher.net.proxy.base import Channel  # 延迟循环导入
        if channel is None:
            if self.provider is None:
                raise BrowserLaunchError("use_proxy=True 但未配置 ProxyProvider")
            return self.provider.acquire()
        if isinstance(channel, Channel):
            return channel
        # 旧版兼容：直接传 "host:port" 字符串（指定隧道入口）
        ch = self.provider.acquire() if self.provider else None
        return Channel(server=str(channel),
                       username=ch.username if ch else None,
                       password=ch.password if ch else None,
                       provider=ch.provider if ch else "")

    # ---- 重启（换 IP / 浏览器死亡修复） ----

    def relaunch(self, session: Session, channel=None,
                 seed_kit: dict | None = "__keep__",
                 stop: threading.Event | None = None,
                 max_retry: int | None = None,
                 backoff_base: float = 30.0,
                 backoff_cap: float = 120.0) -> Session:
        """关闭旧会话（先回写 Cookie），重开新实例以绑定新出口 IP。

        最多重试 max_retry（默认 config.ip_retry）次（线性退避），
        全部失败抛 BrowserLaunchError。seed_kit 默认沿用旧会话的种子。
        """
        if seed_kit == "__keep__":
            seed_kit = session.seed_kit
        ch = channel if channel is not None else session.channel
        session.close(store=self.store, log=self.log)

        retries = max_retry if max_retry is not None else self.config.ip_retry
        last_err = None
        for attempt in range(1, retries + 1):
            if stop is not None and stop.is_set():
                raise UserInterrupted("用户中断")
            try:
                new_session = self.launch(channel=ch, seed_kit=seed_kit,
                                          stop=stop)
                self.log(f"    [relaunch] 浏览器已重启，新出口 "
                         f"IP={new_session.identity}")
                return new_session
            except UserInterrupted:
                raise
            except (Exception, SystemExit) as e:  # noqa: BLE001
                last_err = e
                backoff = min(backoff_base * attempt, backoff_cap)
                self.log(f"    [!] 获取新 IP 第 {attempt}/{retries} "
                         f"次失败: {e}，{backoff}s 后重试...")
                if stop is not None:
                    if stop.wait(backoff):
                        raise UserInterrupted("用户中断") from e
                else:
                    time.sleep(backoff)
        raise BrowserLaunchError(
            f"重试 {retries} 次仍无法获取新 IP: {last_err}")

    # ---- view 管理 ----

    def ensure_site(self, session: Session, site_name: str,
                    site_domain: str, seed_kit: dict | None = None,
                    stop: threading.Event | None = None) -> SiteView:
        """确保 session 有 site_name 的 view；无则懒建。

        懒建：browser.new_context(locale="zh-CN") → 按 f"{site_name}:{bare}"
        装载 Cookie（库优先；直连无库时 JSON 种子兜底；代理新 IP 播种
        seed_kit——复用 launch 的 Cookie 装载段逻辑）→ new_page →
        warmup（该站首页现场签发 Cookie）。返回 view。
        """
        if site_name in session.views:
            return session.views[site_name]

        cfg = self.config
        # 确定 identity
        if cfg.use_proxy and session.req_proxies is not None:
            exit_ip = self._query_exit_ip_with_retry(session.req_proxies)
            if exit_ip is None:
                raise ExitIPError(f"经通道查询出口 IP 失败，"
                                  f"隧道疑似不可用，无法绑定 Cookie identity")
            identity = f"{site_name}:{exit_ip}"
        else:
            identity = f"{site_name}:direct"

        # ---- Cookie 装载（与 launch 现状逐字一致）----
        cookies = self.store.load(identity)
        if not cookies and not cfg.use_proxy:
            seed_json = cfg.resolved_cookie_json()
            if not seed_json.exists():
                raise BrowserLaunchError(
                    f"数据库中没有 identity={identity} 的 Cookie，"
                    f"且找不到种子文件 {seed_json}，请先导出 Cookie")
            n = self.store.seed_from_json(identity, seed_json)
            cookies = self.store.load(identity)
            self.log(f"    [cookie] 已从 {seed_json.name} 导入 {n} 个 Cookie "
                     f"到 identity={identity}")
        info = self.store.info(identity)
        self.log(f"    [cookie] identity={identity}，可用 {len(cookies)} 个"
                 f"（库内共 {info['total']}，已过期剔除 {info['expired']}，"
                 f"最近过期: {info['earliest_expiry'] or '未知'}）")
        if cfg.use_proxy and not cookies and seed_kit:
            cookies = [dict(c) for c in seed_kit["cookies"]]
            self.store.save(identity, cookies)
            self.store.record_event(
                identity, "seed",
                f"kit={seed_kit['name']} x5sec={1 if seed_kit.get('x5sec') else 0}")
            self.log(f"    [cookie] 新出口 IP 播种独占种子身份"
                     f"「{seed_kit['name']}」（{len(cookies)} 个 Cookie"
                     f"{'，含 x5sec 实验组' if seed_kit.get('x5sec') else ''}）")
        elif cfg.use_proxy and not cookies:
            self.log(f"    [cookie] 无种子身份，新出口 IP 空会话白板启动，"
                     f"warmup 时由站点为 {identity} 现场签发全新匿名身份")
        if not cookies and not cfg.use_proxy:
            raise BrowserLaunchError(
                f"identity={identity} 下没有可用 Cookie（可能全部过期）")

        # ---- 创建 context + 注入 Cookie + new_page ----
        ctx = session.browser.new_context(locale="zh-CN")
        if cookies:
            ctx.add_cookies(cookies)
        page = ctx.new_page()

        view = SiteView(context=ctx, page=page, identity=identity,
                        domain=site_domain, seed_kit=seed_kit)
        session.views[site_name] = view

        # ---- warmup（代理模式访问首页现场签发 Cookie）----
        if cfg.use_proxy:
            self.warmup(session, site_name, homepage=self.homepage, stop=stop)

        return view

    # ---- 预热 ----

    def warmup(self, session: Session, site_name: str,
               homepage: str = "https://www.1688.com/",
               stop: threading.Event | None = None,
               block_check=None, max_wait: float = 600.0) -> bool:
        """新 IP 的 Cookie 自动更新：访问首页触发站点现场签发并回写。

        site_name: 要预热的 view 的站点注册名（session.views[site_name]）。
        block_check: fn(page) -> str | None 的风控检测回调（站点插件提供，
        如 sites.alibaba1688.page_block_reason）；None 时跳过检测。
        返回 True 表示预热顺利（含过证后）；未过证/失败返回 False
        （不阻断启动，后续抓取重试/手动过证流程会处理）。
        homepage: 落地页；None 归一到默认 1688 首页（兼容旧调用不传参）。
        """
        homepage = homepage or "https://www.1688.com/"
        view = session.views[site_name]
        page, ctx, identity = view.page, view.context, view.identity
        headed = not self.config.headless
        try:
            page.goto(homepage, wait_until="domcontentloaded", timeout=60000)
            time.sleep(random.uniform(2.0, 4.0))
            blocked = block_check(page) if block_check else None
            if blocked and headed:
                self.log(f"    [warmup] 首页命中风控（{blocked}）")
                if self.auto_solve is not None:
                    try:
                        self.log(f"    [warmup] 先尝试自动过证（轨迹回放滑块）…")
                        if self.auto_solve(page) \
                                and (block_check is None
                                     or block_check(page) is None):
                            n = self.store.save_from_context(
                                identity, ctx, self.log, domain=view.domain)
                            self.log(f"    [warmup] ✓ 自动过证成功，{n} 个 Cookie"
                                     f"（含新 x5sec）已写回 {identity} 名下")
                            return True
                    except Exception as e:  # noqa: BLE001
                        self.log(f"    [warmup] [!] 自动过证异常"
                                 f"（{type(e).__name__}: {e}），转等手动")
                self.log(f"    [warmup] 👉 请在 {identity} 的浏览器窗口里手动"
                         f"拖动滑块，脚本每 5s 自动检测"
                         f"（最长 {max_wait / 60:.0f} 分钟）...")
                if self._wait_manual_pass(
                        page, stop, max_wait, block_check=block_check,
                        auto_solve=self.auto_solve):
                    n = self.store.save_from_context(
                        identity, ctx, self.log, domain=view.domain)
                    self.log(f"    [warmup] ✓ 检测到验证已通过，{n} 个 Cookie"
                             f"（含新 x5sec）已写回 {identity} 名下")
                    return True
                if stop is not None and stop.is_set():
                    return False
                self.log(f"    [warmup] 等待超时仍未过证（不阻断启动）")
                return False
            n = self.store.save_from_context(
                identity, ctx, self.log, domain=view.domain)
            if blocked:
                self.log(f"    [warmup] 首页即命中风控（{blocked}），已回写 {n} 个"
                         f" Cookie；headed 模式可在窗口手动过证后自动继续")
                return False
            self.log(f"    [warmup] 首页预热完成，{n} 个 Cookie 已与出口 "
                     f"{identity} 绑定（站点现场签发）")
            return True
        except Exception as e:  # noqa: BLE001
            self.log(f"    [!] 首页预热失败（不阻断启动，后续抓取重试处理）: "
                     f"{str(e).splitlines()[0][:150]}")
            return False

    def _wait_manual_pass(self, page, stop, seconds: float,
                          interval: float = 5.0, block_check=None,
                          auto_solve=None, auto_interval: float = 90.0) -> bool:
        """轮询当前页面是否已脱离拦截态（不发起新请求，只在当前页读
        innerText，不会加重风控）。检测到验证通过返回 True。

        auto_solve 不为空时，等待期间每隔 auto_interval 秒自己尝试一轮
        自动过证，与人工操作互不排斥，谁先通过算谁。
        """
        deadline = time.monotonic() + seconds
        last_auto = time.monotonic()
        while time.monotonic() < deadline:
            if stop is not None and stop.is_set():
                return False
            try:
                if block_check is None or block_check(page) is None:
                    return True
            except Exception:  # noqa: BLE001
                return False  # 页面/浏览器异常，交给调用方后续流程
            if auto_solve is not None \
                    and time.monotonic() - last_auto >= auto_interval:
                last_auto = time.monotonic()
                try:
                    # 先刷新拿新鲜滑块（陈旧滑块原地回放永远不过）
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    time.sleep(random.uniform(1.5, 3.0))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    if auto_solve(page) and (block_check is None
                                             or block_check(page) is None):
                        return True
                except Exception:  # noqa: BLE001
                    pass
            if stop is not None:
                stop.wait(interval)
            else:
                time.sleep(interval)
        return False

    # ---- Cookie 回写 ----

    def save_cookies(self, session: Session) -> int:
        """把浏览器所有 view 的最新 Cookie（含新 x5sec）写回各 identity 名下。"""
        total = 0
        for _site_name, view in session.views.items():
            if view.context is not None:
                total += self.store.save_from_context(
                    view.identity, view.context, self.log, domain=view.domain)
        return total
