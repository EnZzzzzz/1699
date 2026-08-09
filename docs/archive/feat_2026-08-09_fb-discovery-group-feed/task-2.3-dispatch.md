你正在实现 Step 2.3：FbPostTask.on_success 群 upsert 补位（TDD）。

## 任务描述

先读你的任务 brief（需求唯一来源，含 PLAN Step 2.3 原文、SPEC §5.5 精确规格、协调者裁定）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-brief.md`

## 上下文

Phase 2 第三个 Step，也是整个 feature 里**唯一既有 Task 的改动点**（种子路径②）：
FbPostTask.on_success 追加「每抓到一帖 = 发现一个群」的 upsert_fb_groups。幂等
INSERT OR IGNORE，不触碰既有群状态机与 fb_posts/fb_contacts 状态流。

注意：Step 2.1 修复时已把 group_id 解析提取到共享位置
`fetcher/fetcher/sites/facebook/urls.py`（公共名 `group_id_from_url`），post_task.py
从那里导入。**不要重复定义正则/函数**，直接用既有导入。

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

- 只改 `fetcher/fetcher/sites/facebook/post_task.py` 的 on_success（追加 upsert 调用）
  与 `fetcher/tests/test_fb_post_task.py`（扩展测试）
- 遵循既有模式；不重构任务范围外的东西

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）：架构决策、无法弄清未提供代码、方案不确定、
需 brief 未预见的重构。

## 汇报之前：自查

**完整性：** spec 每一条实现了吗？边界（无 group_id、name 缺省、重复抓帖幂等）？
**质量：** 命名清晰？对齐既有 on_success 模式？
**纪律：** YAGNI？只做了要求的？
**测试：** 真实行为（落库真库断言）？TDD？既有 on_success 测试零回归？输出干净？

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-report.md`：
- 实现了什么、测了什么、测试结果
- **TDD 证据**：RED（命令、失败输出、为什么符合预期）、GREEN（命令、通过输出）
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行测试总结
- 疑虑（如有）
- report 路径
