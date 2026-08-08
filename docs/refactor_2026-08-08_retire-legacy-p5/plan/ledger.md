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


### Step 1.2（cmdparse + 死字段删除）— complete

- BASE 7b5401c → HEAD c46fc60 `refactor(p5): 删除 cmdparse 从命令导入链路与 TaskParams 死字段`（+ docs commit 27f1f5b）
- implementer 状态 DONE_WITH_CONCERNS，三疑虑均已裁决为非缺陷：
  ① wa_check preview 走批次分支返回 200（wa_check 在 BATCH_TYPES，queue=wa_check）——正确活行为，brief 预期 422 是主 Agent 预期错误；
  ② 队列名 crawl_1688_contact（代码 BATCH_TYPES 权威）；③ retry_failed 注释过期 → 归 Step 2.1。
- review：通过（spec ✅，无 Critical/Important）。Minor：tasks.py:117 retry_failed 注释过期（并入 Step 2.1 清理）；陈旧 .pyc。
- 修复轮：0
- 主 Agent 复核：冒烟四组 curl 证据落 plan（批次/yiwugo 200 + wa_check 批次文案 + 未知类型 422）；全量 56 passed 持平；app/ grep 零残留。
- minor (deferred)：tasks.py:117 retry_failed 注释同步清理（Step 2.1 与 api.ts 注释一起）；陈旧 pyc 已清理。

### Step 2.1（前端同步）— complete

- BASE cc5c163 → HEAD b9ee35d `refactor(p5): 前端同步——wa 表单裁剪 + 删从命令导入 UI + api.ts 类型失配修复`（+ commit B 63e758d 后端注释）
- review：通过（spec ✅，无 Critical/Important）。Minor×2（均前置遗留/范围外，终审分诊）：
  ① channels 非整数边界（isFinite 放行 "1.5"，后端 int 会 422）——非本 Step 回归；
  ② batchLimit 不在 paramsKey 依赖（批次表单改 limit 预览不刷新）——P4 遗留。
- 修复轮：0
- 主 Agent 复核：tsc -b 零错误；走查 4 截图存在（wa 新表单/历史任务 73/yiwugo/批次）；grep 零残留；diff -251 行净删。
- minor (deferred)：① channels 加 Number.isInteger 守卫；② batchLimit 补进 paramsKey 依赖（终审分诊）。

### Step 3.1（DB 死列迁移）— pending

- 生产库核对：tasks 仅 idx_tasks_status 索引；flows 表存在；4 行 celery_id/flow_id 全 NULL。
- 测试 fixture：Step 1.1 已删 2 个 wa_tasks 测试文件，剩 4 个含死列（test_batch_tasks/test_dispatcher_api/test_loop_restart/test_task_waiting_status(dict 形式)）。
- 决策点（2026-08-08 用户裁决）：tasks 表重建顺序——SPEC §3.4 字面为 RENAME-first（tasks→tasks_legacy），
  但 SQLite RENAME 会把 task_events.task_id / proxy_channels.used_by_task 外键改写指向 tasks_legacy，
  DROP 后悬空（代码库从未启用 PRAGMA foreign_keys，休眠地雷）。用户裁决 **方案 B（交换式）**：
  建 tasks_new → INSERT SELECT → DROP tasks → RENAME tasks_new TO tasks → DROP flows → 重建索引。
  删除面/单事务/幂等/失败留原表要求不变；外键始终指向 "tasks" 表名，最终 schema 干净。

### Step 3.1（DB 死列迁移）— complete

- BASE 3f70220 → HEAD 61d6758 `refactor(p5): tasks 表重建迁移——删 celery_id/flow_id 死列与 flows 表（方案 B 交换式）`
- review：通过（spec ✅，无 Critical/Important）。Minor：① BEGIN 失败时 ROLLBACK 掩盖原始错误（影响极小）；
  ② 方案 B 隐含依赖 FK 强制关闭，建议注释记录前提；③ before.txt 与 report 的 flows 行数不一致（1 vs 3）；
  ④ before.txt 为逆向构造非直接快照（已披露）。均终审分诊。
- 修复轮：0
- **重要事件——生产库被提前迁移**（implementer 归因有误，主 Agent 已调查）：
  - 时间线：01:26 生产库旧 schema → db.py 新代码 01:28 落盘 → 01:29:48 cp 时生产库已是新 schema。
  - 排除项：pid 39496 是本 session 的 pi 进程（非并行 agent）；uvicorn 57435 是 23:00 旧代码进程（无法跑新迁移）；
    implementer 的 /tmp 脚本全部显式 DB_PATH 指向副本（已读源码核实）。
  - 结论：唯一能解释的是某个导入新 db.py 且未 patch DB_PATH 的进程在 01:28 后调了 migrate()（生产库本体）。
    归因存疑，但**迁移结果已验证正确无损**（4 行数据与 P5 前快照逐行一致、死列/flows 已删、外键指向 tasks 完好、
    idx_tasks_status 在、sqlite_sequence=74 保留）。生产库正式迁移时序（Step 4.2 uvicorn 重启）实际提前发生。
  - 影响：无功能影响；Step 4.2 冒烟时重启 uvicorn 会跑幂等 migrate（no-op）并加载新代码（当前 57435 仍是
    23:00 旧代码进程，parse 端点 500 即旧代码证据）。
- 主 Agent 复核：全量 62 passed（56+6 新增迁移测试）；celery_id/flow_id 残留仅迁移实现与测试自身。
- minor (deferred)：① BEGIN 失败 ROLLBACK 异常掩盖；② FK 前提注释；③ flows 行数证据不一致；④ before.txt 逆向构造。
