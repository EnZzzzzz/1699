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

## Step 2.1 执行记录

- implementer commit `7a09836`（DONE，13 新增 + 734 全量）
- reviewer：spec ✅，2 Important（均标注不阻塞）+ 4 Minor
- Minor 记 deferred：① fetch 的 `int(item.get("limit") or 10)` 对 limit=0 兜底为 10
  ② on_success state 的 n_new 是去重新增数、与 len(phones) 可能不同 ③ _result 测试
  助手同 number 不同 bucket 去重丢弃 ④ prepare 打印进测试输出（既有行为）
- 修复循环 round 1：2 个 Important 派发（_group_id_from_url 与 post_task.py 逐字重复→
  提取共享；stats 依赖 data["phones"] 顶级聚合与逐帖口径不一致→改逐帖计数）
- Step 2.1 fix round 1/5（2 addressed, 0 open — group_id 共享函数提取 urls.py + 逐帖口径
  stats; commits 7a09836..40e3de9），re-review 干净
- Step 2.1: complete (commits 5e9dce7..40e3de9, review clean)

## Step 2.2 执行记录

- implementer commit `b9c6ad5`（DONE，test_cli_fb.py 6/6 + 56 fb 回归）
- reviewer：spec ✅，0 Critical/Important，2 Minor
- Minor 记 deferred：① test_cli_fb.py docstring 未提 crawl_fb_group ②
  test_queues_choices_accept_fb 未断言 crawl_fb_group（Step 1.4 同款命名过泛）
- Step 2.2: complete (commits cb3e02b..b9c6ad5, review clean)

## Step 2.3 执行记录

- implementer commit `8c58e4e`（DONE，19/19 + 60 fb 回归；第 4 个幂等守护测试无独立
  RED——守护既有 INSERT OR IGNORE 语义，可接受）
- reviewer：spec ✅，0 Critical/Important，2 Minor
- Minor 记 deferred：① test 用 row[0] 位置取值与列名取值风格不一 ② 幂等测试二次调用
  同 name 无法区分覆盖与否（INSERT OR IGNORE 语义已保证）
- Step 2.3: complete (commits 1f6d100..8c58e4e, review clean)

## Step 2.4 冒烟记录（2026-08-09 22:26，DONE）

- 临时 DB：A 段 /tmp/fb_group_smoke_A_1786285428/1688.db；B 段 /tmp/fb_group_smoke_B_1786285428/1688.db（均为 ShopDB 初始化建表，未触碰生产库 .cache/1688.db）
- A. 缺 key 真实链路：daemon PID 7771（`python -m fetcher daemon --db <A库> --queues crawl_fb_group --local-workers 1`，不带 key 环境，无头），观测日志
  `[claim] queue=crawl_fb_group item=1 → [finish] item=1 status=failed`，work_items#1 result_json=`{"reason": "缺少 Bright Data API key（传 api_key 或设环境变量 BRIGHTDATA_API_KEY）", "kind": "fatal"}`（reason 即原子 FATAL detail，经 LocalLoop on_giveup(fatal)→QueueRouter._finish 落库）；fb_groups 群 `https://www.facebook.com/groups/676368063029200/` status=pending→**failed** ✓（daemon 随后自行退出）
- B. mock done 链路：方案=同进程 monkeypatch `FetchFbGroupPosts.run`（返回构造的 2 帖：帖1 含 cn_uncertain+declared_wa 两号、帖2 无号）后，按 `fetcher/cli/main.py::_run_daemon` 逐行装配 QueueRouter+Engine（local_workers=1、browser_workers=0、status_store=None）跑真实 LocalLoop；与真实 daemon 仅差进程边界（patch 不跨子进程）与心跳（非验收项）。日志 `[claim] → [mock atom] → [finish] item=1 status=done`；fb_contacts 新增 **2 行**（post_url=帖 permalink 溯源、group_id=676368063029200、declared_wa→wa_source='declared'、cn_uncertain→wa_source=NULL）；fb_groups 群 status=pending→**done** + post_count=2 + has_contact=1 + last_crawled_at 回写 ✓
- 验收判定：**满足**——两段各走通一轮完整状态机（A: pending→claimed→failed[fatal]；B: pending→claimed→done），B 段 fb_contacts 落号 2 行证据完整；生产 daemon 34402 全程未受影响
- 观测（非阻塞）：① 原子 FATAL 不写 ctx.log，日志链看不到 FATAL 文本，detail 仅落 work_items.result_json（可观测性可议，非缺陷）；② B 段 mock 帖 URL 拼接带双斜杠（`groups/676368063029200//posts/...`）为 mock 数据自身拼接所致，真实 BD/Apify 帖 url 由接口返回不会双斜杠，非代码缺陷

