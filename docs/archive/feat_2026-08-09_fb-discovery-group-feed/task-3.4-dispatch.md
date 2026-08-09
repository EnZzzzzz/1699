你正在执行 Step 3.4：平台冒烟（含 SPEC §6.5 start.sh 改动）。

## 任务描述

先读你的任务 brief（需求唯一来源，含精确冒烟步骤与环境事实）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.4-brief.md`

## 上下文

平台批次接线 Phase 3 最后一个 Step。Step 3.1-3.3 已完成（runner BATCH_TYPES +
enqueue 分支 + app/db.py 双函数 + TaskParams 四字段，代码全绿）。本 Step：
1. 改 platform/start.sh（SPEC §6.5：BRIGHTDATA_API_KEY/APIFY_TOKEN pass-through）
2. 重启后端 + daemon（含新队列）
3. API 创建 fb_discover/fb_group 任务 → DB 断言 work_items

**关键约束**：
- start.sh 是追加（已有 --headed/WA_CHECK_ACCOUNTS 改动已入库），合并不覆盖
- 生产 daemon 34402 可能在运行——保守：stop.sh 停旧 → start.sh 起新（保证新队列注册）
- 生产库只读连接做断言（爬虫可能正在写库）
- 发现代码 bug → 停下 BLOCKED 上报，不要自己修代码

## 开始之前

对步骤/验收/环境有疑问——**现在就问**。

## 你的工作

1. 按 brief 步骤执行（start.sh 改动 + 重启 + API 创建 + DB 断言；命令输出保留）
2. 验证验收标准（两类型任务可创建/启动/停止，入队断言正确）
3. start.sh 改动 + ledger 冒烟记录 commit（只 add 你的文件，禁止 -A）
4. 完整证据写入 report

工作目录：/Volumes/DataDrive/proj/public/1699

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）。生产库操作谨慎：任何 INSERT/UPDATE 生产库
fb_groups 前先确认是否必要，做完清理。

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.4-report.md`：
- 执行过程与命令输出（start.sh 改动、重启、API 调用、DB 断言）
- **验收证据**：work_items 查询结果（真实行+字段）、任务状态流转、daemon 日志片段
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径
