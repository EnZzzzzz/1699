# -*- coding: utf-8 -*-
"""strategy：策略层（包装原子，按声明式策略表处置场景）。"""

from fetcher.strategy.base import PolicyAction, StepResult, Strategy
from fetcher.strategy.policy import (
    DEFAULT_POLICY_TABLE,
    AttemptTracker,
    Policy,
    PolicyDecision,
)
from fetcher.strategy.strategies import (
    BackoffSleepStrategy,
    BlockRestStrategy,
    ClearIdentitySwapIPStrategy,
    RefreshStrategy,
    RelaunchBrowserStrategy,
    SleepStrategy,
    SolveSliderStrategy,
    SwapIPStrategy,
    WaitHumanLoginStrategy,
    WaitHumanVerifyStrategy,
    default_strategies,
)

__all__ = [
    "AttemptTracker",
    "BackoffSleepStrategy",
    "BlockRestStrategy",
    "ClearIdentitySwapIPStrategy",
    "DEFAULT_POLICY_TABLE",
    "Policy",
    "PolicyAction",
    "PolicyDecision",
    "RefreshStrategy",
    "RelaunchBrowserStrategy",
    "SleepStrategy",
    "SolveSliderStrategy",
    "StepResult",
    "Strategy",
    "SwapIPStrategy",
    "WaitHumanLoginStrategy",
    "WaitHumanVerifyStrategy",
    "default_strategies",
]
