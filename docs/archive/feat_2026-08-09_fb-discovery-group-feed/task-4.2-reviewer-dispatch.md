你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §7.2 为本 Step 规格主体）：
1. `TASK_TYPE_OPTIONS` 追加两项：fb_discover → 「Facebook 帖子发现」、fb_group → 「Facebook 群帖采集」。
2. `paramsSummary` 追加两分支：
   - fb_discover → `N 词 × M 页` + 循环（N=keywords 按换行拆词计数，M=pages 缺省 1）。
   - fb_group → `provider=Bright Data|Apify` + `每群≤N帖`（posts_per_group）+ `群数上限=M`（limit，0=不限）+ 循环。
3. 协调者裁定：新分支必须置于既有 BATCH_TYPES 集合检查之前（否则落入通用 limit 摘要）；不要把两新类型加进 BATCH_TYPES 集合；fb_discover 空 keywords 显示「默认矩阵」；provider 缺省 Bright Data；limit 缺省/0 → 群数不限；复用 humanizeSeconds；只改 task-ui.tsx；验收 tsc 全绿。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-report.md
（报告声称 esbuild 冒烟验证 7 组用例，fb_post 对照仍走通用分支）

## 待 review 的 diff

**Base：** 15a0d90
**Head：** HEAD（当前 9c20140）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-review.md

只读一次 diff 文件。diff 的上下文行就是变更后的文件。不要重跑 git 命令。不要在代码库里漫游。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。

## 测试

tsc 由 implementer 已跑过（全绿）。不要重跑。只有读代码产生具体疑问才跑聚焦检查。

## Part 1：Spec 合规

对照"需求是什么"检查 diff：缺失/多余/误解。无法仅凭 diff 验证的报 ⚠️ 项。

## Part 2：代码质量

分支顺序正确（新分支在 BATCH_TYPES 检查前）？格式精确（N 词 × M 页、provider=… 每群≤N帖 群数上限=M）？复用 humanizeSeconds？边界（空 keywords、limit=0、缺省值）？

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
