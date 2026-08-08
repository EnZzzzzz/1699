# SPEC — P5 退役旧路径（冻结代码删除 + 文档同步）

> 版本：v1 · 2026-08-08 · 待评审
> 设计基准：docs/scheduler-architecture.md §10（P5 行）；P4 实施记录 docs/archive/feat_2026-08-08_fetcher-platform-p4/
> 前置：P0~P4 已合并 main（平台任务已全量走 work_items 批次 + daemon 调度）。
> 性质：删除型 refactor。存量盘点（每个删除候选的消费方清单）已于 2026-08-08 完成，结论随本文 §3 逐项引用。

## 1. 背景与目标

P4 平台切换时按「冻结不删」留下了旧路径：wa_tasks.py 进程内执行器、runner 进程内机械、cmdparse CLI 解析、若干死分支/死字段/死列；docs/flow-architecture.md 的 Celery/Redis/flows 设计与现状严重脱节。P5 目标（基准文档 §10 P5 行验收）：**旧代码路径删除，文档同步**。

删除原则：只删「零消费方或有明确替代链路」的代码；用户仍在手动使用的路径（fetcher 旧 CLI）不删——见 §3.6 裁定。

## 2. 范围与非目标

### 范围

- 平台后端：wa_tasks.py 及其测试、runner 进程内机械（`_start_in_process`/`_run_in_process`/`IN_PROCESS_TYPES` 分支/`_RunEntry.stop_event`）、preview 死分支、build_command retry_failed 死分支、cmdparse.py + `/tasks/parse` 端点、TaskParams 死字段（`interval`/`batch_rest_min`/`batch_rest_max`）。
- 平台前端：wa_check 表单 4 个后端已不消费的节奏字段裁剪、task-ui.tsx paramsSummary 死分支、api.ts 失配修复（`channels: string` vs 后端 int、`retry_failed`/preview 过时注释）、「从命令导入」UI 删除。
- DB：tasks 表死列 `celery_id`/`flow_id` 与 `flows` 表（幂等表重建迁移）。
- 文档：flow-architecture.md 脱节章节修订、AGENTS.md §1/§5、README、scheduler-architecture.md §10 P5 行标完成。

### 非目标（P5 不做）

- **fetcher 旧 CLI 子命令删除**（`1688 contact` 等）——用户手动爬虫在用（§3.6 裁定保留）。
- contact 双轨并轨（旧 CLI contact 的 `claim_pending_shops`/`reset_failed`/`--retry-failed` 是活路径，非死代码，不动）。
- yiwugo_search 迁移（subprocess 机械为 yiwugo 保留：`build_command`/`_pump`/`_finalize`/`classify_line`/`_extract_worker`/repeat Timer 全套——批次循环也在用 Timer，**不可删**）。
- task_templates 生产数据清理（3 条模板含死字段，保持「加载即丢弃」现状，§3.5 裁定）。
- scraper/、util/（项目级只读，永不动）。
- yiwugo contact CLI（平台不可达但 CLI 级存活，无维护成本，保留）。

## 3. 设计要点（逐项删除清单 + 裁定）

### 3.1 wa_tasks.py + runner 进程内机械（安全删除）

- `platform/server/app/wa_tasks.py`（445 行）全删；消费方仅：runner 死分支（`runner.py:481-482` 空集守卫永不可达）、2 个测试文件（test_wa_tasks_cooldown.py、test_wa_tasks_guard.py，随删）、文档引用（随 §3.7 修订）。替代链路 `fetcher/fetcher/wa_task.py`（WaCheckTask，P4 已上线并真实冒烟）完整接管。
- runner.py 连带删除：`IN_PROCESS_TYPES` 空集及 start/preview 引用分支、`_start_in_process`（509-525）、`_run_in_process`（527-563）、`_RunEntry.stop_event` 字段与 shutdown 的 stop_event 分支。保留面：repeat Timer 全套（批次循环核心路径，test_loop_restart.py 覆盖）一行不动。

