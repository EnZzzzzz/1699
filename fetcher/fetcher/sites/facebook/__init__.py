# -*- coding: utf-8 -*-
"""Facebook 站点插件。

一期只提供**原子能力**（atoms/facebook.py 的 FetchFbPost：匿名抓群帖
permalink + 联系方式分桶提取），不提供控制层任务（发现层 Google 搜索、
落库循环属于任务编排，二期接入）。

实测依据：docs/channel-research/facebook-groups.md（§4 匿名可用性、
§8 查号分层、§9 PoC 记录）。
"""

from __future__ import annotations

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

    # ---- 判断侧 ----

    def detectors(self) -> list:
        """站点探测器（优先级序）：登录墙 > 频率限制页 > 内嵌验证 > 空页。"""
        return make_detectors()

    def block_reason(self, page) -> str | None:
        """「是否被拦」的统一口径（含登录墙与空白页）。"""
        return page_block_reason(page)

    # ---- 任务注册表（一期无控制层任务）----

    def task_names(self) -> list[str]:
        return []

    def make_task(self, name: str):
        raise KeyError(f"facebook 插件暂不提供任务: {name!r}"
                       "（一期仅原子能力 fetch_fb_post）")


# 自注册：sites 包自动发现本目录并 import 时生效
from fetcher.sites import register_site  # noqa: E402

register_site("facebook", FacebookPlugin)

__all__ = ["FacebookPlugin"]
