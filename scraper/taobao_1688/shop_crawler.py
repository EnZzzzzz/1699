#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 店铺 URL 采集（任务层 · 多 worker 并发由 common 网络层引擎驱动）

任务内容：从 1688 首页提取类目入口（类目 = 关键词搜索页），随机挑选
类目翻页采集：搜索结果页内嵌数据（window.data.offerV2...OFFER.items）
自带商家信息（shop.text 公司名 / shopAddition.shopLinkUrl 店铺 URL），
无需点进商品详情页（已验证：一页 60 个商品直接给出 60 个店铺 URL，
比逐个商品点击进店少 60 倍请求，风控暴露面最小），直接解析出店铺
域名入库 .cache/1688.db 的 shops 表（status=pending），供
contact_fetcher.py 消费抓取联系方式。

本文件只含任务层逻辑：
    - fetch_homepage_categories / scrape_category  类目与搜索页解析
    - CategoryPool                                 类目队列（进程内互斥）
    - ShopTask                                     任务定义与店铺入库
网络层（Cookie 按出口 IP 隔离、青果代理通道、浏览器生命周期、风控
状态机、批次休息、状态板）全部在 common.py 的 FetchTask / run_workers
引擎里，与 contact_fetcher.py 共用同一套，禁止在这里另写网络逻辑。

结果处理:
    - 一页提取到店铺 → upsert 进 shops 表（新店铺 status=pending，
      已存在的只更新 last_seen，不动联系方式抓取进度）
    - 空页或 hasMore=false → 类目标记 exhausted，之后采集跳过
    - 抓取失败 → 页码不前进，下次运行从该页重采

断点续采:
    每个类目的 next_page 记在 category_progress，随时 Ctrl+C 或重启
    脚本，下次运行从各类目上次页码继续；exhausted 类目自动跳过。

用法:
    export CLOAKBROWSER_LICENSE_KEY=cb_xxx   # 或直接写进 .cache/config.json
    python3 shop_crawler.py --proxy              # 5 通道 5 worker 并发
    python3 shop_crawler.py --proxy -n 500       # 每个 worker 每批 500 个店铺
    python3 shop_crawler.py --proxy --max-batches 2   # 最多采 2 批
    python3 shop_crawler.py --proxy --headed     # 有头模式（首次过滑块）
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from pathlib import Path

from common import (HOMEPAGE, FetchTask, add_common_args, browser_alive,
                    is_fatal_browser_error, is_network_error,
                    page_block_reason, run_workers)
from database import ShopDB

# 滑块兜底：真人轨迹回放自动过证（轨迹库 util/tracks.json，录入/测试见
# util/slider_track.py）。导入失败时退化为纯检测（原有换 IP 重试行为）。
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "util"))
try:
    from slider_track import solve_all_sliders
except Exception:
    solve_all_sliders = None


# ---------- 类目搜索页解析（任务层：采什么） ----------

SEARCH_URL_TPL = ("https://s.1688.com/selloffer/offer_search.htm"
                  "?charset=utf8&keywords={keyword}&beginPage={page}")

# 搜索域落地页（低敏）：用于 mtop 握手，不直接碰 offer_search 深链
SEARCH_HOME = "https://s.1688.com/"


def build_search_url(keyword: str, page_no: int = 1) -> str:
    """构造类目搜索页 URL（1688 首页类目本质就是关键词搜索页）。"""
    from urllib.parse import quote
    return SEARCH_URL_TPL.format(keyword=quote(keyword), page=page_no)


# ---------- mtop 握手（搜索域入场券） ----------
#
# 实测（2026-08-03）：offer_search 的数据走 mtop API（h5api.m.1688.com），
# 会话必须持有 _m_h5_tk 令牌才放行；无令牌的匿名会话直接踢登录墙
# （marketSigninJump），凌晨严格时段首请求即踢，连滑块都不给。
# 今晚数据：健康会话全部持有 _m_h5_tk；被秒踢的新会话全部没有。
# 因此：正式翻页前先在低敏落地页完成握手拿令牌，拿不到就不碰搜索。


