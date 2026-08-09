# Step 1.3 review package
5dff797 feat(fb): Step 1.3 FbDiscoverTask——discover_fb 队列 local 消费者（DDG 查询→分流落库，TDD）
 .../task-1.3-brief.md                              | 100 +++++++
 .../task-1.3-report.md                             |  80 ++++++
 fetcher/fetcher/sites/facebook/discover_task.py    | 157 +++++++++++
 fetcher/tests/test_fb_discover_task.py             | 302 +++++++++++++++++++++
 4 files changed, 639 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-brief.md
new file mode 100644
index 0000000..0507160
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-brief.md
@@ -0,0 +1,100 @@
+# Step 1.3 — FbDiscoverTask（TDD）
+
+> 这是你的需求唯一来源。PLAN Step 1.3 原文 + SPEC §5.2 精确规格抄录如下。
+
+## PLAN Step 1.3 原文（验收以 checkbox 为准）
+
+- [ ] `fetcher/fetcher/sites/facebook/discover_task.py`：Task 协议实现（SPEC §5.2）：
+      prepare/acquire_item/label/fetch（原子透传节奏）/on_success（save_fb_posts +
+      upsert_fb_groups 分流）/on_giveup/make_stats
+- [ ] 测试（`fetcher/tests/test_fb_discover_task.py`）：fetch 原子透传、on_success
+      分流落库（帖→fb_posts、群→fb_groups、派生群、名称去后缀）、on_giveup 无落库、
+      acquire_item 认领
+- 预估 40min；验收：新测试全绿
+
+## SPEC §5.2 FbDiscoverTask（精确规格）
+
+local 消费者，参照 `fetcher/fetcher/wa_task.py` 的 WaCheckTask 形态：
+
+- 类属性：`name="fb_discover"`、`unit="查询"`、`QUEUE="discover_fb"`。
+- `prepare(config)`：打印队列待处理数（discover 无源表状态机，无需崩溃恢复）；
+  返回 True。
+- `acquire_item(ctx)`：`claim_next_eligible(["discover_fb"], consumer_id_for(ctx))`，
+  payload 注入 `id`（对齐 WaCheckTask）。
+- `label(item)`：`f"{item['query']} 第{item['page']}页"`。
+- `fetch(ctx, item)`：调 FetchDdgSerp 原子，params 透传
+  `query/page/sample_min/sample_max`（节奏取 `ctx.config.sample_min/max`）。
+- `on_success(ctx, item, result)`：把 `result.data["results"]` 分流落库：
+  - 帖 permalink 类 → `db.save_fb_posts(keyword=item["query"], source="ddg",
+    posts=[{"url","group_id","group_name"}...])`；
+  - 全部 FB 群 URL（群主页 + 帖派生）→ `db.upsert_fb_groups([{"url","group_id",
+    "name"}...])`（name 取 SERP 标题去 `" | Facebook"` / `" - Facebook"` 后缀，
+    近似溯源）；
+  - stats 计数（ok/empty/failed），返回新增帖数（计入批次配额）。
+- `on_giveup(ctx, item, reason, kind)`：BLOCKED/NET_ERROR/EMPTY 无落库，仅日志短语
+  + stats；返回短语。
+- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。
+
+## 协调者裁定（覆盖 SPEC 未定细节）
+
+1. **分流依据**：`result.data["results"]` 每项是
+   `{"url","title","kind","group_id","group_url"}`（Step 1.2 FetchDdgSerp OK 输出）。
+   - `kind == "post"` → save_fb_posts（url=该项 url，group_id，group_name=净化标题）；
+   - `kind == "group"` → upsert_fb_groups（url=该项 group_url 或 url，group_id，
+     name=净化标题）；kind 为 None 的非 FB 条目跳过。
+2. **帖派生群也 upsert**：SPEC §5.2 说「全部 FB 群 URL（群主页 + 帖派生）→
+   upsert_fb_groups」。即 post 类条目除了 save_fb_posts，其 group_url 也要进
+   upsert_fb_groups（group_id 取自该项）。
+3. **名称净化**：title 去掉 `" | Facebook"` 与 `" - Facebook"` 后缀（strip 后
+   endswith 检查，去一次即可；无则原样）。这是「近似溯源」，群名允许为空串。
+4. **返回新增帖数**：on_success 返回 `save_fb_posts` 的返回值（int，计入批次配额）。
+5. **stats 口径**：有 results 且落库 → ok+1；results 空（EMPTY 已由原子返回，正常
+   OK 路径不会出现空，但防御）→ empty；on_giveup → failed。对齐 FbPostTask 的
+   wctx_stats/set_status 用法（读 post_task.py 参照）。
+6. **on_giveup 的 kind 参数**：Task 协议 on_giveup(ctx, item, reason, kind) 返回
+   str 短语；BLOCKED/NET_ERROR/EMPTY 均不落库。给 BLOCKED 一个让出型冷却登记？
+   不需要——LocalLoop 的冷却由框架处理（冷却键=queue 名，自动）。仅日志短语。
+7. **prepare 打印**：`print(f"[fb_discover] 队列待处理: {n}")` 风格对齐 WaCheckTask。
+8. **set_status**：on_success 里调用 `ctx.set_status(state=..., n=..., ok=..., empty=..., failed=...)`（对齐 FbPostTask.on_success 的 stats 更新模式，见 post_task.py L156-163）。
+
+## 代码库上下文（brief 之外你需要知道的）
+
+- **Task 协议**：`fetcher/fetcher/control/task.py` 的 Task 类（prepare/acquire_item/
+  label/fetch/validate/on_success/on_giveup/on_abort/giveup_cost/make_stats/
+  rest_counter）。
+- **参照实现**：
+  - `fetcher/fetcher/wa_task.py` WaCheckTask（acquire_item payload 注入 id、
+    make_stats、on_giveup 短语）；
+  - `fetcher/fetcher/sites/facebook/post_task.py` FbPostTask（on_success 落库 +
+    set_status 模式、wctx_stats 用法）。
+- **DB 函数**（Step 1.1 已实现）：`db.save_fb_posts(keyword, source, posts)`、
+  `db.upsert_fb_groups(groups)`（条目键 url/group_id/name，可选 source 键）。
+- **FetchDdgSerp 原子**（Step 1.2 已实现）：`fetcher/fetcher/atoms/facebook_discover.py`，
+  run(ctx, params) → ActionResult；OK 的 data 含 results 列表。
+- **ctx 契约**：`ctx.config.sample_min/sample_max`（RunConfig 浮点，缺省 13/20——
+  原子会抬到 60 floor）；`consumer_id_for(ctx)` 在
+  `fetcher/fetcher/control/queue_router.py`。
+- **测试模式**：现有 test_fb_post_task.py、test_wa_task.py 参照（mock 原子、临时
+  ShopDB、构造 ctx）。测试需要构造 WorkerContext（fetcher/fetcher/core/context.py，
+  字段可空装配）+ 临时 DB。
+- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
+  -s tests -p "test_fb_discover_task.py"`；回归 `-p "test_fb_*.py"` 与
+  `-p "test_wa_task*.py"`。
+
+## TDD 纪律
+
+1. 先失败测试 → RED → 最小实现 → GREEN。mock 只在原子层（mock FetchDdgSerp.run），
+  落库用真实 ShopDB 临时库断言。
+2. 测试覆盖：fetch 原子透传（params 含 query/page/sample_min/sample_max）、on_success
+  分流（帖→fb_posts 且 keyword/source='ddg' 溯源、群→fb_groups、帖派生群同时进两表、
+  名称去 `| Facebook` 后缀、kind=None 跳过）、on_giveup 无落库 + 短语、acquire_item
+  认领 + payload id 注入、make_stats、stats 计数。
+3. 输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`fetcher/fetcher/sites/facebook/discover_task.py`、
+  `fetcher/tests/test_fb_discover_task.py`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 1.3 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-report.md
new file mode 100644
index 0000000..3937da1
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-report.md
@@ -0,0 +1,80 @@
+# Step 1.3 报告 — FbDiscoverTask（TDD）
+
+## 实现了什么
+
+`fetcher/fetcher/sites/facebook/discover_task.py`（新文件，SPEC §5.2）：
+discover_fb 队列的 local 消费者 Task，消费 work_items → 调 FetchDdgSerp 原子 → 按 kind 分流落库。
+
+- 类属性：`name="fb_discover"`、`unit="查询"`、`QUEUE="discover_fb"`。
+- `prepare(config)`：打印 `[fb_discover] 队列待处理: {n}`（discover 无源表状态机，无崩溃恢复），返回 True。
+- `acquire_item(ctx)`：`claim_next_eligible(["discover_fb"], consumer_id_for(ctx))`，payload 注入 `id`（对齐 WaCheckTask）。
+- `label(item)`：`f"{item['query']} 第{item['page']}页"`。
+- `fetch(ctx, item)`：调 FetchDdgSerp 原子，params 透传 `query/page/sample_min/sample_max`（节奏取 `ctx.config.sample_min/max`）。
+- `on_success(ctx, item, result)`：`result.data["results"]` 分流落库：
+  - `kind=="post"` → `db.save_fb_posts(keyword=item["query"], source="ddg", posts=[{"url","group_id","group_name"}...])`；
+    帖派生群（`group_url` 非空时）同时进 `db.upsert_fb_groups([{"url","group_id","name"}...])`（协调者裁定 2）；
+  - `kind=="group"` → `db.upsert_fb_groups`（url 取 `group_url` 或 url，协调者裁定 1）；
+  - `kind is None`（非 FB 条目）跳过（协调者裁定 1）；
+  - 名称净化 `_clean_title`：strip 后 endswith 检查去 `" | Facebook"` / `" - Facebook"` 后缀一次，无则原样（协调者裁定 3）；空标题落空串；
+  - 空 results（防御）→ stats `empty+1`，返回 0；
+  - 正常路径 stats `ok+1`，`ctx.set_status(state=..., n=..., ok=..., empty=..., failed=...)`（对齐 FbPostTask L156-163 模式），返回 `save_fb_posts` 返回值（新增帖数，协调者裁定 4/8）。
+- `on_giveup(ctx, item, reason, kind)`：BLOCKED/NET_ERROR/EMPTY 一律不落库，仅 `ctx.log` 短语 + stats `failed+1` + set_status（协调者裁定 5/6；冷却由 LocalLoop/框架按 queue 名自动处理）。
+- `make_stats()`：`{"ok": 0, "empty": 0, "failed": 0}`。
+- 附加（对齐 WaCheckTask 参考形态、daemon 路径需要）：`summary()`（聚合三计数，QueueRouter.summary 委托调用）、`empty_message()`（QueueRouter.empty_message 委托调用）。
+
+## 测了什么（`fetcher/tests/test_fb_discover_task.py`，21 个测试）
+
+- **fetch 原子透传**：params 含 query/page/sample_min/sample_max（13.0/20.0），返回原样透传。
+- **on_success 分流**（真实 ShopDB 临时库断言落库）：
+  - 帖 → fb_posts（url/group_id/group_name/keyword/source='ddg' 溯源）+ 帖派生群同时进 fb_groups；
+  - 群主页 → 仅 fb_groups（url 取 group_url），名称去 `- Facebook` 后缀；
+  - 混合（帖+群+非 FB）→ 两表各得其位，同 URL 群 INSERT OR IGNORE 去重；
+  - kind=None 跳过（不落任何表）；
+  - 名称净化边界：` | Facebook`（含首尾空白）、` - Facebook`、无后缀原样、空标题落空串；
+  - 帖无 group_id/group_url（防御）→ fb_posts 落 NULL，不派生群行不崩；
+  - stats 计数 + set_status 携带 ok/empty/failed/n；
+  - 空 results（防御）→ empty+1 返回 0。
+- **on_giveup**：不落库 + 返回短语 + failed+1。
+- **acquire_item**：认领最老 pending 项、payload id 注入、行置 claimed/claimed_by=local0；空队列返回 None。
+- **元数据**：类属性、make_stats、label、prepare 返回 True。
+
+## TDD 证据
+
+**RED**（实现前，测试先写）：
+```
+$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_fb_discover_task.py"
+ImportError: Failed to import test module: test_fb_discover_task
+ModuleNotFoundError: No module named 'fetcher.sites.facebook.discover_task'
+Ran 1 test in 0.000s
+FAILED (errors=1)
+```
+失败原因符合预期：`discover_task.py` 尚不存在，功能缺失（不是笔误）。
+
+**GREEN**（最小实现后）：
+```
+$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_fb_discover_task.py"
+.....................
+Ran 21 tests in 0.074s
+OK
+[fb_discover] 队列待处理: 1
+```
+
+**回归**：
+- `-p "test_fb_*.py"`：Ran 42 tests, OK
+- `-p "test_wa_task*.py"`：Ran 29 tests, OK
+- 全量 `-p ""`：Ran 720 tests, OK（31.4s，输出干净无 error/warning）
+
+## 改动的文件
+
+- `fetcher/fetcher/sites/facebook/discover_task.py`（新）
+- `fetcher/tests/test_fb_discover_task.py`（新）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-report.md`（本报告）
+
+## 自查发现
+
+- **完整性**：brief 清单 7 项 hook + 协调者 8 条裁定全部落实；边界（kind=None、空 results、空标题、无 group_id）均有测试。
+- **质量**：命名/结构对齐 wa_task.py（WaCheckTask 形态）与 post_task.py（wctx_stats/set_status 模式）；原子经 `_make_atom` 延迟导入（与既有 Task 一致）；落库全走 db.py 现成短事务函数。
+- **纪律**：未重构任务范围外代码；`summary`/`empty_message` 为对齐参考形态 + daemon QueueRouter 委托调用所需（非 YAGNI 越界）。
+- **疑虑**：
+  1. 帖派生群在 `group_url` 缺失（防御场景，原子正常不会产生）时选择不派生群行，而非回退到帖 URL——避免向 fb_groups 写入 permalink 污染；kind=="group" 则按协调者裁定回退 `url`。
+  2. stats 口径「有 results 且落库 → ok+1」：全 kind=None 条目（有 results 但零落库）按 ok 计——查询本身成功产生结果，非 FB 判定属于上层过滤。
diff --git a/fetcher/fetcher/sites/facebook/discover_task.py b/fetcher/fetcher/sites/facebook/discover_task.py
new file mode 100644
index 0000000..93704ae
--- /dev/null
+++ b/fetcher/fetcher/sites/facebook/discover_task.py
@@ -0,0 +1,157 @@
+# -*- coding: utf-8 -*-
+"""FbDiscoverTask：discover_fb 队列的 local 消费者（SPEC §5.2）。
+
+消费 work_items(discover_fb) 的查询任务 → 调 FetchDdgSerp 原子（DDG 裸抓
+FB 群帖 SERP）→ 按 kind 分流落库：帖 permalink → fb_posts（save_fb_posts，
+keyword/source 溯源）；FB 群 URL（群主页 + 帖派生）→ fb_groups
+（upsert_fb_groups，name 去 " | Facebook"/" - Facebook" 后缀近似溯源）；
+kind=None 的非 FB 条目跳过。
+
+local 消费者（LocalLoop 驱动，无浏览器循环）：OK→on_success 落库；
+BLOCKED/NET_ERROR/EMPTY→on_giveup（不落库，仅日志短语 + stats failed）。
+节奏取 ctx.config.sample_min/max 透传原子（原子抬到 60s 地板）。
+"""
+
+from __future__ import annotations
+
+from fetcher.control.task import Task
+from fetcher.core.types import ActionResult
+
+QUEUE = "discover_fb"
+
+# SERP 标题站点后缀（近似溯源用；strip 后 endswith 匹配，去一次）
+_TITLE_SUFFIXES = (" | Facebook", " - Facebook")
+
+
+def _clean_title(title: str) -> str:
+    """SERP 标题净化：去 " | Facebook" / " - Facebook" 后缀（无则原样）。"""
+    t = (title or "").strip()
+    for suffix in _TITLE_SUFFIXES:
+        if t.endswith(suffix):
+            return t[:-len(suffix)].strip()
+    return t
+
+
+class FbDiscoverTask(Task):
+    """discover_fb 队列执行器：DDG 查询 → 分流落库（SPEC §5.2）。"""
+
+    name = "fb_discover"
+    unit = "查询"
+    batch_unit = ""
+
+    QUEUE = QUEUE
+
+    def __init__(self):
+        self._atom = None
+
+    def _make_atom(self):
+        from fetcher.atoms.facebook_discover import FetchDdgSerp  # 延迟导入
+        return FetchDdgSerp()
+
+    # ---- main 阶段 ----
+
+    def prepare(self, config) -> bool:
+        """打印队列待处理数（discover 无源表状态机，无需崩溃恢复）。"""
+        from fetcher.db import ShopDB  # 延迟导入
+        db = ShopDB(config.resolved_db_path())
+        pending = db.conn.execute(
+            "SELECT COUNT(*) FROM work_items WHERE queue=? "
+            "AND status='pending'", (QUEUE,)).fetchone()[0]
+        print(f"[fb_discover] 队列待处理: {pending}")
+        db.close()
+        return True
+
+    def summary(self, all_stats: dict, db_path=None) -> str:
+        ok = sum(s.get("ok", 0) for s in all_stats.values())
+        empty = sum(s.get("empty", 0) for s in all_stats.values())
+        failed = sum(s.get("failed", 0) for s in all_stats.values())
+        return (f"fb_discover: 成功 {ok}，空 {empty}，失败 {failed}")
+
+    def make_stats(self) -> dict:
+        return {"ok": 0, "empty": 0, "failed": 0}
+
+    # ---- worker 循环 ----
+
+    def acquire_item(self, ctx):
+        """从 discover_fb 队列认领（LocalLoop 经 QueueRouter 路由时不用本
+        方法；保留实现供直接调用/测试）。"""
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
+        return f"{item['query']} 第{item['page']}页"
+
+    def fetch(self, ctx, item) -> ActionResult:
+        """调 FetchDdgSerp 原子（params 透传 query/page/sample_min/max）。"""
+        atom = self._atom or self._make_atom()
+        return atom.run(ctx, {
+            "query": item["query"],
+            "page": int(item.get("page") or 1),
+            "sample_min": float(ctx.config.sample_min),
+            "sample_max": float(ctx.config.sample_max),
+        })
+
+    def on_success(self, ctx, item, result: ActionResult) -> int:
+        """results 分流落库：帖→fb_posts（含派生群→fb_groups）；群→fb_groups；
+        kind=None 跳过。返回新增帖数（计入批次配额）。"""
+        results = (result.data or {}).get("results") or []
+        if not results:
+            stats = self.wctx_stats(ctx)
+            stats["empty"] += 1
+            ctx.set_status(state="○ 无结果", n=sum(stats.values()),
+                           empty=stats["empty"])
+            return 0
+        posts: list[dict] = []
+        groups: list[dict] = []
+        for r in results:
+            kind = r.get("kind")
+            url = r.get("url") or ""
+            title = _clean_title(r.get("title"))
+            group_id = r.get("group_id")
+            if kind == "post":
+                posts.append({"url": url, "group_id": group_id,
+                              "group_name": title})
+                gurl = r.get("group_url") or ""
+                if gurl:
+                    groups.append({"url": gurl, "group_id": group_id,
+                                   "name": title})
+            elif kind == "group":
+                gurl = r.get("group_url") or url
+                groups.append({"url": gurl, "group_id": group_id,
+                               "name": title})
+            # kind=None 的非 FB 条目跳过
+        db = ctx.store.db
+        n_posts = db.save_fb_posts(keyword=item["query"], source="ddg",
+                                   posts=posts) if posts else 0
+        if groups:
+            db.upsert_fb_groups(groups)
+        stats = self.wctx_stats(ctx)
+        stats["ok"] += 1
+        state = f"✓ 新增 {n_posts} 帖（群 {len(groups)}）"
+        ctx.set_status(state=state, n=sum(stats.values()),
+                       ok=stats["ok"], empty=stats["empty"],
+                       failed=stats["failed"])
+        return n_posts
+
+    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
+        """BLOCKED/NET_ERROR/EMPTY：不落库，仅日志短语 + failed 计数。"""
+        ctx.log(f"[fb_discover] 放弃：{reason}")
+        stats = self.wctx_stats(ctx)
+        stats["failed"] += 1
+        ctx.set_status(n=sum(stats.values()), failed=stats["failed"])
+        return "标记 failed 跳过"
+
+    def empty_message(self) -> str:
+        return "discover_fb 队列空"
+
+    # ---- 内部 ----
+
+    @staticmethod
+    def wctx_stats(ctx) -> dict:
+        return ctx.state["task"]["stats"]
diff --git a/fetcher/tests/test_fb_discover_task.py b/fetcher/tests/test_fb_discover_task.py
new file mode 100644
index 0000000..8071588
--- /dev/null
+++ b/fetcher/tests/test_fb_discover_task.py
@@ -0,0 +1,302 @@
+# -*- coding: utf-8 -*-
+"""Step 1.3: FbDiscoverTask 测试（SPEC §5.2）。
+
+覆盖：fetch 原子透传（query/page/sample_min/max）、on_success 分流落库
+（帖→fb_posts 且 keyword/source='ddg' 溯源、群→fb_groups、帖派生群同时进
+两表、名称去 | Facebook / - Facebook 后缀、kind=None 跳过、空 results 防御、
+无 group_id 防御）、on_giveup 无落库 + 短语 + failed 计数、acquire_item 认领
++ payload id 注入、prepare/label/make_stats、名称净化边界。mock 只在原子层
+（FetchDdgSerp.run），落库用真实 ShopDB 临时库断言。
+"""
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+from unittest.mock import MagicMock
+
+from fetcher import IdentityStore, RunConfig, ShopDB, WorkerContext
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.sites.facebook.discover_task import (
+    FbDiscoverTask,
+    QUEUE,
+    _clean_title,
+)
+
+# 帖 permalink 与派生群主页（对齐 FetchDdgSerp OK 输出形态）
+POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
+            "1437583168191347/")
+GROUP_URL = "https://www.facebook.com/groups/185879310028412"
+GID = "185879310028412"
+QUERY = "site:facebook.com/groups 跨境电商 whatsapp"
+
+
+def _ctx(db, consumer_kind="local", wid=0):
+    """真实 WorkerContext（字段可空装配）+ IdentityStore 包装临时库；
+    set_status 记录调用供断言。"""
+    ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
+    ctx.consumer_kind = consumer_kind
+    ctx.wid = wid
+    ctx.store = IdentityStore(db)
+    ctx.state["task"] = {"stats": {"ok": 0, "empty": 0, "failed": 0}}
+    ctx.status_calls = []
+    ctx.set_status = lambda **kw: ctx.status_calls.append(kw)
+    return ctx
+
+
+def _result(results):
+    return ActionResult(Outcome.OK, "ok", {"results": results})
+
+
+def _post_result(url=POST_URL, title="深圳跨境电商群 | Facebook"):
+    return {"url": url, "title": title, "kind": "post",
+            "group_id": GID, "group_url": GROUP_URL}
+
+
+def _group_result(title="深圳外贸交流 - Facebook"):
+    return {"url": GROUP_URL, "title": title, "kind": "group",
+            "group_id": GID, "group_url": GROUP_URL}
+
+
+def _non_fb_result():
+    return {"url": "https://www.1688.com/", "title": "1688 首页",
+            "kind": None, "group_id": None, "group_url": None}
+
+
+class FbDiscoverTaskTest(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "t.db")
+        self.task = FbDiscoverTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def _fb_posts(self):
+        return self.db.conn.execute(
+            "SELECT url, group_id, group_name, keyword, source FROM fb_posts"
+        ).fetchall()
+
+    def _fb_groups(self):
+        return self.db.conn.execute(
+            "SELECT url, group_id, name, source FROM fb_groups"
+        ).fetchall()
+
+    def _enqueue(self, query=QUERY, page=1):
+        self.db.conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, requires,"
+            " created_at) VALUES (?, NULL, ?, ?, '2026-08-09 10:00:00')",
+            (QUEUE, json.dumps({"query": query, "page": page},
+                               ensure_ascii=False), '["local"]'))
+        self.db.conn.commit()
+
+    # ---- fetch 原子透传 ----
+
+    def test_fetch_passes_query_page_and_pacing_to_atom(self):
+        """fetch 调 FetchDdgSerp 原子，params 透传 query/page/sample_min/max。"""
+        mock_atom = MagicMock()
+        sentinel = ActionResult(Outcome.OK, "ok", {})
+        mock_atom.run.return_value = sentinel
+        self.task._make_atom = lambda: mock_atom
+        cfg = RunConfig(sample_min=13.0, sample_max=20.0)
+        ctx = WorkerContext(config=cfg, log=lambda m: None)
+        item = {"query": QUERY, "page": 2}
+        r = self.task.fetch(ctx, item)
+        self.assertIs(r, sentinel)
+        mock_atom.run.assert_called_once()
+        params = mock_atom.run.call_args[0][1]
+        self.assertEqual(params, {"query": QUERY, "page": 2,
+                                  "sample_min": 13.0, "sample_max": 20.0})
+
+    # ---- on_success 分流落库 ----
+
+    def test_on_success_post_goes_to_fb_posts_and_derived_group_to_groups(self):
+        """帖 permalink → fb_posts（keyword/source='ddg' 溯源）；帖派生群同时
+        进 fb_groups；名称去 | Facebook 后缀。返回新增帖数。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result([_post_result()]))
+        self.assertEqual(n, 1)
+        posts = self._fb_posts()
+        self.assertEqual(len(posts), 1)
+        p = posts[0]
+        self.assertEqual(p["url"], POST_URL)
+        self.assertEqual(p["group_id"], GID)
+        self.assertEqual(p["group_name"], "深圳跨境电商群")
+        self.assertEqual(p["keyword"], QUERY)
+        self.assertEqual(p["source"], "ddg")
+        groups = self._fb_groups()
+        self.assertEqual(len(groups), 1)
+        g = groups[0]
+        self.assertEqual(g["url"], GROUP_URL)
+        self.assertEqual(g["group_id"], GID)
+        self.assertEqual(g["name"], "深圳跨境电商群")
+        self.assertEqual(g["source"], "ddg")
+
+    def test_on_success_group_goes_to_fb_groups_only(self):
+        """群主页 → 仅 fb_groups（url 取 group_url），不落 fb_posts。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result([_group_result()]))
+        self.assertEqual(n, 0)
+        self.assertEqual(len(self._fb_posts()), 0)
+        groups = self._fb_groups()
+        self.assertEqual(len(groups), 1)
+        self.assertEqual(groups[0]["url"], GROUP_URL)
+        self.assertEqual(groups[0]["name"], "深圳外贸交流")  # 去 - Facebook 后缀
+
+    def test_on_success_mixed_kinds_fan_out(self):
+        """混合条目：帖 + 群 + 非 FB → 两表各得其位，非 FB 跳过。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(
+            ctx, {"query": QUERY, "page": 1},
+            _result([_post_result(), _group_result(), _non_fb_result()]))
+        self.assertEqual(n, 1)
+        self.assertEqual(len(self._fb_posts()), 1)
+        groups = self._fb_groups()
+        # 帖派生群 + 群主页同 URL → INSERT OR IGNORE 去重为 1 行
+        self.assertEqual(len(groups), 1)
+        self.assertEqual(groups[0]["url"], GROUP_URL)
+
+    def test_on_success_kind_none_skipped(self):
+        """kind=None 的非 FB 条目跳过（不落任何表），stats 仍算 ok。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result([_non_fb_result()]))
+        self.assertEqual(n, 0)
+        self.assertEqual(len(self._fb_posts()), 0)
+        self.assertEqual(len(self._fb_groups()), 0)
+        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
+
+    def test_on_success_cleans_name_suffixes(self):
+        """名称去 | Facebook / - Facebook 后缀（strip 后 endswith，去一次）；
+        无后缀原样；空标题落空串。"""
+        ctx = _ctx(self.db)
+        results = [
+            _post_result(url=POST_URL + "1", title=" 群A | Facebook "),
+            _post_result(url=POST_URL + "2", title="群B - Facebook"),
+            _post_result(url=POST_URL + "3", title="群C（无后缀）"),
+            _post_result(url=POST_URL + "4", title=""),
+        ]
+        self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                             _result(results))
+        names = sorted(r["group_name"] for r in self._fb_posts())
+        self.assertEqual(names, ["", "群A", "群B", "群C（无后缀）"])
+
+    def test_on_success_post_without_group_id(self):
+        """帖无 group_id/group_url（防御）→ fb_posts 落 group_id NULL，
+        不派生群行，不崩。"""
+        ctx = _ctx(self.db)
+        results = [{"url": POST_URL, "title": "孤儿帖 | Facebook",
+                    "kind": "post", "group_id": None, "group_url": None}]
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result(results))
+        self.assertEqual(n, 1)
+        p = self._fb_posts()[0]
+        self.assertIsNone(p["group_id"])
+        self.assertEqual(len(self._fb_groups()), 0)
+
+    def test_on_success_counts_ok_and_calls_set_status(self):
+        """有 results 且落库 → ok+1；set_status 携带 ok/empty/failed 计数。"""
+        ctx = _ctx(self.db)
+        self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                             _result([_post_result()]))
+        self.assertEqual(ctx.state["task"]["stats"],
+                         {"ok": 1, "empty": 0, "failed": 0})
+        last = ctx.status_calls[-1]
+        self.assertEqual(last["ok"], 1)
+        self.assertEqual(last["empty"], 0)
+        self.assertEqual(last["failed"], 0)
+        self.assertEqual(last["n"], 1)
+
+    def test_on_success_empty_results_counts_empty(self):
+        """results 空（防御：正常 OK 路径不会出现）→ empty+1，返回 0。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result([]))
+        self.assertEqual(n, 0)
+        stats = ctx.state["task"]["stats"]
+        self.assertEqual(stats, {"ok": 0, "empty": 1, "failed": 0})
+        self.assertEqual(len(self._fb_posts()), 0)
+        self.assertEqual(len(self._fb_groups()), 0)
+
+    # ---- on_giveup ----
+
+    def test_on_giveup_no_db_write_and_counts_failed(self):
+        """BLOCKED/NET_ERROR/EMPTY 均不落库，仅 failed+1 + 返回短语。"""
+        ctx = _ctx(self.db)
+        phrase = self.task.on_giveup(ctx, {"query": QUERY, "page": 1},
+                                     "DDG 限流（HTTP 202）", "block")
+        self.assertIsInstance(phrase, str)
+        self.assertTrue(phrase)
+        self.assertEqual(len(self._fb_posts()), 0)
+        self.assertEqual(len(self._fb_groups()), 0)
+        self.assertEqual(ctx.state["task"]["stats"]["failed"], 1)
+
+    # ---- acquire_item ----
+
+    def test_acquire_item_claims_discover_fb_and_injects_id(self):
+        """认领 discover_fb 最老 pending 项，payload 注入 id；行置 claimed。"""
+        self._enqueue()
+        self._enqueue(query=QUERY + "2", page=2)
+        ctx = _ctx(self.db)
+        item = self.task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["query"], QUERY)
+        self.assertEqual(item["page"], 1)
+        self.assertIn("id", item)
+        row = self.db.conn.execute(
+            "SELECT status, claimed_by FROM work_items"
+            " WHERE payload_json LIKE ?", ("%" + QUERY + "%",)).fetchone()
+        self.assertEqual(row[0], "claimed")
+        self.assertEqual(row[1], "local0")
+
+    def test_acquire_item_empty_queue_returns_none(self):
+        ctx = _ctx(self.db)
+        self.assertIsNone(self.task.acquire_item(ctx))
+
+    # ---- 元数据 ----
+
+    def test_class_attrs(self):
+        self.assertEqual(FbDiscoverTask.name, "fb_discover")
+        self.assertEqual(FbDiscoverTask.unit, "查询")
+        self.assertEqual(FbDiscoverTask.QUEUE, "discover_fb")
+
+    def test_make_stats(self):
+        self.assertEqual(self.task.make_stats(),
+                         {"ok": 0, "empty": 0, "failed": 0})
+
+    def test_label(self):
+        item = {"query": QUERY, "page": 3}
+        self.assertEqual(self.task.label(item), f"{QUERY} 第3页")
+
+    def test_prepare_returns_true(self):
+        self._enqueue()
+        cfg = RunConfig(db_path=Path(self._tmp.name) / "t.db")
+        self.assertTrue(self.task.prepare(cfg))
+
+
+class CleanTitleTest(unittest.TestCase):
+    def test_strips_pipe_facebook_suffix(self):
+        self.assertEqual(_clean_title("深圳跨境电商群 | Facebook"),
+                         "深圳跨境电商群")
+
+    def test_strips_dash_facebook_suffix(self):
+        self.assertEqual(_clean_title("深圳外贸交流 - Facebook"),
+                         "深圳外贸交流")
+
+    def test_no_suffix_unchanged(self):
+        self.assertEqual(_clean_title("普通标题"), "普通标题")
+
+    def test_strips_whitespace_before_match(self):
+        self.assertEqual(_clean_title("  群A | Facebook  "), "群A")
+
+    def test_blank_or_none(self):
+        self.assertEqual(_clean_title(""), "")
+        self.assertEqual(_clean_title(None), "")
+        self.assertEqual(_clean_title("   "), "")
+
+
+if __name__ == "__main__":
+    unittest.main()
