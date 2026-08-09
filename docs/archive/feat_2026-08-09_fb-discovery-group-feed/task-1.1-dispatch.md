你正在实现 Step 1.1：DB 前置——fb_groups 建表 + save_fb_posts + upsert_fb_groups（TDD）。

## 任务描述

先读你的任务 brief（它是你的需求唯一来源，含 PLAN Step 1.1 原文、SPEC 精确 SQL、协调者裁定）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-brief.md`

## 上下文

这是「Facebook 发现层（DDG SERP 自建）+ 群 feed 全量采集」feature 的第一个实现 Step。
项目分支 feat/facebook-daemon-integration；你改动 fetcher 包的数据层（fetcher/fetcher/db.py
建表区 + 写函数区）并新增数据面测试。这是纯 DB 层的 TDD Step，不涉及 daemon/平台/前端。

重要：这是本 feature 的第一个 commit，没有之前 Step 的产物需要继承。

## 开始之前

如果你对以下任何一点有疑问：需求/验收标准、实现方案、依赖前提、任务描述不清——
**现在就问。** 开始动手之前把疑虑都提出来。

## 你的工作

确认需求清楚之后：
1. 严格实现 brief 要求的内容，不多不少
2. 按 test-driven-development skill 的要求写测试（先写失败测试、看着它失败、再最小实现）——TDD skill 已通过 --skill 加载
3. 验证实现可用（运行 brief 指定的验收命令）
4. commit 你的工作（commit 约束见 brief 末尾，**只精确 add 你自己的文件**）
5. 自查（见下）
6. 汇报

工作目录：/Volumes/DataDrive/proj/public/1699（仓库根，AGENTS.md 已自动装配）

**工作过程中**：遇到意外或不清楚的地方，**提问**。停下来澄清永远是可以的，不要猜。
迭代时只跑与改动对应的聚焦测试；commit 之前跑一次相关回归，不要每次编辑都全量跑。

## 代码组织

- 遵循 brief 定义的文件结构与插入位置（db.py 建表区、写函数区）
- 每个文件一个明确职责、接口清晰
- 修改的既有文件（db.py）已经很大：小心操作，只在指定区域做增量，报告里记为 concern 不要重构任务范围外的东西

## 力不从心时

停下来承认"这个对我来说太难"永远是可以的。出现以下情况立即停下并升级（BLOCKED/NEEDS_CONTEXT）：
- 任务需要在多个合理方案间做架构决策
- 需要理解未提供的代码且无法弄清
- 不确定自己的方案是否正确
- 任务需要以 brief 未预见的方式重构既有代码

## 汇报之前：自查

**完整性：** spec 每一条都实现了吗？边界情况处理了吗？
**质量：** 命名清晰准确吗？代码干净可维护吗？遵循了 db.py 既有模式吗？
**纪律：** 有没有过度设计（YAGNI）？只做了要求的东西吗？
**测试：** 测试验证真实行为（不是 mock 行为）吗？遵守 TDD 了吗（每个测试都先看它失败过）？测试覆盖充分吗？测试输出干净吗？

自查发现问题就现在修，修完再汇报。

## 报告格式

把完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md`：
- 实现了什么
- 测了什么、测试结果
- **TDD 证据**：RED（运行的命令、实现前的失败输出、为什么符合预期）、GREEN（运行的命令、实现后的通过输出）
- SPEC §8.1 回填内容（spike 复核结论按 brief 第 5 条裁定写入）
- 改动的文件
- 自查发现（如有）
- 任何问题或疑虑

然后只回复以下内容（15 行以内——细节都在 report 文件里）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- 创建的 commit（短 SHA + 标题）
- 一行测试总结（如 "14/14 passing，输出干净"）
- 你的疑虑（如有）
- report 文件路径
