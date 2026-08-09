你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §5.1 为本 Step 的规格主体）：
1. 新文件 `fetcher/fetcher/atoms/facebook_discover.py`：`_http_get(url, timeout) -> (status, html)`（urllib + Chrome 125 同款 UA + Accept-Language: zh-CN + Accept-Encoding: gzip + gzip 解压，模块级便于 mock，对齐 facebook_group.py 的 _http_json 模式）。
2. `parse_serp_results(html) -> list[{"url","title"}]`：正则抽 `<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=<enc>&amp;rut=...">` → uddg 参数 URL 解码 → 标题去标签/HTML 实体（&amp; 等）；返回全部有机结果不过滤。
3. `classify_fb_url(url) -> ("post"|"group", group_id, group_url) | None`：
   - POST_RE `facebook\.com/groups/[^/]+/(?:posts|permalink)/(\d+)` → kind="post"，group_url=派生的 `https://www.facebook.com/groups/{gid}`；
   - GROUP_RE `facebook\.com/groups/([^/]+)` → kind="group"，group_url=URL 自身归一化 `https://www.facebook.com/groups/{gid}` 去尾部斜杠；
   - 其余（FB 视频/用户主页/广告页/非 FB）→ None。
4. FetchDdgSerp 原子：name="fetch_ddg_serp"、title="DDG抓FB群帖SERP"；params={query 必填 str, page 可选 1 起 offset=(page-1)*10, sample_min/sample_max 可选, timeout 可选缺省 30}；请求 URL `https://html.duckduckgo.com/html/?q=<quote(query)>&s=<offset>`。
5. 节奏：请求后 `ctx.wait(random.uniform(sample_min', sample_max))`，sample_min'=max(sample_min, 60)（MIN_SAMPLE_FLOOR 常量注明 spike 依据）；202 时先 `ctx.wait(uniform(180,240))` 再返回 BLOCKED。
6. Outcome 口径：200+results→OK（data={"engine":"ddg","query","page","results":[{"url","title","kind","group_id","group_url"}...]}）；200+0 结果→EMPTY；202/403/429→BLOCKED；传输错误/5xx/超时→NET_ERROR；被停止→SKIPPED。
7. 协调者裁定：params 校验失败→FATAL；停止判定在 HTTP 前（SKIPPED 且 wait 0 次）；传输错误原样上抛由 run catch；_http_json/原子的 catch 结构对齐 facebook_group.py。
8. 测试文件 `fetcher/tests/test_facebook_discover.py`：parse 样本结构/标题实体、classify 各形态（帖/群主页/slug 群/视频/非 FB）、mock HTTP 全 outcome 路径、202→BLOCKED、停止→SKIPPED、节奏 wait 次数、params 校验 FATAL、gzip 解压。验收含回归 test_facebook*.py 不动。
9. 时间戳/DB 与本 Step 无关；本 Step 无 DB 写入。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md
（报告含 3 个 concerns，需你在 review 中裁决：① OK results 保留 kind=None 的非 FB 条目不过滤；② sample_max 低于 60 地板时抬到地板防 uniform ValueError；③ sample_max 缺省取 sample_min'+20）

## 待 review 的 diff

**Base：** 4600ca1
**Head：** HEAD（当前 274a409）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-review.md

只读一次 diff 文件——它包含 commit 列表、stat 摘要和带上下文的完整 diff，它就是你对本次改动的全部视野。diff 的上下文行就是变更后的文件：除非某个你必须判断的 hunk 在函数中间被截断（并在报告中说明），不要单独 Read 变更文件。不要重跑 git 命令。
不要在代码库里漫游。只在能说出具体风险时才检查 diff 之外的代码（如 FacebookGroupPosts 原子或 ActionRequest 的构造方式）——每个风险一次聚焦检查，并在报告中写明。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。报告里的设计理由也是声称——就代码论代码。

## 测试

implementer 已跑过测试（35 新增 + 72 fb 回归 + 697 全量）。不要为确认其报告而重跑测试套件。只有当读代码产生了任何已有运行都回答不了的具体疑问时才跑聚焦测试。

## Part 1：Spec 合规

对照"需求是什么"检查 diff：缺失/多余/误解。无法仅凭 diff 验证的报 ⚠️ 项。

## Part 2：代码质量

关注点分离、错误处理、DRY、边界情况；测试验证真实行为；文件职责清晰；本次改动是否撑大既有文件。

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
