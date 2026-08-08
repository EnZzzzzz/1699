# Task 6.2 终审修复报告 — Engine._alloc_seed_kits 接线 sites（SPEC §3.6 种子粒度落地）

## 状态：DONE ✅

全量测试：523 passed（517 baseline + 6 new），2 subtests passed。

## 发现（终审原文）

`engine.py:211` `worker_kits = self._alloc_seed_kits(workers)` 未传 `self.sites`——`_alloc_seed_kits(workers, sites=None)` 方法本身已支持多站点（返回 `dict[site, list[kit]]`），但 `Engine.run()` 调用时始终走单站点分支。SPEC §3.6 要求种子身份池粒度改为「每 (worker, site) 一份」。实际影响：daemon 多站点时所有 site 共用首个 site 的 seed_kit，跨站 ensure_site 播种时错误 domain 的 Cookie 存入跨站 identity（不致命但污染 DB，与 SPEC 不符）。

## 实现摘要

### 改动文件

| 文件 | 改动说明 |
|---|---|
| `fetcher/fetcher/control/engine.py` | `run()` 在 multi-site 时传 `sites=list(self.sites.values())` 给 `_alloc_seed_kits`；`_worker` 新增 `per_site_kits` keyword-only 参数并透传给 CrawlLoop |
| `fetcher/fetcher/control/loop.py` | `CrawlLoop.__init__` 新增 `per_site_kits` 参数；`_bind_item_site` 跨站 ensure_site 时传入对应 `(worker, site)` 的 seed_kit |
| `fetcher/tests/test_engine.py` | 新增 5 个 TDD 测试（`EngineRunSitesWiringTest`） |
| `fetcher/tests/test_control_loop.py` | 新增 `SeedKitCaptureBrowserManager` + 1 个 TDD 测试 |

### 关键设计决策

1. **传递链**：`Engine.run() → _worker(per_site_kits=...) → CrawlLoop(per_site_kits=...) → _bind_item_site → ensure_site(seed_kit=site_seed_kit)`
2. **单站点路径不变**：`per_site_kits=None` → 行为逐字不变（不传 `sites` 给 `_alloc_seed_kits`，_worker 不设 per_site_kits）
3. **per_site_kits 结构**：`dict[site_name, kit|None]`，由 Engine.run() 从 `_alloc_seed_kits` 返回的 `dict[site, list[kit]]` 中按 worker 下标切片
4. **无 kit 时保持白板语义**：`per_site_kits.get(site_name)` 返回值可能为 None → `ensure_site(seed_kit=None)` 即为白板，与现状一致

### TDD 证据（6 RED → 6 GREEN）

| 测试 | 验证点 |
|---|---|
| `test_run_with_sites_calls_alloc_seed_kits_with_sites` | Engine.run() multi-site → _alloc_seed_kits 收到 sites list |
| `test_run_single_site_does_not_pass_sites` | Engine.run() 单站点 → _alloc_seed_kits 不传 sites（行为不变） |
| `test_worker_passes_per_site_kits_to_loop_in_multi_site` | _worker 把 per_site_kits dict 传给 CrawlLoop |
| `test_worker_per_site_kits_none_in_single_site` | 单站点 loop 不收 per_site_kits |
| `test_multi_site_per_worker_kits_structure` | 有种子时每 worker 得到正确的 init kit + per_site_kits |
| `test_bind_item_site_passes_seed_kit_to_ensure_site` | 跨站 ensure_site 播种拿到对应 site 的 kit |
