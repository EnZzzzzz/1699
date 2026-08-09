你正在实现 Step 4.1：lib/api.ts 类型。

## 任务描述

先读你的任务 brief（需求唯一来源）：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-brief.md

## 上下文

前端接线 Phase 4 第一个 Step。后端已支持 fb_discover/fb_group 两类型（Phase 3 完成）。
本 Step 给前端类型加对应成员，为后续 Step 4.2-4.4 铺路。改动极小：api.ts 的 TaskType
union + TaskParams interface 各追加几行。类型声明无运行时逻辑，验收以 tsc 通过为准
（不写单测——协调者裁定明确）。

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

完整性（两处都加了）、质量（注释风格对齐既有）、纪律（只改 api.ts）。

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-report.md：
- 改了什么、tsc 输出
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行 tsc 总结
- 疑虑（如有）
- report 路径
