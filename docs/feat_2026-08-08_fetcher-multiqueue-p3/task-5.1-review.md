# Review Package — Step 5.1 (1688 shop/company feeder 拆分)

## Commits
3fedf72 feat(multiqueue-p3): 1688 shop/company feeder 任务拆分（work_items 驱动）

## Stat
 .../task-5.1-report.md                             |  132 +++
 fetcher/fetcher/sites/alibaba1688/__init__.py      |    8 +-
 fetcher/fetcher/sites/alibaba1688/company.py       |  315 ++++--
 fetcher/fetcher/sites/alibaba1688/shop.py          |  302 ++++--
 fetcher/tests/test_1688_feeder.py                  | 1072 ++++++++++++++++++++
 5 files changed, 1631 insertions(+), 198 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.1-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.1-report.md
new file mode 100644
index 0000000..eff652a
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.1-report.md
@@ -0,0 +1,132 @@
+# Task 5.1 Report — 1688 shop/company feeder 任务拆分
+
+## 状态：DONE
+
+## 实现摘要
+
+按 brief 规格，将 `ShopTask` / `CompanyTask` 从 CategoryPool/KeywordPool 进程内填池模式重构为 work_items 驱动 feeder 模式，与 Step 4.1 的 `MadeInChinaShopTask` 同模式。
+
+### 改动文件
+
+| 文件 | 变更 |
+|---|---|
+| `fetcher/fetcher/sites/alibaba1688/shop.py` | 全面重构：移除 CategoryPool，新增 Alibaba1688ShopTask（work_items feeder 模式） |
+| `fetcher/fetcher/sites/alibaba1688/company.py` | 全面重构：移除 KeywordPool，新增 Alibaba1688CompanyTask（work_items feeder 模式） |
+| `fetcher/fetcher/sites/alibaba1688/__init__.py` | make_task 更新为新类名 |
+| `fetcher/tests/test_1688_feeder.py` | **新增** 41 个 TDD 测试 |
+
+### shop.py 变更要点
+
+- 移除 `CategoryPool` 类（:110-170）
+- 新增 `Alibaba1688ShopTask`（原 `ShopTask`），保留向后兼容别名 `ShopTask = Alibaba1688ShopTask`
+- 新增 `QUEUE = "crawl_1688_shop"`, `SITE = "1688"`
+- **prepare**: 从 `iter_active_categories()`（无拼音过滤，1688 中文/英文都算）逐条播种 category item + 1 条 discover item（幂等）
+- **acquire_item**: `claim_next_eligible(["crawl_1688_shop"], consumer_id)` → payload dict（含 id）
+- **fetch**: `kind=="discover"` → 返回 discover 标记；`kind=="category"` → 读 `category_progress.next_page` → 现搜索页逻辑；无 mtop → BLOCKED
+- **validate**: discover 检查 `discover` 键放行（C1 教训回归）；category 检查 shops list
+- **on_success**: discover → `fetch_homepage_categories` + `ensure_mtop_token` → 新类目逐条 INSERT category item（幂等：跳过 exhausted/pending）；category → 入库 + 链式续喂（hasMore/空页判 exhausted，无 ZERO_NEW_LIMIT）
+- **refill_item**: category 同 payload 补插；discover 补插
+- **cold_start**: 纯浏览软着陆（类目提取归 discover）
+- **after_item**: 空操作（无 CategoryPool 释放）
+
+### company.py 变更要点
+
+- 移除 `KeywordPool` 类（:145-166）
+- 新增 `Alibaba1688CompanyTask`（原 `CompanyTask`），保留向后兼容别名 `CompanyTask = Alibaba1688CompanyTask`
+- 新增 `QUEUE = "crawl_1688_company"`, `SITE = "1688"`
+- **prepare**: 从 `iter_active_categories(prefix="company:")` 播种 category item + 1 条 discover item（幂等）
+- **acquire_item**: `claim_next_eligible(["crawl_1688_company"], consumer_id)` → payload dict
+- **fetch (category)**: 进度键 `get_category_progress("company:女装")`；URL 拼接时去掉前缀裸关键词
+- **fetch (discover)**: 返回 discover 标记
+- **validate**: discover 检查 discover 键；category 检查 shops list
+- **on_success (discover)**: `fetch_homepage_categories` → `ensure_mtop_token` → 新类目逐条 INSERT（keyword 自动加 `company:` 前缀）
+- **on_success (category)**: 入库 shops（`upsert_shops`），progress 键带 `company:` 前缀，链式续喂
+- **refill_item**: category/discover 补插
+- **cold_start**: 纯浏览软着陆
+
+### 未改文件
+
+- `fetcher/fetcher/db.py` — 本次不改
+- `fetcher/fetcher/control/task.py` — `refill_item` 钩子 Step 4.1 已加，本次不碰
+- `platform/`, `scraper/`, `util/` — 不碰
+
+## 测试列表（41 项）
+
+### 1. 链式续喂（1688 shop）
+- `test_chain_feed_inserts_next_page_item` — 有新增 + hasMore → advance + 新 work_item
+- `test_chain_feed_exhausted_when_no_shops` — 空页 → exhausted 不续喂
+- `test_chain_feed_exhausted_when_no_has_more` — hasMore=false → exhausted 不续喂
+- `test_chain_feed_continues_when_has_more_and_shops` — 有店铺有 hasMore → 不 exhausted，续喂
+
+### 2. 链式续喂（1688 company）
+- `test_company_chain_feed_inserts_next_page` — company: 前缀进度 + 新 work_item
+- `test_company_chain_feed_exhausted_when_empty` — company: 空页 exhausted
+
+### 3. discover 产出（1688 shop）— 含 mtop 握手
+- `test_discover_inserts_new_categories` — 新类目逐条 INSERT
+- `test_discover_skips_exhausted_categories` — 跳过已 exhausted
+- `test_discover_skips_existing_pending_category` — 跳过已有 pending
+- `test_discover_fallback_seeds` — 提取失败 → 兜底种子
+- `test_discover_calls_mtop_handshake` — ensure_mtop_token 被调用
+
+### 4. discover 产出（1688 company）
+- `test_company_discover_inserts_prefixed_categories` — company: 前缀 keyword
+- `test_company_discover_skips_exhausted` — 跳过 company: 前缀 exhausted
+- `test_company_discover_fallback_seeds` — company: 前缀兜底种子
+
+### 5. company: 前缀隔离
+- `test_progress_keys_are_isolated` — 同一 keyword shop/company 进度互不干扰
+- `test_exhausted_keys_filtered_by_prefix` — iter_active_categories(prefix="company:") 只返回 company: 行
+- `test_company_prepare_seeds_only_prefixed` — company prepare 播种只产 company: 前缀 keyword
+
+### 6. 失败补插
+- `test_shop_refill_category` — shop category refill
+- `test_shop_refill_discover` — shop discover refill
+- `test_company_refill_category` — company category refill
+- `test_company_refill_discover` — company discover refill
+
+### 7. 幂等播种
+- `test_shop_double_prepare_no_duplicates` — shop 两次 prepare 无重复
+- `test_company_double_prepare_no_duplicates` — company 两次 prepare 无重复
+
+### 8. CLI acquire
+- `test_shop_acquire_returns_payload` — claim_next_eligible 返回 payload
+- `test_shop_acquire_returns_none_when_empty` — 无货 None
+- `test_shop_acquire_returns_discover` — discover payload
+- `test_company_acquire_returns_payload` — company claim_next_eligible
+- `test_company_acquire_returns_none_when_empty` — company 无货 None
+
+### 9. validate discover 放行
+- `test_shop_validate_discover_passes` — shop validate 放行 discover
+- `test_shop_validate_category_checks_shops` — shop validate category 检查 shops
+- `test_company_validate_discover_passes` — company validate 放行 discover
+- `test_discover_full_pipeline_shop` — shop discover 三段式 fetch→validate→on_success
+
+### 10. shop fetch 读 next_page + mtop 检查
+- `test_fetch_reads_next_page_from_db` — category_progress.next_page=3 → fetch 第 3 页
+- `test_fetch_defaults_to_page_1` — 无 progress → page_no=1
+- `test_fetch_blocked_when_no_mtop` — 无 mtop → BLOCKED
+- `test_fetch_discover_no_request` — discover fetch 不发网络请求
+
+### 11. company fetch 读 next_page（company: 前缀）
+- `test_company_fetch_uses_prefixed_progress` — company:前缀进度 → fetch 对应页
+- `test_company_fetch_defaults_to_page_1` — company 无 progress → page=1
+- `test_company_fetch_blocked_no_mtop` — company 无 mtop → BLOCKED
+
+### 12. 类名兼容
+- `test_shop_task_instantiable` — make_task("shop") → Alibaba1688ShopTask
+- `test_company_task_instantiable` — make_task("company") → Alibaba1688CompanyTask
+
+## TDD 证据（RED → GREEN）
+
+1. **RED**: 先写 test_1688_feeder.py，运行失败（ImportError: cannot import Alibaba1688ShopTask）
+2. **GREEN**: 实现 shop.py / company.py / __init__.py 重构，41/41 通过
+3. **GREEN**: 全量 509 passed（468 基线 + 41 新增），无回归
+
+## 自查发现
+
+1. **company: 前缀隔离验证通过**: `test_progress_keys_are_isolated` 证明同一 keyword（女装）在 shop（keyword="女装"）和 company（keyword="company:女装"）的 category_progress 记录完全隔离，iter_active_categories(prefix="company:") 只返回 company: 行。
+2. **discover 三段式验证通过**: `test_discover_full_pipeline_shop` 完整测试 fetch→validate→on_success，确保 C1 教训不会在 1688 重复（validate 正确放行 discover）。
+3. **向后兼容**: `ShopTask` / `CompanyTask` 别名保留，`__init__.py` 的 `make_task` 路径不变，`test_summary_db_path.py` 等既有测试无需修改。
+4. **无 ZERO_NEW_LIMIT**: 按 brief 裁定，1688 沿用现状 hasMore/空页 exhausted 判定，不引入 mic 的零新增保护。
+5. **不碰文件清单**: `db.py`、`task.py`、`platform/`、`scraper/`、`util/` 均未改动。
diff --git a/fetcher/fetcher/sites/alibaba1688/__init__.py b/fetcher/fetcher/sites/alibaba1688/__init__.py
index 47ff8fb..367c618 100644
--- a/fetcher/fetcher/sites/alibaba1688/__init__.py
+++ b/fetcher/fetcher/sites/alibaba1688/__init__.py
@@ -50,25 +50,25 @@ class Alibaba1688Plugin:
 
     def task_names(self) -> list[str]:
         return ["contact", "shop", "company"]
 
     def make_task(self, name: str):
         """按名创建任务实例（控制层 Task 协议）。"""
         if name == "contact":
             from fetcher.sites.alibaba1688.contact import ContactTask
             return ContactTask()
         if name == "shop":
