# Step 2.2 brief — loop chokepoint + 4 处等待点收敛

> 来源：PLAN.md Phase 2 Step 2.2 + SPEC §3.3。本文本是你的需求唯一来源。

## 内容

改 `fetcher/fetcher/control/loop.py`（只动这一个文件）：

### 1. 新增 `_cooldown(seconds, reason)` chokepoint

SPEC §3.3 的契约：唯一等待执行点。职责：
- 写 `self.ctx.cooldown_until[reason] = time.time() + seconds`（WorkerContext 的该字段已在 Step 1.2 落地）；
- 执行可中断等待，返回 True=被 stop 中断；
- **保留现状两种等待展示路径**：长等待（批次休息/周期长休/启动退避，现状走 `wait_countdown` 带秒级倒计时状态行）与短等待（样本间隔，现状走 `ctx.wait` 无倒计时）的展示差异逐字保留——chokepoint 内部按调用方传的展示方式分支（参数或两个内部路径，你读现状后定，report 说明）。`wait_countdown`（board.py:134-148）保留不动，由 chokepoint 内部调用。

### 2. 4 处既有等待点改经 chokepoint（时长公式逐字保留）

| 位置（现状行号，以你读到的为准） | reason | 时长公式（逐字保留） | 展示路径 |
|---|---|---|---|
| :129-137 批次休息 | `"batch_rest"` | `random.uniform(cfg.batch_rest*0.9, cfg.batch_rest*1.1)` | 倒计时 |
| :195-200 样本间隔 | `"sample_interval"` | `uniform(cfg.sample_min + wid*1.5, cfg.sample_max + wid*2.5)` | 静默（ctx.wait 口径） |
| :203-213 周期长休 | `"periodic_rest"` | `uniform(cfg.rest_min, cfg.rest_max)` | 倒计时 |
| :243-249 启动退避 | `"launch_backoff"` | `min(30*attempt, 120)` | 倒计时 |

注意各点的现状细节（中断后的处理、日志文案、状态行内容）逐字保留——diff 对照时除了「等待调用换成 chokepoint + 时长计算可能挪成小函数」外不应有其他行为差异。

### 3. `_process_item` 消费 `step.cooldown`

策略执行后（现状 :386-394 一带）：`step.cooldown` 非空时调 `self._cooldown(step.cooldown, f"strategy:{name}")`；被中断则按现状 stop 路径退出（与现状策略内 `ctx.wait` 被中断返回 SKIPPED→「用户中断」的终局一致——读码确认现状中断后 loop 的走向，对齐它）。策略自己的 log/detail 输出（Step 2.1 已保留）照旧经现状 :393-394 的日志行打出。

### 4. 顺手清理（review 已记的 deferred minor，可选）

`BlockRestStrategy.__init__` 的 `self._params = params` 残留（run() 不读）可删——若删，属于 strategies.py 的一行改动，允许，report 说明。

## 验收

- [ ] loop.py 内 `ctx.wait`/`wait_countdown` 只出现在 `_cooldown` 一处（grep 证据）
- [ ] 4 处等待的时长公式与迁移前逐字一致（report 附 diff 对照说明）
- [ ] `_process_item` 正确消费 step.cooldown，中断语义与现状终局一致
- [ ] 全量 `cd fetcher && python -m pytest tests -x -q` 无回归（若有断言旧等待路径的既有测试失败，按旧契约处理：更新并逐条说明）

## 约束

- 只动 `control/loop.py`（+ 可选的 strategies.py 一行清理 + 必要测试更新）。
- 不碰 board.py、engine.py、daemon_task.py、policy.py、atoms/。
- 本 Step 不做运行冒烟（Phase 3 做）。
