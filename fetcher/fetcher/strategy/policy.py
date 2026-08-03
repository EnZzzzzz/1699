# -*- coding: utf-8 -*-
"""Policy：Scenario -> 策略链 的声明式策略表 + AttemptTracker。

策略表是数据不是代码：用 Python dict 声明（不用 YAML），支持
站点级/任务级覆盖（with_overrides 按场景整条替换）。

链条目形式：
    ("策略名", 最大尝试次数)   —— 次数用尽推进到下一条
    ("give_up", None)          —— 终止条目：放弃当前任务项
    ("abort", None)            —— 终止条目：中止整个任务
链自然走完（无终止条目）等同于 give_up。

熔断（circuit breaker）独立于策略链：连续失败（策略执行后仍未恢复）
达到 max_consecutive_fail 次时，decide 直接返回 ABORT —— 与旧引擎的
--max-consecutive-fail 行为一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fetcher.core.errors import CircuitBreakerTripped
from fetcher.core.types import Scenario
from fetcher.strategy.base import PolicyAction
from fetcher.strategy.strategies import default_strategies

# 终止条目名（不是策略，由 Policy 直接翻译为 PolicyAction）
TERMINAL_GIVE_UP = "give_up"
TERMINAL_ABORT = "abort"
TERMINALS = (TERMINAL_GIVE_UP, TERMINAL_ABORT)

# ---------- 默认策略表 ----------
# 语义对齐旧引擎的风控状态机（原地休息 → 修复换 IP → 放弃）与
# 网络故障退避重试，差异见 docs/design.md 的取舍说明。
DEFAULT_POLICY_TABLE = {
    # 网络卡/页面没加载出来：先便宜地刷新，再换 IP
    Scenario.NET_STALL: [("refresh", 2), ("swap_ip", 3), (TERMINAL_GIVE_UP, None)],
    # 代理隧道层错误（请求没到目标站）：退避重试为主，换 IP 兜底
    Scenario.NET_ERROR: [("backoff_sleep", 5), ("swap_ip", 2), (TERMINAL_GIVE_UP, None)],
    # 浏览器死亡：与风控无关，直接重启；重不起来中止整个任务
    Scenario.BROWSER_DEAD: [("relaunch_browser", 3), (TERMINAL_ABORT, None)],
    # 整页滑块：自动过证 → 原地休息 → 换 IP → 放弃
    Scenario.RISK_SLIDER_PAGE: [("solve_slider", 3), ("block_rest", 1),
                                ("swap_ip", 2), (TERMINAL_GIVE_UP, None)],
    # 内嵌滑块：自动过证 → 有头模式等人工 → 换 IP → 放弃
    Scenario.RISK_SLIDER_EMBED: [("solve_slider", 3), ("wait_human_verify", 1),
                                 ("swap_ip", 2), (TERMINAL_GIVE_UP, None)],
    # 登录墙（最高级风控）：有头等人工登录 → 烧毁身份+换 IP → 放弃。
    # wait_human_login 在无头模式 SKIPPED（solved=False），自然落到下一条，
    # 与旧引擎「无头模式登录墙不原地休息，直接修复换 IP」行为一致。
    Scenario.RISK_LOGIN: [("wait_human_login", 1), ("clear_identity_swap", 2),
                          (TERMINAL_GIVE_UP, None)],
    # 出口 IP 已轮换：重启浏览器按新 identity 重绑 Cookie
    Scenario.IP_ROTATED: [("relaunch_browser", 3), (TERMINAL_ABORT, None)],
    # 页面加载了但内容为空：先刷新，再按软拦截处理
    Scenario.EMPTY: [("refresh", 2), ("block_rest", 1), ("swap_ip", 1),
                     (TERMINAL_GIVE_UP, None)],
}


@dataclass
class PolicyDecision:
    """Policy.decide 的返回值。"""

    action: PolicyAction
    strategy: str | None = None   # action=CONTINUE 时的策略名
    attempt: int = 0              # 该策略的第几次尝试（1 起）
    detail: str = ""


@dataclass
class AttemptTracker:
    """策略链推进状态（每任务项一份，成功/换项时重置）。

    consecutive_fail 跨任务项累计（熔断语义与旧引擎一致：
    连续 N 个任务项都失败 = 被风控盯死，中止整个任务）。
    """

    scenario: Scenario | None = None
    pos: int = 0                  # 当前执行到链上第几条
    used: int = 0                 # 当前条目已用尝试次数
    consecutive_fail: int = 0

    def note_success(self):
        """当前任务项已恢复：链状态与连续失败计数全部清零。"""
        self.scenario = None
        self.pos = 0
        self.used = 0
        self.consecutive_fail = 0

    def note_failure(self):
        """当前任务项最终失败（GIVE_UP 后由控制层调用）。"""
        self.scenario = None
        self.pos = 0
        self.used = 0
        self.consecutive_fail += 1


class Policy:
    """声明式策略表：Scenario -> [(strategy, max_attempts), ...]。"""

    def __init__(self, table: dict | None = None, strategies: dict | None = None,
                 max_consecutive_fail: int = 5):
        self.strategies = strategies if strategies is not None else default_strategies()
        self.max_consecutive_fail = max_consecutive_fail
        self.table = self._normalize(table if table is not None else DEFAULT_POLICY_TABLE)
        self._validate()

    # ---- 声明加载 ----

    @staticmethod
    def _normalize(table: dict) -> dict:
        """接受 Scenario 或字符串键（"net_stall" / "NET_STALL"）。"""
        out = {}
        for k, chain in table.items():
            key = k if isinstance(k, Scenario) else Scenario[k] if k.isupper() \
                else Scenario(k)
            out[key] = [tuple(entry) for entry in chain]
        return out

    def _validate(self):
        for scenario, chain in self.table.items():
            if scenario is Scenario.OK:
                raise ValueError("OK 场景不需要策略链")
            for entry in chain:
                name = entry[0]
                if name in TERMINALS:
                    continue
                if name not in self.strategies:
                    raise KeyError(f"策略表引用了未注册的策略: {name!r}"
                                   f"（场景 {scenario.name}）")

    @classmethod
    def from_dict(cls, table: dict, **kw) -> "Policy":
        """从纯 dict 加载（站点/任务级配置入口）。"""
        return cls(table=table, **kw)

    def with_overrides(self, overrides: dict) -> "Policy":
        """按场景整条替换的覆盖（站点级/任务级），返回新 Policy。"""
        merged = dict(self.table)
        merged.update(self._normalize(overrides))
        return Policy(table=merged, strategies=self.strategies,
                      max_consecutive_fail=self.max_consecutive_fail)

    # ---- 决策 ----

    def decide(self, scenario: Scenario, tracker: AttemptTracker) -> PolicyDecision:
        """对一次场景判定给出下一步动作。"""
        if scenario is Scenario.OK:
            tracker.note_success()
            return PolicyDecision(PolicyAction.CONTINUE, detail="场景正常")

        # 熔断优先于策略链
        if tracker.consecutive_fail >= self.max_consecutive_fail:
            return PolicyDecision(
                PolicyAction.ABORT,
                detail=f"连续失败 {tracker.consecutive_fail} 次，熔断")

        # 场景切换（或首次）：从链头开始
        if tracker.scenario is not scenario:
            tracker.scenario = scenario
            tracker.pos = 0
            tracker.used = 0

        chain = self.table.get(scenario)
        if not chain:
            return PolicyDecision(PolicyAction.GIVE_UP,
                                  detail=f"场景 {scenario.name} 无策略链")

        while tracker.pos < len(chain):
            name, max_attempts = chain[tracker.pos]
            if name == TERMINAL_GIVE_UP:
                return PolicyDecision(PolicyAction.GIVE_UP,
                                      detail="策略链声明放弃")
            if name == TERMINAL_ABORT:
                return PolicyDecision(PolicyAction.ABORT,
                                      detail="策略链声明中止任务")
            if tracker.used < (max_attempts or 1):
                tracker.used += 1
                return PolicyDecision(PolicyAction.CONTINUE, strategy=name,
                                      attempt=tracker.used)
            tracker.pos += 1
            tracker.used = 0

        return PolicyDecision(PolicyAction.GIVE_UP, detail="策略链已用尽")

    def raise_if_tripped(self, tracker: AttemptTracker, reason: str = ""):
        """熔断已触发时抛 CircuitBreakerTripped（控制层在 ABORT 时调用）。"""
        if tracker.consecutive_fail >= self.max_consecutive_fail:
            raise CircuitBreakerTripped(tracker.consecutive_fail, reason)
