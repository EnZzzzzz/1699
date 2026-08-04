# -*- coding: utf-8 -*-
"""wa_check 进程内任务执行器（WhatsApp 全量查号）。

与 subprocess 类任务不同：本执行器在 API 进程内的线程里跑，分批调用
fetcher 的 CheckWhatsApp 原子（原子内部每次调用会拉起 node 子进程连接
WhatsApp，约 5-10s/批，属正常）。

流程：
- 待查号码：contacts 中 wa_checked_at IS NULL 且 mobile 非空，按 id 升序，
  params["limit"]>0 时限量；
- 规范化：fetcher normalize_numbers(mobile, default_cc="86")；
- 每批 50 个号码调一次原子；params["accounts"] 非空时按批轮换账号
  （"default" 映射为原子的缺省账号），空列表 = 仅默认账号；
- 每批写回 contacts（wa_registered/wa_checked_at，北京时间；按号码后 11 位
  对齐 mobile/phone，仅更新规范化后严格匹配的行，歧义则跳过）；
- 每批写 task_events + throttle 更新 tasks.progress_json
  {"total","checked","registered","current_account"}；
- stop_event 置位或 tasks.stop_requested=1（每批检查一次 DB）→ 优雅停止；
- 原子连续 FATAL（未登录/登出，不可自愈）→ failed。

DB 写入一律短事务 + busy_timeout（1688.db 为 WAL，正被采集进程写入）。
"""

import json
import sqlite3
import threading
import time

from fetcher.atoms.wa_check import CheckWhatsApp, normalize_numbers
from fetcher.core.context import WorkerContext
from fetcher.core.types import Outcome

from app.db import DB_PATH, migrate
from app.runner import _db_write, _insert_event, beijing_now

BATCH_SIZE = 50
DEFAULT_CC = "86"
MAX_CONSECUTIVE_FATAL = 2
_PROGRESS_THROTTLE_SEC = 1.0


