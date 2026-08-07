# PLAN — fetcher daemon 骨架（P0）

> 需求与设计唯一来源：同目录 SPEC.md（上游：docs/scheduler-architecture.md §10 P0）
> Step checkbox 只有验收通过后才能标 done，并随代码 commit；执行细节记 ledger.md。

## Phase 总览

| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
|---|---|---|---|---|
| P1 | work_items 存储层：表 + 4 个 DB 方法 + 单测 | 3 | 无 | pending |
| P2 | daemon 执行链路：DaemonTaskProxy + CLI 子命令 + Engine 装配 + 单测 | 4 | P1 | pending |
| P3 | 运行时冒烟与等价性验证 + 文档收尾 | 3 | P2 | pending |

---

## Phase 1 — work_items 存储层

**准入条件**：无（可随时开工）。
**完成标准**：新增 DB 方法单测全绿；既有测试无回归。本 Phase 无运行时行为变化，不要求冒烟。

### Step 1.1 确认 item 访问契约（SPEC §4 假设 1）
- 预估：10 min · 依赖：无 · 状态：done
- 内容：通读 `fetcher/sites/alibaba1688/contact.py` 中 `fetch/validate/on_success/label/cold_start` 对 item 的全部访问点；grep `engine.py`/`loop.py`/`task.py` 确认无 `isinstance(...ContactTask)` 之类对具体 task 类型的判断（SPEC §4 假设 2）。
- 交付物：SPEC §4 表格回填结论（dict 可用 / 需 SimpleNamespace）；若发现 isinstance 判断，记录位置并在 Step 2.2 处理。
- 验收：
  - [x] SPEC §4 假设 1、2 的「依据」列从「推断」改为「已读码验证」，结论明确

### Step 1.2 work_items 表 DDL + ShopDB 四个方法
- 预估：15 min · 依赖：1.1 · 状态：done（与 1.3 合并执行，commit 8fcfe91）
- 内容：`fetcher/db.py` 的 `SCHEMA` 加 work_items 表与索引（SPEC §3.2 DDL）；新增 `topup_contact_work_items` / `claim_work_item` / `finish_work_item` / `reset_claimed_work_items`，严格仿 `claim_pending_shops`（`db.py:286-318`）的 `BEGIN IMMEDIATE` 短事务模式；时间戳沿用模块内 `_now`。
- 交付物：上述代码。
- 验收：
  - [x] 四个方法签名与 SPEC §3.2 表格一致
  - [x] 既有 `python -m pytest tests -x -q` 无回归

### Step 1.3 存储层单测
- 预估：15 min · 依赖：1.2 · 状态：done（与 1.2 合并执行，commit 8fcfe91）
- 内容：新增 `tests/test_work_items.py`（临时 sqlite，仿 `test_contact_task.py` 基建）。用例：① top-up 后 shops 标 in_progress 且 work_items 行生成、重复 top-up 不产生重复行（pending 过滤）；② 两个并发 claim 拿不到同一行（线程级或顺序模拟）；③ finish 落终态+时间戳；④ reset_claimed 把 claimed 重置为 pending；⑤ 空 shops 时 top-up 返回 0。
- 交付物：测试文件。
- 验收：
  - [x] 5 个用例全绿
  - [x] 先红后绿（TDD：测试在方法实现前已写出并亲眼见失败——若 1.2 先行，则本 Step 须能说明每个断言对应的行为）

---

## Phase 2 — daemon 执行链路

**准入条件**：Phase 1 完成标准达成。
**完成标准**：单测全绿；`python -m fetcher daemon --help` 正常；**运行时冒烟**：无代理直连模式 `python -m fetcher daemon --limit 2`（临时 DB + 预置 2 条 shops pending 种子数据）能跑通完整链路（真实浏览器、真实 1688 访问），work_items 落终态。

### Step 2.1 DaemonTaskProxy 实现
- 预估：15 min · 依赖：Phase 1 · 状态：done（commit f6034dd）
- 内容：新增 `fetcher/control/daemon_task.py`：`DaemonTaskProxy(inner, queue, site, domain_suffix)`，实现 Task 协议；`acquire_item` 按 SPEC §3.3 三段式（claim → top-up+notify → condvar wait 30s 自醒查 stop）；`after_item` 透传后 `finish_work_item`；其余 `__getattr__` 透传 inner（类属性 `unit/batch_unit/cold_start_before_acquire/ip_request_budget` 显式转发）。
- 交付物：daemon_task.py；若 Step 1.1 发现 isinstance 判断，此处一并给出兼容处理。
- 验收：
  - [x] proxy 不显式 import ContactTask（对任意 inner task 成立）
  - [x] stop 置位时 acquire_item 最多 30s 内返回 None

### Step 2.2 proxy 单测
- 预估：15 min · 依赖：2.1 · 状态：done（commit 1af732b）
- 内容：新增 `tests/test_daemon_task.py`（仿 `test_control_loop.py` 的 FakeBrowser 基建 + 临时 DB）。用例：① 有货→claim→返回 payload dict；② 空队列→自动 top-up→返回；③ stop 置位→wait 退出返回 None（用极小 wait 超时注入）；④ after_item 正确写 work_items 终态；⑤ 与 CrawlLoop 联跑：loop 跑完 N 项后队列空、stop 置位、loop 正常退出且 stats 正确。
- 交付物：测试文件。
- 验收：
  - [x] 5 个用例全绿（先红后绿）