### 3.2 cmdparse + 「从命令导入」（功能裁剪，呈用户裁定）

- 删 `cmdparse.py` + `POST /api/tasks/parse` 端点 + 前端 `api.ts parseCommand/TaskParseResult` + TaskFormDialog「从命令导入」折叠区（placeholder 还是旧式 CLI 文本，解析产出的参数对批次类型已无效，不认识 madeinchina/wa_check）。**这是用户可见的功能裁剪**：导入功能本身已名存实亡（解析出的 workers/proxy/节奏参数批次模型全不消费），裁定随 P5 删除。无测试覆盖，删除无测试同步成本。
- `/tasks/preview` 保留（批次文案 + yiwugo 真实命令行两个活分支），仅删 IN_PROCESS_TYPES 死分支（api/tasks.py:203-204）与 build_command 的 `1688_contact==retry_failed` 死分支（runner.py:142-143，永不可达）。

### 3.3 TaskParams 死字段 + wa 表单裁剪（前后端同步）

- 后端删 `interval`（wa_tasks 是唯一解释者）、`batch_rest_min`/`batch_rest_max`（新链路无人消费，enqueue_wa_batch 只收 accounts/limit）。
- 前端 wa_check 表单同步裁掉 4 个后端已丢弃的字段：`batch_num`/`sample_min`/`sample_max`/`batch_rest_min`/`batch_rest_max`（现状是「前端在收集、后端静默丢弃」的陷阱，比死代码更该清）。wa 表单保留：limit、accounts。
- task-ui.tsx paramsSummary：wa_check 分支的 `interval/batch_rest_min/max` 展示删除（历史任务展示降级为只显 limit/accounts）；末尾兜底分支的 `retry_failed` 死键删除。
- api.ts 失配修复（现存 bug 级）：`channels?: string` 改 `number`（后端 int；yiwugo 传字符串会被 pydantic 拒）；`retry_failed`、`TaskPreview.cmd` 注释同步现状。

### 3.4 tasks 表死列 + flows 表（表重建迁移）

- `celery_id`/`flow_id` 全代码库零引用（仅 6 个测试文件的建表 fixture 语句与旧文档）；`flows` 表同理。生产库实测 4 条任务两列全 NULL。
- 迁移方案：platform `app/db.py migrate()` 新增幂等表重建（PRAGMA table_info 探测 `celery_id` 存在才执行：`BEGIN IMMEDIATE` → `ALTER TABLE tasks RENAME TO tasks_legacy` → 按新 DDL 建表 → `INSERT SELECT` 拷贝 → DROP tasks_legacy → DROP flows IF EXISTS → 重建索引）。**执行时机**：uvicorn 启动 migrate 阶段、runner/sweeper 启动前（tasks 表写方只有平台，爬虫不写，WAL 冲突面可控）；重建全程单事务，失败回滚留原表。
- 6 个测试文件的建表 fixture 同步删两列（含 flows 引用）。

### 3.5 task_templates 生产数据（裁定：不动）

- 3 条存量模板（店铺采集-循环30分 / 批跑商店采集任务 / 联系人采集）含死字段。现状前端加载时静默丢弃多余字段（fillFromParams 回填、buildParams 不提交），行为正确。**裁定：不动数据、不写清理迁移**——模板是用户数据，死字段无害且用户可能希望保留历史参数记录。前端裁剪字段后加载旧模板的回退行为保持「忽略未知键」。

### 3.6 fetcher 旧 CLI（裁定：保留，README 标注定位）

- `1688/madeinchina 的 shop|contact|company` 旧 CLI 子命令全部保留：本机活爬虫（`python -m fetcher madeinchina`）在用手动路径；contact 双轨（`claim_pending_shops`/`reset_failed`/`--retry-failed`/`--tmd-report`）是**活代码非死代码**，删除属功能裁剪而非清理。
- fetcher README 加一行定位说明：「平台任务走 daemon 批次模型；站点子命令 CLI 仅供手动/调试，与 daemon 同站互斥约定不变」。
- fetcher 侧零代码删除（daemon_task.py 已于 P3 删除，盘点确认无其他死文件）。

