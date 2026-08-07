# Step 2.2 report — DaemonTaskProxy 单测

> 被测对象：Step 2.1 产出 `fetcher/fetcher/control/daemon_task.py`（commit f6034dd）。
> 本 Step 只新增 `fetcher/tests/test_daemon_task.py`，未改被测代码。

## 实现内容

新增 `fetcher/tests/test_daemon_task.py`（5 个用例，unittest 风格，与现有测试一致）：

- 基建：`FakeInnerTask`（可编程假 inner，`acquire_item` 被调到即 AssertionError，防 proxy 偷走 inner 认领路径的假阳性）+ `FakePage`/`MockBrowserManager`（沿用 test_control_loop.py 模式）+ 临时 sqlite（`ShopDB` + WAL）。
- ctx 装配：用例 1–4 用 `store=None` 的轻量 ctx，走 `db_factory` 注入点（proxy 按线程自建连接）；用例 5 用每 worker 独立 `IdentityStore(ShopDB(...))`，走生产 Engine 的 `ctx.store.db` 路径——两条 DB 接入路径都被覆盖。
- 超时注入：模块级 `daemon_task._WAIT_TIMEOUT` 直接改写 + `addCleanup` 还原（用例 3、5，0.05s 自醒）。

### 用例对照

1. **有货直取**（`test_acquire_claims_pending_work_item`）：预置 2 行 pending work_items → 返回 dict 含 `id` + `domain`/`name`/`url` 三键，最老 pending 先领；行变 `claimed`、`claimed_by="w3"`（wid=3）；`ctx.state["daemon_work_item_id"]` 已记录。
2. **空队列自动补货**（`test_acquire_auto_topup_when_queue_empty`）：shops 2 家 pending、work_items 空 → acquire 自动 top-up 后返回；两家 shops 均 `in_progress`；work_items 一行 claimed 一行 pending。
3. **stop 退出**（`test_acquire_returns_none_after_stop`）：库全空，`_WAIT_TIMEOUT=0.05`，Timer 0.3s 后置 stop → 返回 None；断言 elapsed ≥ 0.25（证明确实阻塞等过，非空队列快路径）且 < 5s（自醒及时）。
4. **终态钩子**（`test_terminal_hooks_finish_work_item`）：`on_success` → done（透传 inner 返回值，state pop）；`on_giveup` → failed + `result_json={"reason","kind"}`；重复 finish 幂等（二次 on_giveup 带不同 reason 不落库、不改首次 result_json）；stray finish 不误伤其他 worker 认领中的 item。
5. **CrawlLoop 联跑**（`test_crawl_loop_two_workers_shared_proxy`）：2 个真实 worker 线程各跑一个 `CrawlLoop`、共享一个 proxy 实例；6 个 work_item 全成功后监视线程置 stop，两 loop 均正常退出（无异常、线程不残留）；终态全 done 无 claimed 残留；两 worker 成功 domain 合集 = 全集且无重复（不串 item）；各 worker stats["done"] 与其成功明细一致、总和 = 6。

## 防假阳性证据（对被测代码临时破坏 → 变红 → 还原）

三轮破坏均用 `git checkout -- fetcher/fetcher/control/daemon_task.py` 还原，还原后 `git status` 确认干净。

**破坏 A**：删掉 acquire_item 里 `ctx.state[_STATE_KEY] = item["id"]`。
`cd fetcher && python -m pytest tests/test_daemon_task.py -q`：

```
FAILED tests/test_daemon_task.py::AcquireItemTest::test_acquire_claims_pending_work_item
FAILED tests/test_daemon_task.py::TerminalHookTest::test_terminal_hooks_finish_work_item
FAILED tests/test_daemon_task.py::CrawlLoopIntegrationTest::test_crawl_loop_two_workers_shared_proxy
3 failed, 2 passed in 15.51s
```

用例 1/4/5 红（用例 5 终态断言 `{'claimed': 6} != {'done': 6}`），用例 2/3 保持绿——破坏定向，非全局坍塌。

**破坏 B**：top-up 命中后 `continue` 改为 `return None`：

```
FAILED tests/test_daemon_task.py::AcquireItemTest::test_acquire_auto_topup_when_queue_empty
1 failed, 4 passed in 0.50s
```

只用例 2 红。

**破坏 C**：`wait` 后 stop 分支 `return None` 改为返回假 item dict：

```
FAILED tests/test_daemon_task.py::AcquireItemTest::test_acquire_returns_none_after_stop
1 failed, 4 passed in 0.48s
```

只用例 3 红。

## 测试结果

- 聚焦：`python -m pytest tests/test_daemon_task.py -q` → **5 passed in 0.51s**（破坏验证还原后）。
- 全量：`cd fetcher && python -m pytest tests -x -q` → **226 passed, 2 subtests passed in 7.27s**，无 warnings summary，输出干净。

## 改动的文件

- `fetcher/tests/test_daemon_task.py`（新增，唯一代码改动）
- `docs/feat_2026-08-07_fetcher-daemon-p0/task-2.2-report.md`（本文件）

## 自查发现

- 用例 5 监视循环有 15s deadline 兜底 + `t.join(timeout=10)` + `is_alive` 断言，即使 regression 导致 worker 卡住也是「失败」而非「挂死 CI」。
- 破坏 A 的用例 5 变红需等监视 deadline（约 15s），是三组破坏验证里最慢的一轮，属预期。
- 用例 2 的 ctx 从不置 stop：任何导致「top-up 后拿不到货」的 regression 在该用例下会阻塞在 condvar wait——有 `_WAIT_TIMEOUT` 自醒但不会退出。破坏 B 验证时特意选了「补到货但直接 return None」的快速失败路径规避此点；正式代码路径无此风险。

## 疑虑

- 无用例 5 断言「两个 worker 都至少拿到一个 item」：调度竞争下不保证（理论上一个 worker 可能领完全部），断言了合集无重复 + 各自 stats 与明细一致，已覆盖「不串 item」的可判定语义。
- `prepare()` 未在本 Step 用例清单内，未测（brief 未要求）。
