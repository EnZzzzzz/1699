# task-1.1-brief — P4-1 Step 1.1：LocalExecutor 消费者 + requires="local" 互斥

## 位置

P4 第 1 阶段第 1 步（wa_check 迁入 daemon 的消费者底座）。改动范围：
`fetcher/fetcher/control/engine.py`（local_workers）、`fetcher/fetcher/control/
queue_router.py`（冷却键泛化）、`fetcher/fetcher/control/local_loop.py`（新：
无浏览器执行循环）、`fetcher/fetcher/cli/main.py`（--local-workers 参数）、
`fetcher/tests/test_local_consumer.py`（新测试）。WaCheckTask 本体是 Step 1.2。

## 需求（SPEC §3.4 + PLAN Step 1.1）

### 1. 冷却键泛化（site → 队列/站点标识）

现状：`cooldown_until` 键是 site 注册名；`eligible_queues` 按 `q.site` 查。
wa_check 队列无 site（SPEC：wa_check 项 site=NULL、冷却键取 queue 名）。

改动：
- `queue_router.eligible_queues`：冷却键改为 `q.site or q.queue`（site
  非空用 site，否则退 queue 名）。
- `queue_router.condvar_timeout_multi`：入参 sites 列表可能含 None——
  调用方传 `[spec.site or spec.queue for spec in registry]`。
- `loop._cooldown`：登记键 `ctx.state.get("active_site") or
  ctx.state.get("queue")`（active_site 为 None 时用 queue 名登记，否则不登记）。

### 2. LocalExecutor 消费者（engine 扩展）

- Engine 新增参数 `local_workers: int = 0`（daemon 传 --local-workers，
  默认 2）。CLI 单站点路径不传（0）。
- 新增 `_local_worker(wid, board)` 线程入口：不建 BrowserManager、
  不分配通道/种子；ctx = WorkerContext(resources={"local"},
  consumer_kind="local", wid=wid, stop=self.stop, log=..., store=...)。
- 跑 `LocalLoop(ctx, task, ...)`（新类，见下）。loop 结束后写 stats。
- Engine.run 装配：浏览器 worker 数 = cfg.workers（原逻辑）；另起
  local_workers 个 local 线程（不参与通道分配/错开启动/种子池）。
- **席位**：local 消费者无浏览器，不占 CloakBrowser 席位。

### 3. LocalLoop（fetcher/control/local_loop.py 新类）

无浏览器执行循环（wa_check 类非站点任务的载体）。结构：

```
run():
  while not ctx.stopped():
    item = task.acquire_item(ctx)     # 走 QueueRouter（local 队列）
    if item is None: break
    result = task.fetch(ctx, item)
    outcome = result.outcome
    if outcome is OK: task.on_success(ctx, item, result)
    elif outcome is SKIPPED: break
    elif outcome is FATAL: task.on_giveup(ctx, item, result.detail, "fatal"); break
    else: task.on_giveup(ctx, item, result.detail, "net")
    task.after_item(ctx, item)
  return stats（task.make_stats()）
```

- 不做 SceneInspector/策略表/熔断/浏览器簿记（非站点任务无页面）。
- 停止协作：ctx.stopped() 每轮检查；原子返回 SKIPPED 即收工。
- task 是 Task 协议对象（Step 1.2 的 WaCheckTask 实现 acquire/fetch/
  on_success/on_giveup/after_item/make_stats）。

### 4. CLI

- daemon 子命令加 `--local-workers`（int，默认 2，help 注明无浏览器消费者，
  wa_check 队列消费用）。
- `_run_daemon` 把 args.local_workers 传给 Engine。

## 验收（TDD，先写失败测试）

1. **结构性互斥**：`eligible_queues` 中，browser consumer
   （resources={"channel","browser"}）看不到 requires={"local"} 的队列；
   local consumer（resources={"local"}）看不到 requires={"channel","browser"}
   的队列；同冷却到期判定正确。
2. **冷却键泛化**：wa_check spec（site 空/None）的冷却用 queue 名登记与
   查询（eligible_queues 过滤生效）。
3. **Engine local_workers**：local_workers=2 时起 2 个 local 线程
   （FakeLoop 记录），浏览器 worker 数不受影响；local 线程 ctx.resources
   == {"local"}、consumer_kind == "local"。
4. **LocalLoop**：假 task 走通 acquire→fetch→on_success 循环；FATAL 停止；
   SKIPPED 收工；无浏览器/网络依赖。
5. 现有全量测试不 regress（test_engine/test_queue_router/test_control_loop）。

## 环境约束

- 全部临时 sqlite + 假 task/loop，不起浏览器/网络。
- 提交前 `cd fetcher && python3 -m pytest tests -q` 全量绿。
