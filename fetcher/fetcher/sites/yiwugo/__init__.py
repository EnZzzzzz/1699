# -*- coding: utf-8 -*-
"""义乌购站点插件（第三个站点实现；防护体系与阿里系完全不同）。

差异全部在本目录内：
    - 特征表（passport/captcha.yiwugo.com 域，自研滑块）；
    - csrf 握手替代 mtop 握手（csrfToken Cookie + x-csrf-token 头，
      见 features.py 顶部实测结论）；
    - 任务（search：关键词→商品列表 JSONL；contact：商品 ID→联系方式
      JSONL，联系方式匿名可见）；
    - 策略强度覆盖：自研滑块不吃阿里轨迹回放，去掉 solve_slider，
      直接休息/换 IP。
判定结构、原子、策略、控制循环零改动复用主框架。
"""

from __future__ import annotations

import random
import time

from fetcher.core.types import Scenario
from fetcher.sites.yiwugo.features import (
    HOMEPAGE,
    ensure_csrf_token,
    has_csrf_token,
    make_detectors,
    page_block_reason,
)


class YiwugoPlugin:
    """义乌购站点插件（SitePlugin 协议）。"""

    name = "yiwugo"
    cookie_domain = "yiwugo.com"
    homepage = HOMEPAGE

    # ---- 判断侧 ----

    def detectors(self) -> list:
        return make_detectors()

    def block_reason(self, page) -> str | None:
        return page_block_reason(page)

    # ---- csrf 握手（csrfToken @ yiwugo.com；对应阿里系的 mtop 钩子） ----

    def has_mtop_token(self, page) -> bool:
        """框架通用钩子名沿用 mtop 叫法，义乌购实际是 csrfToken。"""
        return has_csrf_token(page)

    def ensure_mtop_token(self, page, log=None, attempts: int = 2) -> bool:
        return ensure_csrf_token(page, log=log, attempts=attempts)

    # ---- 策略表站点级覆盖 ----
    # 义乌购风控是自研滑块（captcha.yiwugo.com），阿里系轨迹回放
    # （solve_slider）不适用且实测防护极轻：直接原地休息 → 换 IP。
    # 链长 ≤3：单店全链最多 4 次失败计数 < 熔断上限 5，被拦的店走放弃
    # 而不是烧穿熔断中止整个任务。
    policy_overrides = {
        Scenario.RISK_SLIDER_PAGE: [("block_rest", 1), ("swap_ip", 2),
                                    ("give_up", None)],
        Scenario.RISK_SLIDER_EMBED: [("block_rest", 1),
                                     ("wait_human_verify", 1),
                                     ("swap_ip", 1), ("give_up", None)],
    }

    # ---- 任务注册表 ----

    def task_names(self) -> list[str]:
        return ["search", "contact"]

    def make_task(self, name: str, **kw):
        if name == "search":
            from fetcher.sites.yiwugo.search import YiwugoSearchTask
            return YiwugoSearchTask(**kw)
        if name == "contact":
            from fetcher.sites.yiwugo.contact import YiwugoContactTask
            return YiwugoContactTask(**kw)
        raise KeyError(f"未知任务: {name!r}（可选: "
                       f"{', '.join(self.task_names())}）")

    # ---- 会话冷启动软着陆 ----

    def cold_start(self, page, item, log=print) -> None:
        """新会话先逛义乌购首页留真实浏览轨迹（顺带触发 csrfToken 签发）。"""
        try:
            page.goto(self.homepage, wait_until="domcontentloaded",
                      timeout=45000)
            time.sleep(random.uniform(2.0, 4.0))
        except Exception:  # noqa: BLE001
            pass


# 自注册：sites 包自动发现本目录并 import 时生效
from fetcher.sites import register_site  # noqa: E402

register_site("yiwugo", YiwugoPlugin)

__all__ = ["YiwugoPlugin"]
