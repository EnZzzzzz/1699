# -*- coding: utf-8 -*-
"""策略实现：每个策略包装一个（或组合几个）原子。

策略与原子的区别：原子是「做一件事」的能力单元；策略是面向场景的
处置语义（可能组合多个原子，如 ClearIdentitySwapIP = 烧毁身份 +
重启浏览器换 IP 一气呵成）。
"""

from __future__ import annotations

import random

from fetcher.atoms.browser_ops import RelaunchBrowser, SaveCookies
from fetcher.atoms.human import WaitHumanLogin, WaitHumanVerify
from fetcher.atoms.identity_ops import ClearIdentity
from fetcher.atoms.refresh import Refresh
from fetcher.atoms.sleep import human_pause_duration
from fetcher.atoms.slider import SolveSlider
from fetcher.core.types import Outcome
from fetcher.strategy.base import StepResult


class _AtomStrategy:
    """把单个原子包装成策略的基类（params 由策略固定或取默认值）。"""

    name = ""
    atom_cls = None
    params: dict = {}

    def __init__(self, **params):
        self._params = {**self.params, **params}
        self._atom = self.atom_cls()

    def run(self, ctx) -> StepResult:
        ctx.state["attempt"] = ctx.state.get("attempt", 1)
        result = self._atom.run(ctx, self._params)
        solved = result.outcome is Outcome.OK
        return StepResult(solved=solved, detail=result.detail, data=result.data)


class SleepStrategy:
    """拟人随机等待：只算时长输出冷却，不自己等待（等待由控制层执行）。

    时长分布与 Sleep 原子同款（对数正态，截断 [min*0.5, max*5]），
    取参路径一致：min/max 来自 params，缺省 2.0/5.0。
    """

    name = "sleep"

    def __init__(self, **params):
        self._params = params

    def run(self, ctx) -> StepResult:
        lo = float(self._params.get("min", 2.0))
        hi = float(self._params.get("max", 5.0))
        t = human_pause_duration(lo, hi)
        ctx.log(f"    ...随机等待 {t:.1f}s")
        return StepResult(True, f"等待 {t:.1f}s", cooldown=t)


class BackoffSleepStrategy:
    """网络层错误的退避等待（base=30, cap=180，与旧引擎一致）。

    只算时长输出冷却，不自己等待（等待由控制层执行）。
    """

    name = "backoff_sleep"
    params = {"base": 30, "cap": 180}

    def __init__(self, **params):
        self._params = {**self.params, **params}

    def run(self, ctx) -> StepResult:
        base = float(self._params.get("base", 30.0))
        cap = float(self._params.get("cap", 180.0))
        attempt = self._params.get("attempt") or ctx.state.get("attempt", 1)
        t = min(base * int(attempt), cap)
        ctx.log(f"    ...退避等待 {t:.0f}s（第 {attempt} 次）")
        return StepResult(True, f"退避 {t:.0f}s", cooldown=t)


class BlockRestStrategy:
    """风控原地休息：当前 IP 上长休息后再试（block_rest_min~max）。

    时长在 run 时从 ctx.config 取，保证任务级覆盖生效；分布与 Sleep
    同款（对数正态）。只算时长输出冷却，不自己等待（等待由控制层执行）。
    """

    name = "block_rest"

    def __init__(self, **params):
        self._params = params

    def run(self, ctx) -> StepResult:
        lo = float(ctx.config.block_rest_min)
        hi = float(ctx.config.block_rest_max)
        ctx.log(f"    ⚠ 风控休息：保持当前 IP {ctx.identity}，"
                f"休息 {lo / 60:.0f}~{hi / 60:.0f} 分钟后重试")
        t = human_pause_duration(lo, hi)
        return StepResult(True, f"等待 {t:.1f}s", cooldown=t)


class RefreshStrategy(_AtomStrategy):
    name = "refresh"
    atom_cls = Refresh


class SolveSliderStrategy(_AtomStrategy):
    name = "solve_slider"
    atom_cls = SolveSlider


class RelaunchBrowserStrategy(_AtomStrategy):
    """重启浏览器（浏览器死亡修复 / IP 轮换重绑）。"""
    name = "relaunch_browser"
    atom_cls = RelaunchBrowser


