# 终审修复 — Engine._alloc_seed_kits 接线 sites（SPEC §3.6 种子粒度落地）

终审（docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-fix1-review.md 之后的 final review）发现 1 个合并前必修的 Important：

## 发现（终审原文）

`engine.py:211` `worker_kits = self._alloc_seed_kits(workers)` 未传 `self.sites`——`_alloc_seed_kits(workers, sites=None)` 方法本身已支持多站点（返回 dict[site, list[kit]]），但 `Engine.run()` 调用时始终走单站点分支。SPEC §3.6 要求种子身份池粒度改为「每 (worker, site) 一份」。实际影响：daemon 多站点时所有 site 共用首个 site 的 seed_kit，跨站 ensure_site 播种时错误 domain 的 Cookie 存入跨站 identity（不致命但污染 DB，与 SPEC 不符）。

## 要求

把 (worker, site) 种子粒度的接线补完整（TDD）：

1. **Engine.run / _worker**（control/engine.py）：
   - `worker_kits = self._alloc_seed_kits(workers, sites=list(self.sites.values()) if self.sites else None)`（多站点返回 dict[site, list[kit]]；单站点返回 list，行为逐字不变）
   - `_worker` 参数适配：单站点传单个 kit（现状）；多站点传 per-site kits 结构，并经 loop 传给浏览器层——设计自由，但必须保证：
     - 单站点 CLI/daemon 路径行为不变（现有测试不破）
     - 多站点时 BrowserManager.launch（初始 view）用该 worker 对应初始 site 的 kit；**跨站 ensure_site(site) 播种用该 (worker, site) 的 kit**（读 ctx 传递链，可在 ctx.state 或 session.extra 挂 per-site kits dict，loop._bind_item_site 调 ensure_site 时传入）
2. **loop/browser 传递链**（control/loop.py、net/browser.py 如需要）：跨站 ensure_site 的 seed_kit 参数传入 (worker, site) kit；无 kit（None）时保持现状白板语义
3. **TDD 单测**（tests/test_engine.py 或新增）：
   - 多站点装配（sites dict）→ _alloc_seed_kits 返回 dict[site][worker] 且 Engine 实际调用传了 sites（mock 断言）
   - 单站点装配 → 返回 list 现状不变
   - 跨站 ensure_site 播种拿到对应 site 的 kit（假浏览器捕获 ensure_site 调用参数）
4. 全量测试（cd fetcher && python -m pytest tests -q）绿（基线 517 passed）
5. scoped commit（fetcher/fetcher/control/engine.py、fetcher/fetcher/control/loop.py、fetcher/fetcher/net/browser.py 如改动、fetcher/tests/、docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.2-report.md）

## 汇报
报告写 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.2-report.md（实现摘要 + TDD 证据 + 改动文件）。回复 10 行以内：commit sha + 标题、一行测试总结、report 路径。
