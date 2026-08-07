# PLAN — identity (site, IP) 分桶（P2）

> 需求与设计唯一来源：同目录 SPEC.md（上游：docs/scheduler-architecture.md §7/§10 P2）
> Step checkbox 只有验收通过后才能标 done，并随代码 commit；执行细节记 ledger.md。

## Phase 总览

| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
|---|---|---|---|---|
| P1 | 读码回填 + 核心改造（注入点/辅助函数/隐藏点修正）+ 既有测试更新 | 3 | 无 | done ✅ |
| P2 | Cookie 域过滤收紧 + DB 迁移 + 隔离性单测 | 2 | P1 | pending |
| P3 | 等价性冒烟 + 文档 + 终审 | 2 | P2 | pending |

---

## Phase 1 — 读码回填 + 核心改造

**准入条件**：无。
**完成标准**：SPEC §4 假设 1、2 回填「已读码验证」；核心改造完成、既有测试全部适配通过。本 Phase 无运行时行为变化（键格式变化对单站点逻辑透明），不做冒烟。

### Step 1.1 读码回填（SPEC §4 假设 1、2）
- 预估：10 min · 依赖：无 · 状态：done ✅
- 内容：① 读 `fetcher/fetcher/sites/__init__.py` 与两个站点插件，确认 engine 的插件对象上能拿到站点注册名的确切字段（回填 SPEC §3.1）；② 生产库**只读** `SELECT domain, COUNT(*) FROM cookies GROUP BY domain` + 各站点 cookie_domain，回填 SPEC §3.4 的 domain→site 迁移映射确切清单（含未覆盖域的处置）；③ 顺带确认 `net/browser.py:233` identity 诞生点的确切代码形态（回填 SPEC §3.1 行号）。
- 交付物：SPEC 回填 commit；report 附摘录。
- 验收：
  - [x] SPEC §4 假设 1、2 依据列改「已读码验证」，映射清单完整

### Step 1.2 辅助函数 + 隐藏点修正（§3.3 清单 #1-#6）
- 预估：15 min · 依赖：1.1 · 状态：done ✅
- 内容：`core/session.py` 加 `bare_identity`/`is_direct`；按 §3.3 表修正 6 处（browser.py:196、loop.py:451、atoms/identity_ops.py:25、db.py:684、db.py:772、browser.py:299 指纹传参改 bare_identity）；TDD 先写这两个函数的测试。
- 交付物：代码 + 测试。
- 验收：
  - [x] 6 处修正与 §3.3 表一致；SPEC §5 第 6 条 grep 达成（此阶段对尚无前缀的库行为不变——bare_identity 无前缀原样返回）
  - [x] 全量无回归（TDD 先红后绿）

### Step 1.3 identity 诞生点拼前缀 + engine 注入 + 既有测试键格式更新
- 预估：15 min · 依赖：1.2 · 状态：done ✅
- 内容：engine `_make_browser_manager` 传 site 注册名；`browser.py` launch 拼 `f"{site}:{exit_ip}"`（直连 `f"{site}:direct"`，找到 identity 赋值的全部点——含直连分支与 relaunch）；更新 `tests/test_identity.py`、`tests/test_control_loop.py` 等键格式断言（探索报告 §7 清单）；`engine.py` 种子日志等含 identity 的输出无需改（字符串自然带前缀）。
- 交付物：代码 + 测试更新。
- 验收：
  - [x] 拼键只出现在诞生点一处（grep 证据）
  - [x] 全量无回归；既有测试的语义断言（隔离/burn/统计）在带前缀键下仍成立

---

## Phase 2 — Cookie 收紧 + DB 迁移 + 隔离性单测

**准入条件**：Phase 1 完成。
**完成标准**：SPEC §5 第 2、4 条达成；全量绿。本 Phase 无运行时冒烟（P3 做）。

### Step 2.1 Session.close 域过滤 + _migrate 前缀迁移
- 预估：15 min · 依赖：P1 · 状态：pending
- 内容：`Session.close()` 回写按 store.domain 过滤（与 save_from_context 同语义；store 为 None 时不过滤——现状即无回写，保持）；`db.py` `_migrate()` 按 SPEC §3.4 回填的映射清单加幂等迁移（探测→UPDATE，逐映射一条）。
- 交付物：代码 + 单测（close 过滤行为；迁移幂等：旧键库→迁移→新键可 load→再迁移零变化；无法映射的域保持原样）。
- 验收：
  - [ ] SPEC §5 第 4 条达成
  - [ ] 全量无回归（TDD 先红后绿）

