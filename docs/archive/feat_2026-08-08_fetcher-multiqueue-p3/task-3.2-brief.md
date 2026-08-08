# Task 3.2 Brief — SwapIP 两阶段拆分 + 策略冷却让出/release 链路

> 来源：PLAN.md P3-3 Step 3.2 全文 + SPEC §3.4/§3.5。本文件是本次任务的唯一需求来源。

## 目标

1. **SwapIP 无头两阶段拆分**（SPEC §3.5）：relaunch 未轮换 → 回写本站 Cookie、关闭本站 context（浏览器进程保留，其他站点 view 不受影响）、登记 `needs_relaunch[site]=True` → 输出让出型冷却 → 当前 item release 回 pending → 冷却到期重领时 context 懒建路径发现 needs_relaunch → 走完整 relaunch（Step 2.2 已建懒建消费机制，本 Step 接 SwapIP 置位）
2. **策略冷却统一语义**（SPEC §3.4）：策略给出让出型冷却但 item 未完成（block_rest / swap_ip 无头）→ release 回 pending（attempts 熔断防无限循环）——本 Step 把 loop 的策略冷却从「原地等待」（Step 1.3 遗留）改为「让出 + release」
3. **有头 WaitHumanLogin 例外保留**：注释更新「P3 已拆无头路径」

## 规格

### 1. SwapIPStrategy 无头两阶段（strategy/strategies.py）

现状（已读码 strategies.py:86-135）：relaunch 未轮换 → 原地等 rest（有头走 WaitHumanLogin 轮询，无头 ctx.wait）→ 第二次 relaunch。

改后无头路径：

```python
def run(self, ctx) -> StepResult:
    ...
    old_identity = ctx.session.identity
    result = RelaunchBrowser().run(ctx, self._params)
    if result.outcome is Outcome.SKIPPED:
        return StepResult(False, "用户中断")
    if result.outcome is not Outcome.OK:
        return StepResult(False, result.detail, result.data)
    if result.data.get("rotated") or not ctx.config.use_proxy:
        return StepResult(True, result.detail, result.data)

    # 未轮换（青果 30 分钟时效）——P3 无头两阶段第一步：
    site = ctx.state.get("active_site")
    if ctx.headed:
        # 有头例外保留：WaitHumanLogin 轮询人工登录（需活 page，不拆分）
        rest = random.uniform(ctx.config.block_rest_min, ctx.config.block_rest_max)
        login = WaitHumanLogin().run(ctx, {"seconds": rest})
        if login.outcome is Outcome.OK:
            SaveCookies().run(ctx, {})
            return StepResult(True, f"等轮换期间手动登录成功: {login.detail}")
        if login.outcome is Outcome.SKIPPED:
            return StepResult(False, "用户中断")
        return StepResult(False, "未轮换", cooldown=rest)   # 有头也改让出+release
    # 无头：
    #  1. 回写本站 Cookie（SaveCookies 或等价）
    #  2. 关闭本站 context（session.close_site(site)）——进程保留，其他 view 不受影响
    #  3. 登记 needs_relaunch[site]=True（browser_manager.mark_needs_relaunch）
    #  4. 输出让出型冷却 uniform(block_rest_min, block_rest_max)
    rest = random.uniform(ctx.config.block_rest_min, ctx.config.block_rest_max)
    ctx.log(f"    [!] 出口 IP 尚未轮换（青果 30 分钟时效），"
            f"登记 needs_relaunch[{site}]，让出冷却 {rest / 60:.1f} 分钟，"
            f"冷却到期重领时走完整 relaunch")
    ...（回写+close_site+mark_needs_relaunch，注意异常容错）
    return StepResult(False, f"未轮换，已登记两阶段", cooldown=rest)
```

- `close_site(site)` 已存在（Step 2.1）；`mark_needs_relaunch` 已存在（Step 2.2）；SaveCookies 原子存在
- 有头路径：也改为「返回 cooldown + release」？SPEC §3.5 裁定「有头 WaitHumanLogin 原地等待保留」——即**有头分支维持原地等待现状**（不拆）？再读 SPEC：「**有头模式例外保留**：WaitHumanLogin 人工登录轮询需要活 page，维持原地等待不拆分（有头=人工辅助场景，利用率不是目标）；代码注释同步更新『P3 已拆无头路径』」。
  - 裁定：有头分支**保留原地等待**（WaitHumanLogin 轮询 + 必要时原地等 rest），不做让出——但「第二次 relaunch」是否保留？SPEC 说「第二次 relaunch 由此并入正常 launch 路径」——无头路径下第二次 relaunch 不再显式执行（靠 needs_relaunch 懒建消费）。有头路径保留现状（等轮换后仍可原地第二次 relaunch 或直接 solved）。**有头 = 人工辅助场景，保持现状行为**（含原地 rest + 第二次 relaunch），只更新注释。
  - 所以有头分支代码基本不动，只加注释「P3 已拆无头路径，有头保留原地（人工辅助场景）」。
- `needs_release` 语义：无头路径返回 StepResult(cooldown=rest)——loop 的策略冷却统一语义（见规格 2）会自动 release。不需要额外字段——**策略冷却 + item 未完成 = release** 是统一规则（SPEC §3.4），不是 swap_ip 特有。

### 2. loop 策略冷却改为「让出 + release」（control/loop.py）

`_process_item` 策略执行段（现状 loop.py:430-437）：

