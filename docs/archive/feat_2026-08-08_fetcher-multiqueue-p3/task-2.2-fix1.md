# Fix Round 1 — Step 2.2（resume implementer）

你的 Step 2.2 任务 review 判定「需要修复」。reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.2-review.md

## 发现清单（逐字，按优先级）

### C1（Critical）— seed_x5sec 多站点路径 0 测试覆盖

`test_engine.py` 中 test_sites_nonempty_seed_x5sec 实际调 `_alloc_seed_kits(2)`（不带 sites 参数，走 CLI 路径）；test_sites_none_seed_x5sec_unchanged 也只测 CLI。**sites 非空 + seed_x5sec=True 的多站点 A/B 分配完全没被测试覆盖**，违反 brief 验收「单测覆盖 seed_x5sec 分支」。

要求：新增/修改测试——两站点（sites 非空）+ seed_x5sec=True → 断言返回 dict[site][worker] 结构、偶数 worker A 组（含 x5sec 的池）、奇数 worker B 组；CLI 路径 seed_x5sec 测试保留在现有 test_sites_none_seed_x5sec_unchanged。

### I2（Important）— Session 状态迁移脆弱（字段逐一拷贝）

browser.py 中 relaunch 后把 new_session 的 browser/channel/req_proxies/views/seed_kit/extra 逐一拷回旧 session——未来 Session 新增字段极易遗漏（散弹式修改风险）。

要求：给 Session 加集中迁移方法（如 `copy_state_from(other)`，集中定义哪些字段随 relaunch 迁移），relaunch 内改用它；或改为原地替换（session 对象不变，内部字段更新）——选实现清晰且测试覆盖的方案。

### I3（Important）— 缺 clear_needs_relaunch(site) 精确清除 API

实现用 `session.extra["needs_relaunch"] = {}` 全清（relaunch 是进程级，全清语义正确），但 brief 要求逐 site pop API（P3-3 SwapIP 两阶段可能需要在进程内单独清除某 site 标记）。

要求：BrowserManager 加 `clear_needs_relaunch(session, site)`（内调 pop(site, None)），与 mark_needs_relaunch 成对；ensure_site 的懒建消费保持全清（进程级 relaunch 语义）；新 API 有单测。

### M4（Minor）— test_relaunch_complete_clears_flag 不测生产代码

测试体只做 session.extra["needs_relaunch"].pop("1688", None) 断言，纯 dict 操作无生产代码触达。

要求：改用 I3 的 clear_needs_relaunch API（或删除，若被 I3 测试覆盖则删除冗余）。

### M5（Minor）— _alloc_seed_kits_single 参数无类型注解

补 seeds_dir/cfg 类型注解（与同文件其他方法一致）。

## 要求

1. 修复 C1/I2/I3/M4/M5
2. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
3. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.2-report.md 末尾（每条：改了什么、覆盖测试、命令、输出）
4. scoped commit（fetcher/fetcher/net/browser.py、fetcher/fetcher/core/session.py、fetcher/fetcher/control/engine.py、fetcher/tests/、task-2.2-report.md）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、report 已追加确认。
