你正在实现 Step 4.2：task-ui.tsx。

## 任务描述

先读你的任务 brief（需求唯一来源，含 PLAN Step 4.2 原文、SPEC §7.2 精确规格、协调者裁定）：
/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-brief.md

## 上下文

前端接线 Phase 4 第二个 Step。Step 4.1 已给 TaskType/TaskParams 加类型。本 Step 改
task-ui.tsx：TASK_TYPE_OPTIONS 加两项（类型下拉 label）+ paramsSummary 加两分支
（任务列表参数摘要）。**关键**：新分支必须置于既有 BATCH_TYPES 集合检查之前（否则
落入通用 limit 摘要），详见 brief 裁定 1。

## 开始之前

对需求/验收/实现方案有疑问——现在就问。

## 你的工作

1. 严格实现 brief 要求的内容，不多不少
2. 验收：cd platform/web && npx tsc -b（全绿）
3. commit（约束见 brief 末尾）
4. 自查
5. 汇报

工作目录：/Volumes/DataDrive/proj/public/1699

## 汇报之前：自查

完整性（两处都加了、分支位置正确）、质量（格式精确、复用 humanizeSeconds）、纪律（只改 task-ui.tsx）。

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-report.md：
- 改了什么、tsc 输出、可选的自查验证输出
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行 tsc 总结
- 疑虑（如有）
- report 路径
