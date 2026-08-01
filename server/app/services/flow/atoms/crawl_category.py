# -*- coding: utf-8 -*-
"""
crawl_category 原子：采集店铺分页（单 worker 单轮）。

抽取 server/app/workers/shop_crawl.py `_worker` 单轮采集核心（L159-276）：
从共享类目队列取一个未采完类目 → 打开分页 → 提取店铺 → 入库 pending →
上报使用事件。不含 target 判停、长时休息、rotate 换 IP（引擎策略层职责）。

共享类目队列与跨轮状态放在 ctx.vars：
    ctx.vars["category_queue"]  list[dict]  类目队列（worker 间共享，pop 取用）
    ctx.vars["crawl_state"]     {"empty_streak": int}  连续空轮计数

outcome 映射（分类语义对齐 shop_crawl.py，行号见各处注释）：
    有新增入库              → ok（data 带 new_count）
    提取到但无新增 / 末页空 → empty（类目枯竭信号；shop_crawl.py L231-235、
                              L211-216，均不算风控）
    未提取到店铺 / 风控页   → blocked（shop_crawl.py L217-219 on_suspected_block
                              L124-139；连续空轮中止由引擎熔断负责，本原子只
                              在 data.empty_streak 中暴露计数）
    类目页打开失败且命中网络错误特征 → net_error
"""
from __future__ import annotations

import random

from ...crawl import pages as pg
from ..base import (
    Atom, AtomResult, Context,
    OUTCOME_BLOCKED, OUTCOME_EMPTY, OUTCOME_NET_ERROR, OUTCOME_OK,
    OUTCOME_STOPPED,
)
from ..registry import register


def _report_usage(ctx: Context, result: str) -> None:
    """上报通道使用事件（shop_crawl.py L192-193 / L204-207 的原样迁移）。"""
    pool_client = ctx.resources.get("pool_client")
    channel = ctx.resources.get("channel")
    if pool_client is None or channel is None:
        return
    pool_client.report(channel, result=result, task_type="shop_crawl",
                       exit_ip=ctx.resources.get("identity"))


