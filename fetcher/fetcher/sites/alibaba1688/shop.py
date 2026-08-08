# -*- coding: utf-8 -*-
"""1688 店铺 URL 采集任务（迁移 shop_crawler.py 的 ShopTask 全部行为）。

任务内容：从 1688 首页提取类目入口（类目 = 关键词搜索页），随机挑
类目翻页采集：搜索结果页内嵌数据（window.data.offerV2...OFFER.items）
自带商家信息，无需点进商品详情页，直接解析店铺域名入库 shops 表
（status=pending），供 contact 任务消费。

进度：每个类目的 next_page 记在 category_progress；空页或
hasMore=false 标记 exhausted 之后跳过；抓取失败页码不前进。

与旧版的有意差异：抓取内不再就地自动过证（统一由 SolveSlider 策略
处置）；mtop 握手缺失时 fetch 自报 BLOCKED（不触碰搜索），控制层
按风控场景处置 —— 行为等价。
"""

from __future__ import annotations

import random
import threading
import time

from fetcher.control.task import Task
from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.alibaba1688.features import (
    HOMEPAGE,
    ensure_mtop_token,
    has_mtop_token,
)

SEARCH_URL_TPL = ("https://s.1688.com/selloffer/offer_search.htm"
                  "?charset=utf8&keywords={keyword}&beginPage={page}")


def build_search_url(keyword: str, page_no: int = 1) -> str:
    """构造类目搜索页 URL（1688 首页类目本质就是关键词搜索页）。"""
    from urllib.parse import quote
    return SEARCH_URL_TPL.format(keyword=quote(keyword), page=page_no)


# 从首页提取类目入口：类目链接全部指向 offer_search，类目 = 搜索关键词
_JS_EXTRACT_CATEGORIES = """
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="s.1688.com/selloffer/offer_search"]')
    .forEach(a => {
      const name = (a.textContent || '').trim();
      try {
        const kw = new URL(a.href).searchParams.get('keywords');
        if (kw && name && name.length <= 20 && !seen.has(kw)) {
          seen.add(kw);
          out.push({name, keyword: kw});
        }
      } catch (e) {}
    });
  return out;
}
"""

# 从搜索结果页内嵌数据提取商家店铺（shop/shopAddition 偶尔是被截断的
# JSON 字符串而非对象，做双格式兜底）
_JS_EXTRACT_SHOPS = """
() => {
  const data = window.data || {};
  const off = (((data.offerV2 || {}).response || {}).data || {}).OFFER || {};
  const items = off.items || [];
  const out = [];
  for (const it of items) {
    const d = it.data || {};
    let shopUrl = null;
    const sa = d.shopAddition;
    if (sa && typeof sa === 'object') shopUrl = sa.shopLinkUrl || null;
    if (!shopUrl) {
      const m = String(sa || '').match(/shopLinkUrl\\\\?"\\s*:\\s*\\\\?"(https?:[^"\\\\]+)/);
      if (m) shopUrl = m[1];
    }
    let name = null;
    if (d.shop && typeof d.shop === 'object') name = d.shop.text || null;
    if (!name) {
      const m2 = String(d.shop || '').match(/"text\\\\?"\\s*:\\s*\\\\?"([^"\\\\]+)/);
      if (m2) name = m2[1];
    }
    if (!name) name = d.loginId || null;
    out.push({shopUrl, name, loginId: d.loginId || null});
  }
  return {hasMore: String(off.hasMore || 'false'),
          found: String(off.found || '0'), items: out};
}
"""

# 等待搜索结果内嵌数据就绪（offerV2 是异步渲染的）
_JS_DATA_READY = """
() => !!(((window.data || {}).offerV2 || {}).response || {}).data
"""


def fetch_homepage_categories(page, timeout: float = 15.0) -> list[dict]:
    """访问 1688 首页提取类目入口 [{name, keyword}, ...]，失败返回 []。"""
    try:
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
        cats = page.evaluate(_JS_EXTRACT_CATEGORIES) or []
        return [c for c in cats if c.get("keyword")]
    except Exception:  # noqa: BLE001
        return []


# 首页类目提取失败时的兜底种子（均为 1688 常见批发类目关键词）
SEED_CATEGORIES = [
    ("女装", "女装"), ("男装", "男装"), ("内衣", "内衣"),
    ("童装", "童装"), ("鞋", "鞋"), ("箱包", "箱包"),
    ("配饰", "配饰"), ("家纺", "家纺"), ("家具", "家具"),
    ("灯具", "灯具"), ("五金工具", "五金工具"), ("电子元器件", "电子元器件"),
    ("手机配件", "手机配件"), ("数码配件", "数码配件"), ("家电", "家电"),
    ("美妆", "美妆"), ("个护", "个护"), ("食品", "食品"),
    ("茶叶", "茶叶"), ("酒水", "酒水"), ("玩具", "玩具"),
    ("母婴用品", "母婴用品"), ("宠物用品", "宠物用品"), ("运动户外", "运动户外"),
    ("汽车用品", "汽车用品"), ("办公文具", "办公文具"), ("包装", "包装"),
    ("工艺品", "工艺品"), ("珠宝首饰", "珠宝首饰"), ("眼镜", "眼镜"),
    ("手表", "手表"), ("雨伞", "雨伞"), ("厨房用品", "厨房用品"),
    ("卫浴", "卫浴"), ("建材", "建材"), ("机械", "机械"),
]


