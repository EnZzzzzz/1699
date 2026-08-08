# Review package — Step 1.1 (BASE 46ee562..HEAD 18e0cb8)

## git log
18e0cb8 refactor(p5): 删除 wa_tasks 进程内执行器与 runner 进程内机械

## git diff --stat
 platform/server/app/api/tasks.py                |   8 +-
 platform/server/app/db.py                       |   2 +-
 platform/server/app/runner.py                   |  86 +----
 platform/server/app/wa_tasks.py                 | 445 ------------------------
 platform/server/tests/test_wa_tasks_cooldown.py | 168 ---------
 platform/server/tests/test_wa_tasks_guard.py    | 104 ------
 6 files changed, 9 insertions(+), 804 deletions(-)

## git diff -U10
diff --git a/platform/server/app/api/tasks.py b/platform/server/app/api/tasks.py
index cdadc70..8802343 100644
--- a/platform/server/app/api/tasks.py
+++ b/platform/server/app/api/tasks.py
@@ -2,22 +2,22 @@
 import asyncio
 import json
 import sqlite3
 from datetime import datetime, timedelta
 
 from fastapi import APIRouter, HTTPException, Request
 from fastapi.responses import StreamingResponse
 from pydantic import BaseModel, Field
 
 from app.db import DB_PATH, connect
-from app.runner import (BATCH_TYPE_NAMES, BATCH_TYPES, IN_PROCESS_TYPES,
-                        PYTHON_BIN, TASK_COMMANDS, beijing_now, build_command,
+from app.runner import (BATCH_TYPE_NAMES, BATCH_TYPES, PYTHON_BIN,
+                        TASK_COMMANDS, beijing_now, build_command,
                         enqueue_batch_for_task, runner, stop_batch_task,
                         _insert_event)
 
 router = APIRouter()
 
 TASK_TYPES = sorted(set(TASK_COMMANDS) | set(BATCH_TYPES))
 
 
 def _parse_json(text):
     if not text:
@@ -107,21 +107,21 @@ class TaskParams(BaseModel):
     ip_retry: int | None = None             # → --ip-retry
     net_retry: int | None = None            # → --net-retry
     max_consecutive_fail: int | None = None  # → --max-consecutive-fail
     block_rest_min: float | None = None     # → --block-rest-min
     block_rest_max: float | None = None     # → --block-rest-max
     # 开关
     use_proxy: bool | None = None           # true → --proxy
     headless: bool | None = None            # false → --headed
     auto_solve: bool | None = None          # false → --no-auto-solve
     retry_failed: bool | None = None        # true 且 1688_contact → --retry-failed
-    # wa_check（进程内 WhatsApp 查号）专用：
+    # wa_check 专用：
     interval: float | None = None           # 旧参数：固定调用间隔秒（等价
                                             # sample_min == sample_max）
     accounts: list[str] | None = None       # 账号池，空 = 仅默认账号
     batch_rest_min: float | None = None     # wa_check 批间休息下限（秒）
     batch_rest_max: float | None = None     # wa_check 批间休息上限（秒）
     # 注：wa_check 复用上方 batch_num（每批调用次数）、
     # sample_min / sample_max（调用间隔范围）三个字段
     # 循环模式：本轮正常结束（done/failed）后 N 秒自动重启；None/<=0 = 不循环
     repeat_interval: int | None = None
 
@@ -193,22 +193,20 @@ def preview_task(body: TaskCreate):
             status_code=422,
             detail=f"未知任务类型 {body.type!r}，可选: {TASK_TYPES}")
     params = body.params.model_dump()
     if body.type in BATCH_TYPE_NAMES:
         spec = BATCH_TYPES[body.type]
         limit = params.get("limit")
         desc = f"批次提交：{spec['queue']}"
         if limit:
             desc += f"，{limit} 条"
         return {"cmd": None, "cmdline": desc}
-    if body.type in IN_PROCESS_TYPES:
-        return {"cmd": None, "cmdline": "进程内执行（CheckWhatsApp 原子）"}
     try:
         cmd = build_command(body.type, params)
     except ValueError as e:
         raise HTTPException(status_code=422, detail=str(e))
     # 展示串：绝对路径 python 换成 python，保持真实可读
     cmdline = " ".join("python" if p == PYTHON_BIN else p for p in cmd)
     return {"cmd": cmd, "cmdline": cmdline}
 
 
 class TaskUpdate(BaseModel):
