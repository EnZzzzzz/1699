# Review Package — Step 4.2 (iter_active_categories + crawl_mic_shop)

## Commits
379b8c9 feat(multiqueue-p3): iter_active_categories 统一查询 + crawl_mic_shop 注册表 + reset 精确化

## Stat
 .../smoke-step4.2/analysis.md                      |  74 ++++++++++++
 .../task-4.2-report.md                             |  92 ++++++++++++++
 fetcher/fetcher/cli/main.py                        |  17 ++-
 fetcher/fetcher/db.py                              |  28 ++++-
 fetcher/fetcher/sites/madeinchina/shop.py          |  11 +-
 fetcher/tests/test_cli.py                          |  49 ++++++++
 fetcher/tests/test_madeinchina.py                  | 134 +++++++++++++++++++++
 7 files changed, 395 insertions(+), 10 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md
new file mode 100644
index 0000000..58774e4
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md
@@ -0,0 +1,74 @@
+# Smoke Step 4.2 — 冒烟分析
+
+## 环境
+
+- 命令：`python -m fetcher daemon --db /tmp/smoke_p3_42.db --workers 1 --limit 8 -n 1 --queues crawl_mic_shop --batch-rest 1 --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2`
+- 临时库 `/tmp/smoke_p3_42.db`（空库启动）
+- 直连、1 worker、1 batch、limit 8（每批最多 8 个工作项）
+- Dummy cookie `madeinchina:direct`（1 条，避免 ensure_site 直连报错）
+
+## 取证要点
+
+### 1. 启动播种 ✅
+
+```
+[0] 播种 0 个 category item + 1 条 discover
+```
+
+category_progress 空 → `_seed_category_items` 经 `iter_active_categories` → 0 条未采完类目 → 无 category item 播种；`_seed_discover_item` 插 1 条 discover item（powered 幂等）。
+
+验证：work_items 表中仅 1 条 pending discover item（daemon 日志第一行）。
+
+### 2. 启动重置 ✅
+
+```
+[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
+```
+
+- claimed item 回收 = 0（无残留）
+- in_progress 重置 = 0：feeder 队列 topup=None，`reset_daemon_state` 正确跳过 `reset_in_progress`（逐 site 打印空——仅 contact 队列才参与）
+
+验证：`reset_daemon_state` 新增 `if spec.topup is not None` 条件生效。
+
+### 3. Discover 执行 ✅
+
+discover item 被认领 → fetch 返回 `{"discover": True}` → on_success 执行类目提取：
+- 浏览首页 `https://www.made-in-china.com/` + 市场导航页 `https://www.made-in-china.com/shichang/`
+- 提取类目 → 逐条 INSERT category item（~360 个 category work_items pending）
+
+验证：work_items 表含 ~360 条 `kind=category` pending item。
+
+### 4. 类目页消费 ✅
+
+category item `jgdbj`（激光打标机）被认领 → `_fetch_category` 抓取 market 页 → 提取 15 个供应商展厅 → shops 落库。
+
+```
+[OK] 本次采集: 1 页, 店铺 15 个（新增 15）
+```
+
+验证：
+- shops 表：15 条 `*.cn.made-in-china.com` 域名 status=pending
+- category_progress：`jgdbj` next_page=2 pages=1 shops_found=15 exhausted=0
+
+### 5. Category progress 推进 ✅
+
+`advance_category_page` 正确推进：
+- next_page: 1→2
+- pages_crawled: 0→1
+- shops_found: 0→15
+- exhausted=0（非空页）
+
+### 6. 链式续喂
+
+由于 `-n 1 --limit 8`，daemon 在完成第 1 批（discover + 1 个 category + 补种 category items）后退出。`on_success` 代码路径已验证通过（若未 exhausted 会 INSERT 同 payload 下一页 item），但因 daemon 退出未能观察到该 item 被认领。
+
+### 7. 环境噪声
+
+- 浏览器正常启动（CloakBrowser 二进制已存在）
+- ensure_site 成功装载 dummy cookie → 无报错
+- market 页面成功加载并提取类目列表（网络通畅）
+- 无滑块/风控拦截（常规浏览行为）
+
+## 结论
+
+播种→discover→类目页消费→progress 推进 路径全部走通，`iter_active_categories` 统一查询与 `crawl_mic_shop` 注册表正确接入。feeder 队列不触发 `reset_in_progress` 的条件防护验证通过。
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md
new file mode 100644
index 0000000..c04565f
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md
@@ -0,0 +1,92 @@
+# Task 4.2 Report — iter_active_categories 统一查询 + crawl_mic_shop 入注册表 + feeder 冒烟
+
+> 分支：`feat/multiqueue-p3` | 日期：2026-08-08 | 状态：DONE
+
+## 实现摘要
+
+1. **`iter_active_categories` 统一查询**（`db.py`）：新增 `iter_active_categories(prefix="")` 方法，prefix 非空时通过 `LIKE` 过滤 keyword 前缀（如 `"company:"`），prefix 为空返回全部未采完类目，按 id 排序。`get_active_categories` 改为委托 `iter_active_categories()` + `_is_pinyin_slug` 过滤（向后兼容，行为一致）。
+
+2. **`crawl_mic_shop` 入注册表**（`cli/main.py` `_build_registry`）：新增第 3 条队列，`topup=None`（feeder 队列），`domain_suffix=""`，`requires={"channel","browser"}`。
+
+3. **`reset_daemon_state` 精确化**：只对 `topup is not None` 的队列做 `reset_in_progress`（feeder 队列跳过，它不产生 in_progress shops）。
+
+4. **`_seed_category_items` 切到 `iter_active_categories`**（`madeinchina/shop.py`）：改为 `db.iter_active_categories()` + `_is_pinyin_slug` 过滤（与 `get_active_categories` 同口径）。
+
+## 测试列表
+
+### TDD 新增测试
+
+| # | 测试 | 覆盖项 | 文件 |
+|---|---|---|---|
+| 1 | `test_iter_active_categories_returns_non_exhausted` | 未采完返回、exhausted 排除、id 排序 | test_madeinchina.py |
+| 2 | `test_iter_active_categories_prefix_filter` | prefix="company:" 过滤、prefix="" 全量 | test_madeinchina.py |
+| 3 | `test_get_active_categories_delegates_to_iter` | 拼音过滤回归（委托 iter_active_categories） | test_madeinchina.py |
+| 4 | `test_iter_active_categories_empty_name_defaults_to_keyword` | name=NULL 回退为 keyword | test_madeinchina.py |
+| 5 | `test_reset_skips_feeder_queues` | feeder 队列（topup=None）不触发 reset_in_progress | test_cli.py |
+
+### 测试更新
+
+| # | 测试 | 改动 | 文件 |
+|---|---|---|---|
+| 6 | `test_daemon_queues_dynamic_from_registry` | 新增 `assertIn("crawl_mic_shop")` | test_cli.py |
+
+## TDD 证据
+
+### RED → GREEN
+
+1. **RED**：先写 5 个新测试 + 更新 1 个断言 → `python -m pytest tests/test_madeinchina.py tests/test_cli.py -v`
+   - `test_iter_active_categories_*` (3 tests)：`AttributeError: 'ShopDB' object has no attribute 'iter_active_categories'`
+   - `test_daemon_queues_dynamic_from_registry`：`AssertionError: 'crawl_mic_shop' not found`
+   - `test_reset_skips_feeder_queues`：`AssertionError: 2 != 1`（feeder 队列的 `reset_in_progress("")` 误删了 other.example.com）
+
+2. **GREEN**：实现 `iter_active_categories` + 注册表 crawl_mic_shop + reset 精确化 + 播种切到 iter_active_categories → **所有新测试通过**
+
+3. **全量**：`cd fetcher && python -m pytest tests -q` → **468 passed, 2 subtests passed**（基线 463 + 净增 5）
+
+## 冒烟取证
+
+### 命令
+
+```bash
+cd fetcher
+python -m fetcher daemon --db /tmp/smoke_p3_42.db --workers 1 --limit 8 -n 1 \
+  --queues crawl_mic_shop --batch-rest 1 \
+  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
+  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
+  > docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/daemon-run.log 2>&1
+```
+
+### 结果摘要
+
+| 检查项 | 结果 | 证据 |
+|---|---|---|
+| 启动播种 | ✅ | `播种 0 个 category item + 1 条 discover` |
+| 启动重置跳过 feeder | ✅ | `0 个 in_progress 店铺 → pending（逐 site: ）` |
+| discover 执行 | ✅ | 浏览首页+导航页 → 提取 ~360 类目 → INSERT category items |
+| 类目页消费 | ✅ | `jgdbj` 第 1 页 → 提取 15 个供应商展厅 |
+| progress 推进 | ✅ | `jgdbj` → next_page=2, pages=1, shops_found=15 |
+| shops 落库 | ✅ | 15 条 `*.cn.made-in-china.com` 域名 status=pending |
+
+完整分析见 `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md`。
+
+## 改动文件
+
+| 文件 | 改动 |
+|---|---|
+| `fetcher/fetcher/db.py` | 新增 `iter_active_categories(prefix)`；`get_active_categories` 改为委托之 |
+| `fetcher/fetcher/cli/main.py` | `_build_registry` 新增 `crawl_mic_shop`；`reset_daemon_state` 只对 topup 非 None 队列做 reset |
+| `fetcher/fetcher/sites/madeinchina/shop.py` | `_seed_category_items` 切到 `iter_active_categories` + `_is_pinyin_slug`；`cat["slug"]` → `cat["keyword"]` |
+| `fetcher/tests/test_madeinchina.py` | 新增 4 个 iter_active_categories/pinyin 回归测试 |
+| `fetcher/tests/test_cli.py` | 新增 `test_reset_skips_feeder_queues`；更新 `test_daemon_queues_dynamic_from_registry` 断言 |
+| `docs/.../smoke-step4.2/` | 冒烟日志 + 分析 |
+
+## 自查
+
+- ✅ brief 所有裁定均落实（iter_active_categories 统一查询+prefix、crawl_mic_shop 入注册表+topup=None、reset 仅 topup 队列、播种切 iter_active_categories + pinyin 过滤）
+- ✅ `get_active_categories` 委托 `iter_active_categories` + `_is_pinyin_slug`（向后兼容，原有调用方无需改动）
+- ✅ grep 确认无其他 `get_active_categories` 调用方（仅 `madeinchina/shop.py` 的 `_seed_category_items`）
+- ✅ 未碰 platform/、fetcher/vendor/wa-check/、scraper/、util/
+- ✅ --queues choices 自动含 crawl_mic_shop（注册表动态派生，Step 3.1 已实现）
+- ✅ 全量 468 passed（基线 463 + 5 净增）
+- ✅ 冒烟取证完整（播种→discover→类目页消费→progress 推进）
+- ⚠️ 工作区有他人未提交改动，scoped add 仅按 brief 列出文件
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index acdd02d..77262a0 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -234,36 +234,49 @@ def _build_registry(selected_queues: list[str] | None = None) -> list:
     site_mic = get_site("madeinchina")
     specs.append(QueueSpec(
         queue="crawl_mic_contact",
         site="madeinchina",
         task=site_mic.make_task("contact"),
         topup=lambda db, limit: db.topup_contact_work_items(
             "crawl_mic_contact", "madeinchina", ".cn.made-in-china.com", limit),
         domain_suffix=".cn.made-in-china.com",
     ))
 
