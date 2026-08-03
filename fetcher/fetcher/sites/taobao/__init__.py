# -*- coding: utf-8 -*-
"""淘宝站点插件（第二个站点实现，验证框架扩展性）。

与 1688 的差异全部在本目录内：
    - 特征表（login.taobao.com / sec.taobao.com / taobao.com 域）；
    - 任务（search：内存关键词队列 + JSONL 落盘，不碰 1688 库）；
    - 策略强度覆盖（policy_overrides，演示 with_overrides）。
判定结构、mtop 握手、原子、策略、控制循环零改动复用主框架。
"""

from __future__ import annotations

import random
import time

from fetcher.core.types import Scenario
from fetcher.sites.taobao.features import (
    HOMEPAGE,
    ensure_mtop_token,
    has_mtop_token,
    make_detectors,
    page_block_reason,
)


class TaobaoPlugin:
    """淘宝站点插件（SitePlugin 协议）。"""

    name = "taobao"
    cookie_domain = "taobao.com"
    homepage = HOMEPAGE

    # ---- 判断侧 ----

    def detectors(self) -> list:
        return make_detectors()

    def block_reason(self, page) -> str | None:
        return page_block_reason(page)

    # ---- mtop 握手（_m_h5_tk @ taobao.com，与 1688 同机制不同域） ----

    def has_mtop_token(self, page) -> bool:
        return has_mtop_token(page)

    def ensure_mtop_token(self, page, log=None, attempts: int = 2) -> bool:
        return ensure_mtop_token(page, log=log, attempts=attempts)

    # ---- 策略表站点级覆盖（演示 with_overrides）----
    # 淘宝搜索页滑块比 1688 更顽固（同族经验）：过证尝试加码、
    # 换 IP 次数加码；登录墙/网络层处置与 1688 相同不覆盖。
    policy_overrides = {
        Scenario.RISK_SLIDER_PAGE: [("solve_slider", 5), ("block_rest", 1),
                                    ("swap_ip", 3), ("give_up", None)],
        Scenario.RISK_SLIDER_EMBED: [("solve_slider", 5),
                                     ("wait_human_verify", 1),
                                     ("swap_ip", 3), ("give_up", None)],
    }

    # ---- 任务注册表 ----

    def task_names(self) -> list[str]:
        return ["search"]

    def make_task(self, name: str, **kw):
        if name == "search":
            from fetcher.sites.taobao.search import TaobaoSearchTask
            return TaobaoSearchTask(**kw)
        raise KeyError(f"未知任务: {name!r}（可选: "
                       f"{', '.join(self.task_names())}）")

    # ---- 会话冷启动软着陆 ----

    def cold_start(self, page, item, log=print) -> None:
        try:
            page.goto(self.homepage, wait_until="domcontentloaded",
                      timeout=45000)
            time.sleep(random.uniform(2.0, 4.0))
        except Exception:  # noqa: BLE001
            pass


# 自注册：sites 包自动发现本目录并 import 时生效
from fetcher.sites import register_site  # noqa: E402

register_site("taobao", TaobaoPlugin)

__all__ = ["TaobaoPlugin"]
