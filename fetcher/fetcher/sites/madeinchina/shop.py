# -*- coding: utf-8 -*-
"""中国制造网(cn.made-in-china.com) 供应商展厅 URL 采集任务。

任务内容：从 madeinchina 首页 + 市场导航页（/shichang/）提取类目入口
（类目 = 行业市场 market 分页页，slug 是拼音缩写如 wujingj=五金工具，
不透明），随机挑类目翻页采集 market 页，解析页内的供应商展厅子域名
（{showroom}.cn.made-in-china.com）入库 shops 表（status=pending），
供 contact 任务消费。首页只暴露 ~129 个 market 类目（2026-08-06 已全部
采干），类目主力入口是市场导航页（~947 个类目）。

进度：每个类目的 next_page 记在 category_progress；空页或没有下一页
（has_more=false）标记 exhausted 之后跳过；抓取失败页码不前进。

与 1688 ShopTask 的有意差异：
    - 无 mtop 握手（免登录、纯静态市场页，无 API 入场券）
    - 类目 slug 不透明，首页提取失败用内置种子兜底
    - has_more 判定：分页锚点 next 或满页（≥20 链接）两档，宁可多打一页
      也绝不提前停
    - 过滤平台子域名（caigou/membercenter 等导航/页脚链接），只留真供应商
"""

from __future__ import annotations

import random
import threading
import time

from fetcher.control.task import Task
from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.madeinchina.features import (
    HOMEPAGE,
    MARKET_DIR,
    SHOWROOM_DOMAIN_SUFFIX,
)

MARKET_URL_TPL = "https://cn.made-in-china.com/market/{slug}_2-{page}.html"


def build_market_url(slug: str, page_no: int = 1, fmt: str = "x2") -> str:
    """构造行业市场分页页 URL。

    fmt 决定 URL 体系：
      "x2"    -> {slug}_2-{page}.html（静态锚点分页，bxgyxg 等）
      "plain" -> {slug}-{page}.html（JS 分页，jgdbj/huafangchuan 等）
    同一 slug 在两种体系下是不同类目，必须用提取时记录的 fmt。
    """
    if fmt == "plain":
        return f"https://cn.made-in-china.com/market/{slug}-{page_no}.html"
    return MARKET_URL_TPL.format(slug=slug, page=page_no)


# 连续零新增判定为「该类目实际已采完」的页数阈值：健康分页每页必有新增，
# 连续 N 页提取到的全是已入库重复（服务端分页夹取回第 1 页 / 真采完）即标
# exhausted，防止被 has_more「满页≥20」启发式骗到永不停止（实测 bxgyxg
# 单页类目被深挖到 176 页，5075 声称找到仅 29 家真实入库）
ZERO_NEW_LIMIT = 2


# 平台自身子域名（导航/页脚/登录/行业入口等），非供应商展厅，过滤掉
PLATFORM_SUBDOMAINS = {
    "cn", "www", "m", "login", "membercenter", "service", "big5", "en",
    "es", "pt", "fr", "ru", "it", "de", "nl", "sa", "kr", "jp", "hi",
    "th", "tr", "vi", "id", "caigou", "zhanhui", "image", "supervisor",
    "purchase", "sourcing", "trading", "expo", "ai", "data", "insights",
    "world", "micstatic", "3g", "member",
}


def is_platform_subdomain(sub: str) -> bool:
    """展厅子域名是否平台自身子域（过滤用）。"""
    return sub in PLATFORM_SUBDOMAINS


# 从首页/市场导航页提取类目入口：类目链接有两种独立体系——
#   /market/{slug}_2-N.html   _2- 体系（静态 _2-N.html 锚点分页，如 bxgyxg）
#   /market/{slug}-N.html     -N 体系（JS submitSearchByPage 分页，如 jgdbj）
# 同一 pinyin slug 在两种体系下是**不同类目**（如 jgdbj_2=秸秆打包机、
# jgdbj=激光打标机），所以 fmt 必须随 slug 一起记录，构造 URL 时用对应格式。
# slug 从 URL 抽；`_1-N.html` 是移动端 chanpin 变体（302 到 3g），排除。
_JS_EXTRACT_CATEGORIES = """
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/market/"]')
    .forEach(a => {
      const href = a.href || '';
      const m = href.match(/\\/market\\/([a-zA-Z0-9]+?)(?:_2)?-\\d+\\.html/);
      const name = (a.textContent || '').trim();
      if (m && name && name.length <= 20 && !seen.has(m[1])) {
        seen.add(m[1]);
        out.push({slug: m[1], name,
                  fmt: m[0].includes('_2-') ? 'x2' : 'plain'});
      }
    });
  return out;
}
"""

