# Task 3.1 Brief — QueueRouter + 注册表装配 + daemon CLI（--queues）

> 来源：PLAN.md P3-3 Step 3.1 全文 + SPEC §3.1/§3.2/§3.8/§6.8 + 主 Agent 裁定（ledger 裁定 4）。本文件是本次任务的唯一需求来源。

## 目标

1. `QueueRouter` 取代 `DaemonTaskProxy`（P0 组件，仅 daemon 用、无平台依赖，直接替换不保留兼容）
2. 注册表静态装配：本 Step 接 **2 条队列**（`crawl_1688_contact` + `crawl_mic_contact`，双队列验收）；P3-4/P3-5 加 shop/company 队列（本 Step 的注册表结构必须可扩展）
3. daemon CLI：`--queue` 删除，`--queues`（nargs 多值 + choices=注册表键 + 默认全部）
4. 启动 reset 逐 site domain 过滤修复（现 `reset_in_progress()` 无过滤会重置所有站点——现存坑）
5. loop/Engine 多站点装配：per-item site 绑定（ctx.site/inspector/policy 按 active_site 切换）

## 规格

### 1. QueueSpec 补全 + QueueRouter（control/queue_router.py，本文件 Step 1.2 已建基础成员）

```python
@dataclass
class QueueSpec:
    queue: str
    site: str
    task: object                  # 该队列工作项的执行流水线（站点插件 make_task 产出，Task 协议）
    topup: Callable[[ShopDB, int], int] | None   # 补货函数；feeder 类队列为 None
    domain_suffix: str            # contact 类 topup 用；启动 reset 用
    requires: set[str] = field(default_factory=lambda: {"channel", "browser"})
```

```python
class QueueRouter:
    """Task 协议代理：跨队列认领（资源满足 ∧ 站点冷却到期）→ 路由到 item 所属队列的 task。

    acquire_item 三段式（P0 结构沿用）：claim_next_eligible → 各队列 topup →
    condvar 挂起（timeout=min(最近冷却到期剩余, 30s)）。stop 置位才返回 None。
    on_success/on_giveup 路由到 item 所属队列的 task 后落 work_items 终态。
    per-item 方法全部经 ctx.state 路由（WorkerContext 每 worker 独立，天然线程安全）。
    """
```

- **队列侧职责**（acquire/on_success/on_giveup/finish/release）；**执行侧**（fetch/validate/cold_start/label/on_abort/giveup_cost/after_item/empty_message）路由到 item 所属 queue 的 task
- **状态键**（沿用 DaemonTaskProxy 约定 + 新增）：`ctx.state["daemon_work_item_id"]`（item id）、`ctx.state["queue"]`（当前 item 所属队列名）、`ctx.state["active_site"]`（站点注册名，SPEC §3.3「当前站点」）
- **per-worker 动态属性**（loop 在 acquire 前后直接读，方法无 ctx 参数，需给注册表通用默认）：
  - `unit` = "项"、`batch_unit` = ""（多队列下批次节奏弱化，展示口径即可）
  - `cold_start_before_acquire` = False（acquire 后冷启动经路由的 `cold_start(ctx, item)` 逐 item 执行）
  - `rest_counter(stats)` 返回 `stats.get("done", 0)`（总完成数计数）
  - `ip_request_budget` 属性返回 None——**预算必须 per-site**：新增 Task 协议方法 `budget_for(ctx) -> int | None`（Task 基类默认返回 `self.ip_request_budget`，CLI 兼容）；QueueRouter 实现为 `ctx.state["queue"]` 对应 spec.task 的 `budget_for(ctx)`；loop._check_budget 改读 `self.task.budget_for(ctx)`
