# -*- coding: utf-8 -*-
"""1688 站点插件：风控特征表 + 探测器 + mtop 握手 + 任务注册表。

任务（采什么）：
    contact  联系人抓取（消费 shops 表 pending 店铺）
    shop     店铺 URL 采集（商品搜索 offer_search → shops 表）
    company  公司黄页采集（company_search → shops 表）
"""

from __future__ import annotations

import random
import time

from fetcher.sites.alibaba1688.features import (
    HOMEPAGE,
    ensure_mtop_token,
    has_mtop_token,
    make_detectors,
    page_block_reason,
)


class Alibaba1688Plugin:
    """1688 站点插件（SitePlugin 协议的第一个实现）。"""

    name = "alibaba1688"
    cookie_domain = "1688.com"
    homepage = HOMEPAGE

    # ---- 判断侧 ----

    def detectors(self) -> list:
        """站点探测器（优先级序）：登录墙 > 整页滑块 > 内嵌滑块 > 空页。"""
        return make_detectors()

    def block_reason(self, page) -> str | None:
        """「是否被拦/已过证」的统一口径（含登录墙与空白页）。"""
        return page_block_reason(page)

    # ---- mtop 握手（搜索域入场券） ----

    def has_mtop_token(self, page) -> bool:
        return has_mtop_token(page)

    def ensure_mtop_token(self, page, log=None, attempts: int = 2) -> bool:
        return ensure_mtop_token(page, log=log, attempts=attempts)

    # ---- 任务注册表 ----

    def task_names(self) -> list[str]:
        return ["contact", "shop", "company"]

    def make_task(self, name: str):
        """按名创建任务实例（控制层 Task 协议）。"""
        if name == "contact":
            from fetcher.sites.alibaba1688.contact import ContactTask
            return ContactTask()
        if name == "shop":
            from fetcher.sites.alibaba1688.shop import ShopTask
            return ShopTask()
        if name == "company":
            from fetcher.sites.alibaba1688.company import CompanyTask
            return CompanyTask()
        raise KeyError(f"未知任务: {name!r}（可选: "
                       f"{', '.join(self.task_names())}）")

    # ---- 会话冷启动软着陆（原子 ColdStart 的默认实现） ----

    def cold_start(self, page, item, log=print) -> None:
        """新会话先逛店铺首页（或站点首页）留真实浏览轨迹，再进深链页。"""
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

register_site("1688", Alibaba1688Plugin)

__all__ = ["Alibaba1688Plugin"]
