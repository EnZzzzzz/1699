# Step 3.3 review package
d90e01f feat(fb): Step 3.3 TaskParams 追加 keywords/pages/provider/posts_per_group（TDD）
 .../task-3.3-brief.md                              | 57 +++++++++++++++
 .../task-3.3-report.md                             | 84 ++++++++++++++++++++++
 platform/server/app/api/tasks.py                   |  5 ++
 platform/server/tests/test_batch_tasks.py          | 27 +++++++
 4 files changed, 173 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-brief.md
new file mode 100644
index 0000000..786ecb2
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-brief.md
@@ -0,0 +1,57 @@
+# Step 3.3 — api/tasks.py TaskParams 四字段
+
+> 这是你的需求唯一来源。PLAN Step 3.3 原文 + SPEC §6.3 精确规格抄录如下。
+
+## PLAN Step 3.3 原文（验收以 checkbox 为准）
+
+- [ ] TaskParams 追加 keywords/pages/provider/posts_per_group（SPEC §6.3）
+- [ ] 测试：TaskCreate 携带四字段 round-trip 成功；TASK_TYPES 并集含两新类型
+- 预估 15min；验收：测试全绿
+
+## SPEC §6.3 api/tasks.py TaskParams 追加（精确规格）
+
+```python
+keywords: str | None = None         # fb_discover：查询词，换行分隔原文
+pages: int | None = None            # fb_discover：每词页数（1-10）
+provider: str | None = None         # fb_group：brightdata / apify
+posts_per_group: int | None = None  # fb_group：每群帖数上限
+```
+
+## 协调者裁定
+
+1. **插入位置**：`platform/server/app/api/tasks.py` 的 TaskParams 类，放在既有
+   `accounts` 字段之后、`repeat_interval` 之前（或紧跟 accounts——保持「专用字段
+   聚在一起」的注释风格）。
+2. **注释**：每条字段带中文注释说明用途（对齐既有字段的 `# → -n` 风格，但这两个
+   是批次专用字段，写 `# fb_discover：...` 即可）。
+3. **TASK_TYPES 并集断言**：TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPE_NAMES（Step 3.1
+   已注册两新类型）——测试断言 `'fb_discover' in TASK_TYPES` 且 `'fb_group' in
+   TASK_TYPES`。
+4. **测试基建**：platform/server/tests/test_batch_tasks.py 的 BatchTasksTestBase
+   （临时 sqlite + patch DB_PATH）。round-trip 测试：POST /api/tasks 携带四字段 →
+   落库 params_json → 读回断言字段齐全（参照既有 TaskCreate round-trip 测试写法，
+   若有）。若无既有 round-trip 测试，直接测 `TaskParams.model_validate(...)` 与
+   model_dump 往返即可（不依赖 HTTP 端点）。
+5. **不验证四字段取值范围**（pages 1-10 / provider 限定是前端 validate 的职责，
+   SPEC §7.3；后端仅透传）。
+
+## 代码库上下文
+
+- `platform/server/app/api/tasks.py`：TaskParams 在 92 行起（accounts 在 ~119 行，
+  repeat_interval 在 ~126 行）；TaskCreate 在 125 行起。
+- 测试运行：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks
+  -v`；回归同一文件全量。
+
+## TDD 纪律
+
+1. 先失败测试 → RED → 最小实现 → GREEN。
+2. 测试覆盖：TaskParams 四字段 model_dump 往返；TASK_TYPES 并集含两新类型。
+3. 输出干净。
+
+## Commit 约束
+
+- 只 `git add`：`platform/server/app/api/tasks.py`、
+  `platform/server/tests/test_batch_tasks.py`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 3.3 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-report.md
new file mode 100644
index 0000000..e7c5110
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-report.md
@@ -0,0 +1,84 @@
+# Step 3.3 报告 — api/tasks.py TaskParams 四字段
+
+- 状态：**DONE**
+- 日期：2026-08-09（北京时间）
+- 执行人：Step 3.3 implementer（subagent）
+- 环境：`platform/server/.venv/bin/python`；分支 `feat/facebook-daemon-integration`
+
+## 实现了什么
+
+按 SPEC §6.3 + 协调者裁定，`platform/server/app/api/tasks.py` 的 `TaskParams` 在
+`accounts` 字段之后、`repeat_interval` 之前追加四个批次专用字段（含中文注释，
+对齐既有 `# 专用字段聚在一起` 风格）：
+
+```python
+    # fb 批次专用：
+    keywords: str | None = None            # fb_discover：查询词，换行分隔原文
+    pages: int | None = None               # fb_discover：每词页数（1-10）
+    provider: str | None = None            # fb_group：brightdata / apify
+    posts_per_group: int | None = None     # fb_group：每群帖数上限
+```
+
+- 不验证四字段取值范围（pages 1-10 / provider 限定属前端 validate 职责，后端仅透传，遵裁定 5）。
+- 未触碰 runner / db 层——enqueue 消费端已由 Step 3.1/3.2 接好，本 Step 只补 API 层接收能力。
+
+## 测了什么
+
+`platform/server/tests/test_batch_tasks.py` 的 `TaskTypesTest` 新增两个测试：
+
+1. `test_task_types_union_contains_fb_batch_types`：TASK_TYPES（TASK_COMMANDS ∪ BATCH_TYPES
+   并集）含 `fb_discover` / `fb_group`（回归护栏，Step 3.1 已注册）。
+2. `test_fb_batch_params_roundtrip_via_create_task`：`TaskCreate(type="fb_discover", params={四字段})`
+   → 直接调 `create_task` 落库 → 读回 `tasks.params_json` → 断言四字段齐全
+   （keywords 多行原文、pages=3、provider="brightdata"、posts_per_group=50）。
+   库内有既有 TaskCreate round-trip 测试（无 HTTP TestClient 版），遵裁定 4 直接走
+   `create_task` 函数级 round-trip，不依赖 HTTP 端点。
+
+## TDD 证据
+
+**RED**（实现前先跑新测试）：
+
+```
+.venv/bin/python -m unittest tests.test_batch_tasks.TaskTypesTest -v
+...
+test_fb_batch_params_roundtrip_via_create_task ... ERROR
+...
+KeyError: 'keywords'
+```
+失败原因符合预期：pydantic v2 默认 `extra='ignore'`，四字段未声明 → 被静默丢弃，
+`params_json` 里没有 keywords，读回断言直接 KeyError。（TASK_TYPES 并集断言此时已
+绿——Step 3.1 已注册两类型，属正常回归护栏。）
+
+**GREEN**（加 4 行字段后）：
+
+```
+.venv/bin/python -m unittest tests.test_batch_tasks -v
+Ran 30 tests in 0.336s
+OK
+```
+
+**回归**（全量服务端测试）：
+
+```
+.venv/bin/python -m unittest discover -s tests -v
+Ran 72 tests in 0.271s
+OK
+```
+
+## 改动的文件
+
+- `platform/server/app/api/tasks.py`（TaskParams +4 字段，含注释）
+- `platform/server/tests/test_batch_tasks.py`（+2 测试）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-brief.md`（brief，随 commit 收录）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-report.md`（本文件）
+
+## 自查
+
+- **完整性**：SPEC §6.3 四字段名称/类型/默认值/注释逐字对齐；协调者裁定 1（插入位置）、2（中文注释）、3（并集断言）、4（测试基座）、5（不验证取值范围）全部满足。
+- **质量**：插入位置对齐既有 TaskParams 风格（专用字段聚在一起 + `# 前缀：用途` 注释），无重复/冲突字段名。
+- **纪律（YAGNI）**：只加 4 行字段 + 2 个测试，未动取值范围校验、未改 runner/db、未碰前端。
+- **测试**：真实行为（落库 params_json 读回，非 mock）；RED 亲眼失败（KeyError）；输出干净（无 print/日志污染）。
+
+## 疑虑
+
+无。取值范围校验留给前端（SPEC §7.3），后端透传语义与既有批次参数（如 limit）一致。
diff --git a/platform/server/app/api/tasks.py b/platform/server/app/api/tasks.py
index fba97b2..fbbe9e3 100644
--- a/platform/server/app/api/tasks.py
+++ b/platform/server/app/api/tasks.py
@@ -109,20 +109,25 @@ class TaskParams(BaseModel):
     max_consecutive_fail: int | None = None  # → --max-consecutive-fail
     block_rest_min: float | None = None     # → --block-rest-min
     block_rest_max: float | None = None     # → --block-rest-max
     # 开关
     use_proxy: bool | None = None           # true → --proxy
     headless: bool | None = None            # false → --headed
     auto_solve: bool | None = None          # false → --no-auto-solve
     retry_failed: bool | None = None        # 前端 1688_contact 表单开关遗留，不映射 CLI
     # wa_check 专用：
     accounts: list[str] | None = None       # 账号池，空 = 仅默认账号
