# Step 2.1 brief — 策略迁移（Sleep / BackoffSleep / BlockRest）

> 来源：PLAN.md Phase 2 Step 2.1 + SPEC §3.2 + Step 1.1 回填的时长公式。本文本是你的需求唯一来源。

## 内容

改 `fetcher/fetcher/strategy/strategies.py` 三个策略，run() 不再触发任何等待，时长算好放进 `StepResult.cooldown` 返回。**时长公式逐字复刻**（Step 1.1 已读码验证，SPEC §4 假设 2）：

### Sleep 分布（`human_pause_duration(lo, hi)`，atoms/sleep.py:21-27）

```python
lo >= hi → float(lo)
否则：t = random.lognormvariate(math.log((lo + hi) / 2), 0.5)
clamp：max(lo * 0.5, min(t, hi * 5))
# 随机源：stdlib random 模块级实例
```

### BackoffSleep（atoms/sleep.py:57-66）

```python
attempt = params.get("attempt") or ctx.state.get("attempt", 1)   # or 短路逐字保留（0/空串会回落）
t = min(base * int(attempt), cap)    # base=30.0, cap=180.0（现 BackoffSleepStrategy.params 同款）
```

### 逐个迁移要求

| 策略 | 迁移后行为 |
|---|---|
| `SleepStrategy`（strategies.py:41） | 用上述分布算 t（lo/hi 来自 self._params min/max，与现原子取参路径一致——先读 atoms/sleep.py:36-44 确认），返回 `StepResult(True, detail, cooldown=t)`；不再调 Sleep 原子；detail/log 文案保持现状口径 |
| `BackoffSleepStrategy`（:46-50） | 按上式算 t（attempt 获取路径逐字保留 or 短路），返回 `StepResult(True, detail, cooldown=t)`；不再调 BackoffSleep 原子 |
| `BlockRestStrategy`（:53-67） | params 仍 run 时从 `ctx.config.block_rest_min/max` 取（任务级覆盖语义保留）；时长用 Sleep 同款分布（`human_pause_duration(min, max)` 公式逐字复刻——注意现状就是经 Sleep 原子走的对数正态，不是 uniform）；保留现有 log 行（⚠ 风控休息…）；返回 `StepResult(True, detail, cooldown=t)` |
| `SwapIPStrategy`（:86-135） | **不动逻辑**，类 docstring 加一行例外标注：「冷却例外：内部等待夹在两次 relaunch 之间，不迁移（SPEC §2.2，P3 重议）」 |

时长计算建议提取一个模块级辅助函数（如 `_pause_duration(lo, hi)`）放在 strategies.py 或从 atoms/sleep.py import `human_pause_duration`——**优先 import 复用**（atoms/sleep.py 是既有模块，直接 from import 其分布函数，避免复制公式漂移）；若该函数有不宜 import 的耦合再复制，report 说明选择。

## 既有测试的处理

迁移改变了策略契约（不再自己等待）。若有既有测试断言「策略调用了 ctx.wait / 等待发生了」，这些测试测的是旧契约——在同一 commit 中更新为断言新契约（cooldown 输出、零等待），report 逐条说明改了哪些既有测试、为什么改。不许为了让测试过而保留旧行为。

## 验收

- [ ] 三策略 grep 无 `ctx.wait`（strategies.py 中三策略代码路径）；SwapIP 有例外注释
- [ ] 时长公式与 SPEC §4 假设 2 逐字一致（import 复用或逐字复刻，report 说明）
- [ ] 全量 `cd fetcher && python -m pytest tests -x -q` 无回归（被更新的旧契约测试除外，逐条说明）

## 约束

- 只动 `fetcher/fetcher/strategy/strategies.py` + 必要的既有测试文件。
- 不碰 loop.py（chokepoint 是 Step 2.2）——**注意**：本 Step 完成后 loop 尚未消费 cooldown，策略冷却暂时不会被执行（中间态），这是计划内的，Step 2.2 接上；因此本 Step 不做运行冒烟，只跑测试。
- 不碰 atoms/sleep.py（原子保留）。
