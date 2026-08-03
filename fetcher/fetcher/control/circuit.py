# -*- coding: utf-8 -*-
"""CircuitBreaker：连续失败熔断（worker 级）。

对应旧引擎的 consecutive_fail / --max-consecutive-fail：连续 N 个
「风控类失败」判定被风控盯死，中止整个任务。网络层错误
（NET_ERROR / BROWSER_DEAD / IP_ROTATED）与风控无关，不计数；
任务项成功即清零。

与 Policy 内置的 max_consecutive_fail 检查并存：CircuitBreaker 在
场景判定当下立即熔断（与旧引擎同点位），Policy 的检查是策略链层面
的兜底。
"""

from __future__ import annotations

from fetcher.core.types import Scenario

# 计入熔断的场景（对应旧版「抓取失败或疑似被风控拦截」分支：
# 风控三兄弟 + 空白页 + 网络卡（旧版 goto 超时返回 None 按风控计））
CIRCUIT_SCENARIOS = frozenset({
    Scenario.RISK_SLIDER_PAGE,
    Scenario.RISK_SLIDER_EMBED,
    Scenario.RISK_LOGIN,
    Scenario.EMPTY,
    Scenario.NET_STALL,
})


class CircuitBreaker:
    """连续失败计数器；note_failure 返回 True 表示已达熔断上限。"""

    def __init__(self, limit: int = 5):
        self.limit = limit
        self.count = 0

    @property
    def tripped(self) -> bool:
        return self.count >= self.limit

    def note_success(self):
        self.count = 0

    def counts(self, scenario: Scenario) -> bool:
        """该场景是否计入熔断计数。"""
        return scenario in CIRCUIT_SCENARIOS

    def note_failure(self, scenario: Scenario | None = None) -> bool:
        """记一次失败；返回 True = 熔断。scenario 给出且不计数时原样返回。"""
        if scenario is not None and not self.counts(scenario):
            return False
        self.count += 1
        return self.tripped

    def check(self) -> None:
        """已熔断则抛 CircuitBreakerTripped。"""
        from fetcher.core.errors import CircuitBreakerTripped
        if self.tripped:
            raise CircuitBreakerTripped(self.count)