-            from fetcher.sites.alibaba1688.shop import ShopTask
-            return ShopTask()
+            from fetcher.sites.alibaba1688.shop import Alibaba1688ShopTask
+            return Alibaba1688ShopTask()
         if name == "company":
-            from fetcher.sites.alibaba1688.company import CompanyTask
-            return CompanyTask()
+            from fetcher.sites.alibaba1688.company import Alibaba1688CompanyTask
+            return Alibaba1688CompanyTask()
         raise KeyError(f"未知任务: {name!r}（可选: "
                        f"{', '.join(self.task_names())}）")
 
     # ---- 会话冷启动软着陆（原子 ColdStart 的默认实现） ----
 
     def cold_start(self, page, item, log=print) -> None:
         """新会话先逛店铺首页（或站点首页）留真实浏览轨迹，再进深链页。"""
         try:
             domain = item["domain"] if isinstance(item, dict) else getattr(
                 item, "domain", None)
diff --git a/fetcher/fetcher/sites/alibaba1688/company.py b/fetcher/fetcher/sites/alibaba1688/company.py
index e713367..8b536a0 100644
--- a/fetcher/fetcher/sites/alibaba1688/company.py
+++ b/fetcher/fetcher/sites/alibaba1688/company.py
@@ -1,23 +1,26 @@
 # -*- coding: utf-8 -*-
-"""1688 公司黄页采集任务（迁移 company_crawler.py 的 CompanyTask 全部行为）。
+"""1688 公司黄页采集任务（work_items 驱动 feeder 模式）。
 
 端点：s.1688.com/company/company_search.htm（「找供应商」公司黄页），
 直出「公司名 + 店铺域名」，无需从商品卡片内嵌 JSON 抠 shopAddition。
 进度：category_progress 表以 "company:" 前缀存储，与 shop 任务的
 商品搜索进度完全隔离。
+
+P3 Step 5.1：从 KeywordPool 进程内填池重构为 work_items 驱动
+feeder——与 Step 4.1 MadeInChinaShopTask 同模式。
 """
 
 from __future__ import annotations
 
+import json
 import random
-import threading
 import time
 
 from fetcher.control.task import Task
 from fetcher.core.errors import classify_error
 from fetcher.core.types import ActionResult, Outcome
 from fetcher.sites.alibaba1688.features import (
     HOMEPAGE,
     ensure_mtop_token,
     has_mtop_token,
 )
@@ -114,103 +117,93 @@ SEED_KEYWORDS = [
     ("美妆", "美妆"), ("个护", "个护"), ("食品", "食品"),
     ("茶叶", "茶叶"), ("酒水", "酒水"), ("玩具", "玩具"),
     ("母婴用品", "母婴用品"), ("宠物用品", "宠物用品"), ("运动户外", "运动户外"),
     ("汽车用品", "汽车用品"), ("办公文具", "办公文具"), ("包装", "包装"),
     ("工艺品", "工艺品"), ("珠宝首饰", "珠宝首饰"), ("眼镜", "眼镜"),
     ("手表", "手表"), ("雨伞", "雨伞"), ("厨房用品", "厨房用品"),
     ("卫浴", "卫浴"), ("建材", "建材"), ("机械", "机械"),
 ]
 
 
-class KeywordPool:
-    """关键词池：进程内共享，线程安全（与 CategoryPool 同思路）。"""
-
-    def __init__(self, exhausted: set):
-        self.lock = threading.Lock()
-        self.pool: dict = {}
-        self.in_progress: set = set()
-        self.exhausted: set = set(exhausted)
-
-    def pick(self) -> tuple[str, str] | None:
-        with self.lock:
-            candidates = [kw for kw in self.pool
-                          if kw not in self.exhausted
-                          and kw not in self.in_progress]
-            if not candidates:
-                return None
-            kw = random.choice(candidates)
-            self.in_progress.add(kw)
-            return kw, self.pool.get(kw) or kw
-
-    def release(self, keyword: str, exhausted: bool = False):
-        with self.lock:
-            self.in_progress.discard(keyword)
-            if exhausted:
-                self.exhausted.add(keyword)
-
-    def refresh(self, cats: list[dict]) -> int:
-        with self.lock:
-            n = 0
-            for c in cats:
-                kw = c.get("keyword")
-                if kw and kw not in self.pool:
-                    self.pool[kw] = c.get("name") or kw
-                    n += 1
-            return n
-
-    def available(self) -> int:
-        with self.lock:
-            return len([kw for kw in self.pool
-                        if kw not in self.exhausted
-                        and kw not in self.in_progress])
-
-
-class CompanyTask(Task):
-    """公司黄页采集任务：随机关键词 → 黄页 → 公司店铺域名入库。
-
-    任务项为 (keyword, name, page_no) 三元组；进度以 "company:" 前缀
-    存 category_progress，与商品搜索进度隔离。
+class Alibaba1688CompanyTask(Task):
+    """1688 公司黄页采集：work_items 驱动 + 单关键词黄页处理。
+
+    work_items payload：
+      - 类目页：{"kind":"category","keyword":"company:xxx","name":<name>}
+        keyword 天然带 "company:" 前缀；page_no 处理时读
+        category_progress.next_page
+      - 发现：{"kind":"discover"}
+        执行 = 首页类目提取 + mtop 握手 → 新类目逐条 INSERT category item
+        （keyword 带 "company:" 前缀）
+
+    链式续喂：category item on_success 后若未采完则 INSERT 下一页 item。
+    失败补插：refill_item 在 attempts 耗尽时补插同 payload 新 item。
     """
 
     name = "company"
     unit = "页"
     batch_unit = "店铺"
     cold_start_before_acquire = True
-    # 黄页与商品搜索同属 s.1688.com 搜索域，按同一预算保守处理：
-    # 每出口 IP 采满 12 页主动换 IP
     ip_request_budget = 12
 
-    def __init__(self):
-        self.kw_pool: KeywordPool | None = None
+    QUEUE = "crawl_1688_company"
+    SITE = "1688"
 
     # ---- main 阶段 ----
 
     def prepare(self, config) -> bool:
         from fetcher.db import ShopDB  # 延迟导入
         db = ShopDB(config.resolved_db_path())
         exhausted = {k[len(PROGRESS_PREFIX):]
                      for k in db.get_exhausted_keywords()
                      if k.startswith(PROGRESS_PREFIX)}
         if exhausted:
             print(f"[0] 黄页已采到末页的关键词 {len(exhausted)} 个，自动跳过")
-        self.kw_pool = KeywordPool(exhausted)
+        # 播种：活跃 company: 前缀类目逐条插 category item + 一条 discover
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
+        """活跃 company: 前缀类目逐条插 category item
+        （已有同 keyword pending 跳过）。"""
+        active = list(db.iter_active_categories(prefix=PROGRESS_PREFIX))
+        n = 0
+        for cat in active:
+            kw = cat["keyword"]  # 已带 "company:" 前缀
+            name = cat.get("name", kw)
+            if self._count_pending_by_kind(db, "category", kw) > 0:
+                continue
+            self._insert_work_item(db, {"kind": "category", "keyword": kw,
+                                         "name": name})
+            n += 1
+        return n
+
+    def _seed_discover_item(self, db) -> int:
+        """插一条 discover item（已有 pending discover 跳过）。"""
+        existing = self._count_pending_by_kind(db, "discover")
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
         return (f"本次黄页采集: {pages} 页, 店铺 {shops} 个（新增 {new}）"
                 f"\n    数据库统计: {stats}")
@@ -225,64 +218,87 @@ class CompanyTask(Task):
 
     def make_stats(self) -> dict:
         return {"shops": 0, "new": 0, "pages": 0}
 
     def rest_counter(self, stats: dict) -> int:
         return stats["pages"]
 
     # ---- worker 循环 ----
 
     def cold_start(self, ctx, item) -> None:
-        """新会话先逛 1688 首页留真实浏览轨迹，顺带提取首页类目填池。"""
-        cats = fetch_homepage_categories(ctx.page)
-        if not cats:
-            cats = [{"name": n, "keyword": k} for n, k in SEED_KEYWORDS]
-            ctx.log(f"[!] 首页类目提取失败，"
-                    f"使用内置种子关键词（{len(cats)} 个）")
-        n = self.kw_pool.refresh(cats)
-        if n:
-            ctx.log(f"黄页关键词池新增 {n} 个"
-                    f"（可采 {self.kw_pool.available()}，"
-                    f"跳过已采完 {len(self.kw_pool.exhausted)}）")
-        if not ensure_mtop_token(ctx.page, log=ctx.log):
-            ctx.log("[!] mtop 握手未拿到 _m_h5_tk，本会话黄页采集将被搁置"
-                    "（fetch 逐页重试握手，仍无令牌则按风控换 IP）")
+        """新会话先逛 1688 首页留真实浏览轨迹（纯软着陆，不提取类目）。
+
+        类目提取归 discover item 的 on_success 处理。
+        """
+        try:
+            ctx.page.goto(HOMEPAGE, wait_until="domcontentloaded",
+                          timeout=60000)
+            time.sleep(random.uniform(2.0, 4.0))
+        except Exception:  # noqa: BLE001
+            ctx.log("[!] 冷启动浏览失败，继续认领工作项")
 
     def acquire_item(self, ctx):
-        picked = self.kw_pool.pick()
-        if not picked:
+        """从 work_items 队列认领（CLI 与 daemon 同一路径）。"""
+        consumer_id = f"w{ctx.wid}"
+        db = ctx.store.db
+        item = db.claim_next_eligible([self.QUEUE], consumer_id)
+        if item is None:
             return None
