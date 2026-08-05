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

节奏控制（与其他采集任务同策略）：
- 逐号码间隔：params["sample_min"]/["sample_max"]（秒）范围内的随机停顿，
  在 check.js 逐号循环内生效（默认 1.5s 固定）；兼容旧参数
  params["interval"]（等价于 min == max）；
- 批次：每 params["batch_num"] 个号码（默认 500）为一批，采满后批间
  休息 params["batch_rest_min"]~["batch_rest_max"] 秒随机时长；
- 批间休息可被 stop_event 中断。

DB 写入一律短事务 + busy_timeout（1688.db 为 WAL，正被采集进程写入）。
"""

import json
import random
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

# 节奏默认值：逐号码随机间隔 1.5s 固定（check.js 内部缺省）；
# 每 500 个号码一批，批间休息随机 60~180s
DEFAULT_SAMPLE_MIN = 1.5
DEFAULT_SAMPLE_MAX = 1.5
DEFAULT_BATCH_NUM = 500
DEFAULT_BATCH_REST_MIN = 60.0
DEFAULT_BATCH_REST_MAX = 180.0


def _pacing_params(params: dict) -> tuple[float, float, int, float, float]:
    """解析节奏参数：(sample_min, sample_max, batch_num, rest_min, rest_max)。

    sample_min/max 为逐号码随机间隔（秒），batch_num 为每批号码数，
    rest_min/max 为批间休息范围（秒）。兼容旧参数 interval（固定间隔）：
    显式给了 interval 而没给 sample_min/sample_max 时，等价于
    sample_min == sample_max == interval。
    """
    interval = params.get("interval")
    sample_min = params.get("sample_min")
    sample_max = params.get("sample_max")
    if interval is not None:
        interval = float(interval)
        if sample_min is None:
            sample_min = interval
        if sample_max is None:
            sample_max = interval
    lo = float(sample_min) if sample_min is not None else DEFAULT_SAMPLE_MIN
    hi = float(sample_max) if sample_max is not None else DEFAULT_SAMPLE_MAX
    lo, hi = max(0.0, lo), max(0.0, hi)
    if lo > hi:
        lo, hi = hi, lo
    batch_num = int(params.get("batch_num") or DEFAULT_BATCH_NUM)
    r_lo = float(params.get("batch_rest_min")
                 if params.get("batch_rest_min") is not None
                 else DEFAULT_BATCH_REST_MIN)
    r_hi = float(params.get("batch_rest_max")
                 if params.get("batch_rest_max") is not None
                 else DEFAULT_BATCH_REST_MAX)
    r_lo, r_hi = max(0.0, r_lo), max(0.0, r_hi)
    if r_lo > r_hi:
        r_lo, r_hi = r_hi, r_lo
    return lo, hi, max(0, batch_num), r_lo, r_hi


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


def _rest_with_heartbeat(task_id: int, seconds: float, label: str,
                         stop_event: threading.Event) -> bool:
    """分段等待 + 心跳日志，可被 stop_event 中断；返回是否被中断。

    每段最多 30s 刷一条「剩余约 N 分钟」心跳，避免休息期间日志静默
    被误判为卡死；每段都可被 stop_event 中断。
    """
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if stop_event.wait(min(30.0, remaining)):
            return True
        remaining = deadline - time.monotonic()
        if remaining > 1:
            _insert_event(
                task_id, "info",
                f"⏸ {label}，剩余约 {remaining / 60:.1f} 分钟...")


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
        sample_min, sample_max, batch_num, rest_min, rest_max = \
            _pacing_params(params)
        accounts = [str(a).strip()
                    for a in (params.get("accounts") or []) if str(a).strip()]

        # 防主号误用（曾因此误封主号）：wa_check 不显式指定账号时，过去会
        # 静默落到 default（= auth_info 主号），大批量协议查询有封号风险。
        # 空账号一律拒绝启动；显式选 default 则警告（default 目录已删除时
        # 原子层会以「未登录」FATAL，此处仅作提示）。
        if not accounts:
            _insert_event(
                task_id, "error",
                "wa_check 拒绝启动：未指定查号账号（accounts 为空）。"
                "为避免静默使用 default（主号）导致封号，任务已中止，"
                "请显式选择小号账号（如 xiaohao-1）后重试。",
                {"accounts": [], "action": "refused"})
            _finalize(
                task_id, "failed",
                "wa_check 未指定账号，拒绝启动（防空跑主号 default）")
            return
        if "default" in accounts:
            _insert_event(
                task_id, "warning",
                "警告：账号池包含 default（对应 auth_info 主号），"
                "协议批量查询有封号风险，请确认这是有意选择。",
                {"accounts": accounts, "contains_default": True})

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
            f"账号池：{account_label}，每次连接查 {BATCH_SIZE} 个，"
            f"逐号间隔 {sample_min:g}~{sample_max:g}s（随机），"
            f"每 {batch_num} 个号码一批，批间休息 "
            f"{rest_min:g}~{rest_max:g}s（随机）",
            {"total": total, "rows": len(rows), "accounts": accounts,
             "batch_size": BATCH_SIZE,
             "sample_min": sample_min, "sample_max": sample_max,
             "batch_num": batch_num,
             "batch_rest_min": rest_min, "batch_rest_max": rest_max})
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
        nums_since_rest = 0  # 距上次批间休息已成功查号的号码数

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
                "sample_min": sample_min,
                "sample_max": sample_max,
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

            # 批次配额（号码数计）：采满 batch_num 个号码后批间随机长休息
            # （防风控）；逐号码间隔已在 check.js 循环内生效，批与批之间
            # 的间隔即重连开销本身，不再额外 sleep。
            if res.outcome is Outcome.OK:
                nums_since_rest += len(batch)
            if (bi < len(batches) and batch_num > 0
                    and nums_since_rest >= batch_num):
                rest = random.uniform(rest_min, rest_max)
                _insert_event(
                    task_id, "info",
                    f"⏸ 本批已查满 {nums_since_rest} 个号码，"
                    f"批间休息 {rest / 60:.1f} 分钟（防风控）...",
                    {"checked": checked, "registered": registered,
                     "rest_seconds": round(rest, 1)})
                if _rest_with_heartbeat(task_id, rest, "批间休息",
                                        stop_event):
                    stopped = True
                    break
                nums_since_rest = 0
                _insert_event(task_id, "info", "▶ 批间休息结束，继续查号")

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
