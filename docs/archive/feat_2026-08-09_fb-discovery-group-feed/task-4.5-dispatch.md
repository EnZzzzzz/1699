你正在执行 Step 4.5：前端运行时冒烟。

## 任务描述

先读你的任务 brief（需求唯一来源，含精确冒烟要点与环境事实）：
/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.5-brief.md

## 上下文

前端接线 Phase 4 最后一个 Step。Step 4.1-4.4 已完成（类型/task-ui/表单/进度列，tsc 全绿）。
本 Step 做真实页面冒烟：vite dev（已运行 PID 30015）+ backend（已运行 8765）复用，
playwright 驱动页面验证两类型任务的表单默认值/hint/摘要/进度列/编辑回填。

**关键约束**：
- 不要重启 vite/backend（复用）
- 创建任务会真入队——用 1 词自定义 keywords 减副作用，冒烟后停掉/清理
- 发现前端代码 bug → 停下 BLOCKED 上报，不要自己修代码

## 开始之前

对步骤/验收/环境有疑问——现在就问（特别是 playwright 可用性，先检查）。

## 你的工作

1. 检查 playwright 可用性（npx playwright --version 或系统 chromium）
2. 按 brief 冒烟要点驱动页面（脚本在 /tmp，不入库）
3. 冒烟记录追加到 ledger.md 并 commit（只 add ledger.md + report，禁止 -A）
4. 完整证据写入 report

工作目录：/Volumes/DataDrive/proj/public/1699

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）。playwright 不可用且无法安装时，用 curl+API+
静态检查的替代方案并在 report 说明限制——不要编造页面操作证据。

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.5-report.md：
- 冒烟方法与工具、脚本关键片段
- **验收证据**：页面操作步骤与断言输出（默认值/hint/摘要/进度列/编辑回填）、截图路径
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径
