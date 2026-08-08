# -*- coding: utf-8 -*-
"""subprocess 任务监督器（P1）。

职责：
- 按任务类型拼接 fetcher CLI 命令并 Popen 启动（cwd=项目根）；
- 后台线程逐行读输出，写 task_events，throttle 更新 tasks.progress_json；
- 进程退出后回写 tasks.status / finished_at / error；
- stop(task_id)：stop_requested=1 → terminate() → 5 秒不退 kill()；
- 服务启动时清理 DB 里 status='running' 的孤儿任务。

DB 写入一律短事务 + busy_timeout（1688.db 为 WAL，正被其他采集进程写入）。
"""

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

from app.db import DB_PATH, migrate

PROJECT_ROOT = "/Volumes/DataDrive/proj/public/1699"
PYTHON_BIN = os.path.join(PROJECT_ROOT, "platform/server/.venv/bin/python")

# 任务类型 → fetcher CLI 子命令（P4：只剩 yiwugo_search，其余批次化）
TASK_COMMANDS = {
    "yiwugo_search": ["yiwugo", "search"],
}

# 批次任务类型 → 队列映射（P4：平台创建/停止/监控全流程走 dispatcher）。
# 值：{"queue", "enqueue"}——enqueue 为平台侧批次入队函数。
# contact 类带 domain_suffix（按来源过滤）；feeder/wa 无。
BATCH_TYPES = {
    "1688_contact": {
        "queue": "crawl_1688_contact", "site": "1688",
        "domain_suffix": ".1688.com", "kind": "contact",
    },
    "madeinchina_contact": {
        "queue": "crawl_mic_contact", "site": "madeinchina",
        "domain_suffix": ".cn.made-in-china.com", "kind": "contact",
    },
    "1688_shop": {
        "queue": "crawl_1688_shop", "site": "1688",
        "domain_suffix": "", "kind": "feeder",
    },
    "1688_company": {
        "queue": "crawl_1688_company", "site": "1688",
        "domain_suffix": "", "kind": "feeder",
    },
    "madeinchina_shop": {
        "queue": "crawl_mic_shop", "site": "madeinchina",
        "domain_suffix": "", "kind": "feeder",
    },
    "wa_check": {
        "queue": "wa_check", "site": None,
        "domain_suffix": "", "kind": "wa",
    },
}

# 批次任务类型集合（TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPES）
BATCH_TYPE_NAMES = set(BATCH_TYPES)

BJ_TZ = timezone(timedelta(hours=8))

_ERROR_KEYS = ("错误", "failed", "Error")
_SUCCESS_KEYS = ("完成", "成功", "OK")
_WARNING_KEYS = ("风控", "滑块", "警告")

_PROGRESS_THROTTLE_SEC = 1.0
_TAIL_KEEP = 30  # 退出时用于 error 摘要的尾部行数


def beijing_now() -> str:
    return datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def classify_line(line: str) -> str:
    if any(k in line for k in _ERROR_KEYS):
        return "error"
    if any(k in line for k in _WARNING_KEYS):
        return "warning"
    if any(k in line for k in _SUCCESS_KEYS):
        return "success"
    return "info"


# params 键 → CLI 数值/时长参数（值非 None 才输出，缺省=CLI 自带默认值）
_NUMERIC_FLAGS = (
    ("batch_num", "-n"),
    ("limit", "--limit"),
    ("max_batches", "--max-batches"),
    ("workers", "--workers"),
    ("channels", "--channels"),
    ("batch_rest", "--batch-rest"),
    ("sample_min", "--sample-min"),
    ("sample_max", "--sample-max"),
    ("rest_every", "--rest-every"),
    ("rest_min", "--rest-min"),
    ("rest_max", "--rest-max"),
    ("stagger_min", "--stagger-min"),
    ("stagger_max", "--stagger-max"),
    ("ip_retry", "--ip-retry"),
    ("net_retry", "--net-retry"),
    ("max_consecutive_fail", "--max-consecutive-fail"),
    ("block_rest_min", "--block-rest-min"),
    ("block_rest_max", "--block-rest-max"),
)


