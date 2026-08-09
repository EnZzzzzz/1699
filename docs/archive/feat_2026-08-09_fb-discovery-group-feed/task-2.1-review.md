# Step 2.1 review package
7a09836 feat(fb): Step 2.1 FbGroupTask——crawl_fb_group local 消费者（TDD）
 .../task-2.1-brief.md                              | 109 ++++++++++
 .../task-2.1-report.md                             | 132 ++++++++++++
 fetcher/fetcher/db.py                              |  26 +++
 fetcher/fetcher/sites/facebook/group_task.py       | 176 ++++++++++++++++
 fetcher/tests/test_fb_group_task.py                | 234 +++++++++++++++++++++
 5 files changed, 677 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-brief.md
new file mode 100644
index 0000000..af397d1
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-brief.md
@@ -0,0 +1,109 @@
+# Step 2.1 — FbGroupTask（TDD）
+
+> 这是你的需求唯一来源。PLAN Step 2.1 原文 + SPEC §5.3/§5.6 精确规格抄录如下。
+
+## PLAN Step 2.1 原文（验收以 checkbox 为准）
+
+- [ ] `fetcher/fetcher/sites/facebook/group_task.py`：Task 协议实现（SPEC §5.3）：
+      prepare（fb_groups in_progress→pending 崩溃恢复）/acquire_item/label/fetch
+      （FetchFbGroupPosts 透传 url/provider/limit）/on_success（逐帖 save_fb_contacts
+      + mark_fb_group_done 回写）/on_giveup（mark_fb_group_failed）/on_abort/
+      giveup_cost/make_stats
+- [ ] fetcher/db.py 补 `mark_fb_group_done(url, post_count, has_contact)` /
+      `mark_fb_group_failed(url)` / `reset_fb_groups_in_progress() -> int`
+- [ ] 测试（`fetcher/tests/test_fb_group_task.py`）：fetch 透传（mock 原子）、
+      on_success 逐帖落号 + 群 done 回写、on_giveup 群 failed、prepare 崩溃恢复、
+      acquire_item
+- 预估 50min；验收：新测试全绿
+
+## SPEC §5.3 FbGroupTask（精确规格）
+
+包装 FetchFbGroupPosts 的 local 消费者：
+
+- 类属性：`name="fb_group"`、`unit="群"`、`QUEUE="crawl_fb_group"`。
+- `prepare(config)`：**fb_groups in_progress → pending 崩溃恢复**（对齐
+  FbPostTask.prepare 模式；`reset_daemon_state` 只认 domain_suffix 非空的 contact
+  队列，不覆盖 fb_groups，由本 Task 补位）。
+- `acquire_item(ctx)`：`claim_next_eligible(["crawl_fb_group"], ...)`，payload 注入 id。
+- `label(item)`：`f"{item['url']}（{provider}，≤{limit}帖）"`。
+- `fetch(ctx, item)`：`FetchFbGroupPosts().run(ctx, {"url","provider","limit"})`
+  （原子已有实现，零改动）。
+- `on_success(ctx, item, result)`：
+  - 逐帖 `db.save_fb_contacts(post_url, group_id, post["phones"])`——正文全文已在手，
+    号码直接落库，**无需再走 crawl_fb_post**；
+  - `db.mark_fb_group_done(url, post_count, has_contact)`（回写
+    post_count/has_contact/last_crawled_at）；
+  - stats 计数，返回帖数。
+- `on_giveup(ctx, item, reason, kind)`：`db.mark_fb_group_failed(item["url"])`
+  （402/429 额度/限流、网络错误、无帖均置 failed；重跑由平台重开批次）；
+  返回短语。
+- `on_abort`：群留在 in_progress，下次运行 prepare 自动放回 pending（对齐
+  FbPostTask）。
+- `giveup_cost(item)`：返回 1（计入批次配额）。
+- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。
+
+## SPEC §5.6 fetcher/db.py 新增（本 Step 三个写函数）
+
+- `mark_fb_group_done(url, post_count, has_contact)`：status=done + 回写三字段
+  （post_count、has_contact、last_crawled_at=_now()）。
+- `mark_fb_group_failed(url)`：status=failed。
+- `reset_fb_groups_in_progress() -> int`：in_progress → pending（返回行数）。
+- 全部短事务 + busy_timeout=30000（ShopDB.__init__ 已设，直接用 self.conn）。
+
+## 协调者裁定（覆盖 SPEC 未定细节）
+
+1. **on_success 落号细节**：`result.data["posts"]` 每项含 `{"url","text",...,"phones":[...]}`；
+   逐帖 `db.save_fb_contacts(post_url=post["url"], group_id=item["url"] 的 group_id,
+   phones=post["phones"])`。group_id 从 `item["url"]` 解析（群 URL
+   facebook.com/groups/{gid} → gid；参照 post_task.py 的 `_group_id_from_url` 正则
+   模式）。返回新增帖数 = len(posts)（计入批次配额——注意 FbPostTask 返回 1，但
+   本 Task 逐帖落号，返回 len(posts) 更准确；以 SPEC「返回帖数」为准）。
+2. **mark_fb_group_done 参数**：`post_count=len(posts)`、
+   `has_contact=bool(result.data["phones"])`（或 result.data["has_contact"]，两者
+   同义，取 data 里已有的）。
+3. **stats 口径**：有帖且落号 → ok+1（state 含号码数与新增数）；0 帖不会走
+   on_success（原子 EMPTY → on_giveup）；on_giveup → failed+1。set_status 对齐
+   FbPostTask.on_success 模式。
+4. **on_giveup 返回短语**：`"标记 failed 跳过"` 风格（对齐 FbPostTask.on_giveup）。
+5. **on_abort 返回短语**：`f"群 {item['url']} 留在 in_progress，下次运行自动放回 pending"`。
+6. **label 的 provider/limit**：item payload 含 `provider`（brightdata/apify）与
+   `limit`（posts_per_group）；`f"{item['url']}（{provider}，≤{limit}帖）"`。
+7. **prepare 打印**：对齐 FbPostTask.prepare——先 reset_fb_groups_in_progress()（n>0
+   时打印恢复数），再打印 pending 群数。延迟导入 ShopDB。
+8. **acquire_item**：对齐 FbDiscoverTask（claim_next_eligible(["crawl_fb_group"],
+   consumer_id_for(ctx))，payload 注入 id）。
+
+## 代码库上下文
+
+- **Task 协议**：`fetcher/fetcher/control/task.py`（含 giveup_cost/on_abort 默认实现——
+  本 Task 覆盖它们）。
+- **参照**：`fetcher/fetcher/sites/facebook/post_task.py` FbPostTask（prepare 崩溃
+  恢复模式、on_success 落库 + set_status、wctx_stats）；`fetcher/fetcher/wa_task.py`
+  WaCheckTask（acquire 模式）。
+- **原子**：`fetcher/fetcher/atoms/facebook_group.py` FetchFbGroupPosts.run(ctx,
+  {"url","provider","limit"})；data 键：provider/group_url/post_count/posts/phones/
+  has_contact 等。**FATAL 语义**：缺 API key / 未知 provider → FATAL（on_giveup 不
+  会被调——Task 框架对 FATAL 直接停止，见 wa_task 的处置注释）。
+- **DB**：`save_fb_contacts(post_url, group_id, phones)`（Step 1.1 前已存在，791 行）、
+  `_now()`、短事务模式。
+- **测试模式**：参照 test_fb_post_task.py（mock 原子 + 临时 ShopDB + WorkerContext）。
+- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
+  -s tests -p "test_fb_group_task.py"`；回归 `-p "test_fb_*.py"`。
+
+## TDD 纪律
+
+1. 先失败测试 → RED → 最小实现 → GREEN。mock 只在原子层（mock FetchFbGroupPosts.run），
+   落库用真实 ShopDB 临时库断言。
+2. 测试覆盖：fetch 透传（url/provider/limit 断言）、on_success 逐帖落号（post_url
+   溯源 + group_id）+ 群 done 回写（post_count/has_contact/last_crawled_at）、
+   on_giveup 群 failed、prepare 崩溃恢复（预置 in_progress 行 → prepare 后回
+   pending）、acquire_item 认领 + id 注入、label 格式、giveup_cost==1、make_stats。
+3. 输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`fetcher/fetcher/sites/facebook/group_task.py`、
+  `fetcher/fetcher/db.py`、`fetcher/tests/test_fb_group_task.py`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 2.1 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md
new file mode 100644
index 0000000..03e74db
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md
@@ -0,0 +1,132 @@
+# Step 2.1 报告 — FbGroupTask（TDD）
+
+## 状态
+
+**DONE** — 13 个新测试全绿；fetcher 全量回归 734 测试通过。
+
+## 实现了什么
+
+### 1. `fetcher/fetcher/sites/facebook/group_task.py`（新建，FbGroupTask）
+
+crawl_fb_group 队列的 local 消费者 Task（SPEC §5.3），对齐 FbPostTask 模式：
+
+- 类属性：`name="fb_group"`、`unit="群"`、`QUEUE="crawl_fb_group"`。
+- `prepare(config)`：`db.reset_fb_groups_in_progress()` 崩溃恢复（in_progress →
+  pending，n>0 打印恢复数），再打印 pending 群数；ShopDB 延迟导入。
+- `acquire_item(ctx)`：`claim_next_eligible(["crawl_fb_group"], consumer_id_for(ctx))`，
+  payload 注入 `id`（对齐 FbDiscoverTask/WaCheckTask）。
+- `label(item)`：`f"{item['url']}（{provider}，≤{limit}帖）"`。
+- `fetch(ctx, item)`：`FetchFbGroupPosts().run(ctx, {"url","provider","limit"})`
+  透传；provider 缺省 None（原子内部缺省 brightdata）、limit 缺省 10。原子零改动。
+- `on_success(ctx, item, result)`：
+  - 逐帖 `db.save_fb_contacts(post["url"], group_id, post["phones"])`（正文全文已
+    在手直接落库，不走 crawl_fb_post）；无 post_url 的项跳过。
+  - `db.mark_fb_group_done(item["url"], len(posts), has_contact)`——`has_contact`
+    取 `data["has_contact"] or data["phones"]`（两者同义，协调者裁定 2）。
+  - stats：有号码 → ok+1（state 含号码数与新增数），无号码 → empty+1
+    （对齐 FbPostTask.on_success 模式，裁定 3 的自然延伸）。
+  - 返回 `len(posts)`（计入批次配额，裁定 1）。
+- `on_giveup`：`db.mark_fb_group_failed(item["url"])` + failed+1，返回
+  `"标记 failed 跳过"`（402/429/网络错误/无帖均置 failed，裁定 4）。
+- `on_abort`：返回 `"群 {url} 留在 in_progress，下次运行自动放回 pending"`（裁定 5）。
+- `giveup_cost(item)`：返回 1。
+- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。
+- 附带 `summary`/`compose`/`empty_message`/`rest_counter`：QueueRouter 委托调用
+  （queue_router.py:187/206/212 分别委托 empty_message/compose/summary），
+  对齐 FbPostTask 参考形态（Step 1.3 评审先例认可此范围）。
+
+FATAL（缺 API key / 未知 provider）由原子返回、Task 框架直接停止，Task 不
+额外处理（对齐 wa_task 处置注释）。
+
+### 2. `fetcher/fetcher/db.py`（+26 行，三个写函数）
+
+- `mark_fb_group_done(url, post_count, has_contact)`：status=done + 回写
+  post_count/has_contact/last_crawled_at=_now()。
+- `mark_fb_group_failed(url)`：status=failed。
+- `reset_fb_groups_in_progress() -> int`：in_progress → pending，返回行数。
+
+全部短事务 + commit，复用 self.conn（ShopDB.__init__ 已设 busy_timeout=30000），
+镜像 mark_fb_post_done/mark_fb_post_failed/reset_fb_posts_in_progress 既有风格。
+
+## 测了什么（13 个测试，`fetcher/tests/test_fb_group_task.py`）
+
+| 测试 | 断言 |
+|---|---|
+| fetch 透传 url/provider/limit | mock 原子 run 收到 `{"url","provider","limit"}` |
+| fetch 缺省 provider/limit | provider=None 透传、limit=10 |
+| on_success 逐帖落号 | fb_contacts post_url 溯源 + group_id 从群 URL 解析；无号码帖不落行 |
+| on_success 群 done 回写 | post_count=2、has_contact=1、last_crawled_at 非空；stats ok=1 |
+| on_success 无号码 | has_contact=0、empty=1、ok=0 |
+| on_giveup 群 failed | status=failed、failed=1 |
+| prepare 崩溃恢复 | 预置 in_progress 行 → prepare 后回 pending |
+| acquire_item 认领 + id 注入 | 认领 crawl_fb_group 工作项、payload 含 id |
+| acquire_item 空队列 | 返回 None |
+| label 格式 | `{url}（apify，≤20帖）` |
+| giveup_cost | 1 |
+| make_stats | `{"ok":0,"empty":0,"failed":0}` |
+| on_abort 短语 | 含 in_progress 与群 URL |
+| _group_id_from_url | 正/斜杠结尾/空/非 FB URL |
+
+落库断言全部用真实 ShopDB 临时库（`tempfile.TemporaryDirectory`），仅原子层 mock。
+
+## TDD 证据
+
+### RED
+
+命令：
+```
+cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_fb_group_task.py"
+```
+输出（失败）：
+```
+ImportError: Failed to import test module: test_fb_group_task
+ModuleNotFoundError: No module named 'fetcher.sites.facebook.group_task'
+Ran 1 test in 0.000s
+FAILED (errors=1)
+```
+符合预期：group_task 模块尚不存在，测试文件（需求转译）先行失败。
+
+### GREEN
+
+实现 group_task.py + db.py 三函数后，同命令输出：
+```
+Ran 13 tests in 0.061s
+OK
+```
+（尾部两行 prepare 打印为任务自身输出，与 test_fb_post_task.py 既有行为一致。）
+
+### 回归
+
+- `-p "test_fb_*.py"`：55 测试 OK
+- 全量 `-s tests`：**734 测试 OK**（db.py 改动无连带破坏）
+
+## 改动的文件
+
+- `fetcher/fetcher/sites/facebook/group_task.py`（新建）
+- `fetcher/fetcher/db.py`（+26 行）
+- `fetcher/tests/test_fb_group_task.py`（新建，13 测试）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-brief.md`（未改动，随 commit 纳入）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md`（本文件）
+
+## 自查
+
+- **完整性**：SPEC §5.3 逐条对照——类属性/prepare/acquire_item/label/fetch/
+  on_success/on_giveup/on_abort/giveup_cost/make_stats 全部实现；§5.6 三写函数
+  齐备。边界：空 phones → empty 计数 + has_contact=0；无帖 → 原子 EMPTY →
+  on_giveup failed（不走 on_success，框架语义）；缺 provider/limit → 原子缺省；
+  缺 API key/未知 provider → FATAL 框架停止。
+- **质量**：命名/结构对齐 post_task.py（wctx_stats、延迟导入、prepare 打印风格、
+  acquire_item 注释）；落号逻辑按协调者裁定（post_url=帖 URL、group_id 从
+  item["url"] 解析、返回 len(posts)）。
+- **纪律**：未动原子、未重构范围外代码；summary/compose/empty_message 因
+  QueueRouter 委托调用而含（1.3 评审先例认可）。YAGNI：未做重试/换 provider/
+  批次配额上游逻辑（Step 2.2/2.4 范围）。
+- **测试**：真实落库断言（临时 ShopDB）；mock 仅限原子层；13 覆盖 + 全量回归。
+
+## 疑虑
+
+1. `test_fetch_defaults_provider_limit` 断言 fetch 把 `provider=None` 透传给原子——
+   原子内部 `params.get("provider") or "brightdata"` 兜底，行为正确；若后续要
+   严格只传三个键的意图不同，可再议（当前与裁定「透传 url/provider/limit」一致）。
+2. prepare/on_success 的 print 会在测试输出尾部出现（与 test_fb_post_task.py
+   行为一致），非失败输出；如需测试输出零噪音可后续统一加 stdout 捕获。
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 7dd0842..8bf3c58 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -850,20 +850,46 @@ class ShopDB:
 
     def reset_fb_posts_in_progress(self) -> int:
         """fb_posts 的 in_progress 重置回 pending（进程中断残留的认领，
         FbPostTask.prepare 启动时调用——reset_daemon_state 只认
         domain_suffix 非空的 contact 队列，不覆盖 fb_posts）。"""
         cur = self.conn.execute(
             "UPDATE fb_posts SET status='pending' WHERE status='in_progress'")
         self.conn.commit()
         return cur.rowcount
 
+    def mark_fb_group_done(self, url: str, post_count: int,
+                           has_contact: bool) -> None:
+        """群采集完成：status=done + 回写 post_count/has_contact/
+        last_crawled_at（FbGroupTask.on_success 调用）。"""
+        self.conn.execute(
+            "UPDATE fb_groups SET status='done', post_count=?, has_contact=?, "
+            "last_crawled_at=? WHERE url=?",
+            (post_count, 1 if has_contact else 0, _now(), url))
+        self.conn.commit()
+
+    def mark_fb_group_failed(self, url: str) -> None:
+        """群采集失败：status=failed（402/429 额度/限流、网络错误、无帖
+        均置 failed；重跑由平台重开批次）。"""
+        self.conn.execute(
+            "UPDATE fb_groups SET status='failed' WHERE url=?", (url,))
+        self.conn.commit()
+
+    def reset_fb_groups_in_progress(self) -> int:
+        """fb_groups 的 in_progress 重置回 pending（进程中断残留的认领，
+        FbGroupTask.prepare 启动时调用——reset_daemon_state 只认
+        domain_suffix 非空的 contact 队列，不覆盖 fb_groups）。"""
+        cur = self.conn.execute(
+            "UPDATE fb_groups SET status='pending' WHERE status='in_progress'")
+        self.conn.commit()
+        return cur.rowcount
+
     def save_fb_posts(self, keyword: str, source: str,
                       posts: list[dict]) -> int:
         """发现层结果落 fb_posts（INSERT OR IGNORE，url UNIQUE 去重；
         同帖二次发现不覆盖 first_seen_at/keyword/source）。
 
         keyword: 溯源查询词；source: 发现来源（'ddg' / 'fb_post'）；posts:
         [{"url", "group_id", "group_name"}, ...]。返回本次实际新增行数。
         """
         now = _now()
         inserted = 0
diff --git a/fetcher/fetcher/sites/facebook/group_task.py b/fetcher/fetcher/sites/facebook/group_task.py
new file mode 100644
index 0000000..5173020
--- /dev/null
+++ b/fetcher/fetcher/sites/facebook/group_task.py
@@ -0,0 +1,176 @@
+# -*- coding: utf-8 -*-
+"""Facebook 群 feed 全量采集任务（daemon crawl_fb_group 队列的 local 消费者）。
+
+任务内容：消费 work_items(crawl_fb_group) 的群 URL → 调 FetchFbGroupPosts
+原子（Bright Data / Apify 第三方 API 拉群帖）→ 逐帖号码落 fb_contacts
+（正文全文已在手，直接落库，无需再走 crawl_fb_post）→ fb_groups 状态机
+done/failed 回写（post_count/has_contact/last_crawled_at）。
+
+FATAL 处置：缺 API key / 未知 provider → 原子返回 FATAL，Task 框架对
+FATAL 直接停止（on_giveup 不会被调），本 Task 不额外处理（SPEC §5.3）。
+
+分层：原子只做「拉 + 提取」，本 Task 做编排与落库（对齐 FbPostTask 模式）。
+"""
+
+from __future__ import annotations
+
+import re
+
+from fetcher.control.task import Task
+from fetcher.core.types import ActionResult
+
+QUEUE = "crawl_fb_group"
+
+# 从群 URL 解析 group_id：facebook.com/groups/{gid}（payload.url 是群 URL）
+_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")
+
+
+def _group_id_from_url(url: str) -> str | None:
+    """群 URL → 群 id；无/非法返回 None。"""
+    m = _GROUP_RE.search(url or "")
+    return m.group(1) if m else None
+
+
+class FbGroupTask(Task):
+    """FB 群全量采集任务：认领 crawl_fb_group 队列的群工作项。"""
+
+    name = "fb_group"
+    unit = "群"
+    batch_unit = ""
+
+    QUEUE = QUEUE
+
+    def __init__(self):
+        self._atom = None
+
+    def _make_atom(self):
+        from fetcher.atoms.facebook_group import FetchFbGroupPosts  # 延迟导入
+        return FetchFbGroupPosts()
+
+    # ---- main 阶段 ----
+
+    def prepare(self, config) -> bool:
+        """崩溃恢复：fb_groups 的 in_progress 重置回 pending（进程中断残留）。
+
+        注意：reset_daemon_state 只认 domain_suffix 非空的 contact 队列，
+        不覆盖 fb_groups；重置放本 Task.prepare（router.prepare 每队列都会调），
+        与 FbPostTask.prepare 语义一致（SPEC §5.3）。
+        """
+        from fetcher.db import ShopDB  # 延迟导入
+        db = ShopDB(config.resolved_db_path())
+        n = db.reset_fb_groups_in_progress()
+        if n:
+            print(f"[0] 已把 {n} 个中断残留的 in_progress 群重置回 pending")
+        pending = db.conn.execute(
+            "SELECT COUNT(*) FROM fb_groups WHERE status='pending'"
+        ).fetchone()[0]
+        print(f"[1] fb_groups 待采集 {pending} 个（daemon 由 work_items 队列供货）")
+        db.close()
+        return True
+
+    def summary(self, all_stats: dict, db_path=None) -> str:
+        from fetcher.db import ShopDB  # 延迟导入
+        ok = sum(s.get("ok", 0) for s in all_stats.values())
+        empty = sum(s.get("empty", 0) for s in all_stats.values())
+        failed = sum(s.get("failed", 0) for s in all_stats.values())
+        db = ShopDB(db_path)
+        n_contacts = db.conn.execute(
+            "SELECT COUNT(*) FROM fb_contacts").fetchone()[0]
+        n_groups = db.conn.execute(
+            "SELECT COUNT(*) FROM fb_groups").fetchone()[0]
+        db.close()
+        return (f"本次完成: 有联系方式 {ok}, 无联系方式 {empty}, 失败 {failed}"
+                f"\n    fb_groups {n_groups} 行，fb_contacts {n_contacts} 个号码")
+
+    # ---- 状态板 ----
+
+    def compose(self, wid: int, f: dict) -> str:
+        return (f"[w{wid}] 群 {f.get('n', 0)}（✓{f.get('ok', 0)} "
+                f"○{f.get('empty', 0)} ✗{f.get('failed', 0)}）| "
+                f"{f.get('group', '-')} | {f.get('state', '初始化')}")
+
+    def make_stats(self) -> dict:
+        return {"ok": 0, "empty": 0, "failed": 0}
+
+    def rest_counter(self, stats: dict) -> int:
+        return sum(stats.values())
+
+    # ---- worker 循环 ----
+
+    def acquire_item(self, ctx):
+        """从 crawl_fb_group 队列认领（LocalLoop/直调场景用；daemon 经
+        QueueRouter 认领时不用本方法，保留实现供直接调用/测试）。"""
+        from fetcher.control.queue_router import consumer_id_for
+        item = ctx.store.db.claim_next_eligible([self.QUEUE],
+                                                consumer_id_for(ctx))
+        if item is None:
+            return None
+        payload = dict(item["payload"])
+        payload["id"] = item["id"]
+        return payload
+
+    def label(self, item) -> str:
+        return f"{item['url']}（{item.get('provider')}，≤{item.get('limit')}帖）"
+
+    def fetch(self, ctx, item) -> ActionResult:
+        """调 FetchFbGroupPosts 原子（params 透传 url/provider/limit）。"""
+        atom = self._atom or self._make_atom()
+        return atom.run(ctx, {
+            "url": item["url"],
+            "provider": item.get("provider"),
+            "limit": int(item.get("limit") or 10),
+        })
+
+    def on_success(self, ctx, item, result: ActionResult) -> int:
+        """逐帖号码落 fb_contacts + 群置 done 回写三字段 + stats。"""
+        data = result.data or {}
+        posts = data.get("posts") or []
+        group_id = _group_id_from_url(item.get("url") or "")
+        db = ctx.store.db
+        # 逐帖落号：正文全文已在手，直接落库（无需再走 crawl_fb_post）
+        n_new = 0
+        for post in posts:
+            post_url = (post or {}).get("url") or ""
+            if not post_url:
+                continue
+            n_new += db.save_fb_contacts(post_url, group_id,
+                                         (post or {}).get("phones") or [])
+        has_contact = bool(data.get("has_contact") or data.get("phones"))
+        db.mark_fb_group_done(item["url"], len(posts), has_contact)
+        stats = self.wctx_stats(ctx)
+        phones = data.get("phones") or []
+        if phones:
+            stats["ok"] += 1
+            state = f"✓ {len(phones)} 个号码（新增 {n_new}）"
+        else:
+            stats["empty"] += 1
+            state = "○ 无联系方式"
+        ctx.set_status(state=state, n=sum(stats.values()),
+                       ok=stats["ok"], empty=stats["empty"],
+                       failed=stats["failed"])
+        return len(posts)  # 返回帖数（计入批次配额）
+
+    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
+        """402/429 额度/限流、网络错误、无帖均置 failed（重跑由平台重开批次）。"""
+        ctx.store.db.mark_fb_group_failed(item["url"])
+        stats = self.wctx_stats(ctx)
+        stats["failed"] += 1
+        ctx.set_status(n=sum(stats.values()), failed=stats["failed"])
+        return "标记 failed 跳过"
+
+    def on_abort(self, ctx, item) -> str:
+        return (f"群 {item['url']} 留在 in_progress，"
+                f"下次运行自动放回 pending")
+
+    def giveup_cost(self, item) -> int:
+        # 群处理完毕（含标记 failed），计入批次配额
+        return 1
+
+    def empty_message(self) -> str:
+        return "没有待采集的群了"
+
+    # ---- 内部 ----
+
+    @staticmethod
+    def wctx_stats(ctx) -> dict:
+        return ctx.state["task"]["stats"]
diff --git a/fetcher/tests/test_fb_group_task.py b/fetcher/tests/test_fb_group_task.py
new file mode 100644
index 0000000..b2c6d0a
--- /dev/null
+++ b/fetcher/tests/test_fb_group_task.py
@@ -0,0 +1,234 @@
+# -*- coding: utf-8 -*-
+"""Step 2.1: FbGroupTask 测试。
+
+覆盖：fetch 透传（url/provider/limit 断言）、on_success 逐帖落号
+（post_url 溯源 + group_id）+ 群 done 回写（post_count/has_contact/
+last_crawled_at）、on_giveup 群 failed、prepare 崩溃恢复（in_progress
+→ pending）、acquire_item 认领 + id 注入、label 格式、giveup_cost、
+make_stats、on_abort 短语。全 mock 原子，不起真实网络/API；落库断言
+用真实 ShopDB 临时库。
+"""
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+from unittest.mock import MagicMock
+
+from fetcher import RunConfig, ShopDB
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.sites.facebook.group_task import FbGroupTask, _group_id_from_url
+
+GROUP_URL = "https://www.facebook.com/groups/185879310028412"
+POST_URL_1 = GROUP_URL + "/posts/1111111111111/"
+POST_URL_2 = GROUP_URL + "/posts/2222222222222/"
+
+
+def _seed_group(db, url=GROUP_URL, status="pending"):
+    db.conn.execute(
+        "INSERT INTO fb_groups (url, group_id, name, source, status,"
+        " first_seen_at) VALUES (?, '185879310028412',"
+        " 'Shenzhen Expats 2026', 'ddg', ?, '2026-08-08 10:00:00')",
+        (url, status))
+    db.conn.commit()
+
+
+class _Ctx:
+    """最小 WorkerContext 替身（store/state/set_status/consumer_kind）。"""
+
+    def __init__(self, db):
+        self.store = MagicMock()
+        self.store.db = db
+        self.state = {"task": {"stats": {"ok": 0, "empty": 0, "failed": 0}}}
+        self.status_calls = []
+        self.consumer_kind = "local"
+        self.wid = 0
+        self.logs = []
+
+    def set_status(self, **kw):
+        self.status_calls.append(kw)
+
+    def log(self, msg):
+        self.logs.append(msg)
+
+
+def _result(posts=None, has_contact=None):
+    """原子 OK 结果：posts 逐帖含 phones（模拟 parse_post 分桶）。"""
+    posts = posts if posts is not None else [
+        {"url": POST_URL_1, "text": "x" * 200,
+         "phones": [{"number": "13812345678", "bucket": "cn_uncertain",
+                     "source": "text"}]},
+        {"url": POST_URL_2, "text": "y" * 200, "phones": []},
+    ]
+    phones = []
+    seen = set()
+    for p in posts:
+        for ph in p.get("phones") or []:
+            if ph["number"] not in seen:
+                seen.add(ph["number"])
+                phones.append(ph)
+    data = {"provider": "brightdata", "group_url": GROUP_URL,
+            "post_count": len(posts), "posts": posts, "phones": phones,
+            "has_contact": has_contact if has_contact is not None
+            else bool(phones)}
+    return ActionResult(Outcome.OK, "ok", data)
+
+
+class FbGroupTaskTest(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "t.db")
+        self.task = FbGroupTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def _ctx(self):
+        return _Ctx(self.db)
+
+    # ---- fetch 透传 ----
+
+    def test_fetch_passes_url_provider_limit_to_atom(self):
+        mock_atom = MagicMock()
+        sentinel = ActionResult(Outcome.OK, "ok", {})
+        mock_atom.run.return_value = sentinel
+        self.task._make_atom = lambda: mock_atom
+        ctx = self._ctx()
+        item = {"url": GROUP_URL, "provider": "apify", "limit": 20}
+        r = self.task.fetch(ctx, item)
+        self.assertIs(r, sentinel)
+        mock_atom.run.assert_called_once()
+        params = mock_atom.run.call_args[0][1]
+        self.assertEqual(params, {"url": GROUP_URL, "provider": "apify",
+                                  "limit": 20})
+
+    def test_fetch_defaults_provider_limit(self):
+        """payload 缺 provider/limit：provider=None 透传（原子缺省
+        brightdata）、limit 取原子缺省 10。"""
+        mock_atom = MagicMock()
+        mock_atom.run.return_value = ActionResult(Outcome.OK, "ok", {})
+        self.task._make_atom = lambda: mock_atom
+        self.task.fetch(self._ctx(), {"url": GROUP_URL})
+        params = mock_atom.run.call_args[0][1]
+        self.assertEqual(params["provider"], None)
+        self.assertEqual(params["limit"], 10)
+
+    # ---- on_success 落库 ----
+
+    def test_on_success_saves_contacts_per_post_and_marks_done(self):
+        _seed_group(self.db)
+        ctx = self._ctx()
+        r = _result()
+        n = self.task.on_success(ctx, {"url": GROUP_URL}, r)
+        self.assertEqual(n, 2)  # 返回帖数（计入批次配额）
+        rows = {row["post_url"]: row for row in self.db.conn.execute(
+            "SELECT * FROM fb_contacts").fetchall()}
+        # 逐帖落号：post_url 溯源 + group_id 从群 URL 解析
+        self.assertEqual(rows[POST_URL_1]["number"], "13812345678")
+        self.assertEqual(rows[POST_URL_1]["group_id"], "185879310028412")
+        # 第二帖无号码 → 无对应 fb_contacts 行
+        self.assertEqual(len(rows), 1)
+        # 群 done 回写三字段
+        group = self.db.conn.execute(
+            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL,)).fetchone()
+        self.assertEqual(group["status"], "done")
+        self.assertEqual(group["post_count"], 2)
+        self.assertEqual(group["has_contact"], 1)
+        self.assertIsNotNone(group["last_crawled_at"])
+        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
+        self.assertEqual(ctx.state["task"]["stats"]["empty"], 0)
+
+    def test_on_success_no_phones_counts_empty_and_has_contact_0(self):
+        _seed_group(self.db)
+        ctx = self._ctx()
+        r = _result(posts=[{"url": POST_URL_1, "text": "x" * 200,
+                            "phones": []}])
+        self.task.on_success(ctx, {"url": GROUP_URL}, r)
+        group = self.db.conn.execute(
+            "SELECT status, post_count, has_contact FROM fb_groups"
+            " WHERE url=?", (GROUP_URL,)).fetchone()
+        self.assertEqual(group["status"], "done")
+        self.assertEqual(group["post_count"], 1)
+        self.assertEqual(group["has_contact"], 0)
+        self.assertEqual(ctx.state["task"]["stats"]["ok"], 0)
+        self.assertEqual(ctx.state["task"]["stats"]["empty"], 1)
+
+    # ---- on_giveup ----
+
+    def test_on_giveup_marks_failed(self):
+        _seed_group(self.db)
+        ctx = self._ctx()
+        phrase = self.task.on_giveup(ctx, {"url": GROUP_URL}, "block",
+                                     "block")
+        self.assertIsInstance(phrase, str)
+        row = self.db.conn.execute(
+            "SELECT status FROM fb_groups WHERE url=?", (GROUP_URL,)).fetchone()
+        self.assertEqual(row[0], "failed")
+        self.assertEqual(ctx.state["task"]["stats"]["failed"], 1)
+
+    # ---- prepare 崩溃恢复 ----
+
+    def test_prepare_resets_in_progress(self):
+        _seed_group(self.db, status="in_progress")
+        _seed_group(self.db, url=GROUP_URL + "2", status="pending")
+        cfg = RunConfig(db_path=Path(self._tmp.name) / "t.db")
+        ok = self.task.prepare(cfg)
+        self.assertTrue(ok)
+        statuses = [r[0] for r in self.db.conn.execute(
+            "SELECT status FROM fb_groups ORDER BY id").fetchall()]
+        self.assertEqual(statuses, ["pending", "pending"])
+
+    # ---- acquire_item ----
+
+    def test_acquire_item_claims_from_queue_with_id(self):
+        ctx = self._ctx()
+        self.db.conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, requires,"
+            " created_at) VALUES ('crawl_fb_group', 'facebook', ?,"
+            " '[\"local\"]', '2026-08-08 10:00:00')",
+            (json.dumps({"url": GROUP_URL, "provider": "brightdata",
+                         "limit": 10}),))
+        self.db.conn.commit()
+        item = self.task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["url"], GROUP_URL)
+        self.assertIn("id", item)
+
+    def test_acquire_item_empty_queue_returns_none(self):
+        ctx = self._ctx()
+        self.assertIsNone(self.task.acquire_item(ctx))
+
+    # ---- label / 配额 / stats / abort ----
+
+    def test_label_format(self):
+        self.assertEqual(
+            self.task.label({"url": GROUP_URL, "provider": "apify",
+                             "limit": 20}),
+            f"{GROUP_URL}（apify，≤20帖）")
+
+    def test_giveup_cost(self):
+        self.assertEqual(self.task.giveup_cost({}), 1)
+
+    def test_make_stats(self):
+        self.assertEqual(self.task.make_stats(),
+                         {"ok": 0, "empty": 0, "failed": 0})
+
+    def test_on_abort_phrase(self):
+        phrase = self.task.on_abort(self._ctx(), {"url": GROUP_URL})
+        self.assertIn("in_progress", phrase)
+        self.assertIn(GROUP_URL, phrase)
+
+    # ---- group_id 解析 ----
+
+    def test_group_id_from_url(self):
+        self.assertEqual(_group_id_from_url(GROUP_URL),
+                         "185879310028412")
+        self.assertEqual(_group_id_from_url(GROUP_URL + "/"),
+                         "185879310028412")
+        self.assertIsNone(_group_id_from_url(""))
+        self.assertIsNone(_group_id_from_url("https://www.1688.com/"))
+
+
+if __name__ == "__main__":
+    unittest.main()
