# SPEC — P4 平台切换（runner 批次化 + wa_check 迁入 + daemon 纳管 + 消费者看板）

> 版本：v1 · 2026-08-08 · 待评审
> 设计基准：docs/scheduler-architecture.md §8/§9/§10（P4 行）；P3 实施记录 docs/archive/feat_2026-08-08_fetcher-multiqueue-p3/
> 前置：P0~P3 已合并 main（daemon 5 队列多站点调度已生效）。

## 1. 背景与目标

P3 之后调度器内核就绪，但平台仍走旧模型：`runner.py` 拼 fetcher CLI 起 subprocess（`TASK_COMMANDS`），wa_check 在 uvicorn 进程内跑，daemon 完全脱离平台生命周期（手动拉起）。P4 把平台切到调度器上：

1. 浏览器采集类任务从「拼 CLI 起子进程」改为「INSERT work_items 批次」（batch_id = tasks.id）。
2. wa_check 从 runner 进程内线程迁入 dispatcher 的 LocalExecutor。
3. daemon 生命周期纳管（start.sh/stop.sh）+ 运行状态可观测。
4. 前端：批次任务进度/事件展示适配 + 新增调度器看板页。

**验收**（基准文档 §10 P4 行）：平台创建/停止/监控全流程走 dispatcher。

## 2. 范围与非目标

### 范围

- fetcher 侧：work_items `stopped` 态 + batch_id 全链路；批次入队 DB 函数；feeder 批次继承与限量收束；consumer_status 心跳表；proxy_channels 租约写入；wa_check 队列 + LocalExecutor + WaCheckTask（fetcher 侧）。
- 平台后端：runner 批次化（5 个队列入任务类型）、批次 sweeper、停止语义、SSE 事件合成、dispatcher 状态/consumers 端点、start.sh/stop.sh 纳管。
- 平台前端：TaskFormDialog 批次类型表单分支、任务列表批次进度、调度器看板新页面（遵 DESIGN.md）。

### 非目标（P4 不做）

- yiwugo_search / taobao 迁移（yiwugo 保留 subprocess 模型，是 TASK_COMMANDS 唯一残留）。
- 旧代码路径删除（subprocess 采集路径、wa_tasks.py 进程内执行器、cmdparse 的 CLI 解析）——P4 冻结不用，**P5 删除**。
- 多 dispatcher、批次优先级（contact 队列被 feeder 挤占的已知观察随优先级设计另议，见 §8）。
- UI 上一键重启 daemon（本阶段 start.sh/stop.sh shell 管理 + UI 只读展示）。
- shop/company 批次的「限类目/限关键词」细粒度投喂（v1 批次 = discover + 全量类目种子 + limit 页数收束）。

## 3. 设计要点

### 3.0 前置裁定：工作区卫生

用户工作区有未提交的 wa pairing 功能改动（`platform/web/src/lib/api.ts`、`pages/wa/*`、`server/app/api/wa.py` 等）。P4 会触碰 `api.ts`（TaskType/TaskParams）、Tasks 相关组件——**呈用户裁定**：建议先把该功能的改动提交或 stash 再开 P4 分支，否则 scoped commit 需精确到 hunk，误带风险高。此裁定写入 ledger 第 1 条。

### 3.1 批次模型（work_items 全链路）

- **批次 = tasks 表一行**；`batch_id = tasks.id`。创建（POST /api/tasks）只建 pending 任务行；启动（POST /{id}/start）才 INSERT 工作项。
- **work_items 加 `stopped` 终态**（fetcher db.py）：claim 只认 `pending` 天然排除；`finish_work_item` 终态集合扩注释；DDL 注释同步。无需新列。
- **批次入队函数**（fetcher db.py 新增，平台经 fetcher 包调用——平台 venv 已装有 fetcher，runner 本来就 import 不到？**裁定**：平台不 import fetcher，批次 SQL 写在平台侧 app/db 层，与 fetcher db.py 同事务语义对齐；两边 SQL 重复是有意为之的边界）：
  - contact 类：`enqueue_contact_batch(queue, site, domain_suffix, batch_id, limit)`——复用 topup 同事务语义（SELECT pending shops → INSERT items 带 batch_id → shops 置 in_progress，BEGIN IMMEDIATE 单事务），避免与 daemon 自喂 topup 双喂撞车。limit>0 限量。
  - shop/company 类：`enqueue_feeder_batch(queue, site, batch_id, limit)`——INSERT 1 条 discover item + `iter_active_categories` 种子 category items（均带 batch_id）。
