# -*- coding: utf-8 -*-
"""义乌购联系方式采集任务：商品 ID → 详情 API → 联系方式 JSONL。

实测（2026-08-03）：/api/product/detail.htm?productId= 的
content.shopinfo.shop 匿名可见全部联系方式——contacter /
telephone / mobile / safemobile / email / qq / weixin，
无需登录（对比 1688 联系方式要过风控+登录墙，义乌购形同裸奔）。

队列：默认消费 search 任务产出的 .cache/yiwugo_items.jsonl
（dedup 按商品 id），也可显式给 ids/out_path。先跑 search 再跑
contact 是标准管线：

    python -m fetcher yiwugo search -n 50
    python -m fetcher yiwugo contact -n 100
"""

from __future__ import annotations

import json
import threading

from pathlib import Path

from fetcher.control.task import Task
from fetcher.core.errors import classify_error
from fetcher.core.types import ActionResult, Outcome
from fetcher.sites.yiwugo.features import (
    CODE_CAPTCHA,
    CODE_ILLEGAL,
    CODE_SUCCESS,
    CODE_UNAUTHORIZED,
    DEAD_PRODUCT_MARKERS,
    api_code,
    api_get,
    ensure_csrf_token,
    has_csrf_token,
)

DETAIL_API = "/api/product/detail.htm"


class ProductIdQueue:
    """内存商品 ID 队列（线程安全；元素为 dict：至少含 id，
    带上 search 阶段的 title/shop_name 等字段供落盘时回填）。"""

    def __init__(self, rows=()):
        self.lock = threading.Lock()
        self._queue = list(rows)

    @classmethod
    def from_jsonl(cls, path) -> "ProductIdQueue":
        seen, rows = set(), []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    pid = r.get("id")
                    if not pid or pid in seen:
                        continue
                    seen.add(pid)
                    rows.append(r)
        except FileNotFoundError:
            pass
        return cls(rows)

    def pick(self):
        with self.lock:
            return self._queue.pop(0) if self._queue else None

    def remaining(self) -> int:
        with self.lock:
            return len(self._queue)


def parse_contact(data: dict) -> dict | None:
    """把详情 API 响应规范化成联系方式 dict（纯函数，便于单测）。

    返回 None 表示商品失效（content.errorInfo 命中下架标记）——
    这是正常业务态不是拦截，任务层按「跳过不计失败」处理。
    """
    content = (data or {}).get("content") or {}
    err = str(content.get("errorInfo") or "")
    if err and any(m in err for m in DEAD_PRODUCT_MARKERS):
        return None
    shop = ((content.get("shopinfo") or {}).get("shop")) or {}
    if not shop:
        return None
    return {
        "shop_id": shop.get("shopId"),
        "shop_name": shop.get("shopName") or "",
        "shop_url_id": shop.get("shopUrlId") or "",
        "contacter": shop.get("contacter") or "",
        "telephone": shop.get("telephone") or "",
        "mobile": shop.get("mobile") or shop.get("safemobile") or "",
        "email": shop.get("email") or "",
        "qq": str(shop.get("qq") or ""),
        "weixin": shop.get("weixin") or "",
        "weixin_name": shop.get("weixinName") or "",
        "booth_ids": shop.get("boothids") or "",
        "introduction": shop.get("introduction") or "",
        "main_product": shop.get("mainProduct") or "",
        "factory_address": shop.get("factoryAddress") or "",
        "credit": shop.get("credit"),
        "years": content.get("years"),
    }


def has_any_contact(c: dict) -> bool:
    """至少有一种联系方式才算有效产出。"""
    return any(c.get(k) for k in ("contacter", "telephone", "mobile",
                                  "email", "qq", "weixin"))


