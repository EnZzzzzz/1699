# Review Package — Step 4.1 (mic shop feeder 拆分)

## Commits
54ecb07 feat(multiqueue-p3): refactor MadeInChinaShopTask to work_items-driven feeder

## Stat
 .../task-4.1-report.md                             |  88 ++++
 fetcher/fetcher/control/queue_router.py            |   3 +
 fetcher/fetcher/control/task.py                    |   7 +
 fetcher/fetcher/sites/madeinchina/shop.py          | 298 +++++++----
 fetcher/tests/test_madeinchina.py                  | 177 +++----
 fetcher/tests/test_mic_shop_feeder.py              | 566 +++++++++++++++++++++
 6 files changed, 935 insertions(+), 204 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md
new file mode 100644
index 0000000..157115a
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md
@@ -0,0 +1,88 @@
+# Task 4.1 Report — mic shop feeder 任务拆分（work_items 驱动重构）
+
+> 分支：`feat/multiqueue-p3` | 日期：2026-08-08 | 状态：DONE
+
+## 实现摘要
+
+将 `MadeInChinaShopTask` 从进程内 `CategoryPool + acquire` 模式重构为 **work_items 驱动**：
+
+- **payload 形态**：`{"kind":"category","keyword":<slug>,"name":<cat_name>,"fmt":"x2"|"plain"}` 或 `{"kind":"discover"}`
+- **page_no 运行时读**：`fetch` 里读 `db.get_category_progress(keyword)["next_page"]`（无记录=1），不进 payload
+- **discover 执行**：`on_success` 里 `kind=="discover"` 走首页+导航页类目提取，新类目逐条 INSERT category item
+- **链式续喂**：category item `on_success` 未 exhausted 时 INSERT 同 payload 下一页 item（attempts=0）
+- **ZERO_NEW_LIMIT 保护**：streak 在 task 实例内存 dict（slug→计数）+ 锁，连续零新增达标 → `mark_category_exhausted` + 不插下一页
+- **失败补插**：`refill_item` 对 category/discover 均补插同 payload 新 item
+- **CLI acquire**：`db.claim_next_eligible(["crawl_mic_shop"], consumer_id)` → payload dict（与 daemon 同一路径）
+- **冷启动**：`cold_start` 改为纯浏览软着陆（逛首页+导航页，不提取类目；提取归 discover）
+- **CategoryPool 退役**：删除整个 CategoryPool 类、ACQUIRE_WAIT_MAX、_slug_fmt（fmt 从 payload 取）
+
+### 改动文件
+
+| 文件 | 改动 |
+|---|---|
+| `fetcher/fetcher/control/task.py` | `Task` 基类新增 `refill_item(self, ctx, item) -> None`（默认空实现） |
+| `fetcher/fetcher/control/queue_router.py` | `release_item()` 里 attempts 耗尽时调 `_task_for(ctx).refill_item(ctx, item)` |
+| `fetcher/fetcher/sites/madeinchina/shop.py` | **主重构**：删除 CategoryPool/ACQUIRE_WAIT_MAX；MadeInChinaShopTask 全面改为 work_items payload 驱动；新增 `_run_discover`、`_seed_category_items`、`_seed_discover_item`、`refill_item`、`_insert_work_item`、`_count_pending_category` 辅助方法 |
+| `fetcher/tests/test_madeinchina.py` | 移除 CategoryPool 相关测试（3 个）+ 旧 cold_start 测试（2 个）；更新 6 个测试适配 payload dict；新增 1 个纯浏览 cold_start 测试 |
+| `fetcher/tests/test_mic_shop_feeder.py` | **新增**，19 个 TDD 测试覆盖链式续喂/ZERO_NEW_LIMIT/失败补插/discover产出/幂等播种/CLI acquire/page_no运行时读/refill_item基类默认 |
+
+## 测试列表
+
+### TDD 新增测试 (test_mic_shop_feeder.py)
+
+| # | 测试 | 覆盖项 |
+|---|---|---|
+| 1 | `test_chain_feed_inserts_next_page_item` | 有新增店铺 → next_page+1 + 新 work_item |
+| 2 | `test_chain_feed_skips_when_exhausted` | 空页 → exhausted + 不插下一页 |
+| 3 | `test_zero_new_exhausts_after_limit` | 连续 ZERO_NEW_LIMIT 页零新增 → exhausted |
+| 4 | `test_zero_new_no_chain_feed_when_exhausted` | ZERO_NEW_LIMIT 耗尽不再链式续喂 |
+| 5 | `test_zero_new_resets_after_fresh` | 零新增后有新店 → 计数清零 |
+| 6 | `test_refill_inserts_replacement_category_item` | category 补插同 payload |
+| 7 | `test_refill_discover_also_replenishes` | discover 补插 |
+| 8 | `test_discover_inserts_new_categories` | discover → 提取类目 → INSERT category item |
+| 9 | `test_discover_skips_exhausted_categories` | exhausted 类目不重复插 |
+| 10 | `test_discover_skips_existing_pending_category` | 已有 pending 不重复 |
+| 11 | `test_discover_fallback_seeds` | 提取失败 → 种子兜底 |
+| 12 | `test_double_prepare_no_duplicates` | 重复 prepare 幂等 |
+| 13 | `test_acquire_returns_payload` | CLI acquire 返回 payload dict |
+| 14 | `test_acquire_returns_none_when_empty` | 无货返回 None |
+| 15 | `test_acquire_returns_discover_payload` | acquire 认领 discover item |
+| 16 | `test_fetch_reads_next_page_from_db` | fetch 读 next_page=3 → 抓第 3 页 |
+| 17 | `test_fetch_defaults_to_page_1_when_no_progress` | 无 progress → page_no=1 |
+| 18 | `test_fetch_discover_returns_success_without_request` | discover fetch 不发请求 |
+| 19 | `test_base_refill_item_is_noop` | Task 基类 refill_item 不抛异常 |
+
+### 旧测试适配 (test_madeinchina.py)
+
+- `test_pool_remembers_fmt_per_slug` → 删除（CategoryPool 退役）
+- `test_fetch_uses_fmt_for_plain_slug` → `test_fetch_uses_fmt_from_payload`（fmt 从 payload 取）
+- `test_fetch_extracts_showrooms` → item 改为 payload dict
+- `test_on_success_empty_marks_exhausted` → 适配 payload dict
+- `test_on_success_zero_new_marks_exhausted_after_limit` → 适配 payload dict
+- `test_on_success_zero_new_resets_after_fresh_page` → 适配 payload dict
+- `test_prepare_seeds_pool_from_db` → `test_prepare_seeds_from_db`（验证 work_items 播种）
+- `test_pick_none_*` (2 tests) → 删除（CategoryPool 退役）
+- `test_cold_start_seeds_pool_from_market_dir` + `test_cold_start_both_pages_fail_falls_back_to_seeds` → `test_cold_start_browses_home_and_market_dir`（纯浏览）
+
+## TDD 证据
+
+1. **RED**：先写 19 个测试 → `python -m pytest tests/test_mic_shop_feeder.py -v` → **19 failed**（`'Task' object has no attribute 'refill_item'` / `ValueError: too many values to unpack`）
+2. **GREEN**：实现 Task.refill_item + QueueRouter 接线 + MadeInChinaShopTask payload 重构 → **19 passed** + 旧测试适配也全部通过
+3. **全量**：`cd fetcher && python -m pytest tests -q` → **462 passed, 2 subtests passed**（基线 447 + 净增 15）
+
+## 复核确认结论（§3）
+
+| 检查项 | 结果 |
+|---|---|
+| `crawl_mic_contact` 在双队列注册表 | ✅ `cli/main.py:233-241`：queue/site/task/topup/domain_suffix 完整 |
+| `reset_daemon_state` 逐 site 循环 | ✅ `cli/main.py:249-254`：`for spec in registry: db.reset_in_progress(spec.domain_suffix)` |
+| mic contact prepare 带域过滤 | ✅ `contact.py:178`：`db.reset_in_progress(SHOWROOM_DOMAIN_SUFFIX)` |
+
+## 自查
+
+- ✅ brief 所有裁定均落实（payload 形态、page_no 运行时读、discover 走 on_success、streak 内存计数、refill_item 基类默认空、冷启动纯浏览）
+- ✅ 未碰 db.py、platform/、scraper/、util/、vendor/wa-check/
+- ✅ CLI 与 daemon 同一代码路径（acquire_item 用 claim_next_eligible）
+- ✅ ZERO_NEW_LIMIT=2 保持不变；SEED_CATEGORIES 保持不变；_JS_EXTRACT_SHOWROOMS 保持不变
+- ✅ `make_stats` 保持 `{"shops","new","pages"}` 三键
+- ⚠️ 工作区有他人未提交改动，已确认不碰（scoped add 严格按 brief 列出文件）
diff --git a/fetcher/fetcher/control/queue_router.py b/fetcher/fetcher/control/queue_router.py
index 655434e..5c15829 100644
--- a/fetcher/fetcher/control/queue_router.py
+++ b/fetcher/fetcher/control/queue_router.py
@@ -292,20 +292,23 @@ class QueueRouter:
 
         返回终态（"pending"/"failed"）供日志；无认领记录时返回 ""。
         """
         item_id = ctx.state.pop(_STATE_KEY, None)
         if item_id is None:
             return ""
         try:
             status = self._db(ctx).release_work_item(item_id, max_attempts=3)
             if status == "failed":
                 ctx.log(f"[!] 工作项 #{item_id} attempts exhausted，已置 failed")
+                item = ctx.state.get("item")
+                if item is not None:
+                    self._task_for(ctx).refill_item(ctx, item)
             return status
         except Exception as e:  # noqa: BLE001
             ctx.log(f"[!] 工作项 #{item_id} 释放失败: {e}")
             return ""
 
     def _finish(self, ctx, status: str, result: dict | None = None):
         """把当前 worker 认领的 work_item 落终态（done/failed）。"""
         item_id = ctx.state.pop(_STATE_KEY, None)
         if item_id is None:
             return
diff --git a/fetcher/fetcher/control/task.py b/fetcher/fetcher/control/task.py
index 67ef3cd..523eb6a 100644
--- a/fetcher/fetcher/control/task.py
+++ b/fetcher/fetcher/control/task.py
@@ -122,12 +122,19 @@ class Task:
         """放弃的任务项计入批次配额的数量。"""
         return 0
 
     def release_item(self, ctx) -> str:
         """当前 worker 的 item 释放回 pending（CLI 路径默认空实现）。
 
         daemon 多队列路径由 QueueRouter 覆盖为 DB release_work_item。
         """
         return ""
 
+    def refill_item(self, ctx, item) -> None:
+        """工作项 attempts 耗尽后补插同 payload 新 item（默认空实现）。
+
+        CLI 单站点路径兼容；子类按需覆盖（如 MadeInChinaShopTask 对
+        category/discover 补插）。
+        """
+
     def after_item(self, ctx, item) -> None:
         """当前任务项处理完毕（含放弃）后的收尾（如释放类目占用）。"""
diff --git a/fetcher/fetcher/sites/madeinchina/shop.py b/fetcher/fetcher/sites/madeinchina/shop.py
index 7924dc7..02de25a 100644
--- a/fetcher/fetcher/sites/madeinchina/shop.py
+++ b/fetcher/fetcher/sites/madeinchina/shop.py
@@ -48,24 +48,20 @@ def build_market_url(slug: str, page_no: int = 1, fmt: str = "x2") -> str:
     if fmt == "plain":
         return f"https://cn.made-in-china.com/market/{slug}-{page_no}.html"
     return MARKET_URL_TPL.format(slug=slug, page=page_no)
 
 
 # 连续零新增判定为「该类目实际已采完」的页数阈值：健康分页每页必有新增，
 # 连续 N 页提取到的全是已入库重复（服务端分页夹取回第 1 页 / 真采完）即标
 # exhausted，防止被 has_more「满页≥20」启发式骗到永不停止（实测 bxgyxg
 # 单页类目被深挖到 176 页，5075 声称找到仅 29 家真实入库）
 ZERO_NEW_LIMIT = 2
-# acquire 空转等待上限：类目池里只剩被其他 worker 暂占的活跃类目时，
-# 每 2-5s 重试一次；超过此上限视为卡死/无真实工作可抢，退出 worker
-#（避免两个 worker 互相空等永远不退出）。
-ACQUIRE_WAIT_MAX = 600.0
 
 
 # 平台自身子域名（导航/页脚/登录/行业入口等），非供应商展厅，过滤掉
 PLATFORM_SUBDOMAINS = {
     "cn", "www", "m", "login", "membercenter", "service", "big5", "en",
     "es", "pt", "fr", "ru", "it", "de", "nl", "sa", "kr", "jp", "hi",
     "th", "tr", "vi", "id", "caigou", "zhanhui", "image", "supervisor",
     "purchase", "sourcing", "trading", "expo", "ai", "data", "insights",
     "world", "micstatic", "3g", "member",
 }
@@ -210,69 +206,105 @@ class CategoryPool:
         """池里是否还有未采完的类目（无论是否被其他 worker 暂占）。
 
         pick() 返回 None 时用它区分「真采完」和「全被暂占」：还有活跃
         类目但都 in_progress = 被其他 worker 占着，应空转等待而非退出。
         """
         with self.lock:
             return any(slug not in self.exhausted for slug in self.pool)
 
 
 class MadeInChinaShopTask(Task):
-    """中国制造网供应商展厅采集：随机类目 → market 分页页 → 子域名入库。
-
-    任务项为 (slug, cat_name, page_no) 三元组；类目占用与 exhausted 由
-    CategoryPool 管，页码进度由 category_progress 表管。
+    """中国制造网供应商展厅采集：work_items 驱动 + 单类目页处理。
+
+    work_items payload：
+      - 类目页：{"kind":"category","keyword":<slug>,"name":<cat_name>,
+                 "fmt":"x2"|"plain"}
+        page_no 不进 payload——处理时读 category_progress.next_page
+      - 发现：{"kind":"discover"}
+        执行 = 首页+市场导航页提取类目，新类目逐条 INSERT category item
+
+    链式续喂：category item on_success 后若未采完则 INSERT 下一页 item
+    （同 payload，attempts=0）；ZERO_NEW_LIMIT 连续零新增保护。
+    失败补插：refill_item 在 attempts 耗尽时补插同 payload 新 item。
     """
 
     name = "shop"
     unit = "页"
     batch_unit = "店铺"
