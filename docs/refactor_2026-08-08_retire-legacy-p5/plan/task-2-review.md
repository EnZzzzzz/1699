# Review package — Step 1.2 (BASE 7b5401c365afc5eeb6ab77ac28bd0bf2a5173971..HEAD)

## git log
27f1f5b docs(p5): Step 1.2 实施记录——task-2 report + 冒烟证据
c46fc60 refactor(p5): 删除 cmdparse 从命令导入链路与 TaskParams 死字段

## git diff --stat
 .../plan/task-2-report.md                          |  87 +++++++++++
 .../plan/task-2-smoke.txt                          |  14 ++
 platform/server/app/api/tasks.py                   |  21 ---
 platform/server/app/cmdparse.py                    | 169 ---------------------
 platform/server/app/runner.py                      |   3 -
 5 files changed, 101 insertions(+), 193 deletions(-)

## git diff -U10
diff --git a/docs/refactor_2026-08-08_retire-legacy-p5/plan/task-2-report.md b/docs/refactor_2026-08-08_retire-legacy-p5/plan/task-2-report.md
new file mode 100644
index 0000000..4e29c0e
--- /dev/null
+++ b/docs/refactor_2026-08-08_retire-legacy-p5/plan/task-2-report.md
@@ -0,0 +1,87 @@
+# task-2-report — Step 1.2 cmdparse + 死字段删除
+
+> implementer 完成报告。需求来源：同目录 `task-2-brief.md`。分支：`refactor/retire-legacy-p5`。
+
+## 一、实现了什么（删除清单逐项）
+
+| # | 删除项 | 位置 | 状态 |
+|---|---|---|---|
+| 1 | `cmdparse.py` 整个文件（169 行） | `platform/server/app/cmdparse.py` | ✅ git rm，已删 |
+| 2a | `CommandParse` pydantic 模型 | `app/api/tasks.py`（原约 171-174） | ✅ 已删 |
+| 2b | `@router.post("/tasks/parse")` 端点 `parse_task_command`（含函数内 `from app.cmdparse import ...` 延迟导入） | `app/api/tasks.py`（原约 175-186） | ✅ 已删 |
+| 2c | `TaskParams` 三字段：`interval`（含两行注释）、`batch_rest_min`、`batch_rest_max` | `app/api/tasks.py`（原约 118-122） | ✅ 已删 |
+| 3a | `build_command` 死分支 `if task_type == "1688_contact" and params.get("retry_failed") is True: cmd.append("--retry-failed")` | `app/runner.py`（原约 142-143） | ✅ 已删 |
+| 3b | docstring 对应行「retry_failed=true 且 1688_contact→--retry-failed；」 | `app/runner.py`（原约 120） | ✅ 已删 |
+
+**保留面核验（未动）**：`/tasks/preview` 批次分支（BATCH_TYPE_NAMES）与 yiwugo build_command 分支均保留；
+`TaskParams.retry_failed` 字段保留（前端 1688_contact 表单开关在用，Step 2.1 处理）；batch_num/sample_min/sample_max/
+accounts/limit/repeat_interval 等字段未动；runner Timer 全套、subprocess 机械、批次/sweeper 全套未动。
+
+## 二、测试输出
+
+聚焦测试（`-k "task or preview or runner"`）：`25 passed, 31 deselected in 0.28s`
+
+全量测试（`platform/server/tests/`，基线 56 passed）：
+
+```
+======================== 56 passed, 1 warning in 0.37s =========================
+```
+
+净变化零（无测试依赖 cmdparse/死字段，与验收预期一致）。唯一 warning 为既有
+StarletteDeprecationWarning（httpx/testclient），与本次改动无关。
+
+## 三、冒烟 curl 输出（临时 uvicorn 8766 + /tmp 库副本）
+
+证据文件：`plan/task-2-smoke.txt`（完整原文），摘要如下：
+
+```
+[1] 批次分支 1688_contact  limit=100
+    {"cmd":null,"cmdline":"批次提交：crawl_1688_contact，100 条"}   HTTP 200
+[2] yiwugo build_command 分支  limit=50
+    {"cmd":[".../.venv/bin/python","-m","fetcher","yiwugo","search","--limit","50"],
+     "cmdline":"python -m fetcher yiwugo search --limit 50"}        HTTP 200
+[3] 对照组 wa_check（brief 预期 422）
+    {"cmd":null,"cmdline":"批次提交：wa_check"}                     HTTP 200
+[4] 补充对照：未知类型 not_a_type
+    {"detail":"未知任务类型 'not_a_type'，可选: [...]"}             HTTP 422
+```
+
+临时实例已按实际监听 pid 杀掉，8766 端口已释放；生产库 `.cache/1688.db` 未写、8765 活服务未动。
+
+### 冒烟与 brief 预期的两处偏差（均非缺陷，记录在案）
+
+1. **[1] 队列名**：brief 内联预期写「crawl_1688，100 条」，代码实际队列名为 `crawl_1688_contact`
+   （`runner.py BATCH_TYPES["1688_contact"]["queue"]`）。批次分支行为（cmd:null + 批次描述 + limit）完全符合预期，
+   只是 brief 对队列名写得简化了。
+2. **[3] wa_check 预期 422 未出现**：brief 写「wa_check 现走 build_command 会 422」，但 Step 1.1 之后
+   `wa_check` 已注册进 `BATCH_TYPES`（runner.py:57），preview 走批次分支返回 200 `批次提交：wa_check`。
+   这恰好证明 wa_check 已彻底脱离 build_command 旧路径，行为变化比 brief 预期更彻底；「记录即可非缺陷」，
+   此处如实记录。422 路径由 [4] 未知类型对照验证仍工作正常。
+
+## 四、改动文件
+
+```
+D platform/server/app/cmdparse.py        （删除，169 行）
+M platform/server/app/api/tasks.py       （-21 行：3 字段 + CommandParse + /tasks/parse 端点）
+M platform/server/app/runner.py          （-3 行：死分支 + docstring 行）
+```
+
+仅 commit 本 Step 涉及文件（scoped add，含 docs/ 下 SPEC/brief/smoke 证据按 ledger 惯例随附）。
+
+## 五、自查结果（验收标准逐条）
+
+- [x] 平台 pytest 全绿：56 passed（基线持平）
+- [x] `app/` grep `cmdparse\|parse_command\|CommandParse\|/tasks/parse` 零命中
+- [x] `app/` grep `batch_rest_min\|batch_rest_max` 零命中；`interval` 仅剩 preserved 的
+      Timer/sweeper 局部变量（读 `repeat_interval`，如 `_next_restart_at`、`_schedule_restart`），
+      非死字段 `TaskParams.interval`，属保留面（runner Timer 全套）
+- [x] `runner.py` 无 `retry_failed` 残留；`tasks.py` 的 `TaskParams.retry_failed` 字段保留（预期）
+- [x] 临时 uvicorn 冒烟三组 curl 输出落 `plan/task-2-smoke.txt`
+
+## 六、疑虑
+
+1. `TaskParams.retry_failed` 字段（tasks.py 117 行）注释仍写「true 且 1688_contact → --retry-failed」，
+   该行为已随 build_command 死分支删除。字段本身按 brief 保留（前端在用），注释轻微过期——
+   属 Step 2.1（前端表单开关退役）后一并清理的范畴，本 Step 照单未动。
+2. `preview` 端点对批次类型返回 `cmd:null`，对非批次类型返回真实命令；`wa_check` 现走批次分支属 Step 1.1
+   迁移的自然结果，若后续有前端依赖 preview 的 `cmd` 字段对 wa_check 做展示，需留意（暂未发现引用）。
diff --git a/docs/refactor_2026-08-08_retire-legacy-p5/plan/task-2-smoke.txt b/docs/refactor_2026-08-08_retire-legacy-p5/plan/task-2-smoke.txt
new file mode 100644
index 0000000..f80ad3c
--- /dev/null
+++ b/docs/refactor_2026-08-08_retire-legacy-p5/plan/task-2-smoke.txt
@@ -0,0 +1,14 @@
+=== [1] 批次分支 1688_contact (期望 {"cmd":null,"cmdline":"批次提交：crawl_1688，100 条"}) ===
+{"cmd":null,"cmdline":"批次提交：crawl_1688_contact，100 条"}
+HTTP 200
+
+=== [2] yiwugo build_command 分支 (期望含 python -m fetcher yiwugo search) ===
+{"cmd":["/Volumes/DataDrive/proj/public/1699/platform/server/.venv/bin/python","-m","fetcher","yiwugo","search","--limit","50"],"cmdline":"python -m fetcher yiwugo search --limit 50"}
+HTTP 200
+
+=== [3] 对照组 wa_check (期望 422，行为变化记录非缺陷) ===
+{"cmd":null,"cmdline":"批次提交：wa_check"}
+HTTP 200
+=== [4] 补充对照：未知类型 (期望 422) ===
+{"detail":"未知任务类型 'not_a_type'，可选: ['1688_company', '1688_contact', '1688_shop', 'madeinchina_contact', 'madeinchina_shop', 'wa_check', 'yiwugo_search']"}
+HTTP 422
diff --git a/platform/server/app/api/tasks.py b/platform/server/app/api/tasks.py
index 8802343..f53f209 100644
--- a/platform/server/app/api/tasks.py
+++ b/platform/server/app/api/tasks.py
@@ -108,25 +108,21 @@ class TaskParams(BaseModel):
     net_retry: int | None = None            # → --net-retry
     max_consecutive_fail: int | None = None  # → --max-consecutive-fail
     block_rest_min: float | None = None     # → --block-rest-min
     block_rest_max: float | None = None     # → --block-rest-max
     # 开关
     use_proxy: bool | None = None           # true → --proxy
     headless: bool | None = None            # false → --headed
     auto_solve: bool | None = None          # false → --no-auto-solve
     retry_failed: bool | None = None        # true 且 1688_contact → --retry-failed
     # wa_check 专用：