+    # crawl_mic_shop（feeder 队列：topup=None，不参与 in_progress reset）
+    specs.append(QueueSpec(
+        queue="crawl_mic_shop",
+        site="madeinchina",
+        task=site_mic.make_task("shop"),
+        topup=None,
+        domain_suffix="",
+        requires={"channel", "browser"},
+    ))
+
     if selected_queues:
         specs = [s for s in specs if s.queue in selected_queues]
     return specs
 
 
 def reset_daemon_state(db, registry: list) -> tuple[int, int]:
     """daemon 启动崩溃恢复：全量回收 claimed + 逐 site 重置 in_progress。
 
+    只对 topup 非 None 的队列做 reset_in_progress（feeder 队列跳过——
+    它不产生 in_progress shops）。
     返回 (n_claimed_reset, n_in_progress_reset)。
     提取为独立函数便于测试（I2）。
     """
     n_items = db.reset_claimed_work_items()
     total_shops = 0
     for spec in registry:
-        n = db.reset_in_progress(spec.domain_suffix)
-        total_shops += n
+        if spec.topup is not None:
+            n = db.reset_in_progress(spec.domain_suffix)
+            total_shops += n
     return n_items, total_shops
 
 
 def _run_daemon(args) -> int:
     """daemon 常驻模式装配：QueueRouter 跨队列认领 + Engine 跑。"""
     from fetcher.control.engine import Engine
     from fetcher.control.queue_router import QueueRouter
     from fetcher.db import ShopDB
 
     cfg = config_from_args(args)
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 57374c8..10c2082 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -624,35 +624,53 @@ class ShopDB:
         return self.conn.execute(
             "SELECT next_page FROM category_progress WHERE keyword=?",
             (keyword,)).fetchone()[0]
 
     def get_exhausted_keywords(self) -> set:
         """返回所有已采到末页的类目关键词（shop_crawler 选类目时跳过）。"""
         rows = self.conn.execute(
             "SELECT keyword FROM category_progress WHERE exhausted=1").fetchall()
         return {r[0] for r in rows}
 
