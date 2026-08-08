# Task 1.2 Report — 冷却表改建（键改 site）+ eligible_queues + claim 过滤与 condvar timeout

> 分支：`feat/multiqueue-p3` ｜ 状态：DONE ｜ TDD 全流程完成，全量 336 passed（基线 319 + 新增 17）

## 实现摘要

### 1. `WorkerContext.cooldown_until` 键语义改 site（core/context.py）

- docstring 更新：「site 注册名 → 到期时刻」；删除 P1「只写不读」遗留注释，替换为 site 语义说明
- 新增字段 `resources: set[str]`，默认 `{"channel", "browser"}`（与 SPEC §4.2 BrowserConsumer 一致）

### 2. `eligible_queues` + `condvar_timeout` 纯函数（新建 control/queue_router.py）

- `QueueSpec` dataclass：三字段 queue / site / requires
- `eligible_queues(registry, ctx, now) -> list[str]`：资源满足 ∧ 冷却到期，返回队列名列表（按注册表顺序），纯函数无副作用
- `condvar_timeout(cooldown_until, site, now, cap=30.0) -> float`：冷却中 → min(剩余, cap)；不在冷却 → cap；返回值总是 > 0

### 3. `CrawlLoop._cooldown` 键改 site（control/loop.py）

- 登记逻辑：`active_site = ctx.state.get("active_site")` → 有则 `cooldown_until[active_site] = time.time() + seconds`，无则不登记
- `reason` 参数保留，仅用于日志/展示
- 等待行为不变（原地等待）

### 4. `DaemonTaskProxy.acquire_item` 冷却过滤 + condvar timeout + active_site（control/daemon_task.py）

- claim 前查冷却：`now < ctx.cooldown_until.get(self._site, 0)` → 不 claim 不 topup，直接进 condvar wait（timeout 经 condvar_timeout 计算）
- claim 成功后在 `ctx.state["active_site"] = self._site`
- 其余（topup notify_all、stop 检查、_WAIT_TIMEOUT 兜底）保持现状

## 测试列表

### test_queue_router.py（新建，12 个用例）

| 测试 | 覆盖点 |
|---|---|
| `test_construction_and_fields` | QueueSpec 构造与字段访问 |
| `test_all_eligible_with_no_cooldown` | 无冷却时全队列可见 |
| `test_cooldown_filters_site_queues` | 用例 1：site A 冷却中 → 该 site 队列被滤 |
| `test_resource_filtering` | 用例 2：requires 超 resources → 被滤 |
| `test_expiry_recovery` | 用例 3：now 推进到冷却到期 → 恢复可见 |
| `test_empty_registry` | 空注册表 → 空列表 |
| `test_empty_resources_still_matches_empty_requires` | 空 resources 仍可匹配空 requires 队列 |
| `test_not_in_cooldown_returns_cap` | 不在冷却 → cap=30 |
| `test_in_cooldown_returns_min_of_remaining_and_cap` | 用例 4：冷却中 → min(剩余, 30) |
| `test_custom_cap` | 自定义 cap 生效 |
| `test_very_small_remaining_returns_positive` | 剩余 0.01s → 返回 0.01（>0） |
| `test_exactly_at_deadline_returns_cap` | now==到期 → cap |

### test_cooldown.py（适配 7 处 + 新增 2 个用例）

| 测试 | 变更 |
|---|---|
| `test_silent_path_writes_deadline_and_returns_false` | reason 键断言 → 空 dict 断言（无 active_site） |
| `test_countdown_path_stop_interrupt_returns_true_fast` | reason 键断言 → 空 dict 断言 |
| `test_strategy_cooldown_via_chokepoint_then_retry_success` | cooldown_until["strategy:cool"] 断言 → 空 dict |
| `test_batch_sample_periodic_rest_via_chokepoint` | 三类 reason 均登记 → 空 dict + reason spy 证据 |
| `test_launch_backoff_via_chokepoint` | cooldown_until 含 "launch_backoff" → 空 dict |
| `test_site_key_when_active_site_set` | **新增**：设 active_site → 登记 site 键 |
| `test_no_registration_without_active_site` | **新增**：未设 active_site → 不登记 |

### test_daemon_task.py（新增 3 个用例）

