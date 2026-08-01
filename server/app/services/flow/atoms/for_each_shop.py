# -*- coding: utf-8 -*-
"""
for_each_shop 原子：店铺循环（容器）。

批次配额语义抽取自 server/app/workers/contact_fetch.py L149-184：
每批 num 个 → 批间强制休息 batch_rest 秒（±10% 随机浮动，对应
random.uniform(batch_rest*0.9, batch_rest*1.1)，L165-167）并发事件
（L173-178）；max_batches 封顶（0 不限）；limit 限制成功处理总数
（0 不限，只计 ok + empty，对齐 L153-154 / L360-361 中 state["fetched"]
口径）；db.count_pending()==0 的判停由 body 内 claim_shops 的 empty
outcome 表达（见下）。

循环体：body 为子节点列表 [{"id", "atom", "params"}]，每次迭代共享同一个
ctx 依次执行（registry.get 实例化）；子节点 outcome 非 ok 时透传并中断本
迭代（跳过剩余子节点），按 empty/failed 计数后继续下一迭代。若中断原因
是 empty 且 ctx.vars["shops"] 为空列表（claim_shops 认领枯竭信号），整个
循环结束。

P0 只实现串行版：parallel 字段保留并校验 >= 1；parallel > 1 需 P1 引擎的
多 worker 上下文 + 共享配额锁（docs/flow-architecture.md §5.1），本实现
一律按串行执行。

停止感知：迭代边界、子节点间、批间休息均检查 ctx.stop_requested() /
ctx.wait()。汇总统计写 ctx.vars["loop_stats"]。
"""
from __future__ import annotations

import random
import time

from ..base import (
    Atom, AtomResult, Context,
    OUTCOME_EMPTY, OUTCOME_OK, OUTCOME_STOPPED,
)
from ..registry import register


@register
class ForEachShopAtom(Atom):
    name = "for_each_shop"
    title = "店铺循环（容器）"
    inputs = {"vars": "body 子节点读写共享"}
    outputs = {"vars.loop_stats": "dict（ok/empty/failed/batches/fetched）"}
    param_spec = {
        "type": "object",
        "properties": {
            "num": {"type": "integer", "minimum": 1, "default": 10,
                    "description": "每批处理数量"},
            "batch_rest": {"type": "number", "default": 900,
                           "description": "批间强制休息秒（±10% 随机浮动）"},
            "max_batches": {"type": "integer", "minimum": 0, "default": 0,
                            "description": "最多批数（0 不限）"},
            "limit": {"type": "integer", "minimum": 0, "default": 0,
                      "description": "最多成功处理个数（ok+empty，0 不限）"},
            "parallel": {"type": "integer", "minimum": 1, "default": 1,
                         "description": "并行 worker 数（P0 按串行执行，"
                                        ">1 由 P1 引擎支持）"},
            "body": {"type": "array", "default": [],
                     "description": "子节点列表 [{\"id\", \"atom\", \"params\"}]"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        from ..registry import get as get_atom  # 延迟导入避免循环依赖

        params = params or {}
        num = max(1, int(params.get("num") or 10))
        batch_rest = float(params.get("batch_rest") or 900)
        max_batches = int(params.get("max_batches") or 0)
        limit = int(params.get("limit") or 0)
        # parallel 不能用 `or 1` 归一（会把显式 0 吞掉），必须原样取出校验
        parallel = params.get("parallel")
        parallel = 1 if parallel is None else int(parallel)
        body = params.get("body") or []

        if parallel < 1:
            raise ValueError("parallel 必须 >= 1")
        if not isinstance(body, list) or not body:
            raise ValueError("body 必须是非空子节点列表")
        for node in body:
            if not isinstance(node, dict) or not node.get("atom"):
                raise ValueError(f"body 子节点缺少 atom 字段: {node!r}")

        # state 字段对齐 contact_fetch.py L487 的批次配额状态
        state = {"done": 0, "batch": 1, "rest_until": 0.0, "fetched": 0}
        stats = {"ok": 0, "empty": 0, "failed": 0}
        stopped = False
        drained = False  # 认领枯竭（没有待处理店铺）

        while True:
            if ctx.stop_requested():
                stopped = True
                break

            # ---- 批次配额（contact_fetch.py L151-184 串行化：limit 判停 →
            #      批内配额 → max_batches 判停 → 批间 ±10% 休息 + 事件 →
            #      休息结束 done 清零、batch 递增）----
            if limit and state["fetched"] >= limit:
                break
            if state["done"] >= num:
                if max_batches and state["batch"] >= max_batches:
                    break
                now = time.time()
                if state["rest_until"] <= now:
                    state["rest_until"] = now + random.uniform(
                        batch_rest * 0.9, batch_rest * 1.1)
                wait_for = state["rest_until"] - now
                ctx.emit("warning",
                         f"第 {state['batch']} 批已采满 {num} 个，批间休息 "
                         f"{wait_for / 60:.1f} 分钟（防风控）",
                         {"batch": state["batch"], "seconds": round(wait_for)})
                if ctx.wait(wait_for) or ctx.stop_requested():
                    stopped = True
                    break
                state["done"] = 0
                state["batch"] += 1
            state["done"] += 1

            # ---- 执行 body 子节点（共享同一个 ctx）----
            interrupted: AtomResult | None = None
            for node in body:
                if ctx.stop_requested():
                    stopped = True
                    break
                atom = get_atom(node["atom"])
                res = atom.run(ctx, node.get("params") or {})
                if not res.ok:
                    interrupted = res
                    break
            if stopped:
                break

            if interrupted is None:
                stats["ok"] += 1
                state["fetched"] += 1
            elif interrupted.outcome == OUTCOME_EMPTY:
                if not ctx.vars.get("shops"):
                    # 认领枯竭（对齐 contact_fetch.py L186-189 break）
                    drained = True
                    break
                stats["empty"] += 1
                state["fetched"] += 1
            else:
                stats["failed"] += 1

            ctx.report_progress({"batch": state["batch"],
                                 "done": state["done"],
                                 "fetched": state["fetched"], **stats})

        loop_stats = {**stats, "batches": state["batch"],
                      "fetched": state["fetched"]}
        ctx.vars["loop_stats"] = loop_stats
        ctx.report_progress(loop_stats)

        if stopped:
            return AtomResult(outcome=OUTCOME_STOPPED,
                              detail="任务被停止", data=loop_stats)
        if drained and state["fetched"] == 0:
            return AtomResult(outcome=OUTCOME_EMPTY,
                              detail="没有待处理的店铺", data=loop_stats)
        return AtomResult(outcome=OUTCOME_OK,
                          detail=f"循环结束：ok={stats['ok']} "
                                 f"empty={stats['empty']} "
                                 f"failed={stats['failed']}",
                          data=loop_stats)
