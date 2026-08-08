# Fix Round 1 — Step 3.2（新 implementer，原 implementer 超时失联）

你的任务：修复 Step 3.2（SwapIP 两阶段 + 策略冷却 release 链路）review 发现的 4 条问题。
reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-review.md
任务 brief（需求来源）：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-brief.md
当前代码已 commit（5c1afe8），全量 438 passed。你在该基础上修复。

## 发现清单（逐字）

### I1（Important，防御性）— strategies.py:445-450 `_process_item` 中 step.cooldown 无条件优先于 step.solved

现状：`if step.cooldown:` 无条件优先（solved 日志只记不 return）。若未来某策略返回 StepResult(solved=True, cooldown=0.5)，item 会被误 release 而非成功。目前无真实策略如此返回，但结构未阻止。

修复：在 cooldown 分支加 `not step.solved` 守护（solved=True 时不 release），并加注释说明语义。保持现有行为（无策略同时返回 solved+cooldown）。

### M1 — strategies.py:196-203 site=None 时两阶段只输出 cooldown 不置 needs_relaunch

现状：`if site:` 守卫正确防空指针，但 site=None 时静默走两阶段 cooldown 不登记，item 重试至 attempts 耗尽。

修复：加 else 分支——site 未设置时记 WARNING 日志并返回 StepResult(False, "active_site 未设置，无法登记两阶段")，不输出 cooldown（避免静默耗尽 attempts）。

### M2 — test_swapip_two_phase.py:120-150 缺 ctx.wait 未调用断言

TDD 要求 1 明确「无原地 wait（ctx.wait 未被调）」，当前测试未直接断言。

修复：补 ctx.wait 未被调用的断言（mock ctx 或结构注释；用测试可用的方式，若 ctx 是 WorkerContext 真实例不便 mock，加注释说明无头路径不含 ctx.wait 的结构验证）。

### M3 — test_swapip_two_phase.py:568-569 result_json 断言脆弱

`json.loads(row["result_json"])` 与 DB 写入格式耦合（release_work_item 写入 json.dumps("attempts exhausted") = '"attempts exhausted"'）。

修复：改为断言 `row["result_json"]` 含 `"attempts exhausted"`（`assertIn` 或精确 JSON 字符串断言），去掉脆弱解析。注意：确认 release_work_item 的写入格式（fetcher/fetcher/db.py，Step 1.1 实现为 json.dumps("attempts exhausted")）后按实际格式断言。

## 要求

1. 修复 I1/M1/M2/M3（TDD：M2/M3 是测试本身改动，先确认修复前后行为；I1/M1 补失败测试再实现）
2. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
3. 报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-report.md（本 Step 首次 report：实现摘要 + 测试列表 + TDD 证据 + 修复记录）
4. scoped commit（fetcher/fetcher/strategy/strategies.py、fetcher/fetcher/control/loop.py、fetcher/tests/、task-3.2-report.md 等）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、report 路径。
