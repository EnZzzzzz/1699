# PLAN — Facebook 采集接入 daemon 调度（二期编排）

> 版本：v1 · 2026-08-09 · 评审稿
> 关联：SPEC.md（同目录，评审裁决已记录于其 §11）
> 执行方式：subagent-driven-development（每 Step 独立 implementer + 双重 review）；
> 进度双轨：本文件 checkbox（面向人，验收通过才勾）+ ledger.md（面向 Agent，执行时建立）

## Phase 清单

| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
|---|---|---|---|---|
| P1 核心抓取链路 | fb_posts/fb_contacts 数据面 + FbPostTask + crawl_fb_post 队列 + 平台 fb_post 批次类型（含前端）端到端跑通 | 7 | 无 | pending |
| P2 发现层（Apify SERP） | discover_fb 队列 + fb_discover 平台任务类型，关键词矩阵 → fb_posts 自动化喂货 | 6 | P1（fb_posts 表）； spike 失败仅熔断本 Phase | pending |
| P3 wa_check 衔接 | fb_contacts 进 wa_check 双源链路 + 回写双表 + declared 抽样校准 | 4 | P1（fb_contacts 表） | pending |

P2 与 P3 互不依赖，P1 完成后可并行推进。

---

## P1 核心抓取链路

**准入条件**：SPEC 评审通过（✅ 2026-08-09）；`fetch_fb_post` 原子与 37 例
测试为既有基线（不动）。

**完成标准**：
- 全量 fetcher 测试绿（含新增 DB/Task 测试）；
- **运行时冒烟**：手工灌 3 条种子 fb_posts 行 → `python -m fetcher daemon
  --queues crawl_fb_post` 跑通（抓取、落库、状态机流转、fb_contacts 分桶
  正确）→ 平台创建 fb_post 任务 → 进度/停止/SSE 正常；
- `npx tsc -b` 通过。

### Step 明细

- [x] **1.1 fetcher 数据面：两表 + 四个写函数**（预估 30min，依赖：无）
  - `fetcher/fetcher/db.py`：`CREATE TABLE IF NOT EXISTS fb_posts /
    fb_contacts`（schema 见 SPEC §4.1/4.2，建表时机对齐 work_items）；
    `topup_fb_post_work_items(queue, site, limit)`（复刻
    `topup_contact_work_items` 事务模式：BEGIN IMMEDIATE 单事务 SELECT
    pending → INSERT work_items（payload `{"url","domain","name"}`）→
    源行置 in_progress）；`save_fb_contacts(post_url, group_id, phones)`
    （INSERT OR IGNORE upsert，declared_wa 桶 wa_source='declared'）；
    `mark_fb_post_done(url, has_contact)` / `mark_fb_post_failed(url)`。
  - 验收：TDD 先行——`fetcher/tests/test_db_fb.py` 覆盖：建表幂等、
    topup 状态流转与防重、并发 topup 无双写（线程对跑）、save_fb_contacts
    去重与 wa_source 规则、mark_* 流转；全绿。
- [ ] **1.2 FacebookPlugin 接线 + policy_overrides**（预估 15min，依赖：无）
  - `sites/facebook/__init__.py`：`task_names()` → `["post"]`；`make_task`
    延迟 import `post_task.FbPostTask`；补 `policy_overrides`（去
    solve_slider，BLOCKED → block_rest → swap_ip → give_up，参照
    `sites/madeinchina/__init__.py:53-59`）。
  - 验收：单测断言插件注册、task_names、overrides 键集合；既有 FB 测试
    不回归。
- [ ] **1.3 FbPostTask 实现**（预估 40min，依赖：1.1、1.2）
  - 新文件 `sites/facebook/post_task.py`：SPEC §5.1 全量 hook
    （fetch 调原子 / validate 阈值按 PoC 样本复核 / on_success 落库 /
    on_giveup / prepare 崩溃恢复重置 / make_stats / rest_counter /
    compose / summary / giveup_cost / empty_message；`ip_request_budget=60`）。
  - 验收：TDD——`tests/test_fb_post_task.py`（mock ctx/page/原子）覆盖：
    fetch 透传原子结果、validate 边界、on_success 落库调用与返回值、
    prepare 重置 in_progress、on_giveup 标记 failed；全绿。
- [ ] **1.4 daemon 队列注册 + 本地冒烟**（预估 20min，依赖：1.3）
  - `cli/main.py _build_registry` 注册 `crawl_fb_post` QueueSpec（SPEC
    §5.2）；`--queues` choices 自动包含。
  - 验收（运行时冒烟）：`.cache/1688.db` 手工灌 3 条 pending fb_posts
    种子（用 PoC 基线帖 URL）→ `python -m fetcher daemon --queues
    crawl_fb_post` 真实跑通：fb_posts 转 done、fb_contacts 有分桶号码、
    work_items 终态正确、identity 键为 `facebook:<ip>`。冒烟证据记
    ledger。