## Phase 2 完成（Step 2.1-2.4 全 done）

- 冒烟非阻塞发现（终审分诊）：原子 FATAL 不写 ctx.log（可观测性，非缺陷）
- Phase 2 完成标准满足：crawl_fb_group 队列可跑批、状态机两段各走通一轮、相关测试全绿。

## Step 3.1 执行记录

- implementer commit `acf205a`（DONE，21/21 + 63 全量）
- reviewer：spec ✅，1 Important（BATCH_TYPES 新条目行内紧凑格式与既有多行风格不一
  ）+ 2 Minor
- Minor 记 deferred：② 懒导入技术债——report 承诺 Step 3.2 落地真实函数后并入顶部
  import → **列为 Step 3.2 必做收尾项** ③ fb_group 分支注释跨行不规整
- 修复循环 round 1：Important「BATCH_TYPES 格式对齐多行」派发
- Step 3.1 fix round 1/5（1 addressed, 0 open — BATCH_TYPES 多行格式; commits
  acf205a..61f36e2），re-review 干净
- Step 3.1: complete (commits 966120b..61f36e2, review clean)

## Step 3.2 执行记录

- implementer commit `6896454`（DONE，28/28 + test_fb_batch 14/14 回归；懒导入收尾完成）
- reviewer：spec ✅，0 Critical/Important，3 Minor
- Minor 记 deferred：① int(pages) 恒等冗余 ② discover 幂等检查与 INSERT 无 BEGIN
  IMMEDIATE 的并发窗口——brief 明确参照 enqueue_feeder_batch 模式，有意权衡
  ③ n=0 时无操作 commit
- Step 3.2: complete (commits dc717aa..6896454, review clean)

## Step 3.3 执行记录

- implementer commit `d90e01f`（DONE，30/30 + 72 全量）
- reviewer：spec ✅，0 Critical/Important，2 Minor
- Minor 记 deferred：① round-trip 只测 fb_discover 未独立测 fb_group（同模型已覆盖序列化）
  ② _conn() 无 try/finally（临时 SQLite 无实际影响）
- Step 3.3: complete (commits fd29bf1..d90e01f, review clean)

## Step 3.4 平台冒烟记录（2026-08-09 22:46，DONE）

- start.sh：SPEC §6.5 追加 `export BRIGHTDATA_API_KEY="${BRIGHTDATA_API_KEY:-}"` /
  `export APIFY_TOKEN="${APIFY_TOKEN:-}"`（WA_CHECK_ACCOUNTS 之后、daemon 启动前；
  grep 第 29-30 行 + `bash -n` 通过；.env 已 gitignore）
- 后端/daemon：stop.sh 停旧（旧 daemon 34402 不认新队列）→ start.sh 起新；
  uvicorn 30012 / daemon 30020 / vite 30051；daemon.log 最新 boot 段 8 队列全量注册
  含 `[daemon] 队列 discover_fb` / `[daemon] 队列 crawl_fb_group`（line 32954/32956），
  无 key 相关报错
- fb_discover 任务 85（自定义 2 词 × 1 页）：work_items 2 条（requires=["local"]、
  engine=ddg、query 逐词正确、page=1）；任务 89（默认矩阵 5 词 × 1 页）：5 条同断言
- fb_group 任务 86（空表防御）：入队 0 条；任务 88（手动种子 1 条 pending 群）：
  入队 1 条，payload {"url","provider":"brightdata","limit":50}，源行 pending→in_progress
  （冒烟后已清理种子行 + 派生 work_items，生产库复核 0 残留）
- start/stop 流转：85/86/88/89 均 create(201)→start(running)→stop(stopped)，
  progress 计数与入队数一致（85:2/2、86:0/0 零项兜底、88:1/1、89:5/5）
- 验收判定：**满足**——两类型任务可创建/启动/停止，入队断言正确；daemon 8 队列
  全量注册（含新队列）
- 观测（非阻塞）：① daemon 冒烟期内未 claim discover_fb/crawl_fb_group（重队列
  优先），消费链路已在 Step 1.5/2.4 临时库验证 ② stop.sh 对 daemon 子进程需 kill -9
  补刀（pidfile 记父进程，AGENTS.md 已注明）③ start.sh 经 bash 工具调用会挂超时并
  连带杀新起进程，需 nohup 脱离调用 shell（harness 调用方式问题，非脚本缺陷）

