# Task 4.2 Report — iter_active_categories 统一查询 + crawl_mic_shop 入注册表 + feeder 冒烟

> 分支：`feat/multiqueue-p3` | 日期：2026-08-08 | 状态：DONE

## 实现摘要

1. **`iter_active_categories` 统一查询**（`db.py`）：新增 `iter_active_categories(prefix="")` 方法，prefix 非空时通过 `LIKE` 过滤 keyword 前缀（如 `"company:"`），prefix 为空返回全部未采完类目，按 id 排序。`get_active_categories` 改为委托 `iter_active_categories()` + `_is_pinyin_slug` 过滤（向后兼容，行为一致）。

2. **`crawl_mic_shop` 入注册表**（`cli/main.py` `_build_registry`）：新增第 3 条队列，`topup=None`（feeder 队列），`domain_suffix=""`，`requires={"channel","browser"}`。

3. **`reset_daemon_state` 精确化**：只对 `topup is not None` 的队列做 `reset_in_progress`（feeder 队列跳过，它不产生 in_progress shops）。

4. **`_seed_category_items` 切到 `iter_active_categories`**（`madeinchina/shop.py`）：改为 `db.iter_active_categories()` + `_is_pinyin_slug` 过滤（与 `get_active_categories` 同口径）。

## 测试列表

### TDD 新增测试

| # | 测试 | 覆盖项 | 文件 |
|---|---|---|---|
| 1 | `test_iter_active_categories_returns_non_exhausted` | 未采完返回、exhausted 排除、id 排序 | test_madeinchina.py |
| 2 | `test_iter_active_categories_prefix_filter` | prefix="company:" 过滤、prefix="" 全量 | test_madeinchina.py |
| 3 | `test_get_active_categories_delegates_to_iter` | 拼音过滤回归（委托 iter_active_categories） | test_madeinchina.py |
| 4 | `test_iter_active_categories_empty_name_defaults_to_keyword` | name=NULL 回退为 keyword | test_madeinchina.py |
| 5 | `test_reset_skips_feeder_queues` | feeder 队列（topup=None）不触发 reset_in_progress | test_cli.py |

### 测试更新

| # | 测试 | 改动 | 文件 |
|---|---|---|---|
| 6 | `test_daemon_queues_dynamic_from_registry` | 新增 `assertIn("crawl_mic_shop")` | test_cli.py |

## TDD 证据

### RED → GREEN

1. **RED**：先写 5 个新测试 + 更新 1 个断言 → `python -m pytest tests/test_madeinchina.py tests/test_cli.py -v`
   - `test_iter_active_categories_*` (3 tests)：`AttributeError: 'ShopDB' object has no attribute 'iter_active_categories'`
   - `test_daemon_queues_dynamic_from_registry`：`AssertionError: 'crawl_mic_shop' not found`
   - `test_reset_skips_feeder_queues`：`AssertionError: 2 != 1`（feeder 队列的 `reset_in_progress("")` 误删了 other.example.com）

2. **GREEN**：实现 `iter_active_categories` + 注册表 crawl_mic_shop + reset 精确化 + 播种切到 iter_active_categories → **所有新测试通过**

3. **全量**：`cd fetcher && python -m pytest tests -q` → **468 passed, 2 subtests passed**（基线 463 + 净增 5）

## 冒烟取证

### 命令

```bash
cd fetcher
python -m fetcher daemon --db /tmp/smoke_p3_42.db --workers 1 --limit 8 -n 1 \
  --queues crawl_mic_shop --batch-rest 1 \
  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
  > docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/daemon-run.log 2>&1
```

### 结果摘要

| 检查项 | 结果 | 证据 |
|---|---|---|
| 启动播种 | ✅ | `播种 0 个 category item + 1 条 discover` |
| 启动重置跳过 feeder | ✅ | `0 个 in_progress 店铺 → pending（逐 site: ）` |
| discover 执行 | ✅ | 浏览首页+导航页 → 提取 ~360 类目 → INSERT category items |
| 类目页消费 | ✅ | `jgdbj` 第 1 页 → 提取 15 个供应商展厅 |
| progress 推进 | ✅ | `jgdbj` → next_page=2, pages=1, shops_found=15 |
| shops 落库 | ✅ | 15 条 `*.cn.made-in-china.com` 域名 status=pending |

完整分析见 `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/analysis.md`。

## 改动文件

| 文件 | 改动 |
|---|---|
| `fetcher/fetcher/db.py` | 新增 `iter_active_categories(prefix)`；`get_active_categories` 改为委托之 |
| `fetcher/fetcher/cli/main.py` | `_build_registry` 新增 `crawl_mic_shop`；`reset_daemon_state` 只对 topup 非 None 队列做 reset |
| `fetcher/fetcher/sites/madeinchina/shop.py` | `_seed_category_items` 切到 `iter_active_categories` + `_is_pinyin_slug`；`cat["slug"]` → `cat["keyword"]` |
| `fetcher/tests/test_madeinchina.py` | 新增 4 个 iter_active_categories/pinyin 回归测试 |
| `fetcher/tests/test_cli.py` | 新增 `test_reset_skips_feeder_queues`；更新 `test_daemon_queues_dynamic_from_registry` 断言 |
| `docs/.../smoke-step4.2/` | 冒烟日志 + 分析 |

## 自查

- ✅ brief 所有裁定均落实（iter_active_categories 统一查询+prefix、crawl_mic_shop 入注册表+topup=None、reset 仅 topup 队列、播种切 iter_active_categories + pinyin 过滤）
- ✅ `get_active_categories` 委托 `iter_active_categories` + `_is_pinyin_slug`（向后兼容，原有调用方无需改动）
- ✅ grep 确认无其他 `get_active_categories` 调用方（仅 `madeinchina/shop.py` 的 `_seed_category_items`）
- ✅ 未碰 platform/、fetcher/vendor/wa-check/、scraper/、util/
- ✅ --queues choices 自动含 crawl_mic_shop（注册表动态派生，Step 3.1 已实现）
- ✅ 全量 468 passed（基线 463 + 5 净增）
- ✅ 冒烟取证完整（播种→discover→类目页消费→progress 推进）
- ⚠️ 工作区有他人未提交改动，scoped add 仅按 brief 列出文件
