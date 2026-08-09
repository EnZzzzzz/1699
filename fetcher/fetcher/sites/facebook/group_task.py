# -*- coding: utf-8 -*-
"""Facebook 群 feed 全量采集任务（daemon crawl_fb_group 队列的 local 消费者）。

任务内容：消费 work_items(crawl_fb_group) 的群 URL → 调 FetchFbGroupPosts
原子（Bright Data / Apify 第三方 API 拉群帖）→ 逐帖号码落 fb_contacts
（正文全文已在手，直接落库，无需再走 crawl_fb_post）→ fb_groups 状态机
done/failed 回写（post_count/has_contact/last_crawled_at）。

FATAL 处置：缺 API key / 未知 provider → 原子返回 FATAL，Task 框架对
FATAL 直接停止（on_giveup 不会被调），本 Task 不额外处理（SPEC §5.3）。

分层：原子只做「拉 + 提取」，本 Task 做编排与落库（对齐 FbPostTask 模式）。
"""

from __future__ import annotations

import re

from fetcher.control.task import Task
from fetcher.core.types import ActionResult

QUEUE = "crawl_fb_group"

# 从群 URL 解析 group_id：facebook.com/groups/{gid}（payload.url 是群 URL）
_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")


def _group_id_from_url(url: str) -> str | None:
    """群 URL → 群 id；无/非法返回 None。"""
    m = _GROUP_RE.search(url or "")
    return m.group(1) if m else None


class FbGroupTask(Task):
    """FB 群全量采集任务：认领 crawl_fb_group 队列的群工作项。"""

    name = "fb_group"
    unit = "群"
    batch_unit = ""

    QUEUE = QUEUE

    def __init__(self):
        self._atom = None

    def _make_atom(self):
        from fetcher.atoms.facebook_group import FetchFbGroupPosts  # 延迟导入
        return FetchFbGroupPosts()

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        """崩溃恢复：fb_groups 的 in_progress 重置回 pending（进程中断残留）。

        注意：reset_daemon_state 只认 domain_suffix 非空的 contact 队列，
        不覆盖 fb_groups；重置放本 Task.prepare（router.prepare 每队列都会调），
        与 FbPostTask.prepare 语义一致（SPEC §5.3）。
        """
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        n = db.reset_fb_groups_in_progress()
        if n:
            print(f"[0] 已把 {n} 个中断残留的 in_progress 群重置回 pending")
        pending = db.conn.execute(
            "SELECT COUNT(*) FROM fb_groups WHERE status='pending'"
        ).fetchone()[0]
        print(f"[1] fb_groups 待采集 {pending} 个（daemon 由 work_items 队列供货）")
        db.close()
        return True

    def summary(self, all_stats: dict, db_path=None) -> str:
        from fetcher.db import ShopDB  # 延迟导入
        ok = sum(s.get("ok", 0) for s in all_stats.values())
        empty = sum(s.get("empty", 0) for s in all_stats.values())
        failed = sum(s.get("failed", 0) for s in all_stats.values())
        db = ShopDB(db_path)
        n_contacts = db.conn.execute(
            "SELECT COUNT(*) FROM fb_contacts").fetchone()[0]
        n_groups = db.conn.execute(
            "SELECT COUNT(*) FROM fb_groups").fetchone()[0]
        db.close()
        return (f"本次完成: 有联系方式 {ok}, 无联系方式 {empty}, 失败 {failed}"
                f"\n    fb_groups {n_groups} 行，fb_contacts {n_contacts} 个号码")

    # ---- 状态板 ----

    def compose(self, wid: int, f: dict) -> str:
        return (f"[w{wid}] 群 {f.get('n', 0)}（✓{f.get('ok', 0)} "
                f"○{f.get('empty', 0)} ✗{f.get('failed', 0)}）| "
                f"{f.get('group', '-')} | {f.get('state', '初始化')}")

    def make_stats(self) -> dict:
        return {"ok": 0, "empty": 0, "failed": 0}

    def rest_counter(self, stats: dict) -> int:
        return sum(stats.values())

    # ---- worker 循环 ----

    def acquire_item(self, ctx):
        """从 crawl_fb_group 队列认领（LocalLoop/直调场景用；daemon 经
        QueueRouter 认领时不用本方法，保留实现供直接调用/测试）。"""
        from fetcher.control.queue_router import consumer_id_for
        item = ctx.store.db.claim_next_eligible([self.QUEUE],
                                                consumer_id_for(ctx))
        if item is None:
            return None
        payload = dict(item["payload"])
        payload["id"] = item["id"]
        return payload

    def label(self, item) -> str:
        return f"{item['url']}（{item.get('provider')}，≤{item.get('limit')}帖）"

    def fetch(self, ctx, item) -> ActionResult:
        """调 FetchFbGroupPosts 原子（params 透传 url/provider/limit）。"""
        atom = self._atom or self._make_atom()
        return atom.run(ctx, {
            "url": item["url"],
            "provider": item.get("provider"),
            "limit": int(item.get("limit") or 10),
        })

    def on_success(self, ctx, item, result: ActionResult) -> int:
        """逐帖号码落 fb_contacts + 群置 done 回写三字段 + stats。"""
        data = result.data or {}
        posts = data.get("posts") or []
        group_id = _group_id_from_url(item.get("url") or "")
        db = ctx.store.db
        # 逐帖落号：正文全文已在手，直接落库（无需再走 crawl_fb_post）
        n_new = 0
        for post in posts:
            post_url = (post or {}).get("url") or ""
            if not post_url:
                continue
            n_new += db.save_fb_contacts(post_url, group_id,
                                         (post or {}).get("phones") or [])
        has_contact = bool(data.get("has_contact") or data.get("phones"))
        db.mark_fb_group_done(item["url"], len(posts), has_contact)
        stats = self.wctx_stats(ctx)
        phones = data.get("phones") or []
        if phones:
            stats["ok"] += 1
            state = f"✓ {len(phones)} 个号码（新增 {n_new}）"
        else:
            stats["empty"] += 1
            state = "○ 无联系方式"
        ctx.set_status(state=state, n=sum(stats.values()),
                       ok=stats["ok"], empty=stats["empty"],
                       failed=stats["failed"])
        return len(posts)  # 返回帖数（计入批次配额）

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        """402/429 额度/限流、网络错误、无帖均置 failed（重跑由平台重开批次）。"""
        ctx.store.db.mark_fb_group_failed(item["url"])
        stats = self.wctx_stats(ctx)
        stats["failed"] += 1
        ctx.set_status(n=sum(stats.values()), failed=stats["failed"])
        return "标记 failed 跳过"

    def on_abort(self, ctx, item) -> str:
        return (f"群 {item['url']} 留在 in_progress，"
                f"下次运行自动放回 pending")

    def giveup_cost(self, item) -> int:
        # 群处理完毕（含标记 failed），计入批次配额
        return 1

    def empty_message(self) -> str:
        return "没有待采集的群了"

    # ---- 内部 ----

    @staticmethod
    def wctx_stats(ctx) -> dict:
        return ctx.state["task"]["stats"]
