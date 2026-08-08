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
- **commits**：待提交
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
