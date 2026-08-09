# PLAN — Facebook 发现层（DDG SERP 自建）+ 群 feed 全量采集

> 版本：v1 · 2026-08-09 · 评审稿
> 依据：同目录 SPEC.md（设计唯一来源）；执行按 subagent-driven-development skill
> 逐 Step 派发 implementer 子 Agent（写代码遵守 test-driven-development skill），
> 每 Step 后双重 review（spec 合规 + 代码质量），修复循环 5 轮熔断，完成后终审。

## Phase 清单

| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
|---|---|---|---|---|
| 1 发现层（fetcher 侧） | FetchDdgSerp 原子 + FbDiscoverTask + discover_fb 队列 + DB 前置 | 6 | 无 | pending |
| 2 群采集（fetcher 侧） | fb_groups 数据面 + FbGroupTask + crawl_fb_group 队列 + FbPostTask 补位 | 4 | Phase 1 Step 1.1 | pending |
| 3 平台批次 | BATCH_TYPES 双类型 + enqueue 双函数 + TaskParams + 平台测试 | 4 | Phase 1 + 2 | pending |
| 4 前端 | api.ts/task-ui/TaskFormDialog/Tasks.tsx 五处同步 + tsc | 5 | Phase 3 | pending |
| 5 端到端冒烟 + 收尾 | 真实批次闭环 + 看板 + 文档同步 + 归档 | 4 | 全部 | pending |

依赖关系：P1 → P2（DB 共享）→ P3 → P4 → P5；P1/P2 其余部分可并行。

---

## Phase 1 — 发现层（fetcher 侧）

**准入**：SPEC 评审通过；DDG html 端点可访问（spike 已证）。
**完成标准**：`python -m fetcher daemon --queues discover_fb` 可跑批；手工灌
work_items 后真实抓取 1-2 词 → fb_posts/fb_groups 出现增量；相关测试全绿。

### Step 1.1 — DB 前置：fb_groups 建表 + save_fb_posts + upsert_fb_groups（TDD）

- [x] `fetcher/fetcher/db.py` 建表区追加 fb_groups 表 + idx_fb_groups_status 索引
      （SPEC §4.1 精确 SQL，幂等）
- [x] 实现 `save_fb_posts(keyword, source, posts) -> int`（INSERT OR IGNORE，url
      UNIQUE，带 keyword/source/group_id/group_name/first_seen_at；返回新增数）
- [x] 实现 `upsert_fb_groups(groups) -> int`（INSERT OR IGNORE，url UNIQUE；已存在
      行不动 status；返回新增数）
- [x] 测试（新文件 `fetcher/tests/test_db_fb_groups.py`）：建表幂等 + save_fb_posts
      去重/溯源 + upsert_fb_groups 去重/不动状态（参照 test_db_fb.py 模式）
- [x] spike 复核：DDG 恢复后单次验证 `&s=10` 分页 200 态（若限流窗口内则等待）；
      复核结论回填 SPEC §8.1
- 预估 40min；验收：上述测试全绿 + `cd fetcher && ../platform/server/.venv/bin/
  python -m unittest discover -s tests -p "test_db_fb_groups.py"`

### Step 1.2 — FetchDdgSerp 原子 + 纯函数（TDD）

- [ ] `fetcher/fetcher/atoms/facebook_discover.py`：
      `_http_get(url, timeout) -> (status, html)`（urllib + UA + gzip 解压，模块级
      便于 mock）
- [ ] `parse_serp_results(html) -> list[{"url","title"}]`（抽 result__a → uddg 解码
      → 标题净化；真实样本 spike/ddg_sample_1.html 截取 fixture）
- [ ] `classify_fb_url(url) -> ("post"|"group", group_id, group_url) | None`
      （POST_RE / GROUP_RE 双正则，SPEC §5.1）
- [ ] `FetchDdgSerp` 原子 run：params 校验、节奏（sample floor 60 + 202 退避
      uniform(180,240)）、Outcome 映射（OK/EMPTY/BLOCKED/NET_ERROR/SKIPPED/FATAL）
- [ ] 测试（`fetcher/tests/test_facebook_discover.py`）：parse 样本结构/标题实体、
      classify 各形态（帖/群主页/slug 群/视频/非 FB）、mock HTTP 全 outcome 路径、
      202→BLOCKED、停止→SKIPPED、节奏 wait 次数
