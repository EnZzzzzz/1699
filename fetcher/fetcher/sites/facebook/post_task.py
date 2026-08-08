# -*- coding: utf-8 -*-
"""Facebook 群帖采集任务（daemon crawl_fb_post 队列执行器）。

任务内容：消费 work_items(crawl_fb_post) 的帖子 permalink → 调
FetchFbPost 原子（匿名渲染抓 permalink + parse_post 四桶提取）→
号码落 fb_contacts（declared_wa 桶 wa_source='declared'）→ fb_posts
状态机 done/failed + has_contact 回写；微信/TG/邀请链接侧车随
work_items.result_json 留存（观测用）。

分层：原子只做「抓 + 提取」，本 Task 做编排与落库（SPEC §5.1 裁定：
fetch 调 FetchFbPost 原子，不内联 page 操作）。匿名白板会话无需
软着陆（cold_start 空实现）；warmup homepage 偏差接受（SPEC §7.3）。
"""

from __future__ import annotations

import re

from fetcher.control.task import Task
from fetcher.core.types import ActionResult

QUEUE = "crawl_fb_post"

# 从群 URL 解析 group_id：facebook.com/groups/{gid}（payload.domain 是群 URL）
_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")


def _group_id_from_url(url: str) -> str | None:
    """群 URL → 群 id；无/非法返回 None。"""
    m = _GROUP_RE.search(url or "")
    return m.group(1) if m else None


class FbPostTask(Task):
    """FB 群帖采集任务：认领 crawl_fb_post 队列的帖子工作项。"""

    name = "post"
    unit = "帖"
    batch_unit = ""

    # 匿名 permalink 抓取：参照 1688 contact 的保守预算
    ip_request_budget = 60

    QUEUE = QUEUE

    def __init__(self):
        self._atom = None

    def _make_atom(self):
        from fetcher.atoms.facebook import FetchFbPost  # 延迟导入
        return FetchFbPost()

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        """崩溃恢复：fb_posts 的 in_progress 重置回 pending（进程中断残留）。

        注意：reset_daemon_state 只认 domain_suffix 非空的 contact 队列，
        不覆盖 fb_posts；重置放本 Task.prepare（router.prepare 每队列都会调），
        与 1688 contact 的 prepare 语义一致（SPEC §5.1）。
        """
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        n = db.reset_fb_posts_in_progress()
        if n:
            print(f"[0] 已把 {n} 个中断残留的 in_progress 帖子重置回 pending")
        pending = db.conn.execute(
            "SELECT COUNT(*) FROM fb_posts WHERE status='pending'"
        ).fetchone()[0]
        print(f"[1] fb_posts 待抓取 {pending} 个（daemon 由 work_items 队列供货）")
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
        n_posts = db.conn.execute(
            "SELECT COUNT(*) FROM fb_posts").fetchone()[0]
        db.close()
        return (f"本次完成: 有联系方式 {ok}, 无联系方式 {empty}, 失败 {failed}"
                f"\n    fb_posts {n_posts} 行，fb_contacts {n_contacts} 个号码")

    # ---- 状态板 ----

    def compose(self, wid: int, f: dict) -> str:
        return (f"[w{wid}] 出口 {f.get('ip', '…')} | "
                f"采 {f.get('n', 0)}（✓{f.get('ok', 0)} "
                f"○{f.get('empty', 0)} ✗{f.get('failed', 0)}）| "
                f"{f.get('post', '-')} | {f.get('state', '初始化')}")

    def make_stats(self) -> dict:
        return {"ok": 0, "empty": 0, "failed": 0}

    def rest_counter(self, stats: dict) -> int:
        return sum(stats.values())

    # ---- worker 循环 ----

    def acquire_item(self, ctx):
        """从 crawl_fb_post 队列认领（LocalLoop/直调场景用；daemon 经
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
        return item["url"]

    def cold_start(self, ctx, item) -> None:
        """空实现：白板匿名会话无需软着陆（SPEC §7.3，warmup 由框架负责，
        homepage 偏差接受）。"""

    def fetch(self, ctx, item) -> ActionResult:
        """调 FetchFbPost 原子（params 只传 url，节奏/滚动走原子默认）。"""
        atom = self._atom or self._make_atom()
        return atom.run(ctx, {"url": item["url"]})

    def validate(self, ctx, item, result: ActionResult) -> bool:
        """有效帖页判据：DOM 正文非空且长度 ≥ 100（FB 帖页含遮罩文案，
        纯遮罩约 200 字符，有效帖页远超此值——阈值按 SPEC §5.1）。"""
        data = result.data or {}
        text = data.get("text") or ""
        return bool(text.strip()) and len(text) >= 100

    def on_success(self, ctx, item, result: ActionResult) -> int:
        """号码落 fb_contacts + fb_posts 置 done + 侧车副产物留 result_json。"""
        data = result.data or {}
        phones = data.get("phones") or []
        group_id = _group_id_from_url(item.get("domain") or "")
        db = ctx.store.db
        n_new = db.save_fb_contacts(item["url"], group_id, phones)
        has_contact = bool(data.get("has_contact"))
        db.mark_fb_post_done(item["url"], has_contact)
        # 侧车副产物（微信/TG/邀请链接）：非空才设，QueueRouter._finish
        # 经 ctx.state["result_json"] 落 work_items.result_json（SPEC §8）
        sidecar = {}
        for key in ("wechat_ids", "tg_handles", "wa_group_invites"):
            vals = data.get(key) or []
            if vals:
                sidecar[key] = vals
        if sidecar:
            ctx.state["result_json"] = sidecar
        stats = self.wctx_stats(ctx)
        if phones:
            stats["ok"] += 1
            state = f"✓ {len(phones)} 个号码（新增 {n_new}）"
        else:
            stats["empty"] += 1
            state = "○ 无联系方式"
        ctx.set_status(state=state, n=sum(stats.values()),
                       ok=stats["ok"], empty=stats["empty"],
                       failed=stats["failed"])
        return 1

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        ctx.store.db.mark_fb_post_failed(item["url"])
        stats = self.wctx_stats(ctx)
        stats["failed"] += 1
        ctx.set_status(n=sum(stats.values()), failed=stats["failed"])
        return "标记 failed 跳过"

    def on_abort(self, ctx, item) -> str:
        return (f"帖子 {item['url']} 留在 in_progress，"
                f"下次运行自动放回 pending")

    def giveup_cost(self, item) -> int:
        # 本帖处理完毕（含标记 failed），计入批次配额
        return 1

    def empty_message(self) -> str:
        return "没有待抓取的帖子了"

    # ---- 内部 ----

    @staticmethod
    def wctx_stats(ctx) -> dict:
        return ctx.state["task"]["stats"]
