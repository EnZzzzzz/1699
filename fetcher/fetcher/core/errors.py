# -*- coding: utf-8 -*-
"""错误类型与错误分级（迁移自 scraper/taobao_1688/common.py）。

错误分级是场景判断的输入之一：
    - 网络/代理层错误（NET_ERROR）：请求没到目标站，与风控无关，
      不应计入风控连续失败计数；
    - 浏览器进程级致命错误（BROWSER_DEAD）：会话被服务端关闭/崩溃，
      必须重启浏览器，误当风控处理会在死浏览器上空等；
    - 其余异常（多为 goto 超时）：浏览器活着 = 网络卡/页面挂起
      （NET_STALL），浏览器死了 = BROWSER_DEAD。
"""

from __future__ import annotations


# ---------- 包自有异常 ----------

class FetcherError(Exception):
    """fetcher 包异常基类。"""


class CircuitBreakerTripped(FetcherError):
    """连续失败达到熔断上限，控制层应中止整个任务。"""

    def __init__(self, count: int, reason: str = ""):
        self.count = count
        self.reason = reason
        super().__init__(f"已连续失败 {count} 次（{reason}），熔断中止任务")


class BrowserLaunchError(FetcherError):
    """浏览器启动失败（含席位等待超时、二进制退出、出口 IP 查询失败）。"""


class LicenseSeatTimeout(BrowserLaunchError):
    """等待 CloakBrowser 会话席位超时仍满员。"""


class ExitIPError(BrowserLaunchError):
    """经代理通道查询出口 IP 失败（隧道疑似不可用，无法绑定 Cookie identity）。"""


class UserInterrupted(FetcherError):
    """收到停止信号（用户中断 / SIGTERM / SIGHUP）。"""


# ---------- 错误分级（行为与 common.py 完全一致） ----------

# 网络/代理层错误特征（Chromium net 错误码）。
NETWORK_ERR_MARKERS = (
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_TIMED_OUT",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_SOCKET_NOT_CONNECTED",
    "ERR_ADDRESS_UNREACHABLE",
    "ERR_NETWORK_CHANGED",
    "ERR_HTTP2_PROTOCOL_ERROR",
    "net::ERR",  # 兜底：所有 Chromium 网络层错误都先按网络故障处理
)


def is_network_error(err) -> bool:
    """判断异常是否属于网络/代理层错误（与目标站风控无关）。"""
    s = str(err or "")
    return any(m in s for m in NETWORK_ERR_MARKERS)


# 浏览器进程级致命错误特征（与目标站风控完全无关）。
FATAL_ERR_MARKERS = (
    "Target closed",
    "TargetClosedError",
    "has been closed",   # "Target page, context or browser has been closed"
    "Target crashed",
    "Browser closed",
    "Connection closed",
)


def is_fatal_browser_error(err) -> bool:
    """判断异常是否属于浏览器进程死亡/被关闭（应重启浏览器，非风控）。"""
    s = str(err or "")
    return any(m in s for m in FATAL_ERR_MARKERS)


def browser_alive(page) -> bool:
    """探测浏览器/页面是否还活着（goto 超时后鉴别死浏览器 vs 页面挂起）。"""
    try:
        b = page.context.browser
        return bool(b and b.is_connected()) and not page.is_closed()
    except Exception:  # noqa: BLE001
        return False


def classify_error(err, page=None) -> str:
    """把一次抓取异常分级为 Scenario 值（字符串），供 Detector 使用。

    返回 "fatal" / "net_error" / "net_stall"：
        1) 命中致命特征 → fatal；
        2) 命中网络特征 → net_error；
        3) 其他异常（多为 goto 超时）：浏览器已死 → fatal，否则 net_stall。
    """
    if is_fatal_browser_error(err):
        return "fatal"
    if is_network_error(err):
        return "net_error"
    if page is not None and not browser_alive(page):
        return "fatal"
    return "net_stall"
