# Step 3.2 review package
6896454 feat(fb): Step 3.2 enqueue_fb_discover/group_batch 真实实现（TDD）+ runner 懒导入收尾
 .../task-3.2-brief.md                              |  87 +++++++++++++++
 .../task-3.2-report.md                             | 115 ++++++++++++++++++++
 platform/server/app/db.py                          |  96 +++++++++++++++++
 platform/server/app/runner.py                      |  10 +-
 platform/server/tests/test_batch_tasks.py          | 118 +++++++++++++++++++++
 5 files changed, 420 insertions(+), 6 deletions(-)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-brief.md
new file mode 100644
index 0000000..4560655
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-brief.md
@@ -0,0 +1,87 @@
+# Step 3.2 — app/db.py enqueue 双函数（TDD）
+
+> 这是你的需求唯一来源。PLAN Step 3.2 原文 + SPEC §6.2 精确规格抄录如下。
+
+## PLAN Step 3.2 原文（验收以 checkbox 为准）
+
+- [ ] `enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`：换行拆词 × 页
+      展开，payload {"kind","engine","query","page"}，requires='["local"]'，
+      同 query+page 已有 pending 跳过，keywords 空→0
+- [ ] `enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`：
+      BEGIN IMMEDIATE 单事务 SELECT pending fb_groups → INSERT items → 置
+      in_progress；fb_groups 表不存在→0（防御性探测）
+- [ ] 测试（扩展 test_batch_tasks.py）：展开数/幂等/空关键词/限量/表缺失返回 0/
+      payload 断言
+- 预估 40min；验收：新测试全绿
+
+## SPEC §6.2 app/db.py 新增（精确规格）
+
+- `enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`：
+  关键词（换行分隔）逐词 × 页码展开；payload
+  `{"kind":"serp","engine":"ddg","query":kw,"page":N}`；`requires='["local"]'`、
+  site=NULL、batch_id；**幂等：同 query+page 已有 pending 跳过**；keywords 空 → 0。
+  返回入队 item 数。
+- `enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`：
+  `BEGIN IMMEDIATE` 单事务：SELECT pending fb_groups（limit>0 限量）→ INSERT
+  work_items（payload `{"url","provider","limit"}`，limit=posts_per_group）→
+  源行置 in_progress；**fb_groups 表不存在（fetcher 侧未建）→ 返回 0**（防御性
+  探测，对齐 enqueue_fb_post_batch）。返回入队行数。
+
+## 协调者裁定（覆盖 SPEC 未定细节）
+
+1. **收尾 Step 3.1 的懒导入**（Step 3.1 reviewer Minor ② 已列为必做）：本 Step 实现
+   两个函数后，把 runner.py enqueue_batch_for_task 两分支的懒导入并入函数顶部既有
+   的 `from app.db import (...)` 集中 import（enqueue_fb_discover_batch /
+   enqueue_fb_group_batch 加入其中，删掉分支内懒导入）。这是跨 Step 的收尾，必须做。
+2. **enqueue_fb_discover_batch 的展开逻辑**：
+   - keywords 按换行拆词（`splitlines()`），strip 后过滤空行；空 → 0。
+   - 每词 × 每页（1..pages，pages<1 视为 1）；payload `{"kind":"serp","engine":"ddg",
+     "query":kw,"page":N}`；INSERT (queue='discover_fb', site=NULL, batch_id,
+     payload_json, requires='["local"]', created_at=_bj_now())。
+   - 幂等：INSERT 前查 `work_items WHERE queue='discover_fb' AND status='pending'
+     AND json_extract(payload_json,'$.query')=? AND json_extract(payload_json,
+     '$.page')=?` 存在则跳过（参照 enqueue_feeder_batch 的 json_extract 幂等模式）。
+   - 返回实际入队数。
+3. **enqueue_fb_group_batch 的事务模式**：对齐 enqueue_fb_post_batch——
+   sqlite3.connect(DB_PATH, timeout=30) + PRAGMA busy_timeout=30000 + sqlite_master
+   探测 fb_groups 表（无 → 0）+ BEGIN IMMEDIATE + SELECT pending fb_groups
+   (ORDER BY first_seen_at, id，limit>0 时 LIMIT) + INSERT work_items
+   (queue='crawl_fb_group', site=NULL, batch_id, payload `{"url":r["url"],
+   "provider":provider,"limit":posts_per_group}`，requires='["local"]',
+   created_at) + UPDATE fb_groups SET status='in_progress' + commit；异常 rollback
+   + raise；finally close。返回入队行数。
+4. **limit 语义**：fb_group 的 limit 是「群数上限」（0=不限），与 enqueue_fb_post_batch
+   的 limit 语义一致。
+5. **时间戳**：`_bj_now()`（platform app/db.py 既有，北京时区字符串）。
+6. **测试基建**：test_batch_tasks.py 的 BatchTasksTestBase（临时 sqlite + patch
+   DB_PATH）。测试需要建 work_items/fb_groups 表结构（参照既有测试的 _schema 或
+   enqueue_fb_post_batch 测试的建表方式）。
+7. **测试覆盖**（PLAN 已列）：展开数（2 词 × 2 页 = 4）、幂等（同 query+page 已有
+   pending 跳过 → 二次调用入队 0）、空关键词 → 0、payload 断言（kind/engine/query/
+   page、requires='["local"]'、site=NULL、batch_id）、fb_group 限量（limit=2 取 2
+   群）、表缺失返回 0（无 fb_groups 表时）、fb_group payload 断言（url/provider/
+   limit=posts_per_group）、源行置 in_progress。
+
+## 代码库上下文
+
+- `platform/server/app/db.py`：`_bj_now()`（顶部）、`enqueue_fb_post_batch`（192 行起，
+  本 Step 直接参照其结构）、`enqueue_wa_batch`（316 行起，requires='["local"]' 的
+  INSERT 写法参照）。
+- `platform/server/app/runner.py`：enqueue_batch_for_task 两分支（Step 3.1 已加，
+  懒导入在分支内）。
+- 测试运行：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks
+  -v`；回归同一文件全量。
+
+## TDD 纪律
+
+1. 先失败测试 → RED → 最小实现 → GREEN。落库用临时 sqlite 断言真实行。
+2. 测试覆盖（brief 已列全）。
+3. 输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`platform/server/app/db.py`、`platform/server/app/runner.py`（懒导入
+  收尾）、`platform/server/tests/test_batch_tasks.py`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 3.2 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-report.md
new file mode 100644
index 0000000..711a770
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-report.md
@@ -0,0 +1,115 @@
+# Step 3.2 — app/db.py enqueue 双函数（TDD）执行报告
+
+## 状态：DONE
+
+## 实现了什么
+
+### `platform/server/app/db.py`（新增两个函数，插在 `enqueue_fb_post_batch` 与 `enqueue_feeder_batch` 之间）
+
+1. **`enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`**
+   - keywords 按 `splitlines()` 拆词 → strip → 过滤空行；空 → 返回 0。
+   - 每词 × 每页（1..pages，`pages<1` 视为 1）展开；payload
+     `{"kind":"serp","engine":"ddg","query":kw,"page":N}`。
+   - INSERT `work_items (queue='discover_fb', site=NULL, batch_id, payload_json,
+     requires='["local"]', created_at=_bj_now())`。
+   - 幂等：INSERT 前查 `work_items WHERE queue='discover_fb' AND status='pending'
+     AND json_extract(payload_json,'$.query')=? AND json_extract(payload_json,'$.page')=?`
+     存在则跳过（json_extract 模式参照 `enqueue_feeder_batch`）。
+   - 返回实际入队数。
+
+2. **`enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`**
+   - 结构对齐 `enqueue_fb_post_batch`：`sqlite3.connect(DB_PATH, timeout=30)` +
+     `PRAGMA busy_timeout=30000` + sqlite_master 探测 fb_groups 表（无 → 0）+
+     `BEGIN IMMEDIATE` 单事务。
+   - SELECT pending fb_groups（`ORDER BY first_seen_at, id`，limit>0 时 `LIMIT ?`）→
+     INSERT work_items（queue='crawl_fb_group'、site=NULL、batch_id、payload
+     `{"url":r["url"],"provider":provider,"limit":posts_per_group}`、
+     requires='["local"]'、created_at）→ UPDATE fb_groups `status='in_progress'`。
+   - 异常 rollback + raise；finally close。返回入队行数。
+
+### `platform/server/app/runner.py`（懒导入收尾，跨 Step 必做项）
+
+- `enqueue_fb_discover_batch` / `enqueue_fb_group_batch` 并入 `enqueue_batch_for_task`
+  函数顶部既有 `from app.db import (...)` 集中 import；
+- 删掉 fb_discover/fb_group 两分支内的懒导入与「Step 3.2 提供真实函数」占位注释
+  （改为描述缺省值语义的注释）。
+
+### `platform/server/tests/test_batch_tasks.py`（新增 `FbBatchEnqueueTest`，7 个测试）
+
+临时 sqlite（复用 `BatchTasksTestBase` patch DB_PATH）断言真实行：
+
+| 测试 | 覆盖 |
+|---|---|
+| `test_fb_discover_expands_keywords_times_pages` | 2 词 × 2 页 = 4 条；payload 全键（kind/engine/query/page）、requires=['local']、site=NULL、batch_id；词×页组合恰好各一条 |
+| `test_fb_discover_idempotent_same_query_page` | 二次调用同 query+page（已有 pending）→ 入队 0，总条数不变 |
+| `test_fb_discover_empty_keywords_returns_zero` | 空串 / 纯空白行 → 0，不产生 item |
+| `test_fb_discover_pages_less_than_one_treated_as_one` | pages=0 → 按 1 页 |
+| `test_fb_group_enqueues_and_marks_in_progress` | limit=2 取 2 群；payload {url,provider,limit}（limit=50=posts_per_group）；源行前 2 群 in_progress、第 3 群仍 pending |
+| `test_fb_group_limit_zero_unlimited` | limit=0 → 全部 3 群入队 |
+| `test_fb_group_missing_table_returns_zero` | fb_groups 表不存在 → 0（防御性探测），不产生 item |
+
+## TDD 证据
+
+### RED
+
+命令：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks.FbBatchEnqueueTest -v`
+
+```
+ERROR: test_fb_discover_expands_keywords_times_pages ...
+ImportError: cannot import name 'enqueue_fb_discover_batch' from 'app.db'
+...
+ERROR: test_fb_group_missing_table_returns_zero ...
+ImportError: cannot import name 'enqueue_fb_group_batch' from 'app.db'
+...
+Ran 7 tests in 0.274s
+FAILED (errors=7)
+```
+
+符合预期：失败原因是功能缺失（两个函数尚未实现），非笔误。7/7 全 error。
+
+### GREEN
+
+命令：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks.FbBatchEnqueueTest -v`
+
+```
+Ran 7 tests in 0.227s
+OK
+```
+
+实现最小化：只加了 brief 规定的两个函数 + runner 懒导入收尾，无多余改动。
+
+## 测试结果（验收命令 + 回归）
+
+```
+$ .venv/bin/python -m unittest tests.test_batch_tasks          # 28 tests OK（21 既有 + 7 新增）
+$ .venv/bin/python -m unittest tests.test_fb_batch             # 14 tests OK（未触碰文件回归）
+```
+
+- 既有 `FbBatchDispatchTest`（Step 3.1，mock `db_module.enqueue_fb_*`）在懒导入
+  收尾后仍全过：集中 import 在函数调用时解析模块属性，patch.object 依然生效。
+- 输出干净，无 error/warning。
+
+## 改动的文件
+
+- `platform/server/app/db.py`（+96 行：两个 enqueue 函数）
+- `platform/server/app/runner.py`（-6/+4 行：懒导入收尾）
+- `platform/server/tests/test_batch_tasks.py`（+118 行：FbBatchEnqueueTest）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-brief.md` / `task-3.2-report.md`（本 Step 文档）
+
+## 自查
+
+- **完整性**：SPEC §6.2 两条 + 协调者裁定 1-7 逐条对照，全部落实。边界覆盖：
+  空关键词（含纯空白行）、limit=0、pages<1、fb_groups 表缺失、同 query+page 幂等。
+- **质量**：`enqueue_fb_group_batch` 直接对齐 `enqueue_fb_post_batch` 的事务/探测结构
+  （BEGIN IMMEDIATE、sqlite_master、LIMIT 拼装、rollback/raise/finally）；
+  `enqueue_fb_discover_batch` 幂等模式对齐 `enqueue_feeder_batch` 的 json_extract 写法；
+  注释为中文、顶部一行说明函数职责。
+- **纪律**：只做了 brief 要求的内容（含跨 Step 懒导入收尾）；未重构任务范围外代码。
+- **测试**：真实行为断言（临时 sqlite 真实行 + payload 解析断言），无 mock 实现；
+  TDD 流程完整（先 RED 亲眼看失败 → 最小实现 → GREEN）。
+
+## 疑虑
+
+- `enqueue_fb_discover_batch` 未用 BEGIN IMMEDIATE（与 `enqueue_feeder_batch` 同型）：
+  幂等检查与 INSERT 之间理论上存在并发窗口，但代码库既有 feeder 模式即如此，
+  brief 裁定 2 明确参照该模式，未加锁属有意对齐（YAGNI，不扩大范围）。
diff --git a/platform/server/app/db.py b/platform/server/app/db.py
index 2f8301a..9ed68b4 100644
--- a/platform/server/app/db.py
+++ b/platform/server/app/db.py
@@ -232,20 +232,116 @@ def enqueue_fb_post_batch(queue: str, site: str, batch_id: int,
                 (r["id"],))
         conn.commit()
         return len(rows)
     except Exception:
         conn.rollback()
         raise
     finally:
         conn.close()
 
 
