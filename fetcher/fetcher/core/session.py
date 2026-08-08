# -*- coding: utf-8 -*-
"""Session：一个 worker 当前持有的浏览器会话及其链路身份。

会话链路一致性（迁移自 scraper/taobao_1688/common.py 的设计）：
    Cookie / UA / 指纹 / 出口 IP 四者必须配套。identity 即出口 IP
    （直连记 "direct"），Cookie 按 identity 隔离存取；指纹种子按
    identity（或种子身份名）固定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 避免 core -> net 的反向依赖
    from fetcher.net.proxy.base import Channel


# ---------- identity 辅助函数 ----------

def bare_identity(identity: str) -> str:
    """剥掉站点前缀：'1688:1.2.3.4' → '1.2.3.4'；无前缀原样返回。

    指纹/保鲜检查等需要裸 IP 的场合用此函数从 identity 键中提取裸 IP。
    兼容旧键（无前缀直存 IP 或 'direct'）。
    """
    return identity.split(":", 1)[1] if ":" in identity else identity


def is_direct(identity: str) -> bool:
    """identity 是否代表直连模式（含 'direct' 与 'site:direct' 两种形态）。"""
    return bare_identity(identity) == "direct"


@dataclass
class SiteView:
    """一个站点在本浏览器进程内的独立上下文视图。"""

    context: Any = None          # Playwright BrowserContext
    page: Any = None             # Playwright Page
    identity: str = ""           # f"{site}:{ip}" 或 f"{site}:direct"（P2 键）
    seed_kit: dict | None = None
    domain: str = ""             # 该站 Cookie 域（close_site 回写过滤用）


@dataclass
class Session:
    """一次浏览器启动的产物。

    browser 为 Playwright 对象（Any 以保持本包可独立 import，
    不依赖 playwright 安装）。views 按 site 注册名索引多个
    SiteView（一站点一独立 context）；page/ctx/identity 经
    _active_site 路由到活动 view。

    向后兼容：保留 page/identity 仅关键字参数；传入时自动装填为
    `_default` view，供旧测试/旧调用方过渡。新代码应走 views +
    ensure_site 路径。
    """

    browser: Any = None
    channel: "Channel | None" = None  # 代理通道；直连为 None
    req_proxies: dict | None = None   # requests 查询出口 IP 用的代理字典
    views: dict[str, SiteView] = field(default_factory=dict)  # site 注册名 → view
    seed_kit: dict | None = None      # 进程级种子（首个 view 播种用；保留兼容）
    extra: dict = field(default_factory=dict)  # 站点/任务层暂存
    _active_site: str | None = None   # 当前活动站点（view 路由用；由控制层设置）

    def __init__(self, browser=None, channel=None, req_proxies=None,
                 views=None, seed_kit=None, extra=None,
                 _active_site=None,
                 page=None, identity=None):
        """向后兼容：page/identity 自动装填为 _default view。
        新代码应只传 views。"""
        self.browser = browser
        self.channel = channel
        self.req_proxies = req_proxies
        self.views = views if views is not None else {}
        self.seed_kit = seed_kit
        self.extra = extra if extra is not None else {}
        self._active_site = _active_site
        # 向后兼容：page / identity 快捷构造 → 单 view
        if page is not None or identity is not None:
            ctx = None
            if page is not None:
                # 尝试取 page.context（Playwright Page 或 Mock）
                try:
                    ctx = page.context
                except Exception:  # noqa: BLE001
                    ctx = None
            vid = identity if identity is not None else "direct"
            self.views["_default"] = SiteView(
                context=ctx, page=page, identity=vid)

    # ---- view 路由 ----

    def _active_view(self) -> SiteView | None:
        """按 _active_site 路由返回活动 view；未设且仅一个 view 时回落。"""
        if self._active_site is not None:
            return self.views.get(self._active_site)
        if len(self.views) == 1:
            return next(iter(self.views.values()))
        return None

    def set_active_site(self, site: str):
        """设置当前活动站点。site 必须在 views 中。"""
        if site not in self.views:
            raise ValueError(
                f"set_active_site({site!r})：views 中不存在该站点，"
                f"当前 views={list(self.views.keys())}")
        self._active_site = site

    @property
    def page(self):
        """路由到活动 view 的 page。"""
        view = self._active_view()
        return view.page if view else None

    @property
    def ctx(self):
        """路由到活动 view 的 BrowserContext。"""
        view = self._active_view()
        return view.context if view else None

    @property
    def identity(self) -> str:
        """路由到活动 view 的 identity。"""
        view = self._active_view()
        return view.identity if view else ""

    @property
    def use_proxy(self) -> bool:
        return self.channel is not None and self.channel.server is not None

    # ---- Cookie 回写辅助（F4：DRY 共用逻辑）----

    @staticmethod
    def _write_view_cookies(view: SiteView, store, log) -> None:
        """按 view.domain 过滤后回写该 view 的 Cookie 到 store。

        domain 过滤逻辑：优先 view.domain，否则回落 store.domain，
        确保多站共存时各站 Cookie 入各桶（与 save_from_context 同语义）。
        """
        if store is None or view.context is None:
            return
        domain_filter = view.domain or getattr(store, "domain", "")
        cookies = [c for c in view.context.cookies()
                   if domain_filter in c.get("domain", "")]
        if cookies:
            store.save(view.identity, cookies)

    # ---- 两层关闭 ----

    def close_site(self, site: str, store=None, log=None):
        """关闭单个站点的 view：回写该 view Cookie（按 view.domain 过滤）→
        关 context → 从 views 移除。供 P3-3 SwapIP 两阶段用。
        """
        view = self.views.get(site)
        if view is None:
            return
        # 回写 Cookie（按 view.domain 过滤）
        try:
            self._write_view_cookies(view, store, log)
        except Exception as e:  # noqa: BLE001 - 回写失败不阻断关闭
            if log:
                log(f"[!] close_site({site}) Cookie 回写失败: {e}")
        # 关 context
        if view.context is not None:
            try:
                view.context.close()
            except Exception:  # noqa: BLE001
                pass
        # 从 views 移除
        del self.views[site]
        # 如果关闭的恰是 active site，清空
        if self._active_site == site:
            self._active_site = None

    def close(self, store=None, log=None):
        """关闭会话：全部 view 回写 Cookie → browser.close()。

        任何退出路径都应走这里，保证服务端会话租约及时释放、
        Cookie 信任链不丢。Session 字段（views/identity 等）保留
        不变，供调用方事后检查（与旧版 close 语义一致）。

        注意：close() 不清除 views——view 中的 page/context 等
        Playwright 对象在 browser.close() 后已失效，但 views 字典
        本身保留供 _cleanup 等调用方读取 identity 等管理字段。
        """
        # 遍历 views 回写 Cookie（不通过 close_site，保留 views 供事后检查）
        for _site, view in self.views.items():
            try:
                self._write_view_cookies(view, store, log)
            except Exception as e:  # noqa: BLE001 - 回写失败不阻断关闭
                if log:
                    log(f"[!] close() Cookie 回写失败(view={_site}): {e}")
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:  # noqa: BLE001
                pass
