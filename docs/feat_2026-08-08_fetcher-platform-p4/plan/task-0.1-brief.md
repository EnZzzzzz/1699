# task-0.1-brief — P4-0 Step 0.1：work_items stopped 态 + 批次入队函数 + batch 索引

## 位置

P4 平台切换第 0 阶段第 1 步（fetcher 批次底座）。改动范围：`fetcher/fetcher/db.py`
+ 新增测试 `fetcher/tests/test_batch_enqueue.py`。这是 P4 全部后续步骤的地基。

## 需求（SPEC §3.1 + PLAN Step 0.1）

### 1. work_items `stopped` 终态（无新列，纯注释/语义）

- work_items DDL 注释中 status 终态集合更新为 `pending/claimed/done/failed/stopped`。
- `finish_work_item` 文档注释：终态集合扩为 done/failed/stopped（含注释）。
- claim 天然排除 stopped（`WHERE status='pending'` 已成立，不改 claim 逻辑）。

### 2. batch 索引（幂等）

- `idx_work_items_batch(batch_id, status)` —— 放 SCHEMA 里（`CREATE INDEX IF NOT EXISTS`），
  紧随现有 `idx_work_items_claim` 之后。SCHEMA 每次执行 executescript 都会跑，幂等补建。

### 3. `enqueue_contact_batch(queue, site, domain_suffix, batch_id, limit)`（新增）

- 语义与 `topup_contact_work_items` 同事务对齐（BEGIN IMMEDIATE 单事务：
  SELECT pending shops → INSERT work_items 带 batch_id → shops 置 in_progress）。
- 唯一差异：INSERT 带 batch_id（传参）；limit>0 时 SELECT 限量；limit<=0 不限。
- 与 daemon 自喂 topup 双喂防护：同事务互斥天然成立（已 in_progress 的店不再被选）。
- payload 与 topup 一致 `{"domain","name","url"}`（contact 批次无链式续喂，不写 batch_limit）。

### 4. `enqueue_feeder_batch(queue, site, batch_id, limit)`（新增）

- INSERT 1 条 discover item + `iter_active_categories()` 种子 category items，全部带 batch_id。
- discover payload：`{"kind":"discover","batch_limit":<limit>}`；
  category payload：`{"kind":"category","keyword":kw,"name":name,"batch_limit":<limit>}`。
- batch_limit 写入 payload（SPEC §3.1：limit 存 payload batch_limit，供 Step 0.2 收束用）。
- 种子跳过逻辑与现有 task._seed_* 对齐：已有同 keyword pending category 跳过；
  已有 pending discover 时只补 category 种子、不重复插 discover。
- 返回 (n_category, n_discover) 或统一计数（测试锚定你的选择，report 里写明）。

## 验收（TDD，先写失败测试）

1. `enqueue_contact_batch`：入队带 batch_id；limit 限量；幂等（重复调用不重复入队）；
   与 topup 不双喂（先 enqueue 后 topup 不重复选已 in_progress 店铺）。
2. `enqueue_feeder_batch`：discover + category 种子都带 batch_id 与 batch_limit；
   幂等（重复调用不重复）；有 pending discover 时不重复插 discover。
3. `stopped` 不被 claim：置 stopped 的 item 不会被 claim_next_eligible 返回。
4. `idx_work_items_batch` 索引存在（PRAGMA index_list 断言）。
5. 现有 work_items/feeder 测试不 regress（跑 fetcher/tests 全量）。

## 环境约束

- 测试全部用临时 sqlite（tempfile + ShopDB(tmp_path)），绝不碰生产库。
- 测试基建仿 test_work_items.py（unittest，临时目录，不 mock 被测对象）。
- 提交前跑 `cd fetcher && python3 -m pytest tests -q` 全量绿。
