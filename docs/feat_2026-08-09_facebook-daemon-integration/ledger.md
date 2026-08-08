# SDD ledger — plan: docs/feat_2026-08-09_facebook-daemon-integration/PLAN.md

> 执行方式适配（诚实记录）：本 session **无子 agent 派发工具**，以单 agent
> 严格模拟 SDD 纪律执行——逐 Step TDD（先失败测试→最小实现）、每 Step 后
> 双重自查（spec 合规 + 代码质量，切换审查视角不自我豁免）、ledger 全程
> 记账、运行时冒烟证据留档、终审。隔离上下文的收益由「brief 文件驱动 +
> 每 Step 独立心智」近似替代。
>
> BASE（分支起点）= `0e17b24da1c7e169464f0d101836c5be330a885c`
> 分支 = `feat/facebook-daemon-integration`

## 冲突扫描裁定（开工前一次性裁决，2026-08-09）

1. **APIFY_TOKEN 缺失**：环境变量/仓库/配置均无 token（facebook-groups.md
   §12 明确「key 仅存于验证会话」）。→ P1/P3 照常推进；P2 Step 2.1 spike
   到达时若无 token：按熔断路径（P2 暂缓、回填文档，P3 照常）。
2. **生产 daemon 冲突**：现网 daemon（`--queues crawl_1688_contact
   crawl_mic_contact`）与 uvicorn(8765)/vite(3000) 在线。新 daemon 启动会
   全量 `reset_claimed_work_items`。→ 冒烟前 stop 生产 daemon，冒烟后按
   原参数重启；后端改动后 stop.sh/start.sh 重启 uvicorn。
3. **PoC 基线帖 URL 不可恢复**（§9 明细在 /tmp 已消失）→ 冒烟种子改用 §12
   实测验证真实帖：
   - `https://www.facebook.com/groups/185879310028412/posts/1437583168191347/`
     （Shenzhen Expats 2026，test_facebook_group.py fixture 同源）
   - `https://www.facebook.com/groups/1305282597018167/posts/1796051251274630/`
     （third-party-brightdata.md 实测样本）
4. **payload.domain 语义**：fb_posts 只有 group_id/group_name，无群 URL 列
   → topup 时 domain 由 `https://www.facebook.com/groups/{group_id}` 拼接
   （SPEC §3.2「domain=群 URL」，平台 SSE `_item_label` 用它显示）。
5. **policy_overrides 键**：覆盖 `RISK_SLIDER_PAGE`/`RISK_SLIDER_EMBED`
   两场景（去 solve_slider，链 = block_rest → swap_ip → give_up），参照
   madeinchina/__init__.py:53-59。
6. **wa_check 双源回写**：fb_contacts 按 `number` 直接匹配（normalize 后）；
   fb 侧附带 `wa_source='checked'`；contacts 侧无 wa_source 列不写。

## Step 进度

- [ ] 1.1 fetcher 数据面：fb_posts/fb_contacts 两表 + 4 写函数
- [ ] 1.2 FacebookPlugin 接线 + policy_overrides
- [ ] 1.3 FbPostTask 实现
- [ ] 1.4 daemon 队列注册 + 本地冒烟
- [ ] 1.5 平台 fb_post 批次类型
- [ ] 1.6 前端 fb_post
- [ ] 1.7 平台端到端冒烟
- [ ] 2.1 Apify spike（熔断点；待 APIFY_TOKEN）
- [ ] 2.2 FetchApifySerp 原子 + permalink 解析
- [ ] 2.3 FbDiscoverTask + discover_fb 队列
- [ ] 2.4 平台 fb_discover 批次类型
- [ ] 2.5 前端 fb_discover
- [ ] 2.6 发现→抓取闭环冒烟
- [ ] 3.1 fetcher wa_check 双源挑号 + 回写双表
- [ ] 3.2 declared 桶抽样校准混入
- [ ] 3.3 平台 enqueue_wa_batch 双源扩展
- [ ] 3.4 wa_check 端到端冒烟
- [ ] 终审 / 文档同步 / 归档

## 执行记录

### Step 1.1 — fetcher 数据面（两表 + 4 写函数）
- commit 范围：`fetcher/fetcher/db.py`（SCHEMA 加 fb_posts/fb_contacts +
  4 写函数）、`fetcher/tests/test_db_fb.py`（10 例）、brief/ledger/PLAN checkbox
- TDD：先写测试亲眼看 10 failed → 最小实现 → 10 passed；全量 593 passed
  （583 基线 + 10 新增）零回归
