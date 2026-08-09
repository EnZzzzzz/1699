你正在实现 Step 1.4：discover_fb 队列注册（TDD）。

## 任务描述

先读你的任务 brief（需求唯一来源）：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-brief.md`

## 上下文

「Facebook 发现层」feature 第四个 Step。FbDiscoverTask（Step 1.3）已实现，本 Step
把它注册进 daemon 队列注册表 `_build_registry`（discover_fb，local 消费者）。
供 Step 1.5 冒烟使用。改动小：main.py 加一个 QueueSpec + 注册测试。

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

完整性（spec 每一条）、质量（对齐既有 QueueSpec 写法）、纪律（YAGNI）、测试（真实行为、TDD、覆盖、干净输出）。

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-report.md`：
- 实现了什么、测了什么、测试结果
- **TDD 证据**：RED（命令、失败输出、为什么符合预期）、GREEN（命令、通过输出）
- 改动的文件、自查发现、疑虑

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行测试总结
- 疑虑（如有）
- report 路径
