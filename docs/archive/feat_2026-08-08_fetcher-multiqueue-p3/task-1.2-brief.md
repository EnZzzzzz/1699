# Task 1.2 Brief — 冷却表改建（键改 site）+ eligible_queues + claim 过滤与 condvar timeout

> 来源：PLAN.md P3-1 Step 1.2 全文 + SPEC §3.2/§3.3 + 主 Agent 冲突扫描裁定（ledger 裁定 2/5）。本文件是本次任务的唯一需求来源。

## 目标

把冷却表语义从「reason 键」改建为「site 键」，新增 `eligible_queues` 纯函数，并把 daemon proxy 的认领改为「冷却过滤 + 冷却感知的 condvar timeout」。**本 Step 只改机制不改行为**：loop 等待方式全部保持现状（原地等待），让出型行为是 Step 1.3 的内容。

## 规格

### 1. `WorkerContext.cooldown_until` 键语义改 site（core/context.py）

- 字段 docstring 更新：`cooldown_until: dict[str, float]` → 「site 注册名 → 到期时刻（time.time()+seconds）」；P1 遗留注释（「P1 阶段只写不读，是 P3 调度器的查询接口」）同步更新为 site 语义
- `WorkerContext` 新增字段 `resources: set[str]`（默认 `{"channel", "browser"}`，与 SPEC §4.2 BrowserConsumer 一致），供 eligible_queues 用（daemon 消费者天然如此；CLI 路径不影响）

### 2. `eligible_queues(registry, ctx, now)` 纯函数（新建 control/queue_router.py）

- 新建 `fetcher/fetcher/control/queue_router.py`，本 Step 先放两个无副作用成员（P3-3 的 QueueRouter 类后续在此文件演进，不另建文件）：

```python
@dataclass
class QueueSpec:
    """队列注册表条目（P3-3 补全 task/topup/domain_suffix 字段；本 Step 先建三字段）。"""
    queue: str            # "crawl_1688_contact" / ...
    site: str             # 站点注册名 "1688" / "madeinchina"
    requires: set[str]    # 资源需求，如 {"channel", "browser"}


def eligible_queues(registry, ctx, now: float) -> list[str]:
    """当前消费者可认领的队列名列表：资源满足 ∧ 该站点冷却已到期。

    registry: 可迭代的 QueueSpec（或鸭子类型：有 .queue/.site/.requires 属性）。
    ctx: 有 .resources（set）与 .cooldown_until（dict[site, float]）的对象。
    纯函数，无副作用；返回按注册表顺序。
    """
```

- 语义逐字对应 SPEC §3.2：`q.requires <= ctx.resources and now >= ctx.cooldown_until.get(q.site, 0)`

### 3. `condvar_timeout(cooldown_until, site, now, cap=30.0)` 纯函数（同文件）

- SPEC §3.2 挂起等待语义：`wait(timeout=min(最近冷却到期剩余, 30s))`——30s 自醒兜底沿用 P0（外部 INSERT 无 notify，最坏 30s 发现）；冷却到期靠 timeout 自然醒来
- 实现：该 site 在冷却中（now < 到期）→ `min(到期 - now, cap)`；不在冷却 → `cap`
- 返回值必须 > 0（调用方直接传给 Condition.wait；0 会忙转）。冷却剩余极小（如 0.01s）时返回该值即可
- 放 queue_router.py 模块级，P3-3 复用

### 4. loop `_cooldown` 写入键改 site（control/loop.py）

- `_cooldown(seconds, reason, prefix=None)` 的登记行从 `cooldown_until[reason]` 改为：`site = ctx.state.get("active_site")`，**有则** `cooldown_until[site] = time.time() + seconds`，**无则不登记**（acquire 前的原地型路径——launch_backoff——active_site 未设置，天然不登记；CLI 站点路径同样不登记，P1 的「只写不读」无消费方，行为不受影响）
- reason 参数保留，仅用于日志/展示（docstring 注明）
- **等待行为本 Step 不变**（仍原地等待），让出是 Step 1.3