### Step 2.2 隔离性单测
- 预估：15 min · 依赖：2.1 · 状态：pending
- 内容：新增 `fetcher/tests/test_identity_isolation.py`：同一裸 IP（如 1.2.3.4）两站点（1688:/madeinchina:）——① Cookie 各落各桶、load 不串；② burn 一站另一站完好；③ ip_stats/ip_events 分行统计；④ 内存键（ip_req/budget_stuck）分开（经 loop 簿记或键级断言）；⑤ 指纹参数同裸 IP 逐字一致（md5 输入=bare ip）；⑥ check_ip_fresh 对 `1688:1.2.3.4` vs `1.2.3.4` 判相等。
- 验收：
  - [ ] SPEC §5 第 2、3 条达成（防假阳性证据：至少一轮定向破坏）
  - [ ] 全量无回归

---

## Phase 3 — 等价性冒烟 + 文档 + 终审

**准入条件**：Phase 2 完成。
**完成标准**：SPEC §5 全部达成；终审通过。

### Step 3.1 等价性冒烟
- 预估：15 min（不含跑数）· 依赖：P2 · 状态：pending
- 内容：临时库预置 2 条 shops pending，`python -u -m fetcher daemon --db /tmp/ident_smoke.db --workers 1 --limit 2 --headed` 直连跑通；核查：cookies 表出现 `1688:direct` 桶（无裸 `direct` 新行）、行为与 P1 一致（日志口径、contacts 落库）；平台正则兼容断言（python -c 跑 SPEC §4 假设 4 的正则对 `identity=1688:1.2.3.4` 与 `identity=madeinchina:direct` 匹配）；生产库零污染核查（基线对照法，参照前两次冒烟；**注意**：本冒烟只用临时库，不动生产库迁移——生产库的 _migrate 由首次新代码进程自然触发，属预期行为，记录在 report）。
- 交付物：report 含命令/输出/SQL 证据。
- 验收：
  - [ ] SPEC §5 第 5 条达成
  - [ ] 平台正则兼容结论

### Step 3.2 文档同步 + 终审
- 预估：10 min · 依赖：3.1 · 状态：pending
- 内容：`docs/scheduler-architecture.md` §10 P2 行标完成、§7 更新（指纹修正、席位证据升级、BrowserContext 移至 P3 的说明）；AGENTS.md 如涉及 identity 说明则同步；README 补迁移的部署窗口提示（活爬虫停跑时部署新代码）；ledger 补全；全分支终审。
- 验收：
  - [ ] 文档更新随代码同 commit
  - [ ] 终审通过：隐藏点清单（§3.3）逐项 diff 核实、单站点等价性成立

---

## 冲突扫描（呈交前自查）

**PLAN 内部**：Step 1.2 先修比较点（bare_identity 对无前缀键原样返回）→ 1.3 再引入前缀键，中间态安全（顺序有依赖，不可对调）。Step 2.1 的迁移依赖 1.1 的映射清单回填，准入已串好。

**PLAN vs 代码库现状**：
- `identity` 的全部使用点已由探索报告穷尽（grep `\.identity` + 7 个隐藏点），§3.3 表全覆盖；终审复核 grep 兜底。
- 旧代码进程与新代码进程并存期（部署窗口）：旧进程写裸键、新进程读不到旧裸键 Cookie（按白板）——SPEC §3.4 运维注意已写明，README 提示在 Step 3.2。
- 平台正则（runner.py:137 / task-ui.tsx:112）不改代码，Step 3.1 验证兼容。
- `ip_stats.identity` 是 PRIMARY KEY——拼前缀方案不动 schema，规避了 SQLite 不能改 PK 的重建成本（探索报告已论证不选加列方案）。
- madeinchina 活爬虫在跑：它们写裸键 Cookie（made-in-china.com 域）；P2 合并后首次新进程打开生产库会把这些行迁成 `madeinchina:` 前缀——旧代码活爬虫再读就读不到（白板重启一次）。这是 SPEC §3.4 已声明的部署窗口问题，必须在合并前向用户明示。

**PLAN vs 外部依赖**：无新依赖。CloakBrowser 席位证据已升级为包源码证据（SPEC §3.6），P2 无多 context 动作，无实测阻塞项。
