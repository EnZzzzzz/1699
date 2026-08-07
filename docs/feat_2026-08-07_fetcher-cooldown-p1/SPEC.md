# SPEC — 冷却策略迁移（P1）

> 上游设计：docs/scheduler-architecture.md（§6 冷却策略表、§10 落地路线 P1）
> 前置：daemon P0 已合并（docs/archive/feat_2026-08-07_fetcher-daemon-p0/）
> 本文档是 P1 的需求与设计唯一来源；评审通过后相对稳定，变更在文末「变更记录」追加。

## 1. 背景与目标

P0 把 daemon 骨架立起来了，但所有等待仍内联在执行路径里：loop 4 处、策略层 N 处各自为政，没有统一的「冷却到什么时候」状态可查询——多队列调度器（P3）拿不到冷却截止时间，就无法做「冷却期间去干别的队列」。

**P1 的目标：时长计算策略化 + 等待执行收敛到单一 chokepoint，行为完全等价。**

- 策略不再自己执行冷却等待，改为**输出冷却时长**（`StepResult.cooldown`）；
- `CrawlLoop` 新增唯一等待执行点 `_cooldown(seconds, reason)`，loop 自身的 4 处等待与策略上报的冷却全部经它执行；
- 所有时长计算公式**逐字保留**，全部等待保持 stop 可中断；
- 本阶段**不做**多队列调度、不做 item 挂起/让出——chokepoint 当前实现仍是「就地等待」，但契约（策略只输出时长、loop 唯一执行等待）让 P3 只需替换 chokepoint 实现即可做让出。

验收口径：**同一批次总耗时、请求节奏分布与旧实现相当**（时长公式逐字保留 + 可中断语义保留，结构性保证等价，冒烟对比佐证）。

## 2. 范围与非目标

### 2.1 范围（P1 做）

1. 契约层：`StepResult` 加 `cooldown: float | None` 字段（秒）；`PolicyDecision` 加同名透传字段；`WorkerContext` 加 `cooldown_until: dict[str, float]` 暂存（P3 的状态钩子，本阶段只写不读）。
2. 策略迁移（`strategy/strategies.py`）：`SleepStrategy` / `BackoffSleepStrategy` / `BlockRestStrategy` 的 run() 不再触发 `ctx.wait`，时长算好放进 `StepResult.cooldown` 返回。
3. loop 收敛（`control/loop.py`）：新增 `_cooldown(seconds, reason)` chokepoint；4 处既有等待点（批次休息 :129-137、样本间隔 :195-200、周期长休 :203-213、启动退避 :243-249）全部改经 chokepoint；`_process_item` 在 `step.cooldown` 非空时调 chokepoint 执行等待。
4. 单元测试 + 等价性冒烟。

### 2.2 非目标（P1 明确不做）

- **SwapIPStrategy 的内部等待不迁移**（裁定见 §4 假设 1）：它的 600~900s 等待夹在「第一次 relaunch → 等青果轮换 → 第二次 relaunch」算法中间（strategies.py:114-135），外移需要把策略拆成跨 loop 迭代的两阶段状态机，且只有配合 P3 的 item 挂起机制才有收益。P1 保留现状并在代码注释中标注为例外。
- **WaitHumanVerify/Login 的交互等待**不迁移（轮询人工操作，非冷却）。
- **SolveSlider 的亚秒 `time.sleep`**（atoms/slider.py，拟人轨迹）不迁移。
- **Engine 启动错开 sleep**（engine.py:201，主线程启动期行为）不动。
- 多队列调度、work_items 冷却态、chokepoint 让出实现：P3。
- `atoms/sleep.py` 的 Sleep/BackoffSleep 原子保留不删（旧路径与其他调用方兼容）。
- 平台侧、identity 模型、daemon_task.py 均不动。

## 3. 关键设计

### 3.1 契约变更

```python
# strategy/base.py
@dataclass
class StepResult:
    solved: bool
    detail: str = ""
    data: dict = field(default_factory=dict)
    cooldown: float | None = None   # 秒；非空=调用方（loop）应经 chokepoint 执行该冷却
```

- 语义：**策略输出冷却、不执行冷却**。`cooldown` 非空时策略保证自己没有为这段时长等待过（调用方执行一次，不重复）。
- `PolicyDecision`（policy.py:70-77）加 `cooldown: float | None = None` 透传字段；`Policy.decide` 不决策时长，只搬运（decide 当前不接触策略执行结果——实际透传点在 loop：`_process_item` 拿到 `step.cooldown` 直接消费。**若 decide 链路用不上该字段则不加，以读码核实为准，report 说明**）。
- `WorkerContext.cooldown_until: dict[str, float]`：chokepoint 每次执行等待时写入 `cooldown_until[reason] = time.time() + seconds`。P0/P1 单队列下无人读它，是 P3 调度器的查询接口。

### 3.2 策略迁移（逐个）

