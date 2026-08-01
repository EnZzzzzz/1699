# -*- coding: utf-8 -*-
"""relaunch_browser 原子：原通道重启浏览器（不换通道）。

复刻蓝本 scraper/taobao_1688/contact_fetcher.py docstring「网络/代理层错误」
的处置：隧道断开/连接重置/DNS 失败等网络层错误与风控区分处理——不换通道，
在**原通道**上重启浏览器并退避重试。

语义 = swap_ip 去掉「换通道」一步（代码结构对齐 SwapIpAtom，行为来源
contact_fetch.py::_relaunch_browser）：
  1. 回写旧 Cookie（save_cookies，失败仅告警不阻断）；
  2. 关闭旧浏览器（忽略异常）；
  3. 用**当前** channel 经 pool_client.channel_proxy 取代理
     （直连通道返回 (None, None)）；
  4. launch_browser 重启，ip_retry 次重试，退避 min(30*attempt, 120)，
     停止感知。

直连通道：网络错误本就需要原通道重启（蓝本语义），**不退化**，以
proxy_server=None 正常重启。
"""
from __future__ import annotations

from ..base import (
    Atom, AtomResult, Context,
    OUTCOME_NET_ERROR, OUTCOME_STOPPED,
)
from ..registry import register
from ...crawl import browser as browser_mod


@register
class RelaunchBrowserAtom(Atom):
    name = "relaunch_browser"
    title = "原通道重启浏览器"
    inputs = {
        "resources.pool_client": "PoolClient",
        "resources.channel": "dict 当前通道（不换，原地重启）",
        "resources.db": "ShopDB",
        "resources.browser": "旧浏览器（可空）",
        "resources.page": "旧页面（可空，取其 context 回写 Cookie）",
        "resources.identity": "str 旧出口 IP 或 'direct'",
    }
    outputs = {
        "resources.browser": "新浏览器实例",
        "resources.page": "新页面实例",
        "resources.identity": "str 出口 IP（原通道不变）",
        "resources.req_proxies": "dict|None",
    }
    param_spec = {
        "type": "object",
        "properties": {
            "ip_retry": {"type": "integer", "default": 3, "minimum": 1,
                         "title": "重启浏览器重试次数"},
            "headed": {"type": "boolean", "default": False,
                       "title": "有头模式"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        res = ctx.resources
        pool_client = res.get("pool_client")
        db = res.get("db")
        channel = res.get("channel")
        if pool_client is None or channel is None:
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail="ctx.resources 缺少 pool_client 或 channel")
        ip_retry = max(1, int(params.get("ip_retry") or 3))
        headed = bool(params.get("headed", False))
        old_browser = res.get("browser")
        old_page = res.get("page")
        old_identity = res.get("identity") or "direct"

        # ---- 1. 回写旧 Cookie（来源：_relaunch_browser 开头）----
        old_bctx = old_page.context if old_page is not None else None
        if old_bctx is not None and db is not None:
            try:
                browser_mod.save_cookies(db, old_identity, old_bctx)
            except Exception as e:  # noqa: BLE001 - 原实现仅告警
                ctx.emit("warning", f"旧 Cookie 回写失败: {e}",
                         {"worker": ctx.worker_id})
        # ---- 2. 关闭旧浏览器 ----
        if old_browser is not None:
            try:
                old_browser.close()
            except Exception:  # noqa: BLE001
                pass

        # ---- 3. 原通道取代理（不换通道；直连为 (None, None)）----
        try:
            server, auth = pool_client.channel_proxy(channel)
        except Exception as e:  # noqa: BLE001
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail=f"读取通道代理配置失败：{e}")

        # ---- 4. 重试重启浏览器（退避 min(30*attempt, 120)，停止感知）----
        last_err = None
        for attempt in range(1, ip_retry + 1):
            if ctx.stop_requested():
                return AtomResult(outcome=OUTCOME_STOPPED,
                                  detail="任务已停止")
            try:
                browser, page, identity, req_proxies, _ = \
                    browser_mod.launch_browser(
                        db, headless=not headed,
                        proxy_server=server, proxy_auth=auth)
                res["browser"] = browser
                res["page"] = page
                res["identity"] = identity
                res["req_proxies"] = req_proxies
                ctx.emit("info",
                         f"浏览器已在原通道上重启（出口 IP: {identity}）",
                         {"worker": ctx.worker_id, "identity": identity})
                return AtomResult(data={
                    "identity": identity,
                    "channel_id": channel.get("id"),
                })
            except (Exception, SystemExit) as e:  # 与原实现捕获口径一致
                last_err = e
                backoff = min(30 * attempt, 120)
                ctx.report_progress({"retry": attempt,
                                     "exit_ip": old_identity})
                ctx.emit("warning",
                         f"重启浏览器第 {attempt}/{ip_retry} 次失败: {e}，"
                         f"{backoff}s 后重试",
                         {"worker": ctx.worker_id, "retry": attempt})
                ctx.wait(backoff)
        return AtomResult(
            outcome=OUTCOME_NET_ERROR,
            detail=f"重试 {ip_retry} 次仍无法重启浏览器: {last_err}")
