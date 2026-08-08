# -*- coding: utf-8 -*-
"""WaCheckTask：wa_check 队列的 daemon 执行器（P4-1 迁入 dispatcher）。

不走 sites 插件体系（非站点任务）：acquire 走 wa_check 队列，fetch 调
CheckWhatsApp 原子（现成），on_success 写回 contacts 的 wa_registered/
wa_checked_at（逻辑移植自平台 wa_tasks._apply_results：后 11 位 LIKE
候选 + normalize 严格校验 + 歧义跳过 + 北京时间）。

执行载体是 LocalLoop（无浏览器循环）：outcome 直接处置——OK→on_success、
FATAL→停止、SKIPPED→收工、NET_ERROR→giveup 继续。节奏（逐号间隔经
原子 sample_min/max）与批间休息由原子/循环控制；风控冷却经让出型冷却
（冷却键 = queue 名 "wa_check"，Step 1.1 泛化已就绪）。

入队 feeder（daemon topup 角色）：wa_check_topup 从 contacts 捞未查号码
→ normalize 去重 → 50/块 → 账号按块轮换（WA_CHECK_ACCOUNTS 环境变量，
空则 ["default"]）→ INSERT work_item（requires=["local"]，site=NULL）。

DB 写入一律短事务 + busy_timeout（WAL，爬虫可能正在写库）。
"""

from __future__ import annotations

import json
import os
import time

from fetcher.atoms.wa_check import CheckWhatsApp, normalize_numbers
from fetcher.control.task import Task
from fetcher.core.types import ActionResult, Outcome

WA_QUEUE = "wa_check"
BATCH_SIZE = 50
DEFAULT_CC = "86"

# 查号账号池（env 逗号分隔；空 = 仅默认账号 auth_info/）
ACCOUNTS = [a.strip() for a in os.environ.get("WA_CHECK_ACCOUNTS", "").split(",")
            if a.strip()] or ["default"]


def wa_check_topup(db, limit: int = 0) -> int:
    """daemon topup：contacts 未查号码 → 50/块入队 wa_check 队列。

    幂等：已有 pending/claimed 项时整批跳过（防重复入队）。
    返回入队 item 数。
    """
    # 已有在途项 → 整批跳过（简单可靠，daemon 常驻 30s 唤醒）
    in_flight = db.conn.execute(
        "SELECT COUNT(*) FROM work_items WHERE queue=?"
        " AND status IN ('pending','claimed')", (WA_QUEUE,)).fetchone()[0]
    if in_flight:
        return 0
    rows = db.conn.execute(
        "SELECT mobile FROM contacts WHERE wa_checked_at IS NULL"
        " AND mobile IS NOT NULL AND TRIM(mobile) <> ''"
        " ORDER BY id ASC").fetchall()
    numbers: list[str] = []
    seen: set[str] = set()
    for (mobile,) in rows:
        for n in normalize_numbers([mobile], DEFAULT_CC):
            if n not in seen:
                seen.add(n)
                numbers.append(n)
    if not numbers:
        return 0
    batches = [numbers[i:i + BATCH_SIZE]
               for i in range(0, len(numbers), BATCH_SIZE)]
    n = 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for i, batch in enumerate(batches):
        account = ACCOUNTS[i % len(ACCOUNTS)]
        payload = {"numbers": batch, "account": account,
                   "batch_size": BATCH_SIZE}
        db.conn.execute(
            "INSERT INTO work_items (queue, site, payload_json, requires,"
            " created_at) VALUES (?, NULL, ?, ?, ?)",
            (WA_QUEUE, json.dumps(payload, ensure_ascii=False),
             '["local"]', now))
        n += 1
    db.conn.commit()
    return n


