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
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

from app.db import DB_PATH, migrate

PROJECT_ROOT = "/Volumes/DataDrive/proj/public/1699"
PYTHON_BIN = os.path.join(PROJECT_ROOT, "platform/server/.venv/bin/python")

# 任务类型 → fetcher CLI 子命令
TASK_COMMANDS = {
    "1688_shop": ["1688", "shop"],
    "1688_contact": ["1688", "contact"],
    "1688_company": ["1688", "company"],
    "yiwugo_search": ["yiwugo", "search"],
}

# 进程内任务类型：不起 subprocess，在 API 进程内线程执行（见 app/wa_tasks.py）
IN_PROCESS_TYPES = {"wa_check"}

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
    - wa_check 等进程内类型不走这里。
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


class _RunEntry:
    __slots__ = ("proc", "thread", "stop_requested", "lines", "tail", "lock",
                 "stop_event")

    def __init__(self, proc=None, stop_event=None):
        self.proc = proc              # subprocess 任务非空；进程内任务为 None
        self.stop_event = stop_event  # 进程内任务的停止信号
        self.thread = None
        self.stop_requested = False
        self.lines = 0
        self.tail = []
        self.lock = threading.Lock()


class TaskRunner:
    """进程注册表在内存；随 FastAPI lifespan 初始化。"""

    def __init__(self):
        self._runs = {}  # task_id -> _RunEntry
        self._timers = {}  # task_id -> threading.Timer（循环模式待重启）
        self._lock = threading.Lock()

    # ---------- 生命周期 ----------

    def startup(self) -> None:
        """服务启动：幂等迁移 + 把 DB 里遗留的 running 任务标记为 failed。"""
        migrate()
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
            cur = conn.execute(
                "UPDATE tasks SET status='failed', error=?, finished_at=? "
                "WHERE status='running'",
                ("服务重启，进程丢失", beijing_now()),
            )
            conn.commit()
            if cur.rowcount:
                print(f"[runner] 清理孤儿 running 任务 {cur.rowcount} 个")
        finally:
            conn.close()

    def shutdown(self) -> None:
        """服务关闭：取消待重启 Timer；终止仍在跑的子进程 / 通知进程内任务停止。"""
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
            entries = list(self._runs.items())
        for timer in timers:
            timer.cancel()
        for task_id, entry in entries:
            if entry.stop_event is not None:
                entry.stop_event.set()
                continue
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
        # 等进程内任务线程收尾（wa 原子会随 stop_event 终止 node 子进程）
        for task_id, entry in entries:
            if entry.stop_event is not None and entry.thread:
                entry.thread.join(timeout=10)

    # ---------- 启动 / 停止 ----------

    def start(self, task_id: int, task_type: str, params: dict):
        """启动任务：进程内类型走线程执行器，其余起子进程。返回 pid 或 None。"""
        if task_type in IN_PROCESS_TYPES:
            return self._start_in_process(task_id, task_type, params)
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

    def _start_in_process(self, task_id: int, task_type: str, params: dict):
        """进程内任务：派生线程跑执行器（如 wa_tasks.run），stop_event 停止。"""
        stop_event = threading.Event()
        entry = _RunEntry(None, stop_event)
        with self._lock:
            self._runs[task_id] = entry
        t = threading.Thread(
            target=self._run_in_process,
            args=(task_id, entry, task_type, params),
            daemon=True, name=f"task-inproc-{task_id}",
        )
        entry.thread = t
        t.start()
        _insert_event(task_id, "info",
                      f"进程内任务已启动 type={task_type}",
                      {"type": task_type})
        return None

    def _run_in_process(self, task_id: int, entry: _RunEntry,
                        task_type: str, params: dict) -> None:
        try:
            if task_type == "wa_check":
                from app import wa_tasks  # 延迟导入，避免与 runner 循环依赖
                wa_tasks.run(task_id, params, entry.stop_event)
            else:
                raise ValueError(f"未知进程内任务类型: {task_type}")
        except Exception as e:
            # 双保险：执行器自身已 try/finalize，这里兜底未捕获的异常
            print(f"[runner] 进程内任务 {task_id} 异常: {e}")
            try:
                _insert_event(task_id, "error", f"进程内执行器异常: {e}")
                _db_write(
                    "UPDATE tasks SET status='failed', error=?, finished_at=? "
                    "WHERE id=? AND status='running'",
                    (f"进程内执行器异常: {e}"[:500], beijing_now(), task_id),
                )
            except Exception:
                pass
        finally:
            with self._lock:
                self._runs.pop(task_id, None)
            # 进程内任务循环模式：执行器自身已回写终态，按 DB 状态决定是否重启
            try:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                try:
                    conn.execute("PRAGMA busy_timeout = 30000")
                    row = conn.execute(
                        "SELECT status FROM tasks WHERE id=?",
                        (task_id,)).fetchone()
                finally:
                    conn.close()
                if row:
                    self._maybe_schedule_restart(task_id, row[0])
            except Exception as e:
                print(f"[runner] 进程内任务 {task_id} 重启调度失败: {e}")

    def stop(self, task_id: int) -> bool:
        """先置 stop_requested=1；取消待重启 Timer；进程内任务置 stop_event，子进程 terminate。"""
        _db_write("UPDATE tasks SET stop_requested=1 WHERE id=?", (task_id,))
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
        if entry.stop_event is not None:
            entry.stop_event.set()
            return True
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
        self.cancel_timer(task_id)
        timer = threading.Timer(interval, self._auto_restart, args=(task_id,))
        timer.daemon = True
        timer.name = f"task-restart-{task_id}"
        with self._lock:
            self._timers[task_id] = timer
        timer.start()

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
            _db_write(
                "UPDATE tasks SET status='running', error=NULL, progress_json=NULL, "
                "stop_requested=0, started_at=?, finished_at=NULL WHERE id=?",
                (beijing_now(), task_id))
            _insert_event(task_id, "info", "循环模式：自动重启任务")
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
                    _insert_event(task_id, classify_line(line), line)
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