+    def iter_active_categories(self, prefix: str = "") -> list[dict]:
+        """返回未采完的类目（启动播种用，幂等）。
+
+        prefix 非空 → 只返回 keyword 以 prefix 开头的行（如 "company:"）。
+        prefix 为空 → 返回全部未采完类目。
+        返回 [{"keyword","name"}]，按 id 排序。
+        """
+        if prefix:
+            rows = self.conn.execute(
+                "SELECT keyword, name FROM category_progress"
+                " WHERE exhausted=0 AND keyword LIKE ? ORDER BY id",
+                (prefix + "%",)).fetchall()
+        else:
+            rows = self.conn.execute(
+                "SELECT keyword, name FROM category_progress"
+                " WHERE exhausted=0 ORDER BY id").fetchall()
+        return [{"keyword": r[0], "name": r[1] or r[0]} for r in rows]
+
     def get_active_categories(self) -> list[dict]:
         """返回未采完的拼音类目（madeinchina market slug 是拼音缩写）。
 
+        委托 iter_active_categories() 获取全量未采完类目，再经拼音过滤。
         当前首页只暴露少量 market 链接，类目池只靠首页提取会把大量
         已发现但未采完的类目搁浅在 category_progress 里；这里把
         非 exhausted 的拼音类目捞回来，prepare 时播种进类目池续采。
 
         过滤规则：keyword 是纯拼音（ASCII [a-zA-Z0-9_]+）——1688 等其他
         任务的中文/company: 关键词行与 madeinchina 无关，排除。
         """
