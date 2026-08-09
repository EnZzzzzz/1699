你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §6.3 为本 Step 规格主体）：
1. TaskParams 追加四字段：`keywords: str | None = None`（fb_discover：查询词，换行分隔原文）、`pages: int | None = None`（fb_discover：每词页数 1-10）、`provider: str | None = None`（fb_group：brightdata / apify）、`posts_per_group: int | None = None`（fb_group：每群帖数上限）。
2. 协调者裁定：插入位置在 accounts 之后、repeat_interval 之前；注释带中文说明；测试断言 `'fb_discover' in TASK_TYPES` 且 `'fb_group' in TASK_TYPES`；round-trip 测试（TaskParams 落库读回或 model_dump 往返）；不验证取值区间（前端职责）。
3. 测试（扩展 test_batch_tasks.py）：TaskCreate 携带四字段 round-trip；TASK_TYPES 并集含两新类型。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-report.md

## 待 review 的 diff

**Base：** fd29bf1
**Head：** HEAD（当前 d90e01f）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.3-review.md

只读一次 diff 文件。diff 的上下文行就是变更后的文件。不要重跑 git 命令。不要在代码库里漫游；只在能说出具体风险时才检查 diff 之外的代码（如 create_task 端点如何落 params_json）。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。

## 测试

implementer 已跑过测试（test_batch_tasks 30/30 + 72 全量）。不要为确认其报告而重跑套件。只有当读代码产生具体疑问时才跑聚焦测试。

## Part 1：Spec 合规

对照"需求是什么"检查 diff：缺失/多余/误解。无法仅凭 diff 验证的报 ⚠️ 项。

## Part 2：代码质量

关注点分离、错误处理、DRY、边界情况；测试验证真实行为；文件职责清晰；是否撑大既有文件。

每条发现要有 file:line。你的最后一条消息就是报告本身：直接以 spec 合规结论开头，每行都是结论或发现，不要开场白、不要过程叙述、不要结尾总结。

## 校准

Important = 不修就不能信任本 Step；Minor = 覆盖可更全/润色。先肯定做得好的再列问题。

## 输出格式

### Spec 合规
- ✅ 合规 | ❌ 发现问题（带 file:line）
- ⚠️ 无法从 diff 验证

### 优点

### 问题
#### Critical（必须修）
#### Important（应当修）
#### Minor（可改可不改）

### 评估
**Step 质量：** [通过 | 需要修复]
**理由：** [1-2 句]