| 策略 | 现状 | 迁移后 |
|---|---|---|
| `SleepStrategy`（:41） | Sleep 原子内 `ctx.wait(t)`（对数正态时长，params min/max） | run() 用同一分布算出 t，返回 `StepResult(True, cooldown=t)`，不调原子 |
| `BackoffSleepStrategy`（:46-50） | BackoffSleep 原子 `ctx.wait(min(30*attempt,180))` | run() 算 `min(30*attempt,180)`（attempt 来源与现子一致：policy decide 给的 attempt——读码确认其传递路径），返回 cooldown |
| `BlockRestStrategy`（:53-67） | run 时取 config block_rest_min/max → Sleep 原子 wait | 时长口径改为 `random.uniform(block_rest_min, block_rest_max)`（**注意**：现状经 Sleep 原子是对数正态 clamp 到 [min,max]——迁移时必须保留同一分布，读 atoms/sleep.py 确认分布公式后逐字复刻，report 给出公式对照），返回 cooldown，保留现有 log 行 |
| `SwapIPStrategy`（:86-135） | 内部 ctx.wait/WaitHumanLogin | **不动**（§2.2 例外），类 docstring 加一行「冷却例外」标注 |

### 3.3 loop chokepoint

```python
# control/loop.py
def _cooldown(self, seconds: float, reason: str) -> bool:
    """唯一等待执行点：登记冷却截止时间 + 可中断等待。返回 True=被 stop 中断。"""
    self.ctx.cooldown_until[reason] = time.time() + seconds
    ...  # 现状的 wait_countdown / ctx.wait 逻辑收拢到这里
```

- 4 处既有等待点改为：算时长（公式逐字保留，含 wid 错峰、±10% 浮动）→ `self._cooldown(t, reason)`。reason 取值：`"batch_rest" / "sample_interval" / "periodic_rest" / "launch_backoff"`；策略冷却的 reason 用 `f"strategy:{strategy.name}"`。
- `_process_item` 策略执行后：`if step.cooldown: interrupted = self._cooldown(step.cooldown, f"strategy:{...}")`，中断则按现状 stop 路径退出。
- 倒计时状态行展示（wait_countdown 的 set_status 效果）在 chokepoint 内保留——长等待仍有秒级倒计时，短等待（样本间隔）维持现状的 ctx.wait 即可（读码确认现状哪种等待配哪种展示，逐字保留）。

### 3.4 状态流（职责分配）

- 初始化：`WorkerContext` 创建时 `cooldown_until = {}`（core/context.py，dataclass field）。
- 写入：唯一写入者是 `_cooldown` chokepoint。
- 读取：P1 无人读（P3 调度器读）。测试可断言写入正确。
- 生命周期：进程内存态，随 worker 线程消亡；不落库（P3 若需要再议）。

## 4. 契约与行为后果（假设与验证）

| # | 行为假设 | 依据 | 验证方式 |
|---|---|---|---|
| 1 | SwapIP 的内部等待外移需要两阶段状态机，P1 不做的损失可接受 | 已读码验证（主 Agent）：strategies.py:102-135，等待夹在两次 RelaunchBrowser 之间，外移后第二次 relaunch 无人执行会破坏换 IP 语义 | 无需 spike；P3 设计时重议（届时有 item 挂起机制） |
| 2 | Sleep 原子的时长分布（对数正态 clamp）可以在策略层逐字复刻 | 推断（explore 报告：atoms/sleep.py:41 对数正态，params min/max） | Step 1.1 读 atoms/sleep.py 全文，把分布公式逐字抄进 SPEC 本节回填；测试断言样本落在 [min,max] 且分布参数一致 |
| 3 | decide/PolicyDecision 链路不需要 cooldown 字段（loop 直接消费 step.cooldown） | 推断（explore 报告：loop.py:386-394 消费 step，decision 只含 action/strategy/attempt） | Step 1.1 读 policy.py 确认；若确认无需透传，§3.1 的 PolicyDecision 字段取消并回填 |
| 4 | 迁移后 loop 的等待展示行为（倒计时状态行）不回归 | 现状：wait_countdown 仅 loop 三处使用（board.py:134-148） | chokepoint 实现保留两种展示路径；冒烟观察状态行 |
| 5 | ctx.wait / wait_countdown 的 stop 可中断语义经 chokepoint 后不变 | 已读码验证：ctx.wait=stop.wait(timeout)（context.py:127-129），wait_countdown 循环 stop.wait(min(1,remain))（board.py:147） | 单测：冷却中置 stop → 立即中断返回 |

## 5. 验收标准（P1 整体）

1. `cd fetcher && python -m pytest tests -x -q` 全绿（含新增：策略 cooldown 输出、chokepoint 中断、时长边界）。
2. 策略层不再有任何 `ctx.wait` 调用（Sleep/BackoffSleep/BlockRest 三个策略 grep 为零；SwapIP 例外有注释标注）。
3. loop.py 的等待执行只出现在 `_cooldown` 内（grep `ctx.wait\|wait_countdown` 在 loop.py 仅 chokepoint 一处）。
4. 等价性冒烟：直连 `python -m fetcher daemon --db <临时库> --workers 1 --limit 6 -n 3 --batch-rest 60`（小批次强制触发批休+样本间隔+长休路径），日志时间戳序列与旧实现同参数对比，节奏模式一致（间隔落在相同时长区间）；stop 中断等待的行为冒烟一次。
5. 等价性冒烟：旧 CLI `1688 contact` 同参数跑一遍（同一临时库口径），确认非 daemon 路径也不回归。

## 6. 变更记录

（空——评审后变更在此追加）