-        keyword, name = picked
-        prog = ctx.store.db.get_category_progress(PROGRESS_PREFIX + keyword)
-        page_no = prog["next_page"] if prog else 1
-        return (keyword, name, page_no)
+        payload = dict(item["payload"])
+        payload["id"] = item["id"]
+        return payload
 
     def label(self, item) -> str:
-        return f"{item[1]} p{item[2]}"
+        kind = item.get("kind", "")
+        if kind == "discover":
+            return "discover"
+        kw = item.get("keyword", "?")
+        # 显示时去掉 company: 前缀
+        name = item.get("name", kw)
+        return f"{name}"
 
     def fetch(self, ctx, item) -> ActionResult:
-        """抓取一页公司黄页，提取「公司名 + 店铺域名」列表。"""
+        """按 kind 分派：category → 抓黄页，discover → 返回标记。"""
+        kind = item.get("kind", "")
+        if kind == "discover":
+            return ActionResult(Outcome.OK, "discover", {"discover": True})
+        if kind == "category":
+            return self._fetch_category(ctx, item)
+        return ActionResult.fatal(f"未知 kind: {kind}")
+
+    def _fetch_category(self, ctx, item) -> ActionResult:
+        """抓取一页公司黄页，提取「公司名 + 店铺域名」列表。
+
+        page_no 从 category_progress 运行时读（单一事实来源）。
+        keyword 已带 PROGRESS_PREFIX；fetch URL 需要去掉前缀裸关键词。
+        """
         page = ctx.page
-        keyword, _name, page_no = item
-        url = build_company_url(keyword, page_no)
+        db = ctx.store.db
+        full_keyword = item["keyword"]  # "company:女装"
+        # 进度键带前缀
+        prog = db.get_category_progress(full_keyword)
+        page_no = prog["next_page"] if prog else 1
+        # URL 使用裸关键词（去掉 company: 前缀）
+        raw_kw = full_keyword
+        if raw_kw.startswith(PROGRESS_PREFIX):
+            raw_kw = raw_kw[len(PROGRESS_PREFIX):]
+        url = build_company_url(raw_kw, page_no)
         try:
-            # 无 mtop 令牌不碰黄页（无令牌裸奔 = 首请求即踢登录墙）
             if not has_mtop_token(page) and not ensure_mtop_token(page):
                 return ActionResult.blocked(
                     "会话缺少 mtop 令牌（_m_h5_tk），搜索域入场券未获取，"
                     "未触碰黄页")
             referer = (HOMEPAGE if page_no <= 1
-                       else build_company_url(keyword, page_no - 1))
+                       else build_company_url(raw_kw, page_no - 1))
             page.goto(url, wait_until="domcontentloaded", timeout=60000,
                       referer=referer)
             time.sleep(random.uniform(1.0, 2.0))
-            # 等企业卡片渲染就绪（轮询，不加重风控）
             deadline = time.monotonic() + 15.0
             while time.monotonic() < deadline:
                 try:
                     if page.evaluate(_JS_CARDS_READY):
                         break
                 except Exception:  # noqa: BLE001
                     break
                 time.sleep(1.0)
             time.sleep(random.uniform(1.5, 3.0))
             result = page.evaluate(_JS_EXTRACT_COMPANIES) or {}
@@ -297,59 +313,162 @@ class CompanyTask(Task):
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
-        """结构化校验：结果必须含 shops 列表（空列表 = 采到末页，合法）。"""
+        """结构化校验：discover → 检查 discover 标记；category → shops 列表。"""
+        if item.get("kind") == "discover":
+            return isinstance((result.data or {}).get("discover"), bool)
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
+        """discover 成功：首页类目提取 + mtop 握手 → 新类目逐条 INSERT
+        category item（keyword 带 company: 前缀）。"""
+        db = ctx.store.db
+        page = ctx.page
+        # mtop 握手
+        if not ensure_mtop_token(page, log=ctx.log):
+            ctx.log("[!] discover mtop 握手未拿到 _m_h5_tk，"
+                    "后续黄页采集将被搁置")
+        # 提取首页类目
+        cats = fetch_homepage_categories(page)
+        if not cats:
+            cats = [{"name": n, "keyword": k} for k, n in SEED_KEYWORDS]
+            ctx.log(f"[!] 首页类目提取失败，"
+                    f"使用内置种子关键词（{len(cats)} 个）")
+        n = 0
+        for c in cats:
+            prefixed_kw = PROGRESS_PREFIX + c["keyword"]
+            # 跳过已 exhausted
+            prog = db.get_category_progress(prefixed_kw)
+            if prog and prog.get("exhausted"):
+                continue
+            # 跳过已有同 keyword pending category item
+            if self._count_pending_by_kind(db, "category", prefixed_kw) > 0:
+                continue
+            self._insert_work_item(
+                db,
+                {"kind": "category", "keyword": prefixed_kw,
+                 "name": c.get("name", c["keyword"])})
+            n += 1
+        if n:
+            ctx.log(f"discover 产出 {n} 个新类目 category item"
+                    f"（company: 前缀）")
+        return 0  # discover 不计入页数
+
+    def _on_category_success(self, ctx, item, result: ActionResult) -> int:
+        """category 成功：入库 shops → 链式续喂。
+        company 落库逻辑与 shop 一致（upsert_shops 到 shops 表）。"""
         db = ctx.store.db
         stats = ctx.state["task"]["stats"]
-        keyword, name, page_no = item
+        full_keyword = item["keyword"]  # "company:女装"
+        cat_name = item.get("name", full_keyword)
+        prog = db.get_category_progress(full_keyword)
+        page_no = prog["next_page"] if prog else 1
         page_shops = result.data["shops"]
         has_more = result.data["has_more"]
-        run_id = db.start_run(name, PROGRESS_PREFIX + keyword)
+        run_id = db.start_run(cat_name, full_keyword)
         n_new = db.upsert_shops(page_shops, run_id=run_id,
-                                category_keyword=keyword)
+                                category_keyword=full_keyword)
         db.finish_run(run_id, shops_found=len(page_shops),
                       shops_picked=n_new, note=f"company page={page_no}")
         if not page_shops or not has_more:
-            db.mark_category_exhausted(PROGRESS_PREFIX + keyword, name)
-            ctx.state["task"]["exhausted"] = True
-            ctx.set_status(state=f"■ {name} 采到末页，标记 exhausted")
-            ctx.log(f"■ 关键词 {name} 第 {page_no} 页 "
+            db.mark_category_exhausted(full_keyword, cat_name)
+            ctx.set_status(state=f"■ {cat_name} 采到末页，标记 exhausted")
+            ctx.log(f"■ 关键词 {cat_name} 第 {page_no} 页 "
                     f"{len(page_shops)} 店，hasMore={has_more}，"
                     f"采到末页标记 exhausted")
         else:
-            db.advance_category_page(PROGRESS_PREFIX + keyword, name,
+            db.advance_category_page(full_keyword, cat_name,
                                      shops_found=len(page_shops))
             ctx.set_status(state=f"✓ {len(page_shops)} 店（新 {n_new}）")
         stats["shops"] += len(page_shops)
         stats["new"] += n_new
         stats["pages"] += 1
         ctx.set_status(n=stats["shops"], new=stats["new"],
                        pages=stats["pages"])
+        # 链式续喂
+        if not page_shops or not has_more:
+            pass  # exhausted，不续喂
+        else:
+            payload = {"kind": "category", "keyword": full_keyword,
+                       "name": cat_name}
+            self._insert_work_item(db, payload)
         return len(page_shops)
 
     def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
         return "跳过该页，页码不前进下次重采"
 
     def on_abort(self, ctx, item) -> str:
-        return (f"关键词 {item[0]} 第 {item[2]} 页页码不前进，"
-                f"下次运行自动续采")
+        kw = item.get("keyword", "?")
+        return f"关键词 {kw} 页码不前进，下次运行自动续采"
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
+                       "name": item.get("name", item["keyword"])}
+            self._insert_work_item(db, payload)
+            ctx.log(f"[refill] 关键词 {item.get('keyword')} 补插 category item")
+        elif kind == "discover":
+            self._insert_work_item(db, {"kind": "discover"})
+            ctx.log("[refill] 补插 discover item")
 
     def after_item(self, ctx, item) -> None:
-        self.kw_pool.release(item[0],
-                             exhausted=ctx.state["task"].pop("exhausted",
-                                                             False))
+        pass
 
     def empty_message(self) -> str:
-        return "没有可采的关键词了（全部采完或被占用）"
+        return "没有待认领的 work_item 了"
+
+    # ---- work_items 辅助 ----
+
+    def _insert_work_item(self, db, payload: dict) -> int:
+        """向 work_items 插 pending 行，返回 id。"""
+        cur = db.conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, created_at)"
+            " VALUES (?, ?, ?, datetime('now','localtime'))",
+            (self.QUEUE, self.SITE, json.dumps(payload, ensure_ascii=False)))
+        db.conn.commit()
+        return cur.lastrowid
+
+    def _count_pending_by_kind(self, db, kind: str, keyword: str = None) -> int:
+        """统计同 kind（+可选 keyword）的 pending item 数量。"""
+        if keyword is not None:
+            return db.conn.execute(
+                "SELECT COUNT(*) FROM work_items WHERE queue=?"
+                " AND status='pending'"
+                " AND json_extract(payload_json, '$.kind')=?"
+                " AND json_extract(payload_json, '$.keyword')=?",
+                (self.QUEUE, kind, keyword)).fetchone()[0]
+        return db.conn.execute(
+            "SELECT COUNT(*) FROM work_items WHERE queue=?"
+            " AND status='pending'"
+            " AND json_extract(payload_json, '$.kind')=?",
+            (self.QUEUE, kind)).fetchone()[0]
+
+
+# 向后兼容别名（P3 Step 5.1 重构前后兼容）
+CompanyTask = Alibaba1688CompanyTask
diff --git a/fetcher/fetcher/sites/alibaba1688/shop.py b/fetcher/fetcher/sites/alibaba1688/shop.py
index 54cf09a..ad86270 100644
--- a/fetcher/fetcher/sites/alibaba1688/shop.py
+++ b/fetcher/fetcher/sites/alibaba1688/shop.py
@@ -1,30 +1,33 @@
 # -*- coding: utf-8 -*-