+    # fb 批次专用：
+    keywords: str | None = None            # fb_discover：查询词，换行分隔原文
+    pages: int | None = None               # fb_discover：每词页数（1-10）
+    provider: str | None = None            # fb_group：brightdata / apify
+    posts_per_group: int | None = None     # fb_group：每群帖数上限
     # 注：batch_num/sample_min/sample_max 为 subprocess 类型（yiwugo）节奏参数；
     # wa_check 走 daemon 批次，只消费 limit/accounts
     # 循环模式：本轮正常结束（done/failed）后 N 秒自动重启；None/<=0 = 不循环
     repeat_interval: int | None = None
 
 
 class TaskCreate(BaseModel):
     type: str = Field(...)
     params: TaskParams = Field(default_factory=TaskParams)
 
diff --git a/platform/server/tests/test_batch_tasks.py b/platform/server/tests/test_batch_tasks.py
index 2cb31d8..d62fba1 100644
--- a/platform/server/tests/test_batch_tasks.py
+++ b/platform/server/tests/test_batch_tasks.py
@@ -434,20 +434,47 @@ class BatchStartStopTest(BatchTasksTestBase):
 
 
 class TaskTypesTest(BatchTasksTestBase):
     def test_task_types_include_batch_and_yiwugo(self):
         from app.api.tasks import TASK_TYPES
         for t in ("1688_contact", "madeinchina_contact", "1688_shop",
                   "1688_company", "madeinchina_shop", "wa_check",
                   "yiwugo_search"):
             self.assertIn(t, TASK_TYPES)
 
