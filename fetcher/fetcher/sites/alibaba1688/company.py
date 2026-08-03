# -*- coding: utf-8 -*-
"""1688 公司黄页采集任务（迁移 company_crawler.py 的 CompanyTask 全部行为）。

端点：s.1688.com/company/company_search.htm（「找供应商」公司黄页），
直出「公司名 + 店铺域名」，无需从商品卡片内嵌 JSON 抠 shopAddition。
进度：category_progress 表以 "company:" 前缀存储，与 shop 任务的
商品搜索进度完全隔离。
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

COMPANY_URL_TPL = ("https://s.1688.com/company/company_search.htm"
                   "?charset=utf8&keywords={keyword}&beginPage={page}")

# category_progress 存储前缀：与商品搜索进度隔离
PROGRESS_PREFIX = "company:"


def build_company_url(keyword: str, page_no: int = 1) -> str:
    """构造公司黄页 URL。charset=utf8 必须带：不带时页面按 GBK 解码
    UTF-8 关键词，标题全变乱码（实测 2026-08-03）。"""
    from urllib.parse import quote
    return COMPANY_URL_TPL.format(keyword=quote(keyword), page=page_no)


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

# 从黄页提取企业卡片：.company-offer-card 内找店铺首页链接（hostname
# 为 xxx.1688.com 且非已知功能子域），公司名取卡片内文字最长的店铺
# 锚文本；同时探测「下一页」按钮判断是否还有下页
_JS_EXTRACT_COMPANIES = """
() => {
  const SKIP = ['s.', 'www.', 'login.', 'go.', 'air.', 'cx.', '114.',
                'mind.', 'show.', 'r.', 'cart.', 'work.', 'sale.',
                'purchase.', 'rongzi.', 'global.', 'sourcingbot.'];
  const items = [];
  const seen = new Set();
  document.querySelectorAll('.company-offer-card').forEach(card => {
    let best = null;
    card.querySelectorAll('a[href]').forEach(a => {
      let h;
      try { h = new URL(a.href); } catch (e) { return; }
      if (!h.hostname.endsWith('.1688.com')) return;
      if (SKIP.some(p => h.hostname.startsWith(p))) return;
      if (h.pathname !== '/' && h.pathname !== '') return;
      const t = (a.textContent || '').trim();
      if (!best || t.length > best.name.length) {
        best = {domain: h.hostname.toLowerCase(), name: t};
      }
    });
    if (best && !seen.has(best.domain)) {
      seen.add(best.domain);
      items.push(best);
    }
  });
  const next = document.querySelector('a.fui-next:not(.fui-disabled)');
  return {items, hasMore: !!next,
          cards: document.querySelectorAll('.company-offer-card').length};
}
"""

_JS_CARDS_READY = """
() => document.querySelectorAll('.company-offer-card').length > 0
"""


def fetch_homepage_categories(page) -> list[dict]:
    """访问 1688 首页提取类目关键词 [{name, keyword}, ...]，失败返回 []。"""
    try:
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
        cats = page.evaluate(_JS_EXTRACT_CATEGORIES) or []
        return [c for c in cats if c.get("keyword")]
    except Exception:  # noqa: BLE001
        return []


SEED_KEYWORDS = [
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


class KeywordPool:
    """关键词池：进程内共享，线程安全（与 CategoryPool 同思路）。"""

    def __init__(self, exhausted: set):
        self.lock = threading.Lock()
        self.pool: dict = {}
        self.in_progress: set = set()
        self.exhausted: set = set(exhausted)

    def pick(self) -> tuple[str, str] | None:
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


class CompanyTask(Task):
    """公司黄页采集任务：随机关键词 → 黄页 → 公司店铺域名入库。

    任务项为 (keyword, name, page_no) 三元组；进度以 "company:" 前缀
    存 category_progress，与商品搜索进度隔离。
    """

    name = "company"
    unit = "页"
    batch_unit = "店铺"
    cold_start_before_acquire = True
    # 黄页与商品搜索同属 s.1688.com 搜索域，按同一预算保守处理：
    # 每出口 IP 采满 12 页主动换 IP
    ip_request_budget = 12

    def __init__(self):
        self.kw_pool: KeywordPool | None = None

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        exhausted = {k[len(PROGRESS_PREFIX):]
                     for k in db.get_exhausted_keywords()
                     if k.startswith(PROGRESS_PREFIX)}
        if exhausted:
            print(f"[0] 黄页已采到末页的关键词 {len(exhausted)} 个，自动跳过")
        self.kw_pool = KeywordPool(exhausted)
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

    def summary(self, all_stats: dict) -> str:
        from fetcher.db import ShopDB  # 延迟导入
        shops = sum(s.get("shops", 0) for s in all_stats.values())
        new = sum(s.get("new", 0) for s in all_stats.values())
        pages = sum(s.get("pages", 0) for s in all_stats.values())
        db = ShopDB()
        stats = db.stats()
        db.close()
        return (f"本次黄页采集: {pages} 页, 店铺 {shops} 个（新增 {new}）"
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
            cats = [{"name": n, "keyword": k} for n, k in SEED_KEYWORDS]
            ctx.log(f"[!] 首页类目提取失败，"
                    f"使用内置种子关键词（{len(cats)} 个）")
        n = self.kw_pool.refresh(cats)
        if n:
            ctx.log(f"黄页关键词池新增 {n} 个"
                    f"（可采 {self.kw_pool.available()}，"
                    f"跳过已采完 {len(self.kw_pool.exhausted)}）")
        if not ensure_mtop_token(ctx.page, log=ctx.log):
            ctx.log("[!] mtop 握手未拿到 _m_h5_tk，本会话黄页采集将被搁置"
                    "（fetch 逐页重试握手，仍无令牌则按风控换 IP）")

    def acquire_item(self, ctx):
        picked = self.kw_pool.pick()
        if not picked:
            return None
        keyword, name = picked
        prog = ctx.store.db.get_category_progress(PROGRESS_PREFIX + keyword)
        page_no = prog["next_page"] if prog else 1
        return (keyword, name, page_no)

    def label(self, item) -> str:
        return f"{item[1]} p{item[2]}"

    def fetch(self, ctx, item) -> ActionResult:
        """抓取一页公司黄页，提取「公司名 + 店铺域名」列表。"""
        page = ctx.page
        keyword, _name, page_no = item
        url = build_company_url(keyword, page_no)
        try:
            # 无 mtop 令牌不碰黄页（无令牌裸奔 = 首请求即踢登录墙）
            if not has_mtop_token(page) and not ensure_mtop_token(page):
                return ActionResult.blocked(
                    "会话缺少 mtop 令牌（_m_h5_tk），搜索域入场券未获取，"
                    "未触碰黄页")
            referer = (HOMEPAGE if page_no <= 1
                       else build_company_url(keyword, page_no - 1))
            page.goto(url, wait_until="domcontentloaded", timeout=60000,
                      referer=referer)
            time.sleep(random.uniform(1.0, 2.0))
            # 等企业卡片渲染就绪（轮询，不加重风控）
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                try:
                    if page.evaluate(_JS_CARDS_READY):
                        break
                except Exception:  # noqa: BLE001
                    break
                time.sleep(1.0)
            time.sleep(random.uniform(1.5, 3.0))
            result = page.evaluate(_JS_EXTRACT_COMPANIES) or {}
            shops = [{"domain": it["domain"],
                      "name": it.get("name") or None,
                      "url": f"https://{it['domain']}"}
                     for it in result.get("items") or [] if it.get("domain")]
            return ActionResult(Outcome.OK, "已解析公司黄页", {
                "shops": shops,
                "has_more": bool(result.get("hasMore")),
                "found": str(result.get("cards") or 0),
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
        keyword, name, page_no = item
        page_shops = result.data["shops"]
        has_more = result.data["has_more"]
        run_id = db.start_run(name, PROGRESS_PREFIX + keyword)
        n_new = db.upsert_shops(page_shops, run_id=run_id,
                                category_keyword=keyword)
        db.finish_run(run_id, shops_found=len(page_shops),
                      shops_picked=n_new, note=f"company page={page_no}")
        if not page_shops or not has_more:
            db.mark_category_exhausted(PROGRESS_PREFIX + keyword, name)
            ctx.state["task"]["exhausted"] = True
            ctx.set_status(state=f"■ {name} 采到末页，标记 exhausted")
            ctx.log(f"■ 关键词 {name} 第 {page_no} 页 "
                    f"{len(page_shops)} 店，hasMore={has_more}，"
                    f"采到末页标记 exhausted")
        else:
            db.advance_category_page(PROGRESS_PREFIX + keyword, name,
                                     shops_found=len(page_shops))
            ctx.set_status(state=f"✓ {len(page_shops)} 店（新 {n_new}）")
        stats["shops"] += len(page_shops)
        stats["new"] += n_new
        stats["pages"] += 1
        ctx.set_status(n=stats["shops"], new=stats["new"],
                       pages=stats["pages"])
        return len(page_shops)

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        return "跳过该页，页码不前进下次重采"

    def on_abort(self, ctx, item) -> str:
        return (f"关键词 {item[0]} 第 {item[2]} 页页码不前进，"
                f"下次运行自动续采")

    def after_item(self, ctx, item) -> None:
        self.kw_pool.release(item[0],
                             exhausted=ctx.state["task"].pop("exhausted",
                                                             False))

    def empty_message(self) -> str:
        return "没有可采的关键词了（全部采完或被占用）"