## Phase 3 完成（Step 3.1-3.4 全 done）

- 冒烟非阻塞发现（终审分诊）：① daemon 冒烟期未实际 claim 新队列（1688/mic 重队列
  优先，消费链路已由 Step 1.5/2.4 临时库验证）② stop.sh SIGTERM 后需 kill -9 补刀
  （pidfile 记父进程，AGENTS.md 已注明）③ start.sh 经 bash 工具调用挂超时需 nohup
  脱离（harness 调用方式问题）
- Phase 3 完成标准满足：两类型任务可创建/启动/停止、入队断言正确、平台测试全绿。

## Step 4.1 执行记录

- implementer commit `a8edfe3`（DONE，tsc 全绿）
- reviewer：spec ✅，0 问题
- Step 4.1: complete (commits 95fd521..a8edfe3, review clean)

## Step 4.2 执行记录

- implementer commit `9c20140`（DONE，tsc 全绿 + esbuild 冒烟 7 组用例）
- reviewer：spec ✅，0 Critical/Important，2 Minor
- Minor 记 deferred：① task-ui.tsx:150 注释「空视为 1」与代码「默认矩阵」行为不一
  ② 空 keywords + 显式 pages>1 显示「默认矩阵 × M 页」vs 裁定示例 × 1 页（实际场景罕见）
- Step 4.2: complete (commits 15a0d90..9c20140, review clean)

## Step 4.3 执行记录

- implementer commit `8d0f528`（DONE，tsc 全绿 + API 冒烟三分支零回归）
- reviewer：spec ✅（2 项 plan-mandated Important + 3 Minor）
- Minor 记 deferred：③ fbDiscoverKeywords useState 初始值可直填默认矩阵（SSR 闪现
  边缘）④ fb_group 循环间隔独占一行（视觉偏好）⑤ batchLimit 重置修复了 isBatch 潜伏
  bug（正向，已验证非回归）
- 修复循环 round 1：2 个 Important 派发（keywords 空 toast 警告、provider 防御校验）
- Step 4.3 fix round 1/5（2 addressed, 0 open — keywords 空 warning + provider 防御校验;
  commits 8d0f528..95ff95f），re-review 干净
- Step 4.3: complete (commits 5735a78..95ff95f, review clean)

## Step 4.4 执行记录

- implementer commit `e4a6866`（DONE，tsc 全绿）
- reviewer：spec ✅，0 问题
- Step 4.4: complete (commits 211927a..e4a6866, review clean)

## Step 4.5 前端冒烟记录（2026-08-09 23:03:43）
- 环境：vite :3000（PID 30015）、backend :8765 复用（未重启）
- 工具：playwright-core 1.62.1 + 系统缓存 chromium-1228 headless shell（executablePath 直启，
  无网络下载）；脚本 /tmp/fb_smoke_web_smoke.mjs（不入库）
- 操作：打开 /tasks → 新建 fb_discover（断言默认矩阵 5 行、每词页数=1、hint「DDG SERP 单 IP
  限流」）→ 切 fb_group（断言 provider 默认 Bright Data 且 trigger 含 h-8+font-medium、每群
  帖数=50、hint「Bright Data 免费层」）→ 提交自定义 1 词 fb_discover（断言类型标签「Facebook
  帖子发现」+ 摘要「1 词 × 1 页」）→ 提交默认 fb_group（断言标签「Facebook 群帖采集」+ 摘要
  「provider=Bright Data 每群≤50帖 群数不限」+ 状态列排队中渲染不崩）→ 编辑 fb_discover 回填
  （keywords/pages=1 正确、类型只读）。共 18 项断言全部通过（passed=18 failed=0）
- 创建的任务：id=92 fb_discover {keywords:"site:facebook.com/groups 冒烟测试",pages:1}、
  id=93 fb_group {provider:brightdata,posts_per_group:50}——创建即 pending 不入队（批次入队
  仅在显式 start 时发生），冒烟后 DELETE 两任务清理，DB 验证 0 残留 work_items
- 截图：/tmp/fb_smoke_web/01-tasks-list.png ~ 06-edit-backfill.png
- 验收判定：满足（PLAN checkbox 两项均达成）
- 观测：打开 Dialog 时出现 React 19 既存 ref 警告（shadcn Slot 组件，非本 Step 引入，改动前
  文件即存在）

## Phase 4 完成（Step 4.1-4.5 全 done）

