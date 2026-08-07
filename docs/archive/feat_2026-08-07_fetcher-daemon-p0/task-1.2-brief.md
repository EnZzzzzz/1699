# Step 1.2+1.3 brief — work_items 表 DDL + ShopDB 四个方法 + 存储层单测

> 来源：PLAN.md Phase 1 Step 1.2、1.3（PLAN 冲突扫描已裁定允许合并执行，但每个方法必须有对应的先红后绿记录）。本文本是你的需求唯一来源。

## Step 1.2 — DDL + 四个 DB 方法

在 `fetcher/fetcher/db.py` 的模块级 `SCHEMA` 常量中追加（严格按此 DDL，不得增减列）：

```sql
CREATE TABLE IF NOT EXISTS work_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    queue       TEXT NOT NULL,             -- P0 固定 "crawl_1688_contact"
    site        TEXT,                      -- "1688"
    batch_id    INTEGER,                   -- P0 恒 NULL（平台批次 P4 接入）
    payload_json TEXT NOT NULL,            -- contact: {"domain","name","url"}
    requires    TEXT NOT NULL DEFAULT '["channel","browser"]',
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/claimed/done/failed
    claimed_by  TEXT,                      -- "w0".."wN"
    claimed_at  TEXT,
    finished_at TEXT,
    result_json  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_items_claim ON work_items(queue, status, id);
```

并在 `ShopDB` 新增四个方法，严格仿照既有 `claim_pending_shops`（`db.py:286-318`）的 `BEGIN IMMEDIATE` 短事务模式；时间戳沿用模块内 `_now`：

| 方法签名 | 语义 |
|---|---|
| `topup_contact_work_items(self, queue: str, site: str, domain_suffix: str, limit: int) -> int` | 单事务：SELECT shops 中 status='pending' 且 domain 匹配 suffix 的最老 N 行（排序口径与 `claim_pending_shops` 一致：first_seen_at, id）→ 对每行 INSERT work_items（payload_json 含 domain/name/url 三键）+ UPDATE 该 shop 标 'in_progress' → 返回补货数。shops 状态语义必须与 claim_pending_shops 严格一致 |
| `claim_work_item(self, queue: str, consumer_id: str) -> dict \| None` | 单事务：取该队列最老 pending 项 → UPDATE 标 claimed + claimed_by + claimed_at → 返回 dict（含 id、payload 解析后的 domain/name/url；无货返回 None） |
| `finish_work_item(self, item_id: int, status: str, result: dict \| None = None) -> None` | status（done/failed）+ finished_at + result_json（result 为 None 时存 NULL）落库 |
| `reset_claimed_work_items(self) -> int` | 全部 claimed → pending，清空 claimed_by/claimed_at，返回重置行数 |

注意：`ShopDB` 的 `SCHEMA` 常量在 `db.py:78-171`，建表在 `__init__`（:184-204）；`INDEXES_AFTER_MIGRATE`（:174）是迁移后索引，索引放哪参照现有 work_items 之外表的做法（新表索引可直接写进 SCHEMA 段，与既有风格保持一致为准）。

## Step 1.3 — 存储层单测

新增 `fetcher/tests/test_work_items.py`（临时 sqlite，仿 `tests/test_contact_task.py` 基建）。用例：

1. top-up 后 shops 标 in_progress 且 work_items 行生成、重复 top-up 不产生重复行（pending 过滤）
2. 两个并发 claim 拿不到同一行（线程级或顺序模拟均可）
3. finish 落终态 + finished_at 时间戳
4. reset_claimed 把 claimed 重置为 pending
5. 空 shops 时 top-up 返回 0

## TDD 纪律（合并执行的裁定）

允许 DDL/方法与测试在同一个 Step 内迭代，但每个方法必须有「先写测试、亲眼看失败、再实现转绿」的记录（report 中 RED/GREEN 两段证据：命令 + 输出）。DDL 本身（表存在性）可作为用例 1 的前置断言顺带覆盖。

## 验收

- [ ] 四个方法签名与上表一致
- [ ] 5 个用例全绿，且先红后绿证据齐全
- [ ] 既有 `cd fetcher && python -m pytest tests -x -q` 无回归
- [ ] DDL 与上面给的 SQL 逐字一致（列、默认值、索引）

## 约束

- 只动 `fetcher/fetcher/db.py` + 新增 `fetcher/tests/test_work_items.py`，不碰其他文件。
- 不改任何既有方法的行为；SCHEMA 只追加，不改既有表定义。
- 代码风格跟随 db.py 既有模式（中文注释、_now、事务写法）。
