# Task 4.1 Report — mic shop feeder 任务拆分（work_items 驱动重构）

> 分支：`feat/multiqueue-p3` | 日期：2026-08-08 | 状态：DONE

## 实现摘要

将 `MadeInChinaShopTask` 从进程内 `CategoryPool + acquire` 模式重构为 **work_items 驱动**：

- **payload 形态**：`{"kind":"category","keyword":<slug>,"name":<cat_name>,"fmt":"x2"|"plain"}` 或 `{"kind":"discover"}`
- **page_no 运行时读**：`fetch` 里读 `db.get_category_progress(keyword)["next_page"]`（无记录=1），不进 payload
- **discover 执行**：`on_success` 里 `kind=="discover"` 走首页+导航页类目提取，新类目逐条 INSERT category item
- **链式续喂**：category item `on_success` 未 exhausted 时 INSERT 同 payload 下一页 item（attempts=0）
- **ZERO_NEW_LIMIT 保护**：streak 在 task 实例内存 dict（slug→计数）+ 锁，连续零新增达标 → `mark_category_exhausted` + 不插下一页
- **失败补插**：`refill_item` 对 category/discover 均补插同 payload 新 item
- **CLI acquire**：`db.claim_next_eligible(["crawl_mic_shop"], consumer_id)` → payload dict（与 daemon 同一路径）
- **冷启动**：`cold_start` 改为纯浏览软着陆（逛首页+导航页，不提取类目；提取归 discover）
- **CategoryPool 退役**：删除整个 CategoryPool 类、ACQUIRE_WAIT_MAX、_slug_fmt（fmt 从 payload 取）

### 改动文件

| 文件 | 改动 |
|---|---|
| `fetcher/fetcher/control/task.py` | `Task` 基类新增 `refill_item(self, ctx, item) -> None`（默认空实现） |
| `fetcher/fetcher/control/queue_router.py` | `release_item()` 里 attempts 耗尽时调 `_task_for(ctx).refill_item(ctx, item)` |
| `fetcher/fetcher/sites/madeinchina/shop.py` | **主重构**：删除 CategoryPool/ACQUIRE_WAIT_MAX；MadeInChinaShopTask 全面改为 work_items payload 驱动；新增 `_run_discover`、`_seed_category_items`、`_seed_discover_item`、`refill_item`、`_insert_work_item`、`_count_pending_category` 辅助方法 |
| `fetcher/tests/test_madeinchina.py` | 移除 CategoryPool 相关测试（3 个）+ 旧 cold_start 测试（2 个）；更新 6 个测试适配 payload dict；新增 1 个纯浏览 cold_start 测试 |
| `fetcher/tests/test_mic_shop_feeder.py` | **新增**，19 个 TDD 测试覆盖链式续喂/ZERO_NEW_LIMIT/失败补插/discover产出/幂等播种/CLI acquire/page_no运行时读/refill_item基类默认 |

## 测试列表

### TDD 新增测试 (test_mic_shop_feeder.py)