- **feeder 批次继承与收束**（fetcher 侧改动）：discover 产出的 category item、链式续喂的下一页 item、失败补插 item 一律**继承父 item 的 batch_id**；续喂/补插前检查 `SELECT count(*) WHERE batch_id=? AND status='done'` ≥ 批次 limit（limit 存 payload `batch_limit`）则停止续喂，批次自然收束。batch_id NULL 的 daemon 自喂行为逐字不变（现状链路不受影响）。
- **停止语义**（基准文档 §5）：stop → 平台侧 `UPDATE work_items SET status='stopped' WHERE batch_id=? AND status='pending'`；claimed 项跑完当前项后自然终态。sweeper 每 tick 强一致性兜底（ stopped 批次的 pending 项再压一次 stopped，防 daemon 重启 `reset_claimed_work_items` 把 claimed 回 pending 后复活）。
- **repeat_interval 兼容**：批次任务保留循环语义——sweeper 判定 done 且 repeat_interval>0 且未 stop_requested → 到点重新入队同参数批次（复用 `_auto_restart` 的 Timer 机制，改调批次入队而非 runner.start）。

### 3.2 任务类型映射

| 平台任务类型 | 模型 | 队列 / CLI |
|---|---|---|
| `1688_contact`（改） | 批次 | `crawl_1688_contact` |
| `madeinchina_contact`（新） | 批次 | `crawl_mic_contact` |
| `1688_shop`（改） | 批次 | `crawl_1688_shop` |
| `1688_company`（改） | 批次 | `crawl_1688_company` |
| `madeinchina_shop`（新） | 批次 | `crawl_mic_shop` |
| `wa_check`（改） | 批次 | `wa_check`（LocalExecutor） |
| `yiwugo_search`（不动） | subprocess | 保留 TASK_COMMANDS 唯一项 |

`TASK_TYPES` = 批次类型集 ∪ {yiwugo_search}；`TASK_COMMANDS` 只剩 yiwugo_search；`IN_PROCESS_TYPES` 清空（wa_tasks.py 冻结，P5 删）。TaskParams：批次类型只保留 `limit`、`repeat_interval`（+ wa_check 的 `accounts` 及节奏参数，见 §3.4）；workers/channels/headless/use_proxy 等变为 daemon 启动参数（平台不再逐任务下发）——**这是用户可见的行为变化，SPEC 明示**：节奏与代理配置收敛到 daemon 级，逐任务覆盖能力取消。`api/tasks.py` 的 preview/parse 端点对批次类型返回描述文案（"批次提交：{queue}，{limit} 条"），cmdparse 对旧 CLI 文本的解析冻结。

### 3.3 批次状态机与 sweeper（平台后端）

- 批次任务无子进程，状态由 **sweeper**（runner 内一个守护线程，5s tick，短事务）派生写回 tasks 表：
  - `running`：存在 pending/claimed 项；
  - `done`：全部终态且无 failed（或 failed 占比容忍？**裁定**：有任何 failed 仍算 done，failed 计数进 progress——与现状 CLI「部分店铺失败但整体跑完=done」语义一致）；`stopped`：stop_requested 且 pending 已清空；`failed`：仅 sweeper 自身异常兜底。
  - `progress_json` 每 tick 节流（1s）写 `{total, done, failed, stopped, claimed, pending, updated_at}`（聚合 `GROUP BY status`）。