class SwapIPStrategy:
    """换 IP：重启浏览器绑定新出口 IP（通道不变，靠出口轮换/重连）。

    冷却例外：内部等待夹在两次 relaunch 之间，不迁移（SPEC §2.2，P3 重议）。

    迁移旧引擎 block_stage==1 的完整逻辑：
        1. 重启浏览器（旧 Cookie 先回写）；
        2. 出口尚未轮换（青果 30 分钟时效，identity 没变）：休息一轮
           等其过期（有头模式期间可人工登录，登录成功立即算解决），
           再重启一次绑定新 IP；
        3. 两步都成功即 solved（是否真换到 IP 由 data["rotated"] 标注）。
    """

    name = "swap_ip"

    def __init__(self, **params):
        self._params = params

    def run(self, ctx) -> StepResult:
        if ctx.browser_manager is None or ctx.session is None:
            return StepResult(False, "未装配 browser_manager / session")
        old_identity = ctx.session.identity
        result = RelaunchBrowser().run(ctx, self._params)
        if result.outcome is Outcome.SKIPPED:
            return StepResult(False, "用户中断")
        if result.outcome is not Outcome.OK:
            return StepResult(False, result.detail, result.data)
        if result.data.get("rotated") or not ctx.config.use_proxy:
            return StepResult(True, result.detail, result.data)

        # 出口还没轮换（休息不足 30 分钟）：再等一轮让青果轮换
        rest = random.uniform(ctx.config.block_rest_min,
                              ctx.config.block_rest_max)
        ctx.log(f"    [!] 出口 IP 尚未轮换（青果 30 分钟时效），"
                f"再休息 {rest / 60:.1f} 分钟等其过期后重试")
        if ctx.headed:
            # 有头模式：等轮换期间轮询用户是否手动登录（Cookie 增量检测），
            # 登录成功立即继续，不必等轮换
            login = WaitHumanLogin().run(ctx, {"seconds": rest})
            if login.outcome is Outcome.OK:
                SaveCookies().run(ctx, {})
                return StepResult(True, f"等轮换期间手动登录成功: {login.detail}")
            if login.outcome is Outcome.SKIPPED:
                return StepResult(False, "用户中断")
        elif ctx.wait(rest):
            return StepResult(False, "用户中断")
        result2 = RelaunchBrowser().run(ctx, self._params)
        if result2.outcome is Outcome.OK:
            return StepResult(True, result2.detail, result2.data)
        if result2.outcome is Outcome.SKIPPED:
            return StepResult(False, "用户中断")
        return StepResult(False, result2.detail, result2.data)


class WaitHumanVerifyStrategy(_AtomStrategy):
    name = "wait_human_verify"
    atom_cls = WaitHumanVerify


class WaitHumanLoginStrategy(_AtomStrategy):
    name = "wait_human_login"
    atom_cls = WaitHumanLogin


class ClearIdentitySwapIPStrategy:
    """登录墙处置组合：烧毁当前身份（清空 Cookie）→ 重启浏览器换 IP。

    登录墙 = 会话身份被最高级标记，旧 Cookie 留着只会让轮换回来的
    IP 复活已烧毁的会话，必须先清空再换 IP。
    """

    name = "clear_identity_swap"

    def __init__(self, **params):
        self._params = params

    def run(self, ctx) -> StepResult:
        clear = ClearIdentity().run(ctx, {})
        relaunch = RelaunchBrowser().run(ctx, self._params)
        solved = relaunch.outcome is Outcome.OK
        return StepResult(solved=solved,
                          detail=f"{clear.detail}; {relaunch.detail}",
                          data={**clear.data, **relaunch.data})


def default_strategies() -> dict:
    """策略注册表：策略名 -> Strategy 实例（Policy 按名解析）。"""
    instances = [
        SleepStrategy(),
        BackoffSleepStrategy(),
        BlockRestStrategy(),
        RefreshStrategy(),
        SolveSliderStrategy(),
        RelaunchBrowserStrategy(),
        SwapIPStrategy(),
        WaitHumanVerifyStrategy(),
        WaitHumanLoginStrategy(),
        ClearIdentitySwapIPStrategy(),
    ]
    return {s.name: s for s in instances}