| 测试 | 覆盖点 |
|---|---|
| `test_cooldown_blocks_claim` | 用例 5：冷却中 → acquire 阻塞，不 claim 不 topup |
| `test_cooldown_expired_allows_claim` | 用例 6：冷却到期 → 正常 claim |
| `test_active_site_set_on_claim` | 用例 7：claim 成功后 state["active_site"] 正确 |

## TDD 证据

### RED（实现前）

```
$ python -m pytest tests/test_queue_router.py tests/test_cooldown.py tests/test_daemon_task.py -q
ERROR collecting tests/test_queue_router.py — ModuleNotFoundError: No module named 'fetcher.control.queue_router'
FAILED tests/test_cooldown.py::CooldownChokepointTest::test_countdown_path_stop_interrupt_returns_true_fast
FAILED tests/test_cooldown.py::CooldownChokepointTest::test_no_registration_without_active_site
FAILED tests/test_cooldown.py::CooldownChokepointTest::test_silent_path_writes_deadline_and_returns_false
FAILED tests/test_cooldown.py::CooldownChokepointTest::test_site_key_when_active_site_set
FAILED tests/test_cooldown.py::StrategyCooldownIntegrationTest::test_strategy_cooldown_via_chokepoint_then_retry_success
FAILED tests/test_cooldown.py::WaitPointsTest::test_batch_sample_periodic_rest_via_chokepoint
FAILED tests/test_cooldown.py::WaitPointsTest::test_launch_backoff_via_chokepoint
FAILED tests/test_daemon_task.py::CooldownFilterTest::test_active_site_set_on_claim
FAILED tests/test_daemon_task.py::CooldownFilterTest::test_cooldown_blocks_claim
9 failed, 7 passed in 12.10s
```

失败全部预期：queue_router 模块不存在（ImportError）、cooldown_until 仍按 reason 键写入（site 键断言失败）、daemon 无冷却过滤（claim 立即成功）。

### GREEN（实现后）

```
$ python -m pytest tests/test_queue_router.py tests/test_cooldown.py tests/test_daemon_task.py -q
28 passed in 12.14s
```

### 全量无回归

```
$ cd fetcher && python -m pytest tests -q
336 passed, 2 subtests passed in 24.64s   （基线 319 + 新增 17）
```

## 改动文件

- `fetcher/fetcher/core/context.py`：cooldown_until docstring 更新 + 新增 resources 字段
- `fetcher/fetcher/control/queue_router.py`（**新建**）：QueueSpec / eligible_queues / condvar_timeout
- `fetcher/fetcher/control/loop.py`：_cooldown 键改 site（active_site 有则登记，无则跳过）
- `fetcher/fetcher/control/daemon_task.py`：acquire_item 增加冷却过滤、condvar_timeout、active_site 写入
- `fetcher/tests/test_queue_router.py`（**新建**）：12 个纯函数用例
- `fetcher/tests/test_cooldown.py`：7 处断言适配 + 2 个新用例
- `fetcher/tests/test_daemon_task.py`：新增 CooldownFilterTest 类（3 个用例）

## 自查发现

- **等待行为未改**：loop 原地等待、daemon_task queue-empty 路径仍用 _WAIT_TIMEOUT（30s 兜底），仅 cooldown-wait 路径改用 condvar_timeout。让出型行为是 Step 1.3 内容。
- **active_site 设置时机**：仅 daemon_task claim 成功后才设，CLI 路径 / CrawlLoop 直接调用路径不设。这与 brief「acquire 前的原地型路径——launch_backoff——active_site 未设置，天然不登记」一致。
- **cooldown_until 语义变更影响面**：既有 test_cooldown.py 全部 5 个 wait-point 测试的 cooldown_until 断言均改为空（因这些路径无 active_site）。不登记意味着 CLI 路径的等待无法被 daemon 调度器查询——这是刻意设计：site 键语义只服务于 daemon 消费者的跨队列冷却感知，CLI 路径本来就不该被调度器看到。
- **condvar_timeout 与 _WAIT_TIMEOUT 分离**：cooldown wait 用 condvar_timeout（冷却感知），queue-empty wait 仍用 _WAIT_TIMEOUT（30s 兜底）。若 Step 1.3 需要统一，届时收敛不迟。
- 他人未提交改动（platform/*、vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/）未触碰。
