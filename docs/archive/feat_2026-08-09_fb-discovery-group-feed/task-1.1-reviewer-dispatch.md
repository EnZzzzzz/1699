你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录）：
1. fb_groups 建表 SQL（SPEC §4.1 精确）：CREATE TABLE IF NOT EXISTS fb_groups（id/url UNIQUE/group_id/name/source DEFAULT 'ddg'/status DEFAULT 'pending'/post_count/has_contact/first_seen_at/last_crawled_at）+ CREATE INDEX IF NOT EXISTS idx_fb_groups_status ON fb_groups(status, id)，幂等。
2. save_fb_posts(keyword, source, posts) -> int：INSERT OR IGNORE（url UNIQUE），带 keyword/source/group_id/group_name/first_seen_at；返回新增行数。
3. upsert_fb_groups(groups) -> int：INSERT OR IGNORE（url UNIQUE），status 默认 pending；已存在行不动 status；返回新增行数。
4. 协调者裁定：upsert_fb_groups 条目可带可选 "source" 键缺省 'ddg'；save_fb_posts 条目键 {"url","group_id","group_name"}；时间戳用 _now()；短事务 + commit。
5. 测试文件 fetcher/tests/test_db_fb_groups.py：建表幂等 + save_fb_posts 去重/溯源 + upsert_fb_groups 去重/不动状态。
6. spike 复核结论回填 SPEC §8.1（协调者已实测 &s=10 → 200，implementer 只回填结论不重发请求）。
7. 时间戳为北京时间字符串（_now()），不做 +8 偏移。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md

## 待 review 的 diff

**Base：** dbab0da
**Head：** HEAD（当前 b401560）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-review.md

只读一次 diff 文件——它包含 commit 列表、stat 摘要和带上下文的完整 diff，它就是你对本次改动的全部视野。diff 的上下文行就是变更后的文件：除非某个你必须判断的 hunk 在函数中间被截断（并在报告中说明），不要单独 Read 变更文件。不要重跑 git 命令。
不要在代码库里漫游。只在能说出具体风险时才检查 diff 之外的代码——每个风险一次聚焦检查，并在报告中写明风险和你检查了什么。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。它可能不完整、不准确、过于乐观。对照 diff 逐条验证。报告里的设计理由也是声称——就代码论代码，陈述的理由永不降低发现的严重度。

## 测试

implementer 已经跑过测试并在 report 中给出了 TDD 证据。不要为确认其报告而重跑测试套件。只有当读代码产生了任何已有运行都回答不了的具体疑问时才跑测试——且只跑聚焦测试。觉得需要重型验证时，在报告中建议，不要自己跑。

## Part 1：Spec 合规

对照"需求是什么"检查 diff：
- 缺失：被跳过、遗漏、或声称做了但没实现的需求
- 多余：没要求的功能、过度设计
- 误解：功能对了但做法错了

如果某条需求无法仅凭这个 diff 验证，报为 ⚠️ 项。

## Part 2：代码质量

- 关注点分离清晰？错误处理得当？DRY 而没有过早抽象？边界情况处理了？
- 测试验证真实行为而非 mock？边界情况覆盖了吗？
- 每个文件是否一个明确职责？实现是否遵循 plan 的文件结构？
- 本次改动是否显著撑大了既有文件？（只看本次改动贡献的部分）

报告要给出证据：每条发现都要有 file:line。引用行号的紧凑报告给主 Agent 所需的一切。

你的最后一条消息就是报告本身：直接以 spec 合规结论开头。每行都是结论、带 file:line 的发现、或你跑过的检查——不要开场白、不要过程叙述、不要结尾总结。

## 校准

按实际严重度分级。Important 意味着不修就不能信任这个 Step：不正确或脆弱的行为、漏掉的需求、会被拦下的可维护性损伤——整段复制粘贴的逻辑块、被吞掉的错误、不断言任何事的测试。Minor 是"覆盖可以更全"和润色建议。
如果 brief 明确要求了本标准判定为缺陷的东西，那仍然是发现——报为 Important 并标注 plan-mandated。
先肯定做得好的部分再列问题。

## 输出格式

### Spec 合规
- ✅ 合规 | ❌ 发现问题：[缺了什么/多了什么/误解了什么，带 file:line]
- ⚠️ 无法从 diff 验证：[无法仅凭 diff 验证的需求，以及主 Agent 应检查什么]

### 优点
[做得好的地方，具体说明]

### 问题
#### Critical（必须修）
#### Important（应当修）
#### Minor（可改可不改）

每条问题：file:line、问题是什么、为什么要紧、怎么修（如果不显然）。

### 评估
**Step 质量：** [通过 | 需要修复]
**理由：** [1-2 句技术评估]
