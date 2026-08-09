你正在实现 Step 3.1：runner BATCH_TYPES + enqueue 分支（TDD）。

## 任务描述

先读你的任务 brief（需求唯一来源，含 PLAN Step 3.1 原文、SPEC §6.1 精确规格、协调者裁定）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-brief.md`

## 上下文

「Facebook 发现层 + 群采集」feature 的平台批次接线 Phase 3 第一个 Step。Phase 1-2
（fetcher 侧）已完成：discover_fb / crawl_fb_group 两条队列就绪。本 Step 在平台
runner.py 注册两个批次类型（fb_discover/fb_group）+ enqueue_batch_for_task 两分支。
app/db.py 的两个 enqueue 函数在 Step 3.2 实现——本 Step 测试用 mock 断言分派参数。

**重要**：enqueue_fb_discover_batch / enqueue_fb_group_batch 尚不存在，**不要在本
Step 实现它们**（Step 3.2 的活）。测试 mock app.db 属性即可。

## 开始之前

对以下任何一点有疑问——**现在就问**：需求/验收、实现方案、依赖前提、任务描述不清。

## 你的工作

1. 严格实现 brief 要求的内容，不多不少
2. 按 test-driven-development skill 写测试（先失败、看着失败、最小实现）——TDD skill 已加载
3. 验证（brief 指定验收命令 + 回归）
4. commit（约束见 brief 末尾）
5. 自查
6. 汇报

工作目录：/Volumes/DataDrive/proj/public/1699

## 代码组织

- 只改 `platform/server/app/runner.py`（BATCH_TYPES + enqueue_batch_for_task）与
  `platform/server/tests/test_batch_tasks.py`（扩展测试）
- 遵循既有模式；不重构任务范围外的东西

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）：架构决策、无法弄清未提供代码、方案不确定、
需 brief 未预见的重构。

## 汇报之前：自查

**完整性：** spec 每一条实现了吗？边界（缺省值、显式值、limit 透传）？
**质量：** 命名清晰？对齐既有 BATCH_TYPES/enqueue 模式？
**纪律：** YAGNI？只做了要求的（没实现 app/db.py 函数）？
**测试：** 真实行为？TDD？覆盖充分？输出干净？

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md`：
- 实现了什么、测了什么、测试结果
- **TDD 证据**：RED（命令、失败输出、为什么符合预期）、GREEN（命令、通过输出）
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行测试总结
- 疑虑（如有）
- report 路径
