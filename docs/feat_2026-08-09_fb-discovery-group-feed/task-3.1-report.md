# Step 3.1 报告 — runner BATCH_TYPES + enqueue 分支（TDD）

## 实现了什么

1. **`platform/server/app/runner.py` BATCH_TYPES 追加**（SPEC §6.1 精确 dict，放在
   fb_post 之后）：

   ```python
   "fb_discover": {"queue": "discover_fb", "site": None,
                   "domain_suffix": "", "kind": "fb_discover"},
   "fb_group":    {"queue": "crawl_fb_group", "site": None,
                   "domain_suffix": "", "kind": "fb_group"},
   ```

   `BATCH_TYPE_NAMES = set(BATCH_TYPES)` 自动并集，已验证 `fb_discover`/`fb_group`
   进入 `api.tasks.TASK_TYPES`（TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPE_NAMES，
   api/tasks.py 无需改动）。

2. **`enqueue_batch_for_task` 追加两分支**（追加在既有 fb_post 分支之后、
   `return 0` 之前，逐字对照 SPEC §6.1）：

   ```python
   if spec["kind"] == "fb_discover":
       # Step 3.2 提供真实函数；此处懒导入，缺省 keywords=""、pages=1
       from app.db import enqueue_fb_discover_batch
       return enqueue_fb_discover_batch(task_id, params.get("keywords") or "",
                                        int(params.get("pages") or 1))
   if spec["kind"] == "fb_group":
       # Step 3.2 提供真实函数；此处懒导入，缺省 provider="brightdata"、
       # posts_per_group=50，limit 透传
       from app.db import enqueue_fb_group_batch
       return enqueue_fb_group_batch(task_id,
                                     (params.get("provider") or "brightdata"),
                                     int(params.get("posts_per_group") or 50),
                                     limit)
   ```

   **与 SPEC 的唯一偏差**：两分支用「分支内懒导入」而非「函数顶部统一 import」。
   原因：`enqueue_fb_discover_batch` / `enqueue_fb_group_batch` 尚不存在（Step 3.2
   实现），统一 import 会在任何一次调用时 `ImportError`（import 语句要求全部名字
   存在），且测试逐类型 mock 单个属性时同样会炸。懒导入在调用时解析模块属性，
   mock（create=True）与 Step 3.2 的真实函数都能命中，分派参数行为与 SPEC 逐字一致。
   Step 3.2 落地真实函数后，可（在彼 Step 内）把两个名字并入顶部 import 收尾。

3. **`platform/server/tests/test_batch_tasks.py` 扩展**：新增第 5 节
   `FbBatchDispatchTest` 4 个测试，mock `app.db` 模块属性
   （`patch.object(db_module, ..., create=True)`——属性不存在需 create）断言分派
   参数精确透传：
   - fb_discover 缺省：`enqueue_fb_discover_batch(7, "", 1)`
   - fb_discover 显式：`enqueue_fb_discover_batch(7, "面膜 洗面奶", 3)`（keywords
     原样透传、pages 转 int）
   - fb_group 缺省：`enqueue_fb_group_batch(8, "brightdata", 50, 0)`
   - fb_group 显式+limit 透传：`enqueue_fb_group_batch(8, "scraperapi", 30, 120)`
   - 每个测试同时断言 mock 返回值原样透出（n=3/4）

   **未实现 app/db.py 的两个 enqueue 函数**（Step 3.2 的活，协调者裁定）。

## TDD 证据

### RED

命令：

```
cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks.FbBatchDispatchTest -v
```

第一轮失败输出（`patch.object` 无 create → 模块属性不存在报错）：

```
AttributeError: <module 'app.db' ...> does not have the attribute 'enqueue_fb_group_batch'
FAILED (errors=4)
```

按 TDD skill「测试报错要修到能正常失败为止」，给 `patch.object` 加 `create=True`
（函数本就不存在，属测试基建修正，非改实现）。第二轮失败输出：

```
AssertionError: Expected 'enqueue_fb_group_batch' to be called once. Called 0 times.
Ran 4 tests in 0.240s
FAILED (failures=4)
```

**为什么符合预期**：BATCH_TYPES 已有 fb 条目但分派分支缺失，`enqueue_batch_for_task`
走到 `return 0`，enqueue mock 一次也没被调用——失败点精确指向缺失的分派行为
（功能缺失，非笔误）。

### GREEN

命令：

