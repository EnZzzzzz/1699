你正在执行 Step 5.1：端到端闭环冒烟。

## 任务描述

先读你的任务 brief（需求唯一来源，含 SPEC §10 验收 1/2/4/5 的精确标准、环境事实、冒烟步骤）：
/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-5.1-brief.md

## 上下文

Phase 5 第一个 Step，feature 级端到端验证（最重的一步）。Phase 1-4 已完成：发现层
（discover_fb）+ 群采集（crawl_fb_group）+ 平台批次接线 + 前端全就绪。本 Step 在
生产环境跑真实闭环：fb_discover 抓 DDG 落 fb_posts/fb_groups → fb_post 接续 →
fb_group（缺 key FATAL 路径）→ wa_check 观察新号入队 → 看板两条队列。

**关键约束**：
- daemon（PID 30019）/backend/frontend 均运行中，复用不重启
- 生产库真实操作，谨慎；冒烟后任务置 stop，不删数据
- fb_group 走缺 key FATAL→failed 真实路径（done 已由 Step 2.4 mock 覆盖），不要 mock
- 有耐心等批次跑完（fb_discover 5 词 × 60s 节奏 ≈ 5-15 分钟 + 202 退避）
- 发现代码 bug → 停下 BLOCKED 上报，不要自己修代码

## 开始之前

对步骤/验收/环境有疑问——现在就问。

## 你的工作

1. 按 brief 步骤执行（看板 → fb_discover → fb_post → fb_group → wa_check 观察；
   命令输出保留）
2. 验证验收标准（SPEC §10 1/2/4/5 逐条）
3. 冒烟记录追加到 ledger.md 并 commit（只 add 你的文件，禁止 -A）
4. 完整证据写入 report

工作目录：/Volumes/DataDrive/proj/public/1699

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）。DDG 限流是预期观测（记录退避即可）；连续 2 批
全 BLOCKED 才按 SPEC §8.2 熔断判定上报。

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-5.1-report.md：
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