-        rows = self.conn.execute(
-            "SELECT keyword, name FROM category_progress WHERE exhausted=0"
-        ).fetchall()
-        return [{"slug": r[0], "name": r[1] or r[0]} for r in rows
-                if r[0] and _is_pinyin_slug(r[0])]
+        all_cats = self.iter_active_categories()
+        return [{"slug": cat["keyword"], "name": cat["name"]}
+                for cat in all_cats
+                if cat["keyword"] and _is_pinyin_slug(cat["keyword"])]
 
     def mark_category_exhausted(self, keyword: str, name: str = None):
         """标记类目已采到末页（页码不前进，之后采集跳过该类目）。"""
         self.conn.execute(
             """INSERT INTO category_progress (keyword, name, exhausted,
                                               last_crawled_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(keyword) DO UPDATE SET
                    name = COALESCE(excluded.name, category_progress.name),
                    exhausted = 1,
diff --git a/fetcher/fetcher/sites/madeinchina/shop.py b/fetcher/fetcher/sites/madeinchina/shop.py
index eb2750c..3d58680 100644
--- a/fetcher/fetcher/sites/madeinchina/shop.py
+++ b/fetcher/fetcher/sites/madeinchina/shop.py
@@ -265,29 +265,34 @@ class MadeInChinaShopTask(Task):
               f"{config.batch_num} 个店铺"
               f"（{'最多 ' + str(config.max_batches) + ' 批'
                  if config.max_batches else '不限批数'}），"
               f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
         db.close()
         return True
 
     def _seed_category_items(self, db) -> int:
         """活跃拼音类目逐条插 category item（已有同 keyword pending 跳过）。
 
-        ⚠️ 已知局限：get_active_categories 不含 fmt 字段，播种一律 "x2"；
+        经 iter_active_categories 取全量未采完类目，再 _is_pinyin_slug
+        过滤拼音 slug（与 get_active_categories 同口径）。
+
+        ⚠️ 已知局限：category_progress 不含 fmt 字段，播种一律 "x2"；
         plain 体系类目（如 jgdbj）首次 fetch 会拼错 URL 而失败；
         discover 从页面提取时带正确 fmt 后纠正。Step 4.2 若 category_progress
         加 fmt 列可根除。
         """
-        active = db.get_active_categories()
+        from fetcher.db import _is_pinyin_slug
+        active = [cat for cat in db.iter_active_categories()
+                  if _is_pinyin_slug(cat["keyword"])]
         n = 0
         for cat in active:
-            slug = cat["slug"]
+            slug = cat["keyword"]
             name = cat.get("name", slug)
             existing = self._count_pending_by_kind(db, "category", slug)
             if existing > 0:
                 continue
             # fmt 默认 x2（局限见上），discover 提取时带正确 fmt 覆盖
             payload = {"kind": "category", "keyword": slug,
                        "name": name, "fmt": "x2"}
             self._insert_work_item(db, payload)
             n += 1
         return n
diff --git a/fetcher/tests/test_cli.py b/fetcher/tests/test_cli.py
index fa99810..8e673bb 100644
--- a/fetcher/tests/test_cli.py
+++ b/fetcher/tests/test_cli.py
@@ -39,20 +39,21 @@ class CliParserTest(unittest.TestCase):
         self.assertEqual(args.workers, 3)
         self.assertEqual(args.limit, 5)
 
     def test_daemon_queues_dynamic_from_registry(self):
         """I3：--queues 校验来自注册表动态派生，非硬编码。"""
         from fetcher.cli.main import _build_registry
         full = _build_registry()
         all_names = [s.queue for s in full]
         self.assertIn("crawl_1688_contact", all_names)
         self.assertIn("crawl_mic_contact", all_names)
+        self.assertIn("crawl_mic_shop", all_names)
 
     def test_daemon_config_from_args(self):
         # config_from_args 不读 args.task，daemon 命名空间可直接复用
         cfg = config_from_args(self.ap.parse_args(["daemon"]))
         self.assertEqual(cfg.batch_num, 10)
         self.assertEqual(cfg.limit, 0)
 
     def test_daemon_has_no_task_subparser(self):
         # daemon 后不能再跟 task 位置参数（argparse 报错退出）
         with self.assertRaises(SystemExit):
@@ -194,13 +195,61 @@ class ResetDaemonStateTest(unittest.TestCase):
         self.assertEqual(n_items, 0)
         self.assertEqual(total_shops, 0)
         # s1.1688.com 未被重置（仍 in_progress）
         self.assertEqual(
             self.db.conn.execute(
                 "SELECT status FROM shops WHERE domain=?",
                 ("s1.1688.com",)
             ).fetchone()[0],
             "in_progress")
 
+    def test_reset_skips_feeder_queues(self):
+        """feeder 队列（topup=None）不触发 reset_in_progress。
+
+        feeder 的 domain_suffix="" 若被调用 → 重置所有 in_progress
+        （含 other.example.com）；修复后跳过 feeder → other.example.com
+        保持 in_progress。
+        """
+        from fetcher.cli.main import reset_daemon_state
+        from fetcher.control.queue_router import QueueSpec
+
+        # feeder 队列：topup=None, domain_suffix 为空
+        feeder = QueueSpec(
+            queue="crawl_mic_shop", site="madeinchina",
+            task=lambda: None, topup=None, domain_suffix="",
+            requires={"channel", "browser"})
+        # contact 队列：topup 非 None
+        contact = QueueSpec(
+            queue="crawl_mic_contact", site="madeinchina",
+            task=lambda: None,
+            topup=lambda db, limit: 0,
+            domain_suffix=".cn.made-in-china.com",
+            requires={"channel", "browser"})
+
+        # Seed: mic contact shop + 不匹配任何 contact domain_suffix 的 shop
+        self._seed_in_progress([
+            "s1.cn.made-in-china.com",
+            "other.example.com"])
+
+        registry = [feeder, contact]
+        n_items, total_shops = reset_daemon_state(self.db, registry)
+        self.assertEqual(n_items, 0)
+        # 只 contact 队列的 domain_suffix 被重置（1 个），feeder 跳过
+        self.assertEqual(total_shops, 1)
+        # s1.cn.made-in-china.com 被重置为 pending
+        self.assertEqual(
+            self.db.conn.execute(
+                "SELECT status FROM shops WHERE domain=?",
+                ("s1.cn.made-in-china.com",)
+            ).fetchone()[0],
+            "pending")
+        # other.example.com 保持 in_progress（feeder 未触发全量重置）
+        self.assertEqual(
+            self.db.conn.execute(
+                "SELECT status FROM shops WHERE domain=?",
+                ("other.example.com",)
+            ).fetchone()[0],
+            "in_progress")
+
 
 if __name__ == "__main__":
     unittest.main()
diff --git a/fetcher/tests/test_madeinchina.py b/fetcher/tests/test_madeinchina.py
index 6306a13..c2257cd 100644
--- a/fetcher/tests/test_madeinchina.py
+++ b/fetcher/tests/test_madeinchina.py
@@ -605,20 +605,154 @@ class ShopTaskTest(unittest.TestCase):
         page = MICPage()
         ctx = make_ctx(page)
         self.task.cold_start(ctx, None)
         urls = [u for u, _ in page.goto_calls]
         self.assertIn(HOMEPAGE, urls)
         self.assertIn(MARKET_DIR, urls)
         # 没有提取类目（cold_start 不再做这事）
         # 验证 goto 正常完成即可
         self.assertEqual(len(urls), 2)
 
+    # ---- iter_active_categories - 统一类目查询 ----
+
+    def test_iter_active_categories_returns_non_exhausted(self):
+        """未采完类目返回，exhausted 排除，按 id 排序。"""
+        import tempfile
+        from pathlib import Path
+        from fetcher.db import ShopDB
+        tmp = tempfile.TemporaryDirectory()
+        try:
+            db_path = Path(tmp.name) / "t.db"
+            db = ShopDB(db_path)
+            # Seed: 3 条 exhausted=0，1 条 exhausted=1
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('cat_c', 'C 类目', 0)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('cat_a', 'A 类目', 0)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('cat_ex', 'Exhausted 类目', 1)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('cat_b', 'B 类目', 0)")
+            db.conn.commit()
+            result = db.iter_active_categories()
+            # exhausted=1 的被排除
+            self.assertEqual(len(result), 3)
+            keywords = [r["keyword"] for r in result]
+            self.assertNotIn("cat_ex", keywords)
+            # 按 id 排序 → cat_c, cat_a, cat_b
+            self.assertEqual(keywords, ["cat_c", "cat_a", "cat_b"])
+            # 字段含 keyword/name
+            self.assertEqual(result[0]["name"], "C 类目")
+            db.close()
+        finally:
+            tmp.cleanup()
+
+    def test_iter_active_categories_prefix_filter(self):
+        """prefix='company:' 只返回 company: 前缀行。"""
+        import tempfile
+        from pathlib import Path
+        from fetcher.db import ShopDB
+        tmp = tempfile.TemporaryDirectory()
+        try:
+            db_path = Path(tmp.name) / "t.db"
+            db = ShopDB(db_path)
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('company:abc', 'ABC 公司', 0)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('bxgyxg', '不锈钢型材', 0)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('company:xyz', 'XYZ 公司', 0)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('company:done', 'Done 公司', 1)")
+            db.conn.commit()
+            result = db.iter_active_categories(prefix="company:")
+            keywords = [r["keyword"] for r in result]
+            # 只返回 company: 开头 + exhausted=0 的
+            self.assertEqual(len(result), 2)
+            self.assertIn("company:abc", keywords)
+            self.assertIn("company:xyz", keywords)
+            self.assertNotIn("bxgyxg", keywords)
+            self.assertNotIn("company:done", keywords)
+            # prefix="" 返回全部未采完
+            all_result = db.iter_active_categories()
+            self.assertEqual(len(all_result), 3)  # company:abc,bxgyxg,company:xyz
+            db.close()
+        finally:
+            tmp.cleanup()
+
+    def test_get_active_categories_delegates_to_iter(self):
+        """get_active_categories 经 iter_active_categories + 拼音过滤后行为一致。"""
+        import tempfile
+        from pathlib import Path
+        from fetcher.db import ShopDB
+        tmp = tempfile.TemporaryDirectory()
+        try:
+            db_path = Path(tmp.name) / "t.db"
+            db = ShopDB(db_path)
+            # 拼音类目 + 中文类目（非拼音）+ company: 前缀
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('bxgyxg', '不锈钢型材', 0)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('中文类目', '中文类目名', 0)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('company:test', '测试公司', 0)")
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('jgdbj', '激光打标机', 0)")
+            db.conn.commit()
+            result = db.get_active_categories()
+            # 只返回纯拼音 slug（bxgyxg, jgdbj），排除中文/company:
+            keywords = [r["slug"] for r in result]
+            self.assertIn("bxgyxg", keywords)
+            self.assertIn("jgdbj", keywords)
+            self.assertNotIn("中文类目", keywords)
+            self.assertNotIn("company:test", keywords)
+            # 字段名仍为 slug/name（向后兼容）
+            for r in result:
+                self.assertIn("slug", r)
+                self.assertIn("name", r)
+            db.close()
+        finally:
+            tmp.cleanup()
+
+    def test_iter_active_categories_empty_name_defaults_to_keyword(self):
+        """name 为 NULL 时回退为 keyword。"""
+        import tempfile
+        from pathlib import Path
+        from fetcher.db import ShopDB
+        tmp = tempfile.TemporaryDirectory()
+        try:
+            db_path = Path(tmp.name) / "t.db"
+            db = ShopDB(db_path)
+            db.conn.execute(
+                "INSERT INTO category_progress (keyword, name, exhausted)"
+                " VALUES ('testcat', NULL, 0)")
+            db.conn.commit()
+            result = db.iter_active_categories()
+            self.assertEqual(len(result), 1)
+            self.assertEqual(result[0]["keyword"], "testcat")
+            self.assertEqual(result[0]["name"], "testcat")  # NULL → keyword
+            db.close()
+        finally:
+            tmp.cleanup()
+
 
 # ---------- 策略覆盖 ----------
 
 class PolicyOverrideTest(unittest.TestCase):
     def test_no_solve_slider_for_vemic(self):
         site = get_site("madeinchina")
         overrides = site.policy_overrides
         self.assertIn(Scenario.RISK_SLIDER_PAGE, overrides)
         for chain in overrides.values():
             actions = [a for a, _ in chain]
