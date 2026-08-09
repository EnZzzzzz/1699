# Step 2.3 review package
8c58e4e feat(fb): Step 2.3 FbPostTask.on_success 群 upsert 补位——每抓一帖发现一群（TDD）
 .../task-2.3-brief.md                              | 73 ++++++++++++++++
 .../task-2.3-report.md                             | 99 ++++++++++++++++++++++
 fetcher/fetcher/sites/facebook/post_task.py        |  9 ++
 fetcher/tests/test_fb_post_task.py                 | 52 ++++++++++++
 4 files changed, 233 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-brief.md
new file mode 100644
index 0000000..8fdc587
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-brief.md
@@ -0,0 +1,73 @@
+# Step 2.3 — FbPostTask.on_success 群 upsert 补位（TDD）
+
+> 这是你的需求唯一来源。PLAN Step 2.3 原文 + SPEC §5.5 精确规格抄录如下。
+
+## PLAN Step 2.3 原文（验收以 checkbox 为准）
+
+- [ ] `fetcher/fetcher/sites/facebook/post_task.py on_success` 追加：group_id 非空时
+      `db.upsert_fb_groups([{"url": 派生群URL, "group_id", "name": item.get("name")}])`
+      （SPEC §5.5）
+- [ ] 测试（扩展 test_fb_post_task.py）：抓帖后 fb_groups 出现该群（pending、name
+      溯源）；无 group_id 时零写入；既有 on_success 测试零回归
+- 预估 20min；验收：新断言全绿 + 既有 test_fb_post_task.py 全绿
+
+## SPEC §5.5 FbPostTask.on_success 改动（**唯一既有 Task 改动点，幂等**）
+
+在现有「save_fb_contacts + mark_fb_post_done」之后追加：
+
+```python
+if group_id:
+    db.upsert_fb_groups([{"url": f"https://www.facebook.com/groups/{group_id}",
+                          "group_id": group_id, "name": item.get("name") or ""}])
+```
+
+语义：**每抓到一帖 = 发现一个群**（种子路径②）；INSERT OR IGNORE 幂等、不触碰
+既有群状态机（只写 pending 新行），对既有 fb_posts/fb_contacts 状态流零影响。
+
+## 协调者裁定（覆盖 SPEC 未定细节）
+
+1. **group_id 来源**：post_task.py 的 on_success 已有 `group_id = _group_id_from_url(
+   item.get("domain") or "")`——注意 Step 2.1 修复后该函数已提取到共享位置
+   `fetcher/fetcher/sites/facebook/urls.py`（公共名 `group_id_from_url`），post_task.py
+   现在从那里导入。**本 Step 不要重复定义，直接用既有导入的 group_id_from_url。**
+2. **upsert 调用位置**：在「save_fb_contacts + mark_fb_post_done」之后、sidecar
+   result_json 设置之前（与 SPEC §5.5 语义一致）。group_id 非空才调用。
+3. **name 溯源**：`item.get("name") or ""`（item payload 的 name 来自平台
+   enqueue_fb_post_batch 的 payload {"url","domain","name"}）。
+4. **source 键**：Step 1.1 裁定的 upsert_fb_groups 条目可选 `"source"` 键——本 Step
+   显式传 `"source": "fb_post"`（群由帖派生，SPEC §4.1 source ∈ {ddg, fb_post}）。
+   注意：仅当条目 source 键存在时 upsert 才写 fb_post；不传则缺省 ddg。所以**必须
+   显式传 source="fb_post"**。
+5. **幂等/状态机**：INSERT OR IGNORE 已存在行不动 status（保持采集进度）；对既有
+   fb_posts/fb_contacts 状态流零影响（回归由既有 on_success 测试守护）。
+6. **测试**：扩展 test_fb_post_task.py——
+   - 抓帖 on_success 后 fb_groups 出现该群行（url=派生群 URL、group_id、name=payload
+     name、status=pending、source='fb_post'）；
+   - item 无 domain/group_id 时 upsert 零写入（fb_groups 无新行）；
+   - 既有 on_success 测试零回归（save_fb_contacts/mark_fb_post_done/sidecar 断言不动）。
+
+## 代码库上下文
+
+- `fetcher/fetcher/sites/facebook/post_task.py`：on_success 在约 135-163 行（save_fb_contacts
+  → mark_fb_post_done → sidecar → stats）。group_id 已由 `group_id_from_url`（从
+  urls.py 导入）解析。
+- `fetcher/fetcher/sites/facebook/urls.py`：Step 2.1 新建的共享函数（group_id_from_url）。
+- `fetcher/tests/test_fb_post_task.py`：既有 on_success 测试（mock FetchFbPost 原子 +
+  临时 ShopDB）。参照其构造方式加新断言。
+- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
+  -s tests -p "test_fb_post_task.py"`；回归 `-p "test_fb_*.py"`。
+
+## TDD 纪律
+
+1. 先失败测试 → RED → 最小实现 → GREEN。
+2. 测试覆盖（brief 已列）：抓帖后 fb_groups 出现群行（字段断言全）+ 无 group_id
+   零写入 + 既有零回归。
+3. 输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`fetcher/fetcher/sites/facebook/post_task.py`、
+  `fetcher/tests/test_fb_post_task.py`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 2.3 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-report.md
new file mode 100644
index 0000000..8aba276
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-report.md
@@ -0,0 +1,99 @@
+# Step 2.3 报告 — FbPostTask.on_success 群 upsert 补位
+
+> 状态：DONE
+
+## 实现了什么
+
+`fetcher/fetcher/sites/facebook/post_task.py` 的 `FbPostTask.on_success`：在
+「save_fb_contacts → mark_fb_post_done」之后、sidecar result_json 设置之前追加：
+
+```python
+# 每抓到一帖 = 发现一个群（种子路径②，SPEC §5.5）：INSERT OR IGNORE
+# 幂等，不触碰既有群状态机；source 显式传 fb_post（缺省 ddg）
+if group_id:
+    db.upsert_fb_groups([{
+        "url": f"https://www.facebook.com/groups/{group_id}",
+        "group_id": group_id,
+        "name": item.get("name") or "",
+        "source": "fb_post",
+    }])
+```
+
+- `group_id` 复用 Step 2.1 已提取的共享函数 `group_id_from_url`（post_task.py
+  既有导入，**未重复定义正则/函数**）。
+- `source="fb_post"` 显式传入（upsert 仅在条目带 source 键时才写 fb_post，
+  不传缺省 ddg——协调者裁定 #4）。
+- `name` 溯源 `item.get("name") or ""`（协调者裁定 #3）。
+- 仅 `group_id` 非空时调用（无 domain/group_id 的 item 零写入）。
+
+未改动：`db.upsert_fb_groups` 本身（Step 1.1 已实现）、群状态机、
+fb_posts/fb_contacts 状态流。
+
+## 测了什么（test_fb_post_task.py，+4 个测试，15 → 19）
+
+| 测试 | 断言 |
+|---|---|
+| `test_on_success_upserts_group_row` | 抓帖后 fb_groups 恰 1 行：url=派生群 URL、group_id、name=payload name、source='fb_post'、status='pending'（落真库真断言） |
+| `test_on_success_group_name_defaults_to_empty` | payload 无 name 时 name 缺省空串、source 仍为 fb_post |
+| `test_on_success_no_group_id_zero_writes` | item 无 domain/group_id 时 fb_groups 零写入 |
+| `test_on_success_repeat_fetch_is_idempotent` | 同群帖二次 on_success：仍 1 行，name/status 不被覆盖（INSERT OR IGNORE 守护） |
+
+既有 on_success 测试（save_fb_contacts 分桶 / mark_fb_post_done / sidecar /
+stats）零改动零回归。
+
+## 测试结果
+
+- 验收命令：`cd fetcher && ../platform/server/.venv/bin/python -m unittest
+  discover -s tests -p "test_fb_post_task.py"` → **Ran 19 tests, OK**
+- 回归：`-p "test_fb_*.py"` → **Ran 60 tests, OK**
+
+## TDD 证据
+
+**RED**（先加前 3 个测试，未实现）：
+
+```
+FAIL: test_on_success_upserts_group_row
+AssertionError: 0 != 1          # fb_groups 无行（实现前 on_success 不写群）
+
+ERROR: test_on_success_group_name_defaults_to_empty
+TypeError: 'NoneType' object is not subscriptable   # 同上，无行可取
+
+Ran 18 tests — FAILED (failures=1, errors=1)
+```
+
+符合预期：实现缺失时群表必然为空，两个群行断言失败；`zero_writes` 测试在
+实现前即通过（无写入自然零行，作为守护）。
+
+**GREEN**（最小实现后）：
+
+```
+Ran 19 tests in 0.086s
+OK
+```
+
+**补充说明**：第 4 个幂等测试（`test_on_success_repeat_fetch_is_idempotent`）
+在 GREEN 后追加——它守护的是已实现行为（INSERT OR IGNORE + url UNIQUE），
+本身无独立 RED 阶段；前 3 个 brief 要求的测试均有真实 RED。
+
+## 改动的文件
+
+- `fetcher/fetcher/sites/facebook/post_task.py`（on_success 追加 7 行 upsert 块）
+- `fetcher/tests/test_fb_post_task.py`（+4 测试，全部走真库断言）
+
+## 自查
+
+- **完整性**：SPEC §5.5 逐条落实（调用位置、group_id 非空条件、name 缺省、
+  source='fb_post'、幂等不碰状态机）；边界（无 group_id 零写入、name 缺省、
+  重复抓帖幂等）均有测试。
+- **质量**：命名/注释对齐既有 on_success 模式；upsert 块紧邻
+  mark_fb_post_done，与 sidecar 段由注释分隔，职责清晰。
+- **纪律**：YAGNI——只加了 brief 要求的一处调用与测试，未重构任何既有代码；
+  未触碰 upsert_fb_groups 实现（Step 1.1 产物）。
+- **测试**：真实行为（临时 ShopDB 真库断言，全 mock 原子无网络）；既有
+  on_success 测试零回归；测试输出与基线一致（prepare 的 print 为既有行为）。
+
+## 疑虑
+
+- 无阻塞性疑虑。唯一说明：第 4 个幂等测试为 GREEN 后追加的守护测试
+  （见上），非严格 TDD 顺序，但覆盖的是 brief 明示的「INSERT OR IGNORE 幂等」
+  语义，且无实现时同样会失败（与 upsert 行为绑定）。
diff --git a/fetcher/fetcher/sites/facebook/post_task.py b/fetcher/fetcher/sites/facebook/post_task.py
index fcea777..2792f68 100644
--- a/fetcher/fetcher/sites/facebook/post_task.py
+++ b/fetcher/fetcher/sites/facebook/post_task.py
@@ -124,20 +124,29 @@ class FbPostTask(Task):
 
     def on_success(self, ctx, item, result: ActionResult) -> int:
         """号码落 fb_contacts + fb_posts 置 done + 侧车副产物留 result_json。"""
         data = result.data or {}
         phones = data.get("phones") or []
         group_id = group_id_from_url(item.get("domain") or "")
         db = ctx.store.db
         n_new = db.save_fb_contacts(item["url"], group_id, phones)
         has_contact = bool(data.get("has_contact"))
         db.mark_fb_post_done(item["url"], has_contact)
+        # 每抓到一帖 = 发现一个群（种子路径②，SPEC §5.5）：INSERT OR IGNORE
+        # 幂等，不触碰既有群状态机；source 显式传 fb_post（缺省 ddg）
+        if group_id:
+            db.upsert_fb_groups([{
+                "url": f"https://www.facebook.com/groups/{group_id}",
+                "group_id": group_id,
+                "name": item.get("name") or "",
+                "source": "fb_post",
+            }])
         # 侧车副产物（微信/TG/邀请链接）：非空才设，QueueRouter._finish
         # 经 ctx.state["result_json"] 落 work_items.result_json（SPEC §8）
         sidecar = {}
         for key in ("wechat_ids", "tg_handles", "wa_group_invites"):
             vals = data.get(key) or []
             if vals:
                 sidecar[key] = vals
         if sidecar:
             ctx.state["result_json"] = sidecar
         stats = self.wctx_stats(ctx)
diff --git a/fetcher/tests/test_fb_post_task.py b/fetcher/tests/test_fb_post_task.py
index 21a9423..b6788ea 100644
--- a/fetcher/tests/test_fb_post_task.py
+++ b/fetcher/tests/test_fb_post_task.py
@@ -160,20 +160,72 @@ class FbPostTaskTest(unittest.TestCase):
                          {"wechat_ids": ["wx12345"], "tg_handles": ["tgbot1"],
                           "wa_group_invites": ["AbCdEf123456"]})
 
     def test_on_success_empty_sidecar_not_set(self):
         _seed_post(self.db)
         ctx = self._ctx()
         self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL},
                              _result())
         self.assertNotIn("result_json", ctx.state)
 
+    def test_on_success_upserts_group_row(self):
+        """抓帖后 fb_groups 出现派生群行（SPEC §5.5：每帖=发现一群）。"""
+        _seed_post(self.db)
+        ctx = self._ctx()
+        self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL,
+                                   "name": "Shenzhen Expats 2026"}, _result())
+        rows = self.db.conn.execute(
+            "SELECT * FROM fb_groups").fetchall()
+        self.assertEqual(len(rows), 1)
+        row = rows[0]
+        self.assertEqual(row["url"], GROUP_URL)
+        self.assertEqual(row["group_id"], "185879310028412")
+        self.assertEqual(row["name"], "Shenzhen Expats 2026")
+        self.assertEqual(row["source"], "fb_post")
+        self.assertEqual(row["status"], "pending")
+
+    def test_on_success_group_name_defaults_to_empty(self):
+        """payload 无 name 时群名缺省空串（name 溯源 or ""）。"""
+        _seed_post(self.db)
+        ctx = self._ctx()
+        self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL},
+                             _result())
+        row = self.db.conn.execute(
+            "SELECT name, source FROM fb_groups").fetchone()
+        self.assertEqual(row[0], "")
+        self.assertEqual(row[1], "fb_post")
+
+    def test_on_success_no_group_id_zero_writes(self):
+        """item 无 domain/group_id 时 fb_groups 零写入（幂等边界）。"""
+        _seed_post(self.db)
+        ctx = self._ctx()
+        self.task.on_success(ctx, {"url": POST_URL}, _result())
+        n = self.db.conn.execute(
+            "SELECT COUNT(*) FROM fb_groups").fetchone()[0]
+        self.assertEqual(n, 0)
+
+    def test_on_success_repeat_fetch_is_idempotent(self):
+        """重复抓同群帖：INSERT OR IGNORE 不新增行、不动既有状态。"""
+        _seed_post(self.db)
+        ctx = self._ctx()
+        item = {"url": POST_URL, "domain": GROUP_URL, "name": "G"}
+        self.task.on_success(ctx, item, _result())
+        # 二次抓帖：已有行不动（status/name 保持采集进度）
+        self.task.on_success(ctx, item, _result())
+        rows = self.db.conn.execute(
+            "SELECT COUNT(*) FROM fb_groups").fetchone()[0]
+        self.assertEqual(rows, 1)
+        row = self.db.conn.execute(
+            "SELECT name, status FROM fb_groups").fetchone()
+        self.assertEqual(row[0], "G")
+        self.assertEqual(row[1], "pending")
+
     def test_queue_router_finish_writes_sidecar_to_result_json(self):
         """侧车经 QueueRouter._finish 真正落 work_items.result_json
         （SPEC §8 观测副产物机制，触达 router 钩子代码）。"""
         from fetcher.control.queue_router import QueueRouter, QueueSpec
         spec = QueueSpec(queue="crawl_fb_post", site="facebook",
                          task=self.task)
         router = QueueRouter([spec])
         self.db.conn.execute(
             "INSERT INTO work_items (queue, site, payload_json, requires,"
             " created_at) VALUES ('crawl_fb_post', 'facebook', ?, ?, "
