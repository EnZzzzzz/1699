# SDD ledger — plan: docs/feat_2026-08-08_fetcher-platform-p4/PLAN.md

> 执行模式说明：本 session 无 subagent 派发工具（未安装 subagent 扩展），
> 按 subagent-driven-development skill 纪律降级执行（主 Agent 兼任
> implementer + reviewer，保留 TDD/双重自检/ledger/scoped commit/终审）。

## 前置裁定（SPEC §3.0）

- **ledger-1**：用户未提交 wa pairing 改动 → 已提交（commit f6a497e，
  main，14 文件 +856/-141）；工作区仅剩 P4 任务文档。P4 分支从 f6a497e 开出
  （feat/platform-p4）。

## 批次/边界裁定（派发前冲突扫描）

- 批次 SQL「fetcher 侧 + 平台侧双份」是 SPEC §3.1 有意裁定（平台不 import
  fetcher）；fetcher 侧版本供 daemon/测试锚定，平台侧 Step 2.1 重写。
- work_items `stopped` 态：claim 只认 pending 天然排除；release 只对
  claimed 生效；reset_claimed_work_items 不碰 stopped（sweeper 兜底在 P4-2）。
- batch 索引双侧幂等：fetcher SCHEMA + 平台 migrate 探测补建（生产库表由
  fetcher 建）。
- 冷却键泛化（site→queue 名）属 P4-1 范围，改动点收敛在 eligible_queues/
  _cooldown，单测锚定。

## Step 记录

### P4-0 Step 0.1 — work_items stopped 态 + 批次入队函数 + batch 索引

- **实现**：fetcher/fetcher/db.py（DDL 注释同步 stopped/batch_id 语义 +
  idx_work_items_batch 索引；enqueue_contact_batch 同事务语义 + limit 限量；
  enqueue_feeder_batch discover+category 种子带 batch_id/batch_limit）。
- **测试**：fetcher/tests/test_batch_enqueue.py 9 用例（先失败后转绿：
  入队带 batch_id/限量/幂等/与 topup 双喂互斥双向/stopped 不被 claim/
  batch 索引存在）。全量 532 passed（基线 523 + 9）。
- **review**：自检通过。限量为 0 的处理从魔数 1<<30 改为条件拼 SQL（
  修复后复跑 test_batch_enqueue + test_work_items 24 passed）。
- **commits**：900ff06
- **状态**：complete

### P4-0 Step 0.3 — consumer_status 心跳 + proxy_channels 租约

- **实现**：
  - fetcher db.py SCHEMA 加 consumer_status 表（幂等建表）；
  - 新模块 fetcher/control/status.py：ConsumerStatusStore（upsert 哨兵语义
    「未传=保留/显式 None=清空」+ clear + heartbeat_all + lease/release
    channels + close）；
  - 接线：queue_router claim/finish 即时 upsert；loop._cooldown 让出型
    登记后上报 cooldowns_json；engine 心跳线程（10s）+ 启动租约 + 退出
    清理（清行/释放/关连接）；cli daemon 装配 status_store。
- **修复（冒烟抓到的真 bug）**：sqlite3 连接不可跨线程——ConsumerStatusStore
  原实现持单 ShopDB 连接，worker 线程 claim 时报
  "SQLite objects created in a thread can only be used in that same thread"。
  重构为线程本地连接（threading.local 懒建 ShopDB），并补跨线程单测。
- **测试**：test_consumer_status.py 12 用例 + test_daemon_status_hooks.py 4
  用例（TDD 先失败后转绿）。全量 558 passed。
- **冒烟**：plan/smoke-step0.3/run.log + 临时库对照（/tmp/p4_smoke_a.db
  已清理）。证据：claim 时 consumer_status 写入
  `w0|browser|crawl_1688_contact|1`；退出后行清空 0、proxy_channels 租约
  释放 NULL。直连 1688 滑块墙 100% 命中 = 环境噪声，item 落 failed 属
  预期结构证据。
- **备注**：发现 P3 遗留 daemon（pid 28917，/tmp/smoke_p3_61b.db）仍在跑，
  占 1 席——非本任务范围，未处理，记录备查。
- **commits**：87f27d7
- **状态**：complete

### P4-1 Step 1.1 — LocalExecutor 消费者 + requires="local" 互斥

