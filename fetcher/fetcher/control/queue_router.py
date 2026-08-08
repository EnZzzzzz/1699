# -*- coding: utf-8 -*-
"""队列路由表与冷却感知的等待函数（P3 Step 1.2 纯函数，无副作用）。

P3-3 将在此文件演进 QueueRouter 类，本 Step 先放基础成员。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueueSpec:
    """队列注册表条目（P3-3 补全 task/topup/domain_suffix 字段）。"""
    queue: str            # "crawl_1688_contact" / ...
    site: str             # 站点注册名 "1688" / "madeinchina"
    requires: set[str]    # 资源需求，如 {"channel", "browser"}


def eligible_queues(registry, ctx, now: float) -> list[str]:
    """当前消费者可认领的队列名列表：资源满足 ∧ 该站点冷却已到期。

    registry: 可迭代的 QueueSpec（或鸭子类型：有 .queue/.site/.requires）。
    ctx: 有 .resources（set）与 .cooldown_until（dict[site, float]）的对象。
    纯函数，无副作用；返回按注册表顺序。
    """
    result = []
    for q in registry:
        if q.requires <= ctx.resources \
                and now >= ctx.cooldown_until.get(q.site, 0):
            result.append(q.queue)
    return result


def condvar_timeout(cooldown_until: dict[str, float], site: str,
                    now: float, cap: float = 30.0) -> float:
    """计算 Condition.wait 的超时值（秒）。

    - site 在冷却中（now < 到期） → min(到期 - now, cap)
    - site 不在冷却 → cap
    - 返回值总是 > 0（若冷却剩余极小如 0.01s 则原样返回）。

    cap 默认为 30s，作为自醒兜底（外部 INSERT 无 notify，最坏 30s 发现）。
    """
    deadline = cooldown_until.get(site, 0)
    if now < deadline:
        remaining = deadline - now
        return remaining if remaining < cap else cap
    return cap