-    interval: float | None = None           # 旧参数：固定调用间隔秒（等价
-                                            # sample_min == sample_max）
     accounts: list[str] | None = None       # 账号池，空 = 仅默认账号
-    batch_rest_min: float | None = None     # wa_check 批间休息下限（秒）
-    batch_rest_max: float | None = None     # wa_check 批间休息上限（秒）
     # 注：wa_check 复用上方 batch_num（每批调用次数）、
     # sample_min / sample_max（调用间隔范围）三个字段
     # 循环模式：本轮正常结束（done/failed）后 N 秒自动重启；None/<=0 = 不循环
     repeat_interval: int | None = None
 
 
 class TaskCreate(BaseModel):
     type: str = Field(...)
     params: TaskParams = Field(default_factory=TaskParams)
 
@@ -161,37 +157,20 @@ def _get_task_row(task_id: int):
         row = conn.execute("SELECT * FROM tasks WHERE id=?",
                            (task_id,)).fetchone()
     if not row:
         raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
     return row
 
 
 # ---------------- 命令预览 / 参数修改 ----------------
 
 
-class CommandParse(BaseModel):
-    command: str = Field(..., min_length=1)
-
-
-@router.post("/tasks/parse")
-def parse_task_command(body: CommandParse):
-    """把 fetcher CLI 命令文本解析回 type + params（build_command 的反向）。
-
-    容忍 python -m fetcher / 直接 fetcher 前缀与 while/for + sleep N 循环包裹。
-    """
-    from app.cmdparse import CommandParseError, parse_command
-    try:
-        return parse_command(body.command)
-    except CommandParseError as e:
-        raise HTTPException(status_code=422, detail=str(e))
-
-
 @router.post("/tasks/preview")
 def preview_task(body: TaskCreate):
     """按 type + params 预览实际将执行的 fetcher CLI 命令（不落库）。"""
     if body.type not in TASK_TYPES:
         raise HTTPException(
             status_code=422,
             detail=f"未知任务类型 {body.type!r}，可选: {TASK_TYPES}")
     params = body.params.model_dump()
     if body.type in BATCH_TYPE_NAMES:
         spec = BATCH_TYPES[body.type]
