# -*- coding: utf-8 -*-
"""中国制造网(cn.made-in-china.com) 站点插件。

任务（采什么）：
    contact  联系方式采集（消费 shops 表 pending 店铺 → showroom
             {sub}-contact.html → meta description 手机号 → contacts 表）
    shop     供应商展厅 URL 采集（行业市场 market 分页页 → shops 表）

与 1688 插件的差异：
    - 无 mtop/csrf 握手（免登录、纯静态联系方式页，不经 API），不提供
      has_mtop_token / ensure_mtop_token 钩子
    - 反爬是 vemic FCaptcha，不吃阿里轨迹回放 → policy_overrides 去掉
      solve_slider，退化为「原地休息 → 换 IP（+有头人工验证）」
"""

from __future__ import annotations

import random
import time

from fetcher.core.types import Scenario
from fetcher.sites.madeinchina.features import (
    HOMEPAGE,
    make_detectors,
    page_block_reason,
)


class MadeInChinaPlugin:
    """中国制造网站点插件（SitePlugin 协议）。"""

    name = "madeinchina"
    cookie_domain = "made-in-china.com"   # 覆盖 cn.* 与 {sub}.cn.* 两级域
    homepage = HOMEPAGE                   # = https://cn.made-in-china.com/

    # ---- 判断侧 ----

    def detectors(self) -> list:
        """站点探测器（优先级序）：登录墙 > 整页滑块 > 内嵌滑块 > 空页。"""
        return make_detectors()

    def block_reason(self, page) -> str | None:
        """「是否被拦/已过证」的统一口径（含登录墙与空白页）。"""
        return page_block_reason(page)

    # ---- 策略覆盖 ----

    # vemic 是 FCaptcha（点击/验证类），不是阿里滑块：默认策略链里的
    # solve_slider（轨迹回放）对它无效，退化为「休息 → 换 IP（+人工验证）」
    # —— 与实测「慢速 + 带验证 cookie 的会话可批量拉」一致。
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
        return ["shop", "contact"]

    def make_task(self, name: str):
        """按名创建任务实例（控制层 Task 协议）。"""
        if name == "shop":
            from fetcher.sites.madeinchina.shop import MadeInChinaShopTask
            return MadeInChinaShopTask()
        if name == "contact":
            from fetcher.sites.madeinchina.contact import (
                MadeInChinaContactTask,
            )
            return MadeInChinaContactTask()
        raise KeyError(f"未知任务: {name!r}（可选: "
                       f"{', '.join(self.task_names())}）")

    # ---- 会话冷启动软着陆 ----

    def cold_start(self, page, item, log=print) -> None:
        """新会话先逛展厅首页（或站点首页）留真实浏览轨迹，再进深链页。"""
        try:
            domain = item["domain"] if isinstance(item, dict) else getattr(
                item, "domain", None)
            url = f"https://{domain}/" if domain else self.homepage
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(random.uniform(2.0, 5.0))
        except Exception:  # noqa: BLE001
            pass  # 首页打不开不阻断，照常走抓取流程


# 自注册：sites 包自动发现本目录并 import 时生效
from fetcher.sites import register_site  # noqa: E402

register_site("madeinchina", MadeInChinaPlugin)

__all__ = ["MadeInChinaPlugin"]