class WaCheckTask(Task):
    """wa_check 队列执行器（Task 协议，LocalLoop 驱动）。"""

    name = "wa_check"
    unit = "批"
    batch_unit = "号码"

    QUEUE = WA_QUEUE

    def __init__(self):
        self._atom = None

    def _make_atom(self) -> CheckWhatsApp:
        return CheckWhatsApp()

    # ---- main ----

    def prepare(self, config) -> bool:
        from fetcher.db import ShopDB  # 延迟导入
        db = ShopDB(config.resolved_db_path())
        pending = db.conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE queue=? "
            "AND status='pending'", (WA_QUEUE,)).fetchone()[0]
        unchecked = db.conn.execute(
            "SELECT COUNT(*) FROM contacts WHERE wa_checked_at IS NULL"
            " AND mobile IS NOT NULL AND TRIM(mobile) <> ''").fetchone()[0]
        print(f"[wa_check] 待查号码 {unchecked} 个，"
              f"在途工作项 {pending} 个（账号池: {', '.join(ACCOUNTS)}）")
        db.close()
        return True

    def summary(self, all_stats: dict, db_path=None) -> str:
        checked = sum(s.get("checked", 0) for s in all_stats.values())
        registered = sum(s.get("registered", 0) for s in all_stats.values())
        return (f"wa_check: 查 {checked} 个号码，"
                f"已注册 {registered} 个")

    def make_stats(self) -> dict:
        return {"checked": 0, "registered": 0}

    # ---- worker 循环 ----

    def acquire_item(self, ctx):
        """从 wa_check 队列认领（LocalLoop 经 QueueRouter 路由时不用本方法；
        保留实现供直接调用/测试）。"""
        from fetcher.control.queue_router import consumer_id_for
        item = ctx.store.db.claim_next_eligible([self.QUEUE],
                                                consumer_id_for(ctx))
        if item is None:
            return None
        payload = dict(item["payload"])
        payload["id"] = item["id"]
        return payload

    def label(self, item) -> str:
        return f"{len(item.get('numbers', []))} 个号码"

    def fetch(self, ctx, item) -> ActionResult:
        """调 CheckWhatsApp 原子（params 透传 numbers/account/节奏）。"""
        atom = self._atom or self._make_atom()
        numbers = item.get("numbers") or []
        if not numbers:
            return ActionResult.empty("无有效号码")
        sample_min = float(ctx.config.sample_min)
        sample_max = float(ctx.config.sample_max)
        return atom.run(ctx, {
            "numbers": numbers,
            "default_cc": DEFAULT_CC,
            "account": str(item.get("account") or ""),
            "sample_min": sample_min,
            "sample_max": sample_max,
        })

    def on_success(self, ctx, item, result: ActionResult) -> int:
        """写回 contacts（移植 wa_tasks._apply_results 语义）。"""
        results = (result.data or {}).get("results") or []
        written = 0
        hits = 0
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        conn = ctx.store.db.conn
        for r in results:
            num = str(r.get("number") or "")
            reg = r.get("registered")
            if not num or reg is None:
                continue
            pat = "%" + num[-11:]
            rows = conn.execute(
                "SELECT id, mobile, phone FROM contacts "
                "WHERE REPLACE(mobile, ' ', '') LIKE :p "
                "OR REPLACE(phone, ' ', '') LIKE :p",
                {"p": pat}).fetchall()
            exact = [row for row in rows
                     if num in normalize_numbers([row["mobile"]], DEFAULT_CC)
                     or num in normalize_numbers([row["phone"]], DEFAULT_CC)]
            if exact:
                targets = exact
            elif len(rows) == 1:
                targets = rows
            else:
                continue  # 歧义跳过
            marks = ",".join("?" * len(targets))
            conn.execute(
                f"UPDATE contacts SET wa_registered=?, wa_checked_at=? "
                f"WHERE id IN ({marks})",
                (1 if reg else 0, ts,
                 *[row["id"] for row in targets]))
            written += len(targets)
            if reg:
                hits += 1
        conn.commit()
        stats = ctx.state.get("task", {}).get("stats", {})
        stats["checked"] = stats.get("checked", 0) + len(results)
        stats["registered"] = stats.get("registered", 0) + hits
        ctx.log(f"[wa_check] 写回 {written} 行（{hits} 已注册，"
                f"{len(results)} 结果）")
        return written

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        ctx.log(f"[wa_check] 放弃：{reason}")
        return "跳过该批"

    def after_item(self, ctx, item) -> None:
        pass

    def empty_message(self) -> str:
        return "wa_check 队列空"
