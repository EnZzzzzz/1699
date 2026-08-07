# Step 1.2 report — 契约层实现（冷却策略迁移 P1，Phase 1）

## 实现内容

按 brief 纯加法两处契约变更，无其他改动：

1. **`fetcher/fetcher/strategy/base.py`** — `StepResult` 加第四字段
   `cooldown: float | None = None`（放最后、带默认值，秒）。语义注释：策略输出冷却、
   不执行冷却；cooldown 非空时策略保证自己没有为这段时长等待过。
2. **`fetcher/fetcher/core/context.py`** — `WorkerContext` 加
   `cooldown_until: dict[str, float]`（dataclass field，default_factory=dict）。
   语义注释：冷却截止时间登记处（reason → time.time()+seconds），唯一写入者是 loop
   的 chokepoint（Step 2.2 落地），P1 阶段只写不读，是 P3 调度器的查询接口。

`PolicyDecision` 未加字段（Step 1.1 已验证 decide 链路不接触策略结果）。

## TDD 证据

测试文件：`fetcher/tests/test_cooldown_contract.py`（新增；tests/ 下无既有
strategy/context 契约测试文件，test_policy.py 只覆盖 Policy/AttemptTracker，故新建）。

### RED（实现前）

```
$ cd fetcher && python -m pytest tests/test_cooldown_contract.py -q
FAILED tests/test_cooldown_contract.py::StepResultCooldownTest::test_cooldown_default_none
FAILED tests/test_cooldown_contract.py::StepResultCooldownTest::test_cooldown_keyword_construction
FAILED tests/test_cooldown_contract.py::StepResultCooldownTest::test_positional_three_args_still_works
FAILED tests/test_cooldown_contract.py::WorkerContextCooldownUntilTest::test_cooldown_until_default_empty_dict
FAILED tests/test_cooldown_contract.py::WorkerContextCooldownUntilTest::test_cooldown_until_not_shared_between_instances
5 failed in 0.06s
（AttributeError / TypeError：字段尚不存在）
```

### GREEN（最小实现后）

```
$ cd fetcher && python -m pytest tests/test_cooldown_contract.py -q
.....                                                                    [100%]
5 passed in 0.03s
```

## 纯加法验证：`StepResult(` / `WorkerContext(` 全包 grep

### `StepResult(`（全部 ≤3 位置参数或关键字构造，零改动）

- `fetcher/tests/test_control_loop.py:177` `StepResult(solved, f"fake#{self.calls}")`
- `fetcher/tests/test_control_loop.py:189` `StepResult(r.outcome is Outcome.OK, r.detail, r.data)`（3 位置）
- `fetcher/tests/test_control_loop.py:356` `StepResult(False, "stop")`
- `fetcher/fetcher/strategy/strategies.py:38` 关键字 `StepResult(solved=..., detail=..., data=...)`
- `strategies.py:104/108/110/112/125/127/129/132/134/135` 均 ≤3 位置参数
- `strategies.py:164` 关键字构造

最严的兼容点是 3 位置参数构造（test_control_loop.py:189、strategies.py:110/112/135），
新字段放第四且带默认值，不受影响；该兼容性由
`test_positional_three_args_still_works` 锁定。

### `WorkerContext(`（全部关键字构造，零改动）

- 测试侧：test_contact_task.py:98、test_plugin_extension.py:108/126/142/166/256/280/297、
  test_yiwugo.py:142/163/178/249/312/357/375、test_detectors.py:73、
  test_daemon_task.py:152/312、test_madeinchina.py:223、test_control_loop.py:204
- 生产侧：`fetcher/fetcher/control/engine.py:149`、`fetcher/fetcher/control/loop.py:67`

全部为关键字参数构造，新增带 default_factory 的字段不影响任何既有调用点。

## 全量测试

```
$ cd fetcher && python -m pytest tests -x -q
236 passed, 2 subtests passed in 8.24s
```

## 改动文件

- `fetcher/fetcher/strategy/base.py`（+5 行：字段 + 语义注释）
- `fetcher/fetcher/core/context.py`（+5 行：字段 + 语义注释）
- `fetcher/tests/test_cooldown_contract.py`（新增，5 个用例）

## 疑虑

无。两处均为纯加法；既有调用点 grep 复核全部兼容；未触碰任何策略/loop/atom 代码。
