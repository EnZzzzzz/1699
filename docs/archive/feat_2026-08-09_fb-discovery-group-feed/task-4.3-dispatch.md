你正在实现 Step 4.3：TaskFormDialog.tsx 两独立表单分支（主要改动面）。

## 任务描述

先读你的任务 brief（需求唯一来源，含 PLAN Step 4.3 原文、SPEC §7.3/§7.4 精确规格、协调者裁定）：
/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-brief.md

## 上下文

前端接线 Phase 4 第三个 Step，也是前端主要改动面。Step 4.1/4.2 已加类型与摘要。
本 Step 给 TaskFormDialog 加 fb_discover（DDG 关键词 SERP）与 fb_group（群帖采集）
两个独立表单分支——现有 isBatch/isWaCheck/默认 三选一扩为五形态。既有三分支行为
必须零回归。

**DESIGN.md 铁律**（改 platform/web 必守）：SelectTrigger 必须 `h-8` + 显式
`font-medium`；hint `text-xs text-muted-foreground`；Label `text-sm`；按钮
`variant="outline" size="sm"`。先读 DESIGN.md（/Volumes/DataDrive/proj/public/1699/DESIGN.md）。

## 开始之前

对需求/验收/实现方案有疑问——现在就问（特别是 Textarea 用组件还是原生、五形态分支顺序）。

## 你的工作

1. 严格实现 brief 要求的内容，不多不少（含既有分支零回归）
2. 验证：cd platform/web && npx tsc -b（全绿）+ 表单运行时验证（编辑回填/模板回填/
   预览不崩/提交不崩——report 记录证据）
3. commit（约束见 brief 末尾）
4. 自查
5. 汇报

工作目录：/Volumes/DataDrive/proj/public/1699

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT），不要硬猜。前端无单测基建（brief 已说明），
运行时验证是唯一证据——做不了就明确说，别编造。

## 汇报之前：自查

完整性（四新 state + 五形态渲染 + buildParams/validate/fillFromParams/paramsKey 全改）、
质量（DESIGN.md 合规）、纪律（既有分支零回归、只改 TaskFormDialog.tsx）、验证（tsc +
运行时证据）。

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md：
- 改了什么、tsc 输出、运行时验证证据（命令输出/截图/API 响应）
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行 tsc/验证总结
- 疑虑（如有）
- report 路径
