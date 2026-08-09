# Step 2.1 报告 — FbGroupTask（TDD）

## 状态

**DONE** — 13 个新测试全绿；fetcher 全量回归 734 测试通过。

## 实现了什么

### 1. `fetcher/fetcher/sites/facebook/group_task.py`（新建，FbGroupTask）

crawl_fb_group 队列的 local 消费者 Task（SPEC §5.3），对齐 FbPostTask 模式：

- 类属性：`name="fb_group"`、`unit="群"`、`QUEUE="crawl_fb_group"`。
- `prepare(config)`：`db.reset_fb_groups_in_progress()` 崩溃恢复（in_progress →
  pending，n>0 打印恢复数），再打印 pending 群数；ShopDB 延迟导入。
- `acquire_item(ctx)`：`claim_next_eligible(["crawl_fb_group"], consumer_id_for(ctx))`，
  payload 注入 `id`（对齐 FbDiscoverTask/WaCheckTask）。
- `label(item)`：`f"{item['url']}（{provider}，≤{limit}帖）"`。
- `fetch(ctx, item)`：`FetchFbGroupPosts().run(ctx, {"url","provider","limit"})`
  透传；provider 缺省 None（原子内部缺省 brightdata）、limit 缺省 10。原子零改动。
- `on_success(ctx, item, result)`：
  - 逐帖 `db.save_fb_contacts(post["url"], group_id, post["phones"])`（正文全文已
    在手直接落库，不走 crawl_fb_post）；无 post_url 的项跳过。
  - `db.mark_fb_group_done(item["url"], len(posts), has_contact)`——`has_contact`
    取 `data["has_contact"] or data["phones"]`（两者同义，协调者裁定 2）。
  - stats：有号码 → ok+1（state 含号码数与新增数），无号码 → empty+1
    （对齐 FbPostTask.on_success 模式，裁定 3 的自然延伸）。
  - 返回 `len(posts)`（计入批次配额，裁定 1）。
- `on_giveup`：`db.mark_fb_group_failed(item["url"])` + failed+1，返回
  `"标记 failed 跳过"`（402/429/网络错误/无帖均置 failed，裁定 4）。
- `on_abort`：返回 `"群 {url} 留在 in_progress，下次运行自动放回 pending"`（裁定 5）。
- `giveup_cost(item)`：返回 1。
- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。
- 附带 `summary`/`compose`/`empty_message`/`rest_counter`：QueueRouter 委托调用
  （queue_router.py:187/206/212 分别委托 empty_message/compose/summary），
  对齐 FbPostTask 参考形态（Step 1.3 评审先例认可此范围）。

FATAL（缺 API key / 未知 provider）由原子返回、Task 框架直接停止，Task 不
额外处理（对齐 wa_task 处置注释）。

### 2. `fetcher/fetcher/db.py`（+26 行，三个写函数）

- `mark_fb_group_done(url, post_count, has_contact)`：status=done + 回写
  post_count/has_contact/last_crawled_at=_now()。
- `mark_fb_group_failed(url)`：status=failed。
- `reset_fb_groups_in_progress() -> int`：in_progress → pending，返回行数。

全部短事务 + commit，复用 self.conn（ShopDB.__init__ 已设 busy_timeout=30000），
镜像 mark_fb_post_done/mark_fb_post_failed/reset_fb_posts_in_progress 既有风格。

## 测了什么（13 个测试，`fetcher/tests/test_fb_group_task.py`）

| 测试 | 断言 |
|---|---|
| fetch 透传 url/provider/limit | mock 原子 run 收到 `{"url","provider","limit"}` |
| fetch 缺省 provider/limit | provider=None 透传、limit=10 |
| on_success 逐帖落号 | fb_contacts post_url 溯源 + group_id 从群 URL 解析；无号码帖不落行 |
| on_success 群 done 回写 | post_count=2、has_contact=1、last_crawled_at 非空；stats ok=1 |
| on_success 无号码 | has_contact=0、empty=1、ok=0 |
| on_giveup 群 failed | status=failed、failed=1 |
| prepare 崩溃恢复 | 预置 in_progress 行 → prepare 后回 pending |
| acquire_item 认领 + id 注入 | 认领 crawl_fb_group 工作项、payload 含 id |
| acquire_item 空队列 | 返回 None |
| label 格式 | `{url}（apify，≤20帖）` |
| giveup_cost | 1 |
| make_stats | `{"ok":0,"empty":0,"failed":0}` |
| on_abort 短语 | 含 in_progress 与群 URL |
| _group_id_from_url | 正/斜杠结尾/空/非 FB URL |

落库断言全部用真实 ShopDB 临时库（`tempfile.TemporaryDirectory`），仅原子层 mock。

## TDD 证据

### RED

命令：
```
cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_fb_group_task.py"
```
输出（失败）：
```
ImportError: Failed to import test module: test_fb_group_task
ModuleNotFoundError: No module named 'fetcher.sites.facebook.group_task'
Ran 1 test in 0.000s
FAILED (errors=1)
```
符合预期：group_task 模块尚不存在，测试文件（需求转译）先行失败。

### GREEN

实现 group_task.py + db.py 三函数后，同命令输出：
```
Ran 13 tests in 0.061s
OK
```
（尾部两行 prepare 打印为任务自身输出，与 test_fb_post_task.py 既有行为一致。）

### 回归

- `-p "test_fb_*.py"`：55 测试 OK
- 全量 `-s tests`：**734 测试 OK**（db.py 改动无连带破坏）

## 改动的文件

- `fetcher/fetcher/sites/facebook/group_task.py`（新建）
- `fetcher/fetcher/db.py`（+26 行）
- `fetcher/tests/test_fb_group_task.py`（新建，13 测试）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-brief.md`（未改动，随 commit 纳入）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md`（本文件）

## 自查

- **完整性**：SPEC §5.3 逐条对照——类属性/prepare/acquire_item/label/fetch/
  on_success/on_giveup/on_abort/giveup_cost/make_stats 全部实现；§5.6 三写函数
  齐备。边界：空 phones → empty 计数 + has_contact=0；无帖 → 原子 EMPTY →
  on_giveup failed（不走 on_success，框架语义）；缺 provider/limit → 原子缺省；
  缺 API key/未知 provider → FATAL 框架停止。
- **质量**：命名/结构对齐 post_task.py（wctx_stats、延迟导入、prepare 打印风格、
  acquire_item 注释）；落号逻辑按协调者裁定（post_url=帖 URL、group_id 从
  item["url"] 解析、返回 len(posts)）。
- **纪律**：未动原子、未重构范围外代码；summary/compose/empty_message 因
  QueueRouter 委托调用而含（1.3 评审先例认可）。YAGNI：未做重试/换 provider/
  批次配额上游逻辑（Step 2.2/2.4 范围）。
- **测试**：真实落库断言（临时 ShopDB）；mock 仅限原子层；13 覆盖 + 全量回归。

## 疑虑

1. `test_fetch_defaults_provider_limit` 断言 fetch 把 `provider=None` 透传给原子——
   原子内部 `params.get("provider") or "brightdata"` 兜底，行为正确；若后续要
   严格只传三个键的意图不同，可再议（当前与裁定「透传 url/provider/limit」一致）。
2. prepare/on_success 的 print 会在测试输出尾部出现（与 test_fb_post_task.py
   行为一致），非失败输出；如需测试输出零噪音可后续统一加 stdout 捕获。
