# task-4-brief — Step 3.1 tasks 表重建迁移（方案 B 交换式）

> 本文件是你（implementer）需求的唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699
> 模型：deepseek-v4-flash。前置：Step 1.1/1.2/2.1 已完成。

## 项目位置

「1688 采集平台调度器改造 P5」的 DB 死列迁移 Step：tasks 表删除 `celery_id`/`flow_id` 死列、
删除 `flows` 表。**表重建方案已经用户裁决为方案 B（交换式）**，不是 SPEC §3.4 字面的
RENAME-first（原因见 plan/ledger.md Step 3.1 决策点记录：RENAME-first 会让 task_events/
proxy_channels 的外键悬空指向被删表）。

## 迁移实现（platform/server/app/db.py `migrate()` 内新增）

在现有 migrate() 末尾（work_items 索引之后、conn.commit() 之前）新增幂等表重建段：

```
# P5：tasks 表重建——删除 celery_id/flow_id 死列与 flows 表（方案 B 交换式）
cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
if "celery_id" in cols:          # 旧 schema 才重建；已迁移库零变化（幂等守卫）
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""
            CREATE TABLE tasks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                params_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                progress_json TEXT,
                stop_requested INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )""")
        conn.execute("""
            INSERT INTO tasks_new (id, type, params_json, status, progress_json,
                                   stop_requested, error, created_at, started_at, finished_at)
            SELECT id, type, params_json, status, progress_json,
                   stop_requested, error, created_at, started_at, finished_at
            FROM tasks""")
        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
        conn.execute("DROP TABLE IF EXISTS flows")
        conn.execute("CREATE INDEX idx_tasks_status ON tasks(status)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")   # 失败留原表（tasks 未动）
        raise
```

要点：
- **探测守卫**：`PRAGMA table_info(tasks)` 里含 `celery_id` 才执行重建——已迁移的库（含测试临时库）
  重跑 migrate() 零变化（幂等）。
- **单事务**：`BEGIN IMMEDIATE` 起、`COMMIT`/`ROLLBACK` 收；中途任何异常 ROLLBACK 后 re-raise，
  tasks 原表保留。
- 注意 db.py 的 migrate() 用的是 `conn = sqlite3.connect(DB_PATH, timeout=30)`（默认事务模式），
  BEGIN IMMEDIATE/COMMIT/ROLLBACK 手写即可；确认现有 migrate() 末尾的 `conn.commit()` 不会与
  本段的手写 COMMIT 冲突（本段 COMMIT 后，外部 conn.commit() 是空提交，无害）。
- 外键保活：方案 B 下 task_events.task_id / proxy_channels.used_by_task 的 `REFERENCES tasks(id)`
  始终指向表名 "tasks"，RENAME 不重写子表定义——迁移后这些外键依然有效（无需动子表）。
- `flows` 表：`DROP TABLE IF EXISTS flows`（存在才删）。

## 测试（TDD，先写失败测试再实现）

新增 `platform/server/tests/test_tasks_table_rebuild.py`（unittest 风格，参照
test_batch_tasks.py 的临时库 + `patch.object(db_module, "DB_PATH", ...)` 模式）：

1. **RED→GREEN**：建临时库含旧 schema（tasks 带 celery_id/flow_id、flows 表、task_events/
   proxy_channels 子表、若干行数据）→ patch DB_PATH → 跑 migrate() → 断言：
   - tasks 的 `PRAGMA table_info` 不含 celery_id/flow_id
   - `flows` 表不存在
   - 数据无损：行数一致 + 抽查内容（id/type/params_json/status/created_at 等）
   - `idx_tasks_status` 索引存在
   - 迁移后 `INSERT INTO task_events (task_id, ...)` 成功（外键路径保活，证明方案 B 无悬空外键）