- **实现**：
  - queue_router：eligible_queues 冷却键泛化（site or queue，wa_check 无 site
    时退 queue 名）；condvar_timeout_multi 入参改 keys；topup 冷却判断同步；
  - loop._cooldown：登记键 active_site or queue（非站点队列用 queue 名）；
  - 新模块 control/local_loop.py：LocalLoop（无浏览器执行循环，outcome 直接
    处置 OK→on_success / FATAL→giveup(fatal) 停止 / SKIPPED→收工 /
    NET_ERROR→giveup(net) 继续）；
  - engine：local_workers 参数 + _local_worker 线程（resources={"local"}，
    consumer_kind="local"，不建 BrowserManager/不分配通道/不认种子，
    wid+10000 隔离 stats/board）+ local_loop_factory 注入点；run 装配
    local 线程与心跳 consumer 列表扩展；
  - cli：daemon 加 --local-workers（默认 2）并传给 Engine。
- **测试**：test_local_consumer.py 10 用例（TDD 先失败后转绿：互斥双向/
  冷却键泛化/LocalLoop 各 outcome 分支/Engine local 装配）。全量 568 passed。
- **review**：自检通过。测试修正：假 task acquire 推进 index（防死循环）、
  on_success 写 ctx.state（与真实 task 一致）、FATAL 断言补 fetch 顺序。
- **commits**：994a19b
- **状态**：complete

### P4-1 Step 1.2 — WaCheckTask + 入队 feeder

- **实现**：
  - 新模块 fetcher/wa_task.py：WaCheckTask（Task 协议，LocalLoop 驱动——
    fetch 调 CheckWhatsApp 原子透传 numbers/account/default_cc；on_success
    写回 contacts（移植 wa_tasks._apply_results：后 11 位 LIKE + normalize
    严格校验 + 歧义跳过 + 北京时间））+ wa_check_topup（contacts 未查号码
    → 50/块 → 账号轮换（WA_CHECK_ACCOUNTS，空默认 ["default"]）→
    INSERT work_item requires=["local"]、site=NULL；有 pending/claimed
    项整批跳过幂等）；
  - db._migrate：contacts 补 wa_registered/wa_checked_at 列（fetcher 侧
    建表路径也要有，与平台对齐）；
  - cli._build_registry：wa_check spec（requires={"local"}，topup=
    wa_check_topup），守卫 check.js 存在 + node 可用才注册；
  - **修复（全量测试抓到）**：reset_daemon_state 误把 wa_check 的空
    domain_suffix 当无过滤 reset 所有站点 in_progress——改为仅
    topup 且有 domain_suffix 的 spec 参与；test_cli 注册表断言更新为
    ≥5 + 守卫条件 wa_check。
- **测试**：test_wa_task.py 13 用例（TDD 先失败后转绿：切块/幂等/账号轮换/
  写回/歧义/原子透传/守卫）。全量 581 passed。
- **commits**：be09e72
- **状态**：complete

### P4-2 Step 2.1 — 批次任务类型 + sweeper

- **实现**：
  - runner：TASK_COMMANDS 只剩 yiwugo_search、IN_PROCESS_TYPES 清空、
    BATCH_TYPES 映射（6 类型 → queue/kind）；模块级 sweeper
    （sweep_batch_tasks：状态派生 + stopped 兜底 + progress 聚合）、
    enqueue_batch_for_task / stop_batch_task；TaskRunner._start_sweeper/
    _sweeper_loop（5s tick）/startup 跳过批次孤儿清理；start/stop/_auto_restart
    批次分派；is_running 批次 False；
  - api/tasks.py：TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPES、TaskParams 保留
    全字段（向后兼容，批次只读 limit/repeat/accounts）、preview 批次返回
    「批次提交：{queue}，{limit} 条」、start/stop 批次分支（start 入队
    batch_id=tasks.id）；
  - app/db.py：migrate 探测补建 idx_work_items_batch；平台侧批次入队
    （enqueue_contact_batch/enqueue_feeder_batch/enqueue_wa_batch，与
    fetcher 同事务语义，SPEC §3.1 双份裁定）。
- **测试**：test_batch_tasks.py 15 用例（TDD 先失败后转绿：三入队函数
  batch_id 全链路/幂等/限量/空账号拒绝、sweeper 派生 running/done/stopped/
  failed 计数/stopped 兜底、start/stop 批次语义、TASK_TYPES/preview、
  uvicorn 重启批次不丢（孤儿清理跳过））。平台全量 53 passed（基线 38+15）。
- **冒烟**：uvicorn 重启生效（生产库 4 条任务保留，旧 wa_check running
  由旧 shutdown 收尾 stopped）；API 验证批次 preview 冻结文案 + yiwugo
  subprocess 保留（plan/smoke-step2.1/preview.txt）。
- **review**：自检通过。测试基建修复：api.tasks 的 DB_PATH 是导入时
  拷贝引用，patch db_module 不影响它——必须单独 patch api_tasks.DB_PATH
  （否则测试写生产库，debug 阶段发现并清理了 1 条污染数据）。
- **commits**：6f40655
- **状态**：complete

### P4-2 Step 2.2 — SSE 事件合成 + dispatcher API

