# Step 3.2 — app/db.py enqueue 双函数（TDD）

> 这是你的需求唯一来源。PLAN Step 3.2 原文 + SPEC §6.2 精确规格抄录如下。

## PLAN Step 3.2 原文（验收以 checkbox 为准）

- [ ] `enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`：换行拆词 × 页
      展开，payload {"kind","engine","query","page"}，requires='["local"]'，
      同 query+page 已有 pending 跳过，keywords 空→0
- [ ] `enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`：
      BEGIN IMMEDIATE 单事务 SELECT pending fb_groups → INSERT items → 置
      in_progress；fb_groups 表不存在→0（防御性探测）
- [ ] 测试（扩展 test_batch_tasks.py）：展开数/幂等/空关键词/限量/表缺失返回 0/
      payload 断言
- 预估 40min；验收：新测试全绿

## SPEC §6.2 app/db.py 新增（精确规格）

- `enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`：
  关键词（换行分隔）逐词 × 页码展开；payload
  `{"kind":"serp","engine":"ddg","query":kw,"page":N}`；`requires='["local"]'`、
  site=NULL、batch_id；**幂等：同 query+page 已有 pending 跳过**；keywords 空 → 0。
  返回入队 item 数。
- `enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`：
  `BEGIN IMMEDIATE` 单事务：SELECT pending fb_groups（limit>0 限量）→ INSERT
  work_items（payload `{"url","provider","limit"}`，limit=posts_per_group）→
  源行置 in_progress；**fb_groups 表不存在（fetcher 侧未建）→ 返回 0**（防御性
  探测，对齐 enqueue_fb_post_batch）。返回入队行数。

## 协调者裁定（覆盖 SPEC 未定细节）

1. **收尾 Step 3.1 的懒导入**（Step 3.1 reviewer Minor ② 已列为必做）：本 Step 实现
   两个函数后，把 runner.py enqueue_batch_for_task 两分支的懒导入并入函数顶部既有
   的 `from app.db import (...)` 集中 import（enqueue_fb_discover_batch /
   enqueue_fb_group_batch 加入其中，删掉分支内懒导入）。这是跨 Step 的收尾，必须做。
2. **enqueue_fb_discover_batch 的展开逻辑**：
   - keywords 按换行拆词（`splitlines()`），strip 后过滤空行；空 → 0。
   - 每词 × 每页（1..pages，pages<1 视为 1）；payload `{"kind":"serp","engine":"ddg",
     "query":kw,"page":N}`；INSERT (queue='discover_fb', site=NULL, batch_id,
     payload_json, requires='["local"]', created_at=_bj_now())。
   - 幂等：INSERT 前查 `work_items WHERE queue='discover_fb' AND status='pending'
     AND json_extract(payload_json,'$.query')=? AND json_extract(payload_json,
     '$.page')=?` 存在则跳过（参照 enqueue_feeder_batch 的 json_extract 幂等模式）。
   - 返回实际入队数。
3. **enqueue_fb_group_batch 的事务模式**：对齐 enqueue_fb_post_batch——
   sqlite3.connect(DB_PATH, timeout=30) + PRAGMA busy_timeout=30000 + sqlite_master
   探测 fb_groups 表（无 → 0）+ BEGIN IMMEDIATE + SELECT pending fb_groups
   (ORDER BY first_seen_at, id，limit>0 时 LIMIT) + INSERT work_items
   (queue='crawl_fb_group', site=NULL, batch_id, payload `{"url":r["url"],
   "provider":provider,"limit":posts_per_group}`，requires='["local"]',
   created_at) + UPDATE fb_groups SET status='in_progress' + commit；异常 rollback
   + raise；finally close。返回入队行数。
4. **limit 语义**：fb_group 的 limit 是「群数上限」（0=不限），与 enqueue_fb_post_batch
   的 limit 语义一致。
5. **时间戳**：`_bj_now()`（platform app/db.py 既有，北京时区字符串）。
6. **测试基建**：test_batch_tasks.py 的 BatchTasksTestBase（临时 sqlite + patch
   DB_PATH）。测试需要建 work_items/fb_groups 表结构（参照既有测试的 _schema 或
   enqueue_fb_post_batch 测试的建表方式）。
7. **测试覆盖**（PLAN 已列）：展开数（2 词 × 2 页 = 4）、幂等（同 query+page 已有
   pending 跳过 → 二次调用入队 0）、空关键词 → 0、payload 断言（kind/engine/query/
   page、requires='["local"]'、site=NULL、batch_id）、fb_group 限量（limit=2 取 2
   群）、表缺失返回 0（无 fb_groups 表时）、fb_group payload 断言（url/provider/
   limit=posts_per_group）、源行置 in_progress。

## 代码库上下文

- `platform/server/app/db.py`：`_bj_now()`（顶部）、`enqueue_fb_post_batch`（192 行起，
  本 Step 直接参照其结构）、`enqueue_wa_batch`（316 行起，requires='["local"]' 的
  INSERT 写法参照）。
- `platform/server/app/runner.py`：enqueue_batch_for_task 两分支（Step 3.1 已加，
  懒导入在分支内）。
- 测试运行：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks
  -v`；回归同一文件全量。

## TDD 纪律

1. 先失败测试 → RED → 最小实现 → GREEN。落库用临时 sqlite 断言真实行。
2. 测试覆盖（brief 已列全）。
3. 输出干净。

## Commit 约束

- 只 `git add`：`platform/server/app/db.py`、`platform/server/app/runner.py`（懒导入
  收尾）、`platform/server/tests/test_batch_tasks.py`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 3.2 ...`。
