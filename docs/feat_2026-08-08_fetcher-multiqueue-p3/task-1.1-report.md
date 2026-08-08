# Task 1.1 Report — work_items 扩展（attempts / release_work_item / claim_next_eligible）

> 分支：`feat/multiqueue-p3` ｜ 状态：DONE ｜ TDD 全流程完成，全量 318 passed（基线 309 + 新增 9）

## 实现摘要

在 `fetcher/fetcher/db.py` 的 work_items 存储层新增三个能力（现有方法一律未动）：

1. **attempts 列（幂等迁移）**：`_migrate()` 追加 work_items 列探测（`PRAGMA table_info(work_items)` 模式，与 shops/ip_events 既有探测一致），缺列时 `ALTER TABLE work_items ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0`。存量行默认 0；重开库幂等。
2. **`release_work_item(item_id, max_attempts=3) -> str`**（SPEC §3.4 挂起/重试语义）：
   - 单事务 `BEGIN IMMEDIATE`：`attempts = attempts + 1`，清空 `claimed_by/claimed_at`；
   - `attempts >= max_attempts` → 置 `failed`（写 `finished_at`、`result_json = json.dumps("attempts exhausted")`），返回 `"failed"`；
   - 否则置 `pending`，返回 `"pending"`；
   - 只对 `status='claimed'` 行生效；rowcount=0（非 claimed/不存在）返回 `"failed"`（防御性兜底，行内容不变）；
   - 异常路径 rollback 后 raise（与 `claim_pending_shops` 同模式）。
3. **`claim_next_eligible(queues: list[str], consumer_id) -> dict | None`**（SPEC §3.2 跨队列原子认领）：
   - 空 queues 直接返回 None；
   - 单事务 `BEGIN IMMEDIATE`：`WHERE status='pending' AND queue IN (...)` `ORDER BY id LIMIT 1` → 置 claimed（claimed_by/claimed_at），FIFO 按 id、无优先级；
   - 返回四键 `{"id","queue","site","payload"}`，payload 为 `json.loads` 解码字典；无货返回 None；异常 rollback + raise。

## 测试列表（tests/test_work_items.py，新增 9 个 + 更新 1 个既有断言）

| 测试 | 覆盖点 |
|---|---|
| `test_release_returns_to_pending` | 用例 1：claim→release 回 pending、attempts=1、认领信息清空；重领不重置 attempts |
| `test_release_exhausts_attempts_to_failed` | 用例 2：release×3（默认 max_attempts=3）→ 第三次 failed、result_json="attempts exhausted"、finished_at 非空 |
| `test_release_terminal_return_with_custom_max_attempts` | 用例 3：自定义 max_attempts=2，返回值 pending→failed |
| `test_release_on_non_claimed_is_defensive_failed` | 用例 4：pending/done 行与不存在 id 均返回 failed 且行内容不变 |
| `test_claim_next_eligible_filters_queues` | 用例 5：只认领 queues 内；他队 pending 不碰；返回四键结构 |
| `test_claim_next_eligible_fifo_by_id_across_queues` | 用例 6：A/B 队交叉插入，严格按 id 升序认领 |
| `test_claim_next_eligible_no_double_claim` | 用例 7：两个消费者各领一次不撞单（仿 test_claim_no_double_claim） |
| `test_attempts_column_present_and_legacy_migration` | 用例 8：新建库含列；手工构造无 attempts 旧库 → 打开补列、存量行=0、重开幂等 |
| `test_claim_next_eligible_empty_queues_returns_none` | 用例 9：空队列返回 None 且不碰任何行 |
| `test_topup_marks_shops_and_no_duplicates`（更新） | DDL 列集合断言加入 `attempts` |

## TDD 证据

### RED（实现前跑新测试，失败输出）

```
$ python -m pytest tests/test_work_items.py -q
10 failed, 4 passed in 0.16s
FAILED tests/test_work_items.py::WorkItemsTest::test_attempts_column_present_and_legacy_migration
FAILED tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_empty_queues_returns_none
FAILED tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_fifo_by_id_across_queues
FAILED tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_filters_queues
FAILED tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_no_double_claim
FAILED tests/test_work_items.py::WorkItemsTest::test_release_exhausts_attempts_to_failed
FAILED tests/test_work_items.py::WorkItemsTest::test_release_on_non_claimed_is_defensive_failed
FAILED tests/test_work_items.py::WorkItemsTest::test_release_returns_to_pending
FAILED tests/test_work_items.py::WorkItemsTest::test_release_terminal_return_with_custom_max_attempts
FAILED tests/test_work_items.py::WorkItemsTest::test_topup_marks_shops_and_no_duplicates
```

失败原因均为预期：`release_work_item`/`claim_next_eligible` 不存在（AttributeError）、work_items 缺 attempts 列、既有列集合断言未含 attempts。

### GREEN（实现后通过）

```
$ python -m pytest tests/test_work_items.py -q
14 passed in 0.10s
```

### 全量无回归

```
$ cd fetcher && python -m pytest tests -q
318 passed, 2 subtests passed in 15.92s   （基线 309 + 新增 9）
```

