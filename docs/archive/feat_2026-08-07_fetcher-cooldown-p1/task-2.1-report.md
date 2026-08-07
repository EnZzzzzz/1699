# Step 2.1 report — 策略迁移（Sleep / BackoffSleep / BlockRest）

> 依据 task-2.1-brief.md 实现。本 Step 完成后 loop 尚未消费 cooldown（Step 2.2 才接），
> 属计划内中间态，不做运行冒烟。

## 实现内容

改 `fetcher/fetcher/strategy/strategies.py`，三个策略脱离 `_AtomStrategy`，run() 不再触发任何等待，时长算好放进 `StepResult.cooldown` 返回：

| 策略 | 迁移后行为 |
|---|---|
| `SleepStrategy` | `lo/hi` 从 `self._params.get("min"/"max", 2.0/5.0)` 取（与旧 Sleep 原子 atoms/sleep.py:37-38 取参路径一致），`t = human_pause_duration(lo, hi)`；log 文案保留 `...随机等待 {t:.1f}s`，detail 保留 `等待 {t:.1f}s`；返回 `StepResult(True, detail, cooldown=t)` |
| `BackoffSleepStrategy` | `params = {"base": 30, "cap": 180}` 保留；`attempt = self._params.get("attempt") or ctx.state.get("attempt", 1)`（or 短路逐字保留，0/空串回落）；`t = min(base * int(attempt), cap)`；log 文案保留 `...退避等待 {t:.0f}s（第 {attempt} 次）`；返回 `StepResult(True, detail, cooldown=t)` |
| `BlockRestStrategy` | min/max 仍 run 时从 `ctx.config.block_rest_min/max` 取（任务级覆盖语义保留）；时长用 Sleep 同款 `human_pause_duration(lo, hi)`（对数正态，与现状经 Sleep 原子走的分布一致）；⚠ 风控休息 log 行原样保留；返回 `StepResult(True, f"等待 {t:.1f}s", cooldown=t)` |
| `SwapIPStrategy` | 逻辑未动，docstring 加例外标注：「冷却例外：内部等待夹在两次 relaunch 之间，不迁移（SPEC §2.2，P3 重议）」 |

旧 `_AtomStrategy.run` 里 `ctx.state["attempt"] = ctx.state.get("attempt", 1)` 的写入副作用不再存在；新 BackoffSleep 直接以 `ctx.state.get("attempt", 1)` 读取，取值等价，无行为差异。

## 时长复刻方式

**import 复用**：`from fetcher.atoms.sleep import human_pause_duration`。atoms/sleep.py 是既有模块、该函数无耦合（纯 stdlib random/math），import 避免公式复制漂移。BackoffSleep 的 `min(base*int(attempt), cap)` 公式在 atoms/sleep.py 中没有独立函数（嵌在 BackoffSleep.run 内），故按 brief 逐字复刻（含 or 短路）。atoms/sleep.py 未改动（原子保留）。

import 行同步调整：`Sleep, BackoffSleep` 两个原子类不再被 strategies.py 引用，从 import 中移除。

## 更新的既有测试（逐条）

- **无既有测试需要更新**：全仓 grep 确认没有任何既有测试直接 run 这三个策略或断言「策略调用了 ctx.wait」（test_control_loop.py / test_policy.py 均用 FakeStrategy 注入，从不实例化真 Sleep/BackoffSleep/BlockRest 策略）。旧契约无测试锁定，故无「为让测试过而保留旧行为」的问题。
- **新增测试**（追加到既有文件 `fetcher/tests/test_cooldown_contract.py`，未新建文件，遵守「只动 strategies.py + 必要的既有测试文件」约束）：
  - `test_sleep_outputs_cooldown_and_never_waits`：cooldown 落在截断区间 [lo*0.5, hi*5]，waits 为空
  - `test_sleep_fixed_duration_when_min_eq_max`：min==max 时 cooldown == min
  - `test_sleep_default_params`：缺省 2.0/5.0 取参路径
  - `test_backoff_linear_with_state_attempt`：attempt=3 → 90s，零等待
  - `test_backoff_capped`：attempt=99 → 封顶 180s
  - `test_backoff_attempt_or_short_circuit`：params attempt=0 经 or 短路回落 state；有效值优先
  - `test_block_rest_reads_config_and_outputs_cooldown`：从 ctx.config 取 min/max、cooldown 在截断区间、零等待、⚠ log 行保留

## 测试结果

- **RED**：新测试对旧代码（HEAD 版 strategies.py）运行失败——`test_backoff_attempt_or_short_circuit` AssertionError（旧实现经原子走 ctx.wait、cooldown 为 None）。
- **GREEN**：新代码下 `pytest tests/test_cooldown_contract.py` → 12 passed。
- **全量**：`cd fetcher && python -m pytest tests -x -q` → **243 passed, 2 subtests passed in 8.04s**，无回归。
- **验收 grep**：strategies.py 中 `ctx.wait` 仅剩 1 处（line 163，SwapIPStrategy 内部等待，例外项）。

## 改动文件

- `fetcher/fetcher/strategy/strategies.py`（三策略迁移 + SwapIP 例外注释 + import 调整）
- `fetcher/tests/test_cooldown_contract.py`（新增 StrategyCooldownMigrationTest 7 条用例 + 模块 docstring 更新）

## 疑虑

- 旧路径中 Sleep/BlockRest 的 `StepResult.data` 带 `{"seconds": t}`（原子 ActionResult.success 带出），brief 明确返回 `StepResult(True, detail, cooldown=t)`，故新实现不带 data。grep 确认无消费者读取该 data，无影响。
- BlockRest 旧路径会多打一行 `...随机等待 {t:.1f}s`（来自 Sleep 原子）；brief 只点名保留 ⚠ 行，故该辅助行未保留。若 Step 2.2 chokepoint 会统一打等待日志，则信息不丢。