### Step 2.3 CLI daemon 子命令
- 预估：10 min · 依赖：2.1 · 状态：done（commits 24cfe7d, e377a29）
- 内容：`cli/main.py` 顶层加 `daemon` parser（`add_common_args()` 全套）；`main()` 加 `args.site == "daemon"` 分支：get_site("1688") → make_task("contact") → DaemonTaskProxy 包装 → 复用 provider/policy 装配 → Engine.run()；daemon 启动时依次调 `reset_claimed_work_items` + `reset_in_progress`（SPEC §3.3 状态流）。
- 交付物：main.py 改动。
- 验收：
  - [x] `python -m fetcher daemon --help` 输出正常
  - [x] 既有子命令（1688 shop/contact/company、yiwugo）--help 与行为无变化
  - [x] `main()` daemon 分支装配参数与 site 分支逐项一致（provider/policy/Engine 参数）

### Step 2.4 直连冒烟脚本与执行
- 预估：15 min · 依赖：2.3 · 状态：done（无代码 commit，证据见 task-2.4-report.md）
- 内容：临时 DB 预置 2 条 shops pending（手工 SQL 或小脚本），直连模式（无代理）`python -m fetcher daemon --limit 2 --headed`（有头便于观察）；同时验证空队列挂起：跑完后不清数据再启动一次，观察 30s+ 不退出、CPU≈0，Ctrl+C 后 30s 内干净退出。
- 交付物：冒烟记录（命令、输出要点、DB 核查结果）写入 ledger.md。
- 验收：
  - [x] 2 条 work_items done、shops done、contacts 落库
  - [x] 空队列挂起 + 信号退出行为符合 SPEC §5 第 4 条

---

## Phase 3 — 等价性验证与收尾

**准入条件**：Phase 2 完成标准达成。
**完成标准**：代理模式等价性对比通过（SPEC §5 第 2、3 条）；文档同步完成。

### Step 3.1 代理模式等价性对比
- 预估：15 min（不含实际跑数时间）· 依赖：Phase 2 · 状态：done（走查，证据见 task-3.1-report.md）
- 内容：准备一批 pending shops（≥40 条），对半分两组：A 组旧 CLI `1688 contact --proxy --limit 20`、B 组 daemon `--proxy --limit 20`，相同节奏参数；对比每分钟请求数、成功率、contacts 字段完整度。
- 交付物：对比数据与结论写入 ledger.md。
- 验收：
  - [x] SPEC §5 第 2、3 条达成（第 2 条按变更记录放宽为「全部落正确终态」）
  - [x] 平台服务保持运行期间各页面/API 无异常（SPEC §4 假设 3 回填：平台未运行，本项不适用）

### Step 3.2 文档同步
- 预估：10 min · 依赖：3.1 · 状态：done（commit 56953e9）
- 内容：`docs/scheduler-architecture.md` §10 P0 行标注完成（链接本目录）；`fetcher/README.md` 的 CLI 用法段补 daemon 子命令；AGENTS.md §1 fetcher 说明补一句 daemon 模式。
- 验收：
  - [x] 三处文档更新随代码同 commit

### Step 3.3 终审与归档准备
- 预估：10 min · 依赖：3.1、3.2 · 状态：pending
- 内容：按 subagent-driven-development 做全分支终审（diff 全量过一遍：是否最小改动、旧路径是否零改动、注释是否与行为一致）；ledger.md 补全。
- 验收：
  - [ ] 终审 findings 清零或转 issue（issue-create 规范）
  - [ ] 旧代码路径（cli site 分支 / CrawlLoop / ContactTask）diff 为零

---

## 冲突扫描（呈交前自查）

**PLAN 内部**：Step 1.2 与 1.3 的 TDD 顺序有张力（实现先于测试）——裁定：允许 1.2/1.3 合并执行，但每个方法必须有对应失败-通过记录；1.3 验收已注明。Step 2.4 直连访问 1688 可能触风控——裁定：仅 2 条、有头、可人工过滑块，风险可接受，且等价性结论以 3.1 代理模式为准。

**PLAN vs 代码库现状**：
- `Engine` 被 `cli/main.py` 唯一装配，P0 不改 Engine 本体，无消费方迁移问题。
- `ContactTask` 的行为经 proxy 透传复用，旧 CLI 路径 diff 必须为零（Step 3.3 验收兜底）。
- shops 状态机的两个写入点（top-up 标 in_progress / on_success 落终态）与现状完全一致，无第二写入者引入。
- `SCHEMA` 加表是幂等 DDL，既有库文件打开即自动建表，不影响 platform 侧（其访问走只读连接+防御性探测）；SPEC §4 假设 3 已在 3.1 安排验证。
- `reset_in_progress` 在 daemon 启动时调用会重置所有 in_progress shops——与现有 CLI 启动语义相同（既有行为），但**若旧 CLI 任务与 daemon 同时跑会互相重置**：裁定为约束文档化（README 注明 daemon 与旧 CLI 不同站同跑、同站互斥），P0 不加锁。

**PLAN vs 外部依赖**：无新增第三方依赖；Playwright/青果/CloakBrowser 用法零变化。唯一未验证的外部行为是 SPEC §4 假设 5（长跑隧道缓存），已显式排除出 P0 验收。
