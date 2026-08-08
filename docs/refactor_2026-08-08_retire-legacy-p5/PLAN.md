# PLAN — P5 退役旧路径

> 版本：v1 · 2026-08-08 · 待评审
> 配套：SPEC.md（同目录）。删除型 refactor；执行流程按 subagent-driven-development skill；ledger.md 随执行建立。

## Phase 清单

| Phase | 目标 | 预计 Step | 依赖 | 状态 |
|---|---|---|---|---|
| P5-1 | 平台后端删除（wa_tasks + 进程内机械 + cmdparse + 死分支/死字段） | 2 | 无 | pending |
| P5-2 | 前端同步（wa 表单裁剪 + task-ui/api.ts 清理 + 导入 UI 删除） | 1 | P5-1（API 契约先行） | pending |
| P5-3 | DB 死列迁移（celery_id/flow_id/flows 表重建） | 1 | P5-1（测试 fixture 同步在同一分支） | pending |
| P5-4 | 文档修订 + 全量验收 + 终审 | 2 | P5-1~P5-3 | pending |

---

## P5-1 平台后端删除

**准入**：工作区干净（现状已是）。**完成标准**：SPEC §3.1/§3.2/§3.3 后端部分落地；平台 pytest 绿；grep 零残留。

- [x] **Step 1.1** wa_tasks + 进程内机械删除（估 30min，依赖无，状态 done 2026-08-08）
  - 删 `app/wa_tasks.py` + `tests/test_wa_tasks_cooldown.py` + `tests/test_wa_tasks_guard.py`；runner.py 删 `IN_PROCESS_TYPES` 及 start 引用分支、`_start_in_process`、`_run_in_process`、`_RunEntry.stop_event` 与 shutdown stop_event 分支；api/tasks.py 删 preview IN_PROCESS 死分支。
  - 验收：平台 pytest 全绿（repeat Timer 看门测试 test_loop_restart.py 必须保绿）；grep `wa_tasks\|_start_in_process\|_run_in_process\|IN_PROCESS_TYPES` 在 app/ 零命中。
- [x] **Step 1.2** cmdparse + 死字段删除（估 20min，依赖 1.1，状态 done 2026-08-08）
  - 删 `app/cmdparse.py` + `/tasks/parse` 端点；build_command 删 retry_failed 死分支（runner.py:142-143）；TaskParams 删 `interval`/`batch_rest_min`/`batch_rest_max`。
  - 验收：平台 pytest 绿；grep 零命中；uvicorn 重启冒烟（preview 端点批次/yiwugo 两活分支 curl 验证，输出落 plan 目录）。

## P5-2 前端同步

**准入**：P5-1 完成（parse 端点已删、TaskParams 契约冻结）。**完成标准**：SPEC §3.2/§3.3 前端部分落地；`npx tsc -b` 零错误；浏览器走查。

- [x] **Step 2.1** 表单裁剪 + 清理（估 30min，依赖 1.2，状态 done 2026-08-08）
  - api.ts：删 `parseCommand`/`TaskParseResult`、TaskParams 删 3 死字段、`channels` 改 number、`retry_failed`/preview 注释同步；TaskFormDialog：删「从命令导入」折叠区与 handleParse、wa 表单裁 4 字段（保留 limit/accounts）；task-ui.tsx：paramsSummary wa 分支裁 interval/rest 展示、兜底分支删 retry_failed。
  - 验收：`npx tsc -b` 零错误；vite dev 浏览器走查（wa_check 新建/编辑历史任务含旧字段渲染正常、yiwugo 完整表单正常、批次类型表单正常）；走查截图落 plan 目录。

## P5-3 DB 死列迁移

**准入**：P5-1 完成。**完成标准**：幂等表重建迁移落地，生产库副本实测数据无损。

- [x] **Step 3.1** tasks 表重建迁移（估 30min，依赖 1.1，状态 done 2026-08-08）
  - `app/db.py migrate()` 加幂等迁移（PRAGMA 探测 celery_id → RENAME/建新表/INSERT SELECT/DROP tasks_legacy/DROP flows/重建索引，单事务）；6 个测试文件建表 fixture 同步删死列。
  - 验收：TDD（迁移后 schema 正确 + 数据拷贝无损 + 重跑幂等零变化）；**生产库副本实测**（先 cp 备份 `.cache/1688.db` → `.cache/1688.db.bak-p5`，副本上跑 migrate 验证；生产库正式迁移随 uvicorn 重启发生，迁移前后行数/内容对照证据落 plan 目录）。

## P5-4 文档修订 + 验收 + 终审

**准入**：P5-1~P5-3 完成。**完成标准**：SPEC §3.7 文档落地；§7 验收标准逐条取证；终审 MERGE READY。

- [x] **Step 4.1** 文档修订（估 30min，依赖 3.1，状态 done 2026-08-08）
  - flow-architecture.md（头部状态行 + §2 重写 + §6/§7 未落地标注 + §10 重写）；AGENTS.md §1/§5；fetcher README 定位行 + 平台 README 同步（如有任务类型清单）。
  - 验收：文档自检 + review 对照 SPEC §3.7 逐项。
- [ ] **Step 4.2** 全量验收 + 终审（估 30min，依赖 4.1，状态 pending）
  - SPEC §7 逐条取证（grep 零残留清单 / 三侧测试绿 / 迁移实测 / uvicorn 重启冒烟：yiwugo + 批次 + wa_check 历史任务三链路）；scheduler-architecture.md §10 P5 行标完成。
  - 验收：终审 MERGE READY 后呈用户合并；合并后归档本目录到 docs/archive/。
