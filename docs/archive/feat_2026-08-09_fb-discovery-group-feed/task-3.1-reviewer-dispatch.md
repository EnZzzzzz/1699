你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §6.1 为本 Step 规格主体）：
1. `runner.py BATCH_TYPES` 追加：`"fb_discover": {"queue": "discover_fb", "site": None, "domain_suffix": "", "kind": "fb_discover"}` 和 `"fb_group": {"queue": "crawl_fb_group", "site": None, "domain_suffix": "", "kind": "fb_group"}`（BATCH_TYPE_NAMES 自动并集）。
2. `enqueue_batch_for_task` 追加两分支：
   - `if spec["kind"] == "fb_discover": return enqueue_fb_discover_batch(task_id, params.get("keywords") or "", int(params.get("pages") or 1))`
   - `if spec["kind"] == "fb_group": return enqueue_fb_group_batch(task_id, (params.get("provider") or "brightdata"), int(params.get("posts_per_group") or 50), limit)`
3. 协调者裁定：两分支在 fb_post 分支之后、return 0 之前；enqueue_fb_discover_batch / enqueue_fb_group_batch 尚不存在（Step 3.2 实现），本 Step 测试 mock app.db 函数断言参数透传，不得实现 app/db.py 函数。
4. 测试（扩展 test_batch_tasks.py）：两类型分派正确（mock app.db 函数断言参数：fb_discover 缺省 keywords=""、pages=1；fb_group 缺省 provider="brightdata"、posts_per_group=50、limit 透传）+ 既有批次测试零回归。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md
（报告含 1 个疑虑：两分支用懒导入而非 SPEC 字面顶部统一 import——函数尚不存在，Step 3.2 落地后收尾）

## 待 review 的 diff

**Base：** 966120b
**Head：** HEAD（当前 acf205a）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-review.md

只读一次 diff 文件。diff 的上下文行就是变更后的文件。不要重跑 git 命令。不要在代码库里漫游；只在能说出具体风险时才检查 diff 之外的代码（如 enqueue_batch_for_task 的既有分支结构、TASK_TYPES 派生）。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。报告里的设计理由也是声称——就代码论代码。

## 测试

implementer 已跑过测试（test_batch_tasks.py 21/21 + 63 全量）。不要为确认其报告而重跑套件。只有当读代码产生具体疑问时才跑聚焦测试。

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