### 3.7 文档修订

- **docs/flow-architecture.md**：头部加状态行（「v1 原子层已按 §3 落地；flows 表 DAG 编排未落地且已被 docs/scheduler-architecture.md 的队列+消费者池路线取代，§2/§6/§7 相关段落为历史设计」）；§2 分层图与四条关键决策按现状重写（引擎层=daemon QueueRouter + Engine/CrawlLoop；删除 Celery/Redis/TaskRuntime 寄生表述）；§6（flows 表 + tasks.flow_id 加列）整节标注未落地+已随 P5 删除；§7 API 设计中 flows 相关端点标注未落地；§10 非目标按调度器口径重写（「跨任务 DAG 编排不做」与「跨任务队列调度已由 daemon 实现」区分表述）。
- **AGENTS.md**：§1 平台段落（wa_tasks.py 引用、`app/runner.py` 描述）与 §5 任务系统段落重写为现行三类模型（subprocess=yiwugo 唯一 / 批次=dispatcher 调度 / daemon 纳管），删除 IN_PROCESS_TYPES 叙述。
- **README**（根 + fetcher）：fetcher README 加 §3.6 定位行；平台 README 若有任务类型清单同步。
- **scheduler-architecture.md**：§10 P5 行标完成（终审后）。

## 4. 契约与行为后果

| # | 假设 | 依据 | 验证方式 |
|---|---|---|---|
| C1 | tasks 表重建迁移在生产库（WAL、爬虫不写 tasks）可安全执行 | 盘点：tasks 写方仅平台 sweeper/runner；migrate 在 uvicorn 启动、runner 启动前执行 | 迁移单测（含探测幂等：已迁移库重跑零变化）+ 临时库副本实测 |
| C2 | 删除 `/tasks/parse` 后前端无残留调用 | 消费方清单盘点（api.ts:328-332、TaskFormDialog:403-421 仅此两处） | 删除后 grep 零命中 + tsc -b |
| C3 | wa 表单字段裁剪不破坏历史任务展示/编辑 | 历史 wa_check 任务 params_json 含被裁字段；表单 fillFromParams 对未知键需保持忽略 | 单测/走查：加载历史任务（含旧字段）表单正常渲染、提交不携带 |
| C4 | 无第三方依赖变更 | 纯删除 | package.json/pyproject 零变更检查 |

## 5. 职责分配

| 状态 | 初始化 | 谁写 | 谁读（迁移后） |
|---|---|---|---|
| tasks 表（新 schema） | migrate 表重建（拷贝存量行） | runner/sweeper/API（现状写方不变） | tasks API、前端（celery_id/flow_id 从未被读） |
| work_items / daemon 链路 | 不动 | 不动 | 不动（P5 零触碰 fetcher 运行路径） |
| task_templates.params_json | 不动（§3.5） | 用户经模板 UI | 前端加载时忽略未知键 |

## 6. 冲突扫描与裁定

1. **repeat Timer 全套不可删**（批次循环核心）：runner 删除面严格限定进程内机械；`_run_in_process` finally 的 `_maybe_schedule_restart` 是进程内专属，批次循环走 `_auto_restart` 路径，不受影响。
2. **测试连带**：删 wa_tasks 2 测试文件；6 个测试文件建表 fixture 删死列；test_loop_restart.py（批次循环）必须保持绿——它是「Timer 不可删」的看门测试。
3. **删除 vs 用户可见性**：两处用户可见变化——「从命令导入」功能删除（§3.2）、wa_check 表单字段减少（§3.3）。均已明示，合并说明写明。
4. **平台测试基线**：现状 62 passed，删除后应净减 wa_tasks 相关用例、其余全绿；fetcher 583 passed 应保持零变化（P5 不碰 fetcher 代码）。
5. **与用户工作区**：当前工作区干净（wa pairing 已入库），无交叠风险。
6. **迁移幂等**：表重建必须 PRAGMA 探测守卫——已迁移的库（含各测试临时库）重跑 migrate 零变化；迁移失败不得留半截（单事务）。
7. **preview 端点保留面**：批次文案分支与 yiwugo build_command 分支均活，前端命令预览区不受影响。