- [ ] **1.5 平台 fb_post 批次类型**（预估 30min，依赖：1.1）
  - `platform/server/app/db.py`：`enqueue_fb_post_batch(queue, site,
    batch_id, limit)`（复刻 `enqueue_contact_batch` 事务模式，平台侧
    SQL 重写不 import fetcher）+ `sqlite_master` 防御性探测；
    `runner.py`：BATCH_TYPES 加 `fb_post`（kind=`fb_post`）+
    `enqueue_batch_for_task` 分支。
  - 验收：平台侧测试（参照现有 enqueue_* 测试模式）：入队行数/幂等/
    in_progress 互斥、与 daemon topup 并发无双写（SPEC §7.4）；类型
    校验/preview/start/stop 自动兼容冒烟（API 层 curl 验证）。
- [ ] **1.6 前端 fb_post**（预估 20min，依赖：1.5 接口约定）
  - `lib/api.ts`（TaskType+TaskParams）、`task-ui.tsx`（TASK_TYPE_OPTIONS
    「Facebook 帖子采集」+ paramsSummary 批次集合）、`Tasks.tsx`
    （BATCH_TYPE_NAMES）、`TaskFormDialog.tsx`（isBatch 列表加 fb_post，
    表单=limit+循环间隔）。
  - 验收：`npx tsc -b` 通过；对照 DESIGN.md 自查（Select h-8 font-medium、
    按钮 outline sm 等铁律）。
- [ ] **1.7 平台端到端冒烟**（预估 20min，依赖：1.4、1.5、1.6）
  - `platform/start.sh` 拉起全栈 → 前端创建 fb_post 任务（limit=3，种子
    数据沿用 1.4）→ daemon 消费 → 任务页进度/事件流/停止按钮全流程；
    dispatcher 看板出现 crawl_fb_post 队列（SPEC §6.3 未核实项一并验证）。
  - 验收：截图/日志证据记 ledger；Phase 完成标准逐项打勾。

---

## P2 发现层（Apify SERP）

**准入条件**：P1 完成（fb_posts 表在产）；`APIFY_TOKEN` 环境变量可用。

**完成标准**：
- spike 结论回填 SPEC §7.5 与 `third-party-apify.md`；
- **运行时冒烟**：平台创建 fb_discover 任务（2 词 × 1 页）→ fb_posts
  新增去重 pending 行、溯源字段正确 → 接续 fb_post 任务消费（链路闭环）；
- fetcher/平台测试绿、`npx tsc -b` 通过。

### Step 明细

- [ ] **2.1 Apify Google Search Scraper spike**（预估 30min，依赖：无；
  **熔断点**）
  - 免费 $5 额度内实调 actor（候选 `apify/google-search-scraper`）：2 个
    实测查询词 × 2 页，确认 ① `site:` 运算符兼容 ② 分页参数与上限
    ③ 返回结构（organic results URL 字段）④ 实际单价。
  - 验收：结论（actor 名/输入 schema/分页上限/permalink 占比/单价）回填
    SPEC §7.5 与 `facebook-apis/third-party-apify.md`；**spike 失败 →
    本 Phase 暂缓，P3 照常推进**（fb_posts 可脚本灌种子）。
- [ ] **2.2 FetchApifySerp 原子 + permalink 解析纯函数**（预估 40min，
  依赖：2.1）
  - 新文件 `atoms/facebook_discover.py`：urllib 调 actor
    （run-sync-get-dataset-items，模式仿 `fetch_apify_posts`）；Outcome
    映射复用 FetchFbGroupPosts 口径；解析纯函数
    `extract_fb_post_urls(results)`（permalink 判定正则按 spike 样本校准，
    滤群主页/视频等噪声）。
  - 验收：TDD——mock HTTP 覆盖 OK/402/429/401/403/超时/0 结果 + 解析
    函数边界（spike 真实样本入 fixture）；全绿。
- [ ] **2.3 FbDiscoverTask + discover_fb 队列注册**（预估 30min，
  依赖：2.2、1.1）
  - local 消费者 Task（参照 `wa_task.WaCheckTask` 形态）：fetch 调原子 →
    on_success `INSERT OR IGNORE` fb_posts（keyword/source/group 溯源），
    返回新增条数；`cli/main.py` 注册 QueueSpec（site=None、
    requires={"local"}、topup=None）。
  - 验收：TDD（mock 原子）+ 真实冒烟：`daemon --queues discover_fb`
    手工插 1 条 query work_item 真调 Apify（≤$0.01），fb_posts 落行正确。