- 预估 60min；验收：新测试全绿 + `test_facebook.py`/`test_facebook_group.py` 回归
  不动（跑全 fb 测试组）

### Step 1.3 — FbDiscoverTask（TDD）

- [ ] `fetcher/fetcher/sites/facebook/discover_task.py`：Task 协议实现（SPEC §5.2）：
      prepare/acquire_item/label/fetch（原子透传节奏）/on_success（save_fb_posts +
      upsert_fb_groups 分流）/on_giveup/make_stats
- [ ] 测试（`fetcher/tests/test_fb_discover_task.py`）：fetch 原子透传、on_success
      分流落库（帖→fb_posts、群→fb_groups、派生群、名称去后缀）、on_giveup 无落库、
      acquire_item 认领
- 预估 40min；验收：新测试全绿

### Step 1.4 — discover_fb 队列注册（TDD）

- [ ] `fetcher/fetcher/cli/main.py _build_registry` 追加
      `QueueSpec(queue="discover_fb", site=None, task=FbDiscoverTask(), topup=None,
      domain_suffix="", requires={"local"})`
- [ ] 测试（并入 test_fb_discover_task.py 或 test_cli_fb.py）：注册存在 + 字段
      断言（site=None、requires={"local"}、topup=None）
- 预估 20min；验收：注册测试全绿 + `--queues discover_fb` 动态校验通过

### Step 1.5 — 发现层运行时冒烟（真实 DDG）

- [ ] 起 daemon（`python -m fetcher daemon --queues discover_fb --local-workers 1`，
      临时 DB 或生产库视环境），手工 INSERT 2 条 work_items（默认矩阵前 2 词 × 1 页）
- [ ] 观察：2 条 item 顺序消费、间隔 ≥60s、fb_posts/fb_groups 出现真实增量
      （若 202 触发，验证退避后继续）
- [ ] 冒烟记录（结果 + 实际耗时 + 限流观测）写入 ledger.md
- 预估 30min（含等待节奏）；验收：fb_posts 或 fb_groups ≥1 行真实新增（202 场景
      下以退避后成功为准）；冒烟记录完整

**Phase 1 完成标准**：Step 1.1-1.5 全部 done（含冒烟记录）；Phase 2 的 Step 2.1
可开始（依赖 1.1 已满足）。

---

## Phase 2 — 群采集（fetcher 侧）

**准入**：Phase 1 Step 1.1 done（fb_groups 表 + upsert 就绪）。
**完成标准**：`--queues crawl_fb_group` 可跑批；mock/真实 provider 采 1 群 →
fb_contacts 增量 + 群状态机 done；相关测试全绿。

### Step 2.1 — FbGroupTask（TDD）

- [ ] `fetcher/fetcher/sites/facebook/group_task.py`：Task 协议实现（SPEC §5.3）：
      prepare（fb_groups in_progress→pending 崩溃恢复）/acquire_item/label/fetch
      （FetchFbGroupPosts 透传 url/provider/limit）/on_success（逐帖 save_fb_contacts
      + mark_fb_group_done 回写）/on_giveup（mark_fb_group_failed）/on_abort/
      giveup_cost/make_stats
- [ ] fetcher/db.py 补 `mark_fb_group_done(url, post_count, has_contact)` /
      `mark_fb_group_failed(url)` / `reset_fb_groups_in_progress() -> int`
- [ ] 测试（`fetcher/tests/test_fb_group_task.py`）：fetch 透传（mock 原子）、
      on_success 逐帖落号 + 群 done 回写、on_giveup 群 failed、prepare 崩溃恢复、
      acquire_item
- 预估 50min；验收：新测试全绿

### Step 2.2 — crawl_fb_group 队列注册（TDD）

- [ ] `_build_registry` 追加 `QueueSpec(queue="crawl_fb_group", site=None,
      task=FbGroupTask(), topup=None, domain_suffix="", requires={"local"})`
- [ ] 测试：注册存在 + 字段断言
- 预估 15min；验收：注册测试全绿 + `--queues crawl_fb_group` 校验通过

### Step 2.3 — FbPostTask.on_success 群 upsert 补位（TDD）

- [ ] `fetcher/fetcher/sites/facebook/post_task.py on_success` 追加：group_id 非空时
      `db.upsert_fb_groups([{"url": 派生群URL, "group_id", "name": item.get("name")}])`
      （SPEC §5.5）
