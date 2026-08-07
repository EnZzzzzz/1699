# Step 1.1 report — 读码确认（SPEC §4 假设 2、3）

> 执行：2026-08-07，分支 feat/fetcher-cooldown-p1。纯读码 + 回填 SPEC，无 fetcher 代码改动。

## ① 时长分布公式逐字摘录（假设 2 → 已验证）

来源：`fetcher/fetcher/atoms/sleep.py` 全文（66 行）。

### Sleep（Sleep.run :36-44，公式本体 human_pause_duration :21-27）

参数读取（sleep.py:37-38）：

```python
lo = float(params.get("min", 2.0))
hi = float(params.get("max", 5.0))
t = human_pause_duration(lo, hi)
```

时长公式（sleep.py:21-27，逐字）：

```python
def human_pause_duration(lo: float = 2.0, hi: float = 5.0) -> float:
    """拟人随机等待时长（对数正态分布，截断 [lo*0.5, hi*5]）。"""
    if lo >= hi:
        return float(lo)
    median = (lo + hi) / 2
    t = random.lognormvariate(math.log(median), 0.5)
    return max(lo * 0.5, min(t, hi * 5))
```

- 分布类型：对数正态；退化分支 `lo >= hi` → 固定 `float(lo)`。
- 参数：mu = `math.log((lo + hi) / 2)`（中位数取区间中点），sigma = `0.5`。
- clamp：`max(lo * 0.5, min(t, hi * 5))`——**下限 lo×0.5、上限 hi×5**（注意：不是 [lo, hi]，SPEC §3.2 原表述「clamp 到 [min,max]」有误，已在回填中更正为 [min*0.5, max*5]）。
- 随机源：stdlib `random` 模块级实例的 `random.lognormvariate`（无独立 seed/实例）。

### BackoffSleep（BackoffSleep.run :57-66）

```python
base = float(params.get("base", 30.0))
cap = float(params.get("cap", 180.0))
attempt = params.get("attempt") or ctx.state.get("attempt", 1)
t = min(base * int(attempt), cap)
```

- 纯线性退避 `min(base * attempt, cap)`，**无随机源、无 clamp 浮动**。
- attempt 传递路径（已读码确认）：`loop.py:387` `ctx.state["attempt"] = decision.attempt`（decision 来自 policy.decide，attempt=tracker.used，1 起）→ 原子 `ctx.state.get("attempt", 1)`；`params["attempt"]` 非空时优先（`or` 短路，注意 `attempt=0`/空串也会回落到 ctx.state）。

### 原子内 ctx.wait 调用形式（两原子同构）

sleep.py:41-44 / :63-66：

```python
interrupted = ctx.wait(t)
if interrupted:
    return ActionResult(Outcome.SKIPPED, "被停止信号中断")
return ActionResult.success(f"等待 {t:.1f}s", seconds=t)   # BackoffSleep 文案不同
```

即 `ctx.wait(t)` 返回 bool（True=被 stop 中断），中断→SKIPPED，正常→success(seconds=t)。

## ② PolicyDecision 链路读码结论（假设 3 → 已验证：不需要透传）

- `PolicyDecision`（policy.py:70-77）只有四字段：`action / strategy / attempt / detail`。
- `Policy.decide`（policy.py:156-194）是纯链推进决策：输入 scenario+tracker，输出 PolicyDecision；**从不接触策略执行结果**（策略甚至还没执行，decide 在前、run 在后）。
- 消费链路（loop.py `_process_item` :386-394）：`strategy = self.policy.strategies[decision.strategy]` → `ctx.state["attempt"] = decision.attempt` → `step = strategy.run(ctx)` → 只有 loop 自己读 `step.solved`/`step.detail`。step 返回值没有任何其他消费者。
- 结论：**decide 链路用不上 cooldown**。`step.cooldown` 由 loop 在 `_process_item` 内直接消费即可，PolicyDecision 不加透传字段。SPEC §3.1 中「PolicyDecision 加字段」一条已删除，§2.1 范围描述同步加了备注。

## SPEC 回填内容（docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md）

1. §2.1 范围第 1 条：删去「`PolicyDecision` 加同名透传字段」，加备注指向假设 3 结论。
2. §3.1 契约变更：PolicyDecision 条目改为「不加 cooldown 字段」并附读码依据。
3. §3.2 BackoffSleep 行：attempt 传递路径标注为已读码确认（loop.py:387 → atoms/sleep.py:60）。
4. §3.2 BlockRest 行：更正 clamp 区间为 `[min*0.5, max*5]`，公式依据指向 §4 假设 2（删除原「random.uniform」表述——与现状对数正态不一致，复刻依据以假设 2 摘录为准）。
5. §4 假设 2：依据列改「已读码验证（附 file:line）」，验证方式列写入完整公式（分布、参数、clamp、随机源、ctx.wait 调用形式）。
6. §4 假设 3：依据列改「已读码验证（附 file:line）」，结论「不需要透传，loop 直接消费 step.cooldown」。

## 附带发现（供后续 Step 注意）

- SPEC §3.2 原文「clamp 到 [min,max]」与代码不符（实为 [lo*0.5, hi*5]），已更正；等价性验收的时长区间断言应按 [min*0.5, max*5] 写。
- `params["attempt"] or ctx.state.get("attempt", 1)` 是 `or` 短路不是 `is None` 判断，复刻时逐字保留。

## commit

（见下方 git log；message：`docs(cooldown-p1): Step 1.1 读码确认回填 SPEC（时长公式逐字摘录 + PolicyDecision 免透传）`）