- **acquire_item 逻辑**：
  1. `queues = eligible_queues(self.registry, ctx, now)` → 非空则 `db.claim_next_eligible(queues, consumer_id)`；命中 → 写三个状态键 → 返回 `item["payload"]`（dict，contact 为 {"domain","name","url"}）
  2. 未命中 → **topup 只对冷却已到期的 contact 队列**（spec.topup 非 None 且 `now >= cooldown_until.get(spec.site, 0)`）逐队列补货（limit=消费者数×4，沿用 DaemonTaskProxy._topup_limit 语义）→ 补到货 notify_all + 重试
  3. 仍无 → condvar `wait(timeout=最近冷却到期剩余的最小值，上限 30s)`（`condvar_timeout` 复用；多队列取各冷却中的最小值，无冷却 30s）→ 醒后查 stop
- **on_success/on_giveup**：先路由到 item task（透传），再 `finish_work_item(item_id, "done"/"failed")`；_finish 复用 DaemonTaskProxy 的错误容错模式（落库失败只记日志）
- `prepare(config)`：各队列 task.prepare + 打印每队列待办（复用 DaemonTaskProxy.prepare 展示口径，按队列循环）
- `make_stats`/`compose`/`summary`：透传或聚合（make_stats 返回 {"done": 0} 结构，loop stats 兼容现状；summary 透传注册表首个 task 或聚合——选简单方案并注释）

### 2. loop per-item site 绑定（control/loop.py）

- `CrawlLoop.__init__` 新增可选参数 `sites: dict[str, object] = None`、`policies: dict[str, Policy] = None`（daemon 装配注入；CLI 不传保持现状）
- 新增 `_bind_item_site(self)`：在 acquire 返回后（run() 里设置 item 后）与 `_process_item` 内调用——读 `ctx.state["active_site"]`；与 `self._bound_site` 不同则：`ctx.site = sites.get(site_name)`（有则）、`self.inspector = SceneInspector.for_site(ctx.site)`、`self.policy = policies.get(site_name, self.policy)`、`self._bound_site = site_name`
- daemon 模式（sites 非空注入）：`__init__` 时 inspector 延迟建（`self._bound_site = None`，`self.inspector = None`），首个 item 绑定后建立
- CLI 模式：sites 为 None → `_bind_item_site` 无操作（ctx.site/inspector/policy 保持 __init__ 装配），行为逐字不变
- `_check_budget`：`budget = self.task.budget_for(ctx)`（见规格 1）
- 不动 `_cooldown`/让出型逻辑（Step 1.3 已完成）

### 3. Engine 多站点装配（control/engine.py）

- `Engine.__init__` 新增可选参数 `sites: dict = None`、`policies: dict = None`；透传给 `loop_factory`（`CrawlLoop(ctx, task, policy=..., sites=..., policies=...)`）
- daemon 分支：`Engine(cfg, task=router, site=None, provider=..., policy=None, sites=..., policies=..., site_name=<首个注册 site 或 "daemon">)`——site_name 仅用于 BrowserManager 初始 view 的 identity 前缀（P3-3 单初始 site 场景用注册表首个队列的 site；多 site 的 view 由 router 调 ensure_site 懒建）
- store_factory 保持现状（domain 默认 "1688.com"；per-view 的 Cookie 域过滤已在 ensure_site 用 site_domain 参数，P3-2 已就绪）——**daemon 直连时 mic 无种子会报错的运行时细节**：冒烟只喂 1688 店，mic 队列无货不认领则不触 ensure_site(mic)，记录此约束即可
- CLI 路径：Engine 构造不变（sites/policies 缺省 None）

### 4. daemon CLI（cli/main.py）

- `--queue` 删除；`--queues`：`nargs="+"`、`choices=<注册表键>`（从 registry 动态取）、默认 `None`（=全部注册表队列）；help 注明「默认全量」
- registry 装配（本 Step 2 条）：`crawl_1688_contact`（site="1688"，task=get_site("1688").make_task("contact")，topup=lambda db, limit: db.topup_contact_work_items(queue, "1688", ".1688.com", limit)，domain_suffix=".1688.com"）、`crawl_mic_contact`（site="madeinchina"，task=get_site("madeinchina").make_task("contact")，topup=同上参数化 `.cn.made-in-china.com`，domain_suffix=".cn.made-in-china.com"）
- 启动 reset（修现存坑）：`reset_claimed_work_items()`（全量保留，daemon 唯一写者）+ **逐 site** `reset_in_progress(domain_suffix)`（按注册表每个 spec.domain_suffix 循环，不再无过滤全量重置）
- `--queues` 只认领指定队列——装配时 registry 按用户选择过滤（未选队列的 task 仍装配？不——未选队列直接不进 registry，其 site 的 policy/seed 也不需要）
- policies 装配：对 registry 涉及的每个 site 建 Policy（`Policy(max_consecutive_fail=cfg.max_consecutive_fail).with_overrides(site.policy_overrides)`）