def _has_mtop_token(page) -> bool:
    try:
        return any(c["name"] == "_m_h5_tk"
                   for c in page.context.cookies()
                   if "1688.com" in c.get("domain", ""))
    except Exception:
        return False


def ensure_mtop_token(page, log=None, attempts: int = 2) -> bool:
    """确保会话持有 _m_h5_tk：没有就访问搜索域落地页触发 mtop 令牌
    签发（最多 attempts 次）。拿到返回 True；拿不到返回 False，
    调用方应放弃本次搜索采集（无令牌裸奔 = 白烧 IP）。"""
    if _has_mtop_token(page):
        return True
    for i in range(attempts):
        try:
            page.goto(SEARCH_HOME, wait_until="domcontentloaded",
                      timeout=60000, referer=HOMEPAGE)
            time.sleep(random.uniform(2.5, 4.5))
        except Exception:
            pass
        if _has_mtop_token(page):
            if log:
                log(f"mtop 握手完成（第 {i + 1} 次尝试），"
                    f"会话已持有 _m_h5_tk")
            return True
    return False


# 从首页提取类目入口：首页的「类目」链接全部指向
# s.1688.com/selloffer/offer_search.htm?...&keywords=xxx，
# 类目 = 搜索关键词，名字取链接文本。
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

# 从搜索结果页内嵌数据提取商家店铺。
# 页面 window.data.offerV2.response.data.OFFER.items[] 每个商品自带
# 商家信息（无需点进商品详情页）：
#   data.shop.text            公司/店铺名
#   data.loginId              旺旺登录名
#   data.shopAddition.shopLinkUrl  店铺 URL（shopxxx.1688.com）
# shop / shopAddition 偶尔是被截断的 JSON 字符串而非对象，做双格式兜底。
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
    """访问 1688 首页并提取类目入口 [{name, keyword}, ...]。

    首页类目链接就是关键词搜索页，类目即关键词。失败返回空列表，
    调用方用内置种子类目兜底。
    """
    try:
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
        cats = page.evaluate(_JS_EXTRACT_CATEGORIES) or []
        return [c for c in cats if c.get("keyword")]
    except Exception:
        return []


def scrape_category(page, keyword: str, page_no: int = 1,
                    data_wait: float = 15.0) -> dict | None:
    """抓取一页类目搜索结果，提取商家店铺列表。

    返回值约定（引擎按优先级判断）：
        - 正常：dict，含 shops / has_more / found / _source_url / _blocked；
          shops=[] 且未被风控 = 该类目已采到末页（exhausted）
        - 浏览器进程死亡/被关闭（非风控）：{"_fatal": <原因>}
        - 网络/代理层错误（非风控）：{"_net_error": <原因>}
        - 其他异常：None（按风控处理）
    """
    url = build_search_url(keyword, page_no)
    try:
        # 无 mtop 令牌不碰搜索：先尝试补握手，仍无令牌则按风控交引擎
        # 换 IP（无令牌裸奔搜索 = 首请求即踢登录墙，白烧 IP）
        if not _has_mtop_token(page) and not ensure_mtop_token(page):
            return {"_blocked": "会话缺少 mtop 令牌（_m_h5_tk），"
                                "搜索域入场券未获取，未触碰搜索"}
        # referer 链条：第 1 页来自首页，第 N 页来自第 N-1 页搜索页
        # （真人翻页的 referer 是上一页搜索页，永远挂首页是机器特征）
        referer = (HOMEPAGE if page_no <= 1
                   else build_search_url(keyword, page_no - 1))
        page.goto(url, wait_until="domcontentloaded", timeout=60000,
                  referer=referer)
        time.sleep(random.uniform(1.0, 2.0))
        # 滑块兜底：命中风控/待验证时先尝试自动过证（与 contact_fetcher
        # 同策略：点击重置 → 刷新 → 换轨迹再试，最多 5 次），过证后
        # 照常等数据解析；过不了则 _blocked 检测兜底，由引擎换 IP 重试。
        # 不先过证的话，拦截页上 offerV2 数据永远不就绪，会白等
        # data_wait 秒再原样返回
        if solve_all_sliders is not None and page_block_reason(page):
            try:
                if solve_all_sliders(page, max_attempts=5):
                    time.sleep(random.uniform(1.5, 2.5))  # 等真实内容渲染
            except Exception:
                pass  # 过证异常不阻断，交给 _blocked 判定兜底
        # 等异步搜索结果数据就绪（轮询，不加重风控）
        deadline = time.monotonic() + data_wait
        ready = False
        while time.monotonic() < deadline:
            try:
                if page.evaluate(_JS_DATA_READY):
                    ready = True
                    break
            except Exception:
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
        return {
            "shops": shops,
            "has_more": result.get("hasMore") == "true",
            "found": result.get("found") or "0",
            "_source_url": page.url,
            "_blocked": page_block_reason(page),
        }
    except Exception as e:
        reason = str(e).splitlines()[0][:200]
        # 1) 浏览器进程级致命错误（会话被服务端关闭、崩溃等），优先识别
        if is_fatal_browser_error(e):
            return {"_fatal": reason}
        # 2) 网络/代理层错误
        if is_network_error(e):
            return {"_net_error": reason}
        # 3) 其他异常（多为 goto 超时）：先鉴别浏览器是不是已经死了
        if not browser_alive(page):
            return {"_fatal": f"浏览器连接断开: {reason}"}
        return None


