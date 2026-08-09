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

## Step 1.2 执行记录

- implementer commit `274a409`（DONE_WITH_CONCERNS：① OK results 保留 kind=None 非 FB
  条目不过滤——与 SPEC「返回全部有机结果」一致，reviewer 确认合规；② sample_max<60 抬到
  地板——防 uniform ValueError，合理；③ sample_max 缺省 sample_min'+20——SPEC 未定义，
  可接受）
- reviewer：spec ✅，1 Important（or 反模式）+ 4 Minor
- Minor 记 deferred：① 5xx 测试未断言节奏 wait ② RESULT_A_RE 用 re.S 的注释 ③
  _http_get timeout 类型标注 int|float ④ 双 max 冗余
- 修复循环 round 1：Important「or 吞显式 0」派发
- Step 1.2 fix round 1/5（1 addressed, 0 open — or 吞显式 0 反模式三处修正; commits
  274a409..83c75e2），re-review 干净；re-review 补 Minor（非数值输入 ValueError 边缘路径，
  记 deferred 留终审）
- Step 1.2: complete (commits 4600ca1..83c75e2, review clean)

## Step 1.3 执行记录

- implementer commit `5dff797`（DONE，21 新增 + 42 fb + 29 wa + 720 全量回归）
- reviewer：spec ✅，0 Critical/Important，3 Minor
- Minor 记 deferred：① 空 results 的 set_status 只传 empty 未传 ok/failed（快照完整性，
  协调者裁定 8 字面对齐）② 全 kind=None 条目按 ok 计（报告已记录理由，接受）③
  _make_atom 不缓存（与 WaCheckTask 既有模式一致，非本 Step 引入）
- Step 1.3: complete (commits ab27fab..5dff797, review clean)

## Step 1.4 执行记录

- implementer commit `59812e1`（DONE，test_cli_fb.py 5/5 + 42 fb + 721 全量）
- reviewer：spec ✅，0 Critical/Important，1 Minor
- Minor 记 deferred：test_cli_fb.py test_queues_choices_accept_fb 命名过泛（只断言
  crawl_fb_post，非本 Step 引入；discover_fb 由 test_discover_fb_registered 覆盖）
- Step 1.4: complete (commits d85f774..59812e1, review clean)

## Step 1.5 冒烟记录（2026-08-09 21:58，BLOCKED）

- 临时 DB：/tmp/fb_smoke_1786283750/1688.db（ShopDB 初始化建表，2 条 work_items 就绪）
- daemon：`python -u -m fetcher daemon --queues discover_fb --local-workers 1`，PID 76730（首）/77134
  （-u 重启），有头观察：无浏览器窗口弹出（local 消费者，符合预期）
- **阻断发现（代码/环境事实不匹配）**：FETCHER_DB_PATH 对 daemon **无效**——`config_from_args`
  （fetcher/cli/main.py:128）只读 `--db`（默认 None），`RunConfig.resolved_db_path()`
  （core/context.py:76）在 None 时回退 `DEFAULT_CACHE_DIR/1688.db` = **生产库 .cache/1688.db**；
  FETCHER_DB_PATH 仅 fetcher/db.py 模块级 DB_PATH（ShopDB 无参构造）读取，daemon 全程显式
  传 config.resolved_db_path() 不经过它。日志佐证：`[daemon] 队列 discover_fb: 待补货店铺
  3164 个`（discover_fb 无 topup，不该有店铺计数）、`待认领工作项 0 个`（生产库无
  discover_fb 队列）
- **附带损伤（已止损，自愈）**：两次 daemon 启动对生产库执行了
  `reset_claimed_work_items()`（启动崩溃恢复路径）——首次 1 个、二次 7 个 claimed → pending；
  生产 daemon（PID 34402，`--workers 1 --headed`）重新认领（FIFO 自愈）；smoke 的 local0
  心跳曾短暂覆盖生产 daemon 的 local0 心跳行（consumer_id 冲突，生产 daemon 后续已写回）。
  smoke 未消费任何 item（生产库无 discover_fb 队列，`成功 0，空 0，失败 0`），未 INSERT 数据
- item 消费：无（阻断于启动阶段，未达消费环节）
- 间隔：N/A（未消费）
- 落库：fb_posts 0 行、fb_groups 0 行（临时库为空，未执行 DDG 抓取）
- 限流观测：N/A（未发起真实 DDG 请求）
- 验收判定：**不满足**——冒烟未执行（隔离失效，禁止用生产库冒烟）。根因待协调：
  方案 A `config_from_args` 加 `os.environ.get("FETCHER_DB_PATH")` 回退（与 ShopDB 语义对齐）；
  方案 B 冒烟改用显式 `--db`（brief 环境事实第 3 条修正）。不自行修代码，按 brief 纪律
  上报 BLOCKED

## Step 1.5 冒烟记录（2026-08-09 22:03，DONE）

- 临时 DB：/tmp/fb_smoke_1786283975/1688.db（ShopDB 初始化建表，2 条 work_items 就绪，requires='["local"]'）
- daemon：`-u -m fetcher daemon --db /tmp/fb_smoke_1786283975/1688.db --queues discover_fb --local-workers 1`，PID 80522，有头观察：无浏览器窗口弹出（local 消费者，符合预期）；**隔离确认**：启动日志 `队列 discover_fb: 待补货店铺 0 个 + 待认领工作项 2 个`、`[fb_discover] 队列待处理: 2`——读的是临时库（对比上次事故的 3164 店铺计数），consumer_status 心跳仅写临时库 local0，未触碰生产库
- item 消费：item1 21:59:37 claimed → 22:00:39 done（query「site:facebook.com/groups 外贸 whatsapp」第1页）；item2 22:00:39 claimed → 22:01:41 done（query「跨境电商 whatsapp」）；均 local0 消费，终态 done
- 间隔：62s（两次 claimed 与两次 finish 均差 62s；≥60s 下限达标）
- 落库：fb_posts 新增 1 行（source='ddg'，keyword='site:facebook.com/groups 外贸 whatsapp'，url=真实 FB 帖 permalink groups/676368063029200/posts/1442991693033496/，group_name 已去 " | Facebook" 后缀）；fb_groups 新增 18 行（source 全为 'ddg'，含数字 gid 与 slug gid，如 whatspphaiwai；item2 结果与 item1 大量同 URL 被 INSERT OR IGNORE 去重）
- 限流观测：无 202 触发——两条查询首次即 200 返回真实结果，无需退避（协调者 spike 曾实测 2 连查后第 3 次 202，本次节奏 62s 留足余量）
- 验收判定：**满足**——fb_posts 1 行 + fb_groups 18 行真实新增（source='ddg' 溯源完整）、间隔 62s≥60s、item 状态流转 pending→claimed→done 完整

## Phase 1 完成（Step 1.1-1.5 全 done）

- 冒烟过程非阻塞发现（终审分诊，建议开 issue）：
  ① FETCHER_DB_PATH 环境变量对 daemon 无效（config_from_args 只读 --db；与 ShopDB
  无参构造语义不一致）——冒烟已用 --db 绕过，属既有 daemon 行为，非 feature 缺陷
  ② 同机多 daemon 的 consumer_status local0 心跳键冲突（smoke 短暂覆盖生产 daemon
  心跳行，10s 心跳自动写回）——运维注意点
  ③ smoke daemon 启动对生产库执行 reset_claimed_work_items（已自愈，生产 daemon 34402
  重新认领 FIFO）——事故已止损
- Phase 1 完成标准满足：Step 1.1-1.5 全 done（含冒烟记录）；Phase 2 Step 2.1 可开始。
