# Step 3.3 — api/tasks.py TaskParams 四字段

> 这是你的需求唯一来源。PLAN Step 3.3 原文 + SPEC §6.3 精确规格抄录如下。

## PLAN Step 3.3 原文（验收以 checkbox 为准）

- [ ] TaskParams 追加 keywords/pages/provider/posts_per_group（SPEC §6.3）
- [ ] 测试：TaskCreate 携带四字段 round-trip 成功；TASK_TYPES 并集含两新类型
- 预估 15min；验收：测试全绿

## SPEC §6.3 api/tasks.py TaskParams 追加（精确规格）

```python
keywords: str | None = None         # fb_discover：查询词，换行分隔原文
pages: int | None = None            # fb_discover：每词页数（1-10）
provider: str | None = None         # fb_group：brightdata / apify
posts_per_group: int | None = None  # fb_group：每群帖数上限
```

## 协调者裁定

1. **插入位置**：`platform/server/app/api/tasks.py` 的 TaskParams 类，放在既有
   `accounts` 字段之后、`repeat_interval` 之前（或紧跟 accounts——保持「专用字段
   聚在一起」的注释风格）。
2. **注释**：每条字段带中文注释说明用途（对齐既有字段的 `# → -n` 风格，但这两个
   是批次专用字段，写 `# fb_discover：...` 即可）。
3. **TASK_TYPES 并集断言**：TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPE_NAMES（Step 3.1
   已注册两新类型）——测试断言 `'fb_discover' in TASK_TYPES` 且 `'fb_group' in
   TASK_TYPES`。
4. **测试基建**：platform/server/tests/test_batch_tasks.py 的 BatchTasksTestBase
   （临时 sqlite + patch DB_PATH）。round-trip 测试：POST /api/tasks 携带四字段 →
   落库 params_json → 读回断言字段齐全（参照既有 TaskCreate round-trip 测试写法，
   若有）。若无既有 round-trip 测试，直接测 `TaskParams.model_validate(...)` 与
   model_dump 往返即可（不依赖 HTTP 端点）。
5. **不验证四字段取值范围**（pages 1-10 / provider 限定是前端 validate 的职责，
   SPEC §7.3；后端仅透传）。

## 代码库上下文

- `platform/server/app/api/tasks.py`：TaskParams 在 92 行起（accounts 在 ~119 行，
  repeat_interval 在 ~126 行）；TaskCreate 在 125 行起。
- 测试运行：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks
  -v`；回归同一文件全量。

## TDD 纪律

1. 先失败测试 → RED → 最小实现 → GREEN。
2. 测试覆盖：TaskParams 四字段 model_dump 往返；TASK_TYPES 并集含两新类型。
3. 输出干净。

## Commit 约束

- 只 `git add`：`platform/server/app/api/tasks.py`、
  `platform/server/tests/test_batch_tasks.py`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 3.3 ...`。
