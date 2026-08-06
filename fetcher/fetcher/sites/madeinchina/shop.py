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
# acquire 空转等待上限：类目池里只剩被其他 worker 暂占的活跃类目时，
# 每 2-5s 重试一次；超过此上限视为卡死/无真实工作可抢，退出 worker
#（避免两个 worker 互相空等永远不退出）。
ACQUIRE_WAIT_MAX = 600.0


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
    """中国制造网供应商展厅采集：随机类目 → market 分页页 → 子域名入库。

    任务项为 (slug, cat_name, page_no) 三元组；类目占用与 exhausted 由
    CategoryPool 管，页码进度由 category_progress 表管。
    """

    name = "shop"
    unit = "页"
    batch_unit = "店铺"
    # 冷启动要先逛首页提取类目填满类目池，必须在 acquire（选类目）之前
    cold_start_before_acquire = True
    # market 分页页反爬阈值未知，先保守：每出口 IP 采满 60 页主动换 IP [CAL]
    ip_request_budget = 60

    def __init__(self):
        self.cat_pool: CategoryPool | None = None
        # 每类目连续零新增页数（slug -> int），见 ZERO_NEW_LIMIT 说明。
        # 任务对象跨 worker 线程共享，计数需加锁（多 worker 同采一类目时
        # 计数要累计而不是互相覆盖）
        self.zero_new: dict = {}
        self._zero_lock = threading.Lock()

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        exhausted = db.get_exhausted_keywords()
        if exhausted:
            print(f"[0] 已采到末页的类目 {len(exhausted)} 个，自动跳过")
        self.cat_pool = CategoryPool(exhausted)
        # 首页只暴露少量 market 链接，类目池不能只靠首页：把进度库里
        # 未采完的拼音类目也播种进来（跨 run 续采，避免搁浅）
        active = db.get_active_categories()
        n_seed = self.cat_pool.refresh(active)
        if n_seed:
            print(f"[0] 从进度库恢复 {n_seed} 个未采完类目"
                  f"（池内可采 {self.cat_pool.available()}）")
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
        """新会话先逛首页 + 市场导航页留真实浏览轨迹，顺带提取类目填满类目池。

        首页只暴露少量 market 链接（~129 个，2026-08-06 已全部采干），类目
        主力入口是市场导航页 /shichang/（~947 个）；两页都提取，按 slug 合并
        去重进池。新会话一上来就深链 market 分页是明显的爬虫特征，所以先逛
        导航类页面。
        """
        home_cats = fetch_market_categories(ctx.page, HOMEPAGE)
        dir_cats = fetch_market_categories(ctx.page, MARKET_DIR)
        # 按 slug 合并去重（首页与导航页重合的类目只占一个坑）
        cats = list({c["slug"]: c for c in home_cats + dir_cats}.values())
        if not cats:
            cats = [{"name": n, "slug": k} for k, n in SEED_CATEGORIES]
            ctx.log(f"[!] 首页与市场导航页类目提取均失败，"
                    f"使用内置种子类目（{len(cats)} 个）")
        n = self.cat_pool.refresh(cats)
        if n:
            ctx.log(f"类目池新增 {n} 个类目（可采 {self.cat_pool.available()}，"
                    f"跳过已采完 {len(self.cat_pool.exhausted)}）")

    def _slug_fmt(self, slug: str) -> str:
        """类目的 URL 体系（x2/plain）。池里没记（如直连测试/DB 播种前）
        时按 x2 兜底，与历史 `_2-` 采集一致。"""
        if self.cat_pool is not None:
            return self.cat_pool.fmt.get(slug, "x2")
        return "x2"

    def acquire_item(self, ctx):
        # 类目池可能被其他 worker 全部暂占（首页 market 链接极少，2 个
        # worker 会抢同一个类目）：此时 pick() 返回 None 但池里仍有活跃
        # 类目，应空转等待释放而非直接退出；仅当真采完才返回 None。
        deadline = time.monotonic() + ACQUIRE_WAIT_MAX
        while not ctx.stopped():
            picked = self.cat_pool.pick()
            if picked:
                slug, cat_name = picked
                prog = ctx.store.db.get_category_progress(slug)
                page_no = prog["next_page"] if prog else 1
                return (slug, cat_name, page_no)
            if not self.cat_pool.has_active():
                return None  # 真采完：没有未采完的类目
            # 有活跃类目但全被其他 worker 暂占：等待释放后重试
            if time.monotonic() >= deadline:
                ctx.set_status(state="⏳ 等类目释放超时，退出")
                return None
            ctx.set_status(state="⏳ 等其他 worker 释放类目…")
            if ctx.wait(random.uniform(2.0, 5.0)):
                return None  # 用户中断
        return None

    def label(self, item) -> str:
        return f"{item[1]} p{item[2]}"

    def fetch(self, ctx, item) -> ActionResult:
        """抓取一页 market 分页页，提取供应商展厅子域名列表。"""
        page = ctx.page
        slug, _cat_name, page_no = item
        fmt = self._slug_fmt(slug)
        url = build_market_url(slug, page_no, fmt=fmt)
        try:
            # referer 链条：第 1 页来自首页，第 N 页来自第 N-1 页 market 页
            referer = (HOMEPAGE if page_no <= 1
                       else build_market_url(slug, page_no - 1, fmt=fmt))
            page.goto(url, wait_until="domcontentloaded", timeout=60000,
                      referer=referer)
            time.sleep(random.uniform(2.0, 4.0))
            result = page.evaluate(_JS_EXTRACT_SHOWROOMS) or {}
            shops = []
            seen = set()
            for it in result.get("shops") or []:
                domain = (it.get("domain") or "").strip().lower()
                if not domain.endswith(SHOWROOM_DOMAIN_SUFFIX):
                    continue
                sub = domain[: -len(SHOWROOM_DOMAIN_SUFFIX)]
                if is_platform_subdomain(sub) or domain in seen:
                    continue
                seen.add(domain)
                shops.append({"domain": domain,
                              "name": it.get("name"),
                              "url": f"https://{domain}"})
            return ActionResult(Outcome.OK, "已解析 market 分页页", {
                "shops": shops,
                # 分页锚点 next 或满页（≥20 链接）两档：宁可多打一页绝不提前停
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
            return ActionResult.blocked(f"页面加载失败（疑似风控拦截）: {reason}")

    def validate(self, ctx, item, result: ActionResult) -> bool:
        """结构化校验：结果必须含 shops 列表（空列表 = 采到末页，合法）。"""
        return isinstance((result.data or {}).get("shops"), list)

    def on_success(self, ctx, item, result: ActionResult) -> int:
        db = ctx.store.db
        stats = ctx.state["task"]["stats"]
        slug, cat_name, page_no = item
        page_shops = result.data["shops"]
        has_more = result.data["has_more"]
        run_id = db.start_run(cat_name, slug)
        n_new = db.upsert_shops(page_shops, run_id=run_id,
                                category_keyword=slug)
        db.finish_run(run_id, shops_found=len(page_shops),
                      shops_picked=n_new, note=f"page={page_no}")
        if not page_shops or not has_more:
            # 空页或没有下一页：该类目采到末页
            db.mark_category_exhausted(slug, cat_name)
            with self._zero_lock:
                self.zero_new[slug] = 0
            ctx.state["task"]["exhausted"] = True  # after_item 顺手标记
            ctx.set_status(state=f"■ {cat_name} 采到末页，标记 exhausted")
            ctx.log(f"■ 类目 {cat_name} 第 {page_no} 页 "
                    f"{len(page_shops)} 店，hasMore={has_more}，"
                    f"采到末页标记 exhausted")
        elif n_new == 0:
            # 提取到店铺但全部是已入库重复（服务端分页夹取回第 1 页 / 真采
            # 完）：健康分页每页必有新增，连续 N 页零新增即视为采完，防止被
            # has_more「满页≥20」启发式骗到永不 exhausted 无限深挖（实测
            # bxgyxg 单页类目被烧到 176 页，5075 声称找到仅 29 家真实）
            with self._zero_lock:
                streak = self.zero_new.get(slug, 0) + 1
                self.zero_new[slug] = streak
            if streak >= ZERO_NEW_LIMIT:
                db.mark_category_exhausted(slug, cat_name)
                with self._zero_lock:
                    self.zero_new[slug] = 0
                ctx.state["task"]["exhausted"] = True
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
                self.zero_new[slug] = 0  # 有新增，重置连续零新增计数
            db.advance_category_page(slug, cat_name,
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
