# Step 2.1 报告 — DaemonTaskProxy 实现

## 实现了什么

新增 `fetcher/fetcher/control/daemon_task.py`（唯一改动文件），实现
`DaemonTaskProxy(inner, queue, site, domain_suffix, db_factory=None)`：

- 纯组合、不继承 Task 基类。显式定义 `acquire_item / prepare /
  after_item / on_success / on_giveup`，显式以 property 转发类属性
  `unit / batch_unit / cold_start_before_acquire / ip_request_budget`，
  其余（`compose / make_stats / label / fetch / validate / summary` 等）
  经 `__getattr__` 透传 inner。
- `acquire_item` 三段式（SPEC §3.3）：claim → 未命中则
  `topup_contact_work_items`（limit=消费者数×4）+ `notify_all` 重试 →
  仍无货则条件变量 `wait(timeout=30)` 自醒，醒后先查 `ctx.stop`，
  置位返回 None。整个「claim→topup→wait」决策在条件变量锁内完成，
  避免「补货 notify 发生在对方 wait 之前」的丢失唤醒。
- 不 import ContactTask，对任意 inner task 成立。

## 关键设计选择及理由

- **finish 钩子挂 `on_success` / `on_giveup`，不挂 `after_item`**：
  读 `control/loop.py:347-383` 确认 `after_item(ctx, item)` 签名拿不到
  处置结果（成功/放弃只存在于 `_process_item` 的局部 kind），而
  `on_success`（loop.py:350）与 `on_giveup`（loop.py:380）正好是
  终态分叉点。proxy 透传 inner 返回值的同时落
  `finish_work_item(id, "done" / "failed")`（failed 附带
  `{"reason", "kind"}`）。abort/stop 路径 item 保持 claimed，由
  daemon 重启时 `reset_claimed_work_items()` 回收（Step 1.2 已有）。
- **work_item id 按 worker 隔离用 `ctx.state`**（键
  `daemon_work_item_id`）：`WorkerContext` 每 worker 独立
  （engine.py:149 每 worker 新建），`ctx.state` 天然线程隔离，
  比「wid 键字典+锁」少一个共享状态、少一把锁。claim 命中时写入，
  `_finish` 时 pop（幂等，重复 finish 不会误伤别人的 item）。
- **ShopDB 从 `ctx.store.db` 拿**：Engine 的 store_factory
  （engine.py:48-51）已为每 worker 线程建好独立 ShopDB 连接
  （sqlite 连接禁跨线程，proxy 共享实例不能自持单一连接），且与
  inner.on_success 的写库同一连接。无 `ctx.store`（单测/直跑）时
  退回 `db_factory` 注入或 `ShopDB(ctx.config.resolved_db_path())`，
  按线程缓存在 `threading.local`。
- **补货上限**：`(workers if workers > 0 else 1) * 4`。读
  `context.py` 确认 RunConfig 上没有「按通道数解析后」的 workers
  字段（解析发生在 `Engine._alloc_workers` 局部，不写回 config），
  故 workers<=0 按 brief 裁定的 4×1=4 兜底。
- **prepare**：调 `inner.prepare`（保留其 reset_in_progress 等副作用），
  但其返回 False（现仅「pending 为空」一种情形）不退出——daemon
  模式下队列空不是终止条件，acquire 会阻塞等货；只打印一行提示。
  队列待办口径 = `count_pending(domain_suffix)`（shops pending 未
  补货数）+ 直读连接 `SELECT COUNT(*) FROM work_items WHERE queue=?
  AND status='pending'`（db 层无现成 work_items 计数方法，只读直查）。
- **after_item 容错透传**：1688/madeinchina ContactTask 均未定义
  after_item（基类空实现），`getattr(inner, "after_item", None)` 判空。
- **落终态失败不打死 worker**：`_finish` 捕获异常只记日志，残留
  claimed 由重启回收。

## 验证命令与输出

- `cd fetcher && python -c "from fetcher.control.daemon_task import DaemonTaskProxy"` → `import ok`
- `cd fetcher && python -m pytest tests -x -q` → `221 passed, 2 subtests passed in 9.25s`（无回归）
- 临时脚本冒烟（未入库，仅验证用，覆盖）：空库 topup 补货→claim 返回
  含 domain/name/url 三键的 dict；on_success 落 done、on_giveup 落
  failed；stop 置位立即返回 None；两线程并发等货一得一等、stop 后
  27s 内全部退出（≤30s 自醒）；`__getattr__` 透传与类属性转发正常、
  inner 没有的属性正确抛 AttributeError。输出：`smoke ok: [(0, 2)] 退出耗时 27.0s`

## 改动的文件

- 新增：`fetcher/fetcher/control/daemon_task.py`（未触碰任何既有文件）

## 自查发现、疑虑

- 等待中的 worker 只能靠 30s 自醒感知 stop（stop Event 与条件变量
  不联动），最坏 30s 退出——满足验收「最多 30s 内返回 None」。
- `prepare` 忽略 inner 的 False 是对 brief「调 inner.prepare」的主动
  扩展裁定（daemon 语义要求），已在上方说明；若 Step 2.3 接线时
  希望「启动即空队列直接退出」，在 CLI 侧判断即可，proxy 不需要改。
- `on_giveup` 落 failed 时把 reason/kind 写进 result_json，便于排查；
  done 不写 result（联系方式已在 contacts 表）。
- 条件变量锁内执行 DB 事务（BEGIN IMMEDIATE），多 worker 串行化
  claim/topup；单条操作毫秒级，不构成瓶颈，且换来无丢失唤醒。
