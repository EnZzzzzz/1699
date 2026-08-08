# 调试报告 — worker 异常退出 'empty'/'failed'

## 摘要

- **根因**：`QueueRouter.make_stats()` 返回 `{"done": 0}`，但 per-site contact task 的 `on_success`/`on_giveup` 通过 `wctx_stats(ctx)` → `ctx.state["task"]["stats"]` 期望 `{"ok": 0, "empty": 0, "failed": 0}`，导致 `KeyError: 'empty'` 或 `KeyError: 'failed'`
- **判定**：**P3 引入**（`QueueRouter` 是 P3 Step 3.1 新增组件，main 分支无此代码路径）
- **修复**：`QueueRouter.make_stats()` 合并所有注册队列 task 的统计键；`QueueRouter.rest_counter()` 委托给首个注册 task
- **状态**：✅ 已修复，447 passed

---

## Phase 1 — 根因调查

### 1.1 冒烟日志时序

**run-3**（`daemon-run-3.log`）——崩 `'failed'`:
```
1688 滑块墙 → relaunch → 浏览器重启，新出口 IP=1688:direct
[w0] [X] worker 异常退出: 'failed'
```

**run-4**（`daemon-run-4.log`）——崩 `'empty'`:
```
1688 滑块墙 → relaunch → mic 成功 1 请求
[w0] [X] worker 异常退出: 'empty'
```

两场景的共同点：worker 在 `_process_item` 内部触发 `on_success` 或 `on_giveup` 回调时崩溃。

### 1.2 加 traceback 复现

在 `loop.py:274` 的 `except Exception` 分支加 `traceback.format_exc()` 后，用临时库复现（`/tmp/dbg_p3.db`，2 个 1688 店 + 2 个 mic 店 + mic dummy cookie），得到完整栈：

```
Traceback (most recent call last):
  File "fetcher/control/loop.py", line 216, in run
    kind, count = self._process_item(item)
  File "fetcher/control/loop.py", line 409, in _process_item
    count = self.task.on_success(ctx, item, result)
  File "fetcher/control/queue_router.py", line 271, in on_success
    count = self._task_for(ctx).on_success(ctx, item, result)
  File "fetcher/sites/alibaba1688/contact.py", line 231, in on_success
    stats["empty"] += 1
KeyError: 'empty'
```

### 1.3 raise 点定位

调用链：
1. `CrawlLoop.__init__` → `self.stats = task.make_stats()` → `QueueRouter.make_stats()` 返回 `{"done": 0}`
2. `ctx.state["task"]["stats"] = self.stats`
3. 策略链结束后 `loop._process_item` 调 `task.on_success(ctx, item, result)`
4. `QueueRouter.on_success` 路由到 `1688ContactTask.on_success`
5. `1688ContactTask.wctx_stats(ctx)` 返回 `ctx.state["task"]["stats"]`，即 `{"done": 0}`
6. `stats["empty"] += 1` → **`KeyError: 'empty'`**

同理，`on_giveup` 路径 `stats["failed"] += 1` → **`KeyError: 'failed'`**

异常消息中的引号来自 Python 内置行为：`str(KeyError('empty'))` → `"'empty'"`。

---

## Phase 2 — P3 引入 vs 预存判定

### 判定依据

| 维度 | 结论 |
|------|------|
| 崩溃代码路径 | `QueueRouter.make_stats()` → `{"done": 0}` |
| `QueueRouter` 引入时间 | P3 Step 3.1（commit `6312302`），main 分支不存在 |
| main 分支等效路径 | `Task.make_stats()` 由具体 task 子类覆盖（如 `ContactTask.make_stats()` → `{"ok": 0, "empty": 0, "failed": 0}`），无此 bug |
| 对照 | 无需对照验证——`QueueRouter` 是纯新增组件，main 分支不存在多队列路由 |

**判定：P3 引入的回归 bug。**

---

## Phase 3 — 修复

### 3.1 修复内容

**`fetcher/fetcher/control/queue_router.py`**：

1. `make_stats()`：合并所有注册队列 task 的 `make_stats()` 结果
   ```python
   def make_stats(self):
       merged = {}
       for spec in self._specs:
           merged.update(spec.task.make_stats())
       return merged
   ```

2. `rest_counter()`：委托给首个注册 task 的实现（而非硬编码 `stats.get("done", 0)`）
   ```python
   def rest_counter(self, stats: dict) -> int:
       if self._specs:
           return self._specs[0].task.rest_counter(stats)
       return 0
   ```

### 3.2 traceback 打印保留（产品改进）

`loop.py:274` 的 `except Exception` 分支：加了 `traceback.format_exc()` 输出栈，方便未来定位异常根因。

### 3.3 测试

- 新增 3 个测试：`test_make_stats_merges_all_registered_tasks`、`test_make_stats_covers_contact_keys`、`test_rest_counter_delegates_to_first_task`
- 全量：**447 passed**（含新增 3 个，替换 1 个旧 test_rest_counter）

### 3.4 复现验证

修复后同参数 daemon 冒烟：worker 正常处理 1688（滑块墙 → 策略链放弃 → 标 failed）和 mic（正常 fetch），**不再崩溃**，统计正常输出。
