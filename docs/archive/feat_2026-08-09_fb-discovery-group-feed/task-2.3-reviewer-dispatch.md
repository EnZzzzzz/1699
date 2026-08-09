你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §5.5 为本 Step 规格主体）：
1. `fetcher/fetcher/sites/facebook/post_task.py on_success` 追加：group_id 非空时 `db.upsert_fb_groups([{"url": f"https://www.facebook.com/groups/{group_id}", "group_id": group_id, "name": item.get("name") or ""}])`（SPEC §5.5）。
2. 语义：每抓到一帖=发现一个群（种子路径②）；INSERT OR IGNORE 幂等、不触碰既有群状态机（只写 pending 新行），对既有 fb_posts/fb_contacts 状态流零影响。
3. 协调者裁定：group_id 用既有共享 group_id_from_url（urls.py，Step 2.1 提取，不得重复定义）；upsert 调用在 save_fb_contacts+mark_fb_post_done 之后、sidecar 之前；name=item.get("name") or ""；必须显式传 source="fb_post"；幂等/状态机不触碰。
4. 测试（扩展 test_fb_post_task.py）：抓帖后 fb_groups 出现该群（url/group_id/name/status=pending/source='fb_post' 字段断言）；无 group_id 时零写入；既有 on_success 测试零回归。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-report.md
（报告含 1 个疑虑：第 4 个幂等守护测试无独立 RED 阶段——守护已实现的 INSERT OR IGNORE 语义；brief 要求的 3 个测试均有真实 RED）

## 待 review 的 diff

**Base：** 1f6d100
**Head：** HEAD（当前 8c58e4e）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.3-review.md

只读一次 diff 文件。diff 的上下文行就是变更后的文件。不要重跑 git 命令。不要在代码库里漫游；只在能说出具体风险时才检查 diff 之外的代码（如 upsert_fb_groups 的实现、urls.py 共享函数）。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。报告里的设计理由也是声称——就代码论代码。

## 测试

implementer 已跑过测试（test_fb_post_task.py 19/19 + 60 fb 回归）。不要为确认其报告而重跑套件。只有当读代码产生具体疑问时才跑聚焦测试。

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
