# task-2.1-brief — P4-2 Step 2.1：批次任务类型 + sweeper

## 位置

P4 第 2 阶段第 1 步（平台后端批次化核心）。改动范围：
`platform/server/app/runner.py`（BATCH_TYPES/sweeper/start 批次化）、
`platform/server/app/api/tasks.py`（TASK_TYPES/TaskParams/preview 冻结）、
`platform/server/app/db.py`（work_items batch 索引探测补建）、
`platform/server/tests/test_batch_tasks.py`（新测试）。

## 需求（SPEC §3.1/§3.2/§3.3 + PLAN Step 2.1）

### 1. 批次任务类型映射（SPEC §3.2）

| 平台类型 | 模型 | 队列 |
|---|---|---|
| 1688_contact（改） | 批次 | crawl_1688_contact |
| madeinchina_contact（新） | 批次 | crawl_mic_contact |
| 1688_shop（改） | 批次 | crawl_1688_shop |
| 1688_company（改） | 批次 | crawl_1688_company |
| madeinchina_shop（新） | 批次 | crawl_mic_shop |
| wa_check（改） | 批次 | wa_check |
| yiwugo_search（不动） | subprocess | TASK_COMMANDS 唯一残留 |

- `TASK_COMMANDS` 只剩 yiwugo_search；`IN_PROCESS_TYPES` 清空
  （wa_tasks.py 冻结不删，P5 删）。
- 新增 `BATCH_TYPES`：类型 → 队列映射（含入队函数区分 contact/feeder/wa）。

### 2. 平台侧批次入队（SPEC §3.1 裁定：平台不 import fetcher，SQL 重写）

平台 app/db 层新增（与 fetcher db.py 同事务语义对齐）：
- `enqueue_contact_batch(queue, site, domain_suffix, batch_id, limit)`：
  BEGIN IMMEDIATE：SELECT pending shops → INSERT work_items 带 batch_id
  → shops 置 in_progress。limit>0 限量。
- `enqueue_feeder_batch(queue, site, batch_id, limit)`：discover + 活跃
  类目 category 种子，带 batch_id + payload.batch_limit。
- `enqueue_wa_batch(batch_id, accounts, limit)`：contacts 未查号码 →
  normalize 去重 → 50/块 → 账号按块轮换 → INSERT（batch_id 带、
  requires=["local"]）。**账号清单来自任务 params（SPEC §3.4），空拒绝**。

### 3. sweeper（runner.py 守护线程）

- `runner.startup()`：孤儿清理**跳过批次类型**；启动 sweeper 线程（5s tick）。
- sweeper tick：
  1. 所有非终态批次任务状态重建：有 pending/claimed 项 → running；
     全部终态且无 pending/claimed → done（有 failed 也算 done，failed 进
     progress）；stop_requested 且 pending 已清空 → stopped。
  2. stopped 兜底：`UPDATE work_items SET status='stopped' WHERE batch_id=?
     AND status='pending'`（防 daemon 重启复活，每 tick 强一致性）。
  3. progress_json 1s 节流：`{total, done, failed, stopped, claimed,
     pending, updated_at}`（GROUP BY status）。
  4. repeat_interval：done 且 repeat>0 且未 stop_requested → 复用
     _auto_restart Timer 机制，到点重新入队同参数批次（改调批次入队
     而非 runner.start）。
- 批次任务无子进程/无进程内线程：`runner.is_running` 对批次类型返回
  False（无 _runs 条目）。

### 4. api/tasks.py

- `TASK_TYPES = set(TASK_COMMANDS) | set(BATCH_TYPES)`。
- `TaskParams`：批次类型只保留 limit、repeat_interval（+ wa_check 的
  accounts/节奏）；workers/channels/headless/use_proxy 等移除或保留但
  批次类型忽略？**裁定（SPEC §3.2）**：TaskParams 保留全部字段（向后兼容
  旧模板读取），批次类型只读 limit/repeat_interval/accounts，其余忽略。
- preview/parse：批次类型返回描述文案 `"批次提交：{queue}，{limit} 条"`，
  cmdparse 冻结。

### 5. start/stop 语义

- `POST /{id}/start`（批次类型）：清 events → 状态置 running → 入队
  批次（含 batch_id=tasks.id）。返回 {ok, queue, item_count}。
- `POST /{id}/stop`（批次类型）：置 stop_requested → 平台侧
  `UPDATE work_items SET status='stopped' WHERE batch_id=? AND
  status='pending'`。claimed 项跑完自然终态。
- 循环模式 Timer 触发时批次类型走批次入队。

## 验收（TDD，先写失败测试）

1. 平台侧 enqueue_contact/feeder/wa_batch：batch_id 全链路、幂等、限量
   （临时 sqlite，仿 fetcher 测试模式——**平台测试不能连生产库**，
   db.py 的 DB_PATH 需可注入）。
2. sweeper：状态派生（running/done/stopped/failed）、progress 聚合、
   stopped 兜底、repeat_interval 重入队（Timer 触发）。
3. start/stop 端点：批次生命周期 create→start（入队）→sweeper 状态流转
   →stop（pending 置 stopped）。
4. TASK_TYPES/TaskParams/preview 适配。
5. **冒烟：重启 uvicorn 批次不丢**（sweeper 重建）。

## 环境约束

- 平台测试用临时 sqlite（DB_PATH 注入——现有 app.db.DB_PATH 是模块常量，
  测试需 patch）。绝不碰生产库 .cache/1688.db。
- 提交前跑 platform/server 测试 + fetcher 全量 + 重启 uvicorn 冒烟。
- 冒烟证据落 plan 目录。