## 改动文件

- `fetcher/fetcher/db.py`：`_migrate()` 追加 work_items attempts 迁移；新增 `release_work_item`、`claim_next_eligible` 两方法（`# ---------- work_items ----------` 段内，reset_claimed_work_items 之后）
- `fetcher/tests/test_work_items.py`：更新 DDL 列集合断言 + 新增 9 个用例（含 `_insert_item` helper，绕过 topup 直接构造多队列行）

## 自查发现

- **既有测试受列新增影响**：`test_topup_marks_shops_and_no_duplicates` 硬编码了 work_items 列集合断言，必须同步加入 `attempts`（否则旧测试挂，属预期连锁改动，已在 scoped 内）。
- **SCHEMA 未改动**：按 brief 仅实现 `_migrate()` 迁移（新建库同样经迁移补列，探测幂等）；SCHEMA 的 work_items DDL 保持原样，diff 最小。若后续希望新库 DDL 原生含列，可另行把 `attempts` 加进 SCHEMA，不属本任务范围。
- **release 的 rowcount=0 路径**：用 commit 结束事务（未发生任何写，rollback/commit 等价），返回 "failed" 不 raise，与 brief「防御性兜底」口径一致。
- **claim_next_eligible 空 queues**：前置 `if not queues: return None`，不进入事务（与「视为无货」语义一致）。
- 他人未提交改动（platform/*、vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/）未触碰。

## 提交

scoped commit：仅 `fetcher/fetcher/db.py` + `fetcher/tests/test_work_items.py`（未用 `git add -A`）。

---

## Review 修复（Important-1/2 + Minor-3/4）

> 审查包：task-1.1-review.md。修复 commit：见下文「提交」段。

### 改了什么

1. **Important-1（payload_json 非法泄漏）**：`claim_next_eligible` 的 `json.loads` 从 try 块外/commit 之后移入 try 块内、**UPDATE 置 claimed 之前**执行。非法 JSON 时 JSONDecodeError 走 `except → rollback`，行保持 pending（未被认领），不再产生「已 claimed 却拿不到 id、无法 release/finish」的永久泄漏行。
2. **Important-2（SELECT * 脆弱性）**：`claim_next_eligible` 的 `SELECT *` 改为显式列 `SELECT id, queue, site, payload_json`（sqlite3.Row 按名索引不受影响）。
3. **Minor-3**：`release_work_item` rowcount=0 路径 `commit()` → `rollback()`（无任何写发生，与文件内其他方法风格一致），加注释说明。
4. **Minor-4**：`claim_next_eligible` 返回构造移入 try 块内（commit 后），与 `release_work_item` 的 return-in-try 风格对称。

### 新增/调整测试

- 新增 `test_claim_next_eligible_invalid_payload_does_not_leak`（用例 10）：手工 UPDATE 一条非法 payload_json 的 pending 行 → claim 抛 `json.JSONDecodeError`（调用方可感知）→ 断言行保持 `pending`、`claimed_by` 为 NULL（可回收）→ 修复 payload 后可正常认领（未被卡死）。
- 既有 9 个用例未改动，全部继续通过。

### TDD 证据

RED（修复前跑新测试，失败在泄漏断言）：

```
$ python -m pytest tests/test_work_items.py::WorkItemsTest::test_claim_next_eligible_invalid_payload_does_not_leak -q
>       self.assertEqual(row["status"], "pending")
E       AssertionError: 'claimed' != 'pending'
1 failed in 0.05s
```

另用一次性脚本确认泄漏现形：异常后行状态为 claimed、claimed_by='w0'（LEAKED）。

GREEN（修复后）：

```
$ python -m pytest tests/test_work_items.py -q
15 passed in 0.10s
```

全量无回归：

```
$ cd fetcher && python -m pytest tests -q
319 passed, 2 subtests passed in 15.88s   （318 + 新增 1 个泄漏用例）
```

### 改动文件

- `fetcher/fetcher/db.py`：`claim_next_eligible`（解析移入 try、显式列、return 入 try、docstring 补说明）、`release_work_item`（rowcount=0 路径 rollback + 注释）
- `fetcher/tests/test_work_items.py`：新增用例 10

### 自查发现

- **泄漏确认**：修复前用一次性脚本实测——非法 payload 的 claim 抛出 JSONDecodeError 后行已置 claimed 且调用方拿不到 id（只能等 daemon 重启时 reset_claimed_work_items 回收），证实 review 判定属实。
- **解析放在 UPDATE 之前**而非「解析后 UPDATE 再 commit」：非法 payload 时 UPDATE 根本不会执行，rollback 语义最干净（避免先解析后 UPDATE 又因解析失败需手动还原的场景）。
- 无其他回归风险：显式列与 SELECT * 的 Row 按名索引行为一致，既有测试（含 filters/fifo/no_double_claim）全绿。

### 提交

scoped commit：仅 `fetcher/fetcher/db.py` + `fetcher/tests/test_work_items.py`（未用 `git add -A`，未触碰他人未提交改动）。
