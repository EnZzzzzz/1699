你正在执行 Step 5.2：全量回归。

## 任务描述

先读你的任务 brief（需求唯一来源）：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-5.2-brief.md

## 上下文

Phase 5 第二个 Step，纯回归验证（零代码改动）。feature 代码已全部完成（Step 1.1-5.1），
本 Step 跑三组全量：fetcher unittest、平台 unittest、前端 tsc。spec 验收 6 要求三组全绿。

## 开始之前

对步骤/验收有疑问——现在就问。

## 你的工作

1. 按 brief 命令跑三组回归（输出保留）
2. 有不绿的：判断归属（本 feature vs 既有），本 feature 引入 → BLOCKED 上报
3. 报告写入 report 文件 + ledger 一行记录，commit（只 add 你的文件）

工作目录：/Volumes/DataDrive/proj/public/1699

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-5.2-report.md：
- 三组命令与输出（测试数、通过数、耗时）
- 失败清单（如有）+ 归属判断
- ledger.md 追加内容

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行回归总结
- 疑虑（如有）
- report 路径