class CategoryPool:
    """类目池：进程内共享，线程安全（相当于 contact 的 shops pending
    队列，只是队列在内存里、页码进度在 category_progress 表里）。"""

    def __init__(self, exhausted: set):
        self.lock = threading.Lock()
        self.pool: dict = {}
        self.in_progress: set = set()
        self.exhausted: set = set(exhausted)

    def pick(self) -> tuple[str, str] | None:
        """随机挑一个可采类目并占用；无可采类目返回 None。"""
        with self.lock:
            candidates = [kw for kw in self.pool
                          if kw not in self.exhausted
                          and kw not in self.in_progress]
            if not candidates:
                return None
            kw = random.choice(candidates)
            self.in_progress.add(kw)
            return kw, self.pool.get(kw) or kw

    def release(self, keyword: str, exhausted: bool = False):
        with self.lock:
            self.in_progress.discard(keyword)
            if exhausted:
                self.exhausted.add(keyword)

    def refresh(self, cats: list[dict]) -> int:
        """合并首页提取到的类目，返回新增数量。"""
        with self.lock:
            n = 0
            for c in cats:
                kw = c.get("keyword")
                if kw and kw not in self.pool:
                    self.pool[kw] = c.get("name") or kw
                    n += 1
            return n

    def available(self) -> int:
        with self.lock:
            return len([kw for kw in self.pool
                        if kw not in self.exhausted
                        and kw not in self.in_progress])