# 从 market 分页页提取供应商展厅子域名 + 分页锚点 next
_JS_EXTRACT_SHOWROOMS = """
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*=".cn.made-in-china.com"]')
    .forEach(a => {
      let host = '';
      try { host = new URL(a.href, location.href).hostname; } catch (e) { return; }
      host = (host || '').toLowerCase();
      if (!/^[a-z0-9][a-z0-9\\-]*\\.cn\\.made-in-china\\.com$/.test(host)) return;
      if (seen.has(host)) return;
      seen.add(host);
      out.push({domain: host, name: (a.textContent || '').trim().slice(0, 60)});
    });
  // next 判定按当前页 URL 体系分派：
  //   _2-N：静态锚点 a[href*="{slug}_2-{n+1}.html"]（页面里带分页锚点）
  //   -N  ：JS 分页按钮（submitSearchByPage / page-next），有「下一页」即 next
  let next = false;
  const m = (location.pathname || '').match(/\\/market\\/([a-zA-Z0-9]+?)(?:_2)?-(\\d+)\\.html$/);
  if (m) {
    if (m[0].includes('_2-')) {
      const suffix = m[1] + '_2-' + (parseInt(m[2], 10) + 1) + '.html';
      next = !!document.querySelector('a[href*="' + suffix + '"]');
    } else {
      const n = parseInt(m[2], 10) + 1;
      next = !!document.querySelector('a.page-next')
          || !!document.querySelector('a[href*="submitSearchByPage(' + n + ')"]');
    }
  }
  return {shops: out, next, found: String(out.length)};
}
"""


