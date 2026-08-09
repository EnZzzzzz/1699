你正在实现 Step 4.4：Tasks.tsx BATCH_TYPE_NAMES。

## 任务描述

先读你的任务 brief（需求唯一来源）：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-brief.md

## 上下文

前端接线 Phase 4 第四个 Step。Step 4.1-4.3 已完成。本 Step 给 Tasks.tsx 的
BATCH_TYPE_NAMES 集合追加 'fb_discover' | 'fb_group'（否则任务列表进度列不显示
批次进度——归档 SPEC §6.2 的坑）。改动极小：一行集合。

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

完整性、质量、纪律（只改 Tasks.tsx 集合一行）。

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-report.md：
- 改了什么、tsc 输出
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行 tsc 总结
- 疑虑（如有）
- report 路径
