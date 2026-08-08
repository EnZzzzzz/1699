# PLAN — P4 平台切换

> 版本：v1 · 2026-08-08 · 待评审
> 配套：SPEC.md（同目录）。执行流程按 subagent-driven-development skill；ledger.md 随执行建立。

## Phase 清单

| Phase | 目标 | 预计 Step | 依赖 | 状态 |
|---|---|---|---|---|
| P4-0 | fetcher 批次底座：stopped 态 + batch_id 链路 + consumer_status + 租约 | 3 | §3.0 工作区裁定落地 | pending |
| P4-1 | wa_check 迁入：LocalExecutor + WaCheckTask + 队列入注册表 | 3 | P4-0 | pending |
| P4-2 | 平台后端：批次任务类型 + sweeper + SSE 合成 + dispatcher API + 脚本纳管 | 3 | P4-0（P4-1 可并行） | pending |
| P4-3 | 前端：表单分支 + 批次进度 + 调度器看板页 | 2 | P4-2 | pending |
| P4-4 | 端到端验收 + 终审 | 2 | P4-1、P4-3 | pending |

---

## P4-0 fetcher 批次底座

**准入**：SPEC §3.0 工作区裁定已落地（用户提交/stash 其 wa 改动）。**完成标准**：批次相关 DB 语义单测全绿；daemon 跑批时 consumer_status/proxy_channels 有真实写入（冒烟）。

- [x] **Step 0.1** work_items stopped 态 + 批次入队函数 + batch 索引（估 30min，依赖无，状态 done）
  - fetcher db.py：DDL 注释 + `idx_work_items_batch(batch_id, status)` 幂等迁移；`enqueue_contact_batch`（topup 同事务语义 + batch_id + limit）；`enqueue_feeder_batch`（discover + iter_active_categories 种子 + batch_id）；终态集合注释更新。
  - 验收：TDD——入队幂等/限量/与 topup 不双喂（同事务互斥）、stopped 不被 claim。
- [x] **Step 0.2** feeder 批次继承与限量收束（估 30min，依赖 0.1，状态 done）
  - discover 产出、链式续喂、失败补插继承父 batch_id；续喂/补插前 done 计数 ≥ payload.batch_limit 则收束；batch_id NULL 自喂路径逐字不变。
  - 验收：TDD——继承链、收束边界（limit=0 不限）、现状路径零变化（既有测试不 regress）。
- [x] **Step 0.3** consumer_status 心跳 + proxy_channels 租约（估 30min，依赖无，状态 done）
  - consumer_status 建表（幂等迁移）+ daemon 侧写入钩子（claim/finish/release/冷却登记即时 + 10s 心跳线程 + 退出清空）；启动按 tunnel 写 used_by_task=consumer_id、退出清零。
  - 验收：TDD + 冒烟（`--workers 1` 临时库？**注意**：租约写 proxy_channels 是平台表——冒烟用临时库整体拷贝，绝不碰生产库）；日志证据落 plan 目录。

## P4-1 wa_check 迁入

**准入**：P4-0 完成。**完成标准**：`wa_check` 队列在 daemon 注册（守卫条件满足时），LocalExecutor 消费真实小批量查号并写回 contacts。

- [ ] **Step 1.1** LocalExecutor 消费者 + requires="local" 互斥（估 30min，依赖 0.1，状态 pending）
  - Engine 加 `--local-workers`（默认 2）无浏览器消费者线程（resources={"local"}，无通道/BrowserManager 装配）；eligible_queues 键泛化（site 或 queue 名）。
  - 验收：TDD——browser consumer 领不到 local 队列、local consumer 领不到 browser 队列（结构性互斥单测）。
- [ ] **Step 1.2** WaCheckTask + 入队 feeder（估 40min，依赖 1.1，状态 pending）
  - fetcher/wa_task.py：contacts 未查号码 → normalize 去重 → 50/块 → 账号轮换入 payload；fetch=CheckWhatsApp 原子；on_success 写回 wa_registered/wa_checked_at（移植 _apply_results 语义）；节奏/风控冷却经让出型（键=queue）；停止协作改查批次 stopped。
  - 验收：TDD——切块/轮换/写回/歧义跳过/冷却键；node 缺失守卫单测。
