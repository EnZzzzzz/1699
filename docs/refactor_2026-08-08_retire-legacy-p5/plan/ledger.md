# SDD ledger — plan: docs/refactor_2026-08-08_retire-legacy-p5/PLAN.md

> 主 Agent 协调记录。每 Step 记：派发 commit 范围、review 结论、修复轮次、parked findings。
> 压缩恢复依据：本 ledger + git log，不信记忆。

## 基线

- 分支：refactor/retire-legacy-p5（自 main 开出）
- 基线测试：平台 62 passed（platform/server/.venv 环境）；fetcher 583 passed；前端 npx tsc -b 干净
- 生产库：.cache/1688.db（只读访问）；tasks 4 行，celery_id/flow_id 全 NULL；flows 表存在
- 测试环境：platform/server/.venv/bin/python（fetcher 已装进该 venv）

## 冲突扫描记录（派发前，2026-08-08）

1. `_maybe_schedule_restart` 并非进程内专属：subprocess `_pump` finally（runner.py:814）也调用。
   删除清单不含该方法本身（仅删 `_run_in_process` 的 finally 调用块），保留面不受影响——brief 中明确。
2. SPEC §3.1 盘点遗漏的 wa_tasks 注释引用：db.py:230（「与 wa_tasks 拒绝语义一致」）、
   runner.py:34（冻结说明注释）。属「grep 零残留」验收的自然要求，随 Step 1.1 一并清理（不改语义）。
3. 删除 preview IN_PROCESS 分支后，wa_check preview 行为变化：原返回「进程内执行」文案 →
   build_command ValueError → 422 → 前端 catch 静默 → 「预览不可用」。前端已容错，属可接受降级；
   P5-2 同步更新 TaskFormDialog:817 注释。
4. api.ts:88-92 注释（wa_check 节奏字段说明）需随前端裁剪同步更新。
5. test_task_waiting_status.py 的 fixture 是 dict 形式（"celery_id": None），非建表 SQL，删法不同。

## Step 记录

### Step 1.1（wa_tasks + 进程内机械删除）— complete

- BASE 46ee562 → HEAD 18e0cb8 `refactor(p5): 删除 wa_tasks 进程内执行器与 runner 进程内机械`
- review：通过（spec ✅，无 Critical/Important）。Minor：三处纯注释清理略超 brief 清单（build_command/shutdown docstring、TaskParams 注释），零语义风险，终审分诊；db.py 措辞与 brief 略异，语义一致。
- 修复轮：0
- 主 Agent 复核：app/ 源码 grep 零残留（仅陈旧 .pyc）；tests/ 56 passed（wa_tasks 用例净减，62→56）；pyc 未被 git 跟踪。
- minor (deferred)：三处「进程内」注释清理超清单（可接受，终审确认）；陈旧 test_wa_tasks *.pyc 已手工清理。

