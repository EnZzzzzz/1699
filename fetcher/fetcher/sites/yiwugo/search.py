# -*- coding: utf-8 -*-
"""义乌购商品搜索采集任务：关键词 → 搜索 API → 商品列表 JSONL 落盘。

与阿里系的差异（全部实测于 2026-08-03）：
    - 数据不渲染在 HTML 里（搜索页是 SPA 壳），直接调 JSON API
      /api/search/s.htm，不经 page.goto 采页面；
    - 无需 mtop 令牌，只需 csrfToken（ensure_csrf_token 握手）；
    - 无登录墙、匿名可见全部列表字段（含商铺名/市场摊位号）；
    - 产出落 .cache/yiwugo_items.jsonl，不碰 1688 库语义。

队列：内存关键词 × 页码（与淘宝 search 任务同构）。
"""

from __future__ import annotations

import json
import threading

from fetcher.control.task import Task
from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.yiwugo import features
from fetcher.sites.yiwugo.features import (
    CODE_CAPTCHA,
    CODE_ILLEGAL,
    CODE_SUCCESS,
    HOMEPAGE,
    api_code,
    api_get,
    ensure_csrf_token,
    has_csrf_token,
)

SEARCH_API = "/api/search/s.htm"

# 实测默认页长 10；pageSize 可调（前端分页组件按 10/20/40 档）
PAGE_SIZE = 10

DEFAULT_KEYWORDS = ["手机壳", "发夹", "玩具", "饰品", "袜子"]

# 搜索 API 参数模板（前端 search.vue 实测构造）
SEARCH_PARAMS = {"appid": 6, "source": "pc", "checkLabel": 1,
                 "searchMethod": "original"}

# 「无结果」判定：numfound == 0 即合法空页（搜索 API 有结构化总数，
# 不需要像淘宝那样猜页面文案）


class KeywordQueue:
    """内存关键词队列（线程安全；每个关键词采 pages_per_keyword 页）。"""

    def __init__(self, keywords=(), pages_per_keyword: int = 1):
        self.lock = threading.Lock()
        self.pages_per_keyword = pages_per_keyword
        self._queue = [(kw, p) for kw in keywords
                       for p in range(1, pages_per_keyword + 1)]

    def pick(self):
        with self.lock:
            return self._queue.pop(0) if self._queue else None

    def remaining(self) -> int:
        with self.lock:
            return len(self._queue)


def parse_search_products(data: dict) -> tuple[list[dict], int]:
    """把搜索 API 响应规范化成 (商品列表, 总数)（纯函数，便于单测）。

    过滤：无 id 或无标题的条目丢弃；广告条（isAd）保留并标记。
    """
    content = (data or {}).get("content") or {}
    numfound = int(content.get("numfound") or 0)
    items = []
    for p in content.get("prslist") or []:
        pid = p.get("id")
        title = (p.get("title") or "").strip()
        if not pid or not title:
            continue
        shop_url_id = p.get("shopUrlId") or ""
        items.append({
            "id": pid,
            "title": title,
            "shop_id": p.get("shopId"),
            "shop_name": p.get("shopName") or "",
            "shop_url_id": shop_url_id,
            "url": f"https://www.yiwugo.com/product/detail/{pid}.html",
            "shop_url": (f"https://www.yiwugo.com/hu/{shop_url_id}.html"
                         if shop_url_id else ""),
            # 义乌购大量商品不标价（询价制），保留原始字段
            "price": p.get("sellPrice") or p.get("facePrice") or "",
            "max_price": p.get("maxPrice") or 0,
            # 市场摊位信息（义乌购独有，比联系方式更硬的身份锚点）
            "market_info": p.get("marketinfo") or "",
            "market_area": p.get("marketOrAdress") or "",
            "booth_no": p.get("boothNo") or "",
            "picture": p.get("picture1") or "",
            "credit": p.get("credit"),
            "is_ad": bool(p.get("isAd")),
        })
    return items, numfound


