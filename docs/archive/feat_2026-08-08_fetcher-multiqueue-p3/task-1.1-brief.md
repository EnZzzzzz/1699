# Task 1.1 Brief — work_items 扩展（attempts / release_work_item / claim_next_eligible）

> 来源：PLAN.md P3-1 Step 1.1 全文 + SPEC §3.2/§3.4 + 主 Agent 冲突扫描裁定。本文件是本次任务的唯一需求来源。

## 目标

在 `fetcher/fetcher/db.py` 的 work_items 存储层新增三个能力（全部 TDD，先写失败测试再看它失败）：

1. 幂等迁移：work_items 加 `attempts INTEGER NOT NULL DEFAULT 0` 列
2. `release_work_item(item_id, max_attempts=3) -> str`：挂起/重试语义（SPEC §3.4）
3. `claim_next_eligible(queues, consumer_id)`：跨队列原子认领（SPEC §3.2）

## 规格

### 1. attempts 列（幂等迁移）

- `_migrate()` 追加：`PRAGMA table_info(work_items)` 探测缺列时 `ALTER TABLE work_items ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0`
- 存量行 attempts=0（迁移默认）；重复执行幂等

### 2. release_work_item

```python
def release_work_item(self, item_id: int, max_attempts: int = 3) -> str:
    """工作项释放回 pending（attempts+1）；attempts 达上限置 failed。

    单事务（BEGIN IMMEDIATE）：attempts = attempts + 1，清空
    claimed_by/claimed_at；attempts >= max_attempts 时置 failed
    （写 finished_at、result_json="attempts exhausted"），否则置
    pending。返回终态字符串："pending" / "failed"。
    """
```

语义细节：
- 只对 **claimed** 状态的行生效（`WHERE id=? AND status='claimed'`）；rowcount=0（非 claimed/不存在）时返回 `"failed"`（调用方视为不可恢复，防御性兜底）——实现与测试都按此口径
- `attempts >= max_attempts` 时终态 `failed`，`result_json` 存 `"attempts exhausted"`（JSON 字符串，`json.dumps("attempts exhausted")`）
- 写 `finished_at`（北京时间字符串，`_now()`）
- 失败路径 `rollback` 后 `raise`（与既有 `claim_pending_shops` 同模式）

### 3. claim_next_eligible

```python
def claim_next_eligible(self, queues: list[str], consumer_id: str) -> dict | None:
    """跨队列原子认领最老 pending 工作项（FIFO 按 id，无优先级）。

    单事务（BEGIN IMMEDIATE）：WHERE status='pending' AND queue IN (...)
    ORDER BY id LIMIT 1 → 置 claimed（claimed_by/claimed_at）。返回
    {"id", "queue", "site", "payload"}（payload 为 json.loads 解码后
    的字典）；无货返回 None。
    """
```

- 入参是队列**集合**，返回四键 `{"id","queue","site","payload"}`（与现有 `claim_work_item` 的平铺 domain/name/url 形态不同——新调用方是 P3-3 的 QueueRouter）
- 空 queues 列表返回 None（或视为无货，防御性处理即可）
- 失败路径 `rollback` 后 `raise`

**现有方法一律不动**：`claim_work_item` / `topup_contact_work_items` / `finish_work_item` / `reset_claimed_work_items` 保持原样（旧路径兼容，P3-3 才替换调用方）。

## TDD 要求

新增测试放在 `tests/test_work_items.py`（仿既有基建：unittest + tempfile + ShopDB + `_shop()` helper）或新增 `tests/test_work_items_release.py`。至少覆盖：

1. **release 回 pending**：claim 后 release → status=pending、attempts=1、claimed_by/claimed_at 清空；再次 claim 可重领（且 attempts 保留）
2. **attempts 耗尽置 failed**：release 三次（max_attempts=3）→ 第三次返回 "failed"、status=failed、result_json 含 "attempts exhausted"、finished_at 非空
3. **release 终态返回值**：不足上限返回 "pending"，达上限返回 "failed"
4. **release 非 claimed 防御**：对 pending/done 行调用返回 "failed" 且行内容不变
5. **claim_next_eligible 队列集合过滤**：只认领 queues 内的；混有他队 pending 时不碰
6. **FIFO**：多队混排按 id 最老先领（可含不同 queue 的交叉插入）
7. **并发不重复认领**：顺序模拟两个消费者各领一次，不撞单（仿 `test_claim_no_double_claim` 模式）
8. **attempts 列存在性**：新建库 PRAGMA table_info 断言列存在；存量行（手工构造）默认 0
9. **空队列返回 None**

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`（测试命令 `cd fetcher && python -m pytest tests -q`）
- 既有模式参考（已读码）：`db.py:325` `claim_pending_shops`（BEGIN IMMEDIATE + rollback + raise）、`:429` `topup_contact_work_items`、`:465` `claim_work_item`、`:492` `finish_work_item`
- `_migrate()` 在 `db.py:225`（探测模式：`cols = {r[1] for r in self.conn.execute("PRAGMA table_info(shops)")}`）；work_items DDL 在 `db.py:174-189`；`_now()` 返回北京时间字符串
- payload_json 列存 JSON 字符串；claim_next_eligible 返回前 `json.loads`
- 现有测试基线 309 passed（`cd fetcher && python -m pytest tests -q`）——commit 前全量确认不 regress
- 写库一律短事务；ShopDB.__init__ 已设 `PRAGMA busy_timeout=30000`

## Git

- 分支 `feat/multiqueue-p3` 已就绪，直接在其上工作
- commit 范围：**scoped add**——只 add `fetcher/fetcher/db.py` + `fetcher/tests/` 下本次改动文件；工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），**绝不碰绝不带**，不要用 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`
- 若 commit 遇到 `.git/index.lock` 竞态（可能有另一个 Step 并行提交），sleep 几秒重试一次，仍失败就只保留工作区改动不 commit，并在 report 里注明

## 验收

1. TDD 证据：RED（实现前跑新测试，失败输出符合预期）→ GREEN（实现后通过）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿（309 + 新增）
3. 报告（task-1.1-report.md）含：实现摘要、测试列表、TDD RED/GREEN 证据（命令+输出）、改动文件、自查发现
