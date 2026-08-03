# -*- coding: utf-8 -*-
"""浏览器操作原子：RelaunchBrowser / SaveCookies / CheckIPFresh / ColdStart。"""

from __future__ import annotations

from fetcher.core.errors import BrowserLaunchError, UserInterrupted
from fetcher.core.types import ActionResult


class RelaunchBrowser:
    """重启浏览器（换 IP / 浏览器死亡修复 / IP 轮换重绑通用）。

    params = {"max_retry": None(=config.ip_retry), "keep_seed": True}
    成功后 ctx.session 指向新会话；旧会话 Cookie 已由
    BrowserManager.relaunch 回写。
    """

    name = "relaunch_browser"
    title = "重启浏览器"

    def run(self, ctx, params: dict) -> ActionResult:
        if ctx.browser_manager is None or ctx.session is None:
            return ActionResult.fatal("未装配 browser_manager / session")
        try:
            old_identity = ctx.session.identity
            session = ctx.browser_manager.relaunch(
                ctx.session,
                max_retry=params.get("max_retry"),
                seed_kit=("__keep__" if params.get("keep_seed", True) else None),
                stop=ctx.stop)
            ctx.session = session
            ctx.state["warm"] = True  # 新会话需重新冷启动软着陆
            rotated = session.identity != old_identity
            return ActionResult.success(
                f"浏览器已重启，出口 {old_identity} -> {session.identity}",
                identity=session.identity, rotated=rotated)
        except UserInterrupted:
            return ActionResult.skipped("用户中断")
        except BrowserLaunchError as e:
            return ActionResult.fatal(str(e))
        except Exception as e:  # noqa: BLE001
            ctx.last_error = e
            return ActionResult.fatal(f"重启浏览器异常: {e}")


class SaveCookies:
    """把浏览器最新 Cookie（含新 x5sec）写回当前 identity 名下。

    每次过证/抓取成功/退出前调用，保证进程意外退出也不丢信任链。
    """

    name = "save_cookies"
    title = "回写 Cookie"

    def run(self, ctx, params: dict) -> ActionResult:
        if ctx.browser_manager is None or ctx.session is None:
            return ActionResult.fatal("未装配 browser_manager / session")
        try:
            n = ctx.browser_manager.save_cookies(ctx.session)
            return ActionResult.success(f"已回写 {n} 个 Cookie", count=n)
        except Exception as e:  # noqa: BLE001
            # 回写失败不阻断主流程（与旧版一致，仅降级为日志）
            ctx.log(f"    [!] Cookie 回写失败: {e}")
            return ActionResult.success(f"回写失败（不阻断）: {e}")


class CheckIPFresh:
    """出口 IP 保鲜检查（青果 30 分钟轮换检测）。

    返回 OK = IP 未轮换；BLOCKED = 已轮换/隧道失效（data["rotated"]=True，
    控制层/策略层据此走 IP_ROTATED 场景）。
    """

    name = "check_ip_fresh"
    title = "出口 IP 保鲜检查"

    def run(self, ctx, params: dict) -> ActionResult:
        if not ctx.config.use_proxy:
            return ActionResult.success("直连模式无需检查")
        if ctx.browser_manager is None or ctx.session is None:
            return ActionResult.fatal("未装配 browser_manager / session")
        need, cur_ip, reason = ctx.browser_manager.check_ip_fresh(ctx.session)
        if need:
            return ActionResult.blocked(reason, rotated=True, cur_ip=cur_ip)
        return ActionResult.success(f"出口 IP 有效（{cur_ip}）", cur_ip=cur_ip)


class ColdStart:
    """新会话冷启动软着陆（留下真实浏览轨迹）。

    新会话一上来就深链目标页是明显的爬虫特征。具体逛什么由站点插件
    的 cold_start(page, item, log) 决定；无站点插件时退化为访问其
    homepage。
    """

    name = "cold_start"
    title = "冷启动软着陆"

    def run(self, ctx, params: dict) -> ActionResult:
        page = ctx.page
        if page is None:
            return ActionResult.fatal("无活动页面")
        item = ctx.state.get("item")
        try:
            if ctx.site is not None:
                ctx.site.cold_start(page, item, log=ctx.log)
            ctx.state["warm"] = False
            return ActionResult.success("冷启动完成")
        except Exception as e:  # noqa: BLE001
            # 冷启动失败不阻断（与旧版一致）
            ctx.log(f"    [!] 冷启动软着陆异常（不阻断）: {e}")
            ctx.state["warm"] = False
            return ActionResult.success(f"冷启动异常（不阻断）: {e}")
