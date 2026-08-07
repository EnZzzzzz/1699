# Step 1.2 brief — 契约层实现 + 单测

> 来源：PLAN.md Phase 1 Step 1.2 + SPEC §3.1（含 Step 1.1 已回填的修正）。本文本是你的需求唯一来源。

## 内容

纯加法契约变更，两处（PolicyDecision **不加**字段——Step 1.1 已验证 decide 链路接触不到策略结果，loop 直接消费 step.cooldown）：

1. **`fetcher/fetcher/strategy/base.py`**：`StepResult`（:26-35）加第四字段 `cooldown: float | None = None`（放最后、带默认值，秒）。语义注释：**策略输出冷却、不执行冷却；cooldown 非空时策略保证自己没有为这段时长等待过**。
2. **`fetcher/fetcher/core/context.py`**：`WorkerContext`（:83-128）加 `cooldown_until: dict[str, float]`（dataclass field，default_factory=dict）。语义注释：冷却截止时间登记处（reason → time.time()+seconds），唯一写入者是 loop 的 chokepoint（Step 2.2 落地），P1 阶段只写不读，是 P3 调度器的查询接口。

## 测试

新增或并入既有测试文件（先看 `fetcher/tests/` 有没有 strategy/context 相关测试文件，跟随既有组织）：

1. `StepResult` 新字段默认值 None、关键字构造 `StepResult(True, "x", cooldown=12.5)` 生效；
2. 既有三参数位置构造 `StepResult(True, "x", {"k":1})` 不破坏（cooldown 落默认 None）——grep 全包 `StepResult(` 既有调用点，确认全部是位置≤3 或关键字构造，测试锁定这个兼容性；
3. `WorkerContext` 新字段初始化（默认空 dict、两实例不共享同一份 dict——default_factory 语义）。

## 验收

- [ ] 纯加法：grep `StepResult(` 与 `WorkerContext(` 全部既有调用点零改动（report 附 grep 结果）
- [ ] 新单测全绿（TDD 先红后绿）+ 全量 `cd fetcher && python -m pytest tests -x -q` 无回归

## 约束

- 只动 `strategy/base.py`、`core/context.py` + 测试文件。
- 不改任何策略/loop/atom 代码。