class ShopTask(Task):
    """店铺 URL 采集任务：随机类目 → 搜索页 → 店铺域名入库。

    任务项为 (keyword, cat_name, page_no) 三元组；类目占用与 exhausted
    由 CategoryPool 管，页码进度由 category_progress 表管。
    """

    name = "shop"
    unit = "页"
    batch_unit = "店铺"
    # 冷启动要先逛首页提取类目填满类目池，必须在 acquire（选类目）之前
    cold_start_before_acquire = True
    # 搜索页匿名配额墙实测阈值 18~26 页：每出口 IP 采满 12 个搜索页
    # 请求即主动换 IP，把「被配额墙踢掉」变成「主动全身而退」
    ip_request_budget = 12

    def __init__(self):
        self.cat_pool: CategoryPool | None = None

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        exhausted = db.get_exhausted_keywords()
        if exhausted:
            print(f"[0] 已采到末页的类目 {len(exhausted)} 个，自动跳过")
        self.cat_pool = CategoryPool(exhausted)
        st = db.stats()
        print(f"[1] 数据库现有店铺 {st['shops']} 个（pending {st['pending']} / "
              f"done {st['done']} / no_contact {st['no_contact']} / "
              f"failed {st['failed']}），每个 worker 每批 "
              f"{config.batch_num} 个店铺"
              f"（{'最多 ' + str(config.max_batches) + ' 批'
                 if config.max_batches else '不限批数'}），"
              f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
        db.close()
        return True

    def summary(self, all_stats: dict, db_path=None) -> str:
        from fetcher.db import ShopDB  # 延迟导入
        shops = sum(s.get("shops", 0) for s in all_stats.values())
        new = sum(s.get("new", 0) for s in all_stats.values())
        pages = sum(s.get("pages", 0) for s in all_stats.values())
        db = ShopDB(db_path)
        stats = db.stats()
        db.close()
        return (f"本次采集: {pages} 页, 店铺 {shops} 个（新增 {new}）"
                f"\n    数据库统计: {stats}")

    # ---- 状态板 ----

    def compose(self, wid: int, f: dict) -> str:
        return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                f"采 {f.get('n', 0)} 店（新 {f.get('new', 0)} 页 "
                f"{f.get('pages', 0)}）| {f.get('shop', '-')} | "
                f"{f.get('state', '初始化')}")

    def make_stats(self) -> dict:
        return {"shops": 0, "new": 0, "pages": 0}

    def rest_counter(self, stats: dict) -> int:
        return stats["pages"]

    # ---- worker 循环 ----

    def cold_start(self, ctx, item) -> None:
        """新会话先逛 1688 首页留真实浏览轨迹，顺带提取首页类目填池。"""
        cats = fetch_homepage_categories(ctx.page)
        if not cats:
            cats = [{"name": n, "keyword": k} for n, k in SEED_CATEGORIES]
            ctx.log(f"[!] 首页类目提取失败，使用内置种子类目（{len(cats)} 个）")
        n = self.cat_pool.refresh(cats)
        if n:
            ctx.log(f"类目池新增 {n} 个类目（可采 {self.cat_pool.available()}，"
                    f"跳过已采完 {len(self.cat_pool.exhausted)}）")
        # mtop 握手：搜索页数据走 mtop API，须持有 _m_h5_tk 再碰 offer_search
        if not ensure_mtop_token(ctx.page, log=ctx.log):
            ctx.log("[!] mtop 握手未拿到 _m_h5_tk，本会话搜索采集将被搁置"
                    "（fetch 逐页重试握手，仍无令牌则按风控换 IP）")

    def acquire_item(self, ctx):
        picked = self.cat_pool.pick()
        if not picked:
            return None
        keyword, cat_name = picked
        prog = ctx.store.db.get_category_progress(keyword)
        page_no = prog["next_page"] if prog else 1
        return (keyword, cat_name, page_no)

    def label(self, item) -> str:
        return f"{item[1]} p{item[2]}"

    def fetch(self, ctx, item) -> ActionResult:
        """抓取一页类目搜索结果，提取商家店铺列表。"""
        page = ctx.page
        keyword, _cat_name, page_no = item
        url = build_search_url(keyword, page_no)
        try:
            # 无 mtop 令牌不碰搜索（无令牌裸奔 = 首请求即踢登录墙，白烧 IP）
            if not has_mtop_token(page) and not ensure_mtop_token(page):
                return ActionResult.blocked(
                    "会话缺少 mtop 令牌（_m_h5_tk），搜索域入场券未获取，"
                    "未触碰搜索")
            # referer 链条：第 1 页来自首页，第 N 页来自第 N-1 页搜索页
            referer = (HOMEPAGE if page_no <= 1
                       else build_search_url(keyword, page_no - 1))
            page.goto(url, wait_until="domcontentloaded", timeout=60000,
                      referer=referer)
            time.sleep(random.uniform(1.0, 2.0))
            # 等异步搜索结果数据就绪（轮询，不加重风控）
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                try:
                    if page.evaluate(_JS_DATA_READY):
                        break
                except Exception:  # noqa: BLE001
                    break
                time.sleep(1.0)
            time.sleep(random.uniform(1.5, 3.0))
            result = page.evaluate(_JS_EXTRACT_SHOPS) or {}
            shops = []
            seen = set()
            for it in result.get("items") or []:
                shop_url = (it.get("shopUrl") or "").strip()
                if not shop_url:
                    continue
                from urllib.parse import urlparse
                domain = (urlparse(shop_url).hostname or "").lower()
                if not domain.endswith(".1688.com") or domain in seen:
                    continue
                seen.add(domain)
                shops.append({"domain": domain,
                              "name": it.get("name"),
                              "url": f"https://{domain}"})
            return ActionResult(Outcome.OK, "已解析类目搜索页", {
                "shops": shops,
                "has_more": result.get("hasMore") == "true",
                "found": result.get("found") or "0",
                "_source_url": page.url,
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
        """结构化校验：结果必须含 shops 列表（空列表 = 采到末页，合法）。"""
        return isinstance((result.data or {}).get("shops"), list)

    def on_success(self, ctx, item, result: ActionResult) -> int:
        db = ctx.store.db
        stats = ctx.state["task"]["stats"]
        keyword, cat_name, page_no = item
        page_shops = result.data["shops"]
        has_more = result.data["has_more"]
        run_id = db.start_run(cat_name, keyword)
        n_new = db.upsert_shops(page_shops, run_id=run_id,
                                category_keyword=keyword)
        db.finish_run(run_id, shops_found=len(page_shops),
                      shops_picked=n_new, note=f"page={page_no}")
        if not page_shops or not has_more:
            # 空页或官方说没有下一页：该类目采到末页
            db.mark_category_exhausted(keyword, cat_name)
            ctx.state["task"]["exhausted"] = True  # after_item 顺手标记
            ctx.set_status(state=f"■ {cat_name} 采到末页，标记 exhausted")
            ctx.log(f"■ 类目 {cat_name} 第 {page_no} 页 "
                    f"{len(page_shops)} 店，hasMore={has_more}，"
                    f"采到末页标记 exhausted")
        else:
            db.advance_category_page(keyword, cat_name,
                                     shops_found=len(page_shops))
            ctx.set_status(state=f"✓ {len(page_shops)} 店（新 {n_new}）")
        stats["shops"] += len(page_shops)
        stats["new"] += n_new
        stats["pages"] += 1
        ctx.set_status(n=stats["shops"], new=stats["new"],
                       pages=stats["pages"])
        return len(page_shops)  # 批次配额按提取到的店铺数计

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        # 页码不前进（不 advance），下次运行从该页重采
        return "跳过该页，页码不前进下次重采"

    def on_abort(self, ctx, item) -> str:
        return (f"类目 {item[0]} 第 {item[2]} 页页码不前进，"
                f"下次运行自动续采")

    def after_item(self, ctx, item) -> None:
        # 释放类目占用（采到末页的顺手标记，之后所有 worker 都跳过）
        self.cat_pool.release(item[0],
                              exhausted=ctx.state["task"].pop("exhausted",
                                                              False))

    def empty_message(self) -> str:
        return "没有可采的类目了（全部采完或被占用）"
