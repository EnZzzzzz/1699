# Task 1.3 Brief — `_cooldown` 让出型改造（节奏冷却登记即返回）

> 来源：PLAN.md P3-1 Step 1.3 全文 + SPEC §3.3 + 主 Agent 冲突扫描裁定（ledger 裁定 1/3/5）。本文件是本次任务的唯一需求来源。

## 目标

把 loop 的等待 chokepoint 拆成两种语义：**让出型**（节奏冷却：样本间隔/批休/周期长休）登记 site 键后**立即返回不等待**（等待自然转移到 acquire_item 的 condvar timeout）；**原地型**（launch_backoff、策略冷却）保持现状原地等待。**单队列行为等价**是验收口径（等待只是从 loop 内移到 condvar，总时长等价；P3-3 接多队列后冷却期间才能转取其他队列）。

## 规格

### 1. `_cooldown` 让出参数（control/loop.py）

```python
def _cooldown(self, seconds: float, reason: str,
              prefix: str | None = None, yield_: bool = False) -> bool:
    """唯一等待执行点。返回 True=被 stop 中断。

    yield_=True（让出型）：登记 cooldown_until[active_site] 后立即返回
    False，不等待——等待由下一轮 acquire_item 的 condvar timeout 执行
    （冷却期间该站点队列对本消费者不可见 → 多队列时自然转取其他队列）。
    yield_=False（原地型）：登记后原地等待（现状，秒级/装配中途等待用，
    如 launch_backoff；策略冷却待 P3-3 router 接 release 后改让出）。
    """
```

- 让出型登记：`site = ctx.state.get("active_site")`，有则 `cooldown_until[site] = time.time() + seconds`（与 Step 1.2 同规则；理论上让出型调用点 active_site 均已设置，未设时静默跳过登记仍按不等待返回）
- 原地型保持 Step 1.2 的登记规则 + `ctx.wait`/`wait_countdown` 展示路径逐字保留

### 2. 调用点改造

| 调用点 | 现状 | 改后 |
|---|---|---|
| batch_rest（批次采满） | `_cooldown(rest, "batch_rest", prefix="批次休息")` | `yield_=True` |
| sample_interval（样本间隔） | `_cooldown(t, "sample_interval")` | `yield_=True` |
| periodic_rest（周期长休） | `_cooldown(t, "periodic_rest", prefix="长休息")` | `yield_=True` |
| launch_backoff（启动退避） | `_cooldown(backoff, "launch_backoff", prefix="启动退避")` | 原地（默认），加注释「装配中途、秒级，换队列无意义」 |
| 策略冷却（_process_item 内 step.cooldown） | `_cooldown(step.cooldown, f"strategy:{...}")` | 原地（默认），加注释「item 未完成的路径暂保留现状，P3-3 router 接 release 后改让出」 |

- 让出型的 stop 中断语义：让出型不等待所以不会被中断返回 True——返回 False 继续循环；下一轮 acquire_item 的 condvar wait 内 stop 置位 → 返回 None → loop break（终局与改造前一致：stop 后干净退出）
- 倒计时状态行（wait_countdown）仅原地型使用；让出型不再显示「批次休息 mm:ss」状态行——展示变化可接受（P3-3 后由 board 的「等货/等冷却」取代），不强行保真

### 3. P1 遗留注释同步

- `core/context.py:113` cooldown_until 注释（Step 1.2 已改 site 语义，确认无残留 reason 描述）
- `loop.py` `_cooldown` docstring、strategies.py 中 SwapIP 的「冷却例外」注释——如有提及「P3 重议」等字样核对是否需要同步（不需要扩大范围，只改本 Step 触及的注释）

### 4. 既有测试适配

- `tests/test_cooldown.py`：chokepoint 测试适配——让出型调用（模拟三处节奏冷却）断言「登记 site 键 + 立即返回不等待（不触 ctx.wait/wait_countdown）」；原地型（launch_backoff/策略冷却）断言保持等待
- `tests/test_control_loop.py`：如有节奏断言同步适配（保持用例语义）

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

至少覆盖：

1. **让出型立即返回**：yield_=True 时 _cooldown 返回 False（不等），不调用 ctx.wait/wait_countdown
2. **让出型登记 site 键**：active_site="1688" 时 cooldown_until["1688"] 被写入
3. **原地型保持等待**：yield_=False 时走 ctx.wait（prefix=None）或 wait_countdown（prefix 非空），可中断
4. **三处调用点确实传 yield_=True**（可经单测 + grep 复核）
5. **单队列等价性冒烟**（见下，report 附证据）

## 冒烟（验收证据，随跑随写）

单队列 daemon 冒烟（环境铁律：--workers 1、直连、临时库放 /tmp、浏览器 launch +1 席以内）：

```
cd /Volumes/DataDrive/proj/public/1699/fetcher
python -m fetcher daemon --db /tmp/smoke_p3_13.db --workers 1 --limit 6 -n 3 --batch-rest 60 <--workers 1 直连-->
```

- 参考 P1 冒烟记录（docs/archive/feat_2026-08-07_fetcher-cooldown-p1/smoke/）的命令与节奏对比口径
- **直连环境 1688 滑块墙近乎必现，全 failed 是环境噪声**——取结构证据即可：
  - 冷却登记：改造后批休/样本间隔的等待体现在「下一次认领前的时间差」（时间戳序列间隔落在 sample_min~max / batch_rest 区间）与 proxy 的 condvar 等待路径日志（如有）
  - 节奏等价：对比改造前同参数的时间戳间隔模式（若 P1 smoke 有存档对比；无存档则记录本冒烟的间隔数据作为新基线）
  - 冒烟日志（命令 + 输出摘录）写入 `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/`（目录随跑随建，报告引用路径）
- 冒烟后确认 `ip_events` / shops 落库口径与旧路径一致（如可观察）

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 336 passed）
- 现状（已读码）：`loop.py:110-122` `_cooldown`（登记 reason 键 + 等待两路径）；`loop.py:123-141` batch_rest、`:195-200` sample_interval、`:203-213` periodic_rest、`:243-249` launch_backoff、`:386-394` 策略冷却；Step 1.2 已把登记键改为 active_site（未设不登记）
- proxy（daemon_task.py）Step 1.2 已具备冷却过滤 + condvar timeout（min(剩余,30)）——让出型登记后下一轮 acquire 自然等待
- 不要动 `fetcher/fetcher/db.py`、`fetcher/fetcher/control/queue_router.py`、`fetcher/fetcher/core/context.py`（Step 1.2 已完成）
- 冒烟环境：本机常有活爬虫（CloakBrowser solo 5 席，活爬虫约占 2），launch 前 wait_for_license_seat 会自动等席；若席位满 5/5 等待超时失败，报告环境情况稍后重试，不要调参硬闯

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/control/loop.py`、`fetcher/tests/` 下本次改动文件、`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/` 冒烟日志
- 工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`
- 若 commit 遇 `.git/index.lock` 竞态，sleep 几秒重试一次，仍失败则保留工作区不 commit 并在 report 注明

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. 冒烟证据落 plan 目录 smoke-step1.3/（命令 + 时间戳间隔数据 + 结构证据）
4. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.3-report.md`：实现摘要、测试列表、TDD 证据、冒烟证据（含环境情况）、改动文件、自查发现