- `runner.startup()` 孤儿清理**跳过批次类型**（它们由 daemon 服务，uvicorn 重启不影响）；sweeper 启动时对所有非终态批次任务做一次状态重建。
- **SSE 事件合成**：`GET /tasks/{id}/events` 对批次类型改从 work_items 合成——回放最近 200 条（finished 项，message = `✓ {domain或标识}` / `✗ ... {reason}`，level 映射），增量 1s 轮询 `WHERE batch_id=? AND finished_at 新于游标`；status 帧/心跳/关流语义复用现状。daemon 自身日志进 `logs/daemon.log`（ops 用），不写 task_events（边界裁定：fetcher 不碰平台表）。
- **前端进度**：Tasks 列表批次类型显示 `done/total（failed 标红）`；日志抽屉无改动（SSE 契约不变）。

### 3.4 wa_check 迁入 dispatcher

- **资源令牌**：wa_check 工作项 `requires='["local"]'`；QueueSpec `requires={"local"}`。LocalExecutor 消费者 `resources={"local"}`；BrowserConsumer `{"channel","browser"}` 不含 local → 结构性互斥，浏览器消费者永不领 wa_check。
- **工作项粒度**：一项 = 一批 ≤50 个号码（对齐 check.js 协议与现状 BATCH_SIZE），payload `{numbers, account, batch_limit_params}`。入队函数（fetcher 侧新增，daemon 内 topup 角色）：`SELECT contacts WHERE wa_checked_at IS NULL AND mobile 非空` → normalize 去重 → 按 50 切块 → 账号按批轮换写入 payload。批次任务的账号清单存任务 params，入队时展开。
- **LocalExecutor**（fetcher engine 扩展）：daemon 增加 N 个无浏览器消费者线程（默认 2，`--local-workers`），跑同一 QueueRouter acquire 循环，`ctx.resources={"local"}`，无 BrowserManager/通道分配。wa_check 队列入注册表的条件守卫：vendor check.js 存在 + node 可用，不满足则跳过注册并 log 警告（防御性）。
- **WaCheckTask**（fetcher 新模块 `fetcher/fetcher/wa_task.py`，不走 sites 插件体系——非站点任务）：acquire 走 router；fetch = `CheckWhatsApp` 原子（现成，`atoms/wa_check.py`）；on_success 写回 `contacts.wa_registered/wa_checked_at`（逻辑移植自 `wa_tasks._apply_results`：后 11 位 LIKE + normalize 校验 + 歧义跳过，北京时间）；节奏（逐号间隔经 env、批间休息、错误率 ≥30% 风控冷却 20~30min）经让出型冷却——wa_check 无 site，冷却键用队列名（cooldown_until 键语义从 site 泛化为「队列/站点标识」，实现上 wa_check 项 site=NULL、冷却键取 queue）。
- **停止协作**：沿用现状三层（stop_event / 每批查 DB stop_requested→**改查批次 stopped 标记** / 原子 SKIPPED）。
- 平台侧 `wa_tasks.py` 冻结（P5 删）；`wa_login.py`（扫码登录）留在平台不动（它是请求-响应式 UI 流程，不是队列工作）。

### 3.5 daemon 可观测（consumer_status 表）

```sql
CREATE TABLE IF NOT EXISTS consumer_status (
    consumer_id TEXT PRIMARY KEY,     -- "w0".."wN" / "local0"..
    kind TEXT NOT NULL,               -- browser / local
    tunnel TEXT, exit_ip TEXT,
    current_queue TEXT, current_item_id INTEGER, current_batch_id INTEGER,
    cooldowns_json TEXT,              -- {"1688": 到期epoch, ...}
    updated_at TEXT NOT NULL          -- 北京时间
);
```