class YiwugoContactTask(Task):
    """义乌购联系方式：商品 ID 队列 → /api/product/detail.htm → JSONL。

    任务项为 search 落盘的商品行 dict；产出 .cache/yiwugo_contacts.jsonl。
    """

    name = "contact"
    unit = "商品"
    batch_unit = "联系方式"
    cold_start_before_acquire = False
    ip_request_budget = 60  # [CAL-3] 防护阈值未知，先保守

    def __init__(self, in_path=None, out_path=None, ids=None):
        self.in_path = in_path    # None 时取 <cache>/yiwugo_items.jsonl
        self.out_path = out_path  # None 时取 <cache>/yiwugo_contacts.jsonl
        self._ids = ids           # 显式商品 ID 列表（测试/小批量用）
        self.queue: ProductIdQueue | None = None

    # ---- main 阶段 ----

    def _in_path(self, config):
        return (self.in_path
                or config.resolved_db_path().parent / "yiwugo_items.jsonl")

    def prepare(self, config) -> bool:
        if self._ids is not None:
            rows = [{"id": i} for i in self._ids]
        else:
            rows = ProductIdQueue.from_jsonl(self._in_path(config))._queue
        self.queue = ProductIdQueue(rows)
        if not self.queue.remaining():
            print(f"[X] 没有待采的商品 ID（输入 {self._in_path(config)} "
                  "不存在或为空；请先跑 yiwugo search）")
            return False
        print(f"[1] 商品 ID 队列 {self.queue.remaining()} 个，"
              f"每 worker 每批 {config.batch_num} 个，"
              f"产出 → {self._out_path(config)}")
        return True

    def summary(self, all_stats: dict) -> str:
        contacts = sum(s.get("contacts", 0) for s in all_stats.values())
        done = sum(s.get("done", 0) for s in all_stats.values())
        dead = sum(s.get("dead", 0) for s in all_stats.values())
        return (f"本次义乌购联系方式采集: 处理 {done} 个商品, "
                f"有效联系方式 {contacts} 条, 失效商品 {dead} 个")

    # ---- 状态板 ----

    def compose(self, wid: int, f: dict) -> str:
        return (f"[w{wid}] 出口 {f.get('ip', '…')} | 批 {f.get('batch', 1)} | "
                f"采 {f.get('contacts', 0)} 条（处理 {f.get('done', 0)}）| "
                f"{f.get('shop', '-')} | {f.get('state', '初始化')}")

    def make_stats(self) -> dict:
        return {"done": 0, "contacts": 0, "dead": 0}

    def rest_counter(self, stats: dict) -> int:
        return stats["done"]

    # ---- worker 循环 ----

    def acquire_item(self, ctx):
        if self.queue is None:  # 库用法绕过 prepare 时兜底
            self.prepare(ctx.config)
        return self.queue.pick() if self.queue else None

    def label(self, item) -> str:
        return (item.get("shop_name") or item.get("title")
                or str(item.get("id")))[:20]

    def fetch(self, ctx, item) -> ActionResult:
        """调详情 API 解析联系方式。"""
        page = ctx.page
        pid = item.get("id")
        try:
            if not has_csrf_token(page) \
                    and not ensure_csrf_token(page, log=ctx.log):
                return ActionResult.blocked(
                    "会话缺少 csrfToken（yiwugo.com），未触碰详情 API")
            data = api_get(page, DETAIL_API, params={"productId": pid},
                           referer=f"https://www.yiwugo.com/product/detail/"
                                   f"{pid}.html")
            code = api_code(data)
            if code == CODE_ILLEGAL:
                return ActionResult.blocked(
                    "详情 API 判非法请求（-1），csrfToken 疑似失效")
            if code == CODE_CAPTCHA:
                return ActionResult.blocked(
                    "详情 API 触发自研滑块验证码（-5）")
            if code == CODE_UNAUTHORIZED:
                return ActionResult.blocked(
                    "详情 API 要求登录（-2）——匿名配额可能用尽")
            if code != CODE_SUCCESS:
                return ActionResult.empty(
                    f"详情 API 返回未知 code={code!r}")
            contact = parse_contact(data)
            if contact is None:
                # 商品失效/无 shopinfo：正常业务态，不是拦截
                return ActionResult(Outcome.OK, "商品已失效或无店铺信息",
                                    {"dead": True})
            contact["id"] = pid
            # 回填 search 阶段已有的标题/摊位信息
            for k in ("title", "market_info", "booth_no", "keyword"):
                if item.get(k):
                    contact.setdefault(k, item[k])
            return ActionResult(Outcome.OK, "已解析联系方式",
                                {"contact": contact})
        except Exception as e:  # noqa: BLE001
            ctx.last_error = e
            kind = classify_error(e, page)
            reason = str(e).splitlines()[0][:200]
            if kind == "fatal":
                return ActionResult.fatal(reason)
            if kind == "net_error":
                return ActionResult.net_error(reason)
            return ActionResult.blocked(f"详情 API 请求失败（疑似风控）: {reason}")

    def validate(self, ctx, item, result: ActionResult) -> bool:
        """dead（失效商品）合法；contact 至少有一种联系方式。"""
        data = result.data or {}
        if data.get("dead"):
            return True
        c = data.get("contact")
        return isinstance(c, dict) and has_any_contact(c)

    def on_success(self, ctx, item, result: ActionResult) -> int:
        stats = ctx.state["task"]["stats"]
        stats["done"] += 1
        if result.data.get("dead"):
            stats["dead"] += 1
            ctx.set_status(done=stats["done"], dead=stats["dead"],
                           state=f"■ {item.get('id')} 已失效")
            return 1
        contact = result.data["contact"]
        self._append_jsonl(ctx.config, [contact])
        stats["contacts"] += 1
        ctx.set_status(done=stats["done"], contacts=stats["contacts"],
                       state=f"✓ {contact['shop_name'] or contact['id']}")
        return 1

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        return "跳过该商品（内存队列不重采）"

    def giveup_cost(self, item) -> int:
        return 0

    def empty_message(self) -> str:
        return "商品 ID 队列已采完"

    # ---- 落盘 ----

    def _out_path(self, config):
        if self.out_path:
            return self.out_path
        return config.resolved_db_path().parent / "yiwugo_contacts.jsonl"

    def _append_jsonl(self, config, rows: list[dict]):
        path = Path(self._out_path(config))
        with open(path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
