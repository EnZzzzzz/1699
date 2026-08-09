# -*- coding: utf-8 -*-
"""Facebook URL 工具（group_task / post_task 共享）：群 URL → group_id 解析。

单一来源：group_task.py（payload.url 是群 URL）与 post_task.py
（payload.domain 是群 URL）都从这里取，改正则只需改一处。
"""

from __future__ import annotations

import re

# 从群 URL 解析 group_id：facebook.com/groups/{gid}
_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")


def group_id_from_url(url: str) -> str | None:
    """群 URL → 群 id；无/非法返回 None。"""
    m = _GROUP_RE.search(url or "")
    return m.group(1) if m else None
