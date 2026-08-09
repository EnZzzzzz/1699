# -*- coding: utf-8 -*-
"""FbDiscoverTask：discover_fb 队列的 local 消费者（SPEC §5.2）。

消费 work_items(discover_fb) 的查询任务 → 调 FetchDdgSerp 原子（DDG 裸抓
FB 群帖 SERP）→ 按 kind 分流落库：帖 permalink → fb_posts（save_fb_posts，
keyword/source 溯源）；FB 群 URL（群主页 + 帖派生）→ fb_groups
（upsert_fb_groups，name 去 " | Facebook"/" - Facebook" 后缀近似溯源）；
kind=None 的非 FB 条目跳过。

local 消费者（LocalLoop 驱动，无浏览器循环）：OK→on_success 落库；
BLOCKED/NET_ERROR/EMPTY→on_giveup（不落库，仅日志短语 + stats failed）。
节奏取 ctx.config.sample_min/max 透传原子（原子抬到 60s 地板）。
"""

from __future__ import annotations

from fetcher.control.task import Task
from fetcher.core.types import ActionResult

QUEUE = "discover_fb"

# SERP 标题站点后缀（近似溯源用；strip 后 endswith 匹配，去一次）
_TITLE_SUFFIXES = (" | Facebook", " - Facebook")


def _clean_title(title: str) -> str:
    """SERP 标题净化：去 " | Facebook" / " - Facebook" 后缀（无则原样）。"""
    t = (title or "").strip()
    for suffix in _TITLE_SUFFIXES:
        if t.endswith(suffix):
            return t[:-len(suffix)].strip()
    return t


class FbDiscoverTask(Task):
    """discover_fb 队列执行器：DDG 查询 → 分流落库（SPEC §5.2）。"""

    name = "fb_discover"
    unit = "查询"
    batch_unit = ""

    QUEUE = QUEUE

    def __init__(self):
        self._atom = None

    def _make_atom(self):
        from fetcher.atoms.facebook_discover import FetchDdgSerp  # 延迟导入
        return FetchDdgSerp()

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        """打印队列待处理数（discover 无源表状态机，无需崩溃恢复）。"""
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        pending = db.conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE queue=? "
            "AND status='pending'", (QUEUE,)).fetchone()[0]
        print(f"[fb_discover] 队列待处理: {pending}")
        db.close()
        return True

    def summary(self, all_stats: dict, db_path=None) -> str:
        ok = sum(s.get("ok", 0) for s in all_stats.values())
        empty = sum(s.get("empty", 0) for s in all_stats.values())
        failed = sum(s.get("failed", 0) for s in all_stats.values())
        return (f"fb_discover: 成功 {ok}，空 {empty}，失败 {failed}")

    def make_stats(self) -> dict:
        return {"ok": 0, "empty": 0, "failed": 0}

    # ---- worker 循环 ----

    def acquire_item(self, ctx):
        """从 discover_fb 队列认领（LocalLoop 经 QueueRouter 路由时不用本
        方法；保留实现供直接调用/测试）。"""
        from fetcher.control.queue_router import consumer_id_for
        item = ctx.store.db.claim_next_eligible([self.QUEUE],
                                                consumer_id_for(ctx))
        if item is None:
            return None
        payload = dict(item["payload"])
        payload["id"] = item["id"]
        return payload

    def label(self, item) -> str:
        return f"{item['query']} 第{item['page']}页"

    def fetch(self, ctx, item) -> ActionResult:
        """调 FetchDdgSerp 原子（params 透传 query/page/sample_min/max）。"""
        atom = self._atom or self._make_atom()
        return atom.run(ctx, {
            "query": item["query"],
            "page": int(item.get("page") or 1),
            "sample_min": float(ctx.config.sample_min),
            "sample_max": float(ctx.config.sample_max),
        })

    def on_success(self, ctx, item, result: ActionResult) -> int:
        """results 分流落库：帖→fb_posts（含派生群→fb_groups）；群→fb_groups；
        kind=None 跳过。返回新增帖数（计入批次配额）。"""
        results = (result.data or {}).get("results") or []
        if not results:
            stats = self.wctx_stats(ctx)
            stats["empty"] += 1
            ctx.set_status(state="○ 无结果", n=sum(stats.values()),
                           empty=stats["empty"])
            return 0
        posts: list[dict] = []
        groups: list[dict] = []
        for r in results:
            kind = r.get("kind")
            url = r.get("url") or ""
            title = _clean_title(r.get("title"))
            group_id = r.get("group_id")
            if kind == "post":
                posts.append({"url": url, "group_id": group_id,
                              "group_name": title})
                gurl = r.get("group_url") or ""
                if gurl:
                    groups.append({"url": gurl, "group_id": group_id,
                                   "name": title})
            elif kind == "group":
                gurl = r.get("group_url") or url
                groups.append({"url": gurl, "group_id": group_id,
                               "name": title})
            # kind=None 的非 FB 条目跳过
        db = ctx.store.db
        n_posts = db.save_fb_posts(keyword=item["query"], source="ddg",
                                   posts=posts) if posts else 0
        if groups:
            db.upsert_fb_groups(groups)
        stats = self.wctx_stats(ctx)
        stats["ok"] += 1
        state = f"✓ 新增 {n_posts} 帖（群 {len(groups)}）"
        ctx.set_status(state=state, n=sum(stats.values()),
                       ok=stats["ok"], empty=stats["empty"],
                       failed=stats["failed"])
        return n_posts

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        """BLOCKED/NET_ERROR/EMPTY：不落库，仅日志短语 + failed 计数。"""
        ctx.log(f"[fb_discover] 放弃：{reason}")
        stats = self.wctx_stats(ctx)
        stats["failed"] += 1
        ctx.set_status(n=sum(stats.values()), failed=stats["failed"])
        return "标记 failed 跳过"

    def empty_message(self) -> str:
        return "discover_fb 队列空"

    # ---- 内部 ----

    @staticmethod
    def wctx_stats(ctx) -> dict:
        return ctx.state["task"]["stats"]