- **实现**：
  - api/tasks.py：批次 SSE 合成（_compose_batch_event：done→✓ success/
    failed→✗ + reason error/stopped→⏹ warning；_fetch_batch_events 按 id
    游标增量；_replay_batch_events 回放 200）；task_events 端点批次分支；
  - 新模块 api/dispatcher.py：GET /dispatcher/status（daemon_alive 心跳
    30s 新鲜度 + queue_depth GROUP BY + today_done）+ GET /dispatcher/
    consumers（offline 标记 + cooldowns_json 解析）；注册进 api/__init__。
- **测试**：test_dispatcher_api.py 9 用例（TDD 先失败后转绿：合成 message/
  level、回放+增量游标、daemon 存活判定、queue_depth 聚合、today_done、
  consumers offline、路由可达 TestClient）。平台全量 62 passed。
- **冒烟**：uvicorn 重启后 curl 验证（plan/smoke-step2.2/status.json +
  consumers.json）：daemon_alive=false（无 daemon）、queue_depth 聚合真实
  生产数据（crawl_1688_contact claimed 19/done 14/pending 3——P3 遗留
  daemon 正在跑）、today_done 14。
- **review**：自检通过。修复：sqlite3.Row 无 .get（用索引+KeyError 兜底）、
  _fetch_batch_events SELECT 补 queue 列、路由断言改 TestClient（FastAPI
  新版 _IncludedRouter 无 path）。
- **commits**：89ad3ce
- **状态**：complete

### P4-2 Step 2.3 — start.sh/stop.sh 纳管 daemon + 冒烟

- **实现**：
  - start.sh：start_daemon()（pidfile run/daemon.pid、日志 logs/daemon.log、
    nohup server/.venv/bin/python -m fetcher daemon，cwd=项目根；DAEMON_ARGS
    环境变量可覆盖，默认 --workers 1）；防双 daemon 提示；
  - stop.sh：graceful_stop(daemon.pid)（SIGTERM→5s→SIGKILL）+ pkill 兜底
    特征 fetcher.*daemon；
  - README：纳管说明 + 防手动 daemon 警告。
- **修复（冒烟抓到 2 个真 bug）**：
  1) start.sh echo `$DAEMON_ARGS）` 中文括号粘连变量名（unbound variable）
     ——改 `${DAEMON_ARGS}` 花括号包裹；
  2) local worker 的 board.set(wid+10000) 越界（board 只分配浏览器 worker
     行）——local 消费者不用 board（log 直打印、set_status noop）。
- **冒烟**（临时库 /tmp/p4_nsmoke.db 已清理）：start.sh 完整拉起后端+前端+
  daemon（pid 53145）；重复 start 幂等（跳过）；daemon 心跳写
  consumer_status（w0/local0/local1 22:54:08 新鲜）；stop.sh 优雅停止 +
  兜底清理；退出后 consumer_status 清空 0。冒烟前停掉 P3 遗留 daemon
  （pid 28917，P3 冒烟 /tmp 临时库残留）。
- **测试**：fetcher 583 + 平台 62 全绿（board 修复复跑相关 37 passed）。
- **commits**：e9bc28f
- **状态**：complete

### P4-3 Step 3.1 — 任务类型表单 + 批次进度

- **实现**：
  - api.ts：TaskType 加 madeinchina_contact/madeinchina_shop；
  - task-ui.tsx：TASK_TYPE_OPTIONS 加两项；paramsSummary 批次分支
    （只显 limit + repeat_interval）；
  - TaskFormDialog：isBatch 三分支（批次采集只留 limit + repeat_interval，
    Label 按 contact=条数/shop=页数切换文案，daemon 收敛提示；validate/
    buildParams/fillFromParams 适配）；
  - Tasks.tsx：批次进度列 done/total + failed 标红（text-destructive）。
- **验收**：npx tsc -b 零错误；浏览器走查（playwright 截图见 Step 3.2）。
- **commits**：6ecf36f
- **状态**：complete

### P4-3 Step 3.2 — 调度器看板页

- **实现**：
  - 新页 Dispatcher.tsx（/dispatcher）：StatCard 行（daemon 在线 sky/离线
    neutral、工作项积压、今日完成）+ 队列深度表（数值列右对齐、failed
    标红）+ 消费者表（workerChip、kind、通道/IP、当前队列+工作项、
    CooldownBadges amber 徽标 + 1s 倒计时）；useApiData 自适应轮询（在线
    5s/离线 30s）；PageState 三态；
  - api.ts：DispatcherStatus/DispatcherConsumer 接口 + dispatcherStatus/
    dispatcherConsumers 方法；
  - App.tsx 路由 + Layout navItems「调度器」（Network 图标，供应商改
    ServerCog）。
