#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1688 公司黄页采集（找供应商 · 任务层 · 多 worker 并发由 common 引擎驱动）

与 shop_crawler.py（商品搜索 offer_search）完全独立，互不引用：

- 端点：s.1688.com/company/company_search.htm（搜索页顶部「找供应商」
  标签，公司黄页），直出「公司名 + 店铺域名」，无需从商品卡片内嵌
  JSON 里抠 shopAddition —— 对「采店铺联系方式」的目标更直接，
  每页有效产出更高、需要的页数更少，天然省搜索配额
- 业务画像：「查公司」比「翻几十页商品搜索结果」更接近真实采购行为
- 翻页：beginPage 参数（与商品搜索相同，实测 2026-08-03）
- 进度：category_progress 表以 "company:" 前缀存储，与 shop_crawler
  的商品搜索进度完全隔离（同一关键词两个脚本各采各的）

复用 common 引擎层的：mtop 握手（无 _m_h5_tk 不碰黄页）、每 IP 请求
预算（ip_request_budget=12）、风控状态机、滑块自动过证、种子身份池。

用法:
    export CLOAKBROWSER_LICENSE_KEY=cb_xxx   # 或直接写进 .cache/config.json
    python3 company_crawler.py --proxy              # 5 通道 5 worker 并发
    python3 company_crawler.py --proxy -n 500       # 每个 worker 每批 500 个店铺
    python3 company_crawler.py --proxy --max-batches 2
    python3 company_crawler.py --proxy --headed     # 有头模式（首次过滑块）
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from pathlib import Path

from common import (HOMEPAGE, FetchTask, add_common_args, browser_alive,
                    ensure_mtop_token, has_mtop_token,
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


# ---------- 公司黄页解析（任务层：采什么） ----------

COMPANY_URL_TPL = ("https://s.1688.com/company/company_search.htm"
                   "?charset=utf8&keywords={keyword}&beginPage={page}")


def build_company_url(keyword: str, page_no: int = 1) -> str:
    """构造公司黄页 URL。charset=utf8 必须带：不带时页面按 GBK 解码
    UTF-8 编码的关键词，标题与关键词全变乱码（实测 2026-08-03，
    '女装' 变 '濂宠'）。"""
    from urllib.parse import quote
    return COMPANY_URL_TPL.format(keyword=quote(keyword), page=page_no)


# 从首页提取类目入口作关键词来源（与 shop_crawler 同思路，独立实现：
# 首页类目链接文本即关键词）
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

# 从黄页提取企业卡片：.company-offer-card 内找店铺首页链接
# （hostname 为 xxx.1688.com 且非已知功能子域），公司名取卡片内
# 文字最长的店铺锚文本；同时探测「下一页」按钮判断是否还有下页。
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

# 等待黄页卡片渲染就绪（异步渲染，轮询不加重风控）
_JS_CARDS_READY = """
() => document.querySelectorAll('.company-offer-card').length > 0
"""


def fetch_homepage_categories(page) -> list[dict]:
    """访问 1688 首页提取类目关键词 [{name, keyword}, ...]，
    失败返回空列表，调用方用内置种子类目兜底。"""
    try:
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2.0, 4.0))
        cats = page.evaluate(_JS_EXTRACT_CATEGORIES) or []
        return [c for c in cats if c.get("keyword")]
    except Exception:
        return []