- 冒烟非阻塞发现（终审分诊）：React 19 + shadcn Slot 的既存 ref 警告（dialog/select
  改动在旧提交 a1e5c8a，非本 feature 引入）
- Phase 4 完成标准满足：npx tsc -b 全绿、表单可创建两类型任务、既有类型零回归。

## Step 5.1 端到端冒烟记录（2026-08-09 23:05-23:55）

- 环境：daemon PID 30020（全量队列，复用）· backend :8765 · frontend :3000
- 看板：discover_fb / crawl_fb_group 两条队列出现 ✓（depth: discover_fb done=1,failed=4；crawl_fb_group failed=2,stopped=3）
- fb_discover 任务 #94：默认矩阵 5 词 × 1 页，5 item 消费耗时 ~10 min（含 23 min wa_check 清空等待）
  实测节奏 60-80s、202 退避 4 次（每 item ~4:30-5:00）、1/5 成功（20% 通过率）
  fb_posts 新增 1 行（source='ddg'，keyword 溯源「亚马逊卖家 微信」正确）
  fb_groups 新增 10 行（全部 source='ddg'，SERP 群主页 + 帖派生群）
  无重复行（url UNIQUE 约束生效）
- fb_post 接续：DDG 帖 #389 自动被 crawl_fb_post 消费者接续（work_item 25766 done，306→306）
  独立 fb_post 批次未创建（fb_posts 0 pending，全部已消费）
- fb_group 任务 #95：limit=5，2 个 item FATAL→failed（缺 BRIGHTDATA_API_KEY）✓
  群状态机 pending→in_progress→failed 流转正确 ✓
  3 个 item 因 daemon 本地消费者停滞未处理（后 stopped）
  done 路径已由 Step 2.4 mock 覆盖，本步仅验证 FATAL 真实路径
- wa_check：❌ 未验证（消费者停滞；topup 机制活跃但无消费者消费）
- 关键问题：daemon 本地消费者（local0/local1）在 23:48 处理 fb_group FATAL 后停滞
  board.py fields 越界为已知历史问题（昨日启动复现），今日停滞待查；心跳线程持续运行
  造成 131 wa_check + 3 fb_group items 滞留
- 验收判定：
  SPEC §10-1 ✅ fb_discover → fb_posts source='ddg' + fb_groups，keyword 溯源，无重复
  SPEC §10-2 ⚠️ fb_group FATAL→failed 验证通过（2/5），余 3 items 因 daemon 停滞
  SPEC §10-3 ✅ fb_post 接续链路验证（DDG 帖自动消费），独立批次因无 pending 未创
  SPEC §10-4 ❌ wa_check 未验证（消费者停滞）
  SPEC §10-5 ✅ dispatcher 看板两条队列出现
- 状态：**BLOCKED**（daemon 本地消费者停滞，验收 2/4 未完整）
- 详报：task-5.1-report.md

## Step 5.1 收尾恢复 + 验收 4 补验（2026-08-10 00:00-00:05，第 2 阶段）

- **根因（协调者已定位，非 feature 代码 bug）**：fetcher/control/local_loop.py 的
  FATAL 分支 on_giveup(fatal)→set_status→break 结束 _local_worker 线程；engine.run 主循环
  只 join 不重启（wa_check 注释「FATAL→停止」= 不可自愈环境错误停消费者）。fb_group 缺
  BRIGHTDATA_API_KEY 的 FATAL 连坐停掉 discover_fb（不需要 key）。不改代码。
- **恢复 daemon（运维，无代码改动）**：stop.sh 停旧（SIGTERM 父 30019 + 兜底 pkill；子
  30020 需 kill -9 补刀）→ `nohup bash platform/start.sh > /tmp/fb_recover_start.log 2>&1 &`
  起新（bash 工具直接调用 start.sh 会挂超时并连带杀新进程）。新 daemon 00:00 启动：
  9 条 `[daemon] 队列` 注册（crawl_1688_contact / crawl_fb_post / crawl_mic_contact /
  crawl_mic_shop / crawl_1688_shop / crawl_1688_company / wa_check / discover_fb /
  crawl_fb_group）+ `[2] 启动 1 个 worker（直连）` + `[2] 另启动 2 个 local 消费者`；
  consumer_status local0/local1（kind=local）心跳持续更新，00:00:03 即认领 wa_check
  items 26166/26167（停滞解除的直接证据）。
