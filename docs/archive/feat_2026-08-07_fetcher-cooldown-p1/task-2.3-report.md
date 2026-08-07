# Step 2.3 report — 冷却迁移 loop 侧单测

> 对应 brief：task-2.3-brief.md（范围修正后只做 loop 侧 ③④⑤）。
> 被测对象：`fetcher/fetcher/control/loop.py` 的 `_cooldown`（:108-122）、
> 4 处等待点（:152 / :215 / :226 / :260）、`_process_item` cooldown 消费（:410-412）。

## 用例清单（新增 `fetcher/tests/test_cooldown.py`，6 用例 3 组）

### 组 1：chokepoint 单测（CooldownChokepointTest）

| 用例 | 覆盖点 |
|---|---|
| `test_silent_path_writes_deadline_and_returns_false` | 静默路径（prefix=None → ctx.wait）：`cooldown_until["ut_silent"]` ≈ time.time()+0.05（delta=1.0），且是唯一写入的 reason；正常等完返回 False |
| `test_countdown_path_stop_interrupt_returns_true_fast` | 倒计时路径（prefix="倒计时" → wait_countdown）：seconds=30，Timer(0.1) 置 stop → 返回 True，elapsed ∈ [0.05, 5.0)（远小于 30，且非立即返回快路径）；cooldown_until 同样登记 ≈ time.time()+30 |

两条展示路径各覆盖一次（静默 / 倒计时）。

### 组 2：`_process_item` 策略冷却集成（StrategyCooldownIntegrationTest）

CrawlLoop 联跑（临时 sqlite + 真 threading.Event + FakePage/MockBrowserManager），
spy `_cooldown`（记录参数、调用真实实现，不 mock 被测方法本身）：

| 用例 | 覆盖点 |
|---|---|
| `test_strategy_cooldown_via_chokepoint_then_retry_success` | 首次 fetch 自报 blocked → 假策略输出 `StepResult(solved=True, cooldown=0.3)` → spy 断言恰好 1 次 `("strategy:cool", 0.3, prefix=None)`；真实等待过（elapsed ≥ 0.25）；随后重试 fetch 成功（fetches=2、succeeded=["item1"]、无 giveup）；`cooldown_until["strategy:cool"]` ≈ 写入时刻+0.3 |
| `test_strategy_cooldown_interrupted_by_stop_is_stop_terminal` | cooldown=30，Timer(0.15) 置 stop → loop <5s 退出；「stop 终局」语义：item1 未成功未放弃、item2 未被认领（fetches=1），spy 记录到 30s 冷却调用 |

### 组 3：4 处等待点触发（WaitPointsTest）

| 用例 | 覆盖点 |
|---|---|
| `test_batch_sample_periodic_rest_via_chokepoint` | 小参数联跑（batch_num=1、max_batches=2、batch_rest=0.2、sample_min/max=0.05/0.10、rest_every=1、rest_min/max=0.06/0.12），2 个 item 全成功。spy reason 断言：`batch_rest`×1（∈[0.18,0.22]，prefix="批次休息"）、`sample_interval`×2（∈[0.05,0.10]，prefix=None）、`periodic_rest`×2（∈[0.06,0.12]，prefix="长休息"）；三类 reason 均登记入 cooldown_until |
| `test_launch_backoff_via_chokepoint` | launch 恒失败的 MockBrowserManager + ip_retry=2：首次失败即进 `_cooldown(30.0, "launch_backoff", prefix="启动退避")`（backoff=min(30×1,120)）；Timer(0.15) 置 stop → UserInterrupted 路径 <5s 退出、未二次 launch。reason 级 + 时长/前缀断言，未等满 30s（避免慢测试） |

launch_backoff 按 brief 许可做 reason 级断言（附 stop 中断快速退出证明真实走了 chokepoint）。

## 防假阳性证据（定向破坏 → 变红 → 还原）

### 破坏 A：删除 cooldown_until 写入

```python
# loop.py:116 替换为
pass  # SABOTAGE-A: 不写 cooldown_until
```

```
$ cd fetcher && python -m pytest tests/test_cooldown.py -q
FAILED tests/test_cooldown.py::CooldownChokepointTest::test_countdown_path_stop_interrupt_returns_true_fast
FAILED tests/test_cooldown.py::CooldownChokepointTest::test_silent_path_writes_deadline_and_returns_false
FAILED tests/test_cooldown.py::StrategyCooldownIntegrationTest::test_strategy_cooldown_via_chokepoint_then_retry_success
FAILED tests/test_cooldown.py::WaitPointsTest::test_batch_sample_periodic_rest_via_chokepoint
FAILED tests/test_cooldown.py::WaitPointsTest::test_launch_backoff_via_chokepoint
5 failed, 1 passed in 1.40s
```

### 破坏 B：静默路径不等待、不查 stop

```python
# loop.py:117-118 替换为
if prefix is None:
    return False  # SABOTAGE-B: 静默路径不等待不查 stop
```

```
$ cd fetcher && python -m pytest tests/test_cooldown.py -q
FAILED tests/test_cooldown.py::StrategyCooldownIntegrationTest::test_strategy_cooldown_interrupted_by_stop_is_stop_terminal
FAILED tests/test_cooldown.py::StrategyCooldownIntegrationTest::test_strategy_cooldown_via_chokepoint_then_retry_success
2 failed, 4 passed in 0.72s
```

（2a 红在「真实等待过 elapsed≥0.25」断言，2b 红在 stop 终局断言——等待与中断检查均被锁定。）

两轮破坏后均 `git checkout -- fetcher/fetcher/control/loop.py` 还原，
`git status --short` 确认 loop.py 无残留改动。

## 全量测试结果

```
$ cd fetcher && python -m pytest tests -x -q
249 passed, 2 subtests passed in 9.58s
```

## 改动文件

- 新增 `fetcher/tests/test_cooldown.py`（唯一代码改动；loop.py / strategies.py 未动）
- 新增本报告 `docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.3-report.md`

## 疑虑

- `test_strategy_cooldown_via_chokepoint_then_retry_success` 原断言「截止时间在
  未来」存在时序竞争（run 结束晚于 0.3s 截止点即假失败），已改为
  `assertAlmostEqual(deadline, time.time()+0.3, delta=1.0)` 的近似断言，
  语义不变（验证 ≈ 写入时刻+seconds）。
- 组 3 的时长区间断言依赖 random.uniform，理论上界/下界是闭区间取值，
  断言用 >=/<= 无边界抖动风险。
- 未发现被测代码 bug。
