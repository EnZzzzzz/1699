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


def build_command(task_type: str, params: dict) -> list:
    sub = TASK_COMMANDS.get(task_type)
    if not sub:
        raise ValueError(f"未知任务类型: {task_type}")
    params = params or {}
    cmd = [PYTHON_BIN, "-m", "fetcher"] + sub
    if params.get("use_proxy", True):
        cmd.append("--proxy")
    batch_num = int(params.get("batch_num") or 10)
    cmd += ["-n", str(batch_num)]
    max_batches = int(params.get("max_batches") or 0)
    if max_batches > 0:
        cmd += ["--max-batches", str(max_batches)]
    limit = int(params.get("limit") or 0)
    if limit > 0:
        cmd += ["--limit", str(limit)]
    if not params.get("headless", True):
        cmd.append("--headed")
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
        """服务关闭：终止仍在跑的子进程 / 通知进程内任务停止，避免留下孤儿。"""
        with self._lock:
            entries = list(self._runs.items())
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

    def stop(self, task_id: int) -> bool:
        """先置 stop_requested=1；进程内任务置 stop_event，子进程 terminate。"""
        _db_write("UPDATE tasks SET stop_requested=1 WHERE id=?", (task_id,))
        with self._lock:
            entry = self._runs.get(task_id)
        if not entry:
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
            self._finalize(task_id, rc, entry.stop_requested, tail)
            with self._lock:
                self._runs.pop(task_id, None)

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
                  stopped: bool, tail: list) -> None:
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


# 模块级单例，由 main.py lifespan 初始化
runner = TaskRunner()
