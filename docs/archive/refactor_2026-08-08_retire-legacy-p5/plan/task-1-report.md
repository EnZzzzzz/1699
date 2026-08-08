# task-1-report — Step 1.1 wa_tasks + 进程内机械删除

- 状态：DONE
- commit：`18e0cb8` refactor(p5): 删除 wa_tasks 进程内执行器与 runner 进程内机械
- 分支：refactor/retire-legacy-p5

## 实现了什么

严格按 brief 删除清单执行，不多不少：

1. **删除文件 3 个**（git rm）：
   - `platform/server/app/wa_tasks.py`（445 行，进程内执行器）
   - `platform/server/tests/test_wa_tasks_cooldown.py`（168 行）
   - `platform/server/tests/test_wa_tasks_guard.py`（104 行）
2. **`platform/server/app/runner.py`**：
   - 删 `IN_PROCESS_TYPES: set[str] = set()` 及其上方 P4 冻结说明注释；
   - `start()` 删 `if task_type in IN_PROCESS_TYPES: return self._start_in_process(...)` 分支；
   - 删 `_start_in_process` 与 `_run_in_process` 两个方法（含 finally 里的重启调度块）；
   - `_RunEntry` 删 `stop_event` 字段（`__slots__`、`__init__` 签名与属性）；
   - `shutdown()` 删 stop_event 分支与「等进程内任务线程收尾」循环；
   - `stop()` 删 `if entry.stop_event is not None: ...` 分支，统一走 proc.terminate；
   - `stop_requested = True`、`cancel_timer` 逻辑保留。
3. **`platform/server/app/api/tasks.py`**：
   - import 删 `IN_PROCESS_TYPES`；
   - preview 端点删 `if body.type in IN_PROCESS_TYPES:` 分支。
4. **注释残留清理**（只改注释不改语义）：
   - `db.py` enqueue_wa_batch docstring：「与 wa_tasks 拒绝语义一致」→「防空跑 default 主号」；
   - 同类残留（同属「进程内」死机械引用，一并清理）：
     - `runner.py` build_command docstring 删「wa_check 等进程内类型不走这里」；
     - `runner.py` shutdown docstring「终止仍在跑的子进程 / 通知进程内任务停止」→「终止仍在跑的子进程」；
     - `api/tasks.py` TaskParams 注释「wa_check（进程内 WhatsApp 查号）专用」→「wa_check 专用」。

**保留面逐项核对**：repeat Timer 全套（`_schedule_restart`/`_auto_restart`/`cancel_timer`/
`has_pending_timer`/`_timers`/`_maybe_schedule_restart`，含 subprocess `_pump` finally 调用点）、
subprocess 机械（`build_command`/`_pump`/`_finalize`/`classify_line`/`_extract_worker`/`_update_progress`）、
批次分支（`enqueue_batch_for_task`/`stop_batch_task`）、sweeper 全套均未动。

## 测试

- 聚焦：`platform/server/.venv/bin/python -m pytest tests/test_loop_restart.py -q` → **5 passed**（循环重启看门保绿）
- 全量：`platform/server/.venv/bin/python -m pytest tests/ -q` → **56 passed, 1 warning in 0.44s**
  （warning 为 testclient httpx 弃用提示，与本次改动无关）
- wa_tasks 相关用例随两个测试文件删除而净减（168+104 行测试代码移除）。
- fetcher 测试零改动（未触碰 fetcher/）。

## 改动文件

```
 platform/server/app/api/tasks.py                |   8 +-
 platform/server/app/db.py                       |   2 +-
 platform/server/app/runner.py                   |  86 +----
 platform/server/app/wa_tasks.py                 | 445 ------------------------
 platform/server/tests/test_wa_tasks_cooldown.py | 168 ---------
 platform/server/tests/test_wa_tasks_guard.py    | 104 ------
 6 files changed, 9 insertions(+), 804 deletions(-)
```

## 自查结果

- `grep -rn "wa_tasks\|_start_in_process\|_run_in_process\|IN_PROCESS_TYPES\|stop_event" platform/server/app --include="*.py"` → 零命中（仅 __pycache__ 旧 .pyc 二进制残留，已删除 wa_tasks 的 pyc，其余 import 时自动重建）
- tests/ 下同款 grep → 零命中；两个 wa_tasks 测试文件确认不存在
- fetcher/、scraper/、util/ git status 无改动；docs/ 未提交（文档归 Step 4.1）
- 未写生产库 `.cache/1688.db`；无 DB 迁移

## 疑虑

- 无阻塞性疑虑。说明两点：
  1. 超出 brief 第 4 条清单的两处 runner/api 注释清理（build_command、shutdown docstring、
     TaskParams 注释）属于同类别「进程内死机械」残留引用，纯注释零语义风险，若评审认为越界可一键回退；
  2. 首次 `git add` 因已用 `git rm` 暂存删除而报 pathspec 不匹配，改用分路径 add 后正常，无夹带。
