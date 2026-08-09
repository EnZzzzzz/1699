# SDD ledger — plan: docs/feat_2026-08-09_fb-discovery-group-feed/PLAN.md

## 执行前环境事实（2026-08-09 验收记录）

- 分支：feat/facebook-daemon-integration（非 main，符合分支要求）
- 工作区存在另一条工作线（daemon-headed-queues）的未提交改动：
  runner.py(_derive_batch_status)、platform/server/tests/test_batch_tasks.py、
  platform/start.sh、AGENTS.md、platform/web/src/pages/tasks/TaskFormDialog.tsx、
  docs/archive/feat_2026-08-09_daemon-headed-queues/
  → 与本 feature 无关，执行中不得回退/覆盖；commit 策略待用户裁决。
- Agent 工具不支持显式指定模型（skill 要求做不到），implementer/reviewer 均为
  coder 默认模型；修复循环第 4-5 轮换全新 implementer 的规则保留。

## Step 进度（todo，按 PLAN 逐 Step）

- [ ] Step 1.1 DB 前置：fb_groups 建表 + save_fb_posts + upsert_fb_groups（TDD）
- [ ] Step 1.2 FetchDdgSerp 原子 + 纯函数（TDD）
- [ ] Step 1.3 FbDiscoverTask（TDD）
- [ ] Step 1.4 discover_fb 队列注册（TDD）
- [ ] Step 1.5 发现层运行时冒烟（真实 DDG）
- [ ] Step 2.1 FbGroupTask（TDD）
- [ ] Step 2.2 crawl_fb_group 队列注册（TDD）
- [ ] Step 2.3 FbPostTask.on_success 群 upsert 补位（TDD）
- [ ] Step 2.4 群采集运行时冒烟
- [ ] Step 3.1 runner BATCH_TYPES + enqueue 分支（TDD）
- [ ] Step 3.2 app/db.py enqueue 双函数（TDD）
- [ ] Step 3.3 api/tasks.py TaskParams 四字段
- [ ] Step 3.4 平台冒烟
- [ ] Step 4.1 lib/api.ts 类型
- [ ] Step 4.2 task-ui.tsx
- [ ] Step 4.3 TaskFormDialog.tsx 两独立表单分支
- [ ] Step 4.4 Tasks.tsx BATCH_TYPE_NAMES
- [ ] Step 4.5 前端运行时冒烟
- [ ] Step 5.1 端到端闭环冒烟
- [ ] Step 5.2 全量回归
- [ ] Step 5.3 文档同步
- [ ] Step 5.4 终审 + 归档

## 冲突扫描结论（skill §5，执行前批量裁定）

1. **commit 策略（待用户裁决，阻塞 Step 3.1+）**：daemon-headed-queues 未提交改动
   与 feature 共享文件：runner.py（_derive_batch_status）、test_batch_tasks.py（+34 行）、
   start.sh、TaskFormDialog.tsx、AGENTS.md。Step 3.1+ 的 commit 会把这些改动混进
   feature commit。建议：用户先单独提交 daemon-headed-queues 工作线，再开始
   feature 的 Step commit。→ 已随本 ledger 一次性呈交用户裁决。
2. **SPEC §6.5 start.sh 无对应 PLAN Step**（PLAN gap）：SPEC 要求 start.sh 追加
   BRIGHTDATA_API_KEY/APIFY_TOKEN pass-through，但 PLAN 无显式 Step → 并入
   Step 3.4（平台冒烟，重启后端必经 start.sh），brief 中注明，与已有 --headed/
   WA_CHECK_ACCOUNTS 改动合并而非覆盖。
3. **upsert_fb_groups source 语义裁定**：SPEC §5.6 签名未含 source，但 §4.1 列注释
   声明 source ∈ {ddg, fb_post}。裁定：upsert_fb_groups 的 group 条目可带可选
   "source" 键，缺省 "ddg"；FbPostTask（Step 2.3）传 "fb_post"。已写入 brief。
4. **task-ui.tsx paramsSummary 分支顺序**：fb_discover/fb_group 的自定义摘要分支须
   置于既有 BATCH_TYPES 集合检查之前（否则落入通用 limit 摘要），Step 4.2 brief 注明。
5. **spike 复核（Step 1.1）已完成**：协调者 2026-08-09 实测 `html.duckduckgo.com/
   html/?q=site:facebook.com/groups 外贸 whatsapp&s=10` → 200、33KB、含 result__a、
   无 anomaly。复核结论由 Step 1.1 implementer 回填 SPEC §8.1（分页行依据），
   证据见本 ledger。

## 执行环境事实（子代理派发用）

- 派发机制：`pi --no-session -p`（无 subagent 扩展，用 CLI 子进程隔离上下文；
  模型显式指定 deepseek-v4-flash（经济）/ deepseek-v4-pro（标准/终审））。
- 工作目录：仓库根 /Volumes/DataDrive/proj/public/1699（AGENTS.md 自动装配）。
- 实现者需 TDD skill（--skill 显式加载）；reviewer 不重跑测试。
- 未提交的 daemon-headed-queues 改动：任何子代理不得 `git add -A`/`git commit -am`，
  只准精确 add 自己的文件。

## 2026-08-09 执行启动（用户授权：commit 策略由我裁决）

- 裁决：方案 A——先单独提交 daemon-headed-queues 工作线，再开始 feature Step commit。
- commit `dbab0da`（独立，7 files）：start.sh 有头/WA_CHECK_ACCOUNTS、runner.py
  零项停止兜底、test_batch_tasks.py +2、AGENTS.md/TaskFormDialog 文案。
- 工作区现仅剩本 feature 的 docs/（untracked）。
- Step 1.1 BASE = `dbab0da`。

## Step 1.1 执行记录

- implementer commit `b401560`（DONE，7/7 新测 + 17/17 回归）
- reviewer：spec ✅，3 Important + 4 Minor，Step 质量"通过"（Important 建议 merge 前修）
- Minor 记 deferred：① 两函数相似 for-loop 可抽 _batch_insert_or_ignore（YAGNI 暂缓）
  ② 缺空 url 条目测试 ③ 缺 group_id None 测试 ④ docstring 质量高（无问题）
- 修复循环 round 1：3 个 Important 派发（source 空串语义过宽 / status DEFAULT 契约未
  固化为断言 / 去重测试缺 source 不变验证）
- Step 1.1 fix round 1/5（3 addressed, 0 open — source 语义收窄 + schema 契约测试 +
  source 不变断言; commits b401560..96129f8），re-review 干净
- Step 1.1: complete (commits dbab0da..96129f8, review clean)
