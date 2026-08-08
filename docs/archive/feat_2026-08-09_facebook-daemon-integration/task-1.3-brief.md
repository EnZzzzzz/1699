# task-1.3-brief.md — Step 1.3 FbPostTask 实现

需求唯一来源：PLAN Step 1.3 + SPEC §5.1/§7.3/§8。模板：
`fetcher/fetcher/sites/madeinchina/contact.py`。

## 新文件 `fetcher/fetcher/sites/facebook/post_task.py`

Task 协议实现，类属性/方法（对照 madeinchina/contact.py 模板）：

- 类属性：`name="post"`、`unit="帖"`、`batch_unit=""`、
  `ip_request_budget=60`（匿名 permalink 抓取，参照 1688 contact）。
- `QUEUE = "crawl_fb_post"`（模块级常量，acquire 用）。
- `__init__`：`self._atom = None`；`_make_atom()` 延迟 import 并返回
  `FetchFbPost`（fetcher/atoms/facebook.py）。
- `fetch(ctx, item)`：`FetchFbPost().run(ctx, {"url": item["url"]})`，
  原子 ActionResult 原样上交（loop 的 inspector/fallback 链路无需改动；
  原子 BLOCKED → 兜底映射 RISK_SLIDER_PAGE → facebook 策略链已无
  solve_slider，走 block_rest/swap_ip）。
- `validate(ctx, item, result)`：`data["text"]` 非空且长度 ≥ 100
  （SPEC §5.1 阈值；有效帖页远超此值）。data 为 None → False。
- `on_success(ctx, item, result)`：
  - `db.save_fb_contacts(item["url"], group_id, phones)`——group_id 从
    item["domain"]（群 URL）解析：`facebook.com/groups/{gid}` 正则提取，
    无则 None；
  - `db.mark_fb_post_done(item["url"], bool(data.get("has_contact")))`；
  - stats 计数 `{"ok","empty","failed"}`：phones 非空 → ok+1，否则
    empty+1；`ctx.set_status(...)`（state/n/ok/empty/failed）；
  - **侧车副产物**（SPEC §8）：`ctx.state["result_json"] = {"wechat_ids",
    "tg_handles", "wa_group_invites"}`（仅非空时设；QueueRouter._finish
    的钩子把它写进 work_items.result_json——需给 queue_router.py 加
    2 行：`if result is None: result = ctx.state.pop("result_json", None)`，
    向后兼容，既有任务不设该键零影响）；
  - 返回 1。
- `on_giveup(ctx, item, reason, kind)`：`db.mark_fb_post_failed(item["url"])`
  + stats failed+1 + set_status；返回短语。
- `on_abort(ctx, item)`：返回说明字符串（in_progress 残留下次 reset）。
- `giveup_cost(item)`：返回 1。
- `prepare(config)`：**崩溃恢复**——`db.reset_fb_posts_in_progress()`
  （新 db 方法：fb_posts 全量 in_progress → pending）+ 打印 pending 数；
  返回 True。注意：`reset_daemon_state` 只认 domain_suffix 非空的 contact
  队列，不覆盖 fb_posts（SPEC §5.1），重置放本 Task.prepare（router.prepare
  每队列都会调）。
- `cold_start(ctx, item)`：空实现（白板匿名会话无需软着陆，SPEC §7.3
  warmup 由框架负责，接受 homepage=1688 首页的已知偏差）。
- `acquire_item(ctx)`：参照 WaCheckTask——`claim_next_eligible([QUEUE],
  consumer_id_for(ctx))`，payload 带 id 返回（daemon 模式由 QueueRouter
  认领，本方法供直接调用/测试）。
- `label(item)`：返回 item["url"]。
- `make_stats()` → `{"ok":0,"empty":0,"failed":0}`；
  `rest_counter(stats)` → `sum(stats.values())`；
  `compose(wid, f)` → `[w{wid}] 出口 {ip} | 采 {n}（✓ok ○empty ✗failed）
  | {post} | {state}`；
  `summary(all_stats, db_path)` → 聚合 ok/empty/failed；
  `empty_message()` → "没有待抓取的帖子了"。
- `wctx_stats(ctx)` 静态方法：`ctx.state["task"]["stats"]`（同 madeinchina）。

## db.py 追加

- `reset_fb_posts_in_progress()`：`UPDATE fb_posts SET status='pending'
  WHERE status='in_progress'`，返回重置行数（短事务）。

## queue_router.py 追加（侧车钩子）

- `_finish` 中：`if result is None: result = ctx.state.pop("result_json", None)`
  （放在 pop(_STATE_KEY) 之后、finish_work_item 之前）。

## 验收（TDD，`fetcher/tests/test_fb_post_task.py`）

- fetch 透传：mock 原子（MagicMock.run 返回 ActionResult），断言 run 收到
  {"url": item["url"]}、返回同一 ActionResult；
- validate 边界：data None / text 空 / text<100 → False；text=100 / >100
  → True；
- on_success 落库：真实 ShopDB（临时库）+ seed fb_posts 行 → on_success
  后 fb_contacts 落号（declared_wa→wa_source='declared'）、fb_posts
  done + has_contact、stats 正确、返回 1；
- on_success 空 phones → empty+1、done has_contact=0；
- on_success 侧车：带 wechat_ids/tg_handles/wa_group_invites → 经
  QueueRouter._finish 落 work_items.result_json（直接调
  QueueRouter.on_success 或验证 ctx.state["result_json"] 已设 + 单独测
  _finish 钩子）；
- prepare 重置：seed in_progress 行 → prepare 后全 pending；
- on_giveup：fb_posts failed + stats failed+1；
- acquire_item：先入队 crawl_fb_post work_item → acquire 返回 payload 带 id；
- _group_id_from_url：群 URL → gid；无/非法 → None。

## 硬约束

- 不改 FetchFbPost 原子、parse_post、既有 37 例 FB 测试行为；
- 时间戳北京时间字符串；中文注释；文件顶部一行模块职责注释；
- TDD Iron Law：先失败测试 → 最小实现 → 转绿。
