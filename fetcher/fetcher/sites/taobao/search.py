# -*- coding: utf-8 -*-
"""淘宝商品搜索采集任务（演示站点扩展：不依赖 1688 的任何表与队列）。

任务内容：内置/自定义关键词队列 → s.taobao.com 搜索页 → 解析商品
列表 → JSONL 落盘（.cache/taobao_items.jsonl，不复用 1688 的
shops/contacts 表与库语义）。

⚠️ 解析器待真实环境校准（标注 [CAL]）：选择器策略按「页面内嵌 JSON
优先、DOM 选择器兜底」编写（与 1688 offerV2 同思路），具体字段路径
与 DOM 结构需在真实搜索页上校准：
    [CAL-6] 内嵌数据路径 window.__INIT_DATA__ / g_page_config：
            淘宝搜索页的历史内嵌变量名，现行页面是否沿用待确认；
            解析器对两种变量名 + mods.itemlist 两种结构做了兼容。
    [CAL-7] 商品卡片 DOM 选择器 .item 与字段子选择器：兜底路径，
            class 名大概率已变（淘宝频繁改版），真实环境需重录。
    [CAL-8] 「无结果」判定：items 为空 + raw 含"没有找到"/"找不到"
            关键词视为正常末页（exhausted），否则按 EMPTY 进策略链。
"""

from __future__ import annotations

import json
import random
import re
import threading
import time

from fetcher.control.task import Task
from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.taobao.features import (
    HOMEPAGE,
    ensure_mtop_token,
    has_mtop_token,
)

SEARCH_URL_TPL = "https://s.taobao.com/search?q={keyword}&s={offset}"

# 每页 48 个商品（淘宝搜索固定页长，翻页用 s=offset 而非 page=N）
PAGE_SIZE = 48

DEFAULT_KEYWORDS = ["连衣裙", "蓝牙耳机", "保温杯", "瑜伽垫", "台灯"]

# 内嵌数据提取（[CAL-6]）：优先 __INIT_DATA__，兜底 g_page_config；
# 两种历史结构（mods.itemlist.data.auctions / mods.itemlist.data.items）
_JS_EXTRACT_ITEMS = """
() => {
  const grab = (obj) => {
    const mods = (obj || {}).mods || {};
    const il = mods.itemlist || {};
    const data = il.data || {};
    return data.auctions || data.items || null;
  };
  let items = grab(window.__INIT_DATA__) || grab(window.g_page_config);
  if (!items) return {items: [], found: 0, embedded: false};
  const out = items.map(it => ({
    title: it.raw_title || it.title || '',
    price: (it.view_price || it.price || '') + '',
    shop: it.nick || it.shopName || '',
    url: it.detail_url || it.item_url || '',
    sales: it.view_sales || it.realSales || ''
  }));
  return {items: out, found: out.length, embedded: true};
}
"""

# DOM 兜底提取（[CAL-7]）：内嵌变量不存在时按卡片选择器解析
_JS_EXTRACT_ITEMS_DOM = """
() => {
  const cards = document.querySelectorAll('.item, .items .item');
  const out = [];
  cards.forEach(c => {
    const a = c.querySelector('a.title, .title a, a[href*="item.taobao"], a[href*="detail.tmall"]');
    const p = c.querySelector('.price, .price g_price, strong');
    const s = c.querySelector('.shop, .shopname, .dsrs');
    if (a) out.push({
      title: (a.textContent || '').trim(),
      price: p ? (p.textContent || '').trim() : '',
      shop: s ? (s.textContent || '').trim() : '',
      url: a.href || '',
      sales: ''
    });
  });
  return {items: out, found: out.length, embedded: false};
}
"""

# 「无结果」关键词（[CAL-8]）
NO_RESULT_KEYWORDS = ("没有找到", "找不到相关", "没有相关宝贝")


class KeywordQueue:
    """内存关键词队列（线程安全，多 worker 共享；每个关键词采一轮，
    page 进度随 item 走，不复用 1688 的任何表）。"""

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


def parse_search_items(result: dict) -> list[dict]:
    """把页面提取结果规范化成商品 dict 列表（纯函数，便于单测）。

    过滤：无标题或无链接的条目丢弃；detail_url 协议相对地址补 https:。
    """
    items = []
    for it in (result or {}).get("items") or []:
        title = (it.get("title") or "").strip()
        url = (it.get("url") or "").strip()
        if not title or not url:
            continue
        if url.startswith("//"):
            url = "https:" + url
        items.append({
            "title": re.sub(r"<[^>]+>", "", title),  # 标题可能带 <em> 高亮标签
            "price": it.get("price") or "",
            "shop": it.get("shop") or "",
            "url": url,
            "sales": it.get("sales") or "",
        })
    return items