# ---------- 类目队列（任务层：相当于 contact 的 shops pending 队列） ----------

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
    """类目池：进程内共享，线程安全（相当于 contact_fetcher 里的
    shops 表 pending 队列，只是队列在内存里、页码进度在
    category_progress 表里）。

    - pool: {keyword: name}，首次由某个 worker 从首页提取（其后复用）；
    - in_progress: 正被某 worker 采集的类目（互斥，相当于
      shops.status='in_progress'，避免两 worker 采同一类目撞页）；
    - exhausted: 已采到末页的类目（启动时从 category_progress 加载，
      采到末页时即时更新）。
    """

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


# ---------- 任务定义 ----------

class ShopTask(FetchTask):
    """店铺 URL 采集任务：随机类目 → 搜索页 → 店铺域名入库。

    任务项为 (keyword, cat_name, page_no) 三元组；类目占用与
    exhausted 标记由 CategoryPool 管，页码进度由 category_progress 表管。
    """

    unit = "页"
    batch_unit = "店铺"
    # 冷启动要先逛首页提取类目填满类目池，必须在 acquire（选类目）之前
    cold_start_before_acquire = True
    # 搜索页匿名配额墙实测阈值 18~26 页（2026-08-03）：每出口 IP 采满
    # 12 个搜索页请求即主动换 IP，把「被配额墙踢掉」变成「主动全身而退」
    ip_request_budget = 12

    def __init__(self):
        self.cat_pool: CategoryPool | None = None

    # ---- main 阶段 ----

    def prepare(self, args) -> bool:
        db = ShopDB()
        # 已采到末页的类目启动时载入，之后采集自动跳过
        exhausted = db.get_exhausted_keywords()
        if exhausted:
            print(f"[0] 已采到末页的类目 {len(exhausted)} 个，自动跳过")
        self.cat_pool = CategoryPool(exhausted)

        st = db.stats()
        print(f"[1] 数据库现有店铺 {st['shops']} 个（pending {st['pending']} / "
              f"done {st['done']} / no_contact {st['no_contact']} / "
              f"failed {st['failed']}），每个 worker 每批 {args.num} 个店铺"
              f"（{'最多 ' + str(args.max_batches) + ' 批' if args.max_batches else '不限批数'}），"
              f"批间强制休息 {args.batch_rest / 60:.0f} 分钟")
        db.close()
        return True

    def summary(self, all_stats: dict) -> str:
        shops = sum(s["shops"] for s in all_stats.values())
        new = sum(s["new"] for s in all_stats.values())
        pages = sum(s["pages"] for s in all_stats.values())
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

    def cold_start(self, page, item, log=None) -> None:
        """新会话先逛 1688 首页留真实浏览轨迹，顺带提取首页类目填池
        —— 新会话一上来就深链搜索页是明显的爬虫特征。"""
        cats = fetch_homepage_categories(page)
        if not cats:
            cats = [{"name": n, "keyword": k} for n, k in SEED_CATEGORIES]
            if log:
                log(f"[!] 首页类目提取失败，"
                    f"使用内置种子类目（{len(cats)} 个）")
        n = self.cat_pool.refresh(cats)
        if n and log:
            log(f"类目池新增 {n} 个类目"
                f"（可采 {self.cat_pool.available()}，"
                f"跳过已采完 {len(self.cat_pool.exhausted)}）")
        # mtop 握手：搜索页数据走 mtop API，会话须持有 _m_h5_tk 再碰
        # offer_search；拿不到就记日志，scrape 会拒绝无令牌裸奔
        if not ensure_mtop_token(page, log=log) and log:
            log("[!] mtop 握手未拿到 _m_h5_tk，本会话搜索采集将被搁置"
                "（scrape 逐页重试握手，仍无令牌则交引擎换 IP）")

    def acquire(self, db, wctx: dict):
        picked = self.cat_pool.pick()
        if not picked:
            return None
        keyword, cat_name = picked
        prog = db.get_category_progress(keyword)
        page_no = prog["next_page"] if prog else 1
        return (keyword, cat_name, page_no)

    def label(self, item) -> str:
        return f"{item[1]} p{item[2]}"

    def scrape(self, page, item) -> dict | None:
        keyword, _cat_name, page_no = item
        return scrape_category(page, keyword, page_no)

    def on_success(self, db, item, info: dict, wctx: dict,
                   set_status, log) -> int:
        keyword, cat_name, page_no = item
        stats = wctx["stats"]
        page_shops = info["shops"]
        has_more = info["has_more"]
        run_id = db.start_run(cat_name, keyword)
        n_new = db.upsert_shops(page_shops, run_id=run_id,
                                category_keyword=keyword)
        db.finish_run(run_id, shops_found=len(page_shops),
                      shops_picked=n_new, note=f"page={page_no}")
        if not page_shops or not has_more:
            # 空页或官方说没有下一页：该类目采到末页
            db.mark_category_exhausted(keyword, cat_name)
            wctx["exhausted"] = True  # after_item 释放占用时顺手标记
            set_status(state=f"■ {cat_name} 采到末页，标记 exhausted")
            log(f"■ 类目 {cat_name} 第 {page_no} 页 "
                f"{len(page_shops)} 店，hasMore={has_more}，"
                f"采到末页标记 exhausted")
        else:
            db.advance_category_page(keyword, cat_name,
                                     shops_found=len(page_shops))
            set_status(state=f"✓ {len(page_shops)} 店（新 {n_new}）")
        stats["shops"] += len(page_shops)
        stats["new"] += n_new
        stats["pages"] += 1
        set_status(n=stats["shops"], new=stats["new"], pages=stats["pages"])
        return len(page_shops)  # 批次配额按提取到的店铺数计

    def on_giveup(self, db, item, reason: str, kind: str, wctx: dict,
                  set_status, log) -> str:
        # 页码不前进（不 advance），下次运行从该页重采；
        # 类目占用由 after_item 释放
        return "跳过该页，页码不前进下次重采"

    def on_abort(self, item) -> str:
        return (f"类目 {item[0]} 第 {item[2]} 页页码不前进，"
                f"下次运行自动续采")

    def after_item(self, item, wctx: dict) -> None:
        # 释放类目占用（采到末页的顺手标记，之后所有 worker 都跳过）
        self.cat_pool.release(item[0],
                              exhausted=wctx.pop("exhausted", False))

    def empty_message(self) -> str:
        return "没有可采的类目了（全部采完或被占用）"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="1688 店铺 URL 采集（任务层；随机类目搜索页 → 店铺入库，"
                    "多 worker 并发/风控状态机由 common 网络层引擎驱动）")
    ap.add_argument("-n", "--num", type=int, default=200,
                    help="每个 worker 每批采集的店铺数量（默认 200）；"
                         "采满一批后各自强制休息再开下一批")
    add_common_args(ap)
    ap.set_defaults(rest_every=15)  # 本任务按页长休息，默认 15 页一次
    args = ap.parse_args()

    task = ShopTask()
    if not task.prepare(args):
        return 0
    return run_workers(args, task)


if __name__ == "__main__":
    sys.exit(main())