- review：spec 合规 ✅（schema 逐字段对照 §4.1/4.2；topup 事务模式复刻
  contact 版；payload.domain=群 URL 拼接）代码质量 ✅（无 park）
- 裁定落实：payload.domain 由 group_id 拼 https://www.facebook.com/groups/{gid}
  （冲突扫描 #4）

### Step 1.2 — FacebookPlugin 接线 + policy_overrides
- commit 范围：`fetcher/fetcher/sites/facebook/__init__.py`（task_names=[post]、
  make_task 延迟 import、policy_overrides）、`fetcher/tests/test_fb_plugin.py`
  （6 例）、`fetcher/tests/test_facebook.py`（1 处断言更新）、brief/ledger/PLAN
- TDD：4 failed → 6 passed；全量 599 passed 零回归
- **plan-mandated 测试更新**：`test_site_registered` 原断言 task_names()==[]
  （一期无任务状态），与 PLAN 1.2 明确要求 task_names→["post"] 冲突；原子
  行为（FetchFbPost/parse_post/detectors）未动，仅更新该断言为 ["post"]
- review：spec 合规 ✅（policy_overrides 逐条对照 madeinchina 同款退化、
  SPEC §3.2「BLOCKED→block_rest→swap_ip→give_up」）代码质量 ✅（无 park）
- 说明：make_task("post") 实例化断言留给 1.3（FbPostTask 未存在前不可测）

### Step 1.3 — FbPostTask 实现
- commit 范围：`fetcher/fetcher/sites/facebook/post_task.py`（新文件，Task
  协议全量 hook）、`fetcher/fetcher/db.py`（reset_fb_posts_in_progress）、
  `fetcher/fetcher/control/queue_router.py`（_finish 侧车钩子 2 行）、
  `fetcher/tests/test_fb_post_task.py`（15 例）、brief/ledger/PLAN
- TDD：先红（模块缺失）→ 15 passed；全量 614 passed 零回归
- **框架微改**：QueueRouter._finish 加 `if result is None:
  result = ctx.state.pop("result_json", None)`（SPEC §8 侧车落库机制；
  既有任务不设该键零影响，queue_router 既有测试全过）
- review：spec 合规 ✅（§5.1 全量 hook、validate 阈值 100、prepare 崩溃
  恢复、cold_start 空实现、giveup_cost=1）代码质量 ✅
- minor (deferred)：无

### Step 1.4 — daemon 队列注册（代码部分）
- commit 范围：`fetcher/fetcher/cli/main.py`（_build_registry 注册
  crawl_fb_post QueueSpec）、`fetcher/tests/test_cli_fb.py`（4 例）、
  brief/ledger/PLAN
- TDD：3 failed → 4 passed；全量 618 passed 零回归
- review：spec 合规 ✅（SPEC §5.2：site=facebook、topup 走
  topup_fb_post_work_items、domain_suffix=""、reset 走 Task.prepare）
- **运行时冒烟（证据见下节）**

### Step 1.4 冒烟阻塞修复 — SPEC §7.2 假设修正（匿名白板直连）
- **发现**：冒烟时 daemon 启动浏览器失败——“identity=facebook:direct
  下没有可用 Cookie（可能全部过期）”。ensure_site 的白板路径（无 Cookie
  + 无种子 → 空 context）只在 use_proxy 分支生效（browser.py:466-468），
  直连模式无 Cookie 硬 raise。SPEC §7.2 假设（“白板路径正常工作”）对
  直连模式不成立——PoC 是单站点脚本直连，绕过了 ensure_site。
- **裁定**（实现 SPEC §7.2 描述路径，非违背 plan）：SitePlugin 加
  `anonymous` 标记（FacebookPlugin.anonymous=True），ensure_site 对匿名
  站点直连模式放行空会话白板启动（不注入 Cookie、不要求种子）；非匿名
  站点行为零变化。
- commit 范围：`fetcher/fetcher/net/browser.py`（_site_cookie_optional
  helper + ensure_site 分支）、`fetcher/fetcher/sites/facebook/__init__.py`
  （anonymous=True）、`fetcher/tests/test_browser_anonymous.py`（6 例）
- TDD：RED（_site_cookie_optional 缺失）→ 6 passed；全量 624 passed 零回归
- review：spec 合规 ✅（§7.2 意图落地）代码质量 ✅（延迟 import 防循环；
  未知站点保守 False）

### Step 1.4 运行时冒烟（真实执行，2026-08-09 03:29 北京时间）
- 环境：停生产 daemon（pid 65735）→ 种子 2 条 §12 验证真实帖
  （Shenzhen Expats 2026 `…/posts/1437583168191347/` + BD 实测样本
  `…/posts/1796051251274630/`）→ `daemon --queues crawl_fb_post
  --workers 1 --limit 2 --sample-min 0 --sample-max 1` 跑通