+def enqueue_fb_discover_batch(batch_id: int, keywords: str,
+                               pages: int) -> int:
+    """fb_discover 批次入队：关键词（换行分隔）逐词 × 页码展开。
+
+    payload {"kind":"serp","engine":"ddg","query":kw,"page":N}；
+    requires=["local"]、site=NULL。幂等：同 query+page 已有 pending
+    跳过（防循环模式重入批量重复堆栈，参照 enqueue_feeder_batch 的
+    json_extract 幂等模式）。keywords 空 → 0。返回入队 item 数。
+    """
+    words = [w.strip() for w in (keywords or "").splitlines()]
+    words = [w for w in words if w]
+    if not words:
+        return 0
+    pages = max(1, int(pages))
+    conn = sqlite3.connect(DB_PATH, timeout=30)
+    try:
+        conn.execute("PRAGMA busy_timeout = 30000")
+        now = _bj_now()
+        n = 0
+        for kw in words:
+            for page in range(1, pages + 1):
+                exists = conn.execute(
+                    "SELECT COUNT(*) FROM work_items WHERE queue=?"
+                    " AND status='pending'"
+                    " AND json_extract(payload_json, '$.query')=?"
+                    " AND json_extract(payload_json, '$.page')=?",
+                    ("discover_fb", kw, page)).fetchone()[0]
+                if exists:
+                    continue
+                payload = {"kind": "serp", "engine": "ddg",
+                           "query": kw, "page": page}
+                conn.execute(
+                    "INSERT INTO work_items (queue, site, batch_id,"
+                    " payload_json, requires, created_at)"
+                    " VALUES (?, NULL, ?, ?, ?, ?)",
+                    ("discover_fb", batch_id,
+                     json.dumps(payload, ensure_ascii=False),
+                     '["local"]', now))
+                n += 1
+        conn.commit()
+        return n
+    except Exception:
+        conn.rollback()
+        raise
+    finally:
+        conn.close()
+
+
+def enqueue_fb_group_batch(batch_id: int, provider: str,
+                           posts_per_group: int, limit: int) -> int:
+    """fb_group 批次入队：SELECT pending fb_groups → INSERT items →
+    源行置 in_progress（BEGIN IMMEDIATE 单事务，与群采集消费互斥不双喂，
+    对齐 enqueue_fb_post_batch）。
+
+    payload {"url","provider","limit"}（limit=posts_per_group）；
+    requires=["local"]、site=NULL。fb_groups 表不存在（fetcher 侧未建
+    表）→ 返回 0（防御性探测）。limit>0 限量（<=0 不限）。返回入队行数。
+    """
+    conn = sqlite3.connect(DB_PATH, timeout=30)
+    try:
+        conn.row_factory = sqlite3.Row
+        conn.execute("PRAGMA busy_timeout = 30000")
+        tables = {r[0] for r in conn.execute(
+            "SELECT name FROM sqlite_master WHERE type='table'")}
+        if "fb_groups" not in tables:
+            return 0
+        conn.execute("BEGIN IMMEDIATE")
+        sql = ("SELECT * FROM fb_groups WHERE status='pending'"
+               " ORDER BY first_seen_at, id")
+        params: list = []
+        if limit > 0:
+            sql += " LIMIT ?"
+            params.append(limit)
+        rows = conn.execute(sql, params).fetchall()
+        now = _bj_now()
+        for r in rows:
+            payload = json.dumps(
+                {"url": r["url"], "provider": provider,
+                 "limit": posts_per_group},
+                ensure_ascii=False)
+            conn.execute(
+                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
+                " requires, created_at) VALUES (?, NULL, ?, ?, ?, ?)",
+                ("crawl_fb_group", batch_id, payload, '["local"]', now))
+            conn.execute(
+                "UPDATE fb_groups SET status='in_progress' WHERE id=?",
+                (r["id"],))
+        conn.commit()
+        return len(rows)
+    except Exception:
+        conn.rollback()
+        raise
+    finally:
+        conn.close()
+
+
 def enqueue_feeder_batch(queue: str, site: str, batch_id: int,
                          limit: int) -> tuple[int, int]:
     """feeder 批次入队：1 条 discover + 活跃类目 category 种子，全部带
     batch_id 与 payload.batch_limit（收束边界，0=不限）。幂等：已有同
     keyword pending category / pending discover 跳过。返回 (n_cat, n_disc)。
     """
     conn = sqlite3.connect(DB_PATH, timeout=30)
     try:
         conn.execute("PRAGMA busy_timeout = 30000")
         n_cat = 0
