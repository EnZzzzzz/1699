# Re-review Package — Step 4.2 fix round 1

## Commits
14c92d4 fix(multiqueue-p3): I1 移除私有函数导入 I2 DB取证 M3 docstring M4 结构断言

## Stat
 .../smoke-step4.2/analysis.md                      | 53 ++++++++++++++++++----
 .../task-4.2-report.md                             | 45 ++++++++++++++++++
 fetcher/fetcher/cli/main.py                        |  5 +-
 fetcher/fetcher/sites/madeinchina/shop.py          |  6 ++-
 fetcher/tests/test_madeinchina.py                  |  4 ++
 5 files changed, 100 insertions(+), 13 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md
index 58774e4..39ec8c3 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md
@@ -27,47 +27,84 @@ category_progress 空 → `_seed_category_items` 经 `iter_active_categories` 
 
 - claimed item 回收 = 0（无残留）
 - in_progress 重置 = 0：feeder 队列 topup=None，`reset_daemon_state` 正确跳过 `reset_in_progress`（逐 site 打印空——仅 contact 队列才参与）
 
 验证：`reset_daemon_state` 新增 `if spec.topup is not None` 条件生效。
 
 ### 3. Discover 执行 ✅
 
 discover item 被认领 → fetch 返回 `{"discover": True}` → on_success 执行类目提取：
 - 浏览首页 `https://www.made-in-china.com/` + 市场导航页 `https://www.made-in-china.com/shichang/`
-- 提取类目 → 逐条 INSERT category item（~360 个 category work_items pending）
-
-验证：work_items 表含 ~360 条 `kind=category` pending item。
+- 提取类目 → 逐条 INSERT category item
+
+#### DB 取证（sqlite3 只读，2026-08-08 修复 I2 时补充）
+
+```sql
+-- work_items: category vs 其他 pending 计数
+SELECT payload_json FROM work_items
+WHERE queue='crawl_mic_shop' AND status='pending';
+-- 按 kind 分组统计：
+--   category: 1053
+--   total pending: 1053
+--   status=done: 2 (discover + jgdbj page 1)
+--   status=pending: 1053
+```
 
 ### 4. 类目页消费 ✅
 
 category item `jgdbj`（激光打标机）被认领 → `_fetch_category` 抓取 market 页 → 提取 15 个供应商展厅 → shops 落库。
 
 ```
 [OK] 本次采集: 1 页, 店铺 15 个（新增 15）
 ```
 
-验证：
-- shops 表：15 条 `*.cn.made-in-china.com` 域名 status=pending
-- category_progress：`jgdbj` next_page=2 pages=1 shops_found=15 exhausted=0
+#### DB 取证
+
+```sql
+-- category_progress 推进值
+SELECT keyword, name, next_page, pages_crawled, shops_found, exhausted, last_crawled_at
+FROM category_progress WHERE keyword='jgdbj';
+-- jgdbj|激光打标机|2|1|15|0|2026-08-08 18:14:13
+
+-- shops 落库
+SELECT COUNT(*) AS total, status FROM shops
+WHERE domain LIKE '%made-in-china.com%' GROUP BY status;
+-- 15|pending
+
+-- 店铺采样
+SELECT domain, name, status FROM shops ORDER BY id LIMIT 3;
+-- jixie.cn.made-in-china.com|机械设备|pending
+-- daxian0607.cn.made-in-china.com|2012-07-05|pending
+-- pazhajicom.cn.made-in-china.com|2014-10-24|pending
+```
 
 ### 5. Category progress 推进 ✅
 
 `advance_category_page` 正确推进：
 - next_page: 1→2
 - pages_crawled: 0→1
 - shops_found: 0→15
 - exhausted=0（非空页）
 
-### 6. 链式续喂
+### 6. 链式续喂 ✅
+
+`on_success` 在 jgdbj 页 1 成功后 INSERT 同 payload 下一页 item（attempts=0）：
+
+```sql
+-- jgdbj 相关 work_items
+SELECT payload_json, status FROM work_items
+WHERE queue='crawl_mic_shop' AND payload_json LIKE '%jgdbj%';
+-- kind=category keyword=jgdbj fmt=plain status=done     ← 页 1（已消费）
+-- kind=category keyword=jgdbj fmt=plain status=pending   ← 页 2（链式续喂）
+```
 