- [ ] **Step 1.3** wa_check 真实冒烟（估 30min，依赖 1.2，状态 pending）
  - daemon 注册 wa_check 队列（vendor+node 守卫）；小批量（≤50 号，临时库灌测试 contacts）真实查号 → 写回验证。
  - 验收：contacts.wa_registered 写回正确；证据（DB 前后对照 + 日志）落 plan 目录。**注意账号风控：用专用查号号，量最小化。**

## P4-2 平台后端

**准入**：P4-0 完成（与 P4-1 可并行，wa_check 批次类型部分依赖 P4-1 注册表）。**完成标准**：5+1 批次类型全流程（建/启/停/进度/事件）API 级打通；start.sh/stop.sh 纳管 daemon。

- [ ] **Step 2.1** 批次任务类型 + sweeper（估 40min，依赖 0.2，状态 pending）
  - runner：TASK_COMMANDS 只留 yiwugo_search、IN_PROCESS_TYPES 清空、BATCH_TYPES 映射表；start=批次入队（平台侧 SQL，§3.1 裁定）；sweeper 守护线程（5s tick 状态派生 + 1s 节流 progress + stopped 兜底 + repeat_interval 重入队 + startup 重建）；孤儿清理跳过批次类型。
  - api/tasks.py：TASK_TYPES/TaskParams 适配、preview/parse 冻结文案。
  - 验收：FastAPI TestClient 或 httpx 级测试（批次生命周期：create→start→sweeper 状态流转→stop）；**冒烟：重启 uvicorn 批次不丢**。
- [ ] **Step 2.2** SSE 事件合成 + dispatcher API（估 30min，依赖 2.1，状态 pending）
  - events 端点批次分支（回放 200 + 1s 增量 + status 帧复用）；`GET /api/dispatcher/status` + `GET /api/dispatcher/consumers`（新 router，注册进 main.py）。
  - 验收：端点级测试 + curl 冒烟截图/输出落 plan 目录。
- [ ] **Step 2.3** start.sh/stop.sh 纳管 + 冒烟（估 20min，依赖 无，状态 pending）
  - start_daemon/stop_daemon（pidfile/日志/幂等/SIGTERM 优雅/pkill 兜底特征）；README/AGENTS.md §1 daemon 段落同步。
  - 验收：真起真停——起后 consumer_status 有心跳、停后清空；重复 start 幂等；证据落 plan 目录。

## P4-3 前端

**准入**：P4-2 完成（API 契约冻结）。**完成标准**：三页面改造/新增渲染正确，`npx tsc -b` 零错误，浏览器走查。

- [ ] **Step 3.1** 任务类型表单 + 批次进度（估 40min，依赖 2.1，状态 pending）
  - api.ts TaskType/TaskParams；task-ui.tsx TASK_TYPE_OPTIONS/paramsSummary；TaskFormDialog 三分支（批次采集只留 limit+repeat_interval；wa_check 保留）；Tasks 列表批次进度列（done/total + failed 标红）。
  - 验收：`npx tsc -b` + vite dev 浏览器走查（建批次任务表单渲染、旧模板兼容读取）。
- [ ] **Step 3.2** 调度器看板页（估 40min，依赖 2.2，状态 pending）
  - `/dispatcher` 路由 + navItems 入口；StatCard 行 + 队列深度表 + 消费者表（chip/冷却倒计时/amber 冷却徽标）；useApiData 自适应轮询；PageState 三态；离线灰显。
  - 验收：`npx tsc -b` + 浏览器走查（daemon 在线/离线两态截图落 plan 目录）；DESIGN.md 逐条对照自查（token/徽标/排版/圆角）。

## P4-4 端到端验收 + 终审

**准入**：P4-1、P4-3 完成。**完成标准**：SPEC §7 逐条取证；全分支终审 MERGE READY。

- [ ] **Step 4.1** 全链路验收冒烟（估 40min，依赖 3.2、1.3，状态 pending）
  - SPEC §7 全 7 条逐条取证（contact 批次全链路 + 停止链路 + 看板跨站切换可见 + wa_check 写回 + 脚本纳管 + uvicorn 重启不丢 + 测试/tsc 绿）。
  - 证据（命令 + 输出 + 截图）落 plan 目录 report。
- [ ] **Step 4.2** 全量回归 + 终审（估 30min，依赖 4.1，状态 pending）
  - fetcher 全量测试 + 平台冒烟 + tsc；终审；scheduler-architecture.md §10 P4 行标完成；归档本目录到 docs/archive/（合并后）。
  - 验收：终审 MERGE READY 后呈用户合并。