diff --git a/platform/server/app/db.py b/platform/server/app/db.py
index 7d3ab1e..e441abb 100644
--- a/platform/server/app/db.py
+++ b/platform/server/app/db.py
@@ -220,21 +220,21 @@ def _normalize_numbers(raw, default_cc="86"):
         if 8 <= len(digits) <= 15 and digits not in seen:
             seen.add(digits)
             out.append(digits)
     return out
 
 
 def enqueue_wa_batch(batch_id: int, accounts: list[str],
                      limit: int = 0) -> int:
     """wa_check 批次入队：contacts 未查号码 → 50/块 → 账号按块轮换。
 
-    accounts 为空拒绝（防空跑 default 主号，与 wa_tasks 拒绝语义一致）。
+    accounts 为空拒绝（防空跑 default 主号）。
     requires=["local"]、site=NULL。返回入队 item 数。
     """
     accounts = [str(a).strip() for a in (accounts or []) if str(a).strip()]
     if not accounts:
         return 0
     conn = sqlite3.connect(DB_PATH, timeout=30)
     try:
         conn.execute("PRAGMA busy_timeout = 30000")
         sql = ("SELECT mobile FROM contacts WHERE wa_checked_at IS NULL"
                " AND mobile IS NOT NULL AND TRIM(mobile) <> ''"
diff --git a/platform/server/app/runner.py b/platform/server/app/runner.py
index 22a4742..8b76ca2 100644
--- a/platform/server/app/runner.py
+++ b/platform/server/app/runner.py
@@ -23,24 +23,20 @@ from datetime import datetime, timedelta, timezone
 from app.db import DB_PATH, migrate
 
 PROJECT_ROOT = "/Volumes/DataDrive/proj/public/1699"
 PYTHON_BIN = os.path.join(PROJECT_ROOT, "platform/server/.venv/bin/python")
 
 # 任务类型 → fetcher CLI 子命令（P4：只剩 yiwugo_search，其余批次化）
 TASK_COMMANDS = {
     "yiwugo_search": ["yiwugo", "search"],
 }
 
-# 进程内任务类型（P4：清空——wa_check 迁入 daemon LocalExecutor；
-# wa_tasks.py 冻结不删，P5 移除）
-IN_PROCESS_TYPES: set[str] = set()
-
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
@@ -115,21 +111,20 @@ _NUMERIC_FLAGS = (
 
 
 def build_command(task_type: str, params: dict) -> list:
     """任务类型 + params → fetcher CLI 命令列表（subprocess 直接 Popen）。
 
     规则：
     - 数值/时长参数值非 None 才输出（缺省=CLI 自带默认值，保持命令干净）；
     - 开关：use_proxy=true→--proxy；headless=false→--headed；
       auto_solve=false→--no-auto-solve；
       retry_failed=true 且 1688_contact→--retry-failed；
-    - wa_check 等进程内类型不走这里。
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
@@ -332,26 +327,24 @@ def _extract_worker(line: str):
     m = _WORKER_NUM_RE.match(line)
     if m:
         return {"worker": int(m.group(1))}
     m = _WORKER_IDENTITY_RE.search(line)
     if m:
         return {"worker": m.group(1)}
     return None
 
 
 class _RunEntry:
-    __slots__ = ("proc", "thread", "stop_requested", "lines", "tail", "lock",
-                 "stop_event")
+    __slots__ = ("proc", "thread", "stop_requested", "lines", "tail", "lock")
 
-    def __init__(self, proc=None, stop_event=None):
-        self.proc = proc              # subprocess 任务非空；进程内任务为 None
-        self.stop_event = stop_event  # 进程内任务的停止信号
+    def __init__(self, proc=None):
+        self.proc = proc
         self.thread = None
         self.stop_requested = False
         self.lines = 0
         self.tail = []
         self.lock = threading.Lock()
 
 
 class TaskRunner:
     """进程注册表在内存；随 FastAPI lifespan 初始化。"""
 
@@ -423,70 +416,60 @@ class TaskRunner:
         # 重启前处于循环模式等待期的任务：重新安排自动重启，避免丢失后
         # 任务永远停在 done/failed（见 _recover_loop_restarts）。
         try:
             self._recover_loop_restarts()
         except Exception as e:
             print(f"[runner] 恢复循环重启失败: {e}")
         # P4：启动批次 sweeper（对非终态批次任务做状态重建/进度聚合）
         self._start_sweeper()
 
     def shutdown(self) -> None:
-        """服务关闭：停 sweeper；取消待重启 Timer；终止仍在跑的子进程 /
-        通知进程内任务停止。"""
+        """服务关闭：停 sweeper；取消待重启 Timer；终止仍在跑的子进程。"""
         # P4：停批次 sweeper
         self._stop_sweeper()
         with self._lock:
             timers = list(self._timers.values())
             self._timers.clear()
             entries = list(self._runs.items())
         for timer in timers:
             timer.cancel()
         for task_id, entry in entries:
-            if entry.stop_event is not None:
-                entry.stop_event.set()
-                continue
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
-        # 等进程内任务线程收尾（wa 原子会随 stop_event 终止 node 子进程）
-        for task_id, entry in entries:
-            if entry.stop_event is not None and entry.thread:
-                entry.thread.join(timeout=10)
 
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
-        if task_type in IN_PROCESS_TYPES:
-            return self._start_in_process(task_id, task_type, params)
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
@@ -499,79 +482,23 @@ class TaskRunner:
             target=self._pump, args=(task_id, entry, cmd), daemon=True,
             name=f"task-pump-{task_id}",
         )
         entry.thread = t
         t.start()
         _insert_event(task_id, "info",
                       f"进程已启动 pid={proc.pid} 命令={' '.join(cmd)}"[:500],
                       {"pid": proc.pid, "cmd": cmd})
         return proc.pid
 
-    def _start_in_process(self, task_id: int, task_type: str, params: dict):
-        """进程内任务：派生线程跑执行器（如 wa_tasks.run），stop_event 停止。"""
-        stop_event = threading.Event()
-        entry = _RunEntry(None, stop_event)
-        with self._lock:
-            self._runs[task_id] = entry
-        t = threading.Thread(
-            target=self._run_in_process,
-            args=(task_id, entry, task_type, params),
-            daemon=True, name=f"task-inproc-{task_id}",
-        )
-        entry.thread = t
-        t.start()
-        _insert_event(task_id, "info",
-                      f"进程内任务已启动 type={task_type}",
-                      {"type": task_type})
-        return None
-
-    def _run_in_process(self, task_id: int, entry: _RunEntry,
-                        task_type: str, params: dict) -> None:
-        try:
-            if task_type == "wa_check":
-                from app import wa_tasks  # 延迟导入，避免与 runner 循环依赖
-                wa_tasks.run(task_id, params, entry.stop_event)
-            else:
-                raise ValueError(f"未知进程内任务类型: {task_type}")
-        except Exception as e:
-            # 双保险：执行器自身已 try/finalize，这里兜底未捕获的异常
-            print(f"[runner] 进程内任务 {task_id} 异常: {e}")
-            try:
-                _insert_event(task_id, "error", f"进程内执行器异常: {e}")
-                _db_write(
-                    "UPDATE tasks SET status='failed', error=?, finished_at=? "
-                    "WHERE id=? AND status='running'",
-                    (f"进程内执行器异常: {e}"[:500], beijing_now(), task_id),
-                )
-            except Exception:
-                pass
-        finally:
-            with self._lock:
-                self._runs.pop(task_id, None)
-            # 进程内任务循环模式：执行器自身已回写终态，按 DB 状态决定是否重启
-            try:
-                conn = sqlite3.connect(DB_PATH, timeout=30)
-                try:
-                    conn.execute("PRAGMA busy_timeout = 30000")
-                    row = conn.execute(
-                        "SELECT status FROM tasks WHERE id=?",
-                        (task_id,)).fetchone()
-                finally:
-                    conn.close()
-                if row:
-                    self._maybe_schedule_restart(task_id, row[0])
-            except Exception as e:
-                print(f"[runner] 进程内任务 {task_id} 重启调度失败: {e}")
-
     def stop(self, task_id: int) -> bool:
         """先置 stop_requested=1；取消待重启 Timer；批次任务压 stopped
-        pending 项；进程内任务置 stop_event，子进程 terminate。"""
+        pending 项；子进程 terminate。"""
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
@@ -582,23 +509,20 @@ class TaskRunner:
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
-        if entry.stop_event is not None:
-            entry.stop_event.set()
-            return True
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
diff --git a/platform/server/app/wa_tasks.py b/platform/server/app/wa_tasks.py
deleted file mode 100644
index 5d50385..0000000
--- a/platform/server/app/wa_tasks.py
+++ /dev/null
@@ -1,445 +0,0 @@
-# -*- coding: utf-8 -*-
-"""wa_check 进程内任务执行器（WhatsApp 全量查号）。
-
-与 subprocess 类任务不同：本执行器在 API 进程内的线程里跑，分批调用
-fetcher 的 CheckWhatsApp 原子（原子内部每次调用会拉起 node 子进程连接
-WhatsApp，约 5-10s/批，属正常）。
-
-流程：
-- 待查号码：contacts 中 wa_checked_at IS NULL 且 mobile 非空，按 id 升序，
-  params["limit"]>0 时限量；
-- 规范化：fetcher normalize_numbers(mobile, default_cc="86")；
-- 每批 50 个号码调一次原子；params["accounts"] 非空时按批轮换账号
-  （"default" 映射为原子的缺省账号），空列表 = 仅默认账号；
-- 每批写回 contacts（wa_registered/wa_checked_at，北京时间；按号码后 11 位
-  对齐 mobile/phone，仅更新规范化后严格匹配的行，歧义则跳过）；
-- 每批写 task_events + throttle 更新 tasks.progress_json
-  {"total","checked","registered","current_account"}；
-- stop_event 置位或 tasks.stop_requested=1（每批检查一次 DB）→ 优雅停止；
-- 原子连续 FATAL（未登录/登出，不可自愈）→ failed。
-
-节奏控制（与其他采集任务同策略）：
-- 逐号码间隔：params["sample_min"]/["sample_max"]（秒）范围内的随机停顿，
-  在 check.js 逐号循环内生效（默认 1.5s 固定）；兼容旧参数
-  params["interval"]（等价于 min == max）；
-- 批次：每 params["batch_num"] 个号码（默认 500）为一批，采满后批间
-  休息 params["batch_rest_min"]~["batch_rest_max"] 秒随机时长；
-- 批间休息可被 stop_event 中断。
-
-DB 写入一律短事务 + busy_timeout（1688.db 为 WAL，正被采集进程写入）。
-"""
-
-import json
-import random
-import sqlite3
-import threading
-import time
-
-from fetcher.atoms.wa_check import CheckWhatsApp, normalize_numbers
-from fetcher.core.context import WorkerContext
-from fetcher.core.types import Outcome
-
-from app.db import DB_PATH, migrate
-from app.runner import _db_write, _insert_event, beijing_now
-
-BATCH_SIZE = 50
-DEFAULT_CC = "86"
-MAX_CONSECUTIVE_FATAL = 2
-_PROGRESS_THROTTLE_SEC = 1.0
-
-# 风控冷却：批内错误率 ≥ 阈值判定疑似风控，批后额外长冷却（防风控加重）
-THROTTLE_RATIO = 0.3
-THROTTLE_COOLDOWN_MIN = 1200.0   # 20 分钟
-THROTTLE_COOLDOWN_MAX = 1800.0   # 30 分钟
-
-# 节奏默认值：逐号码随机间隔 1.5s 固定（check.js 内部缺省）；
-# 每 500 个号码一批，批间休息随机 60~180s
-DEFAULT_SAMPLE_MIN = 1.5
-DEFAULT_SAMPLE_MAX = 1.5
-DEFAULT_BATCH_NUM = 500
-DEFAULT_BATCH_REST_MIN = 60.0
-DEFAULT_BATCH_REST_MAX = 180.0
-
-
-def _pacing_params(params: dict) -> tuple[float, float, int, float, float]:
-    """解析节奏参数：(sample_min, sample_max, batch_num, rest_min, rest_max)。
-
-    sample_min/max 为逐号码随机间隔（秒），batch_num 为每批号码数，
-    rest_min/max 为批间休息范围（秒）。兼容旧参数 interval（固定间隔）：
-    显式给了 interval 而没给 sample_min/sample_max 时，等价于
-    sample_min == sample_max == interval。
-    """
-    interval = params.get("interval")
-    sample_min = params.get("sample_min")
-    sample_max = params.get("sample_max")
-    if interval is not None:
-        interval = float(interval)
-        if sample_min is None:
-            sample_min = interval
-        if sample_max is None:
-            sample_max = interval
-    lo = float(sample_min) if sample_min is not None else DEFAULT_SAMPLE_MIN
-    hi = float(sample_max) if sample_max is not None else DEFAULT_SAMPLE_MAX
-    lo, hi = max(0.0, lo), max(0.0, hi)
-    if lo > hi:
-        lo, hi = hi, lo
-    batch_num = int(params.get("batch_num") or DEFAULT_BATCH_NUM)
-    r_lo = float(params.get("batch_rest_min")
-                 if params.get("batch_rest_min") is not None
-                 else DEFAULT_BATCH_REST_MIN)
-    r_hi = float(params.get("batch_rest_max")
-                 if params.get("batch_rest_max") is not None
-                 else DEFAULT_BATCH_REST_MAX)
-    r_lo, r_hi = max(0.0, r_lo), max(0.0, r_hi)
-    if r_lo > r_hi:
-        r_lo, r_hi = r_hi, r_lo
-    return lo, hi, max(0, batch_num), r_lo, r_hi
-
-
-def _fetch_pending_rows(limit: int) -> list:
-    """待查联系人：wa_checked_at IS NULL 且 mobile 非空，id 升序。"""
-    sql = ("SELECT id, mobile FROM contacts "
-           "WHERE wa_checked_at IS NULL "
-           "AND mobile IS NOT NULL AND TRIM(mobile) <> '' "
-           "ORDER BY id ASC")
-    params = ()
-    if limit > 0:
-        sql += " LIMIT ?"
-        params = (limit,)
-    conn = sqlite3.connect(DB_PATH, timeout=30)
-    try:
-        conn.execute("PRAGMA busy_timeout = 30000")
-        return conn.execute(sql, params).fetchall()
-    finally:
-        conn.close()
-
-
-def _db_stop_requested(task_id: int) -> bool:
-    conn = sqlite3.connect(DB_PATH, timeout=30)
-    try:
-        conn.execute("PRAGMA busy_timeout = 30000")
-        row = conn.execute(
-            "SELECT stop_requested FROM tasks WHERE id=?",
-            (task_id,)).fetchone()
-        return bool(row and row[0])
-    finally:
-        conn.close()
-
-
-def _write_progress(task_id: int, total: int, checked: int,
-                    registered: int, current_account: str) -> None:
-    progress = {
-        "total": total,
-        "checked": checked,
-        "registered": registered,
-        "current_account": current_account,
-        "updated_at": beijing_now(),
-    }
-    try:
-        _db_write(
-            "UPDATE tasks SET progress_json=? WHERE id=?",
-            (json.dumps(progress, ensure_ascii=False), task_id),
-        )
-    except Exception as e:
-        print(f"[wa_tasks] task {task_id} 更新进度失败: {e}")
-
-
-def _finalize(task_id: int, status: str, error: str | None) -> None:
-    ts = beijing_now()
-    try:
-        _db_write(
-            "UPDATE tasks SET status=?, error=?, finished_at=? WHERE id=?",
-            (status, error, ts, task_id),
-        )
-        _insert_event(
-            task_id,
-            "success" if status == "done" else (
-                "warning" if status == "stopped" else "error"),
-            f"任务结束，状态 → {status}" + (f"：{error}" if error else ""),
-            {"status": status, "error": error},
-        )
-    except Exception as e:
-        print(f"[wa_tasks] task {task_id} 回写状态失败: {e}")
-
-
-def _apply_results(results: list) -> tuple[int, int, int]:
-    """把一批查号结果写回 contacts。
-
-    匹配策略：按号码后 11 位（num11）做 LIKE 候选过滤（mobile 或 phone
-    去空格后以此结尾），再用 normalize_numbers 规范化候选行号码做严格
-    相等校验；仅当存在严格匹配行、或候选行唯一时才 UPDATE，歧义跳过。
-
-    返回 (写回行数, 结果错误跳过数, 歧义跳过数)。
-    """
-    written = skipped_err = skipped_amb = 0
-    ts = beijing_now()
-    conn = sqlite3.connect(DB_PATH, timeout=30)
-    try:
-        conn.row_factory = sqlite3.Row
-        conn.execute("PRAGMA busy_timeout = 30000")
-        for r in results:
-            num = str(r.get("number") or "")
-            reg = r.get("registered")
-            if not num or reg is None:
-                skipped_err += 1
-                continue
-            pat = "%" + num[-11:]
-            rows = conn.execute(
-                "SELECT id, mobile, phone FROM contacts "
-                "WHERE REPLACE(mobile, ' ', '') LIKE :p "
-                "OR REPLACE(phone, ' ', '') LIKE :p",
-                {"p": pat}).fetchall()
-            exact = [row for row in rows
-                     if num in normalize_numbers([row["mobile"]], DEFAULT_CC)
-                     or num in normalize_numbers([row["phone"]], DEFAULT_CC)]
-            if exact:
-                targets = exact
-            elif len(rows) == 1:
-                targets = rows
-            else:
-                skipped_amb += 1
-                continue
-            marks = ",".join("?" * len(targets))
-            conn.execute(
-                f"UPDATE contacts SET wa_registered=?, wa_checked_at=? "
-                f"WHERE id IN ({marks})",
-                (1 if reg else 0, ts,
-                 *[row["id"] for row in targets]))
-            written += len(targets)
-        conn.commit()
-    finally:
-        conn.close()
-    return written, skipped_err, skipped_amb
-
-
-def _rest_with_heartbeat(task_id: int, seconds: float, label: str,
-                         stop_event: threading.Event) -> bool:
-    """分段等待 + 心跳日志，可被 stop_event 中断；返回是否被中断。
-
-    每段最多 30s 刷一条「剩余约 N 分钟」心跳，避免休息期间日志静默
-    被误判为卡死；每段都可被 stop_event 中断。
-    """
-    deadline = time.monotonic() + seconds
-    while True:
-        remaining = deadline - time.monotonic()
-        if remaining <= 0:
-            return False
-        if stop_event.wait(min(30.0, remaining)):
-            return True
-        remaining = deadline - time.monotonic()
-        if remaining > 1:
-            _insert_event(
-                task_id, "info",
-                f"⏸ {label}，剩余约 {remaining / 60:.1f} 分钟...")
-
-
-def _atom_account(name: str) -> str:
-    """API 账号名 → 原子 account 参数："default" 用缺省 auth_info/。"""
-    return "" if name == "default" else name
-
-
-def run(task_id: int, params: dict, stop_event: threading.Event) -> None:
-    """wa_check 任务主循环（在 API 进程内线程中执行）。"""
-    atom = CheckWhatsApp()
-    try:
-        migrate()  # 防御：服务未跑迁移时也能工作
-        params = params or {}
-        limit = int(params.get("limit") or 0)
-        sample_min, sample_max, batch_num, rest_min, rest_max = \
-            _pacing_params(params)
-        accounts = [str(a).strip()
-                    for a in (params.get("accounts") or []) if str(a).strip()]
-
-        # 防主号误用（曾因此误封主号）：wa_check 不显式指定账号时，过去会
-        # 静默落到 default（= auth_info 主号），大批量协议查询有封号风险。
-        # 空账号一律拒绝启动；显式选 default 则警告（default 目录已删除时
-        # 原子层会以「未登录」FATAL，此处仅作提示）。
-        if not accounts:
-            _insert_event(
-                task_id, "error",
-                "wa_check 拒绝启动：未指定查号账号（accounts 为空）。"
-                "为避免静默使用 default（主号）导致封号，任务已中止，"
-                "请显式选择小号账号（如 xiaohao-1）后重试。",
-                {"accounts": [], "action": "refused"})
-            _finalize(
-                task_id, "failed",
-                "wa_check 未指定账号，拒绝启动（防空跑主号 default）")
-            return
-        if "default" in accounts:
-            _insert_event(
-                task_id, "warning",
-                "警告：账号池包含 default（对应 auth_info 主号），"
-                "协议批量查询有封号风险，请确认这是有意选择。",
-                {"accounts": accounts, "contains_default": True})
-
-        rows = _fetch_pending_rows(limit)
-        # 规范化 + 去重（保持顺序），一个号码可能对应多行联系人
-        numbers: list[str] = []
-        seen: set[str] = set()
-        for _id, mobile in rows:
-            for n in normalize_numbers([mobile], DEFAULT_CC):
-                if n not in seen:
-                    seen.add(n)
-                    numbers.append(n)
-        total = len(numbers)
-        account_label = "、".join(accounts) if accounts else "default"
-        _insert_event(
-            task_id, "info",
-            f"wa_check 启动：待查 {total} 个号码（{len(rows)} 行联系人），"
-            f"账号池：{account_label}，每次连接查 {BATCH_SIZE} 个，"
-            f"逐号间隔 {sample_min:g}~{sample_max:g}s（随机），"
-            f"每 {batch_num} 个号码一批，批间休息 "
-            f"{rest_min:g}~{rest_max:g}s（随机）",
-            {"total": total, "rows": len(rows), "accounts": accounts,
-             "batch_size": BATCH_SIZE,
-             "sample_min": sample_min, "sample_max": sample_max,
-             "batch_num": batch_num,
-             "batch_rest_min": rest_min, "batch_rest_max": rest_max})
-        if total == 0:
-            _write_progress(task_id, 0, 0, 0, account_label)
-            _finalize(task_id, "done", None)
-            return
-
-        batches = [numbers[i:i + BATCH_SIZE]
-                   for i in range(0, total, BATCH_SIZE)]
-        checked = 0
-        registered = 0
-        consec_fatal = 0
-        stopped = False
-        fail_detail = None
-        last_progress = 0.0
-        nums_since_rest = 0  # 距上次批间休息已成功查号的号码数
-        throttle_rest = False  # 本批疑似风控 → 批后额外长冷却
-
-        for bi, batch in enumerate(batches, 1):
-            if stop_event.is_set() or _db_stop_requested(task_id):
-                stopped = True
-                break
-            account_name = (accounts[(bi - 1) % len(accounts)]
-                            if accounts else "default")
-            ctx = WorkerContext(
-                stop=stop_event,
-                log=lambda m: _insert_event(
-                    task_id, "info", m.strip()[:500]))
-            res = atom.run(ctx, {
-                "numbers": batch,
-                "default_cc": DEFAULT_CC,
-                "account": _atom_account(account_name),
-                "sample_min": sample_min,
-                "sample_max": sample_max,
-            })
-
-            if res.outcome is Outcome.OK:
-                consec_fatal = 0
-                results = res.data.get("results") or []
-                written, skipped_err, skipped_amb = _apply_results(results)
-                hits = sum(1 for r in results if r.get("registered"))
-                done = sum(1 for r in results
-                           if r.get("registered") is not None)
-                err_cnt = len(results) - done
-                checked += done  # 只计有结果的号码，出错号码保持 NULL 待查
-                registered += hits
-                msg = (f"批次 {bi}/{len(batches)}：查 {done}/{len(batch)} 个，"
-                       f"累计已注册 {registered}")
-                extra = []
-                if err_cnt and len(results):
-                    ratio = err_cnt / len(results)
-                    extra.append(f"{err_cnt} 个查询出错未写回")
-                    if ratio >= THROTTLE_RATIO:
-                        throttle_rest = True
-                        _insert_event(
-                            task_id, "warning",
-                            f"批次 {bi}/{len(batches)} 错误率 {ratio:.0%}"
-                            f"（{err_cnt}/{len(results)}）"
-                            f" ≥{THROTTLE_RATIO:.0%}，疑似风控，批后将额外冷却",
-                            {"err_cnt": err_cnt, "ratio": round(ratio, 2),
-                             "throttle_rest": True})
-                if skipped_amb:
-                    extra.append(f"{skipped_amb} 个号码匹配歧义跳过")
-                if extra:
-                    msg += "（" + "，".join(extra) + "）"
-                _insert_event(task_id, "info", msg, {
-                    "batch": bi, "batches": len(batches),
-                    "worker": account_name,
-                    "account": account_name, "checked": checked,
-                    "registered": registered, "written": written,
-                })
-            elif res.outcome is Outcome.FATAL:
-                consec_fatal += 1
-                _insert_event(
-                    task_id, "error",
-                    f"批次 {bi}/{len(batches)} FATAL（账号 {account_name}）："
-                    f"{res.detail}")
-                if consec_fatal >= MAX_CONSECUTIVE_FATAL:
-                    fail_detail = (f"原子连续 {consec_fatal} 次 FATAL："
-                                   f"{res.detail}")
-                    break
-            elif res.outcome is Outcome.SKIPPED:
-                stopped = True
-                _insert_event(task_id, "warning",
-                              f"批次 {bi}/{len(batches)} 被停止信号中断")
-                break
-            else:  # NET_ERROR / EMPTY / BLOCKED：记警告后继续下一批
-                consec_fatal = 0
-                _insert_event(
-                    task_id, "warning",
-                    f"批次 {bi}/{len(batches)} {res.outcome.value}"
-                    f"（账号 {account_name}）：{res.detail}")
-
-            now = time.monotonic()
-            if now - last_progress >= _PROGRESS_THROTTLE_SEC:
-                last_progress = now
-                _write_progress(task_id, total, checked,
-                                registered, account_name)
-
-            # 批次配额（号码数计）：采满 batch_num 个号码后批间随机长休息
-            # （防风控）；逐号码间隔已在 check.js 循环内生效，批与批之间
-            # 的间隔即重连开销本身，不再额外 sleep。
-            if res.outcome is Outcome.OK:
-                nums_since_rest += len(batch)
-            if (bi < len(batches) and batch_num > 0
-                    and nums_since_rest >= batch_num):
-                rest = random.uniform(rest_min, rest_max)
-                _insert_event(
-                    task_id, "info",
-                    f"⏸ 本批已查满 {nums_since_rest} 个号码，"
-                    f"批间休息 {rest / 60:.1f} 分钟（防风控）...",
-                    {"checked": checked, "registered": registered,
-                     "rest_seconds": round(rest, 1)})
-                if _rest_with_heartbeat(task_id, rest, "批间休息",
-                                        stop_event):
-                    stopped = True
-                    break
-                nums_since_rest = 0
-                _insert_event(task_id, "info", "▶ 批间休息结束，继续查号")
-
-            # 风控冷却：高错误率批次后额外长休息（不等 batch_num 边界）
-            if throttle_rest and bi < len(batches):
-                cooldown = random.uniform(THROTTLE_COOLDOWN_MIN,
-                                          THROTTLE_COOLDOWN_MAX)
-                _insert_event(
-                    task_id, "warning",
-                    f"⏸ 疑似风控，额外冷却 {cooldown / 60:.1f} 分钟...",
-                    {"checked": checked, "registered": registered,
-                     "cooldown_seconds": round(cooldown, 1)})
-                if _rest_with_heartbeat(task_id, cooldown, "风控冷却",
-                                        stop_event):
-                    stopped = True
-                    break
-                throttle_rest = False
-
-        if fail_detail:
-            _finalize(task_id, "failed", fail_detail[:500])
-        elif stopped:
-            _finalize(task_id, "stopped", None)
-        else:
-            _finalize(task_id, "done", None)
-        _write_progress(task_id, total, checked, registered,
-                        accounts[-1] if accounts else "default")
-    except Exception as e:
-        print(f"[wa_tasks] task {task_id} 执行器异常: {e}")
-        try:
-            _insert_event(task_id, "error", f"执行器异常：{e}")
-        except Exception:
-            pass
-        _finalize(task_id, "failed", f"执行器异常：{e}"[:500])
diff --git a/platform/server/tests/test_wa_tasks_cooldown.py b/platform/server/tests/test_wa_tasks_cooldown.py
deleted file mode 100644
index 17032d3..0000000
--- a/platform/server/tests/test_wa_tasks_cooldown.py
+++ /dev/null
@@ -1,168 +0,0 @@
-# -*- coding: utf-8 -*-
-"""wa_tasks 分段等待助手与风控冷却测试。"""
-
-import json
-import os
-import sqlite3
-import tempfile
-import threading
-import unittest
-from unittest.mock import patch
-
-from fetcher.core.types import ActionResult
-from app import db, runner, wa_tasks
-
-
-def _make_db(path: str) -> None:
-    conn = sqlite3.connect(path)
-    conn.executescript(
-        """
-        CREATE TABLE tasks (
-            id INTEGER PRIMARY KEY,
-            type TEXT NOT NULL,
-            params_json TEXT NOT NULL,
-            celery_id TEXT,
-            status TEXT NOT NULL DEFAULT 'pending',
-            progress_json TEXT,
-            stop_requested INTEGER NOT NULL DEFAULT 0,
-            error TEXT,
-            created_at TEXT NOT NULL,
-            started_at TEXT,
-            finished_at TEXT,
-            flow_id INTEGER
-        );
-        CREATE TABLE task_events (
-            id INTEGER PRIMARY KEY AUTOINCREMENT,
-            task_id INTEGER NOT NULL,
-            ts TEXT NOT NULL,
-            level TEXT NOT NULL,
-            message TEXT NOT NULL,
-            data_json TEXT
-        );
-        CREATE TABLE contacts (
-            id INTEGER PRIMARY KEY,
-            mobile TEXT,
-            phone TEXT,
-            wa_registered INTEGER,
-            wa_checked_at TEXT
-        );
-        INSERT INTO tasks (id, type, params_json, status, created_at)
-        VALUES (1, 'wa_check', '{"accounts": ["xiaohao-1"]}',
-                'pending', '2026-08-05 12:00:00');
-        """
-    )
-    conn.commit()
-    conn.close()
-
-
-class _Base(unittest.TestCase):
-    def setUp(self):
-        fd, self.db = tempfile.mkstemp(suffix=".db")
-        os.close(fd)
-        _make_db(self.db)
-        self.old_db = db.DB_PATH
-        self.old_runner_db = runner.DB_PATH
-        self.old_wa_db = wa_tasks.DB_PATH
-        db.DB_PATH = self.db
-        runner.DB_PATH = self.db
-        wa_tasks.DB_PATH = self.db
-
-    def tearDown(self):
-        db.DB_PATH = self.old_db
-        runner.DB_PATH = self.old_runner_db
-        wa_tasks.DB_PATH = self.old_wa_db
-        try:
-            os.unlink(self.db)
-        except OSError:
-            pass
-
-
-class RestHeartbeatTest(_Base):
-    def test_short_rest_completes_not_interrupted(self):
-        stop = threading.Event()
-        result = wa_tasks._rest_with_heartbeat(1, 1, "测试", stop)
-        self.assertFalse(result)
-
-    def test_interrupted_returns_true(self):
-        stop = threading.Event()
-        stop.set()
-        result = wa_tasks._rest_with_heartbeat(1, 60, "测试", stop)
-        self.assertTrue(result)
-
-
-class ThrottleCooldownTest(_Base):
-    def _ok(self, results):
-        done = sum(1 for r in results if r.get("registered") is not None)
-        hits = sum(1 for r in results if r.get("registered"))
-        return ActionResult.success("ok", results=results,
-                                    checked=done, registered=hits)
-
-    def _rows(self, n=50):
-        return [(i, f"86130000000{i:02d}") for i in range(1, n + 1)]
-
-    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
-    @patch("app.wa_tasks._fetch_pending_rows")
-    @patch("app.wa_tasks.CheckWhatsApp")
-    def test_high_error_ratio_triggers_cooldown(self, mock_cls, mock_rows, mock_apply):
-        # 100 个号码 = 2 批，冷却在批 1 之后触发（需 bi < len(batches)）
-        mock_rows.return_value = self._rows(100)
-        # 40 个出错 + 60 个正常 → 错误率 40% ≥ 30%
-        results = [{"number": f"8613{i:07d}", "registered": None, "error": "x"}
-                   for i in range(40)]
-        results += [{"number": f"8614{i:07d}", "registered": False}
-                    for i in range(60)]
-        mock_cls.return_value.run.return_value = self._ok(results)
-
-        with patch("app.wa_tasks.THROTTLE_COOLDOWN_MIN", 0.01), \
-             patch("app.wa_tasks.THROTTLE_COOLDOWN_MAX", 0.02):
-            wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())
-
-        conn = sqlite3.connect(self.db)
-        warnings = conn.execute(
-            "SELECT message FROM task_events WHERE task_id=1 "
-            "AND level='warning' AND message LIKE '%风控%'").fetchall()
-        conn.close()
-        self.assertTrue(any("疑似风控" in w[0] for w in warnings))
-        self.assertTrue(any("额外冷却" in w[0] for w in warnings))
-
-    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
-    @patch("app.wa_tasks._fetch_pending_rows")
-    @patch("app.wa_tasks.CheckWhatsApp")
-    def test_low_error_ratio_no_cooldown(self, mock_cls, mock_rows, mock_apply):
-        mock_rows.return_value = self._rows()
-        results = [{"number": f"8613{i:07d}", "registered": False}
-                   for i in range(50)]  # 0 出错
-        mock_cls.return_value.run.return_value = self._ok(results)
-
-        wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())
-
-        conn = sqlite3.connect(self.db)
-        cools = conn.execute(
-            "SELECT COUNT(*) FROM task_events WHERE task_id=1 "
-            "AND message LIKE '%额外冷却%'").fetchone()
-        conn.close()
-        self.assertEqual(cools[0], 0)
-
-    @patch("app.wa_tasks._apply_results", return_value=(0, 0, 0))
-    @patch("app.wa_tasks._fetch_pending_rows")
-    @patch("app.wa_tasks.CheckWhatsApp")
-    def test_checked_counts_done_not_batch(self, mock_cls, mock_rows, mock_apply):
-        # 2 个号码，1 个出错（registered:null）→ checked 应计 1 而非 2
-        mock_rows.return_value = self._rows(2)
-        results = [
-            {"number": "8613000000001", "registered": False},
-            {"number": "8613000000002", "registered": None, "error": "x"},
-        ]
-        mock_cls.return_value.run.return_value = self._ok(results)
-
-        wa_tasks.run(1, {"accounts": ["xiaohao-1"]}, threading.Event())
-
-        conn = sqlite3.connect(self.db)
-        prog = conn.execute(
-            "SELECT progress_json FROM tasks WHERE id=1").fetchone()
-        conn.close()
-        self.assertEqual(json.loads(prog[0])["checked"], 1)
-
-
-if __name__ == "__main__":
-    unittest.main()
diff --git a/platform/server/tests/test_wa_tasks_guard.py b/platform/server/tests/test_wa_tasks_guard.py
deleted file mode 100644
index 95a5d1d..0000000
--- a/platform/server/tests/test_wa_tasks_guard.py
+++ /dev/null
@@ -1,104 +0,0 @@
-# -*- coding: utf-8 -*-
-"""wa_check 空账号拦截测试。
-
-覆盖：wa_check 任务 accounts 为空时必须拒绝启动（防止静默落到
-default 主号导致封号），而不是继续取数运行。
-"""
-
-import os
-import sqlite3
-import tempfile
-import threading
-import unittest
-
-from app import db, runner, wa_tasks
-
-
-def _make_db(path: str) -> None:
-    conn = sqlite3.connect(path)
-    conn.executescript(
-        """
-        CREATE TABLE tasks (
-            id INTEGER PRIMARY KEY,
-            type TEXT NOT NULL,
-            params_json TEXT NOT NULL,
-            celery_id TEXT,
-            status TEXT NOT NULL DEFAULT 'pending',
-            progress_json TEXT,
-            stop_requested INTEGER NOT NULL DEFAULT 0,
-            error TEXT,
-            created_at TEXT NOT NULL,
-            started_at TEXT,
-            finished_at TEXT,
-            flow_id INTEGER
-        );
-        CREATE TABLE task_events (
-            id INTEGER PRIMARY KEY AUTOINCREMENT,
-            task_id INTEGER NOT NULL,
-            ts TEXT NOT NULL,
-            level TEXT NOT NULL,
-            message TEXT NOT NULL,
-            data_json TEXT
-        );
-        CREATE TABLE contacts (
-            id INTEGER PRIMARY KEY,
-            mobile TEXT,
-            phone TEXT,
-            wa_registered INTEGER,
-            wa_checked_at TEXT
-        );
-        INSERT INTO tasks (id, type, params_json, status, created_at)
-        VALUES (1, 'wa_check', '{"accounts": []}',
-                'pending', '2026-08-05 12:00:00');
-        """
-    )
-    conn.commit()
-    conn.close()
-
-
-class WaaCheckEmptyAccountsGuardTest(unittest.TestCase):
-    def setUp(self):
-        fd, self.db = tempfile.mkstemp(suffix=".db")
-        os.close(fd)
-        _make_db(self.db)
-        self.old_db = db.DB_PATH
-        self.old_runner_db = runner.DB_PATH
-        self.old_wa_db = wa_tasks.DB_PATH
-        db.DB_PATH = self.db
-        runner.DB_PATH = self.db
-        wa_tasks.DB_PATH = self.db
-
-    def tearDown(self):
-        db.DB_PATH = self.old_db
-        runner.DB_PATH = self.old_runner_db
-        wa_tasks.DB_PATH = self.old_wa_db
-        try:
-            os.unlink(self.db)
-        except OSError:
-            pass
-
-    def test_empty_accounts_refuses_to_run(self):
-        # 若守卫失效，会走到 _fetch_pending_rows → 抛异常使测试失败
-        def _boom():
-            raise AssertionError("守卫失效：空账号仍然尝试取数运行")
-        wa_tasks._fetch_pending_rows = _boom
-
-        stop = threading.Event()
-        wa_tasks.run(1, {"accounts": []}, stop)
-
-        conn = sqlite3.connect(self.db)
-        row = conn.execute(
-            "SELECT status, error FROM tasks WHERE id=1").fetchone()
-        ev = conn.execute(
-            "SELECT level, message FROM task_events "
-            "WHERE task_id=1 ORDER BY id LIMIT 1").fetchone()
-        conn.close()
-
-        self.assertEqual(row[0], "failed")
-        self.assertIn("拒绝启动", row[1])
-        self.assertEqual(ev[0], "error")
-        self.assertIn("拒绝启动", ev[1])
-
-
-if __name__ == "__main__":
-    unittest.main()
