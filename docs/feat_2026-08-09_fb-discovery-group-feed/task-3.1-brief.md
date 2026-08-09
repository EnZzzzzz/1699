# Step 3.1 — runner BATCH_TYPES + enqueue 分支（TDD）

> 这是你的需求唯一来源。PLAN Step 3.1 原文 + SPEC §6.1 精确规格抄录如下。

## PLAN Step 3.1 原文（验收以 checkbox 为准）

- [ ] `platform/server/app/runner.py` BATCH_TYPES 追加 fb_discover/fb_group
      （SPEC §6.1 精确 dict）
- [ ] `enqueue_batch_for_task` 追加两分支（keywords×pages / provider+posts_per_group
      +limit，缺省值 1/50/brightdata）
- [ ] 测试（扩展 platform/server/tests/test_batch_tasks.py）：enqueue_batch_for_task
      对两类型分派正确（mock app.db 函数断言参数）
- 预估 30min；验收：新测试全绿 + 既有批次测试零回归

## SPEC §6.1 批次类型注册（精确规格）

`runner.py BATCH_TYPES` 追加（BATCH_TYPE_NAMES 自动并集）：

```python
"fb_discover": {"queue": "discover_fb", "site": None,
                "domain_suffix": "", "kind": "fb_discover"},
"fb_group":    {"queue": "crawl_fb_group", "site": None,
                "domain_suffix": "", "kind": "fb_group"},
```

`enqueue_batch_for_task` 追加两分支：

```python
if spec["kind"] == "fb_discover":
    return enqueue_fb_discover_batch(task_id, params.get("keywords") or "",
                                     int(params.get("pages") or 1))
if spec["kind"] == "fb_group":
    return enqueue_fb_group_batch(task_id,
                                  (params.get("provider") or "brightdata"),
                                  int(params.get("posts_per_group") or 50),
                                  limit)
```

## 协调者裁定

1. **注意：BATCH_TYPES 里有既有未提交改动吗？** 无——daemon-headed-queues 工作线
   已于 Step 前单独 commit（dbab0da），runner.py 的 _derive_batch_status 改动已入库。
   你现在看到的是干净 base。
2. **两分支顺序**：追加在既有 fb_post 分支之后、`return 0` 之前。
3. **enqueue_fb_discover_batch / enqueue_fb_group_batch 尚不存在**（Step 3.2 实现）——
   本 Step 只改 runner.py 的 BATCH_TYPES + enqueue_batch_for_task 分支；测试 mock
   `app.db.enqueue_fb_discover_batch` / `enqueue_fb_group_batch`（unittest.mock.patch
   app.db 模块属性），断言参数透传。**不要在本 Step 实现 app/db.py 的两个函数**。
4. **TDD 顺序**：先写失败测试（mock app.db 函数 + 断言两类型分派参数）→ 改 runner.py
   转绿。mock 断言精确值：fb_discover → enqueue_fb_discover_batch(task_id,
   keywords_str, pages_int)；缺省 keywords=""、pages=1；fb_group →
   enqueue_fb_group_batch(task_id, provider_str, posts_per_group_int, limit)；
   缺省 provider="brightdata"、posts_per_group=50。
5. **测试基建**：platform/server/tests/test_batch_tasks.py 已有
   BatchTasksTestBase（临时 sqlite + patch DB_PATH）。跑测试用
   `cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks`。
   enqueue_batch_for_task 的调用方（sweeper/runner）已有测试覆盖，本 Step 只加
   分派断言。

## 代码库上下文

- `platform/server/app/runner.py`：BATCH_TYPES 在 36-62 行（fb_post 在 55-60 行），
  enqueue_batch_for_task 在 284 行起（import 在函数内，fb_post 分支约 299-301 行）。
- `platform/server/app/api/tasks.py` 的 TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPE_NAMES
  （自动并集，不用改）。
- 测试运行：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks
  -v`；回归同一文件全量。

## TDD 纪律

1. 先失败测试 → RED → 最小实现 → GREEN。
2. 测试覆盖：fb_discover 分派（默认与显式 keywords/pages）、fb_group 分派（默认与
   显式 provider/posts_per_group、limit 透传）、既有类型零回归。
3. 输出干净。

## Commit 约束

- 只 `git add`：`platform/server/app/runner.py`、
  `platform/server/tests/test_batch_tasks.py`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 3.1 ...`。