-"""1688 店铺 URL 采集任务（迁移 shop_crawler.py 的 ShopTask 全部行为）。
+"""1688 店铺 URL 采集任务（work_items 驱动 feeder 模式）。
 
 任务内容：从 1688 首页提取类目入口（类目 = 关键词搜索页），随机挑
 类目翻页采集：搜索结果页内嵌数据（window.data.offerV2...OFFER.items）
 自带商家信息，无需点进商品详情页，直接解析店铺域名入库 shops 表
 （status=pending），供 contact 任务消费。
 
 进度：每个类目的 next_page 记在 category_progress；空页或
 hasMore=false 标记 exhausted 之后跳过；抓取失败页码不前进。
 
 与旧版的有意差异：抓取内不再就地自动过证（统一由 SolveSlider 策略
 处置）；mtop 握手缺失时 fetch 自报 BLOCKED（不触碰搜索），控制层
 按风控场景处置 —— 行为等价。
+
+P3 Step 5.1：从 CategoryPool 进程内填池重构为 work_items 驱动
+feeder——与 Step 4.1 MadeInChinaShopTask 同模式。
 """
 
 from __future__ import annotations
 
+import json
 import random
-import threading
 import time
 
 from fetcher.control.task import Task
 from fetcher.core.errors import classify_error
 from fetcher.core.types import ActionResult, Outcome
 from fetcher.sites.alibaba1688.features import (
     HOMEPAGE,
     ensure_mtop_token,
     has_mtop_token,
 )
@@ -117,105 +120,96 @@ SEED_CATEGORIES = [
     ("美妆", "美妆"), ("个护", "个护"), ("食品", "食品"),
     ("茶叶", "茶叶"), ("酒水", "酒水"), ("玩具", "玩具"),
     ("母婴用品", "母婴用品"), ("宠物用品", "宠物用品"), ("运动户外", "运动户外"),
     ("汽车用品", "汽车用品"), ("办公文具", "办公文具"), ("包装", "包装"),
     ("工艺品", "工艺品"), ("珠宝首饰", "珠宝首饰"), ("眼镜", "眼镜"),
     ("手表", "手表"), ("雨伞", "雨伞"), ("厨房用品", "厨房用品"),
     ("卫浴", "卫浴"), ("建材", "建材"), ("机械", "机械"),
 ]
 
 
-class CategoryPool:
-    """类目池：进程内共享，线程安全（相当于 contact 的 shops pending
-    队列，只是队列在内存里、页码进度在 category_progress 表里）。"""
-
-    def __init__(self, exhausted: set):
-        self.lock = threading.Lock()
-        self.pool: dict = {}
-        self.in_progress: set = set()
-        self.exhausted: set = set(exhausted)
-
-    def pick(self) -> tuple[str, str] | None:
-        """随机挑一个可采类目并占用；无可采类目返回 None。"""
-        with self.lock:
-            candidates = [kw for kw in self.pool
-                          if kw not in self.exhausted
-                          and kw not in self.in_progress]
-            if not candidates:
-                return None
-            kw = random.choice(candidates)
-            self.in_progress.add(kw)
-            return kw, self.pool.get(kw) or kw
-
-    def release(self, keyword: str, exhausted: bool = False):
-        with self.lock:
-            self.in_progress.discard(keyword)
-            if exhausted:
-                self.exhausted.add(keyword)
-
-    def refresh(self, cats: list[dict]) -> int:
-        """合并首页提取到的类目，返回新增数量。"""
-        with self.lock:
-            n = 0
-            for c in cats:
-                kw = c.get("keyword")
-                if kw and kw not in self.pool:
-                    self.pool[kw] = c.get("name") or kw
-                    n += 1
-            return n
-
-    def available(self) -> int:
-        with self.lock:
-            return len([kw for kw in self.pool
-                        if kw not in self.exhausted
-                        and kw not in self.in_progress])
-
-
-class ShopTask(Task):
-    """店铺 URL 采集任务：随机类目 → 搜索页 → 店铺域名入库。
-
-    任务项为 (keyword, cat_name, page_no) 三元组；类目占用与 exhausted
-    由 CategoryPool 管，页码进度由 category_progress 表管。
+class Alibaba1688ShopTask(Task):
+    """1688 店铺 URL 采集：work_items 驱动 + 单类目搜索页处理。
+
+    work_items payload：
+      - 类目页：{"kind":"category","keyword":<keyword>,"name":<cat_name>}
+        page_no 不进 payload——处理时读 category_progress.next_page
+      - 发现：{"kind":"discover"}
+        执行 = 首页类目提取 + mtop 握手 → 新类目逐条 INSERT category item
+
+    链式续喂：category item on_success 后若未采完则 INSERT 下一页 item
+    （同 payload，attempts=0）；hasMore 判定 exhaust。
+    失败补插：refill_item 在 attempts 耗尽时补插同 payload 新 item。
     """
 
     name = "shop"
     unit = "页"
     batch_unit = "店铺"
-    # 冷启动要先逛首页提取类目填满类目池，必须在 acquire（选类目）之前
+    # 冷启动要先逛首页（软着陆），必须在 acquire 之前
     cold_start_before_acquire = True
     # 搜索页匿名配额墙实测阈值 18~26 页：每出口 IP 采满 12 个搜索页
     # 请求即主动换 IP，把「被配额墙踢掉」变成「主动全身而退」
     ip_request_budget = 12
 
-    def __init__(self):
-        self.cat_pool: CategoryPool | None = None
+    QUEUE = "crawl_1688_shop"
+    SITE = "1688"
 
     # ---- main 阶段 ----
 
     def prepare(self, config) -> bool:
         from fetcher.db import ShopDB  # 延迟导入
         db = ShopDB(config.resolved_db_path())
         exhausted = db.get_exhausted_keywords()
         if exhausted:
             print(f"[0] 已采到末页的类目 {len(exhausted)} 个，自动跳过")
-        self.cat_pool = CategoryPool(exhausted)
+        # 播种：活跃类目逐条插 category item + 一条 discover item
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
+        """活跃类目逐条插 category item（已有同 keyword pending 跳过）。
+
+        iter_active_categories 取全量未采完类目（无拼音过滤——
+        1688 中文/英文关键词都算）。
+        """
+        active = list(db.iter_active_categories())
+        n = 0
+        for cat in active:
+            kw = cat["keyword"]
+            name = cat.get("name", kw)
+            if self._count_pending_by_kind(db, "category", kw) > 0:
+                continue
+            self._insert_work_item(db, {"kind": "category", "keyword": kw,
+                                         "name": name})
+            n += 1
+        return n
+
+    def _seed_discover_item(self, db) -> int:
+        """插一条 discover item（已有 pending discover 跳过）。"""
+        existing = self._count_pending_by_kind(db, "discover")
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
@@ -230,64 +224,81 @@ class ShopTask(Task):
 
     def make_stats(self) -> dict:
         return {"shops": 0, "new": 0, "pages": 0}
 
     def rest_counter(self, stats: dict) -> int:
         return stats["pages"]
 
     # ---- worker 循环 ----
 
     def cold_start(self, ctx, item) -> None:
-        """新会话先逛 1688 首页留真实浏览轨迹，顺带提取首页类目填池。"""
-        cats = fetch_homepage_categories(ctx.page)
-        if not cats:
-            cats = [{"name": n, "keyword": k} for n, k in SEED_CATEGORIES]
-            ctx.log(f"[!] 首页类目提取失败，使用内置种子类目（{len(cats)} 个）")
-        n = self.cat_pool.refresh(cats)
-        if n:
-            ctx.log(f"类目池新增 {n} 个类目（可采 {self.cat_pool.available()}，"
-                    f"跳过已采完 {len(self.cat_pool.exhausted)}）")
-        # mtop 握手：搜索页数据走 mtop API，须持有 _m_h5_tk 再碰 offer_search
-        if not ensure_mtop_token(ctx.page, log=ctx.log):
-            ctx.log("[!] mtop 握手未拿到 _m_h5_tk，本会话搜索采集将被搁置"
-                    "（fetch 逐页重试握手，仍无令牌则按风控换 IP）")
+        """新会话先逛 1688 首页留真实浏览轨迹（纯软着陆，不提取类目）。
+
+        类目提取归 discover item 的 on_success 处理。
+        """
+        try:
+            ctx.page.goto(HOMEPAGE, wait_until="domcontentloaded",
+                          timeout=60000)
+            time.sleep(random.uniform(2.0, 4.0))
+        except Exception:  # noqa: BLE001
+            ctx.log("[!] 冷启动浏览失败，继续认领工作项")
 
     def acquire_item(self, ctx):
-        picked = self.cat_pool.pick()
-        if not picked:
+        """从 work_items 队列认领（CLI 与 daemon 同一路径）。"""
+        consumer_id = f"w{ctx.wid}"
+        db = ctx.store.db
+        item = db.claim_next_eligible([self.QUEUE], consumer_id)
+        if item is None:
             return None
-        keyword, cat_name = picked
-        prog = ctx.store.db.get_category_progress(keyword)
-        page_no = prog["next_page"] if prog else 1
-        return (keyword, cat_name, page_no)
+        payload = dict(item["payload"])
+        payload["id"] = item["id"]
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
-        """抓取一页类目搜索结果，提取商家店铺列表。"""
+        """按 kind 分派：category → 抓搜索页，discover → 返回标记。"""
+        kind = item.get("kind", "")
+        if kind == "discover":
+            return ActionResult(Outcome.OK, "discover", {"discover": True})
+        if kind == "category":
+            return self._fetch_category(ctx, item)
+        return ActionResult.fatal(f"未知 kind: {kind}")
+
+    def _fetch_category(self, ctx, item) -> ActionResult:
+        """抓取一页类目搜索结果，提取商家店铺列表。
+
+        page_no 从 category_progress 运行时读（单一事实来源）。
+        """
         page = ctx.page
-        keyword, _cat_name, page_no = item
+        db = ctx.store.db
+        keyword = item["keyword"]
+        name = item.get("name", keyword)
+        prog = db.get_category_progress(keyword)
+        page_no = prog["next_page"] if prog else 1
         url = build_search_url(keyword, page_no)
         try:
-            # 无 mtop 令牌不碰搜索（无令牌裸奔 = 首请求即踢登录墙，白烧 IP）
             if not has_mtop_token(page) and not ensure_mtop_token(page):
                 return ActionResult.blocked(
                     "会话缺少 mtop 令牌（_m_h5_tk），搜索域入场券未获取，"
                     "未触碰搜索")