def build_command(task_type: str, params: dict) -> list:
    """任务类型 + params → fetcher CLI 命令列表（subprocess 直接 Popen）。

    规则：
    - 数值/时长参数值非 None 才输出（缺省=CLI 自带默认值，保持命令干净）；
    - 开关：use_proxy=true→--proxy；headless=false→--headed；
      auto_solve=false→--no-auto-solve；
      retry_failed=true 且 1688_contact→--retry-failed；
    """
    sub = TASK_COMMANDS.get(task_type)
    if not sub:
        raise ValueError(f"未知任务类型: {task_type}")
    params = params or {}
    cmd = [PYTHON_BIN, "-m", "fetcher"] + sub
    for key, flag in _NUMERIC_FLAGS:
        val = params.get(key)
        if val is not None:
            cmd += [flag, str(val)]
    if params.get("use_proxy") is True:
        cmd.append("--proxy")
    if params.get("headless") is False:
        cmd.append("--headed")
    if params.get("auto_solve") is False:
        cmd.append("--no-auto-solve")
    if task_type == "1688_contact" and params.get("retry_failed") is True:
        cmd.append("--retry-failed")
    return cmd


def _db_write(sql: str, params=()) -> None:
    """短事务写入；busy_timeout 避免与 WAL 写入者冲突。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _insert_event(task_id: int, level: str, message: str, data=None) -> None:
    _db_write(
        "INSERT INTO task_events (task_id, ts, level, message, data_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (task_id, beijing_now(), level, message[:500],
         json.dumps(data, ensure_ascii=False) if data is not None else None),
    )


_WORKER_NUM_RE = re.compile(r"^\s*\[(\d+)\]")
_WORKER_IDENTITY_RE = re.compile(r"identity=([^\s)，、]+)")


# ==================== P4 批次 sweeper（模块级函数，测试可直接调用） ====================


def _batch_items_stats(batch_id: int) -> dict:
    """聚合某批次 work_items 状态计数。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM work_items WHERE batch_id=?"
            " GROUP BY status", (batch_id,)).fetchall()
    finally:
        conn.close()
    stats = {"pending": 0, "claimed": 0, "done": 0, "failed": 0,
             "stopped": 0}
    for st, cnt in rows:
        if st in stats:
            stats[st] = cnt
    return stats


def _derive_batch_status(stats: dict, stop_requested: bool) -> str:
    """按 work_items 聚合派生批次任务状态。

    - 存在 pending/claimed → running（有活项）；
    - 全部终态（done/failed/stopped）且无 pending/claimed：
      stop_requested 且无 pending → stopped；否则 done（有 failed 也
      done，failed 计数进 progress——与现状 CLI 部分失败=整体跑完一致）；
    - 无任何 work_items（批次未入队/空）→ pending 保持（sweeper 不动）。
    """
    if stats["pending"] > 0 or stats["claimed"] > 0:
        return "running"
    if stats["pending"] == 0 and (stats["done"] > 0 or stats["failed"] > 0
                                   or stats["stopped"] > 0):
        if stop_requested and stats["pending"] == 0:
            return "stopped"
        return "done"
    return "pending"  # 无任何项（未入队）


