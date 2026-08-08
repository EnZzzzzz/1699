# -*- coding: utf-8 -*-
"""LocalLoop：无浏览器执行循环（P4-1 wa_check 等非站点任务的载体）。

与 CrawlLoop 的区别：不做浏览器装配/SceneInspector/策略表/熔断/页面簿记
——非站点任务（如 wa_check 的 CheckWhatsApp 原子）没有页面与风控场景，
outcome 直接决定处置：

    OK       → task.on_success（写回结果）
    FATAL    → task.on_giveup(fatal) 后停止（不可自愈，如未登录）
    SKIPPED  → 停止信号，收工
    NET_ERROR/其他 → task.on_giveup(net) 后继续下一项

节奏（逐号间隔/批间休息/风控冷却）由 task 内部经让出型冷却处理
（wa_check 冷却键 = queue 名，见 queue_router.eligible_queues 泛化）。
停止协作：每轮检查 ctx.stopped()；原子返回 SKIPPED 即收工。
"""

from __future__ import annotations

import traceback

from fetcher.control.task import Task
from fetcher.core.types import Outcome


class LocalLoop:
    """单 local 消费者执行循环。

    用法：
        loop = LocalLoop(ctx, task)   # task 为 Task 协议（如 WaCheckTask）
        stats = loop.run()
    """

    def __init__(self, ctx, task: Task):
        self.ctx = ctx
        self.task = task

    def run(self) -> dict:
        stats = self.task.make_stats()
        self.ctx.state.setdefault("task", {})["stats"] = stats
        try:
            while not self.ctx.stopped():
                item = self.task.acquire_item(self.ctx)
                if item is None:
                    self.ctx.set_status(state="无待做任务，退出")
                    break
                self.ctx.state["item"] = item
                self.ctx.set_status(state="执行中…")
                result = self.task.fetch(self.ctx, item)
                outcome = result.outcome if result is not None else None
                if outcome is Outcome.OK:
                    self.task.on_success(self.ctx, item, result)
                elif outcome is Outcome.SKIPPED:
                    self.ctx.set_status(state="被停止信号中断")
                    break
                elif outcome is Outcome.FATAL:
                    self.task.on_giveup(self.ctx, item, result.detail,
                                        "fatal")
                    self.ctx.set_status(state="FATAL，退出")
                    break
                else:
                    self.task.on_giveup(self.ctx, item,
                                        (result.detail if result else "无结果"),
                                        "net")
                self.task.after_item(self.ctx, item)
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            self.ctx.log(f"[X] local 消费者异常退出: {e}\n{tb[-3000:]}")
        return stats