```python
if step.cooldown and self._cooldown(
        step.cooldown, f"strategy:{decision.strategy}"):
    return "stop", 0
```

改为：

```python
if step.cooldown:
    # P3：策略冷却统一让出 + release（SPEC §3.4）——冷却期间该站点
    # 队列不可见，item 释放回 pending（attempts 熔断），冷却到期重领
    if self._cooldown(step.cooldown, f"strategy:{decision.strategy}",
                      yield_=True):
        return "stop", 0
    return "release", 0
```

- `run()` 的 kind 分支处理新增 `"release"`：
  - 不计数（`done_in_batch`/`total_done` 不变）
  - 调 `self.task.release_item(ctx)`（QueueRouter 新方法：`db.release_work_item(item_id)` + 返回终态记日志；Task 基类默认空实现保证 CLI 兼容——CLI 路径不会产生 release kind，防御性 no-op）
  - `after_item` 照常调用
  - 继续循环（下一轮 acquire——该 site 队列冷却中不可见，自然转其他队列；单队列时 condvar 等冷却到期）
- **item 未完成 + 让出型冷却 = release 是统一规则**——block_rest（BlockRestStrategy 返回 cooldown 且未 solved）同样走 release 重领重试（attempts 熔断）。注意现状 BlockRest 后是原地等再重试同一 item（链式升级）——改为 release 后**策略链在 item 重领后从头开始**（SPEC §3.4 裁定：attempts 不跨认领保留策略链进度；全局限速寄托于 (site,IP) 簿记与预算）
- stop 语义：release 路径中 stop 置位由下一轮 acquire 的 stop 检查处理（与让出型一致）

### 3. QueueRouter.release_item（control/queue_router.py）

```python
def release_item(self, ctx) -> str:
    """当前 worker 的 item 释放回 pending（attempts+1，耗尽置 failed）。

    返回终态（"pending"/"failed"）供日志；无认领记录时返回 ""。
    """
```

- 用 `ctx.state["daemon_work_item_id"]` → `db.release_work_item(item_id, max_attempts=3)`（Step 1.1 已有）
- 终态 "failed"（attempts 耗尽）时记日志「attempts exhausted」——**类目链不死的补插是 P3-4/5 feeder 的事，本 Step 不接**（contact 队列无链式语义）
- 错误容错同 _finish（落库失败只记日志）
- Task 基类加 `release_item(self, ctx) -> str: return ""` 默认实现

### 4. 注释同步

- strategies.py SwapIP docstring：「P3 已拆无头两阶段；有头 WaitHumanLogin 例外保留原地（人工辅助场景）」
- loop._process_item 策略冷却段注释更新（Step 1.3 写的「P3-3 router 接 release 后改让出」→ 已实现）

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

至少覆盖：

1. **SwapIP 无头未轮换两阶段**：mock RelaunchBrowser rotated=False + 无头 → 断言 close_site 被调（该 site view 移除）、mark_needs_relaunch 置位、返回 cooldown 非空、无原地 wait（ctx.wait 未被调）
2. **SwapIP 轮换成功**：rotated=True → solved 无 cooldown（现状回归）
3. **SwapIP 有头例外**：headed=True → 保持现状（WaitHumanLogin 路径或原地 rest），不置 needs_relaunch
4. **策略冷却 release 链路（核心）**：loop 集成——fake task fetch 恒 BLOCKED → 策略链走到 block_rest（返回 cooldown）→ loop 返回 "release" kind → router.release_item 落库（work_items attempts+1 回 pending）→ 下一轮重领同一 item（attempts 递增）→ attempts 耗尽置 failed
5. **release 后冷却过滤**：release 后该 site 队列在冷却中不可见（eligible_queues 过滤）
6. **attempts 熔断**：max_attempts=3 第三次 release 置 failed（result_json="attempts exhausted"）
7. **Task 基类 release_item 默认空实现**（CLI 兼容）
8. **stop 语义**：release 路径 stop 后退出干净（集成测试或单测）

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 420 passed）
- 现状（已读码）：strategies.py SwapIPStrategy（:86-135，原地等待 + 第二次 relaunch）；loop.py _process_item 策略冷却（`if step.cooldown and self._cooldown(...)` 原地型）；queue_router.py QueueRouter（Step 3.1 完成，含 _finish 模式）；Task 基类（control/task.py，Step 3.1 已加 budget_for）
- 基础设施已就绪：close_site（Step 2.1）、mark_needs_relaunch/懒建消费（Step 2.2）、release_work_item（Step 1.1）、_cooldown yield_（Step 1.3）
- 本 Step 不动 db.py、engine.py、cli/main.py、Session/BrowserManager（如 close_site 有缺可微调但保持语义）
- 注意：block_rest 让出+release 后**策略链重领重置**是行为变化（SPEC §3.4 裁定接受）——相关既有测试（test_control_loop.py 的策略链测试、test_policy.py）若断言「同 item 链式升级」需要适配为「release 重领」语义

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/strategy/strategies.py`、`fetcher/fetcher/control/loop.py`、`fetcher/fetcher/control/queue_router.py`、`fetcher/fetcher/control/task.py`、`fetcher/tests/` 下本次改动文件
- 工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. 单测覆盖：SwapIP 无头两阶段状态流转（mock rotated=False）、策略冷却 release→重领→attempts 熔断全链路
4. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.2-report.md`：实现摘要、测试列表、TDD 证据、改动文件、自查发现
