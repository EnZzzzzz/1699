# -*- coding: utf-8 -*-
"""身份操作原子：ClearIdentity（登录墙烧毁清空 Cookie）。"""

from __future__ import annotations

from fetcher.core.types import ActionResult


class ClearIdentity:
    """清空当前 identity 名下的全部 Cookie。

    登录墙 = 会话身份被最高级标记：清空该 IP 名下的 Cookie，避免代理
    把此 IP 轮换回来时复活已烧毁的会话（迁移自引擎的登录墙处理段）。
    直连身份（direct）不清空 —— 直连 Cookie 是本机签发的，登录墙
    时应由人工处理而不是烧毁本机身份。
    """

    name = "clear_identity"
    title = "清空身份 Cookie"

    def run(self, ctx, params: dict) -> ActionResult:
        if ctx.store is None:
            return ActionResult.fatal("未装配 identity store")
        identity = ctx.identity
        if identity == "direct":
            return ActionResult.skipped("直连身份不清空（由人工处理）")
        try:
            n = ctx.store.burn(identity)
            ctx.log(f"    🧹 登录墙标记：已清空 {identity} 名下的 {n} 条 Cookie"
                    f"（会话身份已烧毁，此 IP 轮换回来时按全新身份重建）")
            return ActionResult.success(f"已清空 {n} 条 Cookie", count=n)
        except Exception as e:  # noqa: BLE001
            return ActionResult.blocked(f"清空登录墙 IP Cookie 失败: {e}")