-            # referer 链条：第 1 页来自首页，第 N 页来自第 N-1 页搜索页
             referer = (HOMEPAGE if page_no <= 1
                        else build_search_url(keyword, page_no - 1))
             page.goto(url, wait_until="domcontentloaded", timeout=60000,
                       referer=referer)
             time.sleep(random.uniform(1.0, 2.0))
-            # 等异步搜索结果数据就绪（轮询，不加重风控）
             deadline = time.monotonic() + 15.0
             while time.monotonic() < deadline:
                 try:
                     if page.evaluate(_JS_DATA_READY):
                         break
                 except Exception:  # noqa: BLE001
                     break
                 time.sleep(1.0)
             time.sleep(random.uniform(1.5, 3.0))
             result = page.evaluate(_JS_EXTRACT_SHOPS) or {}
@@ -312,62 +323,161 @@ class ShopTask(Task):
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
-        """结构化校验：结果必须含 shops 列表（空列表 = 采到末页，合法）。"""
+        """结构化校验：discover → 检查 discover 标记；category → shops 列表。"""
+        if item.get("kind") == "discover":
+            return isinstance((result.data or {}).get("discover"), bool)
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
+        """discover 成功：首页类目提取 + mtop 握手 → 新类目逐条 INSERT
+        category item。"""
+        db = ctx.store.db
+        page = ctx.page
+        # mtop 握手（搜索域入场券）
+        if not ensure_mtop_token(page, log=ctx.log):
+            ctx.log("[!] discover mtop 握手未拿到 _m_h5_tk，"
+                    "后续搜索采集将被搁置")
+        # 提取首页类目
+        cats = fetch_homepage_categories(page)
+        if not cats:
+            cats = [{"name": n, "keyword": k} for k, n in SEED_CATEGORIES]
+            ctx.log(f"[!] 首页类目提取失败，"
+                    f"使用内置种子类目（{len(cats)} 个）")
+        n = 0
+        for c in cats:
+            kw = c["keyword"]
+            # 跳过已 exhausted
+            prog = db.get_category_progress(kw)
+            if prog and prog.get("exhausted"):
+                continue
+            # 跳过已有同 keyword pending category item
+            if self._count_pending_by_kind(db, "category", kw) > 0:
+                continue
+            self._insert_work_item(
+                db,
+                {"kind": "category", "keyword": kw,
+                 "name": c.get("name", kw)})
+            n += 1
+        if n:
+            ctx.log(f"discover 产出 {n} 个新类目 category item")
+        return 0  # discover 不计入页数
+
+    def _on_category_success(self, ctx, item, result: ActionResult) -> int:
+        """category 成功：入库 shops → 链式续喂。1688 用 hasMore/空页
+        判 exhausted（无 ZERO_NEW_LIMIT 保护）。"""
         db = ctx.store.db
         stats = ctx.state["task"]["stats"]
-        keyword, cat_name, page_no = item
+        keyword = item["keyword"]
+        cat_name = item.get("name", keyword)
+        prog = db.get_category_progress(keyword)
+        page_no = prog["next_page"] if prog else 1
         page_shops = result.data["shops"]
         has_more = result.data["has_more"]
         run_id = db.start_run(cat_name, keyword)
         n_new = db.upsert_shops(page_shops, run_id=run_id,
                                 category_keyword=keyword)
         db.finish_run(run_id, shops_found=len(page_shops),
                       shops_picked=n_new, note=f"page={page_no}")
         if not page_shops or not has_more:
-            # 空页或官方说没有下一页：该类目采到末页
             db.mark_category_exhausted(keyword, cat_name)
-            ctx.state["task"]["exhausted"] = True  # after_item 顺手标记
             ctx.set_status(state=f"■ {cat_name} 采到末页，标记 exhausted")
             ctx.log(f"■ 类目 {cat_name} 第 {page_no} 页 "
                     f"{len(page_shops)} 店，hasMore={has_more}，"
                     f"采到末页标记 exhausted")
         else:
             db.advance_category_page(keyword, cat_name,
                                      shops_found=len(page_shops))
             ctx.set_status(state=f"✓ {len(page_shops)} 店（新 {n_new}）")
         stats["shops"] += len(page_shops)
         stats["new"] += n_new
         stats["pages"] += 1
         ctx.set_status(n=stats["shops"], new=stats["new"],
                        pages=stats["pages"])
