# -*- coding: utf-8 -*-
"""词库产量接口：合并 X / FB 两脚本 state JSON 的 kw_stats + kw_retired。

- 数据源是脚本维护的 state JSON（唯一事实源），每次请求现读现合并，无同步问题；
- 分页 / 搜索 / 筛选 / 排序全部在服务端做，前端不本地分页；
- 防御性：state 文件缺失 / JSON 损坏 → 该平台按空处理，接口不炸。
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/keywords")

# 项目根（platform/server/app/api/keywords.py 上溯 4 级）
PROJECT_ROOT = Path(__file__).resolve().parents[4]

_STATE_FILES = {
    "x": ".cache/x_keyword_search_state.json",
    "fb": ".cache/fb_keyword_search_state.json",
}

_PLATFORMS = ("x", "fb")

# 排序键白名单：total_new=两平台累计新号之和，last_new=两平台上轮新号之和
# （null 按 0），q=两平台使用轮数之和
_SORT_KEYS = ("total_new", "last_new", "q",
              "x_new", "x_last_new", "x_q",
              "fb_new", "fb_last_new", "fb_q")


def _load_kw(name: str) -> tuple[dict, dict]:
    """读某平台 state JSON，返回 (kw_stats, kw_retired)；文件缺失/损坏按空处理。"""
    try:
        state = json.loads(
            (PROJECT_ROOT / _STATE_FILES[name]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    kw_stats = state.get("kw_stats")
    kw_retired = state.get("kw_retired")
    return (
        kw_stats if isinstance(kw_stats, dict) else {},
        kw_retired if isinstance(kw_retired, dict) else {},
    )


def _plat_view(stats: dict, retired: bool) -> dict:
    """单平台子对象。last_new 为「上一轮新号数」（2026-08-23 起脚本才记录，
    历史词无此键 → None，前端显 —）。"""
    return {
        "q": stats.get("q") or 0,
        "new": stats.get("new") or 0,
        "last_new": stats.get("last_new"),
        "last_q_at": stats.get("last_q_at"),
        "retired": retired,
    }


def _merged_keywords() -> list[dict]:
    """以关键词为键合并两平台；某平台没查过（kw_stats / kw_retired 都无）则该平台为 None。"""
    per = {p: _load_kw(p) for p in _PLATFORMS}
    kws: set[str] = set()
    for stats, retired in per.values():
        kws.update(stats.keys())
        kws.update(retired.keys())
    items = []
    for kw in kws:
        item = {"kw": kw}
        for p in _PLATFORMS:
            stats, retired = per[p]
            s = stats.get(kw)
            if isinstance(s, dict):
                item[p] = _plat_view(s, kw in retired)
            elif kw in retired:
                # 仅出现在 kw_retired 的防御分支：无统计但已退役
                item[p] = _plat_view({}, True)
            else:
                item[p] = None
        items.append(item)
    return items


def _is_retired(item: dict) -> bool:
    """两平台均退役 = 存在过的平台全部退役；任一平台在轮转即活跃。"""
    plats = [item[p] for p in _PLATFORMS if item[p] is not None]
    return bool(plats) and all(p["retired"] for p in plats)


def _plat_retired(item: dict, plat: str) -> bool:
    """单平台已退役（该平台没查过 = None 时不满足）。"""
    p = item[plat]
    return p is not None and p["retired"]


def _sort_key(item: dict, sort: str):
    """排序键：total_new/last_new/q 为两平台合计；x_*/fb_* 为单平台口径
    （列头排序必须与该列展示数值一致）。null 平台 / null last_new 按 0；
    附加 kw 升序保证次序稳定。"""
    field = {"total_new": "new", "last_new": "last_new", "q": "q"}
    if sort in field:
        val = sum((item[p] or {}).get(field[sort]) or 0 for p in _PLATFORMS)
    else:  # x_new / fb_q 等单平台键
        plat, _, key = sort.partition("_")
        val = (item[plat] or {}).get(key) or 0
    return (val, item["kw"])


@router.get("")
def list_keywords(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    q: str = Query(default=""),
    platform: str = Query(default="all"),
    status: str = Query(default="all"),
    sort: str = Query(default="total_new"),
    order: str = Query(default="desc"),
):
    for name, val, allowed in (
        ("platform", platform, ("all", "x", "fb")),
        ("status", status,
         ("all", "active", "x_retired", "fb_retired", "retired")),
        ("sort", sort, _SORT_KEYS),
        ("order", order, ("asc", "desc")),
    ):
        if val not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"参数 {name} 必须是 {'/'.join(allowed)} 之一")

    items = _merged_keywords()

    # 过滤：搜索（大小写不敏感包含）→ 平台 → 状态
    needle = q.strip().lower()
    if needle:
        items = [it for it in items if needle in it["kw"].lower()]
    if platform != "all":
        items = [it for it in items if it[platform] is not None]
    # status 口径：active=任一平台在轮转；x_retired/fb_retired=该平台已退役
    # （单平台存在的词该平台退役即满足，不管另一平台）；retired=存在过的平台全部退役
    if status == "active":
        items = [it for it in items if not _is_retired(it)]
    elif status == "x_retired":
        items = [it for it in items if _plat_retired(it, "x")]
    elif status == "fb_retired":
        items = [it for it in items if _plat_retired(it, "fb")]
    elif status == "retired":
        items = [it for it in items if _is_retired(it)]

    # 排序（过滤后、分页前）
    items.sort(key=lambda it: _sort_key(it, sort), reverse=(order == "desc"))

    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