- **写方（fetcher daemon）**：claim/finish/release/冷却登记时即时更新 + 10s 心跳；退出清空。短事务 + busy_timeout 沿用。
- **读方（平台 API）**：`GET /api/dispatcher/status`（daemon 存活=心跳新鲜度<30s + 队列深度聚合）与 `GET /api/dispatcher/consumers`（全量行）。stale 行（updated_at 超 30s）前端灰显「已离线」。
- **proxy_channels 租约**：daemon 启动按 tunnel 匹配 `UPDATE proxy_channels SET used_by_task=consumer_id`（列名不改，语义复用为 consumer 租约——避免改名迁移，基准文档 :197 的改名裁定降级为「语义复用 + 注释」）；退出清零。平台 proxy_ops 的 refresh/probe 不写该列，无冲突。

### 3.6 daemon 生命周期纳管

- `start.sh` 加 `start_daemon()`：照抄现有幂等模式（pidfile `run/daemon.pid`、日志 `logs/daemon.log`、nohup `server/.venv/bin/python -m fetcher daemon`，cwd=项目根）。默认全量 5+1 队列。
- `stop.sh` 加 `stop_daemon()`：graceful_stop(SIGTERM→5s→SIGKILL)——daemon 已注册 SIGTERM 优雅退出（engine.py，P3 现状），语义匹配；pkill 兜底特征 `fetcher.*daemon`（**注意不误伤**：该特征只匹配命令行含 daemon 的 fetcher 进程，手动旧 CLI 不含）。
- 防双 daemon：start.sh 的 is_running(pidfile) 幂等 + README 注明「平台纳管后不要再手动起 daemon」。
- 席位预算：daemon 1 进程（多 context）+ yiwugo subprocess 偶发 1 进程 + 手动爬虫 ≤ solo 5 席，现状可容。

### 3.7 前端

- **TaskFormDialog**：`isWaCheck` 二分支改为三分支（批次采集 / wa_check / yiwugo）：批次采集分支只留 `limit`（contact=条数、shop/company=页数，Label 按类型切换文案）+ `repeat_interval` + 模板/导入能力保留；隐藏 workers/proxy/headless/节奏等全部 daemon 级字段。wa_check 分支现状不变（accounts 勾选等）。`TASK_TYPE_OPTIONS` 加 madeinchina_contact/madeinchina_shop；`paramsSummary` 适配。
- **Tasks 列表**：批次类型进度列显示 `{done}/{total}` + failed 计数（failed>0 时 `text-destructive`），无 progress_json.last_line 时回退现状展示。
- **调度器看板**（新页面 `/dispatcher`，Layout navItems 加「调度器」入口，图标 `Network`）：
  - 顶部 StatCard 行（`grid grid-cols-1 gap-4 md:grid-cols-3`）：daemon 状态（在线 sky / 离线 neutral）、工作项积压（pending 总数，backlog token）、今日完成（done 计数）。
  - 队列深度表：5+1 行（队列、pending/claimed/done/failed 计数），表格外层 `rounded-lg border border-border`，数值列 `text-right`。
  - 消费者表：consumer chip（复用 workerChip 哈希色模式）、kind、通道/出口 IP、当前队列+工作项、各站点冷却倒计时（本地 1s setInterval 倒数，模式复用 RestartCountdown；冷却中的站点徽标 amber `text-amber-600 dark:text-amber-400`）。
  - 轮询：`useApiData(fetcher, hasActive ? 5_000 : 30_000)` 自适应（照抄 Tasks 模式）；页面骨架 PageHeader→内容→PageState 三态。
  - 新颜色需求评估：预计无需新 token（复用 status 业务色 + emerald/amber/sky 语义色阶）；如确需新增，走 tokens.css 双主题成对 + tailwind.config 映射两步。

## 4. 契约与行为后果（外部依赖假设表）

