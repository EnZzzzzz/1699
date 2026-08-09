# Step 1.3 — FbDiscoverTask（TDD）

> 这是你的需求唯一来源。PLAN Step 1.3 原文 + SPEC §5.2 精确规格抄录如下。

## PLAN Step 1.3 原文（验收以 checkbox 为准）

- [ ] `fetcher/fetcher/sites/facebook/discover_task.py`：Task 协议实现（SPEC §5.2）：
      prepare/acquire_item/label/fetch（原子透传节奏）/on_success（save_fb_posts +
      upsert_fb_groups 分流）/on_giveup/make_stats
- [ ] 测试（`fetcher/tests/test_fb_discover_task.py`）：fetch 原子透传、on_success
      分流落库（帖→fb_posts、群→fb_groups、派生群、名称去后缀）、on_giveup 无落库、
      acquire_item 认领
- 预估 40min；验收：新测试全绿

## SPEC §5.2 FbDiscoverTask（精确规格）

local 消费者，参照 `fetcher/fetcher/wa_task.py` 的 WaCheckTask 形态：

- 类属性：`name="fb_discover"`、`unit="查询"`、`QUEUE="discover_fb"`。
- `prepare(config)`：打印队列待处理数（discover 无源表状态机，无需崩溃恢复）；
  返回 True。
- `acquire_item(ctx)`：`claim_next_eligible(["discover_fb"], consumer_id_for(ctx))`，
  payload 注入 `id`（对齐 WaCheckTask）。
- `label(item)`：`f"{item['query']} 第{item['page']}页"`。
- `fetch(ctx, item)`：调 FetchDdgSerp 原子，params 透传
  `query/page/sample_min/sample_max`（节奏取 `ctx.config.sample_min/max`）。
- `on_success(ctx, item, result)`：把 `result.data["results"]` 分流落库：
  - 帖 permalink 类 → `db.save_fb_posts(keyword=item["query"], source="ddg",
    posts=[{"url","group_id","group_name"}...])`；
  - 全部 FB 群 URL（群主页 + 帖派生）→ `db.upsert_fb_groups([{"url","group_id",
    "name"}...])`（name 取 SERP 标题去 `" | Facebook"` / `" - Facebook"` 后缀，
    近似溯源）；
  - stats 计数（ok/empty/failed），返回新增帖数（计入批次配额）。
- `on_giveup(ctx, item, reason, kind)`：BLOCKED/NET_ERROR/EMPTY 无落库，仅日志短语
  + stats；返回短语。
- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。

## 协调者裁定（覆盖 SPEC 未定细节）

1. **分流依据**：`result.data["results"]` 每项是
   `{"url","title","kind","group_id","group_url"}`（Step 1.2 FetchDdgSerp OK 输出）。
   - `kind == "post"` → save_fb_posts（url=该项 url，group_id，group_name=净化标题）；
   - `kind == "group"` → upsert_fb_groups（url=该项 group_url 或 url，group_id，
     name=净化标题）；kind 为 None 的非 FB 条目跳过。
2. **帖派生群也 upsert**：SPEC §5.2 说「全部 FB 群 URL（群主页 + 帖派生）→
   upsert_fb_groups」。即 post 类条目除了 save_fb_posts，其 group_url 也要进
   upsert_fb_groups（group_id 取自该项）。
3. **名称净化**：title 去掉 `" | Facebook"` 与 `" - Facebook"` 后缀（strip 后
   endswith 检查，去一次即可；无则原样）。这是「近似溯源」，群名允许为空串。
4. **返回新增帖数**：on_success 返回 `save_fb_posts` 的返回值（int，计入批次配额）。
5. **stats 口径**：有 results 且落库 → ok+1；results 空（EMPTY 已由原子返回，正常
   OK 路径不会出现空，但防御）→ empty；on_giveup → failed。对齐 FbPostTask 的
   wctx_stats/set_status 用法（读 post_task.py 参照）。
6. **on_giveup 的 kind 参数**：Task 协议 on_giveup(ctx, item, reason, kind) 返回
   str 短语；BLOCKED/NET_ERROR/EMPTY 均不落库。给 BLOCKED 一个让出型冷却登记？
   不需要——LocalLoop 的冷却由框架处理（冷却键=queue 名，自动）。仅日志短语。
7. **prepare 打印**：`print(f"[fb_discover] 队列待处理: {n}")` 风格对齐 WaCheckTask。
8. **set_status**：on_success 里调用 `ctx.set_status(state=..., n=..., ok=..., empty=..., failed=...)`（对齐 FbPostTask.on_success 的 stats 更新模式，见 post_task.py L156-163）。

## 代码库上下文（brief 之外你需要知道的）

- **Task 协议**：`fetcher/fetcher/control/task.py` 的 Task 类（prepare/acquire_item/
  label/fetch/validate/on_success/on_giveup/on_abort/giveup_cost/make_stats/
  rest_counter）。
- **参照实现**：
  - `fetcher/fetcher/wa_task.py` WaCheckTask（acquire_item payload 注入 id、
    make_stats、on_giveup 短语）；
  - `fetcher/fetcher/sites/facebook/post_task.py` FbPostTask（on_success 落库 +
    set_status 模式、wctx_stats 用法）。
- **DB 函数**（Step 1.1 已实现）：`db.save_fb_posts(keyword, source, posts)`、
  `db.upsert_fb_groups(groups)`（条目键 url/group_id/name，可选 source 键）。
- **FetchDdgSerp 原子**（Step 1.2 已实现）：`fetcher/fetcher/atoms/facebook_discover.py`，
  run(ctx, params) → ActionResult；OK 的 data 含 results 列表。
- **ctx 契约**：`ctx.config.sample_min/sample_max`（RunConfig 浮点，缺省 13/20——
  原子会抬到 60 floor）；`consumer_id_for(ctx)` 在
  `fetcher/fetcher/control/queue_router.py`。
- **测试模式**：现有 test_fb_post_task.py、test_wa_task.py 参照（mock 原子、临时
  ShopDB、构造 ctx）。测试需要构造 WorkerContext（fetcher/fetcher/core/context.py，
  字段可空装配）+ 临时 DB。
- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
  -s tests -p "test_fb_discover_task.py"`；回归 `-p "test_fb_*.py"` 与
  `-p "test_wa_task*.py"`。

## TDD 纪律

1. 先失败测试 → RED → 最小实现 → GREEN。mock 只在原子层（mock FetchDdgSerp.run），
  落库用真实 ShopDB 临时库断言。
2. 测试覆盖：fetch 原子透传（params 含 query/page/sample_min/sample_max）、on_success
  分流（帖→fb_posts 且 keyword/source='ddg' 溯源、群→fb_groups、帖派生群同时进两表、
  名称去 `| Facebook` 后缀、kind=None 跳过）、on_giveup 无落库 + 短语、acquire_item
  认领 + payload id 注入、make_stats、stats 计数。
3. 输出干净。

## Commit 约束

- 只 `git add`：`fetcher/fetcher/sites/facebook/discover_task.py`、
  `fetcher/tests/test_fb_discover_task.py`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 1.3 ...`。
