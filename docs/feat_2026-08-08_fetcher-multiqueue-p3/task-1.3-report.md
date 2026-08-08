# Task 1.3 Report — `_cooldown` 让出型改造（节奏冷却登记即返回）

> 来源：PLAN.md P3-1 Step 1.3 · SPEC §3.3 · 主 Agent 裁定 1/3/5
> 分支：feat/multiqueue-p3

## 实现摘要

把 `CrawlLoop._cooldown` 拆成两种语义：

| 语义 | `yield_` | 行为 | 调用点 |
|---|---|---|---|
| **让出型** | `True` | 登记 `cooldown_until[site]` 后立即返回 False（不等待）。等待由 acquire_item 的 condvar timeout 执行 | batch_rest, sample_interval, periodic_rest |
| **原地型** | `False`（默认） | 登记 + 原地等待（可被 stop 中断） | launch_backoff, 策略冷却 |

### 改动文件

- `fetcher/control/loop.py`：`_cooldown` 新增 `yield_: bool = False` 参数；三处节奏调用点传 `yield_=True`；两处原地调用点加注释

### 逻辑路径

```
_cooldown(seconds, reason, prefix, yield_=False)
  ├─ active_site 有值 → cooldown_until[site] = now + seconds
  ├─ yield_=True → return False               ← 让出型：立即返回
  ├─ prefix is None → ctx.wait(seconds)        ← 原地型：静默等待
  └─ prefix 非空 → wait_countdown(...)          ← 原地型：倒计时等待
```

## 测试列表

### 新增测试（5 个，test_cooldown.py YieldCooldownTest）

| 测试 | 覆盖 |
|---|---|
| `test_yield_returns_false_immediately` | yield_=True 立即返回 False（<0.5s），不等待 30s |
| `test_yield_registers_site_key_and_skips_without_active_site` | active_site 设/未设时的登记行为 |
| `test_no_yield_keeps_waiting` | yield_=False（默认）保持原地等待，可被 stop 中断 |
| `test_yield_silent_path_no_wait_countdown` | yield_=True 即使传 prefix 也不走 wait_countdown |
| `test_three_rhythm_sites_pass_yield_true` | batch_rest/sample_interval/periodic_rest 传 yield_=True |

### 既有测试适配（2 处）

- `spy_cooldown` / `spy_cooldown_full`：接受 `**kwargs` 转发，兼容新增的 `yield_` 参数
- `WaitPointsTest.test_batch_sample_periodic_rest_via_chokepoint`：无需修改（仍 passes，spy 捕获参数不受影响）

### 全量结果

```
cd fetcher && python -m pytest tests -q
341 passed, 2 subtests passed in 27.10s
```

基线 336 → 341（+5 新测试）。

## TDD 证据（RED→GREEN）

### RED
```
$ python -m pytest tests/test_cooldown.py -q
.......FFFF..   [100%]
4 failed:
  - TypeError: _cooldown() got an unexpected keyword argument 'yield_'
  - AssertionError: 'batch_rest' not found (yield_ not passed)
```

### GREEN（实现后）
```
$ python -m pytest tests/test_cooldown.py -q
.............   [100%]
13 passed in 11.11s
```

## 冒烟证据

- 路径：`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/`
  - `smoke-output.txt`：daemon 输出（直连，1 worker，2 种子店铺）
  - `smoke-analysis.md`：时间戳间隔分析 + 结构证据
- 命令：`python -m fetcher daemon --db /tmp/smoke_p3_13.db --workers 1 --limit 2 -n 1 --batch-rest 10 ...`
- 环境：直连（无代理），CloakBrowser 1 席
- 结果：
  - daemon 正常启动/运行/退出（总耗时 ~10s）
  - 滑块墙必现（直连环境噪声），首 item 失败 → abort
  - 总运行时间无异常长间隙（若原地型 sample_interval 需 ≥1s 等待，改造后无）
  - active_site 正常设置，cooldown_until 写入路径就绪
  - 节奏冷却触发路径因未走到成功路径而未演示——由单元测试完整覆盖
- 后续复跑：首运行残留浏览器进程占用 CloakBrowser 席位 → 复跑挂起（环境噪声，与改动无关）

## 自查

1. 三处节奏调用点全部传 `yield_=True`（grep 复核 ✓）
2. 两处原地调用点保持默认 + 注释（launch_backoff: "装配中途"；策略冷却: "P3-3 改让出"）
3. `_cooldown` docstring 已同步让出型/原地型语义 + 展示路径说明
4. 未动 `db.py`、`queue_router.py`、`context.py`（Step 1.2 已完成）
5. 单队列行为等价：等待从 loop 内移到 condvar timeout，总时长语义一致

## Git Commit

```
feat(multiqueue-p3): _cooldown 让出型改造——节奏冷却登记即返回
```

---

## Fix Round 1（2026-08-08 review 修复）

### F1 — 冒烟证据缺口：成功路径集成测试（已修复）

**问题**：冒烟因滑块墙 abort 未触发节奏冷却，单队列行为等价缺少运行时证据。

**修复**：补 `YieldIntegrationWithProxyTest`（test_cooldown.py 用例 4），
DaemonTaskProxy + CrawlLoop 集成，2 个成功 item，假基建模式（不依赖真实浏览器）：
- 断言 item1 完成后 sample_interval 登记 site 键（cooldown_until["1688"]）
- 断言 item2 的 condvar 等待发生在 acquire 而非 loop 内（无 ctx.wait 调用）
- 断言总耗时反映 condvar 等待（>= 0.25s，sample_min=0.3）
- 断言 2 个 work_items 标记为 done

**测试**：`python -m pytest tests/test_cooldown.py::YieldIntegrationWithProxyTest -v` → 1 passed

### F2 — 跨文件注释检查（已核实）

- `core/context.py:113` cooldown_until 注释：已是最新（site 注册名语义），无残留 reason 描述 ✓
- `strategy/strategies.py:119` SwapIP 注释：「P3 重议」→「P3-3 router 接 release 后改让出」（已同步）

### F3 — 测试缺 negative 断言（已修复）

- `test_strategy_cooldown_via_chokepoint_then_retry_success`：改用 `spy_cooldown_full`，断言 `yield_=False`
- `test_strategy_cooldown_interrupted_by_stop_is_stop_terminal`：同上
- `test_launch_backoff_via_chokepoint`：改用 `spy_cooldown_full`，断言 `yield_=False`
- `test_three_rhythm_sites_pass_yield_true`：补条件断言（launch_backoff/策略冷却如触发必须为 False）

### F4 — smoke-analysis.md 参数调整说明（已补）

在「环境」段补一句话说明：小参数快速收工，避免直连滑块墙下长耗。

### F5 — 让出型调用点后的死分支加注释（已补）

loop.py 三处 `yield_=True` 调用点的 `return self.stats` 分支添加 `# yield_=True 恒返回 False，此分支不可达；# stop 由 acquire_item 的 condvar 处理`

### F6 — 推测性声明改写（已修）

smoke-analysis.md 中「若为原地型…会有至少 5s+ 的额外等待」改为条件式表述，
明确说明节奏冷却未在 daemon 真实触发，等价性由集成测试覆盖。

### Fix 全量测试

```
cd fetcher && python -m pytest tests -q
342 passed, 2 subtests passed in 28.85s
```

### Fix Commit

```
feat(multiqueue-p3): fix F1-F6 — 让出型集成测试 + 注释/断言补全
```
