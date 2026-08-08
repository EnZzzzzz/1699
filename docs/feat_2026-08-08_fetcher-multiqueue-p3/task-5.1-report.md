# Task 5.1 Report — 1688 shop/company feeder 任务拆分

## 状态：DONE

## 实现摘要

按 brief 规格，将 `ShopTask` / `CompanyTask` 从 CategoryPool/KeywordPool 进程内填池模式重构为 work_items 驱动 feeder 模式，与 Step 4.1 的 `MadeInChinaShopTask` 同模式。

### 改动文件

| 文件 | 变更 |
|---|---|
| `fetcher/fetcher/sites/alibaba1688/shop.py` | 全面重构：移除 CategoryPool，新增 Alibaba1688ShopTask（work_items feeder 模式） |
| `fetcher/fetcher/sites/alibaba1688/company.py` | 全面重构：移除 KeywordPool，新增 Alibaba1688CompanyTask（work_items feeder 模式） |
| `fetcher/fetcher/sites/alibaba1688/__init__.py` | make_task 更新为新类名 |
| `fetcher/tests/test_1688_feeder.py` | **新增** 41 个 TDD 测试 |

### shop.py 变更要点

- 移除 `CategoryPool` 类（:110-170）
- 新增 `Alibaba1688ShopTask`（原 `ShopTask`），保留向后兼容别名 `ShopTask = Alibaba1688ShopTask`
- 新增 `QUEUE = "crawl_1688_shop"`, `SITE = "1688"`
- **prepare**: 从 `iter_active_categories()`（无拼音过滤，1688 中文/英文都算）逐条播种 category item + 1 条 discover item（幂等）
- **acquire_item**: `claim_next_eligible(["crawl_1688_shop"], consumer_id)` → payload dict（含 id）
- **fetch**: `kind=="discover"` → 返回 discover 标记；`kind=="category"` → 读 `category_progress.next_page` → 现搜索页逻辑；无 mtop → BLOCKED
- **validate**: discover 检查 `discover` 键放行（C1 教训回归）；category 检查 shops list
- **on_success**: discover → `fetch_homepage_categories` + `ensure_mtop_token` → 新类目逐条 INSERT category item（幂等：跳过 exhausted/pending）；category → 入库 + 链式续喂（hasMore/空页判 exhausted，无 ZERO_NEW_LIMIT）
- **refill_item**: category 同 payload 补插；discover 补插
- **cold_start**: 纯浏览软着陆（类目提取归 discover）
- **after_item**: 空操作（无 CategoryPool 释放）

### company.py 变更要点

- 移除 `KeywordPool` 类（:145-166）
- 新增 `Alibaba1688CompanyTask`（原 `CompanyTask`），保留向后兼容别名 `CompanyTask = Alibaba1688CompanyTask`
- 新增 `QUEUE = "crawl_1688_company"`, `SITE = "1688"`
- **prepare**: 从 `iter_active_categories(prefix="company:")` 播种 category item + 1 条 discover item（幂等）
- **acquire_item**: `claim_next_eligible(["crawl_1688_company"], consumer_id)` → payload dict
- **fetch (category)**: 进度键 `get_category_progress("company:女装")`；URL 拼接时去掉前缀裸关键词
- **fetch (discover)**: 返回 discover 标记
- **validate**: discover 检查 discover 键；category 检查 shops list
- **on_success (discover)**: `fetch_homepage_categories` → `ensure_mtop_token` → 新类目逐条 INSERT（keyword 自动加 `company:` 前缀）
- **on_success (category)**: 入库 shops（`upsert_shops`），progress 键带 `company:` 前缀，链式续喂
- **refill_item**: category/discover 补插
- **cold_start**: 纯浏览软着陆

### 未改文件

- `fetcher/fetcher/db.py` — 本次不改
- `fetcher/fetcher/control/task.py` — `refill_item` 钩子 Step 4.1 已加，本次不碰
- `platform/`, `scraper/`, `util/` — 不碰

## 测试列表（41 项）

### 1. 链式续喂（1688 shop）
- `test_chain_feed_inserts_next_page_item` — 有新增 + hasMore → advance + 新 work_item
- `test_chain_feed_exhausted_when_no_shops` — 空页 → exhausted 不续喂
- `test_chain_feed_exhausted_when_no_has_more` — hasMore=false → exhausted 不续喂
- `test_chain_feed_continues_when_has_more_and_shops` — 有店铺有 hasMore → 不 exhausted，续喂

### 2. 链式续喂（1688 company）
- `test_company_chain_feed_inserts_next_page` — company: 前缀进度 + 新 work_item
- `test_company_chain_feed_exhausted_when_empty` — company: 空页 exhausted