@register
class CrawlCategoryAtom(Atom):
    name = "crawl_category"
    title = "采集店铺分页"
    inputs = {"db": "ShopDB", "page": "Page",
              "vars.category_queue": "list[dict]"}
    outputs = {"vars.category_queue": "list[dict]（采到的类目回插队首）",
               "vars.crawl_state": "dict（empty_streak 计数）",
               "data.new_count": "int（outcome=ok 时新增入库数）"}
    param_spec = {
        "type": "object",
        "properties": {
            "delay_min": {"type": "number", "default": 1,
                          "description": "轮间随机延迟下界（秒）"},
            "delay_max": {"type": "number", "default": 3,
                          "description": "轮间随机延迟上界（秒）"},
        },
        "required": [],
    }

    def run(self, ctx: Context, params: dict) -> AtomResult:
        params = params or {}
        delay_min = float(params.get("delay_min") or 1)
        delay_max = float(params.get("delay_max") or 3)
        if ctx.stop_requested():
            return AtomResult(outcome=OUTCOME_STOPPED, detail="任务已停止")

        db = ctx.resources["db"]
        page = ctx.resources["page"]
        queue = ctx.vars.setdefault("category_queue", [])
        state = ctx.vars.setdefault("crawl_state", {"empty_streak": 0})

        # ---- 从共享队列取一个未采完的类目（shop_crawl.py L160-176）----
        cat, page_no = None, 1
        while queue:
            candidate = queue.pop()
            prog = db.get_category_progress(candidate["keyword"])
            if prog and prog["exhausted"]:
                continue
            cat = candidate
            page_no = prog["next_page"] if prog else 1
            break
        if cat is None:
            return AtomResult(outcome=OUTCOME_EMPTY,
                              detail="类目队列为空（所有类目均已采完）")

        # ---- 打开类目分页（shop_crawl.py L178-195）----
        url = pg.category_page_url(cat["url"], page_no)
        ctx.emit("info", f"正在采集类目「{cat['name']}」第 {page_no} 页",
                 {"category": cat["name"], "keyword": cat["keyword"],
                  "page": page_no, "url": url})
        try:
            page.goto(url, wait_until="domcontentloaded",
                      timeout=60000, referer=pg.HOMEPAGE)
        except Exception as e:
            # 原实现（L191-195）一律走 on_suspected_block；原子层按 pages.py
            # NETWORK_ERR_MARKERS 区分网络故障与疑似风控，其余保持原分类
            _report_usage(ctx, "error")
            if pg.is_network_error(e):
                return AtomResult(outcome=OUTCOME_NET_ERROR,
                                  detail=f"类目页打开失败（网络故障）: {e}",
                                  data={"category": cat["name"],
                                        "keyword": cat["keyword"],
                                        "page": page_no})
            state["empty_streak"] += 1
            return AtomResult(outcome=OUTCOME_BLOCKED,
                              detail=f"类目页打开失败: {e}（疑似风控，连续空轮 "
                                     f"{state['empty_streak']}）",
                              data={"category": cat["name"],
                                    "keyword": cat["keyword"], "page": page_no,
                                    "empty_streak": state["empty_streak"]})

        # ---- 拟人停顿 + 滚动（shop_crawl.py L196-200；time.sleep 换成
        #      停止感知的 ctx.wait，时长分布不变）----
        pg.human_pause(4, 8)
        for _ in range(3):
            page.mouse.wheel(0, random.randint(600, 1200))
            if ctx.wait(random.uniform(1.0, 2.0)):
                return AtomResult(outcome=OUTCOME_STOPPED, detail="任务已停止")

        # ---- 提取 + 分类上报（shop_crawl.py L202-207）----
        shops = pg.extract_shops(page)
        blocked = pg.page_blocked(page) if not shops else False
        _report_usage(ctx,
                      "blocked" if blocked else ("error" if not shops else "ok"))

        if not shops:
            if page_no > 1 and not blocked:
                # 末页空结果：标记类目采完（shop_crawl.py L211-216）
                db.mark_category_exhausted(cat["keyword"], cat["name"])
                ctx.emit("info", f"类目「{cat['name']}」第 {page_no} 页无结果，"
                         "标记为已采完（exhausted）",
                         {"category": cat["name"], "keyword": cat["keyword"],
                          "page": page_no})
                return AtomResult(outcome=OUTCOME_EMPTY,
                                  detail=f"类目「{cat['name']}」第 {page_no} 页"
                                         "无结果，已标记采完",
                                  data={"category": cat["name"],
                                        "keyword": cat["keyword"],
                                        "page": page_no})
            # 首页无结果或命中风控页：疑似风控（shop_crawl.py L217-219）
            state["empty_streak"] += 1
            reason = "命中风控/验证页" if blocked else "未提取到店铺"
            return AtomResult(outcome=OUTCOME_BLOCKED,
                              detail=f"{reason}（连续空轮 "
                                     f"{state['empty_streak']}，疑似被风控）",
                              data={"category": cat["name"],
                                    "keyword": cat["keyword"], "page": page_no,
                                    "empty_streak": state["empty_streak"]})

        # ---- 整页入库（shop_crawl.py L221-241；upsert 不进锁，DB 事务自身
        #      原子。类目回插队首对应 L229-230，单类目模式由引擎控制队列
        #      内容，本原子一律回插）----
        run_id = db.start_run(cat["name"], cat["keyword"])
        inserted = db.upsert_shops(shops, run_id=run_id,
                                   category_keyword=cat["keyword"])
        queue.insert(0, cat)
        db.finish_run(run_id, shops_found=len(shops),
                      note=f"new={inserted} page={page_no} task={ctx.task_id}")
        db.advance_category_page(cat["keyword"], cat["name"],
                                 shops_found=len(shops))

        if inserted == 0:
            # 提取正常但无新增：类目枯竭，不算风控（shop_crawl.py L231-235）
            state["empty_streak"] += 1
            result = AtomResult(outcome=OUTCOME_EMPTY,
                                detail=f"类目「{cat['name']}」第 {page_no} 页："
                                       f"提取 {len(shops)} 个店铺，无新增"
                                       "（类目枯竭信号）",
                                data={"category": cat["name"],
                                      "keyword": cat["keyword"],
                                      "page": page_no,
                                      "extracted": len(shops), "new_count": 0,
                                      "empty_streak": state["empty_streak"]})
        else:
            state["empty_streak"] = 0
            ctx.emit("success", f"类目「{cat['name']}」第 {page_no} 页：提取 "
                     f"{len(shops)} 个店铺，新增入库 {inserted} 个",
                     {"category": cat["name"], "keyword": cat["keyword"],
                      "page": page_no, "extracted": len(shops),
                      "inserted": inserted})
            result = AtomResult(outcome=OUTCOME_OK,
                                detail=f"新增入库 {inserted} 个店铺",
                                data={"category": cat["name"],
                                      "keyword": cat["keyword"],
                                      "page": page_no,
                                      "extracted": len(shops),
                                      "new_count": inserted})

        # ---- 轮间随机延迟（shop_crawl.py L272-276；target 判停由引擎负责，
        #      原子每轮结束后统一按 params 延迟，停止感知）----
        if delay_max > 0:
            t = random.uniform(delay_min, delay_max)
            if t > 0 and ctx.wait(t):
                return AtomResult(outcome=OUTCOME_STOPPED, detail="任务已停止")
        return result