- [ ] 测试（扩展 test_fb_post_task.py）：抓帖后 fb_groups 出现该群（pending、name
      溯源）；无 group_id 时零写入；既有 on_success 测试零回归
- 预估 20min；验收：新断言全绿 + 既有 test_fb_post_task.py 全绿

### Step 2.4 — 群采集运行时冒烟

- [ ] 起 daemon（`--queues crawl_fb_group --local-workers 1`），手工灌 1 条
      work_items（真实群 URL × provider，key 用环境变量或 mock）
- [ ] 观察：FetchFbGroupPosts 执行 → fb_contacts 新增（post_url 溯源正确）→ 群
      done + post_count/has_contact 回写；缺 key 场景验证 FATAL → 群 failed
- [ ] 冒烟记录写入 ledger.md
- 预估 30min；验收：群状态机完成一轮 pending→done（或 key 缺失→failed），
      fb_contacts 落号正确

**Phase 2 完成标准**：Step 2.1-2.4 全部 done；Phase 3 可开始。

---

## Phase 3 — 平台批次接线

**准入**：Phase 1 + Phase 2 done。
**完成标准**：平台创建/启动两个新类型任务 → work_items 正确入队（batch_id/
payload/requires 断言）；平台测试全绿。

### Step 3.1 — runner BATCH_TYPES + enqueue 分支（TDD）

- [ ] `platform/server/app/runner.py` BATCH_TYPES 追加 fb_discover/fb_group
      （SPEC §6.1 精确 dict）
- [ ] `enqueue_batch_for_task` 追加两分支（keywords×pages / provider+posts_per_group
      +limit，缺省值 1/50/brightdata）
- [ ] 测试（扩展 platform/server/tests/test_batch_tasks.py）：enqueue_batch_for_task
      对两类型分派正确（mock app.db 函数断言参数）
- 预估 30min；验收：新测试全绿 + 既有批次测试零回归

### Step 3.2 — app/db.py enqueue 双函数（TDD）

- [ ] `enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`：换行拆词 × 页
      展开，payload {"kind","engine","query","page"}，requires='["local"]'，
      同 query+page 已有 pending 跳过，keywords 空→0
- [ ] `enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`：
      BEGIN IMMEDIATE 单事务 SELECT pending fb_groups → INSERT items → 置
      in_progress；fb_groups 表不存在→0（防御性探测）
- [ ] 测试（扩展 test_batch_tasks.py）：展开数/幂等/空关键词/限量/表缺失返回 0/
      payload 断言
- 预估 40min；验收：新测试全绿

### Step 3.3 — api/tasks.py TaskParams 四字段

- [ ] TaskParams 追加 keywords/pages/provider/posts_per_group（SPEC §6.3）
- [ ] 测试：TaskCreate 携带四字段 round-trip 成功；TASK_TYPES 并集含两新类型
- 预估 15min；验收：测试全绿

### Step 3.4 — 平台冒烟

- [ ] 重启后端（uvicorn 不自动 reload，按 start.sh/stop.sh）；起 daemon 全量
- [ ] API 创建 fb_discover（默认矩阵 × 1 页）→ 断言 work_items 5 条
      （requires=["local"]、engine="ddg"）；创建 fb_group → 断言入队数（fb_groups
      有 pending 时）或 0（空表防御）
- [ ] 冒烟记录写入 ledger.md
- 预估 20min；验收：两类型任务可创建/启动/停止，入队断言正确

**Phase 3 完成标准**：Step 3.1-3.4 全部 done；Phase 4 可开始。

---

## Phase 4 — 前端

**准入**：Phase 3 done。
**完成标准**：`npx tsc -b` 全绿；表单可创建两类型任务；既有类型零回归。

### Step 4.1 — lib/api.ts 类型

- [ ] TaskType 追加 'fb_discover' | 'fb_group'；TaskParams 追加 keywords/pages/
      provider/posts_per_group
- 预估 10min；验收：tsc 通过

### Step 4.2 — task-ui.tsx

- [ ] TASK_TYPE_OPTIONS 追加两项（label「Facebook 帖子发现」/「Facebook 群帖采集」）
- [ ] paramsSummary 追加两分支（N 词 × M 页；provider=… 每群≤N帖 群数上限=M）
- 预估 15min；验收：tsc 通过 + 类型标签渲染

### Step 4.3 — TaskFormDialog.tsx 两独立表单分支（主要改动面）

- [ ] 新表单状态：fbDiscoverKeywords / fbDiscoverPages / fbGroupProvider /
      fbGroupPostsPerGroup
