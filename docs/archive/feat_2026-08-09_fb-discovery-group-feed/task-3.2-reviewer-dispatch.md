你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §6.2 为本 Step 规格主体）：
1. `enqueue_fb_discover_batch(batch_id, keywords, pages) -> int`：关键词（换行分隔）逐词 × 页码展开；payload `{"kind":"serp","engine":"ddg","query":kw,"page":N}`；requires='["local"]'、site=NULL、batch_id；幂等：同 query+page 已有 pending 跳过；keywords 空 → 0。返回入队 item 数。
2. `enqueue_fb_group_batch(batch_id, provider, posts_per_group, limit) -> int`：BEGIN IMMEDIATE 单事务：SELECT pending fb_groups（limit>0 限量）→ INSERT work_items（payload `{"url","provider","limit"}`，limit=posts_per_group）→ 源行置 in_progress；fb_groups 表不存在 → 返回 0（防御性探测，对齐 enqueue_fb_post_batch）。返回入队行数。
3. 协调者裁定：① 收尾 Step 3.1 懒导入（并入函数顶部集中 import）② discover 展开逻辑（splitlines、strip 过滤空行、pages<1 视为 1、json_extract 幂等参照 enqueue_feeder_batch）③ group 事务模式对齐 enqueue_fb_post_batch（timeout=30 + busy_timeout=30000 + sqlite_master 探测 + BEGIN IMMEDIATE + rollback/raise + finally close）④ limit 是群数上限（0=不限）⑤ 时间戳 _bj_now()。
4. 测试（扩展 test_batch_tasks.py）：展开数（2 词 × 2 页 = 4）、幂等（二次调用入队 0）、空关键词 → 0、payload 断言（kind/engine/query/page、requires='["local"]'、site=NULL、batch_id）、fb_group 限量（limit=2 取 2 群）、表缺失返回 0、fb_group payload 断言（url/provider/limit=posts_per_group）、源行置 in_progress。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-report.md
（报告含 1 个疑虑：discover 幂等检查与 INSERT 无 BEGIN IMMEDIATE——与 enqueue_feeder_batch 同型，brief 裁定 2 明确参照）

## 待 review 的 diff

**Base：** dc717aa
**Head：** HEAD（当前 6896454）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.2-review.md

只读一次 diff 文件。diff 的上下文行就是变更后的文件。不要重跑 git 命令。不要在代码库里漫游；只在能说出具体风险时才检查 diff 之外的代码（如 enqueue_fb_post_batch / enqueue_feeder_batch / enqueue_wa_batch 的既有结构作对照）。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。报告里的设计理由也是声称——就代码论代码。

## 测试

implementer 已跑过测试（test_batch_tasks 28/28 + test_fb_batch 14/14 回归）。不要为确认其报告而重跑套件。只有当读代码产生具体疑问时才跑聚焦测试。

## Part 1：Spec 合规

对照"需求是什么"检查 diff：缺失/多余/误解。无法仅凭 diff 验证的报 ⚠️ 项。

## Part 2：代码质量

关注点分离、错误处理、DRY、边界情况；测试验证真实行为；文件职责清晰；是否撑大既有文件。

每条发现要有 file:line。你的最后一条消息就是报告本身：直接以 spec 合规结论开头，每行都是结论或发现，不要开场白、不要过程叙述、不要结尾总结。

## 校准

Important = 不修就不能信任本 Step；Minor = 覆盖可更全/润色。brief 明确要求的缺陷仍是发现（报 Important 并标注 plan-mandated）。先肯定做得好的再列问题。

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
