你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §7.1 为本 Step 规格主体）：
1. `TaskType` 追加 `'fb_discover' | 'fb_group'`。
2. `TaskParams` 追加 `keywords?: string`（换行分隔原文）、`pages?: number`、`provider?: string`、`posts_per_group?: number`。
3. 协调者裁定：TaskType 在 'fb_post' 之后追加；TaskParams 在 accounts 之后追加（带中文注释）；只改 api.ts；验收 npx tsc -b 全绿；类型声明无运行时逻辑不写单测（TDD 例外）。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-report.md

## 待 review 的 diff

**Base：** 95fd521
**Head：** HEAD（当前 a8edfe3）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-review.md

只读一次 diff 文件。diff 的上下文行就是变更后的文件。不要重跑 git 命令。不要在代码库里漫游。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。

## 测试

tsc 由 implementer 已跑过（全绿）。不要重跑。只有读代码产生具体疑问才跑聚焦检查。

## Part 1：Spec 合规

对照"需求是什么"检查 diff：缺失/多余/误解。无法仅凭 diff 验证的报 ⚠️ 项。

## Part 2：代码质量

类型定义是否精确（pages/posts_per_group 是 number 非 string）？注释风格对齐？是否撑大文件？

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