def scrape_company(page, keyword: str, page_no: int = 1,
                   data_wait: float = 15.0) -> dict | None:
    """抓取一页公司黄页，提取「公司名 + 店铺域名」列表。

    返回值约定（引擎按优先级判断，与 shop_crawler 一致）：
        - 正常：dict，含 shops / has_more / _source_url / _blocked；
          shops=[] 且未被风控 = 该关键词已采到末页（exhausted）
        - {"_fatal": 原因}    浏览器进程死亡（非风控，重启重试）
        - {"_net_error": 原因} 网络/代理层错误（非风控，退避重试）
        - 其他异常：None（按风控处理）
    """
    url = build_company_url(keyword, page_no)
    try:
        # 无 mtop 令牌不碰黄页：先尝试补握手，仍无令牌则按风控交引擎
        # 换 IP（无令牌裸奔 = 首请求即踢登录墙，白烧 IP）
        if not has_mtop_token(page) and not ensure_mtop_token(page):
            return {"_blocked": "会话缺少 mtop 令牌（_m_h5_tk），"
                                "搜索域入场券未获取，未触碰黄页"}
        # referer 链条：第 1 页来自首页，第 N 页来自第 N-1 页黄页
        referer = (HOMEPAGE if page_no <= 1
                   else build_company_url(keyword, page_no - 1))
        page.goto(url, wait_until="domcontentloaded", timeout=60000,
                  referer=referer)
        time.sleep(random.uniform(1.0, 2.0))
        # 滑块兜底：命中风控先自动过证（点击重置 → 刷新 → 换轨迹，
        # 最多 5 次），过了照常等卡片解析；过不了 _blocked 交引擎
        if solve_all_sliders is not None and page_block_reason(page):
            try:
                if solve_all_sliders(page, max_attempts=5):
                    time.sleep(random.uniform(1.5, 2.5))  # 等真实内容渲染
            except Exception:
                pass  # 过证异常不阻断，交给 _blocked 判定兜底
        # 等企业卡片渲染就绪（轮询，不加重风控）
        deadline = time.monotonic() + data_wait
        while time.monotonic() < deadline:
            try:
                if page.evaluate(_JS_CARDS_READY):
                    break
            except Exception:
                break
            time.sleep(1.0)
        time.sleep(random.uniform(1.5, 3.0))
        result = page.evaluate(_JS_EXTRACT_COMPANIES) or {}
        shops = [{"domain": it["domain"],
                  "name": it.get("name") or None,
                  "url": f"https://{it['domain']}"}
                 for it in result.get("items") or [] if it.get("domain")]
        return {
            "shops": shops,
            "has_more": bool(result.get("hasMore")),
            "found": str(result.get("cards") or 0),
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


# ---------- 关键词队列（与 shop_crawler 的 CategoryPool 同思路，独立实现） ----------

# 首页类目提取失败时的兜底种子（均为 1688 常见批发类目关键词）
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
    """关键词池：进程内共享，线程安全。

    - pool: {keyword: name}，首次由某个 worker 从首页提取（其后复用）；
    - in_progress: 正被某 worker 采集的关键词（互斥，避免两 worker
      采同一关键词撞页）；
    - exhausted: 已采到末页的关键词（启动时从 category_progress 加载，
      采到末页时即时更新）。
    """

    def __init__(self, exhausted: set):
        self.lock = threading.Lock()
        self.pool: dict = {}
        self.in_progress: set = set()
        self.exhausted: set = set(exhausted)

    def pick(self) -> tuple[str, str] | None:
        """随机挑一个可采关键词并占用；无可采返回 None。"""
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
        """合并首页提取到的关键词，返回新增数量。"""
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

# category_progress 存储前缀：与 shop_crawler 的商品搜索进度隔离
PROGRESS_PREFIX = "company:"


class CompanyTask(FetchTask):
    """公司黄页采集任务：随机关键词 → 黄页 → 公司店铺域名入库。

    任务项为 (keyword, name, page_no) 三元组；关键词占用与 exhausted
    标记由 KeywordPool 管，页码进度由 category_progress 表管
    （"company:" 前缀存储，与商品搜索进度隔离）。
    """

    unit = "页"
    batch_unit = "店铺"
    # 冷启动要先逛首页提取关键词填池，必须在 acquire（选关键词）之前
    cold_start_before_acquire = True
    # 黄页与商品搜索同属 s.1688.com 搜索域，匿名配额墙按同一预算保守
    # 处理（实测商品搜索阈值 18~26 页）：每出口 IP 采满 12 页主动换 IP
    ip_request_budget = 12

    def __init__(self):
        self.kw_pool: KeywordPool | None = None

    # ---- main 阶段 ----

    def prepare(self, args) -> bool:
        db = ShopDB()
        # 已采到末页的关键词启动时载入（只取黄页前缀的进度）
        exhausted = {k[len(PROGRESS_PREFIX):]
                     for k in db.get_exhausted_keywords()
                     if k.startswith(PROGRESS_PREFIX)}
        if exhausted:
            print(f"[0] 黄页已采到末页的关键词 {len(exhausted)} 个，自动跳过")
        self.kw_pool = KeywordPool(exhausted)

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

    def cold_start(self, page, item, log=None) -> None:
        """新会话先逛 1688 首页留真实浏览轨迹，顺带提取首页类目填池。"""
        cats = fetch_homepage_categories(page)
        if not cats:
            cats = [{"name": n, "keyword": k} for n, k in SEED_KEYWORDS]
            if log:
                log(f"[!] 首页类目提取失败，"
                    f"使用内置种子关键词（{len(cats)} 个）")
        n = self.kw_pool.refresh(cats)
        if n and log:
            log(f"黄页关键词池新增 {n} 个"
                f"（可采 {self.kw_pool.available()}，"
                f"跳过已采完 {len(self.kw_pool.exhausted)}）")
        # mtop 握手：黄页数据走 mtop API，会话须持有 _m_h5_tk 再碰；
        # 拿不到就记日志，scrape 会拒绝无令牌裸奔
        if not ensure_mtop_token(page, log=log) and log:
            log("[!] mtop 握手未拿到 _m_h5_tk，本会话黄页采集将被搁置"
                "（scrape 逐页重试握手，仍无令牌则交引擎换 IP）")

    def acquire(self, db, wctx: dict):
        picked = self.kw_pool.pick()
        if not picked:
            return None
        keyword, name = picked
        prog = db.get_category_progress(PROGRESS_PREFIX + keyword)
        page_no = prog["next_page"] if prog else 1
        return (keyword, name, page_no)

    def label(self, item) -> str:
        return f"{item[1]} p{item[2]}"

    def scrape(self, page, item) -> dict | None:
        keyword, _name, page_no = item
        return scrape_company(page, keyword, page_no)

    def on_success(self, db, item, info: dict, wctx: dict,
                   set_status, log) -> int:
        keyword, name, page_no = item
        stats = wctx["stats"]
        page_shops = info["shops"]
        has_more = info["has_more"]
        run_id = db.start_run(name, PROGRESS_PREFIX + keyword)
        n_new = db.upsert_shops(page_shops, run_id=run_id,
                                category_keyword=keyword)
        db.finish_run(run_id, shops_found=len(page_shops),
                      shops_picked=n_new,
                      note=f"company page={page_no}")
        if not page_shops or not has_more:
            # 空页或没有下一页：该关键词采到末页
            db.mark_category_exhausted(PROGRESS_PREFIX + keyword, name)
            wctx["exhausted"] = True  # after_item 释放占用时顺手标记
            set_status(state=f"■ {name} 采到末页，标记 exhausted")
            log(f"■ 关键词 {name} 第 {page_no} 页 "
                f"{len(page_shops)} 店，hasMore={has_more}，"
                f"采到末页标记 exhausted")
        else:
            db.advance_category_page(PROGRESS_PREFIX + keyword, name,
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
        # 关键词占用由 after_item 释放
        return "跳过该页，页码不前进下次重采"

    def on_abort(self, item) -> str:
        return (f"关键词 {item[0]} 第 {item[2]} 页页码不前进，"
                f"下次运行自动续采")

    def after_item(self, item, wctx: dict) -> None:
        # 释放关键词占用（采到末页的顺手标记，之后所有 worker 都跳过）
        self.kw_pool.release(item[0],
                             exhausted=wctx.pop("exhausted", False))

    def empty_message(self) -> str:
        return "没有可采的关键词了（全部采完或被占用）"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="1688 公司黄页采集（找供应商；随机关键词黄页 → "
                    "公司店铺域名入库，多 worker 并发/风控状态机由 "
                    "common 引擎驱动，与 shop_crawler 完全独立）")
    ap.add_argument("-n", "--num", type=int, default=200,
                    help="每个 worker 每批采集的店铺数量（默认 200）；"
                         "采满一批后各自强制休息再开下一批")
    add_common_args(ap)
    ap.set_defaults(rest_every=15)  # 本任务按页长休息，默认 15 页一次
    args = ap.parse_args()

    task = CompanyTask()
    if not task.prepare(args):
        return 0
    return run_workers(args, task)


if __name__ == "__main__":
    sys.exit(main())