## 7. 验收标准

- [ ] 删除清单逐项落地且 grep 零残留（wa_tasks/_start_in_process/_run_in_process/IN_PROCESS_TYPES/cmdparse/parse 端点/interval/batch_rest_min/max/retry_failed 分支/celery_id/flow_id/flows）。
- [ ] 平台 pytest 全绿（净减 wa_tasks 用例后）；fetcher 583 passed 零变化；前端 `npx tsc -b` 零错误。
- [ ] 迁移实测：生产库副本上 migrate 后 tasks 数据无损、无 celery_id/flow_id/flows；重跑幂等。
- [ ] 运行时冒烟：uvicorn 重启（触发迁移）→ 平台启动正常；yiwugo_search 任务创建/预览/启动链路通（subprocess 保留面回归）；批次任务（1688_contact）创建/启动/停止链路通；wa_check 历史任务（含旧字段）编辑/启动通。
- [ ] flow-architecture.md/AGENTS.md/README 修订完成，scheduler §10 P5 行标完成。

## 8. 风险与回滚

- **风险：表重建迁移在生产库失败**——单事务 + 探测守卫 + 失败留原表；迁移前先备份 `.cache/1688.db`（cp 到 .cache/1688.db.bak-p5，冒烟环境先验）。
- **风险：误删活路径**——每个删除候选的消费方清单已盘点背书；终审逐项复核 grep 证据。
- **回滚**：纯删除型 refactor，revert 即全回；DB 迁移单独成 commit，revert 代码后旧列无写入者但表结构已变——因两列本就零读写，revert 代码不回滚表结构也无害。

---

## §7 验收状态（2026-08-09 P5 执行后填写，证据见 plan/ 目录）

- [x] 删除清单逐项落地且 grep 零残留（wa_tasks/_start_in_process/_run_in_process/IN_PROCESS_TYPES/cmdparse/parse 端点/interval/batch_rest_min/max/retry_failed 分支/celery_id/flow_id/flows）——app/ 源码零命中；celery_id/flow_id/flows 仅存于迁移实现与迁移测试自身。
- [x] 平台 pytest 全绿（62 passed，wa_tasks 用例净减 + 迁移测试净增，test_loop_restart.py 看门保绿）；fetcher 583 passed 零变化（P5 零代码改动，仅 fetcher/README.md +3 文档行）；前端 npx tsc -b 零错误。
- [x] 迁移实测：方案 B 交换式（用户裁决），生产库副本迁移后数据无损（4 行逐项一致）、无 celery_id/flow_id/flows、重跑幂等零变化；生产库已于 2026-08-09 早间被提前迁移（终态验证正确无损，随 uvicorn 重启的正式迁移为幂等 no-op）。
- [x] 运行时冒烟：uvicorn 重启加载新代码（parse 端点已删、preview 批次/yiwugo 两活分支 + wa_check 批次文案 200）；yiwugo_search 创建/预览/启动/done 链路通（subprocess 保留面回归）；批次 1688_contact 创建/启动/入队 5 项/停止→stopped 链路通；wa_check 最小任务创建（params 无死字段）/入队/停止链路通；历史任务 73（含旧字段）编辑保存不携带旧字段（前端走查截图见 plan/smoke-step2.1/）。
- [x] flow-architecture.md/AGENTS.md/README 修订完成，scheduler §10 P5 行标完成。