def fetch_market_categories(page, url: str) -> list[dict]:
    """访问指定页面提取 market 类目入口 [{slug, name, fmt}, ...]，失败返回 []。

    首页与市场导航页（/shichang/）通用：链接格式相同（_2-N / -N 两种体系），
    同一个 _JS_EXTRACT_CATEGORIES 正则都认。
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
        cats = page.evaluate(_JS_EXTRACT_CATEGORIES) or []
        return [c for c in cats if c.get("slug")]
    except Exception:  # noqa: BLE001
        return []


# 首页与市场导航页类目提取均失败时的兜底种子（slug 是拼音缩写，首次实测
# 确认的放进来，其余待真实运行从导航页提取后沉淀）
SEED_CATEGORIES = [
    ("wujingj", "五金工具"),
]


class CategoryPool:
    """类目池：进程内共享，线程安全（相当于 contact 的 shops pending
    队列，只是队列在内存里、页码进度在 category_progress 表里）。"""

    def __init__(self, exhausted: set):
        self.lock = threading.Lock()
        self.pool: dict = {}
        self.fmt: dict = {}          # slug -> "x2" | "plain"（URL 体系）
        self.in_progress: set = set()
        self.exhausted: set = set(exhausted)

    def pick(self) -> tuple[str, str] | None:
        """随机挑一个可采类目并占用；无可采类目返回 None。"""
        with self.lock:
            candidates = [slug for slug in self.pool
                          if slug not in self.exhausted
                          and slug not in self.in_progress]
            if not candidates:
                return None
            slug = random.choice(candidates)
            self.in_progress.add(slug)
            return slug, self.pool.get(slug) or slug

    def release(self, slug: str, exhausted: bool = False):
        with self.lock:
            self.in_progress.discard(slug)
            if exhausted:
                self.exhausted.add(slug)

    def refresh(self, cats: list[dict]) -> int:
        """合并首页提取到的类目，返回新增数量。cat 项可带 fmt（x2/plain，
        缺省按 x2，与历史 `_2-` 采集一致）。"""
        with self.lock:
            n = 0
            for c in cats:
                slug = c.get("slug")
                if slug and slug not in self.pool:
                    self.pool[slug] = c.get("name") or slug
                    self.fmt[slug] = c.get("fmt", "x2")
                    n += 1
            return n

    def available(self) -> int:
        with self.lock:
            return len([slug for slug in self.pool
                        if slug not in self.exhausted
                        and slug not in self.in_progress])

    def has_active(self) -> bool:
        """池里是否还有未采完的类目（无论是否被其他 worker 暂占）。

        pick() 返回 None 时用它区分「真采完」和「全被暂占」：还有活跃
        类目但都 in_progress = 被其他 worker 占着，应空转等待而非退出。
        """
        with self.lock:
            return any(slug not in self.exhausted for slug in self.pool)


class MadeInChinaShopTask(Task):
    """中国制造网供应商展厅采集：work_items 驱动 + 单类目页处理。

    work_items payload：
      - 类目页：{"kind":"category","keyword":<slug>,"name":<cat_name>,
                 "fmt":"x2"|"plain"}
        page_no 不进 payload——处理时读 category_progress.next_page
      - 发现：{"kind":"discover"}
        执行 = 首页+市场导航页提取类目，新类目逐条 INSERT category item

    链式续喂：category item on_success 后若未采完则 INSERT 下一页 item
    （同 payload，attempts=0）；ZERO_NEW_LIMIT 连续零新增保护。
    失败补插：refill_item 在 attempts 耗尽时补插同 payload 新 item。
    """

    name = "shop"
    unit = "页"
    batch_unit = "店铺"
    # 冷启动要先逛首页（软着陆），必须在 acquire 之前
    cold_start_before_acquire = True
    # market 分页页反爬阈值未知，先保守：每出口 IP 采满 60 页主动换 IP [CAL]
    ip_request_budget = 60

    QUEUE = "crawl_mic_shop"
    SITE = "madeinchina"

    def __init__(self):
        # 每类目连续零新增页数（slug -> int），见 ZERO_NEW_LIMIT 说明。
        # 类目 item 是串行链式的（下一页 item 只在上一页成功后插入），
        # 同类目不会并发写，但保留锁防御。
        self.zero_new: dict = {}
        self._zero_lock = threading.Lock()

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        exhausted = db.get_exhausted_keywords()
        if exhausted:
            print(f"[0] 已采到末页的类目 {len(exhausted)} 个，自动跳过")
        # 播种：活跃拼音类目逐条插 category item + 一条 discover item
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
        """活跃拼音类目逐条插 category item（已有同 keyword pending 跳过）。

        经 iter_active_categories 取全量未采完类目，再 _is_pinyin_slug
        过滤拼音 slug（与 get_active_categories 同口径）。

        ⚠️ 已知局限：category_progress 不含 fmt 字段，播种一律 "x2"；
        plain 体系类目（如 jgdbj）首次 fetch 会拼错 URL 而失败；
        discover 从页面提取时带正确 fmt 后纠正。Step 4.2 若 category_progress
        加 fmt 列可根除。
        """
        # 本地拼音判断（与 db._is_pinyin_slug 同义，避免跨模块导私有函数）
        import re
        _pinyin_re = re.compile(r"^[a-zA-Z0-9_]+$")
        active = [cat for cat in db.iter_active_categories()
                  if _pinyin_re.match(cat["keyword"])]
        n = 0
        for cat in active:
            slug = cat["keyword"]
            name = cat.get("name", slug)
            existing = self._count_pending_by_kind(db, "category", slug)
            if existing > 0:
                continue
            # fmt 默认 x2（局限见上），discover 提取时带正确 fmt 覆盖
            payload = {"kind": "category", "keyword": slug,
                       "name": name, "fmt": "x2"}
            self._insert_work_item(db, payload)
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
        """新会话先逛首页 + 市场导航页留真实浏览轨迹（纯软着陆，不提取类目）。

        类目提取归 discover item 的 on_success 处理。
        """
        try:
            ctx.page.goto(HOMEPAGE, wait_until="domcontentloaded",
                          timeout=60000)
            time.sleep(random.uniform(2.0, 4.0))
            ctx.page.goto(MARKET_DIR, wait_until="domcontentloaded",
                          timeout=60000)
            time.sleep(random.uniform(2.0, 4.0))
        except Exception:  # noqa: BLE001
            # 浏览失败不阻塞任务
            ctx.log("[!] 冷启动浏览失败，继续认领工作项")

    def acquire_item(self, ctx):
        """从 work_items 队列认领（CLI 与 daemon 同一路径）。"""
        consumer_id = f"w{ctx.wid}"
        db = ctx.store.db
        item = db.claim_next_eligible([self.QUEUE], consumer_id)
        if item is None:
            return None
        # item = {"id", "queue", "site", "payload"}
        payload = dict(item["payload"])
        payload["id"] = item["id"]  # 保留 id 供 refill / 日志
        return payload

    def label(self, item) -> str:
        kind = item.get("kind", "")
        if kind == "discover":
            return "discover"
        kw = item.get("keyword", "?")
        name = item.get("name", kw)
        return f"{name}"

    def fetch(self, ctx, item) -> ActionResult:
        """按 kind 分派：category → 抓 market 页，discover → 返回标记。"""
        kind = item.get("kind", "")
        if kind == "discover":
            return ActionResult(Outcome.OK, "discover", {"discover": True})
        if kind == "category":
            return self._fetch_category(ctx, item)
        return ActionResult.fatal(f"未知 kind: {kind}")

    def _fetch_category(self, ctx, item) -> ActionResult:
        """抓取一页 market 分页页，提取供应商展厅子域名列表。

        page_no 从 category_progress 运行时读（单一事实来源）。
        """
        page = ctx.page
        db = ctx.store.db
        slug = item["keyword"]
        name = item.get("name", slug)
        fmt = item.get("fmt", "x2")
        prog = db.get_category_progress(slug)
        page_no = prog["next_page"] if prog else 1
        url = build_market_url(slug, page_no, fmt=fmt)
        try:
            referer = (HOMEPAGE if page_no <= 1
                       else build_market_url(slug, page_no - 1, fmt=fmt))
            page.goto(url, wait_until="domcontentloaded", timeout=60000,
                      referer=referer)
            time.sleep(random.uniform(2.0, 4.0))
            result = page.evaluate(_JS_EXTRACT_SHOWROOMS) or {}
            shops = []
            seen = set()
            for it_ in result.get("shops") or []:
                domain = (it_.get("domain") or "").strip().lower()
                if not domain.endswith(SHOWROOM_DOMAIN_SUFFIX):
                    continue
                sub = domain[: -len(SHOWROOM_DOMAIN_SUFFIX)]
                if is_platform_subdomain(sub) or domain in seen:
                    continue
                seen.add(domain)
                shops.append({"domain": domain,
                              "name": it_.get("name"),
                              "url": f"https://{domain}"})
            return ActionResult(Outcome.OK, "已解析 market 分页页", {
                "shops": shops,
                "has_more": bool(result.get("next")) or len(shops) >= 20,
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
        """discover 成功：提取类目 → 新类目逐条 INSERT category item。"""
        db = ctx.store.db
        page = ctx.page
        # 提取首页 + 市场导航页类目
        home_cats = fetch_market_categories(page, HOMEPAGE)
        dir_cats = fetch_market_categories(page, MARKET_DIR)
        cats = list({c["slug"]: c for c in home_cats + dir_cats}.values())
        if not cats:
            cats = [{"name": n, "slug": k} for k, n in SEED_CATEGORIES]
            ctx.log(f"[!] 首页与市场导航页类目提取均失败，"
                    f"使用内置种子类目（{len(cats)} 个）")
        n = 0
        for c in cats:
            slug = c["slug"]
            # 跳过已 exhausted
            prog = db.get_category_progress(slug)
            if prog and prog.get("exhausted"):
                continue
            # 跳过已有同 keyword pending category item
            if self._count_pending_by_kind(db, "category", slug) > 0:
                continue
            payload = {"kind": "category", "keyword": slug,
                       "name": c.get("name", slug),
                       "fmt": c.get("fmt", "x2")}
            self._insert_work_item(db, payload)
            n += 1
        if n:
            ctx.log(f"discover 产出 {n} 个新类目 category item")
        return 0  # discover 不计入页数

    def _on_category_success(self, ctx, item, result: ActionResult) -> int:
        """category 成功：入库 shops → 零新增判定 → 链式续喂。"""
        db = ctx.store.db
        stats = ctx.state["task"]["stats"]
        slug = item["keyword"]
        cat_name = item.get("name", slug)
        prog = db.get_category_progress(slug)
        page_no = prog["next_page"] if prog else 1
        page_shops = result.data["shops"]
        has_more = result.data["has_more"]
        run_id = db.start_run(cat_name, slug)
        n_new = db.upsert_shops(page_shops, run_id=run_id,
                                category_keyword=slug)
        db.finish_run(run_id, shops_found=len(page_shops),
                      shops_picked=n_new, note=f"page={page_no}")
        exhausted = False
        if not page_shops or not has_more:
            db.mark_category_exhausted(slug, cat_name)
            with self._zero_lock:
                self.zero_new[slug] = 0
            exhausted = True
            ctx.set_status(state=f"■ {cat_name} 采到末页，标记 exhausted")
            ctx.log(f"■ 类目 {cat_name} 第 {page_no} 页 "
                    f"{len(page_shops)} 店，hasMore={has_more}，"
                    f"采到末页标记 exhausted")
        elif n_new == 0:
            with self._zero_lock:
                streak = self.zero_new.get(slug, 0) + 1
                self.zero_new[slug] = streak
            if streak >= ZERO_NEW_LIMIT:
                db.mark_category_exhausted(slug, cat_name)
                with self._zero_lock:
                    self.zero_new[slug] = 0
                exhausted = True
                ctx.set_status(
                    state=f"■ {cat_name} 连续 {ZERO_NEW_LIMIT} 页零新增，"
                          f"标记 exhausted")
                ctx.log(f"■ 类目 {cat_name} 第 {page_no} 页 "
                        f"{len(page_shops)} 店但全部重复（new=0），"
                        f"连续 {ZERO_NEW_LIMIT} 页零新增，标记 exhausted")
            else:
                db.advance_category_page(slug, cat_name,
                                         shops_found=len(page_shops))
                ctx.set_status(
                    state=f"○ {len(page_shops)} 店全重复（new=0，"
                          f"{streak}/{ZERO_NEW_LIMIT}）")
        else:
            with self._zero_lock:
                self.zero_new[slug] = 0
            db.advance_category_page(slug, cat_name,
                                     shops_found=len(page_shops))
            ctx.set_status(state=f"✓ {len(page_shops)} 店（新 {n_new}）")
        stats["shops"] += len(page_shops)
        stats["new"] += n_new
        stats["pages"] += 1
        ctx.set_status(n=stats["shops"], new=stats["new"],
                       pages=stats["pages"])
        # 链式续喂：未采完则 INSERT 下一页 item
        if not exhausted:
            payload = {"kind": "category", "keyword": slug,
                       "name": cat_name, "fmt": item.get("fmt", "x2")}
            self._insert_work_item(db, payload)
        return len(page_shops)

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        return "跳过该页，页码不前进下次重采"

    def on_abort(self, ctx, item) -> str:
        kw = item.get("keyword", "?")
        return f"类目 {kw} 页码不前进，下次运行自动续采"

    def refill_item(self, ctx, item) -> None:
        """attempts 耗尽补插：category 同 payload 新 item（attempts=0），
        discover 也补插一次。"""
        db = ctx.store.db if ctx.store else None
        if db is None:
            return
        kind = item.get("kind", "")
        if kind == "category":
            payload = {"kind": "category",
                       "keyword": item["keyword"],
                       "name": item.get("name", item["keyword"]),
                       "fmt": item.get("fmt", "x2")}
            self._insert_work_item(db, payload)
            ctx.log(f"[refill] 类目 {item.get('keyword')} 补插 category item")
        elif kind == "discover":
            self._insert_work_item(db, {"kind": "discover"})
            ctx.log("[refill] 补插 discover item")

    def after_item(self, ctx, item) -> None:
        pass

    def empty_message(self) -> str:
        return "没有待认领的 work_item 了"

    # ---- work_items 辅助 ----

    @staticmethod
    def _insert_work_item(db, payload: dict) -> int:
        """向 work_items 插 pending 行，返回 id。"""
        import json as _json
        cur = db.conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, created_at)"
            " VALUES (?, ?, ?, datetime('now','localtime'))",
            (MadeInChinaShopTask.QUEUE, MadeInChinaShopTask.SITE,
             _json.dumps(payload, ensure_ascii=False)))
        db.conn.commit()
        return cur.lastrowid

    @staticmethod
    def _count_pending_by_kind(db, kind: str, keyword: str = None) -> int:
        """统计同 kind（+可选 keyword）的 pending item 数量。"""
        if keyword is not None:
            return db.conn.execute(
                "SELECT COUNT(*) FROM work_items WHERE queue=?"
                " AND status='pending'"
                " AND json_extract(payload_json, '$.kind')=?"
                " AND json_extract(payload_json, '$.keyword')=?",
                (MadeInChinaShopTask.QUEUE, kind, keyword)).fetchone()[0]
        return db.conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE queue=?"
            " AND status='pending'"
            " AND json_extract(payload_json, '$.kind')=?",
            (MadeInChinaShopTask.QUEUE, kind)).fetchone()[0]

    @staticmethod
    def _count_pending_category(db, keyword: str) -> int:
        """统计同 keyword 的 pending category item 数量。

        委托 _count_pending_by_kind（保留为向后兼容别名）。
        """
        return MadeInChinaShopTask._count_pending_by_kind(
            db, "category", keyword)