diff --git a/platform/server/app/cmdparse.py b/platform/server/app/cmdparse.py
deleted file mode 100644
index 8b554c5..0000000
--- a/platform/server/app/cmdparse.py
+++ /dev/null
@@ -1,169 +0,0 @@
-# -*- coding: utf-8 -*-
-"""fetcher CLI 命令文本 → 任务 type + params 的反向解析（POST /api/tasks/parse）。
-
-容忍形式：
-- python -m fetcher ... / python3 -m fetcher ... / 直接 fetcher ...
-- while/for 循环包裹 + sleep N → repeat_interval=N（秒）
-
-flag 映射与 runner.build_command 正好反向。
-"""
-
-import re
-import shlex
-
-
-class CommandParseError(ValueError):
-    """命令无法识别 → API 层转 422。"""
-
-
-# (站点, 子任务) → 平台任务类型
-SITE_TASKS = {
-    ("1688", "shop"): "1688_shop",
-    ("1688", "contact"): "1688_contact",
-    ("1688", "company"): "1688_company",
-    ("yiwugo", "search"): "yiwugo_search",
-}
-
-# 开关 flag → (params 键, 置为的值)
-_BOOL_FLAGS = {
-    "--proxy": ("use_proxy", True),
-    "--headed": ("headless", False),
-    "--no-auto-solve": ("auto_solve", False),
-    "--retry-failed": ("retry_failed", True),
-}
-
-# 取值 flag → (params 键, 类型转换)；含 argparse 缩写形式 --worker
-_VALUE_FLAGS = {
-    "-n": ("batch_num", int),
-    "--num": ("batch_num", int),
-    "--limit": ("limit", int),
-    "--max-batches": ("max_batches", int),
-    "--workers": ("workers", int),
-    "--worker": ("workers", int),
-    "--channels": ("channels", int),
-    "--batch-rest": ("batch_rest", float),
-    "--sample-min": ("sample_min", float),
-    "--sample-max": ("sample_max", float),
-    "--rest-every": ("rest_every", int),
-    "--rest-min": ("rest_min", float),
-    "--rest-max": ("rest_max", float),
-    "--stagger-min": ("stagger_min", float),
-    "--stagger-max": ("stagger_max", float),
-    "--ip-retry": ("ip_retry", int),
-    "--net-retry": ("net_retry", int),
-    "--max-consecutive-fail": ("max_consecutive_fail", int),
-    "--block-rest-min": ("block_rest_min", float),
-    "--block-rest-max": ("block_rest_max", float),
-}
-
-# 解释器 / 模块调用前缀
-_PREFIX_WORDS = {"python", "python3", "-m", "fetcher"}
-
-# shell 循环 / 结构关键字（静默忽略，不进 warnings）
-_LOOP_WORDS = {"while", "do", "done", "true", "for", "in", "then", "fi",
-               "if", "until", "until", "esac", "case"}
-
-_NUM_RE = re.compile(r"^\d+(\.\d+)?$")
-
-
-def parse_command(command: str) -> dict:
-    """命令文本 → {"type": ..., "params": {...}, "warnings": [...]}。
-
-    无法识别站点任务时抛 CommandParseError。
-    """
-    warnings: list[str] = []
-    try:
-        tokens = shlex.split(command or "")
-    except ValueError as e:
-        raise CommandParseError(f"命令切分失败: {e}")
-    # shell 分号会黏在 token 尾部（如 "true;" "1800;"），统一剥掉
-    tokens = [t.rstrip(";") for t in tokens]
-    tokens = [t for t in tokens if t]
-    if not tokens:
-        raise CommandParseError("空命令")
-
-    params: dict = {}
-
-    # ---- 循环识别：sleep N（配合 while/for 循环或直接出现）----
-    cleaned: list[str] = []
-    i = 0
-    while i < len(tokens):
-        tok = tokens[i]
-        if tok == "sleep" and i + 1 < len(tokens) and _NUM_RE.match(tokens[i + 1]):
-            n = int(float(tokens[i + 1]))
-            if n > 0:
-                params["repeat_interval"] = n
-                warnings.append(f"检测到循环包裹，已设为每 {n} 秒自动重启")
-            i += 2
-            continue
-        cleaned.append(tok)
-        i += 1
-
-    # ---- 定位站点任务：1688 shop/contact/company、yiwugo search ----
-    idx = None
-    for j, tok in enumerate(cleaned):
-        if tok in ("1688", "yiwugo"):
-            idx = j
-            break
-    if idx is None:
-        raise CommandParseError(
-            "无法识别站点任务：未找到 1688 / yiwugo 子命令；"
-            "支持 1688 shop|contact|company、yiwugo search")
-    if idx + 1 >= len(cleaned):
-        raise CommandParseError(f"站点 {cleaned[idx]!r} 后缺少任务名")
-    site, task = cleaned[idx], cleaned[idx + 1]
-    task_type = SITE_TASKS.get((site, task))
-    if not task_type:
-        raise CommandParseError(
-            f"无法识别的任务 {site} {task!r}；"
-            "支持 1688 shop|contact|company、yiwugo search")
-
-    # ---- 站点前的 token：解释器前缀 / 循环关键字跳过，其余进 warnings ----
-    for tok in cleaned[:idx]:
-        if tok in _PREFIX_WORDS or tok in _LOOP_WORDS:
-            continue
-        warnings.append(f"无法识别的 token: {tok}")
-
-    # ---- flag 解析（与 build_command 反向）----
-    rest = cleaned[idx + 2:]
-    i = 0
-    while i < len(rest):
-        tok = rest[i]
-        if tok in _BOOL_FLAGS:
-            key, val = _BOOL_FLAGS[tok]
-            params[key] = val
-            i += 1
-        elif tok in _VALUE_FLAGS:
-            key, conv = _VALUE_FLAGS[tok]
-            if i + 1 >= len(rest):
-                warnings.append(f"参数 {tok} 缺少取值，已忽略")
-                i += 1
-                continue
-            raw = rest[i + 1]
-            try:
-                params[key] = conv(raw)
-            except ValueError:
-                warnings.append(f"参数 {tok} 取值 {raw!r} 无法解析，已忽略")
-            i += 2
-        elif tok.startswith("--") and "=" in tok:
-            # --flag=value 形式
-            flag, _, raw = tok.partition("=")
-            if flag in _VALUE_FLAGS:
-                key, conv = _VALUE_FLAGS[flag]
-                try:
-                    params[key] = conv(raw)
-                except ValueError:
-                    warnings.append(f"参数 {flag} 取值 {raw!r} 无法解析，已忽略")
-            elif flag in _BOOL_FLAGS:
-                key, val = _BOOL_FLAGS[flag]
-                params[key] = val
-            else:
-                warnings.append(f"无法识别的 token: {tok}")
-            i += 1
-        elif tok in _LOOP_WORDS:
-            i += 1
-        else:
-            warnings.append(f"无法识别的 token: {tok}")
-            i += 1
-
-    return {"type": task_type, "params": params, "warnings": warnings}
diff --git a/platform/server/app/runner.py b/platform/server/app/runner.py
index 8b76ca2..877ff9f 100644
--- a/platform/server/app/runner.py
+++ b/platform/server/app/runner.py
@@ -110,39 +110,36 @@ _NUMERIC_FLAGS = (
 )
 
 
 def build_command(task_type: str, params: dict) -> list:
     """任务类型 + params → fetcher CLI 命令列表（subprocess 直接 Popen）。
 
     规则：
     - 数值/时长参数值非 None 才输出（缺省=CLI 自带默认值，保持命令干净）；
     - 开关：use_proxy=true→--proxy；headless=false→--headed；
       auto_solve=false→--no-auto-solve；
-      retry_failed=true 且 1688_contact→--retry-failed；
     """
     sub = TASK_COMMANDS.get(task_type)
     if not sub:
         raise ValueError(f"未知任务类型: {task_type}")
     params = params or {}
     cmd = [PYTHON_BIN, "-m", "fetcher"] + sub
     for key, flag in _NUMERIC_FLAGS:
         val = params.get(key)
         if val is not None:
             cmd += [flag, str(val)]
     if params.get("use_proxy") is True:
         cmd.append("--proxy")
     if params.get("headless") is False:
         cmd.append("--headed")
     if params.get("auto_solve") is False:
         cmd.append("--no-auto-solve")
-    if task_type == "1688_contact" and params.get("retry_failed") is True:
-        cmd.append("--retry-failed")
     return cmd
 
 
 def _db_write(sql: str, params=()) -> None:
     """短事务写入；busy_timeout 避免与 WAL 写入者冲突。"""
     conn = sqlite3.connect(DB_PATH, timeout=30)
     try:
         conn.execute("PRAGMA busy_timeout = 30000")
         conn.execute(sql, params)
         conn.commit()
