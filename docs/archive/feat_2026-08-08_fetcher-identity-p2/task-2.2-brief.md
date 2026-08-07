# Step 2.2 brief — 隔离性单测（同 IP 两站点互不污染）

> 来源：PLAN.md Phase 2 Step 2.2。本文本是你的需求唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699

## 内容

新增 `fetcher/tests/test_identity_isolation.py`：同一裸 IP（如 `1.2.3.4`）两站点（`1688:` 与 `madeinchina:`）的隔离性断言。**SPEC §5 第 2、3 条达成 + 至少一轮定向破坏（防假阳性）**。

### 用例清单（①-⑥，全在临时库上跑，不碰生产库）

1. **Cookie 各落各桶、load 不串**：`IdentityStore(db, domain="1688.com").save("1688:1.2.3.4", [...])` 与 `IdentityStore(db, domain="made-in-china.com").save("madeinchina:1.2.3.4", [...])`（同一裸 IP 两站点，Cookie 值不同以区分）；断言 `load("1688:1.2.3.4")` 只含 1688 域 Cookie、`load("madeinchina:1.2.3.4")` 只含 made-in-china 域 Cookie、互不串。
2. **burn 一站不殃及另一站**：两桶各预置 Cookie；`store(burn "1688:1.2.3.4")` 后 1688 桶空、madeinchina 桶完好。
3. **ip_stats/ip_events 分行统计**：同裸 IP 两站点各 `record_event` / `ip_stat_request`，断言 `ip_events`/`ip_stats` 中 `1688:1.2.3.4` 与 `madeinchina:1.2.3.4` 是两行、互不影响（如只给 1688 记 block，madeinchina 行不受影响）。
4. **内存键分开（ip_req / budget_stuck）**：loop 簿记层或键级断言。参考 `fetcher/fetcher/control/loop.py`：`ctx.state["ip_req"]`（:91，dict 按 identity 计 n/since）、`self.budget_stuck`（:92，set）、`SeedBurnTracker.burn_ips`（`net/seeds.py:103`，set）。断言 `"1688:1.2.3.4"` 与 `"madeinchina:1.2.3.4"` 是**不同键**：如 `ip_req` 中给 1688 键计数不影响 madeinchina 键（get 不到或独立计数）；`budget_stuck`/`burn_ips` 加 1688 键后 madeinchina 键不在其中。构造方式自由（可直接操作 dict/set 断言键分离，或用 loop 簿记方法 `_bookkeep_request` 走真实路径——优先真实路径，键级断言兜底）。
5. **指纹参数同裸 IP 逐字一致**：`fingerprint_args(bare_identity("1688:1.2.3.4")) == fingerprint_args("1.2.3.4") == fingerprint_args(bare_identity("madeinchina:1.2.3.4"))`——md5 输入=bare ip，两站点同 IP 指纹相同（SPEC §3.5 裁定）。
6. **check_ip_fresh 对 `1688:1.2.3.4` vs `1.2.3.4` 判相等**：mock `_query_exit_ip_with_retry` 返回 `"1.2.3.4"`，`Session(identity="1688:1.2.3.4")` 与 `Session(identity="1.2.3.4")` 均不触发 relaunch（参照 test_browser_fresh.py 已有模式）；`"madeinchina:1.2.3.4"` 同。

### 定向破坏（防假阳性，至少一轮）

PLAN 要求「防假阳性证据：至少一轮定向破坏」。做法示例：把其中一处断言故意改反（如断言 `load("1688:1.2.3.4")` 含 madeinchina Cookie 或断言 `budget_stuck` 跨站连带），跑测试**亲眼看它红**（证明测试真的在检测隔离），再改回。RED 证据写入 report（命令 + 失败输出），GREEN 后再全量。

### 测试基础设施

- 临时库模式参照 `fetcher/tests/test_identity.py`（`tempfile.TemporaryDirectory` + `ShopDB(path)` + `IdentityStore(db, domain=...)`）；`FakeBrowserContext` 已有可直接 import 复用
- `check_ip_fresh` 参照 `fetcher/tests/test_browser_fresh.py`（`patch.object(mgr, "_query_exit_ip_with_retry", ...)`；`BrowserManager(config, store=MagicMock(), site_name="1688", log=...)`——**注意 site_name 必传**）
- 跑法：`cd fetcher && python -m pytest tests -x -q`（TDD 聚焦，commit 前全量）

## 背景

P2：identity 键已升级 `site:ip`（Step 1.3），close 域过滤与迁移已就位（Step 2.1）。本步是**证明隔离性的验收测试**——同 IP 两站点的 Cookie/簿记/内存键互不污染，SPEC §5 第 2、3 条。§3.3 说内存键随字符串自然分桶零改动，本步以测试固化该性质。

## 验收

- [ ] SPEC §5 第 2、3 条达成（含定向破坏 RED 证据）
- [ ] 全量无回归（`cd fetcher && python -m pytest tests -x -q` 全绿）

## 约束

- 只新增/修改 `fetcher/tests/` 下文件（不碰生产代码——本步纯测试；如发现生产代码缺陷，DONE_WITH_CONCERNS 上报而不是顺手改）
- 不碰生产库；不做 Step 3 内容（冒烟是下一步）
- **commit 纪律**：git add 显式列文件（禁止 -A/`.`）；commit 信息 `feat(identity-p2): Step 2.2 …`；自查 `git status` / `git diff --cached --stat`
- 注释中文、遵循既有测试模式

## 报告

完整报告写入 `docs/feat_2026-08-08_fetcher-identity-p2/task-2.2-report.md`：
- ①-⑥ 每条用例的断言与结果
- **定向破坏 RED 证据**（改反哪条、命令、失败输出）+ GREEN
- 全量测试结果（总数）、改动的文件、commit（短 SHA + 标题）
- 自查发现与疑虑