| # | 假设 | 依据 | 验证方式 |
|---|---|---|---|
| C1 | daemon 心跳/状态写入（每 consumer 10s UPSERT + 事件即时写）不与爬虫写库产生 WAL 阻塞 | 现状多进程 WAL 读写已共存（爬虫 + 平台）；短事务 + busy_timeout=30s 约定 | 冒烟：daemon 全队列跑时平台 API 读 consumer_status 无超时 |
| C2 | `CheckWhatsApp` 原子从 daemon 进程调用与从 uvicorn 调用等价（env 协议、cwd、node 解析） | 原子自包含（atoms/wa_check.py），env 传递不依赖调用进程 | wa_check 端到端冒烟（小批量真实查号） |
| C3 | SSE 合成事件（1s 轮询 work_items）时延可接受（≤2s） | 现状 SSE 本就是 1s 轮询 task_events | 冒烟观察日志抽屉刷新 |
| C4 | sweeper 5s tick + GROUP BY 聚合在 work_items 百万行内性能可接受 | 有 idx_work_items_claim；batch_id 无索引——**需加索引** `idx_work_items_batch(batch_id, status)`（幂等迁移） | 聚合查询 EXPLAIN + 冒烟实测 |
| C5 | 无第三方新依赖 | 前端不引入新组件库（进度条用文本比例，不装 shadcn Progress） | package.json 零变更检查 |

## 5. 职责分配（初始化 + 变更路径）

| 状态 | 初始化 | 谁写 | 谁读 |
|---|---|---|---|
| work_items.batch_id | 批次入队（平台 SQL / discover 继承） | 入队函数；feeder 续喂/补插继承 | sweeper 聚合、SSE 合成、停止 UPDATE |
| work_items.status='stopped' | 平台停止批次 | 平台 stop 端点 + sweeper 兜底 | claim 排除（status='pending' 过滤天然成立） |
| tasks.status（批次类型） | sweeper 派生 | sweeper 唯一写方（start/stop 端点写 stop_requested） | tasks API、前端列表 |
| tasks.progress_json（批次） | sweeper 1s 节流 | sweeper | tasks API、前端进度列 |
| consumer_status 行 | daemon claim/事件/心跳 | fetcher daemon 唯一写方，退出清空 | dispatcher API → 看板 |
| proxy_channels.used_by_task | daemon 启动/退出 | fetcher daemon（租约语义） | 看板通道列、providers 页（现状展示兼容） |
| contacts.wa_registered | WaCheckTask.on_success | fetcher daemon（LocalExecutor） | 平台 data API（现状读取路径不变） |
| shops.status（contact 批次） | 入队置 in_progress | 平台入队 SQL（与 topup 同事务语义） | daemon topup（跳过 in_progress）、data 页 |

## 6. 冲突扫描与裁定

1. **runner.startup 孤儿清理**：批次类型必须跳过（§3.3），否则 uvicorn 重启把运行中批次标 failed——已有裁定。
2. **daemon 自喂 topup vs 平台批次入队双喂**：contact 入队复用同事务语义（§3.1），两路径都走「SELECT pending→INSERT→置 in_progress」单事务，互不重复。daemon topup 产出的 item batch_id=NULL，不进任何批次进度。
3. **reset_claimed_work_items 复活 stopped 批次**：sweeper 兜底压平（§3.1），裁定接受秒级窗口。
4. **TASK_TYPES/TaskParams/TaskFormDialog/task-ui 四处同步点**（AGENTS.md §5）：全部有对应 Step；cmdparse/preview 冻结语义见 §3.2。
5. **用户未提交 wa 改动与 P4 触碰面交叠**（api.ts、Tasks 组件）：§3.0 前置裁定呈用户。
6. **IN_PROCESS_TYPES 清空后 wa_tasks.py 成死代码**：冻结不删（P5），`api/wa.py`（账号/登录）不受影响。
7. **平台 venv 不 import fetcher**：批次 SQL 平台侧重写（§3.1 裁定），防包边界耦合；两版 SQL 语义对齐由同一 SPEC 约束 + 测试锚定。
8. **work_items 需加 batch_id 索引**（C4）：幂等迁移，fetcher db.py 与平台 migrate 双侧都不重建表——索引加在 fetcher 建表 DDL + 平台侧 migrate 探测补建（生产库是 fetcher 侧建的表，平台 migrate 对它只补索引不建表，防御性探测模式）。
9. **per-task 节奏参数取消是用户可见变化**（§3.2）：已明示；旧任务模板含这些字段时前端忽略多余字段（向后兼容读取）。
10. **消费者看板与 P3 冒烟纪律**：本机活爬虫占席位，P4 冒烟 daemon 用 `--workers 1` 且注意 yiwugo/手动爬虫叠加不超 5 席。
11. **fetcher 侧 wa_check 冷却键泛化**（site→队列/站点标识）：cooldown_until 现有读取方只有 eligible_queues（按 q.site 查），wa_check 队列 site=NULL 时查 queue 名——改动点收敛在 eligible_queues 与 _cooldown 的键选择，单测锚定。