diff --git a/platform/server/app/runner.py b/platform/server/app/runner.py
index c3614e6..d9cc125 100644
--- a/platform/server/app/runner.py
+++ b/platform/server/app/runner.py
@@ -294,37 +294,35 @@ def enqueue_batch_for_task(task_id: int, task_type: str,
     """批次任务入队：按 BATCH_TYPES 分派 contact/feeder/wa。返回 item 数。
 
     contact：limit 限量；feeder：discover+category 种子；wa：账号清单
     （params.accounts）50/块。batch_id = task_id。
     """
     spec = BATCH_TYPES.get(task_type)
     if spec is None:
         raise ValueError(f"非批次任务类型: {task_type}")
     params = params or {}
     limit = int(params.get("limit") or 0)
-    from app.db import (enqueue_contact_batch, enqueue_fb_post_batch,
+    from app.db import (enqueue_contact_batch, enqueue_fb_discover_batch,
+                        enqueue_fb_group_batch, enqueue_fb_post_batch,
                         enqueue_feeder_batch, enqueue_wa_batch)
     if spec["kind"] == "contact":
         return enqueue_contact_batch(spec["queue"], spec["site"],
                                      spec["domain_suffix"], task_id, limit)
     if spec["kind"] == "fb_post":
         return enqueue_fb_post_batch(spec["queue"], spec["site"],
                                      task_id, limit)
     if spec["kind"] == "fb_discover":
-        # Step 3.2 提供真实函数；此处懒导入，缺省 keywords=""、pages=1
-        from app.db import enqueue_fb_discover_batch
+        # 缺省 keywords=""、pages=1
         return enqueue_fb_discover_batch(task_id, params.get("keywords") or "",
                                          int(params.get("pages") or 1))
     if spec["kind"] == "fb_group":
-        # Step 3.2 提供真实函数；此处懒导入，缺省 provider="brightdata"、
-        # posts_per_group=50，limit 透传
-        from app.db import enqueue_fb_group_batch
+        # 缺省 provider="brightdata"、posts_per_group=50，limit 透传
         return enqueue_fb_group_batch(task_id,
                                       (params.get("provider") or "brightdata"),
                                       int(params.get("posts_per_group") or 50),
                                       limit)
     if spec["kind"] == "feeder":
         n_cat, n_disc = enqueue_feeder_batch(
             spec["queue"], spec["site"], task_id, limit)
         return n_cat + n_disc
     if spec["kind"] == "wa":
         accounts = params.get("accounts") or []
diff --git a/platform/server/tests/test_batch_tasks.py b/platform/server/tests/test_batch_tasks.py
index 8bf754c..2cb31d8 100644
--- a/platform/server/tests/test_batch_tasks.py
+++ b/platform/server/tests/test_batch_tasks.py
@@ -522,12 +522,130 @@ class FbBatchDispatchTest(BatchTasksTestBase):
         with patch.object(db_module, "enqueue_fb_group_batch",
                           create=True, return_value=4) as mock_enqueue:
             n = enqueue_batch_for_task(
                 8, "fb_group",
                 {"provider": "scraperapi", "posts_per_group": "30",
                  "limit": "120"})
         mock_enqueue.assert_called_once_with(8, "scraperapi", 30, 120)
         self.assertEqual(n, 4)
 
 
+# =====================================================================
+# 6. Step 3.2：fb_discover / fb_group 真实入队
+# =====================================================================
+
+
+class FbBatchEnqueueTest(BatchTasksTestBase):
+    """enqueue_fb_discover_batch / enqueue_fb_group_batch 真实落库。
+
+    临时 sqlite 断言真实行：展开数/幂等/空关键词/限量/表缺失/源行置位/
+    payload 全键断言。
+    """
+
+    def _seed_fb_groups(self, n=3):
+        """建 fb_groups 表（对齐 fetcher 侧 schema）+ 种 n 条 pending 群。"""
+        conn = self._conn()
+        conn.execute(
+            "CREATE TABLE IF NOT EXISTS fb_groups ("
+            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
+            " url TEXT NOT NULL UNIQUE, group_id TEXT, name TEXT,"
+            " source TEXT NOT NULL DEFAULT 'ddg',"
+            " status TEXT NOT NULL DEFAULT 'pending', post_count INTEGER,"
+            " has_contact INTEGER, first_seen_at TEXT NOT NULL,"
+            " last_crawled_at TEXT)")
+        for i in range(n):
+            conn.execute(
+                "INSERT INTO fb_groups (url, group_id, name, status,"
+                " first_seen_at) VALUES (?, ?, ?, 'pending',"
+                " '2026-08-08 10:00:00')",
+                (f"https://www.facebook.com/groups/g{i}", f"g{i}",
+                 f"群{i}"))
+        conn.commit()
+        conn.close()
+
+    def test_fb_discover_expands_keywords_times_pages(self):
+        """2 词 × 2 页 = 4 条；payload 全键/requires/site/batch_id 断言。"""
+        from app.db import enqueue_fb_discover_batch
+        n = enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2)
+        self.assertEqual(n, 4)
+        items = self._wi(7)
+        self.assertEqual(len(items), 4)
+        for r in items:
+            self.assertEqual(r["queue"], "discover_fb")
+            self.assertIsNone(r["site"])
+            self.assertEqual(r["batch_id"], 7)
+            self.assertEqual(json.loads(r["requires"]), ["local"])
+            p = json.loads(r["payload_json"])
+            self.assertEqual(p["kind"], "serp")
+            self.assertEqual(p["engine"], "ddg")
+            self.assertIn(p["query"], ("面膜", "洗面奶"))
+            self.assertIn(p["page"], (1, 2))
+        # 每个词 × 每页组合恰好一条
+        combos = {(json.loads(r["payload_json"])["query"],
+                   json.loads(r["payload_json"])["page"])
+                  for r in items}
+        self.assertEqual(combos, {("面膜", 1), ("面膜", 2),
+                                  ("洗面奶", 1), ("洗面奶", 2)})
+
+    def test_fb_discover_idempotent_same_query_page(self):
+        """同 query+page 已有 pending → 二次调用入队 0（不重复堆栈）。"""
+        from app.db import enqueue_fb_discover_batch
+        self.assertEqual(enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2), 4)
+        self.assertEqual(enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2), 0)
+        self.assertEqual(len(self._wi(7)), 4)
+
+    def test_fb_discover_empty_keywords_returns_zero(self):
+        """空关键词（空串/纯空白行）→ 0，不产生 item。"""
+        from app.db import enqueue_fb_discover_batch
+        self.assertEqual(enqueue_fb_discover_batch(7, "", 2), 0)
+        self.assertEqual(enqueue_fb_discover_batch(7, "  \n \n", 2), 0)
+        self.assertEqual(len(self._wi(7)), 0)
+
+    def test_fb_discover_pages_less_than_one_treated_as_one(self):
+        """pages<1 → 按 1 页处理（裁定 2）。"""
+        from app.db import enqueue_fb_discover_batch
+        self.assertEqual(enqueue_fb_discover_batch(7, "面膜", 0), 1)
+
+    def test_fb_group_enqueues_and_marks_in_progress(self):
+        """limit=2 取 2 群；payload {url,provider,limit}；源行置 in_progress。"""
+        from app.db import enqueue_fb_group_batch
+        self._seed_fb_groups(3)
+        n = enqueue_fb_group_batch(8, "brightdata", posts_per_group=50,
+                                   limit=2)
+        self.assertEqual(n, 2)
+        items = self._wi(8)
+        self.assertEqual(len(items), 2)
+        urls = [json.loads(r["payload_json"])["url"] for r in items]
+        self.assertEqual(urls[0], "https://www.facebook.com/groups/g0")
+        self.assertEqual(urls[1], "https://www.facebook.com/groups/g1")
+        for r in items:
+            self.assertEqual(r["queue"], "crawl_fb_group")
+            self.assertIsNone(r["site"])
+            self.assertEqual(r["batch_id"], 8)
+            self.assertEqual(json.loads(r["requires"]), ["local"])
+            p = json.loads(r["payload_json"])
+            self.assertEqual(set(p), {"url", "provider", "limit"})
+            self.assertEqual(p["provider"], "brightdata")
+            self.assertEqual(p["limit"], 50)
+        # 源行：前 2 群 in_progress，第 3 群保持 pending
+        conn = self._conn()
+        sts = conn.execute(
+            "SELECT status FROM fb_groups ORDER BY id").fetchall()
+        conn.close()
+        self.assertEqual([r["status"] for r in sts],
+                         ["in_progress", "in_progress", "pending"])
+
+    def test_fb_group_limit_zero_unlimited(self):
+        """limit=0（不限）→ 全部 pending 群入队。"""
+        from app.db import enqueue_fb_group_batch
+        self._seed_fb_groups(3)
+        self.assertEqual(enqueue_fb_group_batch(8, "brightdata", 50, 0), 3)
+
+    def test_fb_group_missing_table_returns_zero(self):
+        """fb_groups 表不存在（fetcher 侧未建）→ 0（防御性探测）。"""
+        from app.db import enqueue_fb_group_batch
+        self.assertEqual(enqueue_fb_group_batch(8, "brightdata", 50, 2), 0)
+        self.assertEqual(len(self._wi(8)), 0)
+
+
 if __name__ == "__main__":
     unittest.main()
