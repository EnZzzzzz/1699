# Step 1.2+1.3 报告 — work_items 存储层

## 实现了什么

按 `task-1.2-brief.md` 逐字实现，全部落在 `fetcher/fetcher/db.py`（追加）+ 新增 `fetcher/tests/test_work_items.py`，未碰其他文件：

1. **DDL**：`SCHEMA` 常量末尾追加 `work_items` 表 + `idx_work_items_claim` 索引，与 brief 所给 SQL 逐字一致（列、默认值、索引；索引直接写进 SCHEMA 段，与 `idx_shops_run`/`idx_cookies_identity` 等既有风格一致）。SCHEMA 纯追加，未改任何既有表定义。
2. **`topup_contact_work_items(queue, site, domain_suffix, limit) -> int`**：`BEGIN IMMEDIATE` 单事务内 SELECT shops 中 `status='pending'` 且 `substr(domain, -N, N)=suffix` 的最老 N 行（`ORDER BY first_seen_at, id`，与 `claim_pending_shops` 同口径）→ 逐行 INSERT work_items（`payload_json` 含 domain/name/url 三键，`json.dumps(ensure_ascii=False)`，created_at 用模块内 `_now`）+ UPDATE 该 shop 为 `in_progress` → 返回补货数。异常 rollback。
3. **`claim_work_item(queue, consumer_id) -> dict | None`**：`BEGIN IMMEDIATE` 单事务取该队列最老 pending 项（`ORDER BY id LIMIT 1`）→ UPDATE 标 `claimed` + `claimed_by` + `claimed_at` → 返回 `{"id", "domain", "name", "url"}`（后三键解析自 payload_json）；无货 commit 后返回 None。异常 rollback。
4. **`finish_work_item(item_id, status, result=None) -> None`**：UPDATE status + finished_at + result_json（result 为 None 时存 NULL，否则 `json.dumps(ensure_ascii=False)`）+ commit。
5. **`reset_claimed_work_items() -> int`**：全部 `claimed` → `pending`，清空 `claimed_by`/`claimed_at`，返回 rowcount。

另加 `import json`（模块顶部，字母序插入既有 import 组）。

## 测了什么、测试结果

`fetcher/tests/test_work_items.py`，临时 sqlite（`tempfile.TemporaryDirectory` + `ShopDB(path)`），仿 `test_contact_task.py` 基建。5 个用例：

1. `test_topup_marks_shops_and_no_duplicates` — 含 DDL 前置断言（`PRAGMA table_info` 列集合 + `PRAGMA index_list` 索引存在）；top-up 后 shops 标 in_progress、work_items 行字段/默认值/payload 三键正确、排序口径最老优先、suffix 不匹配的 madeinchina 店铺不入队；重复 top-up 只补剩余 pending、无重复行
2. `test_claim_no_double_claim` — 两个消费者顺序认领不撞单、返回 dict 键值正确、库内 claimed 字段落库、领空返回 None
3. `test_finish_work_item` — done/failed 终态 + finished_at 非空；result 落 JSON、None 落 NULL
4. `test_reset_claimed_work_items` — claimed → pending、清空认领信息、未认领行不受影响、无 claimed 时返回 0
5. `test_topup_empty_returns_zero` — 空 shops 返回 0 且无行

最终结果：`python -m pytest tests/test_work_items.py -x -q` → **5 passed**；全量 `python -m pytest tests -x -q` → **221 passed, 2 subtests passed**（无回归）。

## TDD 证据（每个方法先红后绿）

### topup_contact_work_items

- RED：`cd fetcher && python -m pytest tests/test_work_items.py -x -q`
  ```
  FAILED tests/test_work_items.py::WorkItemsTest::test_topup_empty_returns_zero
  E  AttributeError: 'ShopDB' object has no attribute 'topup_contact_work_items'
  1 failed in 0.05s
  ```
  失败符合预期：方法尚未实现，属性不存在。
- GREEN：实现 DDL + 方法后同一命令 → `2 passed in 0.04s`（用例 1、5 同时转绿；用例 1 顺带覆盖 DDL 表/索引存在性）

### claim_work_item

- RED：同一命令 →
  ```
  FAILED tests/test_work_items.py::WorkItemsTest::test_claim_no_double_claim
  E  AttributeError: 'ShopDB' object has no attribute 'claim_work_item'
  1 failed in 0.04s
  ```
  符合预期：方法未实现。
- GREEN：实现后 → `3 passed in 0.04s`

### finish_work_item

- RED：同一命令 →
  ```
  FAILED tests/test_work_items.py::WorkItemsTest::test_finish_work_item
  E  AttributeError: 'ShopDB' object has no attribute 'finish_work_item'. Did you mean: 'claim_work_item'?
  1 failed, 1 passed in 0.04s
  ```
  符合预期：方法未实现。
- GREEN：实现后 → `4 passed in 0.05s`

### reset_claimed_work_items

- RED：同一命令 →
  ```
  FAILED tests/test_work_items.py::WorkItemsTest::test_reset_claimed_work_items
  E  AttributeError: 'ShopDB' object has no attribute 'reset_claimed_work_items'
  1 failed, 2 passed in 0.06s
  ```
  符合预期：方法未实现。
- GREEN：实现后 → `5 passed in 0.07s`

## 改动的文件

- `fetcher/fetcher/db.py`（+107 行：import json；SCHEMA 追加 work_items DDL；`# ---------- work_items ----------` 段四个方法，位于 shops 段与 category_progress 段之间）
- `fetcher/tests/test_work_items.py`（新增，5 用例）

commit：`8fcfe91 feat(fetcher): work_items 存储层（daemon 工作队列 DDL + topup/claim/finish/reset 四方法）`（只 add 了这两个文件）

## 自查发现、疑虑

- 完整性：四个方法签名与 brief 表格一致；DDL 与 brief 逐字一致（diff 复核过）；验收四条全满足。
- 纪律：只动 brief 允许的两个文件；`docs/.../task-1.2-brief.md` 是未跟踪的协调产物，未纳入我的 commit。
- 设计选择（已在 brief 授权范围内）：`claim_work_item` 空队列路径走 commit（而非 rollback）释放事务；返回 dict 只含 brief 点名的四键（id + domain/name/url），queue/site/requires 等列消费者用不到，未多给。
- 测试粒度说明：用例 1、5 同属 topup 方法，写在同一个 RED/GREEN 循环里（brief 允许「DDL 与方法在同一个 Step 内迭代」，且 DDL 断言本就要求 topup 前表已存在——`CREATE TABLE IF NOT EXISTS` 在 `ShopDB.__init__` 执行，DDL 先于任何方法生效，所以首个 RED 只是方法缺失，符合 TDD 语义）。
- 并发用例按 brief 许可采用顺序模拟（同一连接上两次 claim 不撞单）；BEGIN IMMEDIATE 的真并发互斥沿用 `claim_pending_shops` 已验证的既有模式，未另起多线程用例。
- 无疑虑。
