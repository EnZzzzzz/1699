# -*- coding: utf-8 -*-
"""阿里系 mtop 握手（站点族共享机制）。

实测（2026-08-03，1688 搜索域）：搜索/黄页数据走 mtop API
（h5api.m.*），会话必须持有 _m_h5_tk 令牌才放行；无令牌的匿名会话
直接踢登录墙（凌晨严格时段首请求即踢，连滑块都不给）。淘宝搜索域
同机制（h5api.m.taobao.com），仅域不同 —— 正式翻页前先在低敏
落地页完成握手拿令牌，拿不到就不碰搜索（无令牌裸奔 = 白烧 IP）。
"""

from __future__ import annotations

import random
import time

MTOP_TOKEN_NAME = "_m_h5_tk"


def has_mtop_token(page, domain: str = "1688.com") -> bool:
    """会话是否已持有指定域的 mtop API 令牌（_m_h5_tk）。"""
    try:
        return any(c["name"] == MTOP_TOKEN_NAME
                   for c in page.context.cookies()
                   if domain in c.get("domain", ""))
    except Exception:  # noqa: BLE001
        return False


def ensure_mtop_token(page, search_home: str, referer: str,
                      domain: str = "1688.com", log=None,
                      attempts: int = 2) -> bool:
    """确保会话持有 _m_h5_tk：没有就访问搜索域落地页触发签发
    （最多 attempts 次）。拿到返回 True；拿不到返回 False。"""
    if has_mtop_token(page, domain):
        return True
    for i in range(attempts):
        try:
            page.goto(search_home, wait_until="domcontentloaded",
                      timeout=60000, referer=referer)
            time.sleep(random.uniform(2.5, 4.5))
        except Exception:  # noqa: BLE001
            pass
        if has_mtop_token(page, domain):
            if log:
                log(f"mtop 握手完成（第 {i + 1} 次尝试），"
                    f"会话已持有 _m_h5_tk（{domain}）")
            return True
    return False