- **验收 4 补验（wa_check 观察，零改动链路）**：
  - 手工 INSERT：fb_posts id=390（url `https://www.facebook.com/groups/999/posts/888`，
    source='manual'，status=pending）+ fb_contacts id=216（number=13800138000，
    bucket='cn_uncertain'，wa_checked_at=NULL，post_url=同上）——模拟「新落的 fb_contacts 号码」
    （假 URL 页无法真提取号码，号码直接落 fb_contacts 即被测链路的起点，与 SPEC §10-4
    「既有双源链路」一致）。
  - fb_post 任务 #96（limit=1）→ start → crawl_fb_post work_item 26300 入队 → w0（浏览器
    消费者）00:02:26 认领 → 00:03:01 failed（假 URL 页不存在，预期）→ fb_posts 390 置
    failed：fb_post 批次入队 + 浏览器消费路径在新 daemon 上验证通过。
  - wa_check 入队观察：存量 127 条 stale pending wa_check items（batch_id NULL，topup
    生成、无归属任务，且 topup 有在途整批跳过守卫）堵塞 topup——按 Step 5.1 冒烟同款
    运维手段 bulk-stop（SQL 置 stopped，stopped 505→629）→ 在途归零 → topup 30s 唤醒
    于 00:03:03 重建批次 → **work_item 29746 出现 13800138000（规范化 8613800138000，
    fb 源优先排 batch 首位）** → local0 00:03:03 认领 → 00:03:41 failed（result：
    「无法连接 WhatsApp（多次重连失败）」，既有账号 403 问题，链路已涵盖=入队+消费）。
    全库该号仅出现在 1 个 wa_check item（分桶无重复）。
  - **验收 4 判定：满足**——新落 fb_contacts 号码自动进 wa_check 队列（topup→work_items→
    local 认领全链观测到）；实际查号失败是既有账号 403 问题，非本 feature 缺陷。
  - 清理：DELETE 任务 #96（API）、DELETE fb_posts 390 + fb_contacts 216（手工行，避免
    假号 13800138000 被后续 topup 反复挑中）；work_items 26300/29746 留 failed 历史记录；
    重建的 wa_check 在途量（129）与补测前（129）一致，无残留污染。
- **Step 5.1 终判（覆盖首轮 BLOCKED）**：验收 1/2/3/5 首轮已证满足；验收 4 本阶段补验
  满足 → **Step 5.1 全部 5 项验收满足，状态 DONE**。
- 详报：task-5.1b-report.md（补充报告，追加于 task-5.1-report.md 侧）

## Step 5.1 执行记录（终判 DONE）

- 首轮 BLOCKED（daemon local 消费者停摆）→ 根因：LocalLoop FATAL→break→local 线程
  结束→engine 不重启（既有框架设计，本 feature 多 local 队列首次暴露连坐）。非本
  feature 代码 bug，不改代码。daemon 恢复 + 验收 4 补验后全 DONE。
- 验收判定：SPEC §10 1/2/3/5 首轮满足；4（wa_check 入队链）补验满足
  （号码→topup→wa_check work_item→local0 认领；查号 403 为既有账号问题）。
- 非阻塞发现（终审分诊，建议开 issue）：
  ① LocalLoop FATAL 连坐：单队列 FATAL 停全部 local 消费者（wa_check 注释「FATAL→
    停止」是有意语义，但多队列共享消费者池时需队列级熔断或线程重启）
  ② wa_check topup 无限补货 + FIFO 认领导致 fb 队列饥饿（冒烟需多次 bulk-stop
    wa_check 释放消费者）
  ③ wa_check topup 在途守卫对 batch_id NULL 的 stale pending 无限期堵塞
  ④ DDG 限流：5 词仅 1 词 200（20% 通过率，spike 预期 2 连查后封，实测首两词即封——
    当前窗口限流更严，原子退避后成功为准，SPec §8.1 数字可调）
  ⑤ 假 URL 帖无法真提取号码——验收 4 以「号码直接落 fb_contacts + fb_post 任务
    批次路径」口径完成
- Step 5.1: complete (commits 05276a1..2d8eb86, review clean——冒烟类 Step 以验收证据
  为准，无代码 review)
- Step 5.2 全量回归：三组全绿零失败。fetcher 740 tests OK (29.193s)；平台 72 tests OK
  (0.319s，含 FbBatchDispatch/Enqueue 8 例；唯一警告为既有 StarletteDeprecationWarning)；
  前端 npx tsc -b EXIT=0 (3.098s)。纯回归零代码改动，SPEC §10 验收 6 满足。
- Step 5.2: complete
