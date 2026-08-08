# -*- coding: utf-8 -*-
"""1688 店铺 URL 采集任务（work_items 驱动 feeder 模式）。

任务内容：从 1688 首页提取类目入口（类目 = 关键词搜索页），随机挑
类目翻页采集：搜索结果页内嵌数据（window.data.offerV2...OFFER.items）
自带商家信息，无需点进商品详情页，直接解析店铺域名入库 shops 表
（status=pending），供 contact 任务消费。

进度：每个类目的 next_page 记在 category_progress；空页或
hasMore=false 标记 exhausted 之后跳过；抓取失败页码不前进。

与旧版的有意差异：抓取内不再就地自动过证（统一由 SolveSlider 策略
处置）；mtop 握手缺失时 fetch 自报 BLOCKED（不触碰搜索），控制层
按风控场景处置 —— 行为等价。

P3 Step 5.1：从 CategoryPool 进程内填池重构为 work_items 驱动
feeder——与 Step 4.1 MadeInChinaShopTask 同模式。
"""

from __future__ import annotations

import json
import random
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


class Alibaba1688ShopTask(Task):
    """1688 店铺 URL 采集：work_items 驱动 + 单类目搜索页处理。

    work_items payload：
      - 类目页：{"kind":"category","keyword":<keyword>,"name":<cat_name>}
        page_no 不进 payload——处理时读 category_progress.next_page
      - 发现：{"kind":"discover"}
        执行 = 首页类目提取 + mtop 握手 → 新类目逐条 INSERT category item

    链式续喂：category item on_success 后若未采完则 INSERT 下一页 item
    （同 payload，attempts=0）；hasMore 判定 exhaust。
    失败补插：refill_item 在 attempts 耗尽时补插同 payload 新 item。
    """

    name = "shop"
    unit = "页"
    batch_unit = "店铺"
    # 冷启动要先逛首页（软着陆），必须在 acquire 之前
    cold_start_before_acquire = True
    # 搜索页匿名配额墙实测阈值 18~26 页：每出口 IP 采满 12 个搜索页
    # 请求即主动换 IP，把「被配额墙踢掉」变成「主动全身而退」
    ip_request_budget = 12

    QUEUE = "crawl_1688_shop"
    SITE = "1688"

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        exhausted = db.get_exhausted_keywords()
        if exhausted:
            print(f"[0] 已采到末页的类目 {len(exhausted)} 个，自动跳过")
        # 播种：活跃类目逐条插 category item + 一条 discover item
        n_cat = self._seed_category_items(db)
        n_disc = self._seed_discover_item(db)
        if n_cat or n_disc:
            print(f"[0] 播种 {n_cat} 个 category item + {n_disc} 条 discover")
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

    def _seed_category_items(self, db) -> int:
        """活跃类目逐条插 category item（已有同 keyword pending 跳过）。

        iter_active_categories 取全量未采完类目（无拼音过滤——
        1688 中文/英文关键词都算）。
        """
        active = list(db.iter_active_categories())
        n = 0
        for cat in active:
            kw = cat["keyword"]
            name = cat.get("name", kw)
            if self._count_pending_by_kind(db, "category", kw) > 0:
                continue
            self._insert_work_item(db, {"kind": "category", "keyword": kw,
                                         "name": name})
            n += 1
        return n

    def _seed_discover_item(self, db) -> int:
        """插一条 discover item（已有 pending discover 跳过）。"""
        existing = self._count_pending_by_kind(db, "discover")
        if existing > 0:
            return 0
        self._insert_work_item(db, {"kind": "discover"})
        return 1

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
        """新会话先逛 1688 首页留真实浏览轨迹（纯软着陆，不提取类目）。

        类目提取归 discover item 的 on_success 处理。
        """
        try:
            ctx.page.goto(HOMEPAGE, wait_until="domcontentloaded",
                          timeout=60000)
            time.sleep(random.uniform(2.0, 4.0))
        except Exception:  # noqa: BLE001
            ctx.log("[!] 冷启动浏览失败，继续认领工作项")

    def acquire_item(self, ctx):
        """从 work_items 队列认领（CLI 与 daemon 同一路径）。"""
        consumer_id = f"w{ctx.wid}"
        db = ctx.store.db
        item = db.claim_next_eligible([self.QUEUE], consumer_id)
        if item is None:
            return None
        payload = dict(item["payload"])
        payload["id"] = item["id"]
        # P4 批次：把 batch_id 注入 payload（feeder 续喂/补插继承用）
        if item.get("batch_id") is not None:
            payload["batch_id"] = item["batch_id"]
        return payload

    def label(self, item) -> str:
        kind = item.get("kind", "")
        if kind == "discover":
            return "discover"
        kw = item.get("keyword", "?")
        name = item.get("name", kw)
        return f"{name}"

    def fetch(self, ctx, item) -> ActionResult:
        """按 kind 分派：category → 抓搜索页，discover → 返回标记。"""
        kind = item.get("kind", "")
        if kind == "discover":
            return ActionResult(Outcome.OK, "discover", {"discover": True})
        if kind == "category":
            return self._fetch_category(ctx, item)
        return ActionResult.fatal(f"未知 kind: {kind}")

    def _fetch_category(self, ctx, item) -> ActionResult:
        """抓取一页类目搜索结果，提取商家店铺列表。

        page_no 从 category_progress 运行时读（单一事实来源）。
        """
        page = ctx.page
        db = ctx.store.db
        keyword = item["keyword"]
        name = item.get("name", keyword)
        prog = db.get_category_progress(keyword)
        page_no = prog["next_page"] if prog else 1
        url = build_search_url(keyword, page_no)
        try:
            if not has_mtop_token(page) and not ensure_mtop_token(page):
                return ActionResult.blocked(
                    "会话缺少 mtop 令牌（_m_h5_tk），搜索域入场券未获取，"
                    "未触碰搜索")
            referer = (HOMEPAGE if page_no <= 1
                       else build_search_url(keyword, page_no - 1))
            page.goto(url, wait_until="domcontentloaded", timeout=60000,
                      referer=referer)
            time.sleep(random.uniform(1.0, 2.0))
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
            return ActionResult.blocked(
                f"页面加载失败（疑似风控拦截）: {reason}")

    def validate(self, ctx, item, result: ActionResult) -> bool:
        """结构化校验：discover → 检查 discover 标记；category → shops 列表。"""
        if item.get("kind") == "discover":
            return isinstance((result.data or {}).get("discover"), bool)
        return isinstance((result.data or {}).get("shops"), list)

    def on_success(self, ctx, item, result: ActionResult) -> int:
        """按 kind 分派入库与链式续喂。"""
        kind = item.get("kind", "")
        if kind == "discover":
            return self._on_discover_success(ctx, item, result)
        if kind == "category":
            return self._on_category_success(ctx, item, result)
        return 0

    def _on_discover_success(self, ctx, item, result: ActionResult) -> int:
        """discover 成功：首页类目提取 + mtop 握手 → 新类目逐条 INSERT
        category item。"""
        db = ctx.store.db
        page = ctx.page
        # mtop 握手（搜索域入场券）
        if not ensure_mtop_token(page, log=ctx.log):
            ctx.log("[!] discover mtop 握手未拿到 _m_h5_tk，"
                    "后续搜索采集将被搁置")
        # 提取首页类目
        cats = fetch_homepage_categories(page)
        if not cats:
            cats = [{"name": n, "keyword": k} for k, n in SEED_CATEGORIES]
            ctx.log(f"[!] 首页类目提取失败，"
                    f"使用内置种子类目（{len(cats)} 个）")
        n = 0
        for c in cats:
            kw = c["keyword"]
            # 跳过已 exhausted
            prog = db.get_category_progress(kw)
            if prog and prog.get("exhausted"):
                continue
            # 跳过已有同 keyword pending category item
            if self._count_pending_by_kind(db, "category", kw) > 0:
                continue
            payload = {"kind": "category", "keyword": kw,
                       "name": c.get("name", kw)}
            # P4 批次继承：discover item 属批次时，产出的 category item
            # 继承父 item 的 batch_id 与 batch_limit（batch_limit 收束用）
            if item.get("batch_id") is not None:
                payload["batch_id"] = item["batch_id"]
                payload["batch_limit"] = item.get("batch_limit", 0)
            self._insert_work_item(db, payload, batch_id=item.get("batch_id"))
            n += 1
        if n:
            ctx.log(f"discover 产出 {n} 个新类目 category item")
        return 0  # discover 不计入页数

    def _on_category_success(self, ctx, item, result: ActionResult) -> int:
        """category 成功：入库 shops → 链式续喂。1688 用 hasMore/空页
        判 exhausted（无 ZERO_NEW_LIMIT 保护）。"""
        db = ctx.store.db
        stats = ctx.state["task"]["stats"]
        keyword = item["keyword"]
        cat_name = item.get("name", keyword)
        prog = db.get_category_progress(keyword)
        page_no = prog["next_page"] if prog else 1
        page_shops = result.data["shops"]
        has_more = result.data["has_more"]
        run_id = db.start_run(cat_name, keyword)
        n_new = db.upsert_shops(page_shops, run_id=run_id,
                                category_keyword=keyword)
        db.finish_run(run_id, shops_found=len(page_shops),
                      shops_picked=n_new, note=f"page={page_no}")
        if not page_shops or not has_more:
            db.mark_category_exhausted(keyword, cat_name)
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
        # 链式续喂：未采完则 INSERT 下一页 item（P4 批次：继承 batch_id，
        # 收束——done 计数 ≥ batch_limit 后停止续喂，批次自然收束）
        if not page_shops or not has_more:
            pass  # exhausted，不续喂
        elif self._batch_reached_limit(db, item):
            ctx.log(f"■ 类目 {cat_name} 批次已达上限"
                    f"（{item.get('batch_limit')} 页），停止续喂")
        else:
            payload = {"kind": "category", "keyword": keyword,
                       "name": cat_name}
            if item.get("batch_id") is not None:
                payload["batch_id"] = item["batch_id"]
                payload["batch_limit"] = item.get("batch_limit", 0)
            self._insert_work_item(db, payload,
                                   batch_id=item.get("batch_id"))
        return len(page_shops)

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        return "跳过该页，页码不前进下次重采"

    def on_abort(self, ctx, item) -> str:
        kw = item.get("keyword", "?")
        return f"类目 {kw} 页码不前进，下次运行自动续采"

    def refill_item(self, ctx, item) -> None:
        """attempts 耗尽补插：category 同 payload 新 item（attempts=0），
        discover 也补插一次。P4 批次：补插继承 batch_id；批次已达上限
        （done ≥ batch_limit）时不再补插。"""
        db = ctx.store.db if ctx.store else None
        if db is None:
            return
        kind = item.get("kind", "")
        if kind == "category":
            if self._batch_reached_limit(db, item):
                ctx.log(f"[refill] 类目 {item.get('keyword')} 批次已达上限，"
                        f"不再补插")
                return
            payload = {"kind": "category",
                       "keyword": item["keyword"],
                       "name": item.get("name", item["keyword"])}
            if item.get("batch_id") is not None:
                payload["batch_id"] = item["batch_id"]
                payload["batch_limit"] = item.get("batch_limit", 0)
            self._insert_work_item(db, payload,
                                   batch_id=item.get("batch_id"))
            ctx.log(f"[refill] 类目 {item.get('keyword')} 补插 category item")
        elif kind == "discover":
            if self._batch_reached_limit(db, item):
                ctx.log("[refill] discover 批次已达上限，不再补插")
                return
            payload = {"kind": "discover"}
            if item.get("batch_id") is not None:
                payload["batch_id"] = item["batch_id"]
                payload["batch_limit"] = item.get("batch_limit", 0)
            self._insert_work_item(db, payload,
                                   batch_id=item.get("batch_id"))
            ctx.log("[refill] 补插 discover item")

    def after_item(self, ctx, item) -> None:
        pass

    def empty_message(self) -> str:
        return "没有待认领的 work_item 了"

    # ---- work_items 辅助 ----

    def _insert_work_item(self, db, payload: dict,
                          batch_id: int | None = None) -> int:
        """向 work_items 插 pending 行，返回 id。

        batch_id 非空时写入批次归属（P4 平台批次）；None 为 daemon 自喂。
        """
        if batch_id is not None:
            cur = db.conn.execute(
                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
                " created_at) VALUES (?, ?, ?, ?, datetime('now','localtime'))",
                (self.QUEUE, self.SITE, batch_id,
                 json.dumps(payload, ensure_ascii=False)))
        else:
            cur = db.conn.execute(
                "INSERT INTO work_items (queue, site, payload_json, created_at)"
                " VALUES (?, ?, ?, datetime('now','localtime'))",
                (self.QUEUE, self.SITE, json.dumps(payload, ensure_ascii=False)))
        db.conn.commit()
        return cur.lastrowid

    def _batch_reached_limit(self, db, item: dict) -> bool:
        """批次收束判定：item 属批次且 batch_limit>0 时，该批次已 done
        计数 ≥ batch_limit 返回 True（停止续喂/补插）。

        batch_id 为 None（daemon 自喂）或 batch_limit<=0（不限）恒 False。
        """
        batch_id = item.get("batch_id")
        limit = item.get("batch_limit", 0)
        if batch_id is None or not limit:
            return False
        done = db.conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE batch_id=? "
            "AND status='done'", (batch_id,)).fetchone()[0]
        return done >= limit

    def _count_pending_by_kind(self, db, kind: str, keyword: str = None) -> int:
        """统计同 kind（+可选 keyword）的 pending item 数量。"""
        if keyword is not None:
            return db.conn.execute(
                "SELECT COUNT(*) FROM work_items WHERE queue=?"
                " AND status='pending'"
                " AND json_extract(payload_json, '$.kind')=?"
                " AND json_extract(payload_json, '$.keyword')=?",
                (self.QUEUE, kind, keyword)).fetchone()[0]
        return db.conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE queue=?"
            " AND status='pending'"
            " AND json_extract(payload_json, '$.kind')=?",
            (self.QUEUE, kind)).fetchone()[0]


# 向后兼容别名（P3 Step 5.1 重构前后兼容）
ShopTask = Alibaba1688ShopTask
