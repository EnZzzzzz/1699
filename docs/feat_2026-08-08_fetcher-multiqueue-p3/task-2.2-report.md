# Task 2.2 Report — needs_relaunch 状态位 + 种子池 (worker, site) 粒度

> 日期：2026-08-08 | 分支：feat/multiqueue-p3 | P3-2 Step 2.2

## 1. 实现摘要

### 1.1 needs_relaunch 状态位（`net/browser.py`）

- **存储**：`session.extra["needs_relaunch"]` = `dict[site, True]`（session.extra 是现成状态暂存区；SPEC 写作 session.state，实现落 extra 并注释对应）
- **API**：
  - `BrowserManager.mark_needs_relaunch(session, site)`：置位（SwapIP 两阶段第一步调用；P3-3 Step 3.2 接入）
  - relaunch 完成路径清除：`session.extra["needs_relaunch"] = {}`（进程级全清）
- **懒建消费**（`ensure_site` 入口）：检测 `needs_relaunch[site]` 为真 → 清除全部 site 标记（防递归）→ 调用 `self.relaunch()` 复用现有逻辑（全 view close_site 回写 + browser.close + launch 新进程）→ 新 session 状态迁回旧对象（session 引用不变）→ 继续正常懒建
- **进程级语义**：一次 relaunch 清除全部 site 的 needs_relaunch 标记（非每 site 各 relaunch）

### 1.2 种子池 (worker, site) 粒度（`control/engine.py`）

- `_alloc_seed_kits(self, workers, sites=None)`：
  - `sites=None`（CLI 单站点路径）：返回 `list[kit]`，行为逐字不变
  - `sites` 非空（daemon 多站点路径）：返回 `dict[site_name, list[kit]]`，逐站点按 `cookie_domain` 加载
- 提取 `_alloc_seed_kits_single()` 复用核心分配逻辑（CLI 与 daemon 共用）
- `seed_x5sec` A/B 实验在多站点路径同样适用（偶数 worker A 组）
- `engine.run()` 无需改动（`sites=None` 时返回 list，消费逻辑不变）

### 1.3 relaunch 复核

- Step 2.1 的 relaunch 路径完整：`session.close()` 全 view 回写 → `browser.close()` → `launch()` 新进程（含 `_exit_ip` 重建）→ 新 views。本 Step 的 ensure_site-consumed relaunch 复用同一逻辑，无缺漏。

## 2. 改动文件

| 文件 | 改动 |
|---|---|
| `fetcher/fetcher/net/browser.py` | +`mark_needs_relaunch()` 方法；`ensure_site()` 入口增加 needs_relaunch 懒建消费逻辑 |
| `fetcher/fetcher/control/engine.py` | `_alloc_seed_kits` 签名增加 `sites=None` 参数；提取 `_alloc_seed_kits_single()` 共用核心 |
| `fetcher/tests/test_needs_relaunch.py` | **新增**：9 个 needs_relaunch 测试（置位/清除/懒建消费/进程级语义/回写） |
| `fetcher/tests/test_engine.py` | **新增**：7 个种子池 (worker,site) 粒度测试（CLI 等价/多站点 dict/domain 过滤/seed_x5sec） |

## 3. 测试列表与 TDD 证据

### 3.1 needs_relaunch（9 tests, all GREEN）

| 测试 | 覆盖 |
|---|---|
| `test_mark_needs_relaunch_sets_flag_in_extra` | 置位写入 extra |
| `test_mark_needs_relaunch_multiple_sites` | 多 site 独立置位 |
| `test_relaunch_complete_clears_flag` | pop 清除（完成路径） |
| `test_ensure_site_triggers_relaunch_when_needs_relaunch_set` | 置位 → 触发 relaunch（browser.close + launch）且清除标记 |
| `test_ensure_site_no_relaunch_when_flag_not_set` | 未置位 → 正常懒建，不 relaunch |
| `test_ensure_site_no_relaunch_when_flag_for_other_site` | 其他 site 置位 → 本站正常懒建 |
| `test_ensure_site_relaunch_clears_all_site_flags` | 多 site 置位 → 一次 relaunch 全清（进程级） |
| `test_ensure_site_relaunch_writes_back_all_views_before_close` | relaunch 前全部现有 view Cookie 回写 |
| `test_ensure_site_relaunch_preserves_session_object_identity` | relaunch 后 session 对象引用不变 |

**RED→GREEN**：首次运行 5 FAILED（`mark_needs_relaunch` 不存在 + `ensure_site` 未消费标志）；实现后全部 GREEN。

### 3.2 种子池 (worker, site) 粒度（7 tests, all GREEN）

| 测试 | 覆盖 |
|---|---|
| `test_sites_none_returns_list_unchanged` | sites=None 返回 list（CLI 等价） |
| `test_sites_none_with_seeds_returns_list` | sites=None 有种子时仍返回 list |
| `test_sites_nonempty_returns_dict_of_lists` | sites 非空 → dict[site][list[kit]] |
| `test_sites_nonempty_per_worker_per_site_independent` | 每 (worker, site) 独立分配 + 越界 None |
| `test_sites_nonempty_cookie_domain_filter` | 不同 domain 调用 load_seed_kits 不同参数 |
| `test_sites_nonempty_seed_x5sec` | 多站点 seed_x5sec A/B 实验 |
| `test_sites_none_seed_x5sec_unchanged` | sites=None seed_x5sec 行为一致 |

**RED→GREEN**：首次运行 3 FAILED（`sites` 参数未接受 + 测试 setup 问题）；实现后全部 GREEN。

### 3.3 全量回归

```
cd fetcher && python -m pytest tests -q
395 passed, 2 subtests passed in 26.91s
```

基线 379 → 395（+16 new tests），0 回归。

## 4. 冒烟等价确认

引用 Step 2.1 冒烟证据 `smoke-step2.1/smoke-fix1-raw.txt`：旧 CLI `1688 contact` 直连路径（`--workers 1`、临时库 `/tmp`、+1 席内）正常运行（launch → Cookie 装载 → warmup → 滑块过证）。本 Step 的 `sites=None` 路径返回 list 行为逐字不变，CLI 路径不受影响。无需复跑。

## 5. 自查发现

- **无遗漏**：brief 列出的所有验收项均已覆盖（needs_relaunch 置位/清除/懒建消费、种子池映射与 CLI 等价、cookie_domain 过滤、seed_x5sec、relaunch 复核、冒烟等价）
- **无越界**：未动 db.py、control/loop.py、daemon_task.py、queue_router.py、strategies.py（SwapIP 两阶段留给 P3-3）
- **engine.run 未改动**：`_alloc_seed_kits(workers)` 调用点保持 sites=None 默认，返回 list，消费逻辑不变
- **ensure_site 防递归**：清除 needs_relaunch 在 relaunch/launch 之前，避免 ensure_site → relaunch → launch → ensure_site 的递归触发
- **session 引用保持**：ensure_site 触发的 relaunch 将新 session 状态迁回旧对象，调用方持有的 session 引用不变
