# -*- coding: utf-8 -*-
"""Strategy 协议与 PolicyAction。

判断与行动分离的另一面：Strategy 只执行动作（包装原子），绝不自己
做检测。每个 Strategy 执行完返回 StepResult（solved = 本次处置是否
解决了问题，需要重新检测确认）；策略链的推进由 Policy + AttemptTracker
决定，Strategy 不感知自己在链中的位置。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class PolicyAction(enum.Enum):
    """Policy 对一次场景判定给出的决策。"""

    CONTINUE = "continue"    # 执行某个策略后重试当前任务项
    GIVE_UP = "give_up"      # 策略链用尽，放弃当前任务项（继续下一个）
    ABORT = "abort"          # 熔断/致命，中止整个任务


@dataclass
class StepResult:
    """策略执行结果。

    solved=True 表示处置后「可能」已恢复（控制层应重新检测场景确认）；
    solved=False 表示本次处置无效，Policy 推进到链上下一步。
    """

    solved: bool
    detail: str = ""
    data: dict = field(default_factory=dict)
    # 策略输出的冷却时长（秒）：策略只「输出」冷却、不执行冷却（等待由
    # 控制层 chokepoint 统一做）；cooldown 非空时策略保证自己没有为
    # 这段时长等待过。
    cooldown: float | None = None


@runtime_checkable
class Strategy(Protocol):
    """策略协议：run(ctx) -> StepResult。"""

    name: str

    def run(self, ctx) -> StepResult:
        ...
