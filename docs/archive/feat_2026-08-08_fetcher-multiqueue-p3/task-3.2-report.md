# Task 3.2 Report — SwapIP 两阶段拆分 + 策略冷却让出/release 链路

> 基线 commit：5c1afe8（438 passed）· 分支 `feat/multiqueue-p3`

## 实现摘要

修复 Step 3.2 review 发现 4 条问题（I1 + M1/M2/M3），详情见 Fix Round 1 文档
`task-3.2-fix1.md`。

### I1（Important，防御性）— loop.py `_process_item` 策略冷却无条件优先

**问题**：`if step.cooldown:` 无条件优先于 `step.solved`，若未来策略返回
`StepResult(solved=True, cooldown=0.5)`，item 会被误 release 而非成功。

**修复**：`loop.py:456` cooldown 分支加 `not step.solved` 守护——
```python
if step.cooldown and not step.solved:
```
solved=True 时不 release，cooldown 仅作冷却建议不计。

**适配测试**：`test_cooldown.py`
- 原 `test_strategy_cooldown_via_chokepoint_then_retry_success`（solved=True+cooldown）
  → 重命名为 `test_strategy_cooldown_with_solved_true_skips_release`：
  断言 solved 优先、cooldown 未被调用、fetch 重试后成功（fetches=2, succeeded=["item1"]）
- 新增 `test_strategy_cooldown_solved_false_triggers_release`：solved=False+cooldown
  → 触发让出+release（原路径全覆盖保留）

**适配测试**：`test_swapip_two_phase.py`
- `FakeReleaseStrategy` 实例化从 `solved=True` 改为 `solved=False`（2 处），
  使其正确测试 release 路径

### M1 — strategies.py site=None 时两阶段静默输出 cooldown

**问题**：`if site:` 守卫正确防空指针，但 site=None 时继续输出 cooldown，item 重试
至 attempts 耗尽而不报错。

**修复**：`strategies.py:196-200` 加 else 分支——
```python
else:
    ctx.log(f"    [WARNING] active_site 未设置，无法登记两阶段")
    return StepResult(False, "active_site 未设置，无法登记两阶段")
```
不输出 cooldown，避免静默耗尽 attempts。

### M2 — test_swapip_two_phase.py 缺 ctx.wait 未调用断言

**修复**：`test_not_rotated_headless_triggers_two_phase` 内用
`patch.object(ctx, 'wait')` mock + `assert_not_called()` 验证无头路径不含原地 wait。

### M3 — test_swapip_two_phase.py result_json 断言脆弱

**修复**：`json.loads(row["result_json"])` → `assertIn("attempts exhausted", row["result_json"])`，
不再与 `json.dumps("attempts exhausted")` 格式耦合；顺带移除未使用的 `import json`。

## 测试列表

### 改动文件

| 文件 | 改动 |
|---|---|
| `fetcher/fetcher/control/loop.py` | I1: cooldown 分支加 `not step.solved` 守护 |
| `fetcher/fetcher/strategy/strategies.py` | M1: site=None else 分支返回错误不输出 cooldown |
| `fetcher/tests/test_cooldown.py` | I1 适配：重命名 1 测试 + 新增 1 测试 |
| `fetcher/tests/test_swapip_two_phase.py` | M1/M2/M3 修复：新增 M1 测试、M2 mock、M3 断言去耦合、solved 参数修正 |

### 测试覆盖

| 测试 | 覆盖项 |
|---|---|
| `test_strategy_cooldown_with_solved_true_skips_release` | I1: solved=True+cooldown → solved 优先，cooldown 不触发 |
| `test_strategy_cooldown_solved_false_triggers_release` | I1: solved=False+cooldown → release（原路径回归） |
| `test_strategy_cooldown_interrupted_by_stop_is_stop_terminal` | stop 语义（solved=False 无变更） |
| `test_no_active_site_headless_returns_error_no_cooldown` | M1: active_site 未设置 → 错误无 cooldown |
| `test_not_rotated_headless_triggers_two_phase` | M2: ctx.wait 未被调用断言 |
| `test_release_item_exhaustion_returns_failed` | M3: assertIn 替代 json.loads |
| 全量 | 440 passed, 2 subtests passed |

## TDD 证据

### I1 TDD（RED → GREEN）

1. **RED**：运行 `test_strategy_cooldown_with_solved_true_skips_release`
   （原名 test_strategy_cooldown_via_chokepoint_then_retry_success）：
   solved=True+cooldown 时原断言 fetches=1 / succeeded=[] 与新守护不兼容
   ——策略被调后 solved 优先，会重试 fetch 成功（fetches=2, succeeded=["item1"]）
2. **GREEN**：加 `not step.solved` 守护 → 更新断言后通过

### M1 TDD（RED → GREEN）

1. **RED**：`test_no_active_site_headless_returns_error_no_cooldown`
   ——加 else 分支前，site=None 走默认路径输出 cooldown，断言 `assertIsNone(result.cooldown)` 失败
2. **GREEN**：加 else 分支 return StepResult(False, …, cooldown=None 即默认) → 通过

### M2/M3（测试本身改动，修复前后行为确认）

- M2：mock ctx.wait → assert_not_called，SwapIP 无头路径未调 ctx.wait（结构验证）
- M3：`assertIn("attempts exhausted", …)` 替代 `json.loads(…)"`，db.py `json.dumps("attempts exhausted")` 不变

## 修复记录

| 编号 | 严重程度 | 描述 | 状态 |
|---|---|---|---|
| I1 | Important | loop.py cooldown 无条件优先 solved | ✅ 已修复 |
| M1 | Minor | strategies.py site=None 静默输出 cooldown | ✅ 已修复 |
| M2 | Minor | test 缺 ctx.wait 未调用断言 | ✅ 已修复 |
| M3 | Minor | test result_json 断言脆弱 | ✅ 已修复 |

## 全量测试

```
cd fetcher && python -m pytest tests -q
440 passed, 2 subtests passed in 26.59s
```