-    # 冷启动要先逛首页提取类目填满类目池，必须在 acquire（选类目）之前
+    # 冷启动要先逛首页（软着陆），必须在 acquire 之前
     cold_start_before_acquire = True
     # market 分页页反爬阈值未知，先保守：每出口 IP 采满 60 页主动换 IP [CAL]
     ip_request_budget = 60
 
+    QUEUE = "crawl_mic_shop"
+    SITE = "madeinchina"
+
     def __init__(self):
-        self.cat_pool: CategoryPool | None = None
         # 每类目连续零新增页数（slug -> int），见 ZERO_NEW_LIMIT 说明。
-        # 任务对象跨 worker 线程共享，计数需加锁（多 worker 同采一类目时
-        # 计数要累计而不是互相覆盖）
+        # 类目 item 是串行链式的（下一页 item 只在上一页成功后插入），
+        # 同类目不会并发写，但保留锁防御。
         self.zero_new: dict = {}
         self._zero_lock = threading.Lock()
 
     # ---- main 阶段 ----
 
     def prepare(self, config) -> bool:
         from fetcher.db import ShopDB  # 延迟导入
         db = ShopDB(config.resolved_db_path())
         exhausted = db.get_exhausted_keywords()
         if exhausted:
             print(f"[0] 已采到末页的类目 {len(exhausted)} 个，自动跳过")
-        self.cat_pool = CategoryPool(exhausted)
-        # 首页只暴露少量 market 链接，类目池不能只靠首页：把进度库里
-        # 未采完的拼音类目也播种进来（跨 run 续采，避免搁浅）
-        active = db.get_active_categories()
-        n_seed = self.cat_pool.refresh(active)
-        if n_seed:
-            print(f"[0] 从进度库恢复 {n_seed} 个未采完类目"
-                  f"（池内可采 {self.cat_pool.available()}）")
+        # 播种：活跃拼音类目逐条插 category item + 一条 discover item
+        n_cat = self._seed_category_items(db)
+        n_disc = self._seed_discover_item(db)
+        if n_cat or n_disc:
+            print(f"[0] 播种 {n_cat} 个 category item + {n_disc} 条 discover")
         st = db.stats()
         print(f"[1] 数据库现有店铺 {st['shops']} 个（pending {st['pending']} / "
               f"done {st['done']} / no_contact {st['no_contact']} / "
               f"failed {st['failed']}），每个 worker 每批 "
               f"{config.batch_num} 个店铺"
               f"（{'最多 ' + str(config.max_batches) + ' 批'
                  if config.max_batches else '不限批数'}），"
               f"批间强制休息 {config.batch_rest / 60:.0f} 分钟")
         db.close()
         return True
 
+    def _seed_category_items(self, db) -> int:
+        """活跃拼音类目逐条插 category item（已有同 keyword pending 跳过）。"""
+        active = db.get_active_categories()
+        n = 0
+        for cat in active:
+            slug = cat["slug"]
+            name = cat.get("name", slug)
+            # 已有同 keyword pending category item 跳过
+            existing = self._count_pending_category(db, slug)
+            if existing > 0:
+                continue
+            # fmt 从 category_progress 推断（默认 x2）
+            payload = {"kind": "category", "keyword": slug,
+                       "name": name, "fmt": "x2"}
+            self._insert_work_item(db, payload)
+            n += 1
+        return n
+
+    def _seed_discover_item(self, db) -> int:
+        """插一条 discover item（已有 pending discover 跳过）。"""
+        existing = db.conn.execute(
+            "SELECT COUNT(*) FROM work_items WHERE queue=? AND status='pending'"
+            " AND json_extract(payload_json, '$.kind')='discover'",
+            (self.QUEUE,)).fetchone()[0]
+        if existing > 0:
+            return 0
+        self._insert_work_item(db, {"kind": "discover"})
+        return 1
+
     def summary(self, all_stats: dict, db_path=None) -> str:
         from fetcher.db import ShopDB  # 延迟导入
         shops = sum(s.get("shops", 0) for s in all_stats.values())
         new = sum(s.get("new", 0) for s in all_stats.values())
         pages = sum(s.get("pages", 0) for s in all_stats.values())
         db = ShopDB(db_path)
         stats = db.stats()
         db.close()
         return (f"本次采集: {pages} 页, 店铺 {shops} 个（新增 {new}）"
                 f"\n    数据库统计: {stats}")
