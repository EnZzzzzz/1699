# task-1.2-brief — P4-1 Step 1.2：WaCheckTask + 入队 feeder

## 位置

P4 第 1 阶段第 2 步（wa_check 迁入 daemon 的核心执行器）。改动范围：
`fetcher/fetcher/wa_task.py`（新模块）、`fetcher/fetcher/cli/main.py`
（wa_check 队列入注册表 + 守卫）、`fetcher/tests/test_wa_task.py`（新测试）。

## 需求（SPEC §3.4 + PLAN Step 1.2）

### 1. WaCheckTask（fetcher/fetcher/wa_task.py 新模块）

不走 sites 插件体系（非站点任务），实现 Task 协议（acquire 走 router 队列）：

- **acquire_item(ctx)**：从 `wa_check` 队列认领（走 db.claim_next_eligible
  ["wa_check"]，consumer_id = f"w{ctx.wid}" 由 QueueRouter 统一处理——
  本 task 在 daemon 里经 QueueRouter 路由，LocalLoop 调 task 协议方法）。
  payload 结构：`{"numbers": [...], "account": <名>, "batch_id": <可空>}`。
  注意：wa_check 队列的入队是 daemon 的 topup feeder（见 §2），
  acquire 只认领已入队的项。
- **fetch(ctx, item)**：调 CheckWhatsApp 原子（atoms/wa_check.py，现成），
  params：`{"numbers": item["numbers"], "default_cc": "86",
  "account": <account>, "sample_min"/"sample_max": 逐号间隔}`。
  原子返回 ActionResult；outcome 透传给 LocalLoop 处置。
- **on_success(ctx, item, result)**：写回 contacts（移植 wa_tasks._apply_results
  语义——后 11 位 LIKE 候选 + normalize 严格校验 + 歧义跳过 + 北京时间），
  返回写回行数。
- **on_giveup(ctx, item, reason, kind)**：记日志返回说明（不写回）。
- **节奏**：逐号间隔经原子 sample_min/max（env 传 check.js）；批间休息与
  风控冷却经**让出型冷却**——fetch 前检查 item 内批次计数，达到
  batch_size（50）边界登记冷却键 `wa_check`（queue 名）让出。**冷却键取
  queue 名**（Step 1.1 泛化已就绪）。
- **停止协作**：LocalLoop 每轮 ctx.stopped() + 原子 SKIPPED；不查平台
  tasks 表（批次 stopped 由平台 sweeper 压 work_items 终态，claim 排除
  pending 即停止）。

### 2. wa_check 队列入注册表（cli/main.py）

- `_build_registry` 加 wa_check spec：
  - queue="wa_check"，site=None，requires={"local"}，topup=wa 入队函数，
    domain_suffix=""。
  - **条件守卫**：vendor/wa-check/check.js 存在 + node 可用才注册；否则
    log 警告跳过（防御性，SPEC §3.4）。
- **入队 feeder（daemon topup 角色，fetcher 侧新增函数）**：
  `wa_check_topup(db, limit) -> int`：
  - `SELECT contacts WHERE wa_checked_at IS NULL AND mobile 非空`
    （仿 wa_tasks._fetch_pending_rows 语义）→ normalize_numbers(mobile,
    "86") 去重 → 按 50 切块 → 账号按批轮换（默认账号池来自配置/环境，
    为空用 ["default"]？**裁定**：空账号池时用 ["default"] 并 log 警告——
    与 wa_tasks 拒绝启动不同，这里是 daemon 常驻，default 账号目录存在
    才可执行，原子层会 FATAL 兜底）→ 每块 INSERT 一条 work_item
    （payload {"numbers","account","batch_size":50}，queue="wa_check"，
    site=NULL，requires='["local"]'，batch_id=NULL）。
  - 幂等：只查未查过的号码（wa_checked_at IS NULL），已入队项不会
    重复产生（下次 topup 时号码已被查过或已 pending？**裁定**：topup
    不做 pending 去重——daemon 常驻时每 30s 唤醒，同一批号码只在首次
    入队，claim 后 items 是 claimed/failed 不再被选；但未 claim 的
    pending 项会与下一次 topup 重复入队 → 需按 payload 号码集合去重：
    `SELECT COUNT(*) FROM work_items WHERE queue='wa_check' AND
    status IN ('pending','claimed')` 非空则本次 topup 跳过（整批去重，
    简单可靠））。

### 3. 账号来源

wa_check 的账号池从哪来？现状平台 wa_check 任务 params.accounts。daemon
级收敛（SPEC §3.2：节奏参数收敛 daemon 级）：本 Step 账号池取环境变量
`WA_CHECK_ACCOUNTS`（逗号分隔），空则 ["default"]。平台批次任务的账号
清单存 tasks params——那是 P4-2 Step 2.1 的批次入队内容（平台侧 SQL 按
账号展开），本 Step 只做 daemon 自喂 topup 的账号轮换。

## 验收（TDD，先写失败测试）

1. **wa_check_topup**：未查号码入队（50/块切块正确）；已查过（wa_checked_at
   非空）不入队；幂等（有 pending/claimed 项时跳过）；payload 结构与
   requires='["local"]'；账号轮换（多账号按块轮换）。
2. **WaCheckTask.on_success**：写回 contacts.wa_registered/wa_checked_at
   （后 11 位匹配、歧义跳过、normalize 校验）——移植自 wa_tasks._apply_results，
   测试锚定等价值。
3. **WaCheckTask.fetch**：CheckWhatsApp 原子被正确调用（mock 原子，验证
   params 透传 numbers/account/default_cc）。
4. **注册表守卫**：node 缺失/check.js 缺失时 wa_check 不入注册表（mock
   shutil.which / 文件存在性）。
5. 现有测试不 regress。

## 环境约束

- 全部 mock（node/原子/文件系统），不起真实 node/浏览器。
- 提交前 `cd fetcher && python3 -m pytest tests -q` 全量绿。
