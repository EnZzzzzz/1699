# Task 3.1 Report — QueueRouter + 注册表装配 + daemon CLI（--queues）

> 日期：2026-08-08 | 分支：feat/multiqueue-p3 | 基线：395 passed → 404 passed

## 实现摘要

**QueueRouter 取代 DaemonTaskProxy**（P0 组件，无平台依赖，直接替换）：

1. **QueueSpec 补全**（`queue_router.py`）：`task`/`topup`/`domain_suffix` 字段，`requires` 默认 `{"channel", "browser"}`
2. **QueueRouter 类**：跨队列认领（三段式：claim_next_eligible → per-queue topup → condvar wait），per-item site 绑定（ctx.state["queue"]/["active_site"]），执行侧方法经 ctx.state 路由到 item 所属 queue 的 task
3. **Task 协议新增 `budget_for(ctx)`**（基类默认返回 `ip_request_budget`，CLI 零影响）
4. **loop `_bind_item_site`**：daemon 路径（sites 非空）按 active_site 动态切换 ctx.site/inspector/policy；CLI 路径（sites=None）无操作
5. **Engine 多站点装配**：sites/policies 参数透传 loop_factory；仅非 None 时传递（兼容现有 FakeLoop 测试）
6. **daemon CLI `--queue`→`--queues`**：nargs="+"，默认全量，支持子集过滤；`_build_registry()` 静态装配 2 条队列（`crawl_1688_contact` + `crawl_mic_contact`）
7. **启动 reset 逐 site**：`reset_in_progress(domain_suffix)` 按注册表逐队列循环（修复无过滤重置所有站点的现存坑）
8. **删除 `daemon_task.py`**（git rm）+ `test_daemon_task.py` 重写为 `test_queue_router.py`

## 改动文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `fetcher/fetcher/control/queue_router.py` | 重写 | QueueSpec 补全 + QueueRouter 类 + condvar_timeout_multi |
| `fetcher/fetcher/control/task.py` | 修改 | +budget_for(ctx) 方法 |
| `fetcher/fetcher/control/loop.py` | 修改 | +sites/policies 参数 + _bind_item_site + _check_budget 改 budget_for |
| `fetcher/fetcher/control/engine.py` | 修改 | +sites/policies 参数，透传 loop_factory |
| `fetcher/fetcher/cli/main.py` | 修改 | --queues + _build_registry + 逐 site reset + QueueRouter 装配 |
| `fetcher/fetcher/control/daemon_task.py` | **删除** | git rm |
| `fetcher/fetcher/core/context.py` | 修改 | 注释更新（daemon_task → queue_router） |
| `fetcher/tests/test_daemon_task.py` | **删除** | git rm（重写为 test_queue_router.py） |
| `fetcher/tests/test_queue_router.py` | 新增 | 29 测试（跨队列/冷却/topup/condvar/终态路由/budget/loop/联跑/执行路由） |
| `fetcher/tests/test_cli.py` | 修改 | --queue → --queues，daemon 测试适配 |
| `fetcher/tests/test_cooldown.py` | 修改 | DaemonTaskProxy → QueueRouter 适配 |

## 测试列表（test_queue_router.py，29 项）

- **跨队列认领**：FIFO 跨队列 claim、payload dict 格式、state 键写入
- **冷却过滤**：冷却中过滤 site A 只认领 B、冷却到期恢复、冷却到期自动认领
- **topup**：冷却中队列不补货、到期队列补货后重试
- **condvar timeout**：多队列取最小冷却剩余、无冷却 30s 兜底、stop 退出、单队列冷却到期唤醒
- **终态路由**：on_success 路由到正确 task + 落 done、on_giveup 路由到正确 task + 落 failed、重复 finish 幂等、跨 ctx stray finish 安全
- **budget_for**：不同 site 返回不同预算、无 queue 返回 None、QueueRouter.ip_request_budget 始终 None
- **Task 兼容**：Task 基类 budget_for 默认返回 ip_request_budget
- **loop 双队列装配**：sites/policies 注入后 site/inspector/policy 切换正确、CLI 路径（sites=None）不变
- **CrawlLoop 联跑**：单 worker 跑双队列，2 项全 done，inner 成功明细不串
- **Router 属性**：unit="项"、batch_unit=""、cold_start_before_acquire=False、rest_counter、ip_request_budget 为 None
- **执行侧路由**：fetch/validate/label 路由到正确 inner task

## TDD 证据

