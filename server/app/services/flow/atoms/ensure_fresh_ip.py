# -*- coding: utf-8 -*-
"""ensure_fresh_ip 原子：出口 IP 保鲜检查。

语义抽取自 server/app/workers/contact_fetch.py::_check_ip_fresh
及其调用点（青果代理出口 IP 每 30 分钟轮换，轮换后需重启浏览器
绑定新 identity）：
  - 用 browser.get_exit_ip(req_proxies) 探测当前出口 IP，
    失败重试 3 次、每次间隔 5s；
  - 查询失败（隧道疑似失效）或 IP 已轮换（!= identity）时，
    内部委托 swap_ip 原子换 IP；
  - 未轮换则直接返回 ok。

与原实现的差异（DAG 化统一）：
  - 原实现 IP 已轮换时不换通道、只重启浏览器；本原子两种情形都委托
    swap_ip（换通道 + 重启浏览器），与设计文档 §3.2「内部调 swap_ip」一致。
  - 探测间隔的 time.sleep(5) 改为 ctx.wait(5)（停止感知，语义等价）。
  - 直连模式（req_proxies 为空）不检查——原实现仅在 proxy 模式下调用
    _check_ip_fresh。
"""
from __future__ import annotations

from ..base import Atom, AtomResult, Context, OUTCOME_STOPPED
from ..registry import register
from ...crawl import browser as browser_mod
from .swap_ip import SwapIpAtom


@register
class EnsureFreshIpAtom(Atom):
    name = "ensure_fresh_ip"
    title = "出口 IP 保鲜检查"
    inputs = {
        "resources.req_proxies": "dict|None requests 代理字典",
        "resources.identity": "str 当前出口 IP 或 'direct'",
        "resources.*": "swap_ip 所需资源（需换 IP 时）",
    }
    outputs = {
        "resources.channel/browser/page/identity/req_proxies":
            "发生换 IP 时由 swap_ip 更新",
    }
    param_spec = {
        "type": "object",
        "properties": {
            "ip_retry": {"type": "integer", "default": 3, "minimum": 1,
                         "title": "换 IP 重试次数（透传 swap_ip）"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        res = ctx.resources
        req_proxies = res.get("req_proxies")
        identity = res.get("identity") or "direct"
        # 直连模式不检查（来源：contact_fetch._worker 仅在 proxy 模式调用）
        if not req_proxies:
            return AtomResult(detail="直连模式无需检查出口 IP",
                              data={"exit_ip": identity, "rotated": False})

        # ---- 探测当前出口 IP（来源：_check_ip_fresh）----
        cur_ip = browser_mod.get_exit_ip(req_proxies)
        if cur_ip is None:
            for _ in range(3):
                if ctx.wait(5):
                    return AtomResult(outcome=OUTCOME_STOPPED,
                                      detail="任务已停止")
                cur_ip = browser_mod.get_exit_ip(req_proxies)
                if cur_ip:
                    break

        if cur_ip is None:
            reason = "出口 IP 查询失败，隧道疑似失效"
        elif cur_ip != identity:
            reason = f"出口 IP 已轮换（{identity} -> {cur_ip}）"
        else:
            return AtomResult(data={"exit_ip": cur_ip, "rotated": False})

        # ---- 委托 swap_ip 换 IP（来源：_worker 中 _check_ip_fresh 调用点）----
        ctx.emit("warning", f"{reason}，重启浏览器绑定新出口 IP",
                 {"worker": ctx.worker_id, "old_ip": identity,
                  "new_ip": cur_ip})
        result = SwapIpAtom().run(ctx, {
            "ip_retry": max(1, int(params.get("ip_retry") or 3)),
            "note": reason,
        })
        if result.ok:
            result.data["rotated"] = True
            result.data["exit_ip"] = res.get("identity")
        return result
