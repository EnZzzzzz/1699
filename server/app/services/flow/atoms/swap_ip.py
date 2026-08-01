# -*- coding: utf-8 -*-
"""swap_ip 原子：更换出口 IP（回写 Cookie → 关旧浏览器 → 换通道 → 重开）。

语义抽取自 server/app/workers/contact_fetch.py::_relaunch_browser
及其调用点（出口 IP 轮换 / 网络故障 / 疑似风控分支），行为不变：
  1. 回写旧 Cookie（save_cookies，失败仅告警不阻断）；
  2. 关闭旧浏览器（忽略异常）；
  3. 换通道 = swap_channel_with_events（release 旧通道回池 + 全池随机重抽，
     埋事件；来源：contact_fetch 各换 IP 分支调用点）；
  4. 以 ip_retry 次重试重启浏览器，退避 min(30*attempt, 120)，停止感知。

与原实现的唯一差异：停止/睡眠改走 ctx.stop_requested / ctx.wait
（原实现用 threading.Event；语义等价，且便于脱离 Celery 单测）。
"""
from __future__ import annotations

from ..base import (
    Atom, AtomResult, Context,
    OUTCOME_NET_ERROR, OUTCOME_STOPPED,
)
from ..registry import register
from ... import pool_client as pool_client_mod
from ...crawl import browser as browser_mod


class _EmitShim:
    """swap_channel_with_events 需要带 emit 的 rt；经 ctx.emit 转发，
    rt 缺失（单测）时静默丢弃。"""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def emit(self, level: str, message: str, data: dict | None = None) -> None:
        self._ctx.emit(level, message, data)


@register
class SwapIpAtom(Atom):
    name = "swap_ip"
    title = "更换出口 IP"
    inputs = {
        "resources.pool_client": "PoolClient",
        "resources.channel": "dict 当前通道",
        "resources.db": "ShopDB",
        "resources.browser": "旧浏览器（可空）",
        "resources.page": "旧页面（可空，取其 context 回写 Cookie）",
        "resources.identity": "str 旧出口 IP 或 'direct'",
    }
    outputs = {
        "resources.channel": "dict 新通道",
        "resources.browser": "新浏览器实例",
        "resources.page": "新页面实例",
        "resources.identity": "str 新出口 IP",
        "resources.req_proxies": "dict|None",
    }
    param_spec = {
        "type": "object",
        "properties": {
            "ip_retry": {"type": "integer", "default": 3, "minimum": 1,
                         "title": "重启浏览器重试次数"},
            "note": {"type": "string", "default": "",
                     "title": "换通道事件备注"},
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

        # ---- 直连模式：出口即本机 IP，换通道无意义。退化为停止感知退避
        #      后重试（对齐 contact_fetch.py L319-323：block_retried 次退避
        #      min(60*attempt, 300)）；attempt 由引擎策略拦截器经
        #      params["_attempt"] 注入（缺省 1）。直连判定与
        #      PoolClient.channel_proxy L121 一致 ----
        if channel.get("is_direct") or not channel.get("tunnel"):
            attempt = max(1, int(params.get("_attempt") or 1))
            backoff = min(60 * attempt, 300)
            ctx.emit("warning", f"直连模式无法换 IP，退避 {backoff}s 后重试",
                     {"worker": ctx.worker_id, "seconds": backoff,
                      "attempt": attempt})
            if ctx.wait(backoff):
                return AtomResult(outcome=OUTCOME_STOPPED,
                                  detail="任务已停止")
            return AtomResult(data={"direct": True, "backoff": backoff})

        ip_retry = max(1, int(params.get("ip_retry") or 3))
        note = params.get("note") or ""
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
        # ---- 2. 关闭旧浏览器（来源：_relaunch_browser）----
        if old_browser is not None:
            try:
                old_browser.close()
            except Exception:  # noqa: BLE001
                pass

        # ---- 3. 换通道（来源：contact_fetch 各换 IP 分支调用点）----
        try:
            channel = pool_client_mod.swap_channel_with_events(
                _EmitShim(ctx), pool_client, channel,
                ctx.worker_id or 0, note=note)
        except Exception as e:  # noqa: BLE001 - 原实现：API 失败抛异常由调用方处置
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail=f"换通道失败：{e}")
        res["channel"] = channel

        # ---- 4. 重试重启浏览器（来源：_relaunch_browser 重试循环）----
        last_err = None
        for attempt in range(1, ip_retry + 1):
            if ctx.stop_requested():
                return AtomResult(outcome=OUTCOME_STOPPED,
                                  detail="任务已停止")
            try:
                server, auth = pool_client.channel_proxy(channel)
                browser, page, identity, req_proxies, _ = \
                    browser_mod.launch_browser(
                        db, headless=not headed,
                        proxy_server=server, proxy_auth=auth)
                res["browser"] = browser
                res["page"] = page
                res["identity"] = identity
                res["req_proxies"] = req_proxies
                ctx.emit("info", f"浏览器已重启，新 identity={identity}",
                         {"worker": ctx.worker_id, "identity": identity})
                return AtomResult(data={
                    "old_ip": old_identity,
                    "new_ip": identity,
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