- [ ] **2.4 平台 fb_discover 批次类型**（预估 25min，依赖：2.3 接口约定）
  - `app/db.py`：`enqueue_fb_discover_batch(batch_id, keywords, pages,
    limit)`——关键词 × 页展开 INSERT work_items（payload
    `{"kind":"apify_serp","query","page"}`，requires=["local"]，同词同页
    pending 幂等跳过）；`runner.py` BATCH_TYPES + 分支。
  - 验收：平台测试（展开数量、幂等、requires 正确）；API 冒烟。
- [ ] **2.5 前端 fb_discover**（预估 25min，依赖：2.4）
  - SPEC §6.2 定死形态：TASK_TYPE_OPTIONS「Facebook 帖子发现」、
    独立表单分支（Textarea 关键词默认五行矩阵预填 + 每词页数 number
    input 默认 1 范围 1-10 + limit + 循环间隔）、api.ts、Tasks.tsx、
    paramsSummary「N 词 × M 页」。
  - 验收：`npx tsc -b` 通过；DESIGN.md 铁律自查。
- [ ] **2.6 发现→抓取链路闭环冒烟**（预估 20min，依赖：2.4、2.5、1.7）
  - 前端创建 fb_discover（2 词 × 1 页）→ fb_posts 新增 → 创建 fb_post
    消费新帖 → fb_contacts 落号；观测 SSE/进度/看板。
  - 验收：证据记 ledger；Phase 完成标准逐项打勾。

---

## P3 wa_check 衔接

**准入条件**：P1 完成（fb_contacts 表在产且有种子数据）。

**完成标准**：
- **运行时冒烟**：fb_contacts 种子（cn_uncertain + declared 两桶）→
  平台创建 wa_check 任务 → fb 号码被查并回写 fb_contacts
  （wa_source='checked'）→ contacts 侧行为零回归（既有 1688 号码照常）；
- fetcher/平台测试绿。

### Step 明细

- [ ] **3.1 fetcher wa_check 双源挑号 + 回写双表**（预估 35min，依赖：1.1）
  - `wa_task.py`：`wa_check_topup` 挑号 SQL 扩展为
    `contacts ∪ fb_contacts`（fb 侧仅 bucket='cn_uncertain' 且
    wa_checked_at IS NULL；DISTINCT 去重）；WaCheckTask 回写按号码双表
    UPDATE（contacts 与 fb_contacts 各 UPDATE 一次，幂等命中；fb 侧
    附带 wa_source='checked'）。
  - 验收：TDD——双源混合、去重、仅 cn_uncertain 桶、回写落表正确、
    1688-only 场景零回归；全绿。
- [ ] **3.2 declared 桶抽样校准混入**（预估 20min，依赖：3.1）
  - 挑号时 declared_wa 桶按 ~5-10% 随机抽样混入（实现：每批 N 个不确定
    号配 max(1, N×10%) 个 declared 抽样，SQL `ORDER BY RANDOM() LIMIT`
    或等效）；抽样结果同样回写 wa_source='checked'，供一致率统计。
  - 验收：TDD——抽样比例边界（空桶/小样本/比例计算）、不重复抽样
    （wa_checked_at 排除已查）；全绿。
- [ ] **3.3 平台 enqueue_wa_batch 双源扩展**（预估 25min，依赖：3.1）
  - `app/db.py` 的 wa 批次挑号 SQL 同步扩展（与 fetcher 侧同口径：双源
    UNION + 抽样），平台侧重写 SQL 不 import fetcher。
  - 验收：平台测试（双源入队数量、去重、账号轮换不回归）。
- [ ] **3.4 wa_check 端到端冒烟**（预估 20min，依赖：3.1-3.3、P1 冒烟数据）
  - 种子 fb_contacts（真实 PoC 号码：cn_uncertain 2 个 + declared 1 个）
    → 平台 wa_check 任务 → 回写验证 → contacts 既有号码回归抽查。
  - 验收：回写行 wa_registered/wa_checked_at/wa_source 正确；证据记
    ledger；Phase 完成标准逐项打勾。

---

## 收尾（全部 Phase 完成后）

- [ ] 全分支终审（subagent-driven-development 终审环节）。
- [ ] 文档同步：`docs/channel-research/facebook-groups.md` §10/§12「未做」
  清单与 `facebook-summary.md` §3 待办勾销二期项；AGENTS.md §1/§5 若涉及
  任务类型清单更新则同步。
- [ ] 归档：本目录（含 ledger.md 与 brief/report/review 文件）移
  `docs/archive/`。
