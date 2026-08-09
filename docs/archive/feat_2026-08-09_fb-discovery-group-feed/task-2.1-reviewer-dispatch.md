你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §5.3 为本 Step 规格主体）：
1. 新文件 `fetcher/fetcher/sites/facebook/group_task.py`：local 消费者包装 FetchFbGroupPosts。类属性 name="fb_group"、unit="群"、QUEUE="crawl_fb_group"。
2. prepare(config)：fb_groups in_progress→pending 崩溃恢复（对齐 FbPostTask.prepare），返回 True。
3. acquire_item(ctx)：claim_next_eligible(["crawl_fb_group"], consumer_id_for(ctx))，payload 注入 id。
4. label(item)：`f"{item['url']}（{provider}，≤{limit}帖）"`。
5. fetch(ctx, item)：FetchFbGroupPosts().run(ctx, {"url","provider","limit"})，原子零改动。
6. on_success：逐帖 db.save_fb_contacts(post_url, group_id, post["phones"]) + db.mark_fb_group_done(url, post_count, has_contact)；stats 计数；返回帖数。
7. on_giveup：db.mark_fb_group_failed(item["url"])；返回短语。on_abort：群留 in_progress 返回短语。giveup_cost(item)=1。make_stats()={"ok":0,"empty":0,"failed":0}。
8. db.py 新增 mark_fb_group_done(url, post_count, has_contact)（status=done + post_count/has_contact/last_crawled_at=_now() 回写）、mark_fb_group_failed(url)（status=failed）、reset_fb_groups_in_progress()->int（in_progress→pending 返回行数）。
9. 协调者裁定：group_id 从 item["url"] 解析；on_success 返回 len(posts)；stats 有帖→ok、giveup→failed；set_status 对齐 FbPostTask；prepare 打印对齐 FbPostTask（先 reset 再打印 pending 数，延迟导入 ShopDB）；acquire 对齐 FbDiscoverTask。
10. 测试 `fetcher/tests/test_fb_group_task.py`：fetch 透传、on_success 逐帖落号 + 群 done 回写、on_giveup 群 failed、prepare 崩溃恢复、acquire_item 认领 + id 注入。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md
（报告含 2 个 concerns：① fetch 缺省 provider=None 透传（原子兜底 brightdata）；② prepare 的 print 出现在测试输出尾部——与 test_fb_post_task.py 既有行为一致）

## 待 review 的 diff

**Base：** 5e9dce7
**Head：** HEAD（当前 7a09836）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-review.md

只读一次 diff 文件——它包含 commit 列表、stat 摘要和带上下文的完整 diff。diff 的上下文行就是变更后的文件：除非某个你必须判断的 hunk 在函数中间被截断（并在报告中说明），不要单独 Read 变更文件。不要重跑 git 命令。
不要在代码库里漫游。只在能说出具体风险时才检查 diff 之外的代码（如 FetchFbGroupPosts.run 的返回 data 键、save_fb_contacts 的签名、Task 协议默认实现）——每个风险一次聚焦检查，并在报告中写明。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。报告里的设计理由也是声称——就代码论代码。

## 测试

implementer 已跑过测试（13 新增 + 734 全量）。不要为确认其报告而重跑套件。只有当读代码产生任何已有运行回答不了的具体疑问时才跑聚焦测试。

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
