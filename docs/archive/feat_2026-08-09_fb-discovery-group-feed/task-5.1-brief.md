# Step 5.1 — 端到端闭环冒烟

> 这是你的需求唯一来源。PLAN Step 5.1 原文 + 环境事实抄录如下。

## PLAN Step 5.1 原文（验收以 checkbox 为准）

- [ ] 起 daemon（全量队列）+ 后端；创建 fb_discover 任务（默认矩阵 × 1 页）→
      跑批 → fb_posts/fb_groups 增量；创建 fb_post 任务 → crawl_fb_post 接续 →
      fb_contacts 增量；创建 fb_group 任务 → 群 feed 采集 → fb_contacts 增量；
      wa_check 批次涵盖新落号码（观察，零改动）
- [ ] dispatcher 看板出现 discover_fb / crawl_fb_group 两条队列
- [ ] 冒烟记录（含实测节奏/限流/耗时）写入 ledger.md
- 预估 60min（含批次节奏等待）；验收：SPEC §10 验收 1/2/4/5 满足

## SPEC §10 验收标准（feature 级，本 Step 覆盖 1/2/4/5）

1. 平台创建 fb_discover 任务（默认矩阵 × 1 页）→ daemon local 消费者节奏跑批 →
   fb_posts 出现 source='ddg' 的帖行、fb_groups 出现群行（SERP 群主页 + 帖派生群），
   keyword 溯源正确；同批/循环重跑无重复行（url UNIQUE）。
2. 平台创建 fb_group 任务 → daemon 调 FetchFbGroupPosts → 群状态机
   pending→in_progress→done/failed 流转、post_count/has_contact/last_crawled_at
   回写 → fb_contacts 出现群帖号码（post_url 溯源正确）。
3. （FbPostTask 种子路径②——Step 5.1 的 fb_post 任务顺带验证）
4. wa_check 批次自动涵盖新落的 fb_contacts 号码（既有双源链路，零代码改动，冒烟
   观察）。
5. dispatcher 看板出现 discover_fb / crawl_fb_group 两条队列（queue_depth 自动
   聚合）。

## 环境事实（协调者已验证）

1. **daemon 运行中**（PID 30019，全量队列，start.sh 起的——含 discover_fb/
   crawl_fb_group）；后端 8765、前端 3000 运行中。**复用，不要重启**（start.sh
   nohup 超时坑）。
2. **DDG 当前可达**（协调者 22:00 前实测 200）；但限流窗口未知——spike 实测约 2
   连查后第 3 次 202、封禁窗口约 4 分钟。fb_discover 默认矩阵 5 词 × 1 页 = 5 条
   item，节奏下限 60s → 整批 5-8 分钟 + 可能 1-2 次 202 退避。**有耐心等**。
3. **无 BRIGHTDATA_API_KEY/APIFY_TOKEN**：fb_group 任务会 FATAL → 群 failed
   （缺 key 是既有行为）。Step 5.1 的 fb_group 验证走「FATAL→failed」真实路径，
   done 路径已由 Step 2.4 mock 冒烟覆盖。**不要 mock 真实 daemon 进程**。
4. **生产库有真实数据**：fb_posts 305 done（既有 crawl_fb_post 批次）、fb_contacts
   有号；discover_fb 有 7 条 stopped 残留（Step 3.4 冒烟遗留，不影响）。
5. **wa_check 观察**：新落的 fb_contacts 号码（cn_uncertain 桶）会自动被 wa_check
   topup 挑号入队（双源链路，零改动）——观察 wa_check work_items 是否出现新号
   （已查号码不重复；新增号码批次排队）。
6. **看板 API**：GET http://127.0.0.1:8765/api/dispatcher（或 /api/dispatcher/queues
   ——查一下 api/dispatcher.py 的路由）应含 discover_fb / crawl_fb_group 两队列的
   depth。
7. **任务 API**：POST /api/tasks（创建）、/api/tasks/<id>/start、/api/tasks/<id>/stop、
   GET /api/tasks/<id>/events（SSE/日志）、GET /api/tasks（列表）。
8. **谨慎**：生产库真实操作。fb_discover 会真抓 DDG 落真数据（这是验收要求的）；
   结束后把任务置 stop（pending item 压 stopped，不删数据）。

## 冒烟步骤（建议）

1. **看板**：先 GET /api/dispatcher 确认两条新队列出现（验收 5）。
2. **fb_discover**（验收 1）：POST /api/tasks {"type":"fb_discover","params":
   {"keywords": 默认矩阵五行, "pages": 1}} → start → 轮询任务状态与 work_items
   （discover_fb 5 条 pending→claimed→done/failed）→ 等整批完成（5-15 分钟，含
   节奏）→ 查 fb_posts（source='ddg' 新增行、keyword 溯源）+ fb_groups（新增群行）
   → 记录实测节奏/202 退避/耗时。
3. **fb_post**（验收 3 顺带）：创建 fb_post 任务（limit 小，如 5）→ start → 等
   crawl_fb_post 消费 → 查 fb_contacts 增量 + fb_groups 出现帖派生群（种子路径②，
   source='fb_post'）。
4. **fb_group**（验收 2，缺 key 路径）：创建 fb_group 任务 → start → 观察
   crawl_fb_group 消费 → 群 FATAL→failed（缺 key）→ 查群状态机流转
   pending→in_progress→failed（result_json 含缺 key detail）。done 路径已有
   Step 2.4 mock 覆盖，本步验证真实链路。
5. **wa_check**（验收 4，观察）：若 fb_discover/fb_post 新落了 cn_uncertain 号，
   观察 wa_check work_items 是否出现新号入队（topup 30s 唤醒）——记录观察即可，
   零改动。
6. **清理**：冒烟后把相关任务 stop（pending item 压 stopped），不删数据；报告写
   明创建的任务 id 与终态。
7. **冒烟记录**追加到 ledger.md（结果 + 实测节奏/限流/耗时）。

## 冒烟记录要求（追加到 ledger.md）

```
## Step 5.1 端到端冒烟记录（<日期时间>）
- 看板：discover_fb / crawl_fb_group 队列出现 ✓（depth 值）
- fb_discover 任务 <id>：5 item 消费耗时 <X> 分钟（实测节奏 <Y>s、202 退避 <Z> 次）、
  fb_posts 新增 <n> 行（source='ddg'）、fb_groups 新增 <n> 行
- fb_post 任务 <id>：crawl_fb_post 消费 <n> 帖、fb_contacts 增量、fb_groups 帖派生群
- fb_group 任务 <id>：FATAL→failed（缺 key），群状态机流转观测
- wa_check：新号入队观察 <有/无 + 详情>
- 验收判定：<SPEC §10 验收 1/2/4/5 逐条 满足/不满足>
```

## 你的工作

1. 按上述步骤执行（命令输出全程保留在 report；有耐心等批次跑完）。
2. 验证验收标准（1/2/4/5 逐条）。
3. 冒烟记录追加到 ledger.md 并 commit（只 add ledger.md + report/brief，禁止 -A）。
4. 完整证据写入 report。
5. 发现代码 bug → 停下 BLOCKED 上报（不自己修——修复循环是主 Agent 的职责）。

工作目录：/Volumes/DataDrive/proj/public/1699

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-5.1-report.md`：
- 执行过程与命令输出（API 调用、轮询、DB 查询）
- **验收证据**：fb_posts/fb_groups/fb_contacts/work_items 查询结果（真实行+字段）、
  任务状态流转、看板响应、实测节奏/限流/耗时
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径