def _fetch_pending_rows(limit: int) -> list:
    """待查联系人：wa_checked_at IS NULL 且 mobile 非空，id 升序。"""
    sql = ("SELECT id, mobile FROM contacts "
           "WHERE wa_checked_at IS NULL "
           "AND mobile IS NOT NULL AND TRIM(mobile) <> '' "
           "ORDER BY id ASC")
    params = ()
    if limit > 0:
        sql += " LIMIT ?"
        params = (limit,)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _db_stop_requested(task_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        row = conn.execute(
            "SELECT stop_requested FROM tasks WHERE id=?",
            (task_id,)).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def _write_progress(task_id: int, total: int, checked: int,
                    registered: int, current_account: str) -> None:
    progress = {
        "total": total,
        "checked": checked,
        "registered": registered,
        "current_account": current_account,
        "updated_at": beijing_now(),
    }
    try:
        _db_write(
            "UPDATE tasks SET progress_json=? WHERE id=?",
            (json.dumps(progress, ensure_ascii=False), task_id),
        )
    except Exception as e:
        print(f"[wa_tasks] task {task_id} 更新进度失败: {e}")


def _finalize(task_id: int, status: str, error: str | None) -> None:
    ts = beijing_now()
    try:
        _db_write(
            "UPDATE tasks SET status=?, error=?, finished_at=? WHERE id=?",
            (status, error, ts, task_id),
        )
        _insert_event(
            task_id,
            "success" if status == "done" else (
                "warning" if status == "stopped" else "error"),
            f"任务结束，状态 → {status}" + (f"：{error}" if error else ""),
            {"status": status, "error": error},
        )
    except Exception as e:
        print(f"[wa_tasks] task {task_id} 回写状态失败: {e}")


def _apply_results(results: list) -> tuple[int, int, int]:
    """把一批查号结果写回 contacts。

    匹配策略：按号码后 11 位（num11）做 LIKE 候选过滤（mobile 或 phone
    去空格后以此结尾），再用 normalize_numbers 规范化候选行号码做严格
    相等校验；仅当存在严格匹配行、或候选行唯一时才 UPDATE，歧义跳过。

    返回 (写回行数, 结果错误跳过数, 歧义跳过数)。
    """
    written = skipped_err = skipped_amb = 0
    ts = beijing_now()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        for r in results:
            num = str(r.get("number") or "")
            reg = r.get("registered")
            if not num or reg is None:
                skipped_err += 1
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
                skipped_amb += 1
                continue
            marks = ",".join("?" * len(targets))
            conn.execute(
                f"UPDATE contacts SET wa_registered=?, wa_checked_at=? "
                f"WHERE id IN ({marks})",
                (1 if reg else 0, ts,
                 *[row["id"] for row in targets]))
            written += len(targets)
        conn.commit()
    finally:
        conn.close()
    return written, skipped_err, skipped_amb


def _atom_account(name: str) -> str:
    """API 账号名 → 原子 account 参数："default" 用缺省 auth_info/。"""
    return "" if name == "default" else name


def run(task_id: int, params: dict, stop_event: threading.Event) -> None:
    """wa_check 任务主循环（在 API 进程内线程中执行）。"""
    atom = CheckWhatsApp()
    try:
        migrate()  # 防御：服务未跑迁移时也能工作
        params = params or {}
        limit = int(params.get("limit") or 0)
        interval = float(params.get("interval")
                         if params.get("interval") is not None else 2.0)
        accounts = [str(a).strip()
                    for a in (params.get("accounts") or []) if str(a).strip()]

        rows = _fetch_pending_rows(limit)
        # 规范化 + 去重（保持顺序），一个号码可能对应多行联系人
        numbers: list[str] = []
        seen: set[str] = set()
        for _id, mobile in rows:
            for n in normalize_numbers([mobile], DEFAULT_CC):
                if n not in seen:
                    seen.add(n)
                    numbers.append(n)
        total = len(numbers)
        account_label = "、".join(accounts) if accounts else "default"
        _insert_event(
            task_id, "info",
            f"wa_check 启动：待查 {total} 个号码（{len(rows)} 行联系人），"
            f"账号池：{account_label}，批大小 {BATCH_SIZE}，批间 {interval}s",
            {"total": total, "rows": len(rows), "accounts": accounts,
             "interval": interval, "batch_size": BATCH_SIZE})
        if total == 0:
            _write_progress(task_id, 0, 0, 0, account_label)
            _finalize(task_id, "done", None)
            return

        batches = [numbers[i:i + BATCH_SIZE]
                   for i in range(0, total, BATCH_SIZE)]
        checked = 0
        registered = 0
        consec_fatal = 0
        stopped = False
        fail_detail = None
        last_progress = 0.0

        for bi, batch in enumerate(batches, 1):
            if stop_event.is_set() or _db_stop_requested(task_id):
                stopped = True
                break
            account_name = (accounts[(bi - 1) % len(accounts)]
                            if accounts else "default")
            ctx = WorkerContext(
                stop=stop_event,
                log=lambda m: _insert_event(
                    task_id, "info", m.strip()[:500]))
            res = atom.run(ctx, {
                "numbers": batch,
                "default_cc": DEFAULT_CC,
                "account": _atom_account(account_name),
            })

            if res.outcome is Outcome.OK:
                consec_fatal = 0
                results = res.data.get("results") or []
                written, skipped_err, skipped_amb = _apply_results(results)
                hits = sum(1 for r in results if r.get("registered"))
                checked += len(batch)
                registered += hits
                msg = (f"批次 {bi}/{len(batches)}：查 {len(batch)} 个，"
                       f"累计已注册 {registered}")
                extra = []
                if skipped_err:
                    extra.append(f"{skipped_err} 个查询出错未写回")
                if skipped_amb:
                    extra.append(f"{skipped_amb} 个号码匹配歧义跳过")
                if extra:
                    msg += "（" + "，".join(extra) + "）"
                _insert_event(task_id, "info", msg, {
                    "batch": bi, "batches": len(batches),
                    "worker": account_name,
                    "account": account_name, "checked": checked,
                    "registered": registered, "written": written,
                })
            elif res.outcome is Outcome.FATAL:
                consec_fatal += 1
                _insert_event(
                    task_id, "error",
                    f"批次 {bi}/{len(batches)} FATAL（账号 {account_name}）："
                    f"{res.detail}")
                if consec_fatal >= MAX_CONSECUTIVE_FATAL:
                    fail_detail = (f"原子连续 {consec_fatal} 次 FATAL："
                                   f"{res.detail}")
                    break
            elif res.outcome is Outcome.SKIPPED:
                stopped = True
                _insert_event(task_id, "warning",
                              f"批次 {bi}/{len(batches)} 被停止信号中断")
                break
            else:  # NET_ERROR / EMPTY / BLOCKED：记警告后继续下一批
                consec_fatal = 0
                _insert_event(
                    task_id, "warning",
                    f"批次 {bi}/{len(batches)} {res.outcome.value}"
                    f"（账号 {account_name}）：{res.detail}")

            now = time.monotonic()
            if now - last_progress >= _PROGRESS_THROTTLE_SEC:
                last_progress = now
                _write_progress(task_id, total, checked,
                                registered, account_name)

            # 批间节奏：stop_event.wait 实现可中断 sleep
            if bi < len(batches) and interval > 0:
                if stop_event.wait(interval):
                    stopped = True
                    break

        if fail_detail:
            _finalize(task_id, "failed", fail_detail[:500])
        elif stopped:
            _finalize(task_id, "stopped", None)
        else:
            _finalize(task_id, "done", None)
        _write_progress(task_id, total, checked, registered,
                        accounts[-1] if accounts else "default")
    except Exception as e:
        print(f"[wa_tasks] task {task_id} 执行器异常: {e}")
        try:
            _insert_event(task_id, "error", f"执行器异常：{e}")
        except Exception:
            pass
        _finalize(task_id, "failed", f"执行器异常：{e}"[:500])