class TaobaoSearchTask(Task):
    """淘宝商品搜索采集：关键词 → 搜索页 → 商品列表 JSONL 落盘。

    任务项为 (keyword, page_no)；队列在内存（KeywordQueue），
    产出落 .cache/taobao_items.jsonl（1688 库语义零接触）。
    """

    name = "search"
    unit = "页"
    batch_unit = "商品"
    cold_start_before_acquire = False
    # 搜索域配额墙：沿用 1688 同族经验值（待淘宝实测校准）
    ip_request_budget = 12

    def __init__(self, keywords=None, pages_per_keyword: int = 1,
                 out_path=None):
        self.queue = KeywordQueue(keywords or DEFAULT_KEYWORDS,
                                  pages_per_keyword)
        self.out_path = out_path  # None 时取 <cache>/taobao_items.jsonl

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        print(f"[1] 关键词队列 {self.queue.remaining()} 个任务项"
              f"（每关键词 {self.queue.pages_per_keyword} 页），"
              f"每 worker 每批 {config.batch_num} 页，"
              f"产出 → {self._out_path(config)}")
        return True

    def summary(self, all_stats: dict) -> str:
        items = sum(s.get("items", 0) for s in all_stats.values())
        pages = sum(s.get("pages", 0) for s in all_stats.values())
        return f"本次淘宝搜索采集: {pages} 页, 商品 {items} 个"

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

    def cold_start(self, ctx, item) -> None:
        """新会话先逛淘宝首页留真实浏览轨迹，再深链搜索页。"""
        try:
            ctx.page.goto(HOMEPAGE, wait_until="domcontentloaded",
                          timeout=45000)
            time.sleep(random.uniform(2.0, 4.0))
            ensure_mtop_token(ctx.page, log=ctx.log)
        except Exception:  # noqa: BLE001
            pass  # 首页打不开不阻断

    def acquire_item(self, ctx):
        return self.queue.pick()

    def label(self, item) -> str:
        return f"{item[0]} p{item[1]}"

    def fetch(self, ctx, item) -> ActionResult:
        """导航到搜索页并解析商品列表。"""
        page = ctx.page
        keyword, page_no = item
        url = SEARCH_URL_TPL.format(keyword=keyword,
                                    offset=(page_no - 1) * PAGE_SIZE)
        try:
            # 无 mtop 令牌不碰搜索（同 1688：无令牌裸奔 = 白烧 IP）
            if not has_mtop_token(page) and not ensure_mtop_token(page):
                return ActionResult.blocked(
                    "会话缺少 mtop 令牌（_m_h5_tk@taobao.com），未触碰搜索")
            page.goto(url, wait_until="domcontentloaded", timeout=60000,
                      referer=HOMEPAGE)
            time.sleep(random.uniform(1.5, 3.0))
            result = page.evaluate(_JS_EXTRACT_ITEMS) or {}
            if not result.get("embedded"):
                # 内嵌变量不存在（页面结构变了/拦截页）：DOM 兜底 [CAL-7]
                result = page.evaluate(_JS_EXTRACT_ITEMS_DOM) or result
            items = parse_search_items(result)
            raw = ""
            try:
                raw = page.evaluate(
                    "() => document.body ? document.body.innerText : ''") or ""
            except Exception:  # noqa: BLE001
                pass
            return ActionResult(Outcome.OK, "已解析淘宝搜索页", {
                "items": items,
                "embedded": bool(result.get("embedded")),
                "no_result": (not items
                              and any(k in raw for k in NO_RESULT_KEYWORDS)),
                "_source_url": page.url,
                "_raw": raw[:500],
            })
        except Exception as e:  # noqa: BLE001
            ctx.last_error = e
            kind = classify_error(e, page)
            reason = str(e).splitlines()[0][:200]
            if kind == "fatal":
                return ActionResult.fatal(reason)
            if kind == "net_error":
                return ActionResult.net_error(reason)
            return ActionResult.blocked(f"页面加载失败（疑似风控拦截）: {reason}")

    def validate(self, ctx, item, result: ActionResult) -> bool:
        """结构化判空：items 为列表即有效；空列表仅在页面明示「无结果」
        时合法（正常末页），否则是软拦截/解析失效 → EMPTY 进策略链。"""
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
                "keyword": keyword, "page": page_no,
                "source_url": result.data.get("_source_url"),
                **it} for it in items])
        else:
            stats["empty"] += 1
            ctx.set_status(state=f"■ {keyword} 无结果（末页）")
        stats["items"] += len(items)
        stats["pages"] += 1
        ctx.set_status(items=stats["items"], pages=stats["pages"],
                       state=f"✓ {len(items)} 商品")
        return len(items)  # 批次配额按商品数计

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        return "跳过该页（内存队列不重采）"

    def giveup_cost(self, item) -> int:
        return 0  # 页未产出，不计批次配额

    def empty_message(self) -> str:
        return "关键词队列已采完"

    # ---- 落盘 ----

    def _out_path(self, config):
        if self.out_path:
            return self.out_path
        return config.resolved_db_path().parent / "taobao_items.jsonl"

    def _append_jsonl(self, config, rows: list[dict]):
        path = self._out_path(config)
        with open(path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
