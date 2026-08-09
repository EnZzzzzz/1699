你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §5.2 为本 Step 规格主体）：
1. 新文件 `fetcher/fetcher/sites/facebook/discover_task.py`：local 消费者，参照 wa_task.py WaCheckTask 形态。类属性 name="fb_discover"、unit="查询"、QUEUE="discover_fb"。
2. prepare(config)：打印队列待处理数，无崩溃恢复，返回 True。
3. acquire_item(ctx)：`claim_next_eligible(["discover_fb"], consumer_id_for(ctx))`，payload 注入 id。
4. label(item)：`f"{item['query']} 第{item['page']}页"`。
5. fetch(ctx, item)：调 FetchDdgSerp 原子，params 透传 query/page/sample_min/sample_max（节奏取 ctx.config.sample_min/max）。
6. on_success(ctx, item, result)：result.data["results"] 分流——kind=="post" → db.save_fb_posts(keyword=item["query"], source="ddg", posts=[{"url","group_id","group_name"}...])；全部 FB 群 URL（群主页+帖派生）→ db.upsert_fb_groups([{"url","group_id","name"}...])（name 去 " | Facebook"/" - Facebook" 后缀）；stats 计数（ok/empty/failed）；返回新增帖数。
7. on_giveup(ctx, item, reason, kind)：BLOCKED/NET_ERROR/EMPTY 无落库，仅日志短语 + stats；返回短语。
8. make_stats()：{"ok": 0, "empty": 0, "failed": 0}。
9. 协调者裁定：kind=None 跳过；帖派生群也 upsert；名称净化 strip+去后缀；on_success 返回 save_fb_posts 返回值；stats 有 results→ok、空→empty、giveup→failed；on_giveup 不落库；prepare 打印风格对齐 WaCheckTask；set_status 对齐 FbPostTask。
10. 测试文件 `fetcher/tests/test_fb_discover_task.py`：fetch 原子透传、on_success 分流落库（帖→fb_posts 溯源、群→fb_groups、派生群、名称去后缀）、on_giveup 无落库、acquire_item 认领 + payload id 注入。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-report.md
（报告含 2 个 concerns：① group_url 缺失时帖派生群不写 fb_groups（防御）；② 全 kind=None 条目按 ok 计——查询成功即 ok）

## 待 review 的 diff

**Base：** ab27fab
**Head：** HEAD（当前 5dff797）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.3-review.md

只读一次 diff 文件——它包含 commit 列表、stat 摘要和带上下文的完整 diff。diff 的上下文行就是变更后的文件：除非某个你必须判断的 hunk 在函数中间被截断（并在报告中说明），不要单独 Read 变更文件。不要重跑 git 命令。
不要在代码库里漫游。只在能说出具体风险时才检查 diff 之外的代码（如 claim_next_eligible 的返回结构、WaCheckTask 的 acquire 模式）——每个风险一次聚焦检查，并在报告中写明。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。报告里的设计理由也是声称——就代码论代码。

## 测试

implementer 已跑过测试（21 新增 + 42 fb 回归 + 29 wa 回归 + 720 全量）。不要为确认其报告而重跑套件。只有当读代码产生任何已有运行回答不了的具体疑问时才跑聚焦测试。

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