```
cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks -v
```

输出（节选）：

```
test_fb_discover_dispatch_with_defaults ... ok
test_fb_discover_dispatch_with_explicit_keywords_pages ... ok
test_fb_group_dispatch_with_defaults ... ok
test_fb_group_dispatch_with_explicit_values_and_limit ... ok
...
Ran 21 tests in 0.338s
OK
```

中间曾出现一次 `ImportError: cannot import name 'enqueue_fb_group_batch'`（统一
import 语句要求全部名字存在而 fb 函数未实现）——按 RED 修到能正常失败的原则改为
分支内懒导入后转绿。

### 回归

```
cd platform/server && .venv/bin/python -m unittest discover -s tests
Ran 63 tests in 0.267s
OK
```

既有 17 个批次测试 + 全量 server 测试套件（63）零回归。BATCH_TYPE_NAMES 自动并集
已验证：`fb_discover in TASK_TYPES` / `fb_group in TASK_TYPES` 均 True。

## 改动的文件

- `platform/server/app/runner.py`（+14 行：BATCH_TYPES 2 条目 + 分派 2 分支）
- `platform/server/tests/test_batch_tasks.py`（+54 行：FbBatchDispatchTest 4 测试）
- 本 report（+ 本 Step 的 brief 一并提交）

## 自查

- **完整性**：SPEC §6.1 两条 BATCH_TYPES 条目逐字一致（queue/site/domain_suffix/
  kind）；两分支缺省值（keywords=""、pages=1、provider="brightdata"、
  posts_per_group=50）与显式值/limit 透传全对（测试断言精确参数）。
- **质量**：分支插在 fb_post 之后、`return 0` 之前（协调者裁定）；懒导入带注释
  说明 Step 3.2 归属，与既有 enqueue 模式风格一致；对齐既有 BATCH_TYPES 缩进风格
  （对齐冒号）。
- **纪律**：YAGNI——只做 brief 要求的两处改动 + 测试；**没有**实现 app/db.py 的
  `enqueue_fb_discover_batch` / `enqueue_fb_group_batch`（mock create=True 断言
  分派）；未动其他文件。
- **测试**：真实调用 `enqueue_batch_for_task`，仅 mock 尚不存在的 enqueue 函数
  （属「不得已」的最小 mock，brief 协调者明确要求此方式）；4 测试都亲眼看失败过
  （RED）；输出干净（无 error/warning）。

## 疑虑

1. **懒导入 vs SPEC 顶部统一 import**：行为一致但形式不同（见上「唯一偏差」）。
   若协调者希望严格逐字 SPEC，可等 Step 3.2 实现真实函数后在彼 Step 把两个名字
   并入顶部 import——本 Step 不改动以免回归。
2. mock 用 `create=True` 是 brief 协调者裁定（函数尚不存在）的直接推论；Step 3.2
   后如把 mock 换成真实函数路径（届时函数已存在），`create=True` 可去掉，属彼 Step
   收尾工作，本 Step 不越界。

---

## 修复 1（review 第 1 轮发现 #1）— BATCH_TYPES 新条目格式对齐既有风格

### 改了什么

`platform/server/app/runner.py` BATCH_TYPES 中 fb_discover/fb_group 两条目由
「行内紧凑 dict」改为与既有 7 条一致的多行 dict 格式（`{` 独占首行、每行 k-v、
`},` 收尾），与 wa_check/fb_post 风格逐字对齐：

```python
"fb_discover": {
    "queue": "discover_fb", "site": None,
    "domain_suffix": "", "kind": "fb_discover",
},
"fb_group": {
    "queue": "crawl_fb_group", "site": None,
    "domain_suffix": "", "kind": "fb_group",
},
```

键值（queue/site/domain_suffix/kind）、顺序、语义零变化——纯格式改动，行为不变。
enqueue 分派分支与测试文件本修复未触碰。

### 覆盖测试

```
cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks -v
Ran 21 tests in 0.336s
OK
```

全绿（含 FbBatchDispatchTest 4 测试 + 既有 17 批次测试）。

### 全量回归

```
cd platform/server && .venv/bin/python -m unittest discover -s tests
Ran 63 tests in 0.252s
OK
```

零回归。

### Commit

`git add platform/server/app/runner.py docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md`
（仅两文件，未 add -A）。

### 疑虑

无——格式与既有条目一致，行为零变化，测试全绿。
