你在做全分支终审：这是 feature 合并前的最后一道关卡。先看它是否匹配需求（spec 合规），再看它是否构建良好（代码质量），最后分诊 ledger 里的 deferred/parked 发现。终审比 Step 级 review 更宽：你有全部代码 + 全部执行记录。

## feature 是什么

「Facebook 发现层（DDG SERP 自建）+ 群 feed 全量采集」——两条新任务线：
- A. fb_discover：DDG html 端点裸抓 → 解析 FB 群 URL → 帖落 fb_posts、群主页落 fb_groups
- B. fb_group：fb_groups pending 群 → FetchFbGroupPosts（BD/Apify）拉全量帖 → 号码落 fb_contacts → 群状态机 done/failed

## 需求是什么（唯一来源）

- SPEC：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/SPEC.md（设计唯一来源，逐节对照）
- PLAN：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/PLAN.md（Step 划分与验收）
- **SPEC §10 验收标准 1-6 是最终判定依据**（1 fb_discover 闭环、2 fb_group 状态机、3 FbPostTask 种子路径②、4 wa_check 自动涵盖、5 看板两队列、6 全量回归）。
- 各 Step brief/report/review 文件在同目录（task-*.brief.md / task-*.report.md / task-*.review.md）——如需核实某 Step 的实现意图可读。

## 终审输入

1. **审查包**：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/final-review.md（feature 范围 dbab0da..HEAD 的 commits + stat + 代码 diff -U10）
2. **ledger**：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/ledger.md（全部执行记录 + deferred Minor + 终审待分诊发现）
3. **冒烟证据**：Step 1.5/2.4/3.4/4.5/5.1 的 report 含真实运行时证据（SPEC §10 验收 1-5 均已实测通过：1 帖+10 群、FATAL→failed、wa_check 入队链、看板两队列、18 项前端断言）。

## 你的工作（三部分）

### Part 1：Spec 合规（全 feature）
逐条对照 SPEC 检查最终代码：§4 数据模型、§5 fetcher 侧（FetchDdgSerp 原子/纯函数/FbDiscoverTask/FbGroupTask/队列注册/FbPostTask 补位/DB 写函数）、§6 平台侧（BATCH_TYPES/enqueue 双函数/TaskParams/start.sh）、§7 前端（类型/task-ui/表单/进度列）。重点核查跨 Step 一致性（如 FbDiscoverTask.on_success 分流与 save_fb_posts/upsert_fb_groups 签名、payload 键名贯通、requires='["local"]' 全链路）。缺失/多余/误解 → 发现。

### Part 2：代码质量（全 feature）
关注点分离、错误处理、DRY、边界情况、测试质量（真实行为 vs mock）、文件职责、跨模块契约一致性。特别留意：Step 间接口是否咬合（Step 1.2 原子输出 → Step 1.3 Task 消费 → Step 3.2 平台入队 payload 键名全链路）。

### Part 3：deferred/parked 分诊（终审必须做）
读 ledger 的「Minor 记 deferred」与各 Step 执行记录，逐条分诊：哪些必须合并前修（Critical/Important），哪些可延期（Minor），给出裁决理由。重点是：
1. Step 1.1 deferred：两函数相似 for-loop 可抽 helper；缺空 url/group_id None 测试
2. Step 1.2 deferred：5xx 测试未断言节奏 wait；RESULT_A_RE 用 re.S；_http_get timeout 类型标注；双 max 冗余；re-review 补的非数值输入 ValueError 边缘路径
3. Step 1.3 deferred：空 results 的 set_status 只传 empty；全 kind=None 按 ok 计；_make_atom 不缓存
4. Step 1.4/2.2 deferred：test_queues_choices_accept_fb 命名过泛（只断言 crawl_fb_post）
5. Step 2.1 deferred：fetch 的 limit=0 兜底为 10；state 的 n_new 与 len(phones) 口径；测试助手同号不同 bucket 去重丢弃；prepare 打印进测试输出
6. Step 2.3 deferred：test row[0] 位置取值 vs 列名；幂等测试同 name 无法区分
7. Step 3.1/3.2/3.3 deferred：懒导入已收尾（3.2 已并入顶部 import，可关闭）；BATCH_TYPES 格式已修；int(pages) 恒等冗余；discover 幂等无 BEGIN IMMEDIATE 并发窗口；n=0 无操作 commit；round-trip 只测 fb_discover；_conn() 无 try/finally
8. Step 4.2/4.3 deferred：注释「空视为 1」vs「默认矩阵」；空 keywords+显式 pages；fbDiscoverKeywords useState 初始值；fb_group 循环独占一行；batchLimit 重置副作用
9. Step 5.1 发现的框架级问题（重点分诊，是否合并前必修）：
   - ① LocalLoop FATAL 连坐：单队列 FATAL 停全部 local 消费者（wa_check 注释「FATAL→停止」是有意语义，但多队列共享消费者池时需队列级熔断或线程重启）
   - ② wa_check topup 无限补货 + FIFO 认领导致 fb 队列饥饿
   - ③ wa_check topup 在途守卫对 batch_id NULL 的 stale pending 无限期堵塞
   - ④ DDG 限流比 spike 更严（5 词 1 词 200，20% 通过率）——SPEC §8.1 数字可调
   - ⑤ 平台测试既有 StarletteDeprecationWarning（非 feature 引入）

## 判定

最终给：**MERGE READY** / **需要修复**（列出必须修的发现，Critical/Important 分级）+ 每条的 file:line 与修复建议。deferred 分诊给「必须合并前修 / 可延期（记 ledger）」。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。不要重跑 git 命令，不要跑测试（冒烟证据已在 report）。

## 输出格式

### Spec 合规（全 feature）
- ✅ / ❌（带 file:line）

### 代码质量（全 feature）
- 优点
- Critical / Important / Minor（带 file:line）

### deferred/parked 分诊
逐条：必须合并前修 / 可延期，理由

### 终审结论
**MERGE READY** 或 **需要修复** + 理由