def sweep_batch_tasks() -> None:
    """批次任务 sweeper 单次 tick：状态派生 + stopped 兜底 + progress 节流。

    遍历所有非终态批次任务（tasks.status NOT IN done/failed/stopped
    或 waiting 派生），逐项：
    1. stopped 兜底：stop_requested=1 的批次，pending 项压 stopped；
    2. 聚合 work_items → 派生状态写回 tasks.status；
    3. progress_json 节流（1s）写 {total,done,failed,stopped,claimed,
       pending,updated_at}。
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        rows = conn.execute(
            "SELECT id, type, params_json, stop_requested, status"
            " FROM tasks WHERE type IN ("
            + ",".join("?" * len(BATCH_TYPE_NAMES)) + ")",
            tuple(BATCH_TYPE_NAMES)).fetchall()
    finally:
        conn.close()
    for row in rows:
        if row["status"] in ("done", "failed", "stopped"):
            continue  # 终态不动（waiting 由 API 层派生）
        tid = row["id"]
        stop_req = bool(row["stop_requested"])
        # 1. stopped 兜底：防 daemon 重启 reset_claimed 复活 pending
        if stop_req:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
                conn.execute(
                    "UPDATE work_items SET status='stopped'"
                    " WHERE batch_id=? AND status='pending'", (tid,))
                conn.commit()
            finally:
                conn.close()
        # 2. 状态派生
        stats = _batch_items_stats(tid)
        derived = _derive_batch_status(stats, stop_req)
        if derived == "running":
            # 已 running 且非 stop：只更新 progress
            pass
        now = beijing_now()
        if derived != "pending":
            conn = sqlite3.connect(DB_PATH, timeout=30)
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
                conn.execute(
                    "UPDATE tasks SET status=?, finished_at=? WHERE id=?",
                    (derived, now if derived in ("done", "stopped") else None,
                     tid))
                conn.commit()
            finally:
                conn.close()
        # 3. progress 节流
        _write_batch_progress(tid, stats)


def _write_batch_progress(task_id: int, stats: dict) -> None:
    """写批次进度（1s 节流由调用方/线程控制；此处只写库）。"""
    progress = {
        "total": sum(stats.values()),
        "done": stats["done"],
        "failed": stats["failed"],
        "stopped": stats["stopped"],
        "claimed": stats["claimed"],
        "pending": stats["pending"],
        "updated_at": beijing_now(),
    }
    _db_write(
        "UPDATE tasks SET progress_json=? WHERE id=?",
        (json.dumps(progress, ensure_ascii=False), task_id))


def enqueue_batch_for_task(task_id: int, task_type: str,
                           params: dict) -> int:
    """批次任务入队：按 BATCH_TYPES 分派 contact/feeder/wa。返回 item 数。

    contact：limit 限量；feeder：discover+category 种子；wa：账号清单
    （params.accounts）50/块。batch_id = task_id。
    """
    spec = BATCH_TYPES.get(task_type)
    if spec is None:
        raise ValueError(f"非批次任务类型: {task_type}")
    params = params or {}
    limit = int(params.get("limit") or 0)
    from app.db import (enqueue_contact_batch, enqueue_feeder_batch,
                        enqueue_wa_batch)
    if spec["kind"] == "contact":
        return enqueue_contact_batch(spec["queue"], spec["site"],
                                     spec["domain_suffix"], task_id, limit)
    if spec["kind"] == "feeder":
        n_cat, n_disc = enqueue_feeder_batch(
            spec["queue"], spec["site"], task_id, limit)
        return n_cat + n_disc
    if spec["kind"] == "wa":
        accounts = params.get("accounts") or []
        return enqueue_wa_batch(task_id, accounts, limit)
    return 0


def stop_batch_task(task_id: int) -> None:
    """批次任务停止：置 stop_requested + pending 项压 stopped（sweeper 兜底
    会持续压，claimed 项跑完自然终态）。"""
    _db_write("UPDATE tasks SET stop_requested=1 WHERE id=?", (task_id,))
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute(
            "UPDATE work_items SET status='stopped'"
            " WHERE batch_id=? AND status='pending'", (task_id,))
        conn.commit()
    finally:
        conn.close()


def _extract_worker(line: str):
    """提取日志的 worker 标识，供前端分色。
    支持：行首编号标记 "[2] ..."；代理身份 identity=出口IP（每 worker 一个）。
    """
    m = _WORKER_NUM_RE.match(line)
    if m:
        return {"worker": int(m.group(1))}
    m = _WORKER_IDENTITY_RE.search(line)
    if m:
        return {"worker": m.group(1)}
    return None


class _RunEntry:
    __slots__ = ("proc", "thread", "stop_requested", "lines", "tail", "lock")

    def __init__(self, proc=None):
        self.proc = proc
        self.thread = None
        self.stop_requested = False
        self.lines = 0
        self.tail = []
        self.lock = threading.Lock()


class TaskRunner:
    """进程注册表在内存；随 FastAPI lifespan 初始化。"""

    # sweeper tick 间隔（秒）与进度节流
    SWEEPER_TICK = 5.0
    PROGRESS_THROTTLE = 1.0

    def __init__(self):
        self._runs = {}  # task_id -> _RunEntry
        self._timers = {}  # task_id -> threading.Timer（循环模式待重启）
        self._lock = threading.Lock()
        # P4 批次 sweeper 守护线程（批次任务无子进程，状态由它派生）
        self._sweeper_stop = threading.Event()
        self._sweeper_thread: threading.Thread | None = None
        self._last_progress: dict[int, float] = {}

    # ---------- 批次 sweeper ----------

    def _start_sweeper(self) -> None:
        """启动批次 sweeper 守护线程（5s tick，短事务）。"""
        if self._sweeper_thread is not None:
            return
        self._sweeper_stop.clear()
        self._sweeper_thread = threading.Thread(
            target=self._sweeper_loop, name="batch-sweeper", daemon=True)
        self._sweeper_thread.start()

    def _sweeper_loop(self) -> None:
        while not self._sweeper_stop.wait(self.SWEEPER_TICK):
            try:
                sweep_batch_tasks()
            except Exception as e:  # noqa: BLE001
                print(f"[sweeper] tick 异常: {e}")

    def _stop_sweeper(self) -> None:
        self._sweeper_stop.set()
        if self._sweeper_thread is not None:
            self._sweeper_thread.join(timeout=2)
        self._sweeper_thread = None

    # ---------- 生命周期 ----------

    def startup(self) -> None:
        """服务启动：幂等迁移 + 清理孤儿 running + 恢复循环模式待重启。

        P4：孤儿清理跳过批次类型（由 daemon 服务，uvicorn 重启不影响）；
        启动批次 sweeper（对非终态批次做状态重建）。
        """
        migrate()
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
            if BATCH_TYPE_NAMES:
                cur = conn.execute(
                    "UPDATE tasks SET status='failed', error=?, finished_at=? "
                    "WHERE status='running' AND type NOT IN ("
                    + ",".join("?" * len(BATCH_TYPE_NAMES)) + ")",
                    ("服务重启，进程丢失", beijing_now(), *BATCH_TYPE_NAMES))
            else:
                cur = conn.execute(
                    "UPDATE tasks SET status='failed', error=?, finished_at=? "
                    "WHERE status='running'",
                    ("服务重启，进程丢失", beijing_now()))
            conn.commit()
            if cur.rowcount:
                print(f"[runner] 清理孤儿 running 任务 {cur.rowcount} 个")
        finally:
            conn.close()
        # 重启前处于循环模式等待期的任务：重新安排自动重启，避免丢失后
        # 任务永远停在 done/failed（见 _recover_loop_restarts）。
        try:
            self._recover_loop_restarts()
        except Exception as e:
            print(f"[runner] 恢复循环重启失败: {e}")
        # P4：启动批次 sweeper（对非终态批次任务做状态重建/进度聚合）
        self._start_sweeper()

    def shutdown(self) -> None:
        """服务关闭：停 sweeper；取消待重启 Timer；终止仍在跑的子进程。"""
        # P4：停批次 sweeper
        self._stop_sweeper()
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
            entries = list(self._runs.items())
        for timer in timers:
            timer.cancel()
        for task_id, entry in entries:
            proc = entry.proc
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    # ---------- 启动 / 停止 ----------

    def start(self, task_id: int, task_type: str, params: dict):
        """启动任务：批次类型走平台入队；yiwugo 走 subprocess。

        返回 pid（subprocess）或 None（批次）。
        """
        if task_type in BATCH_TYPE_NAMES:
            try:
                n = enqueue_batch_for_task(task_id, task_type, params)
            except Exception as e:  # noqa: BLE001
                print(f"[runner] 批次 {task_id} 入队失败: {e}")
                raise
            _insert_event(
                task_id, "info",
                f"批次已提交：{BATCH_TYPES[task_type]['queue']}，"
                f"{n} 个工作项",
                {"queue": BATCH_TYPES[task_type]["queue"], "items": n})
            return None
        cmd = build_command(task_type, params)
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            errors="replace",
            env=env,
        )
        entry = _RunEntry(proc)
        with self._lock:
            self._runs[task_id] = entry
        t = threading.Thread(
            target=self._pump, args=(task_id, entry, cmd), daemon=True,
            name=f"task-pump-{task_id}",
        )
        entry.thread = t
        t.start()
        _insert_event(task_id, "info",
                      f"进程已启动 pid={proc.pid} 命令={' '.join(cmd)}"[:500],
                      {"pid": proc.pid, "cmd": cmd})
        return proc.pid

    def stop(self, task_id: int) -> bool:
        """先置 stop_requested=1；取消待重启 Timer；批次任务压 stopped
        pending 项；子进程 terminate。"""
        _db_write("UPDATE tasks SET stop_requested=1 WHERE id=?", (task_id,))
        # P4 批次：pending 项压 stopped（claimed 跑完自然终态）
        try:
            with self._lock:
                entry = self._runs.get(task_id)
            if task_id not in self._runs:
                stop_batch_task(task_id)
        except Exception as e:  # noqa: BLE001
            print(f"[runner] 批次 {task_id} 停止失败: {e}")
        timer_canceled = self.cancel_timer(task_id)
        with self._lock:
            entry = self._runs.get(task_id)
        if not entry:
            if timer_canceled:
                # 本轮已结束、正在等待自动重启：直接落终态 stopped，不再重启
                _db_write(
                    "UPDATE tasks SET status='stopped', finished_at=? "
                    "WHERE id=? AND status IN ('done', 'failed')",
                    (beijing_now(), task_id))
                _insert_event(task_id, "warning",
                              "循环模式：已取消自动重启（手动停止）")
                return True
            return False
        entry.stop_requested = True
        proc = entry.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:
                pass
        return True

    # ---------- 循环重启 ----------

    def cancel_timer(self, task_id: int) -> bool:
        """取消任务待重启 Timer（stop/delete/shutdown 时调用）。返回是否有 Timer 被取消。"""
        with self._lock:
            timer = self._timers.pop(task_id, None)
        if timer is not None:
            timer.cancel()
            return True
        return False

    def has_pending_timer(self, task_id: int) -> bool:
        with self._lock:
            return task_id in self._timers

    def _schedule_restart(self, task_id: int, delay: int) -> None:
        """登记/重置一个任务的循环重启 Timer：delay 秒后触发 _auto_restart。"""
        self.cancel_timer(task_id)
        timer = threading.Timer(max(0, int(delay)), self._auto_restart,
                                args=(task_id,))
        timer.daemon = True
        timer.name = f"task-restart-{task_id}"
        with self._lock:
            self._timers[task_id] = timer
        timer.start()

    def _maybe_schedule_restart(self, task_id: int, status: str) -> None:
        """本轮正常终态（done/failed）后，按 params.repeat_interval 安排自动重启。"""
        if status not in ("done", "failed"):
            return
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 30000")
            row = conn.execute(
                "SELECT params_json, stop_requested FROM tasks WHERE id=?",
                (task_id,)).fetchone()
        finally:
            conn.close()
        if not row or row["stop_requested"]:
            return
        try:
            params = json.loads(row["params_json"] or "{}")
        except ValueError:
            params = {}
        interval = params.get("repeat_interval")
        if not isinstance(interval, (int, float)) or interval <= 0:
            return
        interval = int(interval)
        try:
            _insert_event(
                task_id, "info",
                f"本轮结束（{status}），{interval} 秒后自动重启（循环模式）",
                {"repeat_interval": interval, "status": status})
        except Exception as e:
            print(f"[runner] task {task_id} 写重启事件失败: {e}")
        self._schedule_restart(task_id, interval)

    def _recover_loop_restarts(self) -> list:
        """服务重启后恢复循环模式任务的待重启定时器。

        仅对 status IN ('done','failed') 且 stop_requested=0、params 带
        repeat_interval>0 的任务重新安排自动重启：
        - 未到期的（finished_at + interval > now）按原节奏补足剩余等待，
          避免服务短暂重启把整轮周期提前；
        - 已到期的立即重启（delay=0），保证宕机期间漏掉的轮次继续循环。

        返回 [(task_id, delay)]，供测试断言与日志观察。
        """
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 30000")
            rows = conn.execute(
                "SELECT id, params_json, stop_requested, finished_at FROM tasks "
                "WHERE status IN ('done','failed') AND stop_requested=0"
            ).fetchall()
        finally:
            conn.close()
        scheduled: list = []
        now = datetime.now(BJ_TZ)
        for row in rows:
            try:
                params = json.loads(row["params_json"] or "{}")
            except ValueError:
                continue
            interval = params.get("repeat_interval")
            if not isinstance(interval, (int, float)) or interval <= 0:
                continue
            interval = int(interval)
            delay = interval
            if row["finished_at"]:
                try:
                    finish = datetime.strptime(
                        row["finished_at"], "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=BJ_TZ)
                    delay = max(0, interval - int((now - finish).total_seconds()))
                except ValueError:
                    pass
            try:
                _insert_event(
                    row["id"], "info",
                    f"服务重启，恢复循环模式：{delay} 秒后自动重启",
                    {"repeat_interval": interval, "delay": delay})
            except Exception as e:
                print(f"[runner] task {row['id']} 写恢复事件失败: {e}")
            self._schedule_restart(row["id"], delay)
            scheduled.append((row["id"], delay))
        return scheduled

    def _auto_restart(self, task_id: int) -> None:
        """Timer 触发：任务仍存在、未被停止、处于终态 → 走与 start 相同的重置逻辑再起一轮。"""
        with self._lock:
            self._timers.pop(task_id, None)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 30000")
            row = conn.execute("SELECT * FROM tasks WHERE id=?",
                               (task_id,)).fetchone()
        finally:
            conn.close()
        if not row or row["stop_requested"]:
            return
        if row["status"] not in ("done", "failed"):
            return
        if self.is_running(task_id):
            return
        try:
            params = json.loads(row["params_json"] or "{}")
        except ValueError:
            params = {}
        try:
            _db_write("DELETE FROM task_events WHERE task_id=?", (task_id,))
            _db_write(
                "UPDATE tasks SET status='running', error=NULL, progress_json=NULL, "
                "stop_requested=0, started_at=?, finished_at=NULL WHERE id=?",
                (beijing_now(), task_id))
            _insert_event(task_id, "info", "循环模式：自动重启任务")
            # P4 批次：循环重启走批次入队（新批次 item）
            if row["type"] in BATCH_TYPE_NAMES:
                n = enqueue_batch_for_task(task_id, row["type"], params)
                _insert_event(
                    task_id, "info",
                    f"批次已提交：{BATCH_TYPES[row['type']]['queue']}，"
                    f"{n} 个工作项")
            else:
                self.start(task_id, row["type"], params)
        except Exception as e:
            print(f"[runner] 任务 {task_id} 自动重启失败: {e}")
            try:
                _insert_event(task_id, "error", f"自动重启失败: {e}")
                _db_write(
                    "UPDATE tasks SET status='failed', error=?, finished_at=? "
                    "WHERE id=? AND status='running'",
                    (f"自动重启失败: {e}"[:500], beijing_now(), task_id))
            except Exception:
                pass

    def is_running(self, task_id: int) -> bool:
        with self._lock:
            entry = self._runs.get(task_id)
        if not entry:
            # P4 批次任务无进程/线程：由 sweeper 派生状态，这里返回 False
            return False
        if entry.proc is not None:
            return entry.proc.poll() is None
        t = entry.thread
        return bool(t and t.is_alive())

    # ---------- 输出泵 ----------

    def _pump(self, task_id: int, entry: _RunEntry, cmd: list) -> None:
        proc = entry.proc
        last_progress = 0.0
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\n").rstrip("\r")
                if not line.strip():
                    continue
                with entry.lock:
                    entry.lines += 1
                    n = entry.lines
                    entry.tail.append(line)
                    if len(entry.tail) > _TAIL_KEEP:
                        entry.tail.pop(0)
                try:
                    _insert_event(task_id, classify_line(line), line,
                                  data=_extract_worker(line))
                except Exception as e:
                    print(f"[runner] task {task_id} 写事件失败: {e}")
                now = time.monotonic()
                if now - last_progress >= _PROGRESS_THROTTLE_SEC:
                    last_progress = now
                    self._update_progress(task_id, line, n)
        except Exception as e:
            print(f"[runner] task {task_id} 读输出异常: {e}")
        finally:
            rc = proc.wait()
            with entry.lock:
                n = entry.lines
                tail = list(entry.tail)
            self._update_progress(task_id,
                                  tail[-1] if tail else "", n)
            status = self._finalize(task_id, rc, entry.stop_requested, tail)
            with self._lock:
                self._runs.pop(task_id, None)
            try:
                self._maybe_schedule_restart(task_id, status)
            except Exception as e:
                print(f"[runner] task {task_id} 重启调度失败: {e}")

    def _update_progress(self, task_id: int, last_line: str, lines: int) -> None:
        progress = {
            "last_line": last_line[:500],
            "lines": lines,
            "updated_at": beijing_now(),
        }
        try:
            _db_write(
                "UPDATE tasks SET progress_json=? WHERE id=?",
                (json.dumps(progress, ensure_ascii=False), task_id),
            )
        except Exception as e:
            print(f"[runner] task {task_id} 更新进度失败: {e}")

    def _finalize(self, task_id: int, rc: int,
                  stopped: bool, tail: list) -> str:
        """回写终态并返回状态字符串（供循环重启调度判断）。"""
        ts = beijing_now()
        if stopped:
            status, error = "stopped", None
        elif rc == 0:
            status, error = "done", None
        else:
            status = "failed"
            error = (f"退出码 {rc}；尾部输出: " + " | ".join(tail[-5:]))[:500]
        try:
            _db_write(
                "UPDATE tasks SET status=?, error=?, finished_at=? WHERE id=?",
                (status, error, ts, task_id),
            )
            _insert_event(
                task_id,
                "success" if status == "done" else (
                    "warning" if status == "stopped" else "error"),
                f"进程退出 rc={rc}，任务状态 → {status}",
                {"returncode": rc, "status": status},
            )
        except Exception as e:
            print(f"[runner] task {task_id} 回写状态失败: {e}")
        return status


# 模块级单例，由 main.py lifespan 初始化
runner = TaskRunner()
