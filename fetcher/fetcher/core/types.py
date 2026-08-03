# -*- coding: utf-8 -*-
"""核心协议类型：Scenario 枚举、Outcome、ActionResult。

判断与行动分离的公共语言：
    - Detector 只产出 Scenario（绝不动浏览器）；
    - Atom / Strategy 只产出 ActionResult（绝不自己做检测）；
    - Policy 把 Scenario 映射为策略链（声明式数据）。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Scenario(enum.Enum):
    """场景判断结果（Detector 的唯一输出）。

    OK                  页面正常，可继续采集
    EMPTY               页面加载了但内容为空（可能是正常空页，也可能是软拦截）
    NET_STALL           网络卡 / 页面没加载出来（浏览器活着，请求挂了）
    NET_ERROR           代理隧道层错误（Chromium net::ERR_*，请求没到目标站）
    BROWSER_DEAD        浏览器进程死亡 / 会话被服务端关闭
    RISK_SLIDER_PAGE    整页滑块跳转（URL/文本命中风控特征）
    RISK_SLIDER_EMBED   内嵌滑块（滑块组件与页面内容同屏）
    RISK_LOGIN          登录墙（被强制跳登录）
    IP_ROTATED          出口 IP 已轮换（Cookie 与出口错配，需重绑）
    """

    OK = "ok"
    EMPTY = "empty"
    NET_STALL = "net_stall"
    NET_ERROR = "net_error"
    BROWSER_DEAD = "browser_dead"
    RISK_SLIDER_PAGE = "risk_slider_page"
    RISK_SLIDER_EMBED = "risk_slider_embed"
    RISK_LOGIN = "risk_login"
    IP_ROTATED = "ip_rotated"


class Outcome(enum.Enum):
    """原子执行结果分类（参考 docs/flow-architecture.md 的 AtomResult）。"""

    OK = "ok"
    EMPTY = "empty"
    BLOCKED = "blocked"        # 执行中发现仍处于/进入风控拦截态
    NET_ERROR = "net_error"    # 网络/代理层错误
    FATAL = "fatal"            # 浏览器进程级致命错误
    SKIPPED = "skipped"        # 条件不满足未执行（如无头模式下的人工过证）


@dataclass
class ActionResult:
    """原子/策略的统一返回值。"""

    outcome: Outcome
    detail: str = ""
    data: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.OK

    # ---- 便捷构造 ----
    @classmethod
    def success(cls, detail: str = "", **data) -> "ActionResult":
        return cls(Outcome.OK, detail, data)

    @classmethod
    def blocked(cls, detail: str = "", **data) -> "ActionResult":
        return cls(Outcome.BLOCKED, detail, data)

    @classmethod
    def net_error(cls, detail: str = "", **data) -> "ActionResult":
        return cls(Outcome.NET_ERROR, detail, data)

    @classmethod
    def fatal(cls, detail: str = "", **data) -> "ActionResult":
        return cls(Outcome.FATAL, detail, data)

    @classmethod
    def empty(cls, detail: str = "", **data) -> "ActionResult":
        return cls(Outcome.EMPTY, detail, data)

    @classmethod
    def skipped(cls, detail: str = "", **data) -> "ActionResult":
        return cls(Outcome.SKIPPED, detail, data)