### 3. discover 产出（1688 shop）— 含 mtop 握手
- `test_discover_inserts_new_categories` — 新类目逐条 INSERT
- `test_discover_skips_exhausted_categories` — 跳过已 exhausted
- `test_discover_skips_existing_pending_category` — 跳过已有 pending
- `test_discover_fallback_seeds` — 提取失败 → 兜底种子
- `test_discover_calls_mtop_handshake` — ensure_mtop_token 被调用

### 4. discover 产出（1688 company）
- `test_company_discover_inserts_prefixed_categories` — company: 前缀 keyword
- `test_company_discover_skips_exhausted` — 跳过 company: 前缀 exhausted
- `test_company_discover_fallback_seeds` — company: 前缀兜底种子

### 5. company: 前缀隔离
- `test_progress_keys_are_isolated` — 同一 keyword shop/company 进度互不干扰
- `test_exhausted_keys_filtered_by_prefix` — iter_active_categories(prefix="company:") 只返回 company: 行
- `test_company_prepare_seeds_only_prefixed` — company prepare 播种只产 company: 前缀 keyword

### 6. 失败补插
- `test_shop_refill_category` — shop category refill
- `test_shop_refill_discover` — shop discover refill
- `test_company_refill_category` — company category refill
- `test_company_refill_discover` — company discover refill

### 7. 幂等播种
- `test_shop_double_prepare_no_duplicates` — shop 两次 prepare 无重复
- `test_company_double_prepare_no_duplicates` — company 两次 prepare 无重复

### 8. CLI acquire
- `test_shop_acquire_returns_payload` — claim_next_eligible 返回 payload
- `test_shop_acquire_returns_none_when_empty` — 无货 None
- `test_shop_acquire_returns_discover` — discover payload
- `test_company_acquire_returns_payload` — company claim_next_eligible
- `test_company_acquire_returns_none_when_empty` — company 无货 None

### 9. validate discover 放行
- `test_shop_validate_discover_passes` — shop validate 放行 discover
- `test_shop_validate_category_checks_shops` — shop validate category 检查 shops
- `test_company_validate_discover_passes` — company validate 放行 discover
- `test_discover_full_pipeline_shop` — shop discover 三段式 fetch→validate→on_success

### 10. shop fetch 读 next_page + mtop 检查
- `test_fetch_reads_next_page_from_db` — category_progress.next_page=3 → fetch 第 3 页
- `test_fetch_defaults_to_page_1` — 无 progress → page_no=1
- `test_fetch_blocked_when_no_mtop` — 无 mtop → BLOCKED
- `test_fetch_discover_no_request` — discover fetch 不发网络请求

### 11. company fetch 读 next_page（company: 前缀）
- `test_company_fetch_uses_prefixed_progress` — company:前缀进度 → fetch 对应页
- `test_company_fetch_defaults_to_page_1` — company 无 progress → page=1
- `test_company_fetch_blocked_no_mtop` — company 无 mtop → BLOCKED

### 12. 类名兼容
- `test_shop_task_instantiable` — make_task("shop") → Alibaba1688ShopTask
- `test_company_task_instantiable` — make_task("company") → Alibaba1688CompanyTask

## TDD 证据（RED → GREEN）

1. **RED**: 先写 test_1688_feeder.py，运行失败（ImportError: cannot import Alibaba1688ShopTask）
2. **GREEN**: 实现 shop.py / company.py / __init__.py 重构，41/41 通过
3. **GREEN**: 全量 509 passed（468 基线 + 41 新增），无回归

## 自查发现

1. **company: 前缀隔离验证通过**: `test_progress_keys_are_isolated` 证明同一 keyword（女装）在 shop（keyword="女装"）和 company（keyword="company:女装"）的 category_progress 记录完全隔离，iter_active_categories(prefix="company:") 只返回 company: 行。
2. **discover 三段式验证通过**: `test_discover_full_pipeline_shop` 完整测试 fetch→validate→on_success，确保 C1 教训不会在 1688 重复（validate 正确放行 discover）。
3. **向后兼容**: `ShopTask` / `CompanyTask` 别名保留，`__init__.py` 的 `make_task` 路径不变，`test_summary_db_path.py` 等既有测试无需修改。
4. **无 ZERO_NEW_LIMIT**: 按 brief 裁定，1688 沿用现状 hasMore/空页 exhausted 判定，不引入 mic 的零新增保护。
5. **不碰文件清单**: `db.py`、`task.py`、`platform/`、`scraper/`、`util/` 均未改动。
