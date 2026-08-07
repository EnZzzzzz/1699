# Step 1.1 brief — 读码确认（SPEC §4 假设 2、3）

> 来源：PLAN.md Phase 1 Step 1.1。本文本是你的需求唯一来源。

## 内容

两个读码确认，结论回填 SPEC：

### ① Sleep/BackoffSleep 的时长分布公式（SPEC §4 假设 2）

读 `fetcher/fetcher/atoms/sleep.py` 全文，把 `Sleep`（约 :41）和 `BackoffSleep`（约 :63）两个原子的时长计算**逐字摘出**（分布类型、参数、clamp 逻辑、随机源），回填到 `docs/feat_2026-08-07_fetcher-cooldown-p1/SPEC.md` §4 假设 2 行：依据列改「已读码验证（附 file:line）」，验证方式列写入完整公式（后续 Step 2.1 要逐字复刻，写错就全盘皆错）。顺带确认原子内 `ctx.wait` 的确切调用形式。

### ② cooldown 是否需要经 PolicyDecision 透传（SPEC §4 假设 3）

读 `fetcher/fetcher/strategy/policy.py`（PolicyDecision :70-77、decide :156-194）与 `fetcher/fetcher/control/loop.py:319-395`（_process_item 的策略消费链路），确认：`step = strategy.run(ctx)` 的返回值是不是只有 loop 消费、decide 链路是否根本接触不到策略执行结果。

- 若确认 decide 用不上 → SPEC §3.1 中 `PolicyDecision` 加字段那条**删除**，假设 3 回填「已验证：不需要透传，loop 直接消费 step.cooldown」；
- 若发现 decide 确实需要携带 → 回填「需要透传」并说明理由。

## 背景

P1 要把三个策略（Sleep/BackoffSleep/BlockRest）从「自己 ctx.wait」改成「输出 cooldown 时长」。时长公式必须逐字保留（等价性验收的根基），你摘的公式就是 Step 2.1 的唯一依据。

## 验收

- [ ] SPEC §4 假设 2、3 依据列改为「已读码验证（附 file:line）」，结论明确无歧义
- [ ] 时长分布公式完整写入 SPEC（含 clamp 边界与随机源）

## 约束

- 只读代码 + 改 SPEC.md，**不改任何 fetcher 代码**。
