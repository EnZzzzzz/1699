# Step 2.1 — FbGroupTask（TDD）

> 这是你的需求唯一来源。PLAN Step 2.1 原文 + SPEC §5.3/§5.6 精确规格抄录如下。

## PLAN Step 2.1 原文（验收以 checkbox 为准）

- [ ] `fetcher/fetcher/sites/facebook/group_task.py`：Task 协议实现（SPEC §5.3）：
      prepare（fb_groups in_progress→pending 崩溃恢复）/acquire_item/label/fetch
      （FetchFbGroupPosts 透传 url/provider/limit）/on_success（逐帖 save_fb_contacts
      + mark_fb_group_done 回写）/on_giveup（mark_fb_group_failed）/on_abort/
      giveup_cost/make_stats
- [ ] fetcher/db.py 补 `mark_fb_group_done(url, post_count, has_contact)` /
      `mark_fb_group_failed(url)` / `reset_fb_groups_in_progress() -> int`
- [ ] 测试（`fetcher/tests/test_fb_group_task.py`）：fetch 透传（mock 原子）、
      on_success 逐帖落号 + 群 done 回写、on_giveup 群 failed、prepare 崩溃恢复、
      acquire_item
- 预估 50min；验收：新测试全绿

## SPEC §5.3 FbGroupTask（精确规格）

包装 FetchFbGroupPosts 的 local 消费者：

- 类属性：`name="fb_group"`、`unit="群"`、`QUEUE="crawl_fb_group"`。
- `prepare(config)`：**fb_groups in_progress → pending 崩溃恢复**（对齐
  FbPostTask.prepare 模式；`reset_daemon_state` 只认 domain_suffix 非空的 contact
  队列，不覆盖 fb_groups，由本 Task 补位）。
- `acquire_item(ctx)`：`claim_next_eligible(["crawl_fb_group"], ...)`，payload 注入 id。
- `label(item)`：`f"{item['url']}（{provider}，≤{limit}帖）"`。
- `fetch(ctx, item)`：`FetchFbGroupPosts().run(ctx, {"url","provider","limit"})`
  （原子已有实现，零改动）。
- `on_success(ctx, item, result)`：
  - 逐帖 `db.save_fb_contacts(post_url, group_id, post["phones"])`——正文全文已在手，
    号码直接落库，**无需再走 crawl_fb_post**；
  - `db.mark_fb_group_done(url, post_count, has_contact)`（回写
    post_count/has_contact/last_crawled_at）；
  - stats 计数，返回帖数。
- `on_giveup(ctx, item, reason, kind)`：`db.mark_fb_group_failed(item["url"])`
  （402/429 额度/限流、网络错误、无帖均置 failed；重跑由平台重开批次）；
  返回短语。
- `on_abort`：群留在 in_progress，下次运行 prepare 自动放回 pending（对齐
  FbPostTask）。
- `giveup_cost(item)`：返回 1（计入批次配额）。
- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。

## SPEC §5.6 fetcher/db.py 新增（本 Step 三个写函数）

- `mark_fb_group_done(url, post_count, has_contact)`：status=done + 回写三字段
  （post_count、has_contact、last_crawled_at=_now()）。
- `mark_fb_group_failed(url)`：status=failed。
- `reset_fb_groups_in_progress() -> int`：in_progress → pending（返回行数）。
- 全部短事务 + busy_timeout=30000（ShopDB.__init__ 已设，直接用 self.conn）。

## 协调者裁定（覆盖 SPEC 未定细节）

1. **on_success 落号细节**：`result.data["posts"]` 每项含 `{"url","text",...,"phones":[...]}`；
   逐帖 `db.save_fb_contacts(post_url=post["url"], group_id=item["url"] 的 group_id,
   phones=post["phones"])`。group_id 从 `item["url"]` 解析（群 URL
   facebook.com/groups/{gid} → gid；参照 post_task.py 的 `_group_id_from_url` 正则
   模式）。返回新增帖数 = len(posts)（计入批次配额——注意 FbPostTask 返回 1，但
   本 Task 逐帖落号，返回 len(posts) 更准确；以 SPEC「返回帖数」为准）。
2. **mark_fb_group_done 参数**：`post_count=len(posts)`、
   `has_contact=bool(result.data["phones"])`（或 result.data["has_contact"]，两者
   同义，取 data 里已有的）。
3. **stats 口径**：有帖且落号 → ok+1（state 含号码数与新增数）；0 帖不会走
   on_success（原子 EMPTY → on_giveup）；on_giveup → failed+1。set_status 对齐
   FbPostTask.on_success 模式。
4. **on_giveup 返回短语**：`"标记 failed 跳过"` 风格（对齐 FbPostTask.on_giveup）。
5. **on_abort 返回短语**：`f"群 {item['url']} 留在 in_progress，下次运行自动放回 pending"`。
6. **label 的 provider/limit**：item payload 含 `provider`（brightdata/apify）与
   `limit`（posts_per_group）；`f"{item['url']}（{provider}，≤{limit}帖）"`。
7. **prepare 打印**：对齐 FbPostTask.prepare——先 reset_fb_groups_in_progress()（n>0
   时打印恢复数），再打印 pending 群数。延迟导入 ShopDB。
8. **acquire_item**：对齐 FbDiscoverTask（claim_next_eligible(["crawl_fb_group"],
   consumer_id_for(ctx))，payload 注入 id）。

## 代码库上下文

- **Task 协议**：`fetcher/fetcher/control/task.py`（含 giveup_cost/on_abort 默认实现——
  本 Task 覆盖它们）。
- **参照**：`fetcher/fetcher/sites/facebook/post_task.py` FbPostTask（prepare 崩溃
  恢复模式、on_success 落库 + set_status、wctx_stats）；`fetcher/fetcher/wa_task.py`
  WaCheckTask（acquire 模式）。
- **原子**：`fetcher/fetcher/atoms/facebook_group.py` FetchFbGroupPosts.run(ctx,
  {"url","provider","limit"})；data 键：provider/group_url/post_count/posts/phones/
  has_contact 等。**FATAL 语义**：缺 API key / 未知 provider → FATAL（on_giveup 不
  会被调——Task 框架对 FATAL 直接停止，见 wa_task 的处置注释）。
- **DB**：`save_fb_contacts(post_url, group_id, phones)`（Step 1.1 前已存在，791 行）、
  `_now()`、短事务模式。
- **测试模式**：参照 test_fb_post_task.py（mock 原子 + 临时 ShopDB + WorkerContext）。
- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
  -s tests -p "test_fb_group_task.py"`；回归 `-p "test_fb_*.py"`。

## TDD 纪律

1. 先失败测试 → RED → 最小实现 → GREEN。mock 只在原子层（mock FetchFbGroupPosts.run），
   落库用真实 ShopDB 临时库断言。
2. 测试覆盖：fetch 透传（url/provider/limit 断言）、on_success 逐帖落号（post_url
   溯源 + group_id）+ 群 done 回写（post_count/has_contact/last_crawled_at）、
   on_giveup 群 failed、prepare 崩溃恢复（预置 in_progress 行 → prepare 后回
   pending）、acquire_item 认领 + id 注入、label 格式、giveup_cost==1、make_stats。
3. 输出干净。

## Commit 约束

- 只 `git add`：`fetcher/fetcher/sites/facebook/group_task.py`、
  `fetcher/fetcher/db.py`、`fetcher/tests/test_fb_group_task.py`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 2.1 ...`。