class YiwugoSearchTask(Task):
    """义乌购商品搜索：关键词 → /api/search/s.htm → JSONL。

    任务项为 (keyword, page_no)；产出 .cache/yiwugo_items.jsonl
    （1688 库语义零接触）。
    """

    name = "search"
    unit = "页"
    batch_unit = "商品"
    cold_start_before_acquire = False
    # 防护强度低（实测 50 连发不触发），但仍给匿名会话一个保守预算 [CAL-3]
    ip_request_budget = 60

    def __init__(self, keywords=None, pages_per_keyword: int = 1,
                 page_size: int = PAGE_SIZE, out_path=None):
        self.queue = KeywordQueue(keywords or DEFAULT_KEYWORDS,
                                  pages_per_keyword)
        self.page_size = page_size
        self.out_path = out_path  # None 时取 <cache>/yiwugo_items.jsonl

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        print(f"[1] 关键词队列 {self.queue.remaining()} 个任务项"
              f"（每关键词 {self.queue.pages_per_keyword} 页 × "
              f"{self.page_size} 条），每 worker 每批 {config.batch_num} 页，"
              f"产出 → {self._out_path(config)}")
        return True

    def summary(self, all_stats: dict, db_path=None) -> str:
        items = sum(s.get("items", 0) for s in all_stats.values())
        pages = sum(s.get("pages", 0) for s in all_stats.values())
        return f"本次义乌购搜索采集: {pages} 页, 商品 {items} 个"

    # ---- 状态板 ----

    def compose(self, wid: int, f: dict) -> str:
        return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                f"采 {f.get('items', 0)} 品（页 {f.get('pages', 0)}）| "
                f"{f.get('shop', '-')} | {f.get('state', '初始化')}")

    def make_stats(self) -> dict:
        return {"items": 0, "pages": 0, "empty": 0}

    def rest_counter(self, stats: dict) -> int:
        return stats["pages"]

    # ---- worker 循环 ----

    def acquire_item(self, ctx):
        return self.queue.pick()

    def label(self, item) -> str:
        return f"{item[0]} p{item[1]}"

    def fetch(self, ctx, item) -> ActionResult:
        """调搜索 API 并解析商品列表（不经页面导航）。"""
        page = ctx.page
        keyword, page_no = item
        try:
            # 无 csrfToken 不碰 API（无令牌裸奔 = 必吃 -1 非法请求）
            if not has_csrf_token(page) \
                    and not ensure_csrf_token(page, log=ctx.log):
                return ActionResult.blocked(
                    "会话缺少 csrfToken（yiwugo.com），未触碰搜索 API")
            data = api_get(page, SEARCH_API, params={
                "q": keyword, "cpage": page_no, "pageSize": self.page_size,
                **SEARCH_PARAMS})
            code = api_code(data)
            if code == CODE_ILLEGAL:
                # 令牌失效/被踢：按风控处理（换 IP 重建会话会重握手）
                return ActionResult.blocked(
                    "搜索 API 判非法请求（-1），csrfToken 疑似失效")
            if code == CODE_CAPTCHA:
                return ActionResult.blocked(
                    "搜索 API 触发自研滑块验证码（-5）")
            if code != CODE_SUCCESS:
                return ActionResult.empty(
                    f"搜索 API 返回未知 code={code!r}: "
                    f"{str(data.get('msg'))[:100]}")
            items, numfound = parse_search_products(data)
            return ActionResult(Outcome.OK, "已解析义乌购搜索响应", {
                "items": items,
                "numfound": numfound,
                "no_result": numfound == 0,
            })
        except Exception as e:  # noqa: BLE001
            ctx.last_error = e
            kind = classify_error(e, page)
            reason = str(e).splitlines()[0][:200]
            if kind == "fatal":
                return ActionResult.fatal(reason)
            if kind == "net_error":
                return ActionResult.net_error(reason)
            return ActionResult.blocked(f"搜索 API 请求失败（疑似风控）: {reason}")

    def validate(self, ctx, item, result: ActionResult) -> bool:
        """结构化判空：items 为列表即有效；空列表仅在 numfound==0
        （正常无结果）时合法，否则按 EMPTY 进策略链。"""
        data = result.data or {}
        if not isinstance(data.get("items"), list):
            return False
        return bool(data["items"]) or bool(data.get("no_result"))

    def on_success(self, ctx, item, result: ActionResult) -> int:
        stats = ctx.state["task"]["stats"]
        keyword, page_no = item
        items = result.data["items"]
        if items:
            self._append_jsonl(ctx.config, [{
                "keyword": keyword, "page": page_no, **it} for it in items])
        else:
            stats["empty"] += 1
            ctx.set_status(state=f"■ {keyword} 无结果")
        stats["items"] += len(items)
        stats["pages"] += 1
        ctx.set_status(items=stats["items"], pages=stats["pages"],
                       state=f"✓ {len(items)} 商品"
                             f"（共 {result.data['numfound']}）")
        return len(items)  # 批次配额按商品数计

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        return "跳过该页（内存队列不重采）"

    def giveup_cost(self, item) -> int:
        return 0

    def empty_message(self) -> str:
        return "关键词队列已采完"

    # ---- 落盘 ----

    def _out_path(self, config):
        if self.out_path:
            return self.out_path
        return config.resolved_db_path().parent / "yiwugo_items.jsonl"

    def _append_jsonl(self, config, rows: list[dict]):
        path = self._out_path(config)
        with open(path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
