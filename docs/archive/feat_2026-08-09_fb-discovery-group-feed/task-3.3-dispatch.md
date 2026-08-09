你正在实现 Step 3.3：api/tasks.py TaskParams 四字段。

## 任务描述

先读你的任务 brief（需求唯一来源）：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-brief.md`

## 上下文

平台批次接线 Phase 3 第三个 Step。Step 3.1/3.2 已把 fb_discover/fb_group 注册进
BATCH_TYPES + enqueue 分支 + app/db.py 双函数。本 Step 给 TaskParams 加四字段
（keywords/pages/provider/posts_per_group），使 API 层能接收前端提交的参数。
改动小：tasks.py 加 4 行字段 + 测试断言。

## 开始之前

对需求/验收/实现方案有疑问——**现在就问**。

## 你的工作

1. 严格实现 brief 要求的内容，不多不少
2. 按 TDD 写测试（先失败、看着失败、最小实现）——TDD skill 已加载
3. 验证（brief 验收命令 + 回归）
4. commit（约束见 brief 末尾）
5. 自查
6. 汇报

工作目录：/Volumes/DataDrive/proj/public/1699

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT），不要硬猜。

## 汇报之前：自查

完整性（spec 每一条）、质量（对齐既有 TaskParams 风格）、纪律（YAGNI）、测试（真实行为、TDD、覆盖、干净输出）。

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-report.md`：
- 实现了什么、测了什么、测试结果
- **TDD 证据**：RED（命令、失败输出、为什么符合预期）、GREEN（命令、通过输出）
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行测试总结
- 疑虑（如有）
- report 路径
