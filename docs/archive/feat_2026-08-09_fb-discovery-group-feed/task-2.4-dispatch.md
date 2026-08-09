你正在执行 Step 2.4：群采集运行时冒烟。

## 任务描述

先读你的任务 brief（需求唯一来源，含精确冒烟步骤与环境事实）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.4-brief.md`

## 上下文

Phase 2 最后一个 Step（运行时冒烟）。Step 2.1-2.3 已完成（FbGroupTask + crawl_fb_group
队列注册 + FbPostTask 补位，代码全绿）。本 Step 做真实运行时验证：缺 key 的 FATAL→群
failed 真实链路（A 段）+ mock 的 pending→done + fb_contacts 落号链路（B 段）。

**关键约束**：
- 无真实 BRIGHTDATA_API_KEY/APIFY_TOKEN（本机未设）→ B 段必须 mock 原子
- 临时 DB 用 `--db`（不认 FETCHER_DB_PATH，Step 1.5 已证实），绝不碰生产库
- 直接 `python -m fetcher daemon`（不要 start.sh）
- 发现代码 bug → 停下 BLOCKED 上报，不要自己修代码

## 开始之前

对步骤/验收/环境有疑问——**现在就问**。

## 你的工作

1. 按 brief 步骤执行（A 缺 key 链路 + B mock done 链路；命令输出保留）
2. 验证验收标准（一轮完整状态机流转 + fb_contacts 落号证据）
3. 冒烟记录追加到 ledger.md 并 commit（只 add ledger.md，禁止 -A）
4. 完整证据写入 report

工作目录：/Volumes/DataDrive/proj/public/1699

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）。mock 方案实现有困难时，report 里说明卡点与
尝试，不要硬凑证据。

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.4-report.md`：
- 执行过程与命令输出（A/B 两段）
- **验收证据**：fb_contacts/fb_groups/work_items 查询结果（真实行数+内容）、状态流转、日志片段
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径