-        return len(page_shops)  # 批次配额按提取到的店铺数计
+        # 链式续喂：未采完则 INSERT 下一页 item
+        if not page_shops or not has_more:
+            pass  # exhausted，不续喂
+        else:
+            payload = {"kind": "category", "keyword": keyword,
+                       "name": cat_name}
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
+                       "name": item.get("name", item["keyword"])}
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
+    def _insert_work_item(self, db, payload: dict) -> int:
+        """向 work_items 插 pending 行，返回 id。"""
+        cur = db.conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, created_at)"
+            " VALUES (?, ?, ?, datetime('now','localtime'))",
+            (self.QUEUE, self.SITE, json.dumps(payload, ensure_ascii=False)))
+        db.conn.commit()
+        return cur.lastrowid
+
+    def _count_pending_by_kind(self, db, kind: str, keyword: str = None) -> int:
+        """统计同 kind（+可选 keyword）的 pending item 数量。"""
+        if keyword is not None:
+            return db.conn.execute(
+                "SELECT COUNT(*) FROM work_items WHERE queue=?"
+                " AND status='pending'"
+                " AND json_extract(payload_json, '$.kind')=?"
+                " AND json_extract(payload_json, '$.keyword')=?",
+                (self.QUEUE, kind, keyword)).fetchone()[0]
+        return db.conn.execute(
+            "SELECT COUNT(*) FROM work_items WHERE queue=?"
+            " AND status='pending'"
+            " AND json_extract(payload_json, '$.kind')=?",
+            (self.QUEUE, kind)).fetchone()[0]
+
+
+# 向后兼容别名（P3 Step 5.1 重构前后兼容）
+ShopTask = Alibaba1688ShopTask
diff --git a/fetcher/tests/test_1688_feeder.py b/fetcher/tests/test_1688_feeder.py
new file mode 100644
index 0000000..327ee44
--- /dev/null
+++ b/fetcher/tests/test_1688_feeder.py
@@ -0,0 +1,1072 @@
+# -*- coding: utf-8 -*-
+"""P3 Step 5.1: 1688 shop/company feeder 任务拆分（work_items 驱动）测试。
+
+TDD 覆盖：链式续喂、discover 产出（含 mtop 握手）、company: 前缀隔离、
+失败补插、幂等播种、CLI acquire、validate discover 放行。
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
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.sites.alibaba1688.shop import (
+    Alibaba1688ShopTask,
+    build_search_url,
+    fetch_homepage_categories,
+    SEED_CATEGORIES,
+)
+from fetcher.sites.alibaba1688.company import (
+    Alibaba1688CompanyTask,
+    PROGRESS_PREFIX,
+    SEED_KEYWORDS,
+)
+
+from tests.test_control_loop import FakePage
+
+SHOP_QUEUE = "crawl_1688_shop"
+COMPANY_QUEUE = "crawl_1688_company"
+SITE = "1688"
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
+    return ctx
+
+
+def _insert_work_item(db: ShopDB, payload: dict, queue=SHOP_QUEUE) -> int:
+    """直接向 work_items 插 pending 行，返回 id。"""
+    cur = db.conn.execute(
+        "INSERT INTO work_items (queue, site, payload_json, created_at)"
+        " VALUES (?, ?, ?, datetime('now', 'localtime'))",
+        (queue, SITE, json.dumps(payload, ensure_ascii=False)))
+    db.conn.commit()
+    return cur.lastrowid
+
+
+def _cat_payload(keyword="女装", name="女装"):
+    return {"kind": "category", "keyword": keyword, "name": name}
+
+
+def _company_cat_payload(keyword="company:女装", name="女装"):
+    return {"kind": "category", "keyword": keyword, "name": name}
+
+
+def _discover_payload():
+    return {"kind": "discover"}
+
+
+def _pending_items(db, queue=SHOP_QUEUE):
+    """返回 queue 的 pending 工作项列表。"""
+    rows = db.conn.execute(
+        "SELECT id, payload_json FROM work_items WHERE queue=? "
+        "AND status='pending' ORDER BY id", (queue,)).fetchall()
+    return [(r["id"], json.loads(r["payload_json"])) for r in rows]
+
+
+def _pending_kind_count(db, kind, queue=SHOP_QUEUE, keyword=None):
+    """统计特定 kind 的 pending 数量。"""
+    if keyword is not None:
+        return db.conn.execute(
+            "SELECT COUNT(*) FROM work_items WHERE queue=?"
+            " AND status='pending'"
+            " AND json_extract(payload_json, '$.kind')=?"
+            " AND json_extract(payload_json, '$.keyword')=?",
+            (queue, kind, keyword)).fetchone()[0]
+    return db.conn.execute(
+        "SELECT COUNT(*) FROM work_items WHERE queue=?"
+        " AND status='pending'"
+        " AND json_extract(payload_json, '$.kind')=?",
+        (queue, kind)).fetchone()[0]
+
+
+class Shop1688Page(FakePage):
+    """1688 搜索页假页面（shop fetch 用）。"""
+
+    def __init__(self, shops=None, has_more=False, url=None):
+        super().__init__()
+        self.url = url or build_search_url("女装", 1)
+        self._shops = shops or []
+        self._has_more = has_more
+        self.goto_calls = []
+        self._evaluate_js_calls = []
+
+    def evaluate(self, js):
+        self._evaluate_js_calls.append(js[:80])
+        if "window.data" in js and "offerV2" in js:
+            items = []
+            for s in self._shops:
+                domain = s.get("domain", "")
+                items.append({
+                    "shopUrl": f"https://{domain}" if domain else "",
+                    "name": s.get("name", ""),
+                    "loginId": domain.split(".")[0] if domain else "",
+                })
+            return {
+                "hasMore": "true" if self._has_more else "false",
+                "found": str(len(items)),
+                "items": items,
+            }
+        return ""
+
+    def goto(self, url, **kw):
+        self.goto_calls.append((url, kw))
+        self.url = url
+
+
+class Company1688Page(FakePage):
+    """1688 黄页假页面（company fetch 用）。"""
+
+    def __init__(self, shops=None, has_more=False, cards_count=None, url=None):
+        super().__init__()
+        self.url = url or "https://s.1688.com/company/company_search.htm"
+        self._shops = shops or []
+        self._has_more = has_more
+        self._cards_count = cards_count if cards_count is not None else len(shops or [])
+        self.goto_calls = []
+        self._evaluate_js_calls = []
+
+    def evaluate(self, js):
+        self._evaluate_js_calls.append(js[:80])
+        # _JS_CARDS_READY: single expression, no "SKIP" / "const"
+        if "length > 0" in js and "SKIP" not in js:
+            return self._cards_count > 0
+        # _JS_EXTRACT_COMPANIES: contains "SKIP" declaration + querySelectorAll
+        if "SKIP" in js:
+            items = [{"domain": s.get("domain", ""), "name": s.get("name", "")}
+                     for s in self._shops]
+            return {"items": items, "hasMore": self._has_more,
+                    "cards": self._cards_count}
+        return ""
+
+    def goto(self, url, **kw):
+        self.goto_calls.append((url, kw))
+        self.url = url
+
+
+# =====================================================================
+# 1. 链式续喂（1688 shop）
+# =====================================================================
+
+class ChainFeedShopTest(unittest.TestCase):
+    """category on_success → advance + INSERT 下一页 item 或 exhausted。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "c.db")
+        self.task = Alibaba1688ShopTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_chain_feed_inserts_next_page_item(self):
+        """有新增店铺 + hasMore → advance + 新 work_item。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        item = _cat_payload("女装", "女装")
+        result = ok_result({
+            "shops": [{"domain": "newshop.1688.com", "name": "新店", "url": "https://newshop.1688.com"}],
+            "has_more": True,
+        })
+
+        count = self.task.on_success(ctx, item, result)
+        self.assertEqual(count, 1)
+
+        # 页码前进
+        prog = self.db.get_category_progress("女装")
+        self.assertIsNotNone(prog)
+        self.assertEqual(prog["next_page"], 2)
+        self.assertEqual(prog["pages_crawled"], 1)
+
+        # 新 work_item 插入（同 payload，attempts=0）
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], _cat_payload("女装", "女装"))
+
+    def test_chain_feed_exhausted_when_no_shops(self):
+        """空页 → mark_category_exhausted → 不插下一页 item。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        item = _cat_payload("女装", "女装")
+        result = ok_result({"shops": [], "has_more": False})
+
+        self.task.on_success(ctx, item, result)
+
+        # exhausted
+        self.assertIn("女装", self.db.get_exhausted_keywords())
+        # 无新 work_item
+        self.assertEqual(len(_pending_items(self.db)), 0)
+
+    def test_chain_feed_exhausted_when_no_has_more(self):
+        """hasMore=false → mark_category_exhausted → 不插下一页 item。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        item = _cat_payload("女装", "女装")
+        result = ok_result({
+            "shops": [{"domain": "shop1.1688.com", "name": "店1", "url": "https://shop1.1688.com"}],
+            "has_more": False,
+        })
+
+        self.task.on_success(ctx, item, result)
+
+        self.assertIn("女装", self.db.get_exhausted_keywords())
+        self.assertEqual(len(_pending_items(self.db)), 0)
+
+    def test_chain_feed_continues_when_has_more_and_shops(self):
+        """有店铺 + hasMore=true → 不标记 exhausted，链式续喂。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        item = _cat_payload("女装", "女装")
+        result = ok_result({
+            "shops": [{"domain": "shop1.1688.com", "name": "店1", "url": "https://shop1.1688.com"}],
+            "has_more": True,
+        })
+
+        self.task.on_success(ctx, item, result)
+
+        self.assertNotIn("女装", self.db.get_exhausted_keywords())
+        self.assertEqual(len(_pending_items(self.db)), 1)  # 链式续喂 1 条
+
+
+# =====================================================================
+# 2. 链式续喂（1688 company）
+# =====================================================================
+
+class ChainFeedCompanyTest(unittest.TestCase):
+    """company category on_success → advance + INSERT 下一页 item
+    （使用 company: 前缀进度键）。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "cc.db")
+        self.task = Alibaba1688CompanyTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_company_chain_feed_inserts_next_page(self):
+        """有新增店铺 + hasMore → advance（company: 前缀）+ 新 work_item。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        item = _company_cat_payload("company:女装", "女装")
+        result = ok_result({
+            "shops": [{"domain": "newshop.1688.com", "name": "新店", "url": "https://newshop.1688.com"}],
+            "has_more": True,
+        })
+
+        count = self.task.on_success(ctx, item, result)
+        self.assertEqual(count, 1)
+
+        # 页码前进（company: 前缀进度键）
+        prog = self.db.get_category_progress("company:女装")
+        self.assertIsNotNone(prog)
+        self.assertEqual(prog["next_page"], 2)
+
+        # 新 work_item（crawl_1688_company 队列）
+        items = _pending_items(self.db, queue=COMPANY_QUEUE)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], _company_cat_payload("company:女装", "女装"))
+
+    def test_company_chain_feed_exhausted_when_empty(self):
+        """空页 → 标记 exhausted（company: 前缀进度键）→ 不插。"""
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        item = _company_cat_payload("company:女装", "女装")
+        result = ok_result({"shops": [], "has_more": False})
+
+        self.task.on_success(ctx, item, result)
+
+        self.assertIn("company:女装", self.db.get_exhausted_keywords())
+        self.assertEqual(len(_pending_items(self.db, queue=COMPANY_QUEUE)), 0)
+
+
+# =====================================================================
+# 3. discover 产出（1688 shop）——含 mtop 握手
+# =====================================================================
+
+class DiscoverShopTest(unittest.TestCase):
+    """discover on_success → 首页类目提取 + mtop 握手 → 新类目逐条
+    INSERT category item。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "d.db")
+        self.task = Alibaba1688ShopTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
+           return_value=True)
+    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
+    def test_discover_inserts_new_categories(self, mock_fetch, _mock_mtop):
+        """新类目逐条 INSERT category item。"""
+        mock_fetch.return_value = [
+            {"keyword": "女装", "name": "女装"},
+            {"keyword": "男装", "name": "男装"},
+            {"keyword": "女装", "name": "女装"},  # dup keyword
+        ]
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        item = _discover_payload()
+        result = ok_result({"discover": True})
+
+        count = self.task.on_success(ctx, item, result)
+        # discover 不计入页数
+        self.assertEqual(count, 0)
+
+        items = _pending_items(self.db)
+        # 2 个唯一 keyword（女装 + 男装）
+        self.assertEqual(len(items), 2)
+        keywords = {p["keyword"] for _, p in items}
+        self.assertEqual(keywords, {"女装", "男装"})
+
+    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
+           return_value=True)
+    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
+    def test_discover_skips_exhausted_categories(self, mock_fetch, _mock_mtop):
+        """已在 category_progress 且 exhausted 的类目不插。"""
+        self.db.mark_category_exhausted("女装", "女装")
+
+        mock_fetch.return_value = [
+            {"keyword": "女装", "name": "女装"},  # exhausted → skip
+            {"keyword": "男装", "name": "男装"},
+        ]
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        self.task.on_success(ctx, _discover_payload(),
+                             ok_result({"discover": True}))
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 1)  # 只有男装
+        self.assertEqual(items[0][1]["keyword"], "男装")
+
+    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
+           return_value=True)
+    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
+    def test_discover_skips_existing_pending_category(self, mock_fetch,
+                                                       _mock_mtop):
+        """已有同 keyword pending category item 时跳过不重复插。"""
+        _insert_work_item(self.db, _cat_payload("女装", "女装"))
+
+        mock_fetch.return_value = [
+            {"keyword": "女装", "name": "女装"},
+            {"keyword": "男装", "name": "男装"},
+        ]
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        self.task.on_success(ctx, _discover_payload(),
+                             ok_result({"discover": True}))
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 2)  # 原女装 + 新男装
+        keywords = {p["keyword"] for _, p in items if p.get("keyword")}
+        self.assertEqual(keywords, {"女装", "男装"})
+
+    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
+           return_value=True)
+    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
+    def test_discover_fallback_seeds(self, mock_fetch, _mock_mtop):
+        """首页类目提取失败 → 兜底种子类目。"""
+        mock_fetch.return_value = []
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        self.task.on_success(ctx, _discover_payload(),
+                             ok_result({"discover": True}))
+
+        items = _pending_items(self.db)
+        self.assertGreater(len(items), 0)
+        keywords = {p["keyword"] for _, p in items if p.get("keyword")}
+        # SEED_CATEGORIES 第一项
+        self.assertIn(SEED_CATEGORIES[0][0], keywords)
+
+    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
+           return_value=True)
+    @patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories")
+    def test_discover_calls_mtop_handshake(self, mock_fetch, mock_mtop):
+        """discover 执行时调用 ensure_mtop_token。"""
+        mock_fetch.return_value = [
+            {"keyword": "女装", "name": "女装"},
+        ]
+        mock_mtop.return_value = True
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        self.task.on_success(ctx, _discover_payload(),
+                             ok_result({"discover": True}))
+
+        mock_mtop.assert_called_once()
+
+
+# =====================================================================
+# 4. discover 产出（1688 company）
+# =====================================================================
+
+class DiscoverCompanyTest(unittest.TestCase):
+    """company discover on_success → 提取类目 → company: 前缀 category item。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "dc.db")
+        self.task = Alibaba1688CompanyTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    @patch("fetcher.sites.alibaba1688.company.ensure_mtop_token",
+           return_value=True)
+    @patch("fetcher.sites.alibaba1688.company.fetch_homepage_categories")
+    def test_company_discover_inserts_prefixed_categories(self, mock_fetch,
+                                                           _mock_mtop):
+        """discover 产出带 company: 前缀 keyword 的 category item。"""
+        mock_fetch.return_value = [
+            {"keyword": "女装", "name": "女装"},
+            {"keyword": "男装", "name": "男装"},
+        ]
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        item = _discover_payload()
+        result = ok_result({"discover": True})
+
+        self.task.on_success(ctx, item, result)
+
+        items = _pending_items(self.db, queue=COMPANY_QUEUE)
+        self.assertEqual(len(items), 2)
+        keywords = {p["keyword"] for _, p in items}
+        self.assertEqual(keywords, {"company:女装", "company:男装"})
+
+    @patch("fetcher.sites.alibaba1688.company.ensure_mtop_token",
+           return_value=True)
+    @patch("fetcher.sites.alibaba1688.company.fetch_homepage_categories")
+    def test_company_discover_skips_exhausted(self, mock_fetch, _mock_mtop):
+        """company discover 跳过已 exhausted 的 company: 前缀进度键。"""
+        self.db.mark_category_exhausted("company:女装", "女装")
+
+        mock_fetch.return_value = [
+            {"keyword": "女装", "name": "女装"},
+            {"keyword": "男装", "name": "男装"},
+        ]
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        self.task.on_success(ctx, _discover_payload(),
+                             ok_result({"discover": True}))
+
+        items = _pending_items(self.db, queue=COMPANY_QUEUE)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1]["keyword"], "company:男装")
+
+    @patch("fetcher.sites.alibaba1688.company.ensure_mtop_token",
+           return_value=True)
+    @patch("fetcher.sites.alibaba1688.company.fetch_homepage_categories")
+    def test_company_discover_fallback_seeds(self, mock_fetch, _mock_mtop):
+        """company discover 失败 → 兜底种子关键词（company: 前缀）。"""
+        mock_fetch.return_value = []
+
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": self.task.make_stats()}
+
+        self.task.on_success(ctx, _discover_payload(),
+                             ok_result({"discover": True}))
+
+        items = _pending_items(self.db, queue=COMPANY_QUEUE)
+        self.assertGreater(len(items), 0)
+        keywords = {p["keyword"] for _, p in items if p.get("keyword")}
+        # SEED_KEYWORDS 第一项 → company:女装
+        self.assertIn("company:" + SEED_KEYWORDS[0][0], keywords)
+
+
+# =====================================================================
+# 5. company: 前缀隔离
+# =====================================================================
+
+class PrefixIsolationTest(unittest.TestCase):
+    """company 的 keyword 带 company: 前缀，进度/播种互不干扰。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "p.db")
+        self.shop_task = Alibaba1688ShopTask()
+        self.company_task = Alibaba1688CompanyTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_progress_keys_are_isolated(self):
+        """同一 keyword（女装）在 shop 与 company 的进度记录互不干扰。"""
+        # shop 侧：keyword="女装"
+        self.db.advance_category_page("女装", "女装", shops_found=3)
+        # company 侧：keyword="company:女装"
+        self.db.advance_category_page("company:女装", "女装", shops_found=5)
+
+        shop_prog = self.db.get_category_progress("女装")
+        company_prog = self.db.get_category_progress("company:女装")
+
+        self.assertEqual(shop_prog["pages_crawled"], 1)
+        self.assertEqual(company_prog["pages_crawled"], 1)
+        self.assertEqual(shop_prog["shops_found"], 3)
+        self.assertEqual(company_prog["shops_found"], 5)
+
+    def test_exhausted_keys_filtered_by_prefix(self):
+        """iter_active_categories(prefix="company:") 只返回 company: 前缀行。"""
+        # 插入混合行
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page) "
+            "VALUES ('女装', '女装', 2)")
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page) "
+            "VALUES ('company:女装', '女装', 2)")
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page) "
+            "VALUES ('男装', '男装', 1)")
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page, "
+            "exhausted) VALUES ('company:男装', '男装', 1, 1)")
+        self.db.conn.commit()
+
+        # 无前缀：返回所有未 exhausted
+        all_cats = self.db.iter_active_categories()
+        all_keywords = {c["keyword"] for c in all_cats}
+        self.assertIn("女装", all_keywords)
+        self.assertIn("company:女装", all_keywords)
+        self.assertIn("男装", all_keywords)
+        self.assertNotIn("company:男装", all_keywords)  # exhausted
+
+        # company: 前缀：只返回 company: 开头且未 exhausted
+        company_cats = self.db.iter_active_categories(prefix="company:")
+        company_keywords = {c["keyword"] for c in company_cats}
+        self.assertEqual(company_keywords, {"company:女装"})
+        self.assertNotIn("女装", company_keywords)
+
+    def test_company_prepare_seeds_only_prefixed(self):
+        """company prepare 播种只产 company: 前缀 keyword 的 category item。"""
+        # 预置混合 category_progress
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page) "
+            "VALUES ('女装', '女装', 2)")
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page) "
+            "VALUES ('company:女装', '女装', 2)")
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page, "
+            "exhausted) VALUES ('company:男装', '男装', 1, 1)")
+        self.db.conn.commit()
+        db_path = self.db.conn.execute("PRAGMA database_list").fetchone()[2]
+        self.db.close()
+
+        cfg = RunConfig()
+        cfg.db_path = db_path
+        task = Alibaba1688CompanyTask()
+        self.assertTrue(task.prepare(cfg))
+
+        db_check = ShopDB(db_path)
+        items = _pending_items(db_check, queue=COMPANY_QUEUE)
+        # company:女装（active）+ 1 discover
+        keywords = {p.get("keyword") for _, p in items if p.get("keyword")}
+        self.assertIn("company:女装", keywords)
+        self.assertNotIn("女装", keywords)  # 不带前缀的不应出现
+        self.assertNotIn("company:男装", keywords)  # exhausted
+        # 应有 1 条 discover
+        discover_count = sum(1 for _, p in items if p.get("kind") == "discover")
+        self.assertEqual(discover_count, 1)
+        db_check.close()
+
+
+# =====================================================================
+# 6. 失败补插
+# =====================================================================
+
+class RefillItemTest(unittest.TestCase):
+    """category item attempts 耗尽 → 同 payload 新 item。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "r.db")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_shop_refill_category(self):
+        """1688 shop category 失败 → 插入同 payload 新 item。"""
+        task = Alibaba1688ShopTask()
+        ctx = make_ctx(db=self.db)
+        item = _cat_payload("女装", "女装")
+
+        task.refill_item(ctx, item)
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], item)
+        row = self.db.conn.execute(
+            "SELECT attempts FROM work_items WHERE id=?",
+            (items[0][0],)).fetchone()
+        self.assertEqual(row["attempts"], 0)
+
+    def test_shop_refill_discover(self):
+        """1688 shop discover 失败也补插。"""
+        task = Alibaba1688ShopTask()
+        ctx = make_ctx(db=self.db)
+        item = _discover_payload()
+
+        task.refill_item(ctx, item)
+
+        items = _pending_items(self.db)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], _discover_payload())
+
+    def test_company_refill_category(self):
+        """1688 company category 失败 → 同 payload（company: 前缀）。"""
+        task = Alibaba1688CompanyTask()
+        ctx = make_ctx(db=self.db)
+        item = _company_cat_payload("company:女装", "女装")
+
+        task.refill_item(ctx, item)
+
+        items = _pending_items(self.db, queue=COMPANY_QUEUE)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], item)
+
+    def test_company_refill_discover(self):
+        """1688 company discover 失败也补插。"""
+        task = Alibaba1688CompanyTask()
+        ctx = make_ctx(db=self.db)
+        item = _discover_payload()
+
+        task.refill_item(ctx, item)
+
+        items = _pending_items(self.db, queue=COMPANY_QUEUE)
+        self.assertEqual(len(items), 1)
+        self.assertEqual(items[0][1], _discover_payload())
+
+
+# =====================================================================
+# 7. 幂等播种
+# =====================================================================
+
+class IdempotentSeedTest(unittest.TestCase):
+    """重复 prepare/播种 → 不产生重复 pending item。"""
+
+    def _setup_db(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db_path = str(Path(self._tmp.name) / "s.db")
+        self.db = ShopDB(self.db_path)
+
+    def _teardown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_shop_double_prepare_no_duplicates(self):
+        """shop 两次 prepare 不产生重复 pending。"""
+        self._setup_db()
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page) "
+            "VALUES ('女装', '女装', 2)")
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page, "
+            "exhausted) VALUES ('男装', '男装', 1, 1)")
+        self.db.conn.commit()
+        self.db.close()
+
+        cfg = RunConfig()
+        cfg.db_path = self.db_path
+
+        task1 = Alibaba1688ShopTask()
+        self.assertTrue(task1.prepare(cfg))
+        db_check = ShopDB(self.db_path)
+        items1 = _pending_items(db_check)
+        keywords1 = {p.get("keyword") for _, p in items1 if p.get("keyword")}
+        self.assertIn("女装", keywords1)
+        self.assertNotIn("男装", keywords1)  # exhausted
+        discover_count1 = sum(1 for _, p in items1 if p.get("kind") == "discover")
+        self.assertEqual(discover_count1, 1)
+        db_check.close()
+
+        # 第二次 prepare 不产生重复
+        task2 = Alibaba1688ShopTask()
+        self.assertTrue(task2.prepare(cfg))
+        db_check2 = ShopDB(self.db_path)
+        items2 = _pending_items(db_check2)
+        self.assertEqual(len(items2), len(items1))
+        db_check2.close()
+        self._teardown()
+
+    def test_company_double_prepare_no_duplicates(self):
+        """company 两次 prepare 不产生重复 pending。"""
+        self._setup_db()
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page) "
+            "VALUES ('company:女装', '女装', 2)")
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page, "
+            "exhausted) VALUES ('company:男装', '男装', 1, 1)")
+        self.db.conn.commit()
+        self.db.close()
+
+        cfg = RunConfig()
+        cfg.db_path = self.db_path
+
+        task1 = Alibaba1688CompanyTask()
+        self.assertTrue(task1.prepare(cfg))
+        db_check = ShopDB(self.db_path)
+        items1 = _pending_items(db_check, queue=COMPANY_QUEUE)
+        keywords1 = {p.get("keyword") for _, p in items1 if p.get("keyword")}
+        self.assertIn("company:女装", keywords1)
+        self.assertNotIn("company:男装", keywords1)
+        db_check.close()
+
+        task2 = Alibaba1688CompanyTask()
+        self.assertTrue(task2.prepare(cfg))
+        db_check2 = ShopDB(self.db_path)
+        items2 = _pending_items(db_check2, queue=COMPANY_QUEUE)
+        self.assertEqual(len(items2), len(items1))
+        db_check2.close()
+        self._teardown()
+
+
+# =====================================================================
+# 8. CLI acquire
+# =====================================================================
+
+class CliAcquireTest(unittest.TestCase):
+    """claim_next_eligible(["crawl_1688_shop"/"crawl_1688_company"])
+    认领返回 payload；无货 None。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "a.db")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_shop_acquire_returns_payload(self):
+        _insert_work_item(self.db, _cat_payload("女装", "女装"))
+        task = Alibaba1688ShopTask()
+        ctx = make_ctx(db=self.db)
+        ctx.wid = 1
+
+        item = task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["kind"], "category")
+        self.assertEqual(item["keyword"], "女装")
+        self.assertIn("id", item)
+
+    def test_shop_acquire_returns_none_when_empty(self):
+        task = Alibaba1688ShopTask()
+        ctx = make_ctx(db=self.db)
+        ctx.wid = 1
+        self.assertIsNone(task.acquire_item(ctx))
+
+    def test_shop_acquire_returns_discover(self):
+        _insert_work_item(self.db, _discover_payload())
+        task = Alibaba1688ShopTask()
+        ctx = make_ctx(db=self.db)
+        ctx.wid = 1
+
+        item = task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["kind"], "discover")
+
+    def test_company_acquire_returns_payload(self):
+        _insert_work_item(self.db, _company_cat_payload("company:女装", "女装"),
+                          queue=COMPANY_QUEUE)
+        task = Alibaba1688CompanyTask()
+        ctx = make_ctx(db=self.db)
+        ctx.wid = 1
+
+        item = task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["keyword"], "company:女装")
+
+    def test_company_acquire_returns_none_when_empty(self):
+        task = Alibaba1688CompanyTask()
+        ctx = make_ctx(db=self.db)
+        ctx.wid = 1
+        self.assertIsNone(task.acquire_item(ctx))
+
+
+# =====================================================================
+# 9. validate discover 放行（Step 4.1 C1 教训回归）
+# =====================================================================
+
+class ValidateDiscoverTest(unittest.TestCase):
+    """discover 走完整 fetch → validate → on_success 三段式。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "v.db")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def test_shop_validate_discover_passes(self):
+        """shop validate 放行 discover（检查 discover 键）。"""
+        task = Alibaba1688ShopTask()
+        ctx = make_ctx(db=self.db)
+
+        # fetch → discover 标记
+        result = task.fetch(ctx, _discover_payload())
+        self.assertEqual(result.outcome, Outcome.OK)
+        self.assertTrue(result.data.get("discover"))
+
+        # validate → 放行
+        self.assertTrue(task.validate(ctx, _discover_payload(), result))
+
+    def test_shop_validate_category_checks_shops(self):
+        """shop validate category 检查 shops 列表。"""
+        task = Alibaba1688ShopTask()
+        ctx = make_ctx(db=self.db)
+
+        self.assertTrue(task.validate(ctx, _cat_payload(),
+                                      ok_result({"shops": []})))
+        self.assertFalse(task.validate(ctx, _cat_payload(),
+                                       ok_result({"wrong_key": 1})))
+
+    def test_company_validate_discover_passes(self):
+        """company validate 放行 discover。"""
+        task = Alibaba1688CompanyTask()
+        ctx = make_ctx(db=self.db)
+
+        result = task.fetch(ctx, _discover_payload())
+        self.assertEqual(result.outcome, Outcome.OK)
+        self.assertTrue(result.data.get("discover"))
+
+        self.assertTrue(task.validate(ctx, _discover_payload(), result))
+
+    def test_discover_full_pipeline_shop(self):
+        """shop discover 三段式（回归 C1 教训）。"""
+        task = Alibaba1688ShopTask()
+        ctx = make_ctx(db=self.db)
+        ctx.state["task"] = {"stats": task.make_stats()}
+
+        with patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
+                   return_value=True):
+            with patch("fetcher.sites.alibaba1688.shop.fetch_homepage_categories",
+                       return_value=[{"keyword": "女装", "name": "女装"}]):
+                item = _discover_payload()
+                # 1. fetch
+                result = task.fetch(ctx, item)
+                self.assertEqual(result.outcome, Outcome.OK)
+                # 2. validate
+                self.assertTrue(task.validate(ctx, item, result))
+                # 3. on_success
+                count = task.on_success(ctx, item, result)
+                self.assertEqual(count, 0)
+                items = _pending_items(self.db)
+                self.assertGreaterEqual(len(items), 1)
+
+
+# =====================================================================
+# 10. shop fetch 读 next_page + mtop 检查
+# =====================================================================
+
+class ShopFetchTest(unittest.TestCase):
+    """shop fetch 从 category_progress 读 next_page，mtop 检查。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "f.db")
+        self.task = Alibaba1688ShopTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    @patch("time.sleep")
+    @patch("random.uniform", return_value=1.0)
+    @patch("fetcher.sites.alibaba1688.shop.has_mtop_token",
+           return_value=True)
+    def test_fetch_reads_next_page_from_db(self, _mtop, _r, _s):
+        """category_progress.next_page=3 → fetch 第 3 页。"""
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page, "
+            "pages_crawled) VALUES ('女装', '女装', 3, 2)")
+        self.db.conn.commit()
+
+        page = Shop1688Page(
+            shops=[{"domain": "shop1.1688.com", "name": "店1"}],
+            has_more=False)
+        ctx = make_ctx(page=page, db=self.db)
+        item = _cat_payload("女装", "女装")
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+
+        # 验证 fetch 了第 3 页
+        url, kw = page.goto_calls[0]
+        self.assertIn("beginPage=3", url)
+        self.assertIn("keywords=", url)
+
+    @patch("time.sleep")
+    @patch("random.uniform", return_value=1.0)
+    @patch("fetcher.sites.alibaba1688.shop.has_mtop_token",
+           return_value=True)
+    def test_fetch_defaults_to_page_1(self, _mtop, _r, _s):
+        """无 category_progress → page_no=1。"""
+        page = Shop1688Page(has_more=True)
+        ctx = make_ctx(page=page, db=self.db)
+        item = _cat_payload("新类目", "新类目")
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+        url, kw = page.goto_calls[0]
+        self.assertIn("beginPage=1", url)
+
+    @patch("fetcher.sites.alibaba1688.shop.has_mtop_token",
+           return_value=False)
+    @patch("fetcher.sites.alibaba1688.shop.ensure_mtop_token",
+           return_value=False)
+    def test_fetch_blocked_when_no_mtop(self, _ensure, _has):
+        """无 mtop 令牌 → fetch 返回 BLOCKED。"""
+        page = FakePage()
+        ctx = make_ctx(page=page, db=self.db)
+        item = _cat_payload("女装", "女装")
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.BLOCKED)
+
+    def test_fetch_discover_no_request(self):
+        """discover item fetch 不发起网络请求。"""
+        page = FakePage()
+        ctx = make_ctx(page=page, db=self.db)
+        item = _discover_payload()
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+        self.assertTrue(result.data.get("discover"))
+
+
+# =====================================================================
+# 11. company fetch 读 next_page（company: 前缀）
+# =====================================================================
+
+class CompanyFetchTest(unittest.TestCase):
+    """company fetch 用 company: 前缀读 category_progress。"""
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "cf.db")
+        self.task = Alibaba1688CompanyTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    @patch("time.sleep")
+    @patch("random.uniform", return_value=1.0)
+    @patch("fetcher.sites.alibaba1688.company.has_mtop_token",
+           return_value=True)
+    def test_company_fetch_uses_prefixed_progress(self, _mtop, _r, _s):
+        """company fetch 从 company:女装 进度读 next_page。"""
+        self.db.conn.execute(
+            "INSERT INTO category_progress (keyword, name, next_page, "
+            "pages_crawled) VALUES ('company:女装', '女装', 2, 1)")
+        self.db.conn.commit()
+
+        page = Company1688Page(
+            shops=[{"domain": "shop1.1688.com", "name": "店1"}],
+            has_more=False, cards_count=1)
+        ctx = make_ctx(page=page, db=self.db)
+        item = _company_cat_payload("company:女装", "女装")
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+        url, kw = page.goto_calls[0]
+        self.assertIn("beginPage=2", url)
+
+    @patch("time.sleep")
+    @patch("random.uniform", return_value=1.0)
+    @patch("fetcher.sites.alibaba1688.company.has_mtop_token",
+           return_value=True)
+    def test_company_fetch_defaults_to_page_1(self, _mtop, _r, _s):
+        """无 category_progress → page_no=1。"""
+        page = Company1688Page(has_more=True, cards_count=1)
+        ctx = make_ctx(page=page, db=self.db)
+        item = _company_cat_payload("company:新类目", "新类目")
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.OK)
+        url, kw = page.goto_calls[0]
+        self.assertIn("beginPage=1", url)
+
+    @patch("fetcher.sites.alibaba1688.company.has_mtop_token",
+           return_value=False)
+    @patch("fetcher.sites.alibaba1688.company.ensure_mtop_token",
+           return_value=False)
+    def test_company_fetch_blocked_no_mtop(self, _ensure, _has):
+        """无 mtop → company fetch BLOCKED。"""
+        page = FakePage()
+        ctx = make_ctx(page=page, db=self.db)
+        item = _company_cat_payload("company:女装", "女装")
+
+        result = self.task.fetch(ctx, item)
+        self.assertEqual(result.outcome, Outcome.BLOCKED)
+
+
+# =====================================================================
+# 12. 类名兼容（确保 __init__.py 的 make_task 仍可用）
+# =====================================================================
+
+class ClassNameCompatibilityTest(unittest.TestCase):
+    """重构后类名 Alibaba1688ShopTask / Alibaba1688CompanyTask，
+    但 __init__.py 的 make_task 仍能实例化。"""
+
+    def test_shop_task_instantiable(self):
+        """通过 make_task("shop") 创建 shop task。"""
+        from fetcher.sites.alibaba1688 import Alibaba1688Plugin
+        plugin = Alibaba1688Plugin()
+        task = plugin.make_task("shop")
+        self.assertIsInstance(task, Alibaba1688ShopTask)
+
+    def test_company_task_instantiable(self):
+        """通过 make_task("company") 创建 company task。"""
+        from fetcher.sites.alibaba1688 import Alibaba1688Plugin
+        plugin = Alibaba1688Plugin()
+        task = plugin.make_task("company")
+        self.assertIsInstance(task, Alibaba1688CompanyTask)
+
+
+if __name__ == "__main__":
+    unittest.main()