-由于 `-n 1 --limit 8`，daemon 在完成第 1 批（discover + 1 个 category + 补种 category items）后退出。`on_success` 代码路径已验证通过（若未 exhausted 会 INSERT 同 payload 下一页 item），但因 daemon 退出未能观察到该 item 被认领。
+由于 `-n 1 --limit 8`，daemon 在完成第 1 批后退出，页 2 未被认领但 item 已插入。
 
 ### 7. 环境噪声
 
 - 浏览器正常启动（CloakBrowser 二进制已存在）
 - ensure_site 成功装载 dummy cookie → 无报错
 - market 页面成功加载并提取类目列表（网络通畅）
 - 无滑块/风控拦截（常规浏览行为）
 
 ## 结论
 
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md
index c04565f..c71df49 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md
@@ -83,10 +83,55 @@ python -m fetcher daemon --db /tmp/smoke_p3_42.db --workers 1 --limit 8 -n 1 \
 ## 自查
 
 - ✅ brief 所有裁定均落实（iter_active_categories 统一查询+prefix、crawl_mic_shop 入注册表+topup=None、reset 仅 topup 队列、播种切 iter_active_categories + pinyin 过滤）
 - ✅ `get_active_categories` 委托 `iter_active_categories` + `_is_pinyin_slug`（向后兼容，原有调用方无需改动）
 - ✅ grep 确认无其他 `get_active_categories` 调用方（仅 `madeinchina/shop.py` 的 `_seed_category_items`）
 - ✅ 未碰 platform/、fetcher/vendor/wa-check/、scraper/、util/
 - ✅ --queues choices 自动含 crawl_mic_shop（注册表动态派生，Step 3.1 已实现）
 - ✅ 全量 468 passed（基线 463 + 5 净增）
 - ✅ 冒烟取证完整（播种→discover→类目页消费→progress 推进）
 - ⚠️ 工作区有他人未提交改动，scoped add 仅按 brief 列出文件
+
+---
+
+## Fix Round 1（task-4.2-fix1.md）
+
+> Commit 待提交 | 修复条目: I1 / I2 / M3 / M4
+
+### I1（Important）— shop.py 跨模块导入 db 私有函数 _is_pinyin_slug
+
+**问题**：`from fetcher.db import _is_pinyin_slug` 破坏封装，扩大 db 公开 API 面。
+
+**修复**：在 shop.py 本地复制拼音判断逻辑（`re.compile(r"^[a-zA-Z0-9_]+$")`），与 db._is_pinyin_slug 同义，不跨模块导私有符号。
+
+### I2（Important）— 冒烟证据不充分：analysis.md 结论超出 log 可证范围
+
+**问题**：daemon-run.log 仅 13 行，未含 discover 类目数、category_progress 推进值等可验证数据；analysis.md 的数值为推理而非取证。
+
+**修复**：对 /tmp/smoke_p3_42.db 做 sqlite3 只读查询取证并补充到 analysis.md：
+- work_items kind 分组：category=1053 pending，done=2（discover + jgdbj 页1）
+- category_progress：jgdbj next_page=2 pages=1 shops_found=15 exhausted=0
+- shops 落库：15 条 pending
+- 链式续喂：jgdbj 页 2 item 已插入（status=pending）
+
+### M3（Minor）— reset_daemon_state docstring 与新行为不一致
+
+**修复**：docstring 改为「逐有 topup 的队列重置 in_progress（feeder 跳过）」。
+
+### M4（Minor）— test_iter_active_categories_returns_non_exhausted 缺结构断言
+
+**修复**：新增 `for r in result: assertIn("keyword"/"name", r)` 结构断言。
+
+### 测试
+
+- 聚焦：test_madeinchina.py (44) + test_cli.py (12) → **56 passed**
+- 全量：`cd fetcher && python -m pytest tests -q` → **468 passed, 2 subtests passed**
+
+### 改动文件
+
+| 文件 | 改动 |
+|---|---|
+| `fetcher/fetcher/sites/madeinchina/shop.py` | I1: 移除 `from fetcher.db import _is_pinyin_slug`，本地复制正则 |
+| `fetcher/fetcher/cli/main.py` | M3: docstring 精确化 |
+| `fetcher/tests/test_madeinchina.py` | M4: 新增结构断言 |
+| `docs/.../smoke-step4.2/analysis.md` | I2: 追加 sqlite3 只读 DB 取证 |
+| `docs/.../task-4.2-report.md` | 本修复记录追加 |
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index 77262a0..044edba 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -250,24 +250,23 @@ def _build_registry(selected_queues: list[str] | None = None) -> list:
         domain_suffix="",
         requires={"channel", "browser"},
     ))
 
     if selected_queues:
         specs = [s for s in specs if s.queue in selected_queues]
     return specs
 
 
 def reset_daemon_state(db, registry: list) -> tuple[int, int]:
-    """daemon 启动崩溃恢复：全量回收 claimed + 逐 site 重置 in_progress。
+    """daemon 启动崩溃恢复：全量回收 claimed + 逐有 topup 的队列重置
+    in_progress（feeder 队列跳过——不产生 in_progress shops）。
 
-    只对 topup 非 None 的队列做 reset_in_progress（feeder 队列跳过——
-    它不产生 in_progress shops）。
     返回 (n_claimed_reset, n_in_progress_reset)。
     提取为独立函数便于测试（I2）。
     """
     n_items = db.reset_claimed_work_items()
     total_shops = 0
     for spec in registry:
         if spec.topup is not None:
             n = db.reset_in_progress(spec.domain_suffix)
             total_shops += n
     return n_items, total_shops
diff --git a/fetcher/fetcher/sites/madeinchina/shop.py b/fetcher/fetcher/sites/madeinchina/shop.py
index 3d58680..1ad9174 100644
--- a/fetcher/fetcher/sites/madeinchina/shop.py
+++ b/fetcher/fetcher/sites/madeinchina/shop.py
@@ -273,23 +273,25 @@ class MadeInChinaShopTask(Task):
         """活跃拼音类目逐条插 category item（已有同 keyword pending 跳过）。
 
         经 iter_active_categories 取全量未采完类目，再 _is_pinyin_slug
         过滤拼音 slug（与 get_active_categories 同口径）。
 
         ⚠️ 已知局限：category_progress 不含 fmt 字段，播种一律 "x2"；
         plain 体系类目（如 jgdbj）首次 fetch 会拼错 URL 而失败；
         discover 从页面提取时带正确 fmt 后纠正。Step 4.2 若 category_progress
         加 fmt 列可根除。
         """
-        from fetcher.db import _is_pinyin_slug
+        # 本地拼音判断（与 db._is_pinyin_slug 同义，避免跨模块导私有函数）
+        import re
+        _pinyin_re = re.compile(r"^[a-zA-Z0-9_]+$")
         active = [cat for cat in db.iter_active_categories()
-                  if _is_pinyin_slug(cat["keyword"])]
+                  if _pinyin_re.match(cat["keyword"])]
         n = 0
         for cat in active:
             slug = cat["keyword"]
             name = cat.get("name", slug)
             existing = self._count_pending_by_kind(db, "category", slug)
             if existing > 0:
                 continue
             # fmt 默认 x2（局限见上），discover 提取时带正确 fmt 覆盖
             payload = {"kind": "category", "keyword": slug,
                        "name": name, "fmt": "x2"}
diff --git a/fetcher/tests/test_madeinchina.py b/fetcher/tests/test_madeinchina.py
index c2257cd..097babc 100644
--- a/fetcher/tests/test_madeinchina.py
+++ b/fetcher/tests/test_madeinchina.py
@@ -639,20 +639,24 @@ class ShopTaskTest(unittest.TestCase):
             db.conn.commit()
             result = db.iter_active_categories()
             # exhausted=1 的被排除
             self.assertEqual(len(result), 3)
             keywords = [r["keyword"] for r in result]
             self.assertNotIn("cat_ex", keywords)
             # 按 id 排序 → cat_c, cat_a, cat_b
             self.assertEqual(keywords, ["cat_c", "cat_a", "cat_b"])
             # 字段含 keyword/name
             self.assertEqual(result[0]["name"], "C 类目")
+            # 结构断言：每条都含 keyword 和 name
+            for r in result:
+                self.assertIn("keyword", r)
+                self.assertIn("name", r)
             db.close()
         finally:
             tmp.cleanup()
 
     def test_iter_active_categories_prefix_filter(self):
         """prefix='company:' 只返回 company: 前缀行。"""
         import tempfile
         from pathlib import Path
         from fetcher.db import ShopDB
         tmp = tempfile.TemporaryDirectory()