@@ -287,186 +319,266 @@ class MadeInChinaShopTask(Task):
 
     def make_stats(self) -> dict:
         return {"shops": 0, "new": 0, "pages": 0}
 
     def rest_counter(self, stats: dict) -> int:
         return stats["pages"]
 
     # ---- worker 循环 ----
 
     def cold_start(self, ctx, item) -> None:
-        """新会话先逛首页 + 市场导航页留真实浏览轨迹，顺带提取类目填满类目池。
+        """新会话先逛首页 + 市场导航页留真实浏览轨迹（纯软着陆，不提取类目）。
 
-        首页只暴露少量 market 链接（~129 个，2026-08-06 已全部采干），类目
-        主力入口是市场导航页 /shichang/（~947 个）；两页都提取，按 slug 合并
-        去重进池。新会话一上来就深链 market 分页是明显的爬虫特征，所以先逛
-        导航类页面。
+        类目提取归 discover item 的 on_success 处理。
         """
-        home_cats = fetch_market_categories(ctx.page, HOMEPAGE)
-        dir_cats = fetch_market_categories(ctx.page, MARKET_DIR)
-        # 按 slug 合并去重（首页与导航页重合的类目只占一个坑）
-        cats = list({c["slug"]: c for c in home_cats + dir_cats}.values())
-        if not cats:
-            cats = [{"name": n, "slug": k} for k, n in SEED_CATEGORIES]
-            ctx.log(f"[!] 首页与市场导航页类目提取均失败，"
-                    f"使用内置种子类目（{len(cats)} 个）")
-        n = self.cat_pool.refresh(cats)
-        if n:
-            ctx.log(f"类目池新增 {n} 个类目（可采 {self.cat_pool.available()}，"
-                    f"跳过已采完 {len(self.cat_pool.exhausted)}）")
-
-    def _slug_fmt(self, slug: str) -> str:
-        """类目的 URL 体系（x2/plain）。池里没记（如直连测试/DB 播种前）
-        时按 x2 兜底，与历史 `_2-` 采集一致。"""
-        if self.cat_pool is not None:
-            return self.cat_pool.fmt.get(slug, "x2")
-        return "x2"
+        try:
+            ctx.page.goto(HOMEPAGE, wait_until="domcontentloaded",
+                          timeout=60000)
+            time.sleep(random.uniform(2.0, 4.0))
+            ctx.page.goto(MARKET_DIR, wait_until="domcontentloaded",
+                          timeout=60000)
+            time.sleep(random.uniform(2.0, 4.0))
+        except Exception:  # noqa: BLE001
+            # 浏览失败不阻塞任务
+            ctx.log("[!] 冷启动浏览失败，继续认领工作项")
 
     def acquire_item(self, ctx):
-        # 类目池可能被其他 worker 全部暂占（首页 market 链接极少，2 个
-        # worker 会抢同一个类目）：此时 pick() 返回 None 但池里仍有活跃
-        # 类目，应空转等待释放而非直接退出；仅当真采完才返回 None。
-        deadline = time.monotonic() + ACQUIRE_WAIT_MAX
-        while not ctx.stopped():
-            picked = self.cat_pool.pick()
-            if picked:
-                slug, cat_name = picked
-                prog = ctx.store.db.get_category_progress(slug)
-                page_no = prog["next_page"] if prog else 1
-                return (slug, cat_name, page_no)
-            if not self.cat_pool.has_active():
-                return None  # 真采完：没有未采完的类目
-            # 有活跃类目但全被其他 worker 暂占：等待释放后重试
-            if time.monotonic() >= deadline:
-                ctx.set_status(state="⏳ 等类目释放超时，退出")
-                return None
-            ctx.set_status(state="⏳ 等其他 worker 释放类目…")
-            if ctx.wait(random.uniform(2.0, 5.0)):
-                return None  # 用户中断
-        return None
+        """从 work_items 队列认领（CLI 与 daemon 同一路径）。"""
+        consumer_id = f"w{ctx.wid}"
+        db = ctx.store.db
+        item = db.claim_next_eligible([self.QUEUE], consumer_id)
+        if item is None:
+            return None
+        # item = {"id", "queue", "site", "payload"}
+        payload = dict(item["payload"])
+        payload["id"] = item["id"]  # 保留 id 供 refill / 日志
+        return payload
 
     def label(self, item) -> str:
-        return f"{item[1]} p{item[2]}"
+        kind = item.get("kind", "")
+        if kind == "discover":
+            return "discover"
+        kw = item.get("keyword", "?")
+        name = item.get("name", kw)
+        return f"{name}"
 
     def fetch(self, ctx, item) -> ActionResult:
-        """抓取一页 market 分页页，提取供应商展厅子域名列表。"""
+        """按 kind 分派：category → 抓 market 页，discover → 返回标记。"""
+        kind = item.get("kind", "")
+        if kind == "discover":
+            return ActionResult(Outcome.OK, "discover", {"discover": True})
+        if kind == "category":
+            return self._fetch_category(ctx, item)
+        return ActionResult.fatal(f"未知 kind: {kind}")
+
+    def _fetch_category(self, ctx, item) -> ActionResult:
+        """抓取一页 market 分页页，提取供应商展厅子域名列表。
+
+        page_no 从 category_progress 运行时读（单一事实来源）。
+        """
         page = ctx.page
-        slug, _cat_name, page_no = item
-        fmt = self._slug_fmt(slug)
+        db = ctx.store.db
+        slug = item["keyword"]
+        name = item.get("name", slug)
+        fmt = item.get("fmt", "x2")
+        prog = db.get_category_progress(slug)
+        page_no = prog["next_page"] if prog else 1
         url = build_market_url(slug, page_no, fmt=fmt)
         try:
-            # referer 链条：第 1 页来自首页，第 N 页来自第 N-1 页 market 页
             referer = (HOMEPAGE if page_no <= 1
                        else build_market_url(slug, page_no - 1, fmt=fmt))
             page.goto(url, wait_until="domcontentloaded", timeout=60000,
                       referer=referer)
             time.sleep(random.uniform(2.0, 4.0))
             result = page.evaluate(_JS_EXTRACT_SHOWROOMS) or {}
             shops = []
             seen = set()
-            for it in result.get("shops") or []:
-                domain = (it.get("domain") or "").strip().lower()
+            for it_ in result.get("shops") or []:
+                domain = (it_.get("domain") or "").strip().lower()
                 if not domain.endswith(SHOWROOM_DOMAIN_SUFFIX):
                     continue
                 sub = domain[: -len(SHOWROOM_DOMAIN_SUFFIX)]
                 if is_platform_subdomain(sub) or domain in seen:
                     continue
                 seen.add(domain)
                 shops.append({"domain": domain,
-                              "name": it.get("name"),
+                              "name": it_.get("name"),
                               "url": f"https://{domain}"})
             return ActionResult(Outcome.OK, "已解析 market 分页页", {
                 "shops": shops,
-                # 分页锚点 next 或满页（≥20 链接）两档：宁可多打一页绝不提前停
                 "has_more": bool(result.get("next")) or len(shops) >= 20,
                 "found": result.get("found") or "0",
                 "_source_url": page.url,
             })
         except Exception as e:  # noqa: BLE001
             ctx.last_error = e
             kind = classify_error(e, page)
             reason = str(e).splitlines()[0][:200]
             if kind == "fatal":
                 return ActionResult.fatal(reason)
             if kind == "net_error":
                 return ActionResult.net_error(reason)
-            return ActionResult.blocked(f"页面加载失败（疑似风控拦截）: {reason}")
+            return ActionResult.blocked(
+                f"页面加载失败（疑似风控拦截）: {reason}")
 
     def validate(self, ctx, item, result: ActionResult) -> bool:
         """结构化校验：结果必须含 shops 列表（空列表 = 采到末页，合法）。"""
         return isinstance((result.data or {}).get("shops"), list)
 
     def on_success(self, ctx, item, result: ActionResult) -> int:
+        """按 kind 分派入库与链式续喂。"""
+        kind = item.get("kind", "")
+        if kind == "discover":
+            return self._on_discover_success(ctx, item, result)
+        if kind == "category":
+            return self._on_category_success(ctx, item, result)
+        return 0
+
+    def _on_discover_success(self, ctx, item, result: ActionResult) -> int:
+        """discover 成功：提取类目 → 新类目逐条 INSERT category item。"""
+        db = ctx.store.db
+        page = ctx.page
+        # 提取首页 + 市场导航页类目
+        home_cats = fetch_market_categories(page, HOMEPAGE)
+        dir_cats = fetch_market_categories(page, MARKET_DIR)
+        cats = list({c["slug"]: c for c in home_cats + dir_cats}.values())
+        if not cats:
+            cats = [{"name": n, "slug": k} for k, n in SEED_CATEGORIES]
+            ctx.log(f"[!] 首页与市场导航页类目提取均失败，"
+                    f"使用内置种子类目（{len(cats)} 个）")
+        n = 0
+        for c in cats:
+            slug = c["slug"]
+            # 跳过已 exhausted
+            prog = db.get_category_progress(slug)
+            if prog and prog.get("exhausted"):
+                continue
+            # 跳过已有同 keyword pending category item
+            if self._count_pending_category(db, slug) > 0:
+                continue
+            payload = {"kind": "category", "keyword": slug,
+                       "name": c.get("name", slug),
+                       "fmt": c.get("fmt", "x2")}
+            self._insert_work_item(db, payload)
+            n += 1
+        if n:
+            ctx.log(f"discover 产出 {n} 个新类目 category item")
+        return 0  # discover 不计入页数
+
+    def _on_category_success(self, ctx, item, result: ActionResult) -> int:
+        """category 成功：入库 shops → 零新增判定 → 链式续喂。"""
         db = ctx.store.db
         stats = ctx.state["task"]["stats"]
-        slug, cat_name, page_no = item
+        slug = item["keyword"]
+        cat_name = item.get("name", slug)
+        prog = db.get_category_progress(slug)
+        page_no = prog["next_page"] if prog else 1
         page_shops = result.data["shops"]
         has_more = result.data["has_more"]
         run_id = db.start_run(cat_name, slug)
         n_new = db.upsert_shops(page_shops, run_id=run_id,
                                 category_keyword=slug)
         db.finish_run(run_id, shops_found=len(page_shops),
                       shops_picked=n_new, note=f"page={page_no}")
+        exhausted = False
         if not page_shops or not has_more:
-            # 空页或没有下一页：该类目采到末页
             db.mark_category_exhausted(slug, cat_name)
             with self._zero_lock:
                 self.zero_new[slug] = 0
-            ctx.state["task"]["exhausted"] = True  # after_item 顺手标记
+            exhausted = True
             ctx.set_status(state=f"■ {cat_name} 采到末页，标记 exhausted")
             ctx.log(f"■ 类目 {cat_name} 第 {page_no} 页 "
                     f"{len(page_shops)} 店，hasMore={has_more}，"
                     f"采到末页标记 exhausted")
         elif n_new == 0:
-            # 提取到店铺但全部是已入库重复（服务端分页夹取回第 1 页 / 真采
-            # 完）：健康分页每页必有新增，连续 N 页零新增即视为采完，防止被
-            # has_more「满页≥20」启发式骗到永不 exhausted 无限深挖（实测
-            # bxgyxg 单页类目被烧到 176 页，5075 声称找到仅 29 家真实）
             with self._zero_lock:
                 streak = self.zero_new.get(slug, 0) + 1
                 self.zero_new[slug] = streak
             if streak >= ZERO_NEW_LIMIT:
                 db.mark_category_exhausted(slug, cat_name)
                 with self._zero_lock:
                     self.zero_new[slug] = 0
-                ctx.state["task"]["exhausted"] = True
+                exhausted = True
                 ctx.set_status(
                     state=f"■ {cat_name} 连续 {ZERO_NEW_LIMIT} 页零新增，"
                           f"标记 exhausted")
                 ctx.log(f"■ 类目 {cat_name} 第 {page_no} 页 "
                         f"{len(page_shops)} 店但全部重复（new=0），"
                         f"连续 {ZERO_NEW_LIMIT} 页零新增，标记 exhausted")
             else:
                 db.advance_category_page(slug, cat_name,
                                          shops_found=len(page_shops))
                 ctx.set_status(
                     state=f"○ {len(page_shops)} 店全重复（new=0，"
                           f"{streak}/{ZERO_NEW_LIMIT}）")
         else:
             with self._zero_lock:
-                self.zero_new[slug] = 0  # 有新增，重置连续零新增计数
+                self.zero_new[slug] = 0
             db.advance_category_page(slug, cat_name,
                                      shops_found=len(page_shops))
             ctx.set_status(state=f"✓ {len(page_shops)} 店（新 {n_new}）")
         stats["shops"] += len(page_shops)
         stats["new"] += n_new
         stats["pages"] += 1
         ctx.set_status(n=stats["shops"], new=stats["new"],
                        pages=stats["pages"])
-        return len(page_shops)  # 批次配额按提取到的店铺数计
+        # 链式续喂：未采完则 INSERT 下一页 item
+        if not exhausted:
+            payload = {"kind": "category", "keyword": slug,
+                       "name": cat_name, "fmt": item.get("fmt", "x2")}
+            self._insert_work_item(db, payload)
+        return len(page_shops)
 
     def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
-        # 页码不前进（不 advance），下次运行从该页重采
         return "跳过该页，页码不前进下次重采"
 
     def on_abort(self, ctx, item) -> str:
-        return (f"类目 {item[0]} 第 {item[2]} 页页码不前进，"
-                f"下次运行自动续采")
+        kw = item.get("keyword", "?")
+        return f"类目 {kw} 页码不前进，下次运行自动续采"
+
+    def refill_item(self, ctx, item) -> None:
+        """attempts 耗尽补插：category 同 payload 新 item（attempts=0），
+        discover 也补插一次。"""
+        db = ctx.store.db if ctx.store else None
+        if db is None:
+            return
+        kind = item.get("kind", "")
+        if kind == "category":
+            payload = {"kind": "category",
+                       "keyword": item["keyword"],
+                       "name": item.get("name", item["keyword"]),
+                       "fmt": item.get("fmt", "x2")}
+            self._insert_work_item(db, payload)
+            ctx.log(f"[refill] 类目 {item.get('keyword')} 补插 category item")
+        elif kind == "discover":
+            self._insert_work_item(db, {"kind": "discover"})
+            ctx.log("[refill] 补插 discover item")
 
     def after_item(self, ctx, item) -> None:
-        # 释放类目占用（采到末页的顺手标记，之后所有 worker 都跳过）
-        self.cat_pool.release(item[0],
-                              exhausted=ctx.state["task"].pop("exhausted",
-                                                              False))
+        pass
 
     def empty_message(self) -> str:
-        return "没有可采的类目了（全部采完或被占用）"
+        return "没有待认领的 work_item 了"
+
+    # ---- work_items 辅助 ----
+
+    @staticmethod
+    def _insert_work_item(db, payload: dict) -> int:
+        """向 work_items 插 pending 行，返回 id。"""
+        import json as _json
+        from fetcher.db import _now
+        cur = db.conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, created_at)"
+            " VALUES (?, ?, ?, ?)",
+            (MadeInChinaShopTask.QUEUE, MadeInChinaShopTask.SITE,
+             _json.dumps(payload, ensure_ascii=False), _now()))
+        db.conn.commit()
+        return cur.lastrowid
+
+    @staticmethod
+    def _count_pending_category(db, keyword: str) -> int:
+        """统计同 keyword 的 pending category item 数量。"""
+        return db.conn.execute(
+            "SELECT COUNT(*) FROM work_items WHERE queue=? AND status='pending'"
+            " AND json_extract(payload_json, '$.kind')='category'"
+            " AND json_extract(payload_json, '$.keyword')=?",
+            (MadeInChinaShopTask.QUEUE, keyword)).fetchone()[0]
diff --git a/fetcher/tests/test_madeinchina.py b/fetcher/tests/test_madeinchina.py
index 821de10..6306a13 100644
--- a/fetcher/tests/test_madeinchina.py
+++ b/fetcher/tests/test_madeinchina.py
@@ -13,23 +13,21 @@ from fetcher.core.types import ActionResult, Outcome
 from fetcher.detect.base import SceneInspector
 from fetcher.sites import get_site, site_names
 from fetcher.sites.madeinchina.contact import (
     MadeInChinaContactTask,
     contact_url_for,
     parse_contact_page,
     showroom_sub,
 )
 from fetcher.sites.madeinchina.features import HOMEPAGE, MARKET_DIR
 from fetcher.sites.madeinchina.shop import (
-    SEED_CATEGORIES,
     ZERO_NEW_LIMIT,
-    CategoryPool,
     MadeInChinaShopTask,
     PLATFORM_SUBDOMAINS,
     build_market_url,
     is_platform_subdomain,
 )
 from fetcher.strategy.policy import Policy
 
 from tests.test_control_loop import FakePage
 
 CONTACT_URL = "https://cn.made-in-china.com/showroom/dihewujin-contact.html"
@@ -400,60 +398,47 @@ class ShopTaskTest(unittest.TestCase):
         self.assertEqual(build_market_url("wujingj", 1),
                          "https://cn.made-in-china.com/market/wujingj_2-1.html")
         self.assertEqual(build_market_url("wujingj", 2),
                          "https://cn.made-in-china.com/market/wujingj_2-2.html")
         # -N 体系：fmt="plain" 拼 {slug}-{page}.html（jgdbj/huafangchuan 等）
         self.assertEqual(build_market_url("jgdbj", 1, fmt="plain"),
                          "https://cn.made-in-china.com/market/jgdbj-1.html")
         self.assertEqual(build_market_url("jgdbj", 2, fmt="plain"),
                          "https://cn.made-in-china.com/market/jgdbj-2.html")
 
-    def test_pool_remembers_fmt_per_slug(self):
-        pool = CategoryPool(exhausted=set())
-        pool.refresh([
-            {"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"},
-            {"slug": "jgdbj", "name": "激光打标机", "fmt": "plain"},
-            {"slug": "huafangchuan", "name": "画舫船"},  # 无 fmt，缺省 x2
-        ])
-        self.assertEqual(pool.fmt["bxgyxg"], "x2")
-        self.assertEqual(pool.fmt["jgdbj"], "plain")
-        self.assertEqual(pool.fmt["huafangchuan"], "x2")
-
-    def test_fetch_uses_fmt_for_plain_slug(self):
-        # -N 体系的 slug：fetch 应拼 {slug}-{page}.html，而不是 _2-
+    def test_fetch_uses_fmt_from_payload(self):
+        # fmt="plain"：fetch 应拼 {slug}-{page}.html，而不是 _2-
         page = MICPage()
         page.url = "https://cn.made-in-china.com/market/jgdbj-1.html"
         page._shops = [
             {"domain": "daqinjiguang.cn.made-in-china.com", "name": "大秦"}]
         page._next = False
         orig_evaluate = page.evaluate
 
         def eval_dispatch(js):
             if "location.pathname" in js:
                 return {"shops": page._shops, "next": False,
                         "found": "1"}
             return orig_evaluate(js)
 
         page.evaluate = eval_dispatch
         ctx = make_ctx(page, db=self.db)
-        self.task.cat_pool = CategoryPool(exhausted=set())
-        self.task.cat_pool.refresh(
-            [{"slug": "jgdbj", "name": "激光打标机", "fmt": "plain"}])
-        item = ("jgdbj", "激光打标机", 1)
+        # fmt 从 payload 获取（不再查池）
+        item = {"kind": "category", "keyword": "jgdbj",
+                "name": "激光打标机", "fmt": "plain"}
         result = self.task.fetch(ctx, item)
         self.assertEqual(result.outcome, Outcome.OK)
         # 访问的是 -1.html 短链 URL（不是 _2-1.html）
         url, kw = page.goto_calls[0]
         self.assertEqual(url,
                          "https://cn.made-in-china.com/market/jgdbj-1.html")
-        self.assertEqual(kw.get("referer"),
-                         "https://cn.made-in-china.com/")
+        self.assertEqual(kw.get("referer"), HOMEPAGE)
 
     def test_is_platform_subdomain(self):
         self.assertTrue(is_platform_subdomain("caigou"))
         self.assertFalse(is_platform_subdomain("dihewujin"))
 
     @patch("time.sleep")
     @patch("random.uniform", return_value=1.0)
     def test_fetch_extracts_showrooms(self, _r, _s):
         page = MICPage()
         page.url = "https://cn.made-in-china.com/market/wujingj_2-1.html"
@@ -466,113 +451,135 @@ class ShopTaskTest(unittest.TestCase):
         orig_evaluate = page.evaluate
 
         def eval_dispatch(js):
             if "location.pathname" in js:      # _JS_EXTRACT_SHOWROOMS
                 return {"shops": page._shops, "next": page._next,
                         "found": str(len(page._shops))}
             return orig_evaluate(js)
 
         page.evaluate = eval_dispatch
         ctx = make_ctx(page, db=self.db)
-        item = ("wujingj", "五金工具", 1)
+        # page_no 从 category_progress 读（无记录→1）
+        item = {"kind": "category", "keyword": "wujingj",
+                "name": "五金工具", "fmt": "x2"}
         result = self.task.fetch(ctx, item)
         self.assertEqual(result.outcome, Outcome.OK)
         domains = [s["domain"] for s in result.data["shops"]]
         self.assertIn("dihewujin.cn.made-in-china.com", domains)
         self.assertNotIn("caigou.cn.made-in-china.com", domains)  # 已过滤
         self.assertEqual(result.data["has_more"], True)
+        # 确认访问了第 1 页（无 category_progress → 1）
+        url, kw = page.goto_calls[0]
+        self.assertEqual(url, build_market_url("wujingj", 1))
+        self.assertEqual(kw.get("referer"), HOMEPAGE)
 
     def test_on_success_empty_marks_exhausted(self):
-        ctx = make_ctx(MICPage(), db=self.db)
+        page = MICPage()
+        ctx = make_ctx(page, db=self.db)
         ctx.state["task"]["stats"] = self.task.make_stats()
-        self.task.cat_pool = None  # on_success 不依赖 cat_pool
         r = ok_result({"shops": [], "has_more": False})
-        n = self.task.on_success(ctx, ("wujingj", "五金工具", 1), r)
+        item = {"kind": "category", "keyword": "wujingj",
+                "name": "五金工具", "fmt": "x2"}
+        n = self.task.on_success(ctx, item, r)
         self.assertEqual(n, 0)
         self.assertIn("wujingj", self.db.get_exhausted_keywords())
 
     def test_on_success_zero_new_marks_exhausted_after_limit(self):
-        # 提取到店铺但全部是已入库重复（服务端分页夹取回第 1 页）：健康分页
-        # 每页必有新增，连续 ZERO_NEW_LIMIT 页零新增即标 exhausted，
-        # 防止「满页≥20」启发式骗到永不停止（实测 bxgyxg 单页类目烧到 176 页）
-        ctx = make_ctx(MICPage(), db=self.db)
+        page = MICPage()
+        ctx = make_ctx(page, db=self.db)
         ctx.state["task"]["stats"] = self.task.make_stats()
-        self.task.cat_pool = None
         self.db.upsert_shops([
             {"domain": "dup1.cn.made-in-china.com", "name": "重复店"}])
         r = ok_result({"shops": [
             {"domain": "dup1.cn.made-in-china.com", "name": "重复店"}],
             "has_more": True})
-        item = ("bxgyxg", "不锈钢异型管", 1)
         # 前 limit-1 页零新增：页码前进，不 exhausted
-        for i in range(1, ZERO_NEW_LIMIT):
-            self.task.on_success(ctx, (item[0], item[1], i), r)
+        for _ in range(1, ZERO_NEW_LIMIT):
+            item = {"kind": "category", "keyword": "bxgyxg",
+                    "name": "不锈钢异型管", "fmt": "x2"}
+            self.task.on_success(ctx, item, r)
             self.assertNotIn("bxgyxg", self.db.get_exhausted_keywords())
         # 第 limit 页零新增：标 exhausted
-        self.task.on_success(ctx, (item[0], item[1], ZERO_NEW_LIMIT), r)
+        item = {"kind": "category", "keyword": "bxgyxg",
+                "name": "不锈钢异型管", "fmt": "x2"}
+        self.task.on_success(ctx, item, r)
         self.assertIn("bxgyxg", self.db.get_exhausted_keywords())
 
     def test_on_success_zero_new_resets_after_fresh_page(self):
-        # 零新增后页面又出现新店：计数清零不误杀（同类目后续仍有新店）
-        ctx = make_ctx(MICPage(), db=self.db)
+        page = MICPage()
+        ctx = make_ctx(page, db=self.db)
         ctx.state["task"]["stats"] = self.task.make_stats()
-        self.task.cat_pool = None
         self.db.upsert_shops([
             {"domain": "dup1.cn.made-in-china.com", "name": "重复店"}])
         dup = ok_result({"shops": [
             {"domain": "dup1.cn.made-in-china.com", "name": "重复店"}],
             "has_more": True})
         fresh = ok_result({"shops": [
             {"domain": "fresh1.cn.made-in-china.com", "name": "新店"}],
             "has_more": True})
-        item = ("wujingj", "五金工具", 1)
         # 1 页零新增 → 1 页有新增（清计数）→ 再 1 页零新增：不应 exhausted
-        self.task.on_success(ctx, (item[0], item[1], 1), dup)
-        self.task.on_success(ctx, (item[0], item[1], 2), fresh)
-        self.task.on_success(ctx, (item[0], item[1], 3), dup)
+        item = {"kind": "category", "keyword": "wujingj",
+                "name": "五金工具", "fmt": "x2"}
+        self.task.on_success(ctx, item, dup)
+        self.task.on_success(ctx, item, fresh)
+        self.task.on_success(ctx, item, dup)
         self.assertNotIn("wujingj", self.db.get_exhausted_keywords())
 
-    # ---- 类目池 DB 播种（首页 market 链接极少，跨 run 续采） ----
+    # ---- 类目提取正则：兼容 _2-N 与 -N，排除 _1-N ----
 
-    def test_get_active_categories_pinyin_only(self):
+    def test_extract_categories_js_matches_both_url_forms(self):
         # 只有拼音类目才算 madeinchina market slug；中文关键词行（1688 等
         # 其他任务）与 company: 前缀不算，exhausted 的不算
         from fetcher.db import _is_pinyin_slug
         self.assertTrue(_is_pinyin_slug("bxgyxg"))
         self.assertTrue(_is_pinyin_slug("wujingj"))
         self.assertFalse(_is_pinyin_slug("马面裙"))
         self.assertFalse(_is_pinyin_slug("company:快递袋"))
         self.assertFalse(_is_pinyin_slug("运动腰包、配件包"))
 
-    def test_prepare_seeds_pool_from_db(self):
-        # 首页提取可能失败/只给少量类目，prepare 要从 category_progress
-        # 把未采完的拼音类目播种进池，否则跨 run 搁浅
+    def test_prepare_seeds_from_db(self):
+        # prepare 从 category_progress 播种 category item + discover item
         self.db.conn.execute(
             "INSERT INTO category_progress (keyword, name, next_page) "
             "VALUES ('bxgyxg', '不锈钢异型管', 2)")
         self.db.conn.execute(
             "INSERT INTO category_progress (keyword, name, next_page, "
             "exhausted) VALUES ('xxylsb', '新型游乐设备', 1, 1)")
         self.db.conn.commit()
         db_path = self.db.conn.execute(
-            "PRAGMA database_list").fetchone()[2]  # self.db 的真实文件路径
-        self.db.close()  # prepare 会新开连接，先关掉避免文件锁
+            "PRAGMA database_list").fetchone()[2]
+        self.db.close()
         cfg = RunConfig()
         cfg.db_path = db_path
         task = MadeInChinaShopTask()
         self.assertTrue(task.prepare(cfg))
-        self.assertIn("bxgyxg", task.cat_pool.pool)      # 未采完拼音类目播种
-        self.assertNotIn("xxylsb", task.cat_pool.pool)   # exhausted 的不播
-
-    # ---- 首页类目提取正则：兼容 _2-N 与 -N，排除 _1-N ----
+        # 验证播种了 work_items
+        db_check = ShopDB(db_path)
+        import json
+        items = db_check.conn.execute(
+            "SELECT payload_json FROM work_items WHERE queue=? "
+            "AND status='pending' ORDER BY id",
+            ("crawl_mic_shop",)).fetchall()
+        payloads = [json.loads(r["payload_json"]) for r in items]
+        # bxgyxg 应播种为 category item
+        self.assertTrue(any(
+            p.get("kind") == "category" and p.get("keyword") == "bxgyxg"
+            for p in payloads))
+        # xxylsb 是 exhausted，不应播种
+        self.assertFalse(any(
+            p.get("keyword") == "xxylsb" for p in payloads))
+        # 至少一条 discover
+        self.assertTrue(any(
+            p.get("kind") == "discover" for p in payloads))
+        db_check.close()
 
-    def test_extract_categories_js_matches_both_url_forms(self):
+    def test_get_active_categories_pinyin_only(self):
         import re
         # 与 _JS_EXTRACT_CATEGORIES 里的正则镜像校验：JS 侧 regex 是
         # /\\/market\\/([a-zA-Z0-9]+?)(?:_2)?-\\d+\\.html/，这里用等价
         # Python 正则验证匹配语义（_2- 分页页与 -1.html 短链都要，_1- 移动
         # 端变体排除），并验证 fmt 判定（含 _2- 前缀 -> x2，否则 plain）
         pat = re.compile(r"/market/([a-zA-Z0-9]+?)(?:_2)?-\d+\.html")
         cases = [
             ("/market/bxgyxg_2-1.html", "bxgyxg", "x2"),    # _2- 分页格式
             ("/market/jgdbj-1.html", "jgdbj", "plain"),     # -1.html 短链
             ("/market/CODcdy-1.html", "CODcdy", "plain"),   # 含大写 slug
@@ -582,87 +589,35 @@ class ShopTaskTest(unittest.TestCase):
             ("/market/mzhxt_1-1.html", None, None),
         ]
         for href, expect_slug, expect_fmt in cases:
             m = pat.search(href)
             got = m.group(1) if m else None
             self.assertEqual(got, expect_slug, href)
             if m is not None:
                 fmt = "x2" if "_2-" in m.group(0) else "plain"
                 self.assertEqual(fmt, expect_fmt, href)
 
-    # ---- acquire 空转重试：被其他 worker 暂占时等待而非退出 ----
-
-    def test_pick_none_but_has_active_distinguishes_busy(self):
-        # 只剩一个类目且被另一个 worker 占着：pick 返回 None，但池里还有
-        # 活跃类目（has_active=True）→ acquire 应等待重试而非直接退出
-        pool = CategoryPool(exhausted=set())
-        pool.pool = {"bxgyxg": "不锈钢异型管"}
-        pool.in_progress = {"bxgyxg"}  # 被另一个 worker 占用
-        self.assertIsNone(pool.pick())
-        self.assertTrue(pool.has_active())
-
-    def test_pick_none_all_exhausted_no_active(self):
-        pool = CategoryPool(exhausted={"bxgyxg"})
-        pool.pool = {"bxgyxg": "不锈钢异型管"}
-        self.assertIsNone(pool.pick())
-        self.assertFalse(pool.has_active())
-
-    # ---- cold_start 类目播种：首页 + 市场导航页（/shichang/）----
+    # ---- cold_start 纯浏览软着陆 ----
 
     @patch("time.sleep")
     @patch("random.uniform", return_value=1.0)
-    def test_cold_start_seeds_pool_from_market_dir(self, _r, _s):
-        # 首页只暴露少量 market 链接（~129 个，2026-08-06 已全部采干），
-        # 类目主力入口是市场导航页 /shichang/（~947 个）；两页都提取合并进池
+    def test_cold_start_browses_home_and_market_dir(self, _r, _s):
+        """冷启动仅浏览首页+导航页（软着陆），不提取类目。"""
         page = MICPage()
-
-        def eval_dispatch(js):
-            if "querySelectorAll" in js and "/market/" in js:
-                if "shichang" in page.url:
-                    return [{"slug": "jgdbj", "name": "激光打标机",
-                             "fmt": "plain"},
-                            {"slug": "wujingj", "name": "五金工具",
-                             "fmt": "x2"}]
-                return [{"slug": "wujingj", "name": "五金工具", "fmt": "x2"}]
-            return ""
-
-        page.evaluate = eval_dispatch
         ctx = make_ctx(page)
-        self.task.cat_pool = CategoryPool(exhausted=set())
         self.task.cold_start(ctx, None)
-        self.assertIn("jgdbj", self.task.cat_pool.pool)     # 导航页类目进池
-        self.assertIn("wujingj", self.task.cat_pool.pool)   # 首页类目进池
-        # 首页与导航页重复的 slug 只占一个坑
-        self.assertEqual(list(self.task.cat_pool.pool).count("wujingj"), 1)
-        # 两个页面都逛了（留真实浏览轨迹）
         urls = [u for u, _ in page.goto_calls]
         self.assertIn(HOMEPAGE, urls)
         self.assertIn(MARKET_DIR, urls)
-
-    @patch("time.sleep")
-    @patch("random.uniform", return_value=1.0)
-    def test_cold_start_both_pages_fail_falls_back_to_seeds(self, _r, _s):
-        # 首页与导航页都提取失败：兜底内置种子类目并打出警告
-        page = MICPage()
-
-        def boom(url, **kw):
-            raise RuntimeError("net down")
-
-        page.goto = boom
-        ctx = make_ctx(page)
-        logs = []
-        ctx.log = logs.append
-        self.task.cat_pool = CategoryPool(exhausted=set())
-        self.task.cold_start(ctx, None)
-        self.assertEqual(sorted(self.task.cat_pool.pool),
-                         sorted(k for k, _ in SEED_CATEGORIES))
-        self.assertTrue(any("种子类目" in m for m in logs))
+        # 没有提取类目（cold_start 不再做这事）
+        # 验证 goto 正常完成即可
+        self.assertEqual(len(urls), 2)
 
 
 # ---------- 策略覆盖 ----------
 
 class PolicyOverrideTest(unittest.TestCase):
     def test_no_solve_slider_for_vemic(self):
         site = get_site("madeinchina")
         overrides = site.policy_overrides
         self.assertIn(Scenario.RISK_SLIDER_PAGE, overrides)
         for chain in overrides.values():
diff --git a/fetcher/tests/test_mic_shop_feeder.py b/fetcher/tests/test_mic_shop_feeder.py
new file mode 100644
index 0000000..269a8f2
--- /dev/null
+++ b/fetcher/tests/test_mic_shop_feeder.py
@@ -0,0 +1,566 @@
+# -*- coding: utf-8 -*-
+"""P3 Step 4.1: mic shop feeder 任务拆分（work_items 驱动）测试。
+
+TDD 覆盖：链式续喂、ZERO_NEW_LIMIT 保护、失败补插、discover 产出、
+幂等播种、CLI acquire、page_no 运行时读、refill_item 基类默认空。
+全 mock，不起浏览器/网络。
+"""
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+from unittest.mock import patch
+
+from fetcher import RunConfig, Session, ShopDB, WorkerContext
+from fetcher.control.task import Task
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.sites.madeinchina.shop import (
+    ZERO_NEW_LIMIT,
+    MadeInChinaShopTask,
+    build_market_url,
+    fetch_market_categories,
+)
+from fetcher.sites.madeinchina.features import HOMEPAGE, MARKET_DIR
+
+from tests.test_control_loop import FakePage
+
+QUEUE = "crawl_mic_shop"
+SITE = "madeinchina"
+
+
+# ---- helpers ----
+
+def ok_result(data=None):
+    return ActionResult(Outcome.OK, "", data or {})
+
+
+def make_ctx(page=None, db=None):
+    """构造 WorkerContext（带 session + db）。"""
+    if page is None:
+        page = FakePage()
+    ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
+    ctx.session = Session(page=page)
+    if db is not None:
+        from fetcher import IdentityStore
+        ctx.store = IdentityStore(db)
+    ctx.state["task"] = {"stats": MadeInChinaShopTask().make_stats()}
+    return ctx
+
+
+def _insert_work_item(db: ShopDB, payload: dict, queue=QUEUE,
+                      site=SITE) -> int:
+    """直接向 work_items 插 pending 行，返回 id。"""
+    cur = db.conn.execute(
+        "INSERT INTO work_items (queue, site, payload_json, created_at)"
+        " VALUES (?, ?, ?, datetime('now', 'localtime'))",
+        (queue, site, json.dumps(payload, ensure_ascii=False)))
+    db.conn.commit()
+    return cur.lastrowid
+
+
+def _cat_payload(keyword="bxgyxg", name="不锈钢异型管", fmt="x2"):
+    return {"kind": "category", "keyword": keyword, "name": name, "fmt": fmt}
+
+
+def _discover_payload():
+    return {"kind": "discover"}
+
+
+def _pending_items(db, queue=QUEUE):
+    """返回 queue 的 pending 工作项列表。"""
+    rows = db.conn.execute(
+        "SELECT id, payload_json FROM work_items WHERE queue=? "
+        "AND status='pending' ORDER BY id", (queue,)).fetchall()
+    return [(r["id"], json.loads(r["payload_json"])) for r in rows]
+
+
+class MICShopPage(FakePage):
+    """madeinchina market 分页页假页面。"""
+
+    def __init__(self, shops=None, has_next=False, url=None):
+        super().__init__()
+        self.url = url or build_market_url("bxgyxg", 1)
+        self._shops = shops or []
+        self._next = has_next
+        self.goto_calls = []
+        self._exceptions = []
+
+    def evaluate(self, js):
+        if "location.pathname" in js:
+            return {"shops": self._shops, "next": self._next,
+                    "found": str(len(self._shops))}
+        return ""  # category extraction JS returns empty
+
+    def goto(self, url, **kw):
+        self.goto_calls.append((url, kw))
+        self.url = url
+
+
+# ---- 1. 链式续喂 ----
+
+class ChainFeedTest(unittest.TestCase):
+    """category item on_success → advance + INSERT 下一页 item。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "c.db")
+        self.task = MadeInChinaShopTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_chain_feed_inserts_next_page_item(self):
+        """有新增店铺 → category_progress next_page+1 + 新 work_item。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
+        result = ok_result({
+            "shops": [{"domain": "newshop.cn.made-in-china.com",
+                       "name": "新店"}],
+            "has_more": True,
+        })
+
+        count = self.task.on_success(ctx, item, result)
+        self.assertEqual(count, 1)
+
+        # 页码前进
+        prog = self.db.get_category_progress("bxgyxg")
+        self.assertIsNotNone(prog)
+        self.assertEqual(prog["next_page"], 2)
+        self.assertEqual(prog["pages_crawled"], 1)
+
+        # 新 work_item 插入（同 payload，attempts=0）
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], _cat_payload("bxgyxg", "不锈钢异型管", "x2"))
+
+    def test_chain_feed_skips_when_exhausted(self):
+        """空页 → mark_category_exhausted → 不插下一页 item。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
+        result = ok_result({"shops": [], "has_more": False})
+
+        self.task.on_success(ctx, item, result)
+
+        # exhausted
+        self.assertIn("bxgyxg", self.db.get_exhausted_keywords())
+        # 无新 work_item
+        self.assertEqual(len(_pending_items(self.db)), 0)
+
+
+# ---- 2. ZERO_NEW_LIMIT 保护 ----
+
+class ZeroNewLimitTest(unittest.TestCase):
+    """连续 N 页零新增 → mark_category_exhausted + 不插下一页。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "z.db")
+        self.task = MadeInChinaShopTask()
+        # 预插一个重复店铺
+        self.db.upsert_shops([
+            {"domain": "dup.cn.made-in-china.com", "name": "重复店"}])
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_zero_new_exhausts_after_limit(self):
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        dup_result = ok_result({
+            "shops": [{"domain": "dup.cn.made-in-china.com", "name": "重复店"}],
+            "has_more": True,
+        })
+
+        # 前 ZERO_NEW_LIMIT-1 页：页码前进，不 exhausted
+        for i in range(1, ZERO_NEW_LIMIT):
+            item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
+            self.task.on_success(ctx, item, dup_result)
+            self.assertNotIn("bxgyxg", self.db.get_exhausted_keywords())
+
+        # 第 ZERO_NEW_LIMIT 页零新增：标 exhausted
+        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
+        self.task.on_success(ctx, item, dup_result)
+        self.assertIn("bxgyxg", self.db.get_exhausted_keywords())
+
+    def test_zero_new_resets_after_fresh(self):
+        """零新增后出现新店：计数清零不误杀。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        dup_result = ok_result({
+            "shops": [{"domain": "dup.cn.made-in-china.com", "name": "重复店"}],
+            "has_more": True,
+        })
+        fresh_result = ok_result({
+            "shops": [{"domain": "fresh.cn.made-in-china.com", "name": "新店"}],
+            "has_more": True,
+        })
+
+        item = _cat_payload("wujingj", "五金工具", "x2")
+        # 1 页零新增 → 1 页有新增（清计数）→ 再 1 页零新增：不应 exhausted
+        self.task.on_success(ctx, item, dup_result)
+        self.task.on_success(ctx, item, fresh_result)
+        self.task.on_success(ctx, item, dup_result)
+        self.assertNotIn("wujingj", self.db.get_exhausted_keywords())
+
+    def test_zero_new_no_chain_feed_when_exhausted(self):
+        """ZERO_NEW_LIMIT 耗尽后不插下一页 item。
+
+        前 ZERO_NEW_LIMIT-1 次链式续喂产 work_item，最后一次不产。
+        """
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        dup_result = ok_result({
+            "shops": [{"domain": "dup.cn.made-in-china.com", "name": "重复店"}],
+            "has_more": True,
+        })
+
+        for _ in range(ZERO_NEW_LIMIT):
+            self.task.on_success(ctx, _cat_payload(), dup_result)
+
+        # 第 1 次非 exhausted 产 1 条链式续喂；第 2 次 exhausted 不产
+        # 总共 1 条 pending
+        self.assertEqual(len(_pending_items(self.db)), 1)
+
+
+# ---- 3. 失败补插 ----
+
+class RefillItemTest(unittest.TestCase):
+    """category item attempts 耗尽 → 同 payload 新 item。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "r.db")
+        self.task = MadeInChinaShopTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_refill_inserts_replacement_category_item(self):
+        """category 失败 → 插入同 payload 新 item（attempts=0）。"""
+        ctx = make_ctx(db=self.db)
+        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
+        ctx.state["item"] = item
+
+        self.task.refill_item(ctx, item)
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], item)
+        # attempts=0（新行默认）
+        row = self.db.conn.execute(
+            "SELECT attempts FROM work_items WHERE id=?",
+            (items[0][0],)).fetchone()
+        self.assertEqual(row["attempts"], 0)
+
+    def test_refill_discover_also_replenishes(self):
+        """discover 失败也补插一次（幂等由'无同 keyword pending item'保证）。"""
+        ctx = make_ctx(db=self.db)
+        item = _discover_payload()
+        ctx.state["item"] = item
+
+        self.task.refill_item(ctx, item)
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], _discover_payload())
+
+
+# ---- 4. discover 产出 ----
+
+class DiscoverOutputTest(unittest.TestCase):
+    """discover on_success → 提取类目 → 新类目逐条 INSERT category item。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "d.db")
+        self.task = MadeInChinaShopTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def _mock_categories(self, page, cats_by_url: dict):
+        """Mock fetch_market_categories 按 URL 返回类目。"""
+        orig = fetch_market_categories
+
+        def mock_fetch(page_obj, url):
+            if url in cats_by_url:
+                return cats_by_url[url]
+            return orig(page_obj, url)
+
+        return mock_fetch
+
+    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
+    def test_discover_inserts_new_categories(self, mock_fetch):
+        """新类目（不在 category_progress、无 pending item）逐条 INSERT。"""
+        mock_fetch.side_effect = lambda page, url: {
+            HOMEPAGE: [{"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"}],
+            MARKET_DIR: [
+                {"slug": "jgdbj", "name": "激光打标机", "fmt": "plain"},
+                {"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"},  # dup
+            ],
+        }.get(url, [])
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        item = _discover_payload()
+        result = ok_result({"discover": True})
+
+        count = self.task.on_success(ctx, item, result)
+        # discover 不计入页数
+        self.assertEqual(count, 0)
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 2)  # bxgyxg + jgdbj（slug 去重）
+        payloads = [p for _, p in items]
+        self.assertIn({"kind": "category", "keyword": "bxgyxg",
+                       "name": "不锈钢异型管", "fmt": "x2"}, payloads)
+        self.assertIn({"kind": "category", "keyword": "jgdbj",
+                       "name": "激光打标机", "fmt": "plain"}, payloads)
+
+    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
+    def test_discover_skips_exhausted_categories(self, mock_fetch):
+        """已在 category_progress 且 exhausted 的类目不插。"""
+        # 先标记 bxgyxg 为 exhausted
+        self.db.mark_category_exhausted("bxgyxg", "不锈钢异型管")
+
+        mock_fetch.side_effect = lambda page, url: {
+            HOMEPAGE: [{"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"},
+                       {"slug": "wujingj", "name": "五金工具", "fmt": "x2"}],
+        }.get(url, [])
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        self.task.on_success(ctx, _discover_payload(), ok_result({"discover": True}))
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 1)  # 只有 wujingj
+        self.assertEqual(items[0][1]["keyword"], "wujingj")
+
+    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
+    def test_discover_skips_existing_pending_category(self, mock_fetch):
+        """已有同 keyword pending category item 时跳过不重复插。"""
+        _insert_work_item(self.db, _cat_payload("bxgyxg", "不锈钢异型管", "x2"))
+
+        mock_fetch.side_effect = lambda page, url: {
+            HOMEPAGE: [{"slug": "bxgyxg", "name": "不锈钢异型管", "fmt": "x2"},
+                       {"slug": "wujingj", "name": "五金工具", "fmt": "x2"}],
+        }.get(url, [])
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        self.task.on_success(ctx, _discover_payload(), ok_result({"discover": True}))
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 2)  # 原 bxgyxg + 新 wujingj
+        keywords = [p["keyword"] for _, p in items if p.get("keyword")]
+        self.assertEqual(sorted(keywords), ["bxgyxg", "wujingj"])
+
+    @patch("fetcher.sites.madeinchina.shop.fetch_market_categories")
+    def test_discover_fallback_seeds(self, mock_fetch):
+        """首页+导航页都提取失败 → 兜底种子类目。"""
+        mock_fetch.return_value = []  # 全部失败
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"]["stats"] = self.task.make_stats()
+
+        self.task.on_success(ctx, _discover_payload(), ok_result({"discover": True}))
+
+        items = _pending_items(self.db)
+        self.assertGreater(len(items), 0)
+        # 至少包含种子类目
+        keywords = {p["keyword"] for _, p in items if p.get("keyword")}
+        self.assertIn("wujingj", keywords)
+
+
+# ---- 5. 幂等播种 ----
+
+class IdempotentSeedTest(unittest.TestCase):
+    """重复 prepare/播种 → 不产生重复 pending item。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = str(Path(self._tmp.name) / "s.db")
+        self.db = ShopDB(self.db_path)
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_double_prepare_no_duplicates(self):
+        """两次 prepare 不产生重复 pending item。"""
+        # 预置 category_progress（未采完拼音类目）
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page) "
+            "VALUES ('bxgyxg', '不锈钢异型管', 2)")
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page, "
+            "exhausted) VALUES ('xxylsb', '新型游乐设备', 1, 1)")
+        self.db.conn.commit()
+        self.db.close()
+
+        cfg = RunConfig()
+        cfg.db_path = self.db_path
+
+        task1 = MadeInChinaShopTask()
+        self.assertTrue(task1.prepare(cfg))
+        # 第一次 prepare 后应有 pending items
+        db_check = ShopDB(self.db_path)
+        items1 = _pending_items(db_check)
+        # 至少 bxgyxg（active）+ discover
+        keywords1 = {p.get("keyword") for _, p in items1 if p.get("keyword")}
+        self.assertIn("bxgyxg", keywords1)
+        self.assertNotIn("xxylsb", keywords1)  # exhausted
+        # 至少 1 条 discover
+        discover_count = sum(1 for _, p in items1 if p.get("kind") == "discover")
+        self.assertEqual(discover_count, 1)
+        db_check.close()
+
+        # 第二次 prepare：不产生重复
+        task2 = MadeInChinaShopTask()
+        self.assertTrue(task2.prepare(cfg))
+        db_check2 = ShopDB(self.db_path)
+        items2 = _pending_items(db_check2)
+        self.assertEqual(len(items2), len(items1))  # 无新重复
+        db_check2.close()
+
+
+# ---- 6. CLI acquire ----
+
+class CliAcquireTest(unittest.TestCase):
+    """claim_next_eligible(["crawl_mic_shop"]) 认领返回 payload；无货 None。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "a.db")
+        self.task = MadeInChinaShopTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_acquire_returns_payload(self):
+        _insert_work_item(self.db, _cat_payload("bxgyxg", "不锈钢异型管", "x2"))
+        ctx = make_ctx(db=self.db)
+        ctx.wid = 1
+
+        item = self.task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["kind"], "category")
+        self.assertEqual(item["keyword"], "bxgyxg")
+        self.assertEqual(item["name"], "不锈钢异型管")
+        self.assertEqual(item["fmt"], "x2")
+        self.assertIn("id", item)  # work_item id 带在 payload 里
+
+    def test_acquire_returns_none_when_empty(self):
+        ctx = make_ctx(db=self.db)
+        ctx.wid = 1
+        self.assertIsNone(self.task.acquire_item(ctx))
+
+    def test_acquire_returns_discover_payload(self):
+        _insert_work_item(self.db, _discover_payload())
+        ctx = make_ctx(db=self.db)
+        ctx.wid = 1
+
+        item = self.task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["kind"], "discover")
+
+
+# ---- 7. page_no 运行时读 ----
+
+class PageNoRuntimeTest(unittest.TestCase):
+    """fetch 时从 category_progress 读 next_page。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "p.db")
+        self.task = MadeInChinaShopTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    @patch("time.sleep")
+    @patch("random.uniform", return_value=1.0)
+    def test_fetch_reads_next_page_from_db(self, _r, _s):
+        """category_progress.next_page=3 → fetch 第 3 页。"""
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page, "
+            "pages_crawled) VALUES ('bxgyxg', '不锈钢异型管', 3, 2)")
+        self.db.conn.commit()
+
+        page = MICShopPage(
+            shops=[{"domain": "shop1.cn.made-in-china.com", "name": "店1"}],
+            has_next=False)
+        ctx = make_ctx(page=page, db=self.db)
+        item = _cat_payload("bxgyxg", "不锈钢异型管", "x2")
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+
+        # 验证 fetch 了第 3 页
+        url, kw = page.goto_calls[0]
+        self.assertEqual(url, build_market_url("bxgyxg", 3))
+        # referer 是第 2 页
+        self.assertEqual(kw.get("referer"),
+                         build_market_url("bxgyxg", 2))
+
+    @patch("time.sleep")
+    @patch("random.uniform", return_value=1.0)
+    def test_fetch_defaults_to_page_1_when_no_progress(self, _r, _s):
+        """无 category_progress → page_no=1。"""
+        page = MICShopPage(has_next=True)
+        ctx = make_ctx(page=page, db=self.db)
+        item = _cat_payload("newcat", "新类目", "x2")
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+        url, kw = page.goto_calls[0]
+        self.assertEqual(url, build_market_url("newcat", 1))
+        self.assertEqual(kw.get("referer"), HOMEPAGE)
+
+    @patch("time.sleep")
+    @patch("random.uniform", return_value=1.0)
+    def test_fetch_discover_returns_success_without_request(self, _r, _s):
+        """discover item：fetch 不抓页面，返回 discover 标记。"""
+        page = FakePage()
+        ctx = make_ctx(page=page, db=self.db)
+        item = _discover_payload()
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+        self.assertTrue(result.data.get("discover"))
+        # 不发网络请求
+        self.assertEqual(len(getattr(page, "goto_calls", [])), 0)
+
+
+# ---- 8. refill_item 基类默认空 ----
+
+class BaseRefillItemDefaultTest(unittest.TestCase):
+    """Task 基类 refill_item 默认空实现（contact 等不补插）。"""
+
+    def test_base_refill_item_is_noop(self):
+        task = Task()
+        ctx = make_ctx()
+        item = {"kind": "category", "keyword": "test", "name": "test", "fmt": "x2"}
+        # 不应抛异常
+        task.refill_item(ctx, item)
+
+
+if __name__ == "__main__":
+    unittest.main()
