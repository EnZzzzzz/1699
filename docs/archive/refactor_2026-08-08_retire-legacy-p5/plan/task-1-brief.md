# task-1-brief — Step 1.1 wa_tasks + 进程内机械删除

> 本文件是你（implementer）需求的唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699
> 模型：deepseek-v4-flash。TDD 纪律：先写失败测试/先删后跑，亲眼看结果，再收尾。

## 项目位置

这是「1688 采集平台调度器改造 P5 退役旧路径」的第一个 Step（平台后端删除，P5-1 的一半）。
P5 是删除型 refactor：wa_check 已由 fetcher 的 WaCheckTask（daemon LocalExecutor）接管，
`platform/server/app/wa_tasks.py` 进程内执行器及其 runner 机械是死代码，本次删除。

## 删除清单（照单执行，不扩大不缩小）

1. 删除文件：
   - `platform/server/app/wa_tasks.py`（整个文件）
   - `platform/server/tests/test_wa_tasks_cooldown.py`（整个文件）
   - `platform/server/tests/test_wa_tasks_guard.py`（整个文件）
2. `platform/server/app/runner.py`：
   - 删 `IN_PROCESS_TYPES: set[str] = set()`（约 line 35）及其上方冻结说明注释
   - `start()` 里删 `if task_type in IN_PROCESS_TYPES: return self._start_in_process(...)` 分支（约 481-482）
   - 删 `_start_in_process` 方法（约 509-525）
   - 删 `_run_in_process` 方法（约 527-563，含 finally 里的 `_maybe_schedule_restart` 调用块）
   - `_RunEntry` 删 `stop_event` 字段（__init__ 签名与属性，约 343-347）
   - `shutdown()` 删 stop_event 相关分支（约 444-445、457-459 的 `entry.stop_event` 判断与注释）
   - `stop()` 删 `if entry.stop_event is not None: entry.stop_event.set(); return True` 分支
     （约 592-593），删除后 stop() 对 entry 统一走 proc.terminate 路径；注意 stop() 里
     `entry.stop_requested = True` 保留、`cancel_timer` 逻辑保留
3. `platform/server/app/api/tasks.py`：
   - line 12 的 import 里删 `IN_PROCESS_TYPES`
   - preview 端点删 `if body.type in IN_PROCESS_TYPES:` 分支（约 203-204）
4. 注释残留清理（「grep 零残留」验收要求，只改注释不改语义）：
   - `platform/server/app/db.py` 约 line 230 `enqueue_wa_batch` docstring 里的
     「与 wa_tasks 拒绝语义一致」改为「空账号拒绝（防空跑 default 主号）」

## 保留面（一行都不能动）

- runner 的 repeat Timer 全套：`_schedule_restart`/`_auto_restart`/`cancel_timer`/
  `has_pending_timer`/`_timers` 字典/`_maybe_schedule_restart` 方法本身——**`_maybe_schedule_restart`
  在 subprocess `_pump` finally（约 line 814，yiwugo 保活路径）也在调用，方法必须保留**。
- subprocess 机械：`build_command`/`_pump`/`_finalize`/`classify_line`/`_extract_worker`/`_update_progress`。
- `start()`/`stop()` 的批次分支（enqueue_batch_for_task / stop_batch_task）、sweeper 全套。
- 循环重启看门测试 `platform/server/tests/test_loop_restart.py` 必须保持绿。

## 环境与约束

- pytest 用 `platform/server/.venv/bin/python -m pytest`（该 venv 装有 fetcher；系统 python 没有）。
- 只跑聚焦测试；commit 前跑 `platform/server` 下全量 `tests/`。
- 禁止碰：fetcher/（零改动）、scraper/、util/、docs/（文档归 Step 4.1）。
- 改完确认 `app/` 下 `grep -rn "wa_tasks\|_start_in_process\|_run_in_process\|IN_PROCESS_TYPES"` 零命中
  （tests/ 里 wa_tasks 两个测试文件已删，应无残留；`stop_event` 允许在 shutdown/stop 的
  proc 终止路径外不再出现——注意 runner 里 `_sweeper_stop` 等 Event 与 stop_event 不同名，勿误删）。
- DB 约束：不要写生产库 `.cache/1688.db`（只读访问）。本 Step 不涉及 DB 迁移。

## 测试

- 本 Step 删除型：无新增功能测试。验证方式是「删除后全量绿」。
- TDD 适配：先做删除，跑全量测试确认绿，再自查 grep。删除 wa_tasks 后平台测试应净减
  wa_tasks 相关用例（test_wa_tasks_cooldown/guard 两个文件消失）。

## commit

- scoped add：`git add platform/server/app/wa_tasks.py platform/server/tests/test_wa_tasks_cooldown.py platform/server/tests/test_wa_tasks_guard.py platform/server/app/runner.py platform/server/app/api/tasks.py platform/server/app/db.py`（用 git add 具体路径；删除的文件用 `git add -A <path>` 或 `git rm`）
- commit message：`refactor(p5): 删除 wa_tasks 进程内执行器与 runner 进程内机械`
- 只 commit 本 Step 涉及文件，不夹带。

## 验收标准

- [ ] 平台 pytest 全绿（含 test_loop_restart.py 保绿）
- [ ] `app/` 下 grep wa_tasks/_start_in_process/_run_in_process/IN_PROCESS_TYPES 零命中
- [ ] fetcher 测试零改动（不必重跑，583 passed 基线即可）