### 5. DaemonTaskProxy claim 过滤 + condvar timeout（control/daemon_task.py）

`acquire_item` 三段式改造（仍是过渡形态，P3-3 被 QueueRouter 取代）：

1. **claim 过滤**：进入 claim 前查冷却——`now < ctx.cooldown_until.get(self._site, 0)` 时**不 claim 不 topup**，直接进 wait；
2. **wait timeout**：`condvar_timeout(ctx.cooldown_until, self._site, now)`（单队列阶段只有本队列一个 site）；
3. **active_site 约定**：claim 成功后在 `ctx.state["active_site"] = self._site`（与 `_STATE_KEY` 同处写入）；
4. 其余（topup 补到货 notify_all、stop 检查、30s 兜底）保持现状。

### 6. 既有测试适配（tests/test_cooldown.py 等）

- `test_cooldown.py` 中 chokepoint 写入断言（reason 键 → site 键）：改为「设 `ctx.state["active_site"]="1688"` 后断言 `cooldown_until["1688"]`」；「未设 active_site 时不登记」新断言
- `test_daemon_task.py` 若有受影响的断言同步适配（保持现有用例语义，不重写——P3-3 才重写）

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

新增测试建议放 `tests/test_queue_router.py`（新文件，测 QueueSpec/eligible_queues/condvar_timeout）+ `tests/test_cooldown.py` 适配 + `tests/test_daemon_task.py` 增补。至少覆盖：

1. **eligible_queues 冷却过滤**：site A 冷却中 → A 队列被滤；site B 到期 → 保留
2. **eligible_queues 资源过滤**：requires 超 resources 的队列被滤
3. **eligible_queues 到期恢复可见**：now 推进到到期后 → 恢复
4. **condvar_timeout 计算**：冷却中 → min(剩余, cap)；不冷却 → cap；剩余极小时返回剩余（>0）
5. **proxy 冷却中不 claim**：注入带冷却的 ctx → acquire 阻塞（等超时唤醒路径），不 claim 不 topup
6. **proxy 冷却到期后恢复认领**：推进 cooldown_until → 正常 claim
7. **active_site 写入**：claim 成功后 ctx.state["active_site"] 正确
8. **loop _cooldown site 键**：设 active_site 登记 site 键；未设不登记

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；测试命令 `cd fetcher && python -m pytest tests -q`
- 现状（已读码）：`context.py:113` cooldown_until 字段（reason 键，docstring 写「P1 阶段只写不读」）；`loop.py:110-122` `_cooldown`；`daemon_task.py:101-141` `acquire_item` 三段式（`_STATE_KEY="daemon_work_item_id"`、`_WAIT_TIMEOUT=30.0`）；engine.py 站点插件装配（ctx.site 是插件对象，不是注册名——active_site 用注册名，来自 daemon_task 的 self._site="1688"）
- `claim_work_item` 返回平铺 dict（id/domain/name/url）；本 Step 不改 DB 层（Step 1.1 已完成 claim_next_eligible，但 proxy 本 Step 仍用 claim_work_item，P3-3 才切换）
- 现有测试基线 319 passed；`test_daemon_task.py` 367 行（P3-3 重写，本 Step 只做最小适配）
- 写库短事务；不要动 `fetcher/fetcher/db.py`（Step 1.1 刚完成，无本 Step 内容）

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/core/context.py`、`fetcher/fetcher/control/queue_router.py`（新）、`fetcher/fetcher/control/loop.py`、`fetcher/fetcher/control/daemon_task.py`、`fetcher/tests/` 下本次改动文件
- 工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`
- 若 commit 遇 `.git/index.lock` 竞态，sleep 几秒重试一次，仍失败则保留工作区不 commit 并在 report 注明

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿（319 + 新增）
3. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.2-report.md`：实现摘要、测试列表、TDD 证据（命令+输出）、改动文件、自查发现
