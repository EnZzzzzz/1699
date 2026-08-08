# task-2.2-brief — P4-2 Step 2.2：SSE 事件合成 + dispatcher API

## 位置

P4 第 2 阶段第 2 步（平台可观测面）。改动范围：
`platform/server/app/api/tasks.py`（SSE 批次事件合成）、
`platform/server/app/api/dispatcher.py`（新 router：status/consumers）、
`platform/server/app/api/__init__.py`（注册 router）、
`platform/server/tests/test_dispatcher_api.py`（新测试）。

## 需求（SPEC §3.3/§3.5 + PLAN Step 2.2）

### 1. SSE 事件合成（GET /tasks/{id}/events，批次类型分支）

批次任务无 subprocess 输出，事件从 work_items 合成：
- **回放**：最近 200 条 finished 项（`WHERE batch_id=? AND finished_at IS NOT
  NULL ORDER BY finished_at DESC LIMIT 200` 反转），message 合成：
  - done：`✓ {domain 或标识}`（payload 有 domain 用 domain，否则 queue 名+id）
  - failed：`✗ {标识} ... {reason}`（result_json 的 reason）
  - stopped：`⏹ {标识}`
  - level 映射：done→success、failed→error、stopped→warning。
- **增量**：1s 轮询 `WHERE batch_id=? AND finished_at > 游标`（游标用
  finished_at 时间戳+id 组合？**裁定**：用 work_items.id 作游标更简单可靠
  ——finished 项按 id 升序，新事件 = id > last_event_id）。
- **status 帧/心跳/关流**：复用现状 SSE 逻辑（status 从 tasks 表读，
  _loop_wait 派生 waiting，终态关流）。

### 2. dispatcher API（新 router，main.py 注册）

- `GET /api/dispatcher/status`：
  ```
  {
    "daemon_alive": bool,        # consumer_status 有 updated_at 新于
                                 # now-30s 的行
    "queue_depth": {queue: {pending, claimed, done, failed}},
    "today_done": int,           # 今日 done 计数（finished_at 当天）
  }
  ```
  queue_depth 按 work_items GROUP BY queue, status；只列有行/注册过的队列。
- `GET /api/dispatcher/consumers`：全量 consumer_status 行（解析
  cooldowns_json），附 `offline: bool`（updated_at 超 30s）。
- 读方只 SELECT（app.db.connect），不写。

### 3. 注册

`api/__init__.py` 加 dispatcher.router。

## 验收（TDD，先写失败测试）

1. **SSE 合成**：finished 项合成 message/level 正确（done/failed/stopped
   + domain/reason）；增量游标（id > last）只取新项；无 finished 项返回空。
2. **dispatcher/status**：daemon_alive 判定（心跳新/旧）；queue_depth
   聚合正确；today_done 计数。
3. **dispatcher/consumers**：行返回 + offline 标记 + cooldowns_json 解析。
4. 注册进 main（路由存在）。
5. 现有测试不 regress。

## 环境约束

- 临时 sqlite（patch DB_PATH 三处：app.db/app.runner/app.api.tasks/
  app.api.dispatcher——dispatcher 模块也要 patch）。
- 冒烟：curl 输出/截图落 plan 目录。
