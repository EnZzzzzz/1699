你正在实现 Step 3.2：app/db.py enqueue 双函数（TDD）。

## 任务描述

先读你的任务 brief（需求唯一来源，含 PLAN Step 3.2 原文、SPEC §6.2 精确规格、协调者裁定）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-brief.md`

## 上下文

「Facebook 发现层 + 群采集」feature 平台批次接线 Phase 3 第二个 Step。Step 3.1 已把
fb_discover/fb_group 注册进 runner BATCH_TYPES + enqueue_batch_for_task 两分支
（懒导入占位）。本 Step 在 platform app/db.py 实现两个真正的 enqueue 函数，并**收尾
Step 3.1 的懒导入**（并入函数顶部集中 import——这是跨 Step 必做项，见 brief 裁定 1）。

参照：`platform/server/app/db.py` 的 enqueue_fb_post_batch（BEGIN IMMEDIATE 单事务 +
sqlite_master 防御探测）与 enqueue_wa_batch（requires='["local"]' INSERT 写法）。

## 开始之前

对以下任何一点有疑问——**现在就问**：需求/验收、实现方案、依赖前提、任务描述不清。

## 你的工作

1. 严格实现 brief 要求的内容，不多不少（含懒导入收尾）
2. 按 test-driven-development skill 写测试（先失败、看着失败、最小实现）——TDD skill 已加载
3. 验证（brief 指定验收命令 + 回归）
4. commit（约束见 brief 末尾）
5. 自查
6. 汇报

工作目录：/Volumes/DataDrive/proj/public/1699

## 代码组织

- 改 `platform/server/app/db.py`（两个新函数）、`platform/server/app/runner.py`
  （懒导入收尾）、`platform/server/tests/test_batch_tasks.py`（扩展测试）
- 遵循既有模式；不重构任务范围外的东西

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）：架构决策、无法弄清未提供代码、方案不确定、
需 brief 未预见的重构。

## 汇报之前：自查

**完整性：** spec 每一条实现了吗？边界（空关键词、limit=0、表缺失、同 query+page
幂等）？
**质量：** 命名清晰？对齐 enqueue_fb_post_batch/enqueue_wa_batch 模式？
**纪律：** YAGNI？只做了要求的？
**测试：** 真实行为（临时 sqlite 断言真实行）？TDD？覆盖充分？输出干净？

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-report.md`：
- 实现了什么、测了什么、测试结果
- **TDD 证据**：RED（命令、失败输出、为什么符合预期）、GREEN（命令、通过输出）
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行测试总结
- 疑虑（如有）
- report 路径
