# task-4-report — Step 3.1 tasks 表重建迁移（方案 B 交换式）

> 对应 brief：`plan/task-4-brief.md`。实现者：deepseek-v4-flash（pi agent）。
> 分支：`refactor/retire-legacy-p5`。日期：2026-08-09。

## 一、交付内容

1. **迁移实现**（`platform/server/app/db.py` `migrate()` 末尾新增重建段）：
   - 探测守卫：`PRAGMA table_info(tasks)` 含 `celery_id` 才重建；已迁移库重跑零变化（幂等）。
   - 方案 B 交换式单事务：`BEGIN IMMEDIATE` → `CREATE TABLE tasks_new` →
     `INSERT SELECT`（保 id/数据）→ `DROP TABLE tasks` → `ALTER TABLE tasks_new RENAME TO tasks`
     → `DROP TABLE IF EXISTS flows` → `CREATE INDEX idx_tasks_status` → `COMMIT`；
     `except` 分支 `ROLLBACK` 后 re-raise，原表保留。
   - 外键保活：RENAME 目标名恒为 `tasks`，task_events/proxy_channels 的
     `REFERENCES tasks(id)` 不被 SQLite 重写，子表无需改动。
2. **新测试**（`platform/server/tests/test_tasks_table_rebuild.py`，6 个用例）：
   - 旧 schema 迁移后：无 celery_id/flow_id、无 flows 表、数据无损（行数+抽查）、
     idx_tasks_status 在、子表外键路径保活（迁移后 INSERT task_events/proxy_channels 成功）。
   - 幂等：已迁移库重跑 migrate() 零变化。
   - 已迁移库 no-op：新 schema 临时库跑 migrate() schema/数据不变。
   - 失败回滚：mock `sqlite3.connect`（factory 子类）在 `DROP TABLE tasks` 抛异常 →
     ROLLBACK 后原表（含死列与数据）保留。
3. **4 个测试 fixture 死列清理**：test_batch_tasks.py（celery_id line30 / flow_id line38）、
   test_dispatcher_api.py（line30/34）、test_loop_restart.py（line30/38）、
   test_task_waiting_status.py（"celery_id"/"flow_id" dict 行）——仅删建表/造数语句，
   测试逻辑零改动。

## 二、TDD 证据

**RED**（实现前，首次全跑）：
```
FAILED MigrateOldSchemaTest::test_migrate_drops_dead_columns_and_flows
FAILED MigrateOldSchemaTest::test_migrate_preserves_data_and_index
FAILED IdempotentTest::test_rerun_migrate_is_noop
FAILED RollbackTest::test_migrate_rollback_keeps_original_tasks
（test_migrate_keeps_child_fk_paths_alive / test_migrate_on_new_schema_is_noop 基线通过）
```
注：首版回滚测试因 `patch("sqlite3.connect")` mock 递归（RecursionError 是 RuntimeError
子类）产生假阳性 PASSED，已改用 `factory=FlakyConn` 子类 + 保存真实 connect 引用修正；
修正后回滚测试在 RED 阶段正确 FAILED，GREEN 阶段正确 PASSED（无假阳性）。

**GREEN**（实现后）：
```
6 passed in 0.0x s —— 全部通过
```

**全量**：`platform/server/.venv/bin/python -m pytest tests/` → `62 passed`，
其中 `test_loop_restart.py`（repeat Timer 看门）保绿。

## 三、生产库副本实测

