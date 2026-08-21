# -*- coding: utf-8 -*-
"""FB 群帖 URL 分类（纯函数，stdlib only）。

原 fetcher.atoms.facebook_discover 的 classify_fb_url，fetcher 包退役后
迁存于此（scraper 直搜脚本仍依赖它从 SERP 链接派生 group_id）。
"""

from __future__ import annotations

import re

# FB 群帖 permalink：groups/<gid>/posts/<帖id> 或 /permalink/<帖id>
POST_RE = re.compile(r"facebook\.com/groups/([^/]+)/(?:posts|permalink)/(\d+)")
# FB 群主页：groups/<群id>
GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")


def classify_fb_url(url: str) -> tuple[str, str, str] | None:
    """分类 FB 群帖 URL：(kind, group_id, group_url) | None。

    kind="post"（帖 permalink）→ group_url 为派生的群主页；
    kind="group"（群主页）→ group_url 归一化到
    https://www.facebook.com/groups/{gid}（去尾部斜杠/协议差异）；
    其余（FB 视频/用户主页/广告页/非 FB）→ None。
    """
    m = POST_RE.search(url)
    if m:
        gid = m.group(1)
        return "post", gid, f"https://www.facebook.com/groups/{gid}"
    m = GROUP_RE.search(url)
    if m:
        gid = m.group(1)
        return "group", gid, f"https://www.facebook.com/groups/{gid}"
    return None