### 5. 移除 DaemonTaskProxy

- `control/daemon_task.py` 删除（QueueRouter 取代；无平台依赖、仅 daemon 用）
- `tests/test_daemon_task.py` **重写**为 QueueRouter 语义（仿原测试基建：FakeInnerTask/FakeBrowser/临时库/双队列）；`tests/test_cli.py` 的 daemon 装配测试同步更新（--queues）
- grep 复核无残留引用（engine/cli/tests）

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

至少覆盖：

1. **跨队列认领**：两队列各有 pending item → claim_next_eligible 跨队列按 id FIFO 认领；payload dict 返回正确
2. **冷却过滤**：site A 冷却中 → 只认领 site B 队列；到期恢复
3. **topup 只对到期队列**：冷却中队列不补货；到期补货后 notify + 重试认领
4. **condvar timeout**：冷却中 wait 剩余、无冷却 30s、stop 置位退出
5. **on_success/on_giveup 路由**：item 所属 queue 的 task 被正确调用（FakeInnerTask 记录）；work_items 落 done/failed 终态
6. **budget_for 路由**：不同 site 的 item 返回各自 task 的预算
7. **loop 双队列装配**：sites/policies 注入 → 处理 site A item 时 ctx.site/inspector/policy 切换正确；CLI 路径（sites=None）行为不变
8. **CLI --queues**：choices 校验、默认全量、指定子集只装配选定队列
9. **reset 逐 site**：两 domain_suffix 的 in_progress 各自重置，其他站点不动（对比无过滤版本）
10. **兼容**：Task 基类 budget_for 默认返回 ip_request_budget（CLI 零影响）

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 395 passed）
- 现状（已读码）：queue_router.py（Step 1.2：QueueSpec 三字段 + eligible_queues + condvar_timeout 纯函数）；daemon_task.py（DaemonTaskProxy 全量 203 行，P3-1 已加冷却过滤 + active_site）；loop.py（policy:79、inspector:81、_check_budget 读 task.ip_request_budget、_process_item 用 self.policy/self.inspector）；engine.py（_worker 建 ctx.site=self.site、loop_factory(ctx, task, policy=self.policy, board, seed_kit)）；cli/main.py（daemon 分支 --queue + reset_claimed_work_items + reset_in_progress() 无过滤）
- 站点插件：get_site("1688")/get_site("madeinchina")；policy_overrides 在插件类上
- 本 Step 不动 db.py（claim_next_eligible/release_work_item 已在 Step 1.1）；不动 Session/BrowserManager（Step 2.1/2.2 已完成）；SwapIP 两阶段是 Step 3.2
- 修改文件：fetcher/fetcher/control/queue_router.py、fetcher/fetcher/control/loop.py、fetcher/fetcher/control/engine.py、fetcher/fetcher/cli/main.py、删除 fetcher/fetcher/control/daemon_task.py、tests/（重写 test_daemon_task.py、更新 test_cli.py、新增 test_queue_router.py 等）

## Git

- 分支 `feat/multiqueue-p3`；scoped add：上述文件（**删除 daemon_task.py 用 git rm**）
- 工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`
- 若 commit 遇 `.git/index.lock` 竞态，sleep 几秒重试一次，仍失败则保留工作区不 commit 并在 report 注明

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿（旧 test_daemon_task.py 重写后无残留断言）
3. grep 复核：无 `DaemonTaskProxy`/`daemon_task` 残留引用；无 `--queue` 残留
4. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md`：实现摘要、测试列表、TDD 证据、改动文件、自查发现