1. **RED**：test_queue_router.py 创建后立即运行，ImportError（QueueRouter 不存在）→ 13 失败 16 通过（缺失实现）→ 逐步修复
2. **GREEN**：全部 29 项通过 + 全量 404 passed（含旧测试无回归）

## grep 复核

- ✅ 无 `DaemonTaskProxy`/`daemon_task` 残留引用（仅注释提及）
- ✅ 无 `--queue` 残留（全部改为 `--queues`）
- ✅ `daemon_task.py` 已通过 git rm 删除

## 自查发现

1. **CrawlLoop._bind_item_site 调用位置**：初次编辑只添加了方法定义未添加调用点，导致集成测试 inspector=None 崩溃。已修复：在 `run()` 的 acquire_item 后 + `_process_item` 入口各加一次调用
2. **_check_budget ctx 变量名**：`budget_for(ctx)` → `budget_for(self.ctx)` 修复
3. **Engine loop_factory kwargs 兼容**：仅 sites/policies 非 None 时传递，避免旧 FakeLoop 测试报 TypeError
4. **label/giveup_cost 无 ctx 参数路由**：通过线程本地缓存 `_tls.last_queue` 实现（acquire_item 时写入）
5. **condvar_timeout_multi cap 参数**：需显式传入 `_WAIT_TIMEOUT` 模块级常量（支持测试注入小超时值）
6. **payload 含 id**：为兼容旧 DaemonTaskProxy 返回格式，acquire_item 返回 payload + `"id"` 键
7. **mic 队列无种子约束**：daemon 直连时 mic 无种子会报错——冒烟只喂 1688 店，mic 队列无货不认领则不触 ensure_site(mic)，记录此约束


## Fix Round 1（task-3.1-fix1.md）

### I1 — Step 1.2 纯函数单测恢复 ✅

从 ebd16ba 找回 eligible_queues / condvar_timeout 纯函数单测 12 项，并入 test_queue_router.py：
- QueueSpecTest（1）：构造与字段
- EligibleQueuesTest（6）：无冷却全可见、冷却过滤、资源过滤、到期恢复、空注册表、空 resources 匹配空 requires
- CondvarTimeoutPureTest（6）：不在冷却返回 cap、冷却中 min(剩余,cap)、自定义 cap、极小剩余>0、到期边缘返回 cap、多 site 取最小值

原 CondvarTimeoutTest（QueueRouter 集成版）重命名为 RouterCondvarTimeoutTest 避免命名冲突。

### I2 — reset 逐 site 测试 ✅

- 从 `_run_daemon` 提取 `reset_daemon_state(db, registry) -> (int, int)` 为独立可测函数
- 新增 `ResetDaemonStateTest`：
  - `test_reset_only_targeted_domain_suffixes`：seed 两组不同 domain_suffix 的 in_progress + 一个无关站点，断言仅匹配的域名被重置、无关站点保持 in_progress
  - `test_reset_with_empty_registry`：空 registry 只做 claimed 回收，不重置任何 in_progress
- 测试使用 `upsert_shops`（非 raw INSERT，避免缺少 first_seen_at 等必需列导致静默失败）

### I3 — --queues 动态校验 ✅

- `all_queue_names` 改为从 `_build_registry()`（全量无过滤）动态派生：`[s.queue for s in full_registry]`
- `test_daemon_queues_dynamic_from_registry` 验证注册表动态派生

### M4 — compose/summary 注释 ✅

两方法各加一行注释：`# 简单方案：委托首个注册 task（多队列下统计口径待后续细化）`

### M5 — payload["id"] 注释 ✅

- grep 确认 site 插件只依赖 domain/name/url（无 item["id"] 引用）
- 保留 `payload["id"]`（测试/DB 验证用），更新注释为：`# 保留 id 键：测试/DB 验证用（site 插件只依赖 domain/name/url）`

### M6 — condvar_timeout（单 queue 版）删除 ✅

全仓库无调用；已删除。多队列版 `condvar_timeout_multi` 保留。

### 副作用修复

- QueueSpec.task 默认值改为 None（纯函数测试不需要 task）
- QueueSpec.topup 类型从 `Callable[[ShopDB, int], int] | None` 改为 `object | None`（Python 3.13 dataclass 兼容性）
- 删除重复 `@dataclass` 装饰器（编辑遗留）
- 删除未使用的 `Callable` import

### 测试验证

```
cd fetcher && python -m pytest tests -q
420 passed, 2 subtests passed
```