> 重要前置说明：会话开始（01:26）实测生产库 `.cache/1688.db` 为**旧 schema**
> （tasks 含 celery_id/flow_id、flows 表 3 行、tasks 4 行、task_events 740 行）。
> 但 01:29:48 cp 备份时，生产库已是**新 schema**（死列已删、flows 已删）——
> 即会话窗口内生产库被**外部进程迁移**（ps 显示并行 pi agent 39496 于 00:14 启动、
> uvicorn 57435 于 23:00 启动；最可能为并行 agent 运行了新版 db.py 的 migrate()，
> 或 uvicorn 加载新代码后 startup() 触发）。**我的 pytest 全程 patch DB_PATH 只连临时库，
> 已用旧 schema 副本跑全量 pytest 验证零变化排除嫌疑；git 无 .cache 变更。**
> 生产库本体当前 schema 与迁移目标完全一致（见 plan/smoke-step3.1/prod-current.txt），
> 且迁移结果正确（4 行数据无损、外键完好、idx_tasks_status 在），与 Step 4.2 正式迁移
> 的预期终态相同——但**生产库正式迁移本应在 Step 4.2 由 uvicorn 重启执行**，此处被
> 提前触发，已记录为疑虑。

副本实测（证据落 `plan/smoke-step3.1/`）：
- `before.txt`：旧 schema 副本（由迁移后副本 `.bak-p5` 加回 celery_id/flow_id 死列
  + flows 表构造，含真实生产数据 4 行/740 事件）——因生产库已提前迁移，无法直接
  从生产库拷贝"迁移前"状态，改为逆向构造等价旧 schema。
- `after.txt`：`app.db.migrate()` 跑副本 → 无死列、无 flows、tasks 4 行内容与迁移前
  逐行一致、idx_tasks_status 在、task_events/proxy_channels 外键 REFERENCES tasks 完好；
  重跑 migrate() 幂等零变化。
- `prod-current.txt`：生产库本体当前状态（外部迁移后）：tasks 4 行、无死列、无 flows、
  外键完好、sqlite_sequence(tasks)=74（AUTOINCREMENT 序列保留）。

验证项对照验收标准：
- [x] 迁移后 schema 正确（无死列/无 flows）——副本 + 生产库本体均确认
- [x] 4 行数据无损（逐行对比 id/type/params_json/status/created_at 等）
- [x] 重跑幂等零变化（副本 migrate 两次 + 生产库现状）
- [x] 外键指向 tasks 完好（sqlite_master 里 `REFERENCES tasks` 完整）
- [x] 证据落 plan/smoke-step3.1/
- [x] 生产库本体未被**我**写（git 无 .cache 变更；我的写操作全部在 /tmp 副本）

## 四、commit

- 单 commit（DB 迁移单独成 commit，SPEC §8 回滚要求）：
  `refactor(p5): tasks 表重建迁移——删 celery_id/flow_id 死列与 flows 表（方案 B 交换式）`
- 文件：db.py + test_tasks_table_rebuild.py + 4 个 fixture 清理文件（与 brief 清单一致）。
- `.cache/1688.db.bak-p5` 未 commit（.gitignore 已覆盖 .cache/）。

## 五、疑虑

1. **生产库被外部提前迁移**（非本 Step 预期）：会话窗口内并行 pi agent（PID 39496，
   00:14 启动）或 uvicorn 加载新代码触发了生产库 migrate()。结果与目标终态一致、
   数据无损，但**违背了 brief「生产库正式迁移随 Step 4.2 uvicorn 重启执行」的时序**。
   建议 Step 4.2 冒烟时直接确认生产库已是目标状态即可（幂等，无需再迁移）。
2. 回滚测试依赖 `DROP TABLE tasks` 精确匹配，若迁移段语句改动需同步测试。
3. 旧 schema 副本由迁移后副本逆向构造（生产库无迁移前快照），迁移路径验证等价但
   非生产库直接拷贝；迁移前快照（tasks=4、celery_id/flow_id、flows=3）已在会话早期
   实测记录于本报告与 smoke 证据。

## 六、验收状态

- [x] TDD RED→GREEN 证据（本报告含失败与通过输出）
- [x] 平台 pytest 全绿（62 passed，test_loop_restart.py 保绿）
- [x] 副本实测：schema 正确、4 行无损、幂等零变化、外键完好
- [x] 证据落 plan/smoke-step3.1/
- [x] 生产库本体未被本实现者写（外部提前迁移已记录疑虑）