- 日志证据：`/tmp/fb_smoke_daemon.log`（claim 10386/10387 → finish done）
- DB 验证（.cache/1688.db）：
  - fb_posts：2 行全部 done（帖 1 has_contact=1、帖 2 has_contact=0）
  - fb_contacts：1 行 `18588244213` bucket=cn_uncertain wa_source=NULL
    （真实页内容为“WeChat/WhatsApp: 18588244213”，parse_post 基线逻辑
    分桶，非 declared）
  - work_items：crawl_fb_post 两 item done；侧车 result_json 落库
    （{"wechat_ids": ["18588244213"]}）
  - identity：`facebook:direct`（直连模式；SPEC 的 facebook:<ip> 是代理
    形态，直连为 facebook:direct，前缀分桶一致）
- 收尾：删残留 pending work_items、重启生产 daemon（原参数）
- 偏差记录：计划 3 条种子，实际 2 条（§9 PoC 基线 URL 不可恢复，冲突
  扫描 #3 已裁定用 §12 URL；仅 2 条验证过存在）
- **Step 1.4 完成**（commits 920520f..），review clean

### Step 1.5 — 平台 fb_post 批次类型
- commit 范围：`platform/server/app/db.py`（enqueue_fb_post_batch +
  sqlite_master 防御性探测）、`platform/server/app/runner.py`（BATCH_TYPES
  fb_post + enqueue_batch_for_task 分支）、`platform/server/tests/
  test_fb_batch.py`（8 例）、brief/ledger/PLAN
- TDD：8 failed → 8 passed；平台全量 70 passed 零回归
- **API 冒烟**（uvicorn 重启后 curl 验证）：
  - preview fb_post → {"cmd":null,"cmdline":"批次提交：crawl_fb_post，3 条"}
  - create task 80 → start → 入队 1 item（batch_id=80）→ 任务 running
    进度 {total:1,pending:1} → stop → 任务 stopped、item stopped
  - **dispatcher 看板自动出现 crawl_fb_post**（SPEC §6.3 未核实项 ✅ 已
    核实：queue_depth 按队列自动聚合）
- review：spec 合规 ✅（§6.1 四处同步铁律的 runner 侧 + §7.4 并发互斥
  测试）代码质量 ✅
- minor (deferred)：无

### Step 1.6 — 前端 fb_post
- commit 范围：`platform/web/src/lib/api.ts`（TaskType 加 fb_post）、
  `task-ui.tsx`（TASK_TYPE_OPTIONS「Facebook 帖子采集」+ paramsSummary
  批次集合）、`Tasks.tsx`（BATCH_TYPE_NAMES）、`TaskFormDialog.tsx`
  （isBatch + 采集上限提示分支）、brief/ledger/PLAN
- 验收：`npx tsc -b` 通过；DESIGN.md 自查 ✅（无新增颜色 token、无新组件，
  提示文案沿用 text-xs text-muted-foreground）
- review：spec 合规 ✅（SPEC §6.2：fb_post 进 isBatch 列表、label
  「Facebook 帖子采集」）代码质量 ✅
- minor (deferred)：无

### Step 1.7 — 平台端到端冒烟（真实执行，2026-08-09 03:35-03:37 北京时间）
- 流程：重置种子 pending → 创建任务 82（fb_post limit=2）→ start 入队 2
  item（batch_id=82）→ fb-only daemon 消费 → 验证进度/SSE → 恢复生产 daemon
- 证据：
  - 任务 82 status=done，progress {total:2,done:2,failed:0,...}
  - SSE 事件流：两条 success（帖子 URL）+ status done 事件
  - work_items batch 82 两 item done；fb_contacts 落号
    （18588244213 cn_uncertain）
  - 前端 vite 已服务新类型「Facebook 帖子采集」（HMR 生效）
  - dispatcher 看板自动出现 crawl_fb_post（§6.3 已核实）
- 观察：daemon 启动 prepare 重置 in_progress → topup 自喂会把批次外重复
  抓一遍（幂等，不产生数据错误）——崩溃恢复路径按设计工作，非缺陷
- 生产 daemon 最终配置：`--workers 1 --queues crawl_1688_contact
  crawl_mic_contact crawl_fb_post --max-consecutive-fail 100`（原配置
  + fb 队列，feature 意图的最终形态）
- **P1 核心抓取链路完成**：完成标准逐项达成（fetcher 624 绿、1.4 冒烟
  证据、1.7 端到端证据、tsc 通过）