| # | 测试 | 覆盖项 |
|---|---|---|
| 1 | `test_chain_feed_inserts_next_page_item` | 有新增店铺 → next_page+1 + 新 work_item |
| 2 | `test_chain_feed_skips_when_exhausted` | 空页 → exhausted + 不插下一页 |
| 3 | `test_zero_new_exhausts_after_limit` | 连续 ZERO_NEW_LIMIT 页零新增 → exhausted |
| 4 | `test_zero_new_no_chain_feed_when_exhausted` | ZERO_NEW_LIMIT 耗尽不再链式续喂 |
| 5 | `test_zero_new_resets_after_fresh` | 零新增后有新店 → 计数清零 |
| 6 | `test_refill_inserts_replacement_category_item` | category 补插同 payload |
| 7 | `test_refill_discover_also_replenishes` | discover 补插 |
| 8 | `test_discover_inserts_new_categories` | discover → 提取类目 → INSERT category item |
| 9 | `test_discover_skips_exhausted_categories` | exhausted 类目不重复插 |
| 10 | `test_discover_skips_existing_pending_category` | 已有 pending 不重复 |
| 11 | `test_discover_fallback_seeds` | 提取失败 → 种子兜底 |
| 12 | `test_double_prepare_no_duplicates` | 重复 prepare 幂等 |
| 13 | `test_acquire_returns_payload` | CLI acquire 返回 payload dict |
| 14 | `test_acquire_returns_none_when_empty` | 无货返回 None |
| 15 | `test_acquire_returns_discover_payload` | acquire 认领 discover item |
| 16 | `test_fetch_reads_next_page_from_db` | fetch 读 next_page=3 → 抓第 3 页 |
| 17 | `test_fetch_defaults_to_page_1_when_no_progress` | 无 progress → page_no=1 |
| 18 | `test_fetch_discover_returns_success_without_request` | discover fetch 不发请求 |
| 19 | `test_base_refill_item_is_noop` | Task 基类 refill_item 不抛异常 |

### 旧测试适配 (test_madeinchina.py)

- `test_pool_remembers_fmt_per_slug` → 删除（CategoryPool 退役）
- `test_fetch_uses_fmt_for_plain_slug` → `test_fetch_uses_fmt_from_payload`（fmt 从 payload 取）
- `test_fetch_extracts_showrooms` → item 改为 payload dict
- `test_on_success_empty_marks_exhausted` → 适配 payload dict
- `test_on_success_zero_new_marks_exhausted_after_limit` → 适配 payload dict
- `test_on_success_zero_new_resets_after_fresh_page` → 适配 payload dict
- `test_prepare_seeds_pool_from_db` → `test_prepare_seeds_from_db`（验证 work_items 播种）
- `test_pick_none_*` (2 tests) → 删除（CategoryPool 退役）
- `test_cold_start_seeds_pool_from_market_dir` + `test_cold_start_both_pages_fail_falls_back_to_seeds` → `test_cold_start_browses_home_and_market_dir`（纯浏览）

## TDD 证据

1. **RED**：先写 19 个测试 → `python -m pytest tests/test_mic_shop_feeder.py -v` → **19 failed**（`'Task' object has no attribute 'refill_item'` / `ValueError: too many values to unpack`）
2. **GREEN**：实现 Task.refill_item + QueueRouter 接线 + MadeInChinaShopTask payload 重构 → **19 passed** + 旧测试适配也全部通过
3. **全量**：`cd fetcher && python -m pytest tests -q` → **462 passed, 2 subtests passed**（基线 447 + 净增 15）

## 复核确认结论（§3）

| 检查项 | 结果 |
|---|---|
| `crawl_mic_contact` 在双队列注册表 | ✅ `cli/main.py:233-241`：queue/site/task/topup/domain_suffix 完整 |
| `reset_daemon_state` 逐 site 循环 | ✅ `cli/main.py:249-254`：`for spec in registry: db.reset_in_progress(spec.domain_suffix)` |
| mic contact prepare 带域过滤 | ✅ `contact.py:178`：`db.reset_in_progress(SHOWROOM_DOMAIN_SUFFIX)` |

## 自查

- ✅ brief 所有裁定均落实（payload 形态、page_no 运行时读、discover 走 on_success、streak 内存计数、refill_item 基类默认空、冷启动纯浏览）
- ✅ 未碰 db.py、platform/、scraper/、util/、vendor/wa-check/
- ✅ CLI 与 daemon 同一代码路径（acquire_item 用 claim_next_eligible）
- ✅ ZERO_NEW_LIMIT=2 保持不变；SEED_CATEGORIES 保持不变；_JS_EXTRACT_SHOWROOMS 保持不变
- ✅ `make_stats` 保持 `{"shops","new","pages"}` 三键
- ⚠️ 工作区有他人未提交改动，已确认不碰（scoped add 严格按 brief 列出文件）
