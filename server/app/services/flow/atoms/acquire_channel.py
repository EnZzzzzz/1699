# -*- coding: utf-8 -*-
"""acquire_channel 原子：向共享池申请通道。

包装 server/app/services/pool_client.py 的 PoolClient.acquire
（事件口径参考 contact_fetch.run_contact_fetch 的申请通道段）。
通道生命周期由引擎管理，本原子只把结果写进 ctx.vars / ctx.resources。
"""
from __future__ import annotations

from ..base import (
    Atom, AtomResult, Context,
    OUTCOME_EMPTY, OUTCOME_NET_ERROR, OUTCOME_STOPPED,
)
from ..registry import register
from ...pool_client import PoolAcquireTimeout


@register
class AcquireChannelAtom(Atom):
    name = "acquire_channel"
    title = "申请通道"
    inputs = {"resources.pool_client": "PoolClient"}
    outputs = {
        "vars.channels": "list[dict] 申请到的全部通道",
        "resources.channel": "dict 首条通道（当前通道）",
    }
    param_spec = {
        "type": "object",
        "properties": {
            "n": {"type": "integer", "default": 1, "minimum": 1,
                  "title": "通道数"},
            "proxy": {"type": "boolean", "default": True,
                      "title": "是否走代理通道"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        pool_client = ctx.resources.get("pool_client")
        if pool_client is None:
            return AtomResult(outcome=OUTCOME_NET_ERROR,
                              detail="ctx.resources 缺少 pool_client")
        n = max(1, int(params.get("n") or 1))
        proxy = bool(params.get("proxy", True))
        ctx.emit("info", f"正在向共享池申请 {n} 条"
                 f"{'代理' if proxy else '直连'}通道",
                 {"n": n, "use_proxy": proxy})
        try:
            channels = pool_client.acquire(
                n, use_proxy=proxy, should_stop=ctx.stop_requested)
        except PoolAcquireTimeout as e:
            # PoolClient.acquire 在等待期间收到停止请求时也抛
            # PoolAcquireTimeout（"等待通道期间收到停止请求"），用
            # ctx.stop_requested 区分两种语义。
            if ctx.stop_requested():
                return AtomResult(outcome=OUTCOME_STOPPED, detail=str(e))
            return AtomResult(outcome=OUTCOME_EMPTY, detail=str(e))
        if not channels:
            return AtomResult(outcome=OUTCOME_EMPTY,
                              detail="共享池未分配到通道")
        ctx.vars["channels"] = channels
        ctx.resources["channel"] = channels[0]
        # 事件口径来源：contact_fetch.run_contact_fetch 申请成功后的 emit
        ctx.emit("info", f"申请到 {len(channels)} 条通道："
                 + "、".join(
                     f"#{c['id']}({c.get('exit_ip') or c.get('tunnel') or '本机IP'})"
                     for c in channels),
                 {"channels": [{"id": c["id"], "tunnel": c.get("tunnel"),
                                "exit_ip": c.get("exit_ip")}
                               for c in channels]})
        return AtomResult(data={"channels": channels})
