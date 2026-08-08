# SDD ledger — plan: docs/feat_2026-08-08_fetcher-platform-p4/PLAN.md

> 执行模式说明：本 session 无 subagent 派发工具（未安装 subagent 扩展），
> 按 subagent-driven-development skill 纪律降级执行（主 Agent 兼任
> implementer + reviewer，保留 TDD/双重自检/ledger/scoped commit/终审）。

## 前置裁定（SPEC §3.0）

- **ledger-1**：用户未提交 wa pairing 改动 → 已提交（commit f6a497e，
  main，14 文件 +856/-141）；工作区仅剩 P4 任务文档。P4 分支从 f6a497e 开出
  （feat/platform-p4）。

## 批次/边界裁定（派发前冲突扫描）

- 批次 SQL「fetcher 侧 + 平台侧双份」是 SPEC §3.1 有意裁定（平台不 import
  fetcher）；fetcher 侧版本供 daemon/测试锚定，平台侧 Step 2.1 重写。
- work_items `stopped` 态：claim 只认 pending 天然排除；release 只对
  claimed 生效；reset_claimed_work_items 不碰 stopped（sweeper 兜底在 P4-2）。
- batch 索引双侧幂等：fetcher SCHEMA + 平台 migrate 探测补建（生产库表由
  fetcher 建）。
- 冷却键泛化（site→queue 名）属 P4-1 范围，改动点收敛在 eligible_queues/
  _cooldown，单测锚定。

## Step 记录

### P4-0 Step 0.1 — work_items stopped 态 + 批次入队函数 + batch 索引

- **实现**：fetcher/fetcher/db.py（DDL 注释同步 stopped/batch_id 语义 +
  idx_work_items_batch 索引；enqueue_contact_batch 同事务语义 + limit 限量；
  enqueue_feeder_batch discover+category 种子带 batch_id/batch_limit）。
- **测试**：fetcher/tests/test_batch_enqueue.py 9 用例（先失败后转绿：
  入队带 batch_id/限量/幂等/与 topup 双喂互斥双向/stopped 不被 claim/
  batch 索引存在）。全量 532 passed（基线 523 + 9）。
- **review**：自检通过。限量为 0 的处理从魔数 1<<30 改为条件拼 SQL（
  修复后复跑 test_batch_enqueue + test_work_items 24 passed）。
- **commits**：900ff06
- **状态**：complete

### P4-0 Step 0.2 — feeder 批次继承与限量收束

- **实现**：
  - db.py claim_next_eligible 返回 batch_id（透传上层）；
  - 三个 feeder task（1688 shop / 1688 company / mic shop）：
    acquire_item 注入 batch_id；_insert_work_item 支持 batch_id；
    discover 产出/链式续喂/refill 补插继承 batch_id + batch_limit；
    _batch_reached_limit（batch_id 非空 ∧ batch_limit>0 ∧ done ≥ limit
    → 停止续喂/补插）；
  - queue_router.acquire_item 同样注入 batch_id（daemon 认领批次 item）。
- **测试**：fetcher/tests/test_batch_inherit.py 10 用例（TDD 先失败后转绿：
  claim 透传/继承链/discover 产出继承/收束边界（达限停、未达续、limit=0
  不限）/refill 继承+收束/自喂路径 batch_id NULL 零变化）。全量 542 passed。
- **review**：自检通过（测试修正：item dict 模拟 acquire 注入 batch_id；
  当前 item 不入库——真实链路已 claim）。
- **commits**：待提交
- **状态**：complete
