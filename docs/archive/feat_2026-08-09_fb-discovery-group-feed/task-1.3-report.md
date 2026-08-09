# Step 1.3 报告 — FbDiscoverTask（TDD）

## 实现了什么

`fetcher/fetcher/sites/facebook/discover_task.py`（新文件，SPEC §5.2）：
discover_fb 队列的 local 消费者 Task，消费 work_items → 调 FetchDdgSerp 原子 → 按 kind 分流落库。

- 类属性：`name="fb_discover"`、`unit="查询"`、`QUEUE="discover_fb"`。
- `prepare(config)`：打印 `[fb_discover] 队列待处理: {n}`（discover 无源表状态机，无崩溃恢复），返回 True。
- `acquire_item(ctx)`：`claim_next_eligible(["discover_fb"], consumer_id_for(ctx))`，payload 注入 `id`（对齐 WaCheckTask）。
- `label(item)`：`f"{item['query']} 第{item['page']}页"`。
- `fetch(ctx, item)`：调 FetchDdgSerp 原子，params 透传 `query/page/sample_min/sample_max`（节奏取 `ctx.config.sample_min/max`）。
- `on_success(ctx, item, result)`：`result.data["results"]` 分流落库：
  - `kind=="post"` → `db.save_fb_posts(keyword=item["query"], source="ddg", posts=[{"url","group_id","group_name"}...])`；
    帖派生群（`group_url` 非空时）同时进 `db.upsert_fb_groups([{"url","group_id","name"}...])`（协调者裁定 2）；
  - `kind=="group"` → `db.upsert_fb_groups`（url 取 `group_url` 或 url，协调者裁定 1）；
  - `kind is None`（非 FB 条目）跳过（协调者裁定 1）；
  - 名称净化 `_clean_title`：strip 后 endswith 检查去 `" | Facebook"` / `" - Facebook"` 后缀一次，无则原样（协调者裁定 3）；空标题落空串；
  - 空 results（防御）→ stats `empty+1`，返回 0；
  - 正常路径 stats `ok+1`，`ctx.set_status(state=..., n=..., ok=..., empty=..., failed=...)`（对齐 FbPostTask L156-163 模式），返回 `save_fb_posts` 返回值（新增帖数，协调者裁定 4/8）。
- `on_giveup(ctx, item, reason, kind)`：BLOCKED/NET_ERROR/EMPTY 一律不落库，仅 `ctx.log` 短语 + stats `failed+1` + set_status（协调者裁定 5/6；冷却由 LocalLoop/框架按 queue 名自动处理）。
- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。
- 附加（对齐 WaCheckTask 参考形态、daemon 路径需要）：`summary()`（聚合三计数，QueueRouter.summary 委托调用）、`empty_message()`（QueueRouter.empty_message 委托调用）。

## 测了什么（`fetcher/tests/test_fb_discover_task.py`，21 个测试）

- **fetch 原子透传**：params 含 query/page/sample_min/sample_max（13.0/20.0），返回原样透传。
- **on_success 分流**（真实 ShopDB 临时库断言落库）：
  - 帖 → fb_posts（url/group_id/group_name/keyword/source='ddg' 溯源）+ 帖派生群同时进 fb_groups；
  - 群主页 → 仅 fb_groups（url 取 group_url），名称去 `- Facebook` 后缀；
  - 混合（帖+群+非 FB）→ 两表各得其位，同 URL 群 INSERT OR IGNORE 去重；
  - kind=None 跳过（不落任何表）；
  - 名称净化边界：` | Facebook`（含首尾空白）、` - Facebook`、无后缀原样、空标题落空串；
  - 帖无 group_id/group_url（防御）→ fb_posts 落 NULL，不派生群行不崩；
  - stats 计数 + set_status 携带 ok/empty/failed/n；
  - 空 results（防御）→ empty+1 返回 0。
- **on_giveup**：不落库 + 返回短语 + failed+1。
- **acquire_item**：认领最老 pending 项、payload id 注入、行置 claimed/claimed_by=local0；空队列返回 None。
- **元数据**：类属性、make_stats、label、prepare 返回 True。

## TDD 证据

**RED**（实现前，测试先写）：
```
$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_fb_discover_task.py"
ImportError: Failed to import test module: test_fb_discover_task
ModuleNotFoundError: No module named 'fetcher.sites.facebook.discover_task'
Ran 1 test in 0.000s
FAILED (errors=1)
```
失败原因符合预期：`discover_task.py` 尚不存在，功能缺失（不是笔误）。

**GREEN**（最小实现后）：
```
$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_fb_discover_task.py"
.....................
Ran 21 tests in 0.074s
OK
[fb_discover] 队列待处理: 1
```

**回归**：
- `-p "test_fb_*.py"`：Ran 42 tests, OK
- `-p "test_wa_task*.py"`：Ran 29 tests, OK
- 全量 `-p ""`：Ran 720 tests, OK（31.4s，输出干净无 error/warning）

## 改动的文件

- `fetcher/fetcher/sites/facebook/discover_task.py`（新）
- `fetcher/tests/test_fb_discover_task.py`（新）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-report.md`（本报告）

## 自查发现

- **完整性**：brief 清单 7 项 hook + 协调者 8 条裁定全部落实；边界（kind=None、空 results、空标题、无 group_id）均有测试。
- **质量**：命名/结构对齐 wa_task.py（WaCheckTask 形态）与 post_task.py（wctx_stats/set_status 模式）；原子经 `_make_atom` 延迟导入（与既有 Task 一致）；落库全走 db.py 现成短事务函数。
- **纪律**：未重构任务范围外代码；`summary`/`empty_message` 为对齐参考形态 + daemon QueueRouter 委托调用所需（非 YAGNI 越界）。
- **疑虑**：
  1. 帖派生群在 `group_url` 缺失（防御场景，原子正常不会产生）时选择不派生群行，而非回退到帖 URL——避免向 fb_groups 写入 permalink 污染；kind=="group" 则按协调者裁定回退 `url`。
  2. stats 口径「有 results 且落库 → ok+1」：全 kind=None 条目（有 results 但零落库）按 ok 计——查询本身成功产生结果，非 FB 判定属于上层过滤。