+    def test_task_types_union_contains_fb_batch_types(self):
+        """Step 3.3：TASK_TYPES 并集（TASK_COMMANDS ∪ BATCH_TYPES）含两新批次类型。"""
+        from app.api.tasks import TASK_TYPES
+        self.assertIn("fb_discover", TASK_TYPES)
+        self.assertIn("fb_group", TASK_TYPES)
+
+    def test_fb_batch_params_roundtrip_via_create_task(self):
+        """TaskCreate 携带四字段 → create_task 落库 params_json → 读回齐全。"""
+        from app.api.tasks import TaskCreate, create_task
+        body = TaskCreate(type="fb_discover", params={
+            "keywords": "耐克\n阿迪达斯",
+            "pages": 3,
+            "provider": "brightdata",
+            "posts_per_group": 50,
+        })
+        task = create_task(body)
+        conn = self._conn()
+        row = conn.execute(
+            "SELECT params_json FROM tasks WHERE id=?",
+            (task["id"],)).fetchone()
+        conn.close()
+        params = json.loads(row["params_json"])
+        self.assertEqual(params["keywords"], "耐克\n阿迪达斯")
+        self.assertEqual(params["pages"], 3)
+        self.assertEqual(params["provider"], "brightdata")
+        self.assertEqual(params["posts_per_group"], 50)
+
     def test_preview_batch_type_returns_description(self):
         from app.api.tasks import preview_task
         body = type("Body", (), {"type": "1688_contact",
                                  "params": type("P", (), {
                                      "model_dump": lambda self: {
                                          "limit": 50}})()})()
         result = preview_task(body)
         self.assertIn("批次", result["cmdline"])
 
     def test_runner_startup_skips_batch_orphan_cleanup(self):