- **验收**：npx tsc -b 零错误；浏览器走查（playwright 截图 plan/
  smoke-step3.2/）：看板页标题/StatCard/队列表/消费者表/导航全部渲染；
  任务表单三分支（默认 1688_shop 批次表单 + 切 madeinchina_contact 条数
  文案 + 预览文案）。DESIGN.md 逐条对照自查通过。
- **commits**：6ecf36f
- **状态**：complete

### P4-4 Step 4.1 — 全链路验收冒烟

- **冒烟**（plan/smoke-step4.1/daemon.log + 临时库 /tmp/p4_e2e.db 已清理）：
  临时库建批次任务 101 → 平台 enqueue_contact_batch 入队 3 items
  （batch_id=101）→ daemon（--workers 1）claim 执行 → finish failed（直连
  滑块墙=环境噪声）→ sweeper 派生 tasks.done + progress{failed:3} → SSE
  合成 `✗ e2e1.1688.com ... 已解析联系方式页` + 增量游标正确。自喂 item
  （batch_id NULL）与批次 item 并存互不干扰。
- **SPEC §7 逐条取证**：1) 全链路 ✓（本条冒烟）；2) 跨站填充可见 ✓
  （Step 2.2 dispatcher 聚合真实数据 + Step 3.2 看板渲染）；3) wa_check
  写回 ✓（Step 1.3 真实查号）；4) 脚本纳管 ✓（Step 2.3 真起真停）；
  5) uvicorn 重启不丢 ✓（Step 2.1 单测）；6) 测试/tsc 绿 ✓（fetcher 583
  + 平台 62 + tsc 零错误）；7) daemon.log 无 ERROR ✓（滑块噪声除外）。
- **commits**：待提交
- **状态**：complete

### P4-1 Step 1.3 — wa_check 真实冒烟

- **冒烟**：plan/smoke-step1.3/run.log + run2.log（临时库 /tmp 已清理）。
  daemon `--queues wa_check --local-workers 1` + 专用查号号 xiaohao-4
  （WA_CHECK_ACCOUNTS）真实查号 1 个测试号。
  证据：claim（site=None）→ 原子连接 WhatsApp → `8613800138000 ❌ 未注册`
  → 写回 1 行 → finish done；contacts 验证
  `1|13800138000|0|2026-08-08 22:31:52`（wa_registered=0、wa_checked_at
  北京时间）；consumer_status 运行期 `local0|local`。
- **修复（冒烟抓到 2 个真 bug）**：
  1) `_run_daemon` 对 site=None spec（wa_check）调 get_site 崩——跳过
     site=None 的策略/站点装配，纯本地队列时 Engine browser_workers=0
     （新增 browser_workers 覆盖参数）不装浏览器 worker；
  2) local 消费者 consumer_id 命名不一致（router 生成 w0，Engine 心跳/
     清理用 local0）→ 退出清理漏行。新增 consumer_id_for(ctx) 按
     consumer_kind 统一命名（browser→w{wid}、local→local{wid}），
     三处统一 + 命名单测。
- **备注**：SIGTERM 后 daemon 退出需等 condvar 30s 自醒（P0 既有语义，
  stop 不 notify condvar）；stop.sh 有 5s 后 SIGKILL 兜底，平台纳管
  路径不受影响。清理残留：Step 0.3 冒烟时误产生的 4 个
  `fetcher/<ShopDB object>` 垃圾文件已删除（未跟踪）。
- **测试**：test_wa_task.py 14 用例（+守卫 spec 断言）、test_local_consumer
  +consumer_id 断言。全量 583 passed。
- **commits**：7530073
- **状态**：complete

### P4-0 Step 0.2 — feeder 批次继承与限量收束

- **实现**：
  - db.py claim_next_eligible 返回 batch_id（透传上层）；
  - 三个 feeder task（1688 shop / 1688 company / mic shop）：
    acquire_item 注入 batch_id；_insert_work_item 支持 batch_id；
    discover 产出/链式续喂/refill 补插继承 batch_id + batch_limit；
    _batch_reached_limit（batch_id 非空 ∧ batch_limit>0 ∧ done ≥ limit
    → 停止续喂/补插）；
  - queue_router.acquire_item 同样注入 batch_id（daemon 认领批次 item）。
- **测试**：fetcher/tests/test_batch_inherit.py 10 用例（TDD 先失败后转绿：
  claim 透传/继承链/discover 产出继承/收束边界（达限停、未达续、limit=0
  不限）/refill 继承+收束/自喂路径 batch_id NULL 零变化）。全量 542 passed。
- **review**：自检通过（测试修正：item dict 模拟 acquire 注入 batch_id；
  当前 item 不入库——真实链路已 claim）。
- **commits**：5b90fa7
- **状态**：complete