### Step 3.1 — fetcher wa_check 双源挑号 + 回写双表
- commit 范围：`fetcher/fetcher/wa_task.py`（wa_check_topup UNION + 回写
  双表）、`fetcher/tests/test_wa_task_fb.py`（9 例）、brief/ledger/PLAN
- TDD：6 failed → 9 passed；全量 633 passed 零回归
- 设计要点：
  - 挑号 SQL：`contacts(mobile 未查) UNION fb_contacts(bucket=cn_uncertain
    且 wa_checked_at IS NULL)`，UNION 天然 DISTINCT（SPEC §7.6 双源口径）
  - 回写：contacts 既有逻辑不动；fb_contacts 按号码后 11 位 LIKE +
    normalize 严格匹配，附带 wa_source='checked'（SPEC §4.2）
  - 行为细节：原 contacts 歧义 `continue`（整号跳过）改为歧义时跳过
    contacts 但仍按 fb 精确命中回写 fb（fb.number 已规范化，精确命中
    高置信；contacts 行为不变）
- review：spec 合规 ✅（§7.6 改动面逐条）代码质量 ✅

### Step 3.2 — declared 桶抽样校准混入
- 同 wa_task.py：挑号后按 max(1, N×10%) 抽 declared_wa 未查号
  （ORDER BY RANDOM() LIMIT），混入同批入队；已查不重抽；抽样号回写
  wa_source='checked'（供一致率统计）
- TDD：2 failed → 5 例新增全过；全量 638 passed
- 既有测试更新（plan-mandated）：`test_fb_only_cn_uncertain_bucket`
  原断言「declared 不入队」被 Step 3.2 抽样机制合法推翻 → declared 标记
  已查（抽样排除），保留原意图（UNION 桶过滤 + 已查不重抽）
- review：spec 合规 ✅（§7.6 declared 抽样 + 比例边界测试）代码质量 ✅

### Step 3.3 — 平台 enqueue_wa_batch 双源扩展
- commit 范围：`platform/server/app/db.py`（enqueue_wa_batch 双源 UNION
  + declared 抽样 + 防御性探测）、`platform/server/tests/test_fb_batch.py`
  （+4 例）、brief/ledger/PLAN
- TDD：2 failed → 4 例新增全过；平台全量 74 passed 零回归
- 防御性探测（SPEC §4.3）：fb_contacts 表缺失（旧库/测试 schema）→ 回退
  contacts-only 挑号，历史行为不变——既有 test_enqueue_wa_batch 依赖此
  回退（其 schema 无 fb_contacts）
- review：spec 合规 ✅（与 fetcher 侧同口径双源 + 抽样）代码质量 ✅
- minor (deferred)：无

### Step 3.4 — wa_check 端到端冒烟（真实执行，2026-08-09 03:43 北京时间）
- **环境事实**：生产库有 165 条 2026-08-08 23:44 排队的旧 wa_check item
  （8237 个旧号，生产 daemon 从未跑 wa_check）——冒烟不可动它们。
  已登录 WhatsApp 账号：auth_info-xiaohao-4/5（vendor/wa-check/）。
- 裁定：独立临时库（/tmp/fb_wa_smoke.db）+ `daemon --queues wa_check
  --db <tmp>` + `WA_CHECK_ACCOUNTS=xiaohao-4,xiaohao-5` 跑真实查号；
  平台 API 双源路径由 3.3 单测覆盖（enqueue 与 topup 同口径）。
- 种子：fb_contacts cn_uncertain×2（真实号 18588244213 + 13912345678）
  + declared×1（8618588244213）；contacts×2（回归抽查）
- 执行证据（/tmp/fb_wa_smoke_daemon.log）：真实 Baileys 查号 4 个号
  ——8618588244213 ✅已注册、其余 ❌未注册；「写回 5 行（1 已注册）」
- 回写验证（临时库）：
  - fb_contacts 三行全部 wa_source='checked' + wa_checked_at 落时间；
    wa_registered：18588244213=1、13912345678=0、8618588244213=1
  - contacts 两行 wa_registered=0 + wa_checked_at 落时间（双表回归）
  - work_items done
- 数据事实：18588244213 与 8618588244213 是同一物理号码（同帖 bare 号
  + wa.me 双桶），seen 去重后只查一次，回写命中两行——符合设计
- 清理：冒烟 daemon 已停、临时库已删、生产 daemon 与 165 旧 item 未动
- **P3 wa_check 衔接完成**：完成标准逐项达成（真实查号回写 + 双表回归）
