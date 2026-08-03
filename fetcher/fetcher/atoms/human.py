# -*- coding: utf-8 -*-
"""人工介入原子：WaitHumanVerify / WaitHumanLogin（有头模式专用）。

迁移自 common.wait_manual_unblock / wait_manual_login，去掉 StatusBoard
依赖（状态经由 ctx.log 输出），保留全部行为：
    - 等待期间不发起新请求，只在当前页读状态，不会加重风控；
    - 等待期间每隔 auto_interval 秒顺带自动重试滑块（先刷新拿新鲜滑块），
      与人工操作互不排斥，谁先通过算谁；
    - 不干等原则：自动过证连续 auto_giveup 秒仍未通过则提前结束等待；
    - 登录检测靠 Cookie 增量（登录态标记 / 新增 ≥3 个 Cookie 名）。
"""

from __future__ import annotations

import random
import time

from fetcher.core.errors import browser_alive
from fetcher.core.types import ActionResult, Outcome

# 阿里系登录态 Cookie 标记：登录成功后站点才会签发（匿名会话没有）
LOGIN_COOKIE_MARKERS = ("unb", "lid", "cookie1", "_nk_", "tracknick", "dnk")


def _fmt_dur(sec: float) -> str:
    m, s = divmod(max(0, int(sec)), 60)
    return f"{m:02d}:{s:02d}"


class WaitHumanVerify:
    """等用户在浏览器窗口里手动过滑块/验证（有头模式专用）。

    params = {"seconds": 600, "interval": 30, "auto_solve": True,
              "auto_interval": 90, "auto_giveup": 300}
    block_check 由站点插件提供（ctx.site.block_reason(page)）；
    无站点插件时无法判定，直接 SKIPPED。
    """

    name = "wait_human_verify"
    title = "等待人工过验证"

    def run(self, ctx, params: dict) -> ActionResult:
        if not ctx.headed:
            return ActionResult.skipped("无头模式不支持人工过证")
        page = ctx.page
        if page is None:
            return ActionResult.fatal("无活动页面")
        block_check = getattr(ctx.site, "block_reason", None)
        if block_check is None:
            return ActionResult.skipped("站点插件未提供 block_reason，无法判定")

        seconds = float(params.get("seconds", 600))
        interval = float(params.get("interval", 30))
        auto_interval = float(params.get("auto_interval", 90))
        auto_giveup = float(params.get("auto_giveup", 300))
        auto_solve = None
        if params.get("auto_solve", True) and ctx.config.auto_solve_slider:
            from fetcher.atoms.slider import make_auto_solve  # 延迟导入
            auto_solve = make_auto_solve()

        ctx.log(f"    👉 请在 {ctx.identity} 的浏览器窗口里手动完成验证，"
                f"脚本每 {interval:.0f}s 自动检测（最长 {seconds / 60:.1f} 分钟）"
                f"{'；等待期间周期性自动重试滑块' if auto_solve else ''}...")

        deadline = time.monotonic() + seconds
        start = time.monotonic()
        last_auto = start
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                return ActionResult.blocked("等待超时仍未过证")
            if auto_solve is not None \
                    and time.monotonic() - start >= auto_giveup:
                ctx.log(f"    等待+自动过证 {auto_giveup / 60:.0f} 分钟仍未通过，"
                        f"不干等，转入休息/重试流程")
                return ActionResult.blocked("自动过证连续超时，不干等")
            ctx.log(f"    ...等待手动过验证 剩 {_fmt_dur(remain)}")
            if ctx.wait(min(interval, remain)):
                return ActionResult(Outcome.SKIPPED, "用户中断")
            try:
                if block_check(page) is None:
                    return ActionResult.success("检测到验证已通过")
            except Exception:  # noqa: BLE001
                if not browser_alive(page):
                    return ActionResult.fatal("等待期间浏览器死亡")
                continue
            # 仍在拦截态：距上次自动过证满 auto_interval 秒就再试一轮
            if auto_solve is not None \
                    and time.monotonic() - last_auto >= auto_interval:
                last_auto = time.monotonic()
                try:
                    # 先刷新拿新鲜滑块（陈旧滑块原地回放永远不过）
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    time.sleep(random.uniform(1.5, 3.0))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    ctx.log("    等待期间自动过证重试（已刷新页面）…")
                    if auto_solve(page) and block_check(page) is None:
                        return ActionResult.success("等待期间自动过证成功")
                except Exception as e:  # noqa: BLE001
                    ctx.log(f"    [!] 自动过证重试异常"
                            f"（{type(e).__name__}: {e}），继续等待")


class WaitHumanLogin:
    """等 IP 轮换期间用户是否在当前窗口手动登录（有头模式专用）。

    此时浏览器刚重启过、页面停在新会话首页（不在拦截页上），页面状态
    判定会误判为「已通过」，改为对比 Cookie 增量：出现登录态标记
    （unb/lid/cookie1/_nk_/tracknick/dnk）或相比基线新增 >= 3 个
    Cookie 名即视为已登录。

    params = {"seconds": 600, "interval": 30}
    """

    name = "wait_human_login"
    title = "等待人工登录"

    def run(self, ctx, params: dict) -> ActionResult:
        if not ctx.headed:
            return ActionResult.skipped("无头模式不支持人工登录")
        page = ctx.page
        if page is None:
            return ActionResult.fatal("无活动页面")
        domain = getattr(ctx.site, "cookie_domain", "1688.com") \
            if ctx.site is not None else "1688.com"
        seconds = float(params.get("seconds", 600))
        interval = float(params.get("interval", 30))

        try:
            baseline = {c["name"] for c in page.context.cookies()
                        if domain in c.get("domain", "")}
        except Exception:  # noqa: BLE001
            return ActionResult.fatal("无法读取 Cookie 基线（浏览器异常）")

        ctx.log(f"    👉 等轮换期间你也可以在 {ctx.identity} 的窗口里手动登录，"
                f"脚本每 {interval:.0f}s 检测 Cookie（登录成功立即继续）...")
        deadline = time.monotonic() + seconds
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                return ActionResult.blocked("等待超时未检测到登录")
            ctx.log(f"    ...等 IP 轮换（可手动登录）剩 {_fmt_dur(remain)}")
            if ctx.wait(min(interval, remain)):
                return ActionResult(Outcome.SKIPPED, "用户中断")
            try:
                names = {c["name"] for c in page.context.cookies()
                         if domain in c.get("domain", "")}
            except Exception:  # noqa: BLE001
                return ActionResult.fatal("等待期间浏览器死亡")
            if any(m in names for m in LOGIN_COOKIE_MARKERS):
                return ActionResult.success("检测到登录态 Cookie，已手动登录")
            if len(names - baseline) >= 3:
                return ActionResult.success("Cookie 增量判定为已手动登录")
