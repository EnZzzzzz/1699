# Step 3.3 报告 — api/tasks.py TaskParams 四字段

- 状态：**DONE**
- 日期：2026-08-09（北京时间）
- 执行人：Step 3.3 implementer（subagent）
- 环境：`platform/server/.venv/bin/python`；分支 `feat/facebook-daemon-integration`

## 实现了什么

按 SPEC §6.3 + 协调者裁定，`platform/server/app/api/tasks.py` 的 `TaskParams` 在
`accounts` 字段之后、`repeat_interval` 之前追加四个批次专用字段（含中文注释，
对齐既有 `# 专用字段聚在一起` 风格）：

```python
    # fb 批次专用：
    keywords: str | None = None            # fb_discover：查询词，换行分隔原文
    pages: int | None = None               # fb_discover：每词页数（1-10）
    provider: str | None = None            # fb_group：brightdata / apify
    posts_per_group: int | None = None     # fb_group：每群帖数上限
```

- 不验证四字段取值范围（pages 1-10 / provider 限定属前端 validate 职责，后端仅透传，遵裁定 5）。
- 未触碰 runner / db 层——enqueue 消费端已由 Step 3.1/3.2 接好，本 Step 只补 API 层接收能力。

## 测了什么

`platform/server/tests/test_batch_tasks.py` 的 `TaskTypesTest` 新增两个测试：

1. `test_task_types_union_contains_fb_batch_types`：TASK_TYPES（TASK_COMMANDS ∪ BATCH_TYPES
   并集）含 `fb_discover` / `fb_group`（回归护栏，Step 3.1 已注册）。
2. `test_fb_batch_params_roundtrip_via_create_task`：`TaskCreate(type="fb_discover", params={四字段})`
   → 直接调 `create_task` 落库 → 读回 `tasks.params_json` → 断言四字段齐全
   （keywords 多行原文、pages=3、provider="brightdata"、posts_per_group=50）。
   库内有既有 TaskCreate round-trip 测试（无 HTTP TestClient 版），遵裁定 4 直接走
   `create_task` 函数级 round-trip，不依赖 HTTP 端点。

## TDD 证据

**RED**（实现前先跑新测试）：

```
.venv/bin/python -m unittest tests.test_batch_tasks.TaskTypesTest -v
...
test_fb_batch_params_roundtrip_via_create_task ... ERROR
...
KeyError: 'keywords'
```
失败原因符合预期：pydantic v2 默认 `extra='ignore'`，四字段未声明 → 被静默丢弃，
`params_json` 里没有 keywords，读回断言直接 KeyError。（TASK_TYPES 并集断言此时已
绿——Step 3.1 已注册两类型，属正常回归护栏。）

**GREEN**（加 4 行字段后）：

```
.venv/bin/python -m unittest tests.test_batch_tasks -v
Ran 30 tests in 0.336s
OK
```

**回归**（全量服务端测试）：

```
.venv/bin/python -m unittest discover -s tests -v
Ran 72 tests in 0.271s
OK
```

## 改动的文件

- `platform/server/app/api/tasks.py`（TaskParams +4 字段，含注释）
- `platform/server/tests/test_batch_tasks.py`（+2 测试）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-brief.md`（brief，随 commit 收录）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-report.md`（本文件）

## 自查

- **完整性**：SPEC §6.3 四字段名称/类型/默认值/注释逐字对齐；协调者裁定 1（插入位置）、2（中文注释）、3（并集断言）、4（测试基座）、5（不验证取值范围）全部满足。
- **质量**：插入位置对齐既有 TaskParams 风格（专用字段聚在一起 + `# 前缀：用途` 注释），无重复/冲突字段名。
- **纪律（YAGNI）**：只加 4 行字段 + 2 个测试，未动取值范围校验、未改 runner/db、未碰前端。
- **测试**：真实行为（落库 params_json 读回，非 mock）；RED 亲眼失败（KeyError）；输出干净（无 print/日志污染）。

## 疑虑

无。取值范围校验留给前端（SPEC §7.3），后端透传语义与既有批次参数（如 limit）一致。