- [ ] 渲染分支扩为五形态：fb_discover 分支（Textarea 预填默认矩阵 §7.4 + 每词页数
      1-10 + 循环 + hint）；fb_group 分支（provider Select h-8 font-medium + 每群
      帖数默认 50 + 群数上限 + 循环 + hint）；isBatch/isWaCheck/默认 分支行为不变
- [ ] buildParams/validate/fillFromParams/paramsKey 增加两分支（校验：pages 1-10、
      posts_per_group ≥1、provider 限定、keywords 换行透传）
- [ ] 测试/验证：编辑模式回填、模板加载回填、预览不崩（现有测试基建若覆盖表单则
      补断言；否则走 tsc + 手工冒烟）
- 预估 60min；验收：tsc 全绿 + 新建两类型任务表单可提交（API 冒烟）

### Step 4.4 — Tasks.tsx BATCH_TYPE_NAMES

- [ ] BATCH_TYPE_NAMES 追加 'fb_discover' | 'fb_group'（批次进度渲染；归档 SPEC
      §6.2 的坑）
- 预估 5min；验收：tsc 通过 + 任务列表进度列对两新类型生效

### Step 4.5 — 前端运行时冒烟

- [ ] vite dev 页面：新建 fb_discover/fb_group 任务（表单默认值正确、hint 展示）、
      列表显示类型标签与参数摘要、进度列渲染
- [ ] 冒烟记录写入 ledger.md
- 预估 15min；验收：页面操作全流程可用

**Phase 4 完成标准**：Step 4.1-4.5 全部 done；`npx tsc -b` 全绿。

---

## Phase 5 — 端到端冒烟 + 文档收尾

**准入**：Phase 1-4 done。
**完成标准**：feature 级验收（SPEC §10）1-6 全部满足；文档同步；目录归档。

### Step 5.1 — 端到端闭环冒烟

- [ ] 起 daemon（全量队列）+ 后端；创建 fb_discover 任务（默认矩阵 × 1 页）→
      跑批 → fb_posts/fb_groups 增量；创建 fb_post 任务 → crawl_fb_post 接续 →
      fb_contacts 增量；创建 fb_group 任务 → 群 feed 采集 → fb_contacts 增量；
      wa_check 批次涵盖新落号码（观察，零改动）
- [ ] dispatcher 看板出现 discover_fb / crawl_fb_group 两条队列
- [ ] 冒烟记录（含实测节奏/限流/耗时）写入 ledger.md
- 预估 60min（含批次节奏等待）；验收：SPEC §10 验收 1/2/4/5 满足

### Step 5.2 — 全量回归

- [ ] fetcher 全测试组（unittest discover）全绿
- [ ] 平台测试组全绿；`npx tsc -b` 全绿
- 预估 15min；验收：三组全绿（SPEC §10 验收 6）

### Step 5.3 — 文档同步

- [ ] AGENTS.md：§1 队列数量 7→9（discover_fb / crawl_fb_group）、§5 批次模型清单
      补两类型
- [ ] docs/channel-research/facebook-groups.md §10/§12「未做」清单更新（发现层已
      自建落地、群 feed 已接队列）
- 预估 15min；验收：两文档与实现一致

### Step 5.4 — 终审 + 归档

- [ ] 全分支终审（subagent-driven-development skill 终审流程）：spec 合规 +
      代码质量 + 冲突扫描结论复核
- [ ] PLAN checkbox 收尾；ledger.md 随代码 commit
- [ ] 整个 docs/feat_2026-08-09_fb-discovery-group-feed/ 移入 docs/archive/
- 预估 20min；验收：归档完成、git 工作区干净（除既有未提交改动）

**Phase 5 完成标准**：全部 Step done；SPEC §10 验收 1-6 全部满足。

---

## 风险与熔断

- **DDG 限流比 spike 更严**（恢复 >150s 或 202 频发）：Step 1.1 复核确认后调整
  原子节奏下限/退避上限（SPEC §8.1 参数可调），不阻断。
- **DDG 全量不可用**：启用 SPEC §8.2 回退分支 1（浏览器渲染抓 Bing），需评审确认
  后调整 Phase 1 后续 Step 范围。
- **Phase 1 冒烟连续 2 批全 BLOCKED**：按 SPEC §8.2 熔断判定执行。
- 计划外问题一律按 issue-create skill 开 issue，不打断当前工作。