## 7. 验收标准

- [x] 全链路：平台创建 1688_contact 批次 → daemon 认领执行 → 列表进度 done/total 增长 → 日志抽屉 SSE 事件流 → 全部终态后任务 done。停止链路：running 中 stop → pending 项 stopped、claimed 跑完 → 任务 stopped。**证据**：plan/ledger.md Step 4.1（批次 101 入队 3 items → daemon claim/finish → sweeper 派生 done + progress{failed:3} → SSE 合成事件 + 增量游标正确）+ plan/smoke-step4.1/daemon.log。
- [x] 跨站填充在平台视角可见：看板消费者表显示同 consumer 在不同站点队列间切换、冷却倒计时正确。**证据**：plan/ledger.md Step 2.2（dispatcher API 聚合真实数据）+ Step 3.2（看板渲染走查，plan/smoke-step3.2）。
- [x] wa_check 全链路：平台建 wa_check 批次（小批量）→ LocalExecutor 执行 → contacts.wa_registered 写回正确。**证据**：plan/ledger.md Step 1.3（专用查号号 xiaohao-4 真实查号，写回 `wa_registered=0 / wa_checked_at=2026-08-08 22:31:52`）+ plan/smoke-step1.3/。
- [x] start.sh/stop.sh 纳管 daemon：起停幂等、SIGTERM 优雅退出、无孤儿。**证据**：plan/ledger.md Step 2.3（真起真停）+ plan/smoke-step2.3/。
- [x] uvicorn 重启不影响运行中批次（孤儿清理跳过 + sweeper 重建状态）。**证据**：plan/ledger.md Step 2.1 单测 + 终审装配层冒烟（uvicorn 重启后 dispatcher API 可达）。
- [x] 前端 `npx tsc -b` 零错误；后端改动重启后冒烟；fetcher 全量测试绿。**证据**：终审全量回归（fetcher 583 + 平台 62 + tsc 零错误）；合并后用户侧独立复跑复核一致。
- [x] daemon.log 无 ERROR 级异常（环境噪声滑块除外，如实记录）。**证据**：plan/smoke-step4.1/daemon.log。

## 8. 风险与回滚

- **风险：批次化砍掉 per-task 节奏参数引发现有任务模板失效**——模板 params 读取向后兼容（多余字段忽略），但行为口径变化需在合并说明中写明。
- **风险：wa_check 迁入引入回归**（账号风控敏感）——放最后一个功能 Phase，前置 Phase 可先独立合并；wa_check 迁移失败可整体回退该 Phase（平台 IN_PROCESS_TYPES 恢复一行的事）。
- **已知观察随带**：contact 队列被 feeder 挤占（P3 终审记录）在平台化后会更明显（feeder 常驻）——P4 不解决优先级，但在看板可见；是否开 issue 由用户定。
- **回滚**：批次类型与 subprocess 类型并存期间（yiwugo 不动），回滚=任务类型映射切回 + daemon 停掉；work_items 的 stopped/batch_id 是纯增量，无破坏性迁移。
