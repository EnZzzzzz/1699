你正在实现 Step 1.2：FetchDdgSerp 原子 + 纯函数（TDD）。

## 任务描述

先读你的任务 brief（它是你的需求唯一来源，含 PLAN Step 1.2 原文、SPEC §5.1 精确规格、协调者裁定）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-brief.md`

## 上下文

这是「Facebook 发现层」feature 的第二个实现 Step。Step 1.1 已完成（fb_groups 建表 +
save_fb_posts/upsert_fb_groups 落库，commit 96129f8）。本 Step 建 DDG SERP 抓取原子
（urllib 裸 HTTP）+ parse/classify 纯函数，供 Step 1.3 的 FbDiscoverTask 透传调用。
不涉及 daemon/平台/前端。

参考实现：`fetcher/fetcher/atoms/facebook_group.py`（_http_json + FetchFbGroupPosts
原子的 Outcome 映射/catch/节奏模式）。

## 开始之前

对以下任何一点有疑问：需求/验收标准、实现方案、依赖前提、任务描述不清——**现在就问**。

## 你的工作

1. 严格实现 brief 要求的内容，不多不少
2. 按 test-driven-development skill 写测试（先失败测试、看着它失败、再最小实现）——TDD skill 已加载
3. 验证实现可用（运行 brief 指定的验收命令 + 回归 test_facebook*.py）
4. commit 你的工作（约束见 brief 末尾）
5. 自查
6. 汇报

工作目录：/Volumes/DataDrive/proj/public/1699

## 代码组织

- 新建 `fetcher/fetcher/atoms/facebook_discover.py`（原子 + 3 个模块级函数），
  新建 `fetcher/tests/test_facebook_discover.py`
- 遵循 facebook_group.py 既有模式；不重构任务范围外的东西

## 力不从心时

停下来承认"这个对我来说太难"永远是可以的。出现以下情况立即停下并升级（BLOCKED/NEEDS_CONTEXT）：
- 任务需要在多个合理方案间做架构决策
- 需要理解未提供的代码且无法弄清
- 不确定自己的方案是否正确
- 任务需要以 brief 未预见的方式重构既有代码

## 汇报之前：自查

**完整性：** spec 每一条都实现了吗？边界情况（202/403/429/5xx/超时/停止/空结果/坏 HTML）处理了吗？
**质量：** 命名清晰？代码干净？对齐了 facebook_group.py 模式吗？
**纪律：** YAGNI？只做了要求的东西？
**测试：** 真实行为？TDD（每个测试先看失败）？覆盖充分？输出干净？

## 报告格式

把完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md`：
- 实现了什么
- 测了什么、测试结果
- **TDD 证据**：RED（命令、失败输出、为什么符合预期）、GREEN（命令、通过输出）
- 改动的文件
- 自查发现（如有）
- 任何问题或疑虑

然后只回复以下内容（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- 创建的 commit（短 SHA + 标题）
- 一行测试总结
- 你的疑虑（如有）
- report 文件路径
