你正在实现 Step 1.3：FbDiscoverTask（TDD）。

## 任务描述

先读你的任务 brief（需求唯一来源，含 PLAN Step 1.3 原文、SPEC §5.2 精确规格、协调者裁定）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-brief.md`

## 上下文

「Facebook 发现层」feature 第三个实现 Step。Step 1.1 落库函数（save_fb_posts/
upsert_fb_groups）、Step 1.2 FetchDdgSerp 原子（parse/classify 纯函数）均已完成。
本 Step 写 discover_fb 队列的 local 消费者 Task：消费 work_items → 调原子 → 分流落库。
供 Step 1.4 队列注册引用。

参照：fetcher/fetcher/wa_task.py（WaCheckTask 形态）、fetcher/fetcher/sites/facebook/
post_task.py（on_success 落库 + set_status 模式）。

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

- 新建 `fetcher/fetcher/sites/facebook/discover_task.py`、`fetcher/tests/test_fb_discover_task.py`
- 遵循既有 Task/DB/测试模式；不重构任务范围外的东西

## 力不从心时

停下承认并升级（BLOCKED/NEEDS_CONTEXT）：架构决策、无法弄清未提供代码、方案不确定、
需 brief 未预见的重构。

## 汇报之前：自查

**完整性：** spec 每一条实现了吗？边界（kind=None、空 results、空标题、无 group_id）？
**质量：** 命名清晰？对齐 wa_task/post_task 模式？
**纪律：** YAGNI？只做了要求的？
**测试：** 真实行为（落库真库断言）？TDD？覆盖充分？输出干净？

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-report.md`：
- 实现了什么、测了什么、测试结果
- **TDD 证据**：RED（命令、失败输出、为什么符合预期）、GREEN（命令、通过输出）
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行测试总结
- 疑虑（如有）
- report 路径
