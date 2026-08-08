# -*- coding: utf-8 -*-
"""Facebook 站点插件。

一期只提供**原子能力**（atoms/facebook.py 的 FetchFbPost：匿名抓群帖
permalink + 联系方式分桶提取），不提供控制层任务（发现层 Google 搜索、
落库循环属于任务编排，二期接入）。

实测依据：docs/channel-research/facebook-groups.md（§4 匿名可用性、
§8 查号分层、§9 PoC 记录）。
"""

from __future__ import annotations

from fetcher.core.types import Scenario
from fetcher.sites.facebook.features import (
    HOMEPAGE,
    make_detectors,
    page_block_reason,
)


class FacebookPlugin:
    """Facebook 站点插件（SitePlugin 协议的判断侧）。"""

    name = "facebook"
    cookie_domain = "facebook.com"   # 匿名抓取不注入 Cookie，仅作协议字段
    homepage = HOMEPAGE              # = https://www.facebook.com/
    # 匿名站点标记（SPEC §7.2）：白板匿名抓取不带 Cookie，直连模式
    # ensure_site 放行空会话启动（非匿名站点维持无 Cookie 硬报错）
    anonymous = True

    # ---- 判断侧 ----

    def detectors(self) -> list:
        """站点探测器（优先级序）：登录墙 > 频率限制页 > 内嵌验证 > 空页。"""
        return make_detectors()

    def block_reason(self, page) -> str | None:
        """「是否被拦」的统一口径（含登录墙与空白页）。"""
        return page_block_reason(page)

    # ---- 策略覆盖 ----

    # FB 匿名抓 permalink 无阿里式滑块：默认策略链里的 solve_slider（轨迹
    # 回放）对它无效，退化为「原地休息 → 换 IP → 放弃」（与 madeinchina
    # 同款退化，sites/madeinchina/__init__.py:53-59）。
    # 链长 ≤3：单帖全链最多 4 次失败计数 < 熔断上限 5，被拦的帖走放弃
    # 而不是烧穿熔断中止整个任务。
    policy_overrides = {
        Scenario.RISK_SLIDER_PAGE: [("block_rest", 1), ("swap_ip", 2),
                                    ("give_up", None)],
        Scenario.RISK_SLIDER_EMBED: [("block_rest", 1), ("swap_ip", 1),
                                     ("give_up", None)],
    }

    # ---- 任务注册表 ----

    def task_names(self) -> list[str]:
        return ["post"]

    def make_task(self, name: str):
        """按名创建任务实例（控制层 Task 协议）。"""
        if name == "post":
            from fetcher.sites.facebook.post_task import FbPostTask
            return FbPostTask()
        raise KeyError(f"未知任务: {name!r}（可选: "
                       f"{', '.join(self.task_names())}）")


# 自注册：sites 包自动发现本目录并 import 时生效
from fetcher.sites import register_site  # noqa: E402

register_site("facebook", FacebookPlugin)

__all__ = ["FacebookPlugin"]
