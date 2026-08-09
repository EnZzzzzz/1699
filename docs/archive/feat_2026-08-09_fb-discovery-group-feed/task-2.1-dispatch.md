你正在实现 Step 2.1：FbGroupTask（TDD）。

## 任务描述

先读你的任务 brief（需求唯一来源，含 PLAN Step 2.1 原文、SPEC §5.3/§5.6 精确规格、协调者裁定）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-brief.md`

## 上下文

「Facebook 群 feed 全量采集」Phase 2 第一个 Step。Phase 1（发现层）已完成：fb_groups
表 + save_fb_posts/upsert_fb_groups（Step 1.1）、FetchDdgSerp 原子（1.2）、FbDiscoverTask
（1.3）、discover_fb 队列（1.4）、冒烟（1.5）。本 Step 写 crawl_fb_group 队列的 local
消费者 Task：包装既有 FetchFbGroupPosts 原子（BD/Apify）拉全量帖 → 逐帖落号
fb_contacts → 群状态机 done/failed。Step 2.2 注册队列、2.3 FbPostTask 补位、
2.4 冒烟。

参照：post_task.py（FbPostTask：prepare 崩溃恢复/on_success/set_status）、wa_task.py
（WaCheckTask：acquire 模式）。

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

- 新建 `fetcher/fetcher/sites/facebook/group_task.py`、`fetcher/tests/test_fb_group_task.py`
- db.py 补 3 个写函数（mark_fb_group_done / mark_fb_group_failed / reset_fb_groups_in_progress）
- 遵循既有模式；不重构任务范围外的东西

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）：架构决策、无法弄清未提供代码、方案不确定、
需 brief 未预见的重构。

## 汇报之前：自查

**完整性：** spec 每一条实现了吗？边界（空 phones、无帖、缺 key、provider 未知）？
**质量：** 命名清晰？对齐 post_task/wa_task 模式？
**纪律：** YAGNI？只做了要求的？
**测试：** 真实行为（落库真库断言）？TDD？覆盖充分？输出干净？

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md`：
- 实现了什么、测了什么、测试结果
- **TDD 证据**：RED（命令、失败输出、为什么符合预期）、GREEN（命令、通过输出）
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行测试总结
- 疑虑（如有）
- report 路径