2. **幂等**：对已迁移库再跑一次 migrate() → 断言零变化（仍无 celery_id/flow_id/flows、数据不变）
3. **已迁移库 no-op**：临时库直接建新 schema（无死列）→ 跑 migrate() → schema/数据不变
4. （可选）失败回滚：mock conn.execute 在 DROP 处抛异常 → 断言 ROLLBACK 后 tasks 原表仍在
   （含 celery_id 与数据）——若实现复杂可跳过并在 report 说明

同步清理 4 个测试文件 fixture 的死列（Step 1.1 已删 2 个 wa_tasks 测试文件，剩 4 个）：
- `tests/test_batch_tasks.py`：删 `celery_id TEXT,`（约 line 30）与 `flow_id INTEGER`（约 line 38）
- `tests/test_dispatcher_api.py`：删 `celery_id TEXT,`（约 line 30）与 `flow_id INTEGER`（约 line 34）
- `tests/test_loop_restart.py`：删 `celery_id TEXT,`（约 line 30）与 `flow_id INTEGER`（约 line 38）
- `tests/test_task_waiting_status.py`：删 dict 行 `"celery_id": None,`（约 28）与 `"flow_id": None,`（约 29）
（这些 fixture 只是建表/造数语句，测试本身不引用死列；删后全量测试必须仍绿——
test_loop_restart.py 是 repeat Timer 看门测试，必须保绿）

## 生产库副本实测（不碰生产库本体）

1. `cp /Volumes/DataDrive/proj/public/1699/.cache/1688.db /Volumes/DataDrive/proj/public/1699/.cache/1688.db.bak-p5`
2. 用 .venv python 跑迁移脚本（放 /tmp）：`import app.db; app.db.DB_PATH = "<副本路径>"; app.db.migrate()`
   （工作目录 platform/server，PYTHONPATH 保证 import app 可用）
3. 对副本验证（sqlite3 -readonly 或 python）：
   - 迁移前快照：tasks 行数=4、celery_id/flow_id 全 NULL、flows 表存在、idx_tasks_status 存在
   - 迁移后：无 celery_id/flow_id/flows、tasks 行数=4、内容与迁移前一致（逐行对比关键列）、
     idx_tasks_status 在、task_events 外键仍指向 tasks（`sqlite_master` 里 `REFERENCES tasks` 完好）
4. 对照证据（迁移前后 schema/行数/内容）落 plan 目录 `smoke-step3.1/`（如 before.txt/after.txt）
5. 生产库正式迁移不在此 Step 发生——它随 uvicorn 重启（Step 4.2 冒烟）执行

## 环境与约束

- pytest：`platform/server/.venv/bin/python -m pytest`；只跑聚焦测试，commit 前全量。
- 禁止碰：fetcher/、scraper/、util/、docs/、platform/web/。
- 生产库 `.cache/1688.db` 只读访问（sqlite3 -readonly 或 app.db 只读语义）；写操作只发生在
  副本上。

## commit

- 单 commit（DB 迁移单独成 commit，SPEC §8 回滚要求）：
  `git add platform/server/app/db.py platform/server/tests/test_tasks_table_rebuild.py platform/server/tests/test_batch_tasks.py platform/server/tests/test_dispatcher_api.py platform/server/tests/test_loop_restart.py platform/server/tests/test_task_waiting_status.py`
- message：`refactor(p5): tasks 表重建迁移——删 celery_id/flow_id 死列与 flows 表（方案 B 交换式）`
- 生产库副本 `.cache/1688.db.bak-p5` 是备份文件，**不要 commit**（确认 .gitignore 已覆盖 .cache/；
  若不覆盖，绝不 git add 它）。

## 验收标准

- [ ] TDD：新测试 RED→GREEN 证据（report 含失败输出与通过输出）
- [ ] 平台 pytest 全绿（test_loop_restart.py 保绿）
- [ ] 生产库副本实测：迁移后 schema 正确、4 行数据无损、重跑幂等零变化、外键指向 tasks 完好
- [ ] 副本迁移对照证据落 plan/smoke-step3.1/
- [ ] 生产库本体未被写（git 无 .cache 变更 + 迁移只在副本执行）
