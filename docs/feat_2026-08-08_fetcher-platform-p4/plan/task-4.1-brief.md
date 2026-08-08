# task-4.1-brief — P4-4 Step 4.1：全链路验收冒烟

## 目标

SPEC §7 全 7 条逐条取证。前 6 个 Phase 的单测已覆盖大部分，本 Step 做
**真实链路冒烟**补运行时证据（不碰生产库）：

1. **全链路**：临时库灌 shops → 平台批次入队（enqueue_contact_batch，
   batch_id=任务）→ 起 daemon（--db 临时库）认领执行 → work_items 终态
   → sweeper 派生 tasks.done → SSE 合成事件可读。
2. **跨站填充可见**：daemon 跑批时 consumer_status 的 current_queue 切换
   （看板数据来源已验证，静态验证心跳字段）。
3. **wa_check 全链路**：已在 P4-1 Step 1.3 冒烟（写回 contacts 验证），
   本步不重复。
4. **start/stop 纳管**：P4-2 Step 2.3 已验证。
5. **uvicorn 重启不丢批次**：Step 2.1 单测覆盖（孤儿清理跳过 + sweeper 重建）。
6. **测试/tsc 绿**：fetcher 583 + 平台 62 + tsc 零错误。
7. **daemon.log 无 ERROR**：真实 daemon 冒烟日志检查。

## 冒烟步骤（临时库 /tmp/p4_e2e.db，全程隔离）

1. 建临时库（shops 灌 3 条 pending + 完整 schema）。
2. 平台入队：用 venv python 直接调 app.db.enqueue_contact_batch（batch_id=101）
   ——不经 HTTP（uvicorn 连生产库，不污染）。
3. 起 daemon：`python -m fetcher daemon --db /tmp/p4_e2e.db --workers 1
   --queues crawl_1688_contact --sample-min 0.5 --sample-max 1 --rest-every 0
   --limit 1 -n 1`（直连滑块墙会 failed，取结构证据）。
4. 观察：work_items 终态、consumer_status 心跳、tasks 派生（模拟 tasks 行
   存在时 sweeper 跑）。
5. 检查 daemon.log 无 ERROR（滑块噪声除外）。
6. 证据落 plan/smoke-step4.1/。

## 环境约束

- 临时库全程隔离；daemon --workers 1（席位纪律）。
- 滑块墙命中是环境噪声，取结构证据不纠缠。
