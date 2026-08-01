# -*- coding: utf-8 -*-
"""launch_browser 原子：启动浏览器。

包装 server/app/services/crawl/browser.py 的 launch_browser
（调用方式来源：contact_fetch._worker 启动段）。代理参数从
ctx.resources["channel"] 经 pool_client.channel_proxy(channel) 取得；
直连通道 channel_proxy 返回 (None, None)，launch_browser 按直连启动。
浏览器生命周期由引擎管理，本原子只把句柄写进 ctx.resources。
"""
from __future__ import annotations

from ..base import Atom, AtomResult, Context, OUTCOME_NET_ERROR
from ..registry import register
from ...crawl import browser as browser_mod


@register
class LaunchBrowserAtom(Atom):
    name = "launch_browser"
    title = "启动浏览器"
    inputs = {
        "resources.db": "ShopDB",
        "resources.pool_client": "PoolClient（有通道时取代理参数）",
        "resources.channel": "dict 当前通道（可空=直连）",
    }
    outputs = {
        "resources.browser": "浏览器实例",
        "resources.page": "页面实例",
        "resources.identity": "str 出口 IP 或 'direct'",
        "resources.req_proxies": "dict|None requests 代理字典",
    }
    param_spec = {
        "type": "object",
        "properties": {
            "headed": {"type": "boolean", "default": False,
                       "title": "有头模式"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        res = ctx.resources
        db = res.get("db")
        pool_client = res.get("pool_client")
        channel = res.get("channel") or {}
        headed = bool(params.get("headed", False))
        try:
            server, auth = None, None
            if pool_client is not None and channel:
                server, auth = pool_client.channel_proxy(channel)
            browser, page, identity, req_proxies, _ = browser_mod.launch_browser(
                db, headless=not headed,
                proxy_server=server, proxy_auth=auth)
        except browser_mod.BrowserUnavailable as e:
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail=f"浏览器不可用：{e}")
        except Exception as e:  # noqa: BLE001 - 启动失败统一归类网络/环境故障
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail=f"启动浏览器失败：{e}")
        res["browser"] = browser
        res["page"] = page
        res["identity"] = identity
        res["req_proxies"] = req_proxies
        # 事件口径来源：contact_fetch._worker 浏览器就绪 emit
        ctx.emit("info", f"浏览器就绪（出口 IP: {identity}）",
                 {"worker": ctx.worker_id, "identity": identity})
        return AtomResult(data={"identity": identity})
