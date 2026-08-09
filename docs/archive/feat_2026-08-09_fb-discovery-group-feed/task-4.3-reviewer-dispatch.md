你在 review 一个 Step 的实现：先看它是否匹配需求，再看它是否构建良好。这是 Step 级别的关卡，不是合并 review——全分支终审在所有 Step 完成后单独进行。

## 需求是什么

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-brief.md

约束本 Step 的全局约束（从 SPEC/PLAN 逐字抄录，SPEC §7.3/§7.4 为本 Step 规格主体）：
1. 新表单状态：fbDiscoverKeywords / fbDiscoverPages / fbGroupProvider / fbGroupPostsPerGroup。
2. 渲染分支扩为五形态：fb_discover 分支（Textarea min-h-24 font-mono text-xs 预填默认矩阵 §7.4 + 每词页数 1-10 + 循环 + hint「DDG SERP 单 IP 限流（实测约 2 连查即封、约 4 分钟恢复），查询间有节奏冷却，整批约 8-15 分钟跑完」）；fb_group 分支（provider Select h-8 font-medium + 每群帖数默认 50 + 群数上限 + 循环 + hint「Bright Data 免费层 5K 条/月额度；provider key 走环境变量 BRIGHTDATA_API_KEY / APIFY_TOKEN（缺失时该群采集失败）」）；isBatch/isWaCheck/默认分支行为不变。
3. buildParams/validate/fillFromParams/paramsKey 增加两分支（校验：pages 1-10、posts_per_group ≥1、provider 限定、keywords 换行透传）。
4. SPEC §7.4 默认矩阵五行（外贸 whatsapp / 跨境电商 whatsapp / china sourcing whatsapp / 货代 微信 / 亚马逊卖家 微信，均带 site:facebook.com/groups 前缀）。
5. 协调者裁定：新分支在 isWaCheck 之后、默认之前；fb_discover 新建预填默认矩阵、pages 默认 '1'；fb_group 新建 provider 默认 'brightdata'、posts_per_group 默认 '50'、群数上限默认 ''（=不限，复用 batchLimit）；buildParams/validate/fillFromParams/paramsKey 具体语义（见 brief）；DESIGN.md 铁律（SelectTrigger h-8 + font-medium、hint text-xs text-muted-foreground）；既有分支零回归；前端无单测基建（验收 tsc + 运行时冒烟）。

## implementer 声称做了什么

读 implementer 的 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md
（报告声称：tsc 全绿 + API 冒烟 fb_discover/fb_group 创建+预览+编辑+模板回填全通过 + 三分支零回归）

## 待 review 的 diff

**Base：** 5735a78
**Head：** HEAD（当前 8d0f528）
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-review.md

只读一次 diff 文件。diff 的上下文行就是变更后的文件。不要重跑 git 命令。不要在代码库里漫游；只在能说出具体风险时才检查 diff 之外的代码（如 Select/Textarea 组件的导出、DESIGN.md 的 Select 规范）。

你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 不要相信报告

把 implementer 的 report 当作未经验证的声称。对照 diff 逐条验证。这是主要改动面——特别检查：既有 isBatch/isWaCheck/默认分支是否被意外改动、五形态分支顺序、buildParams 是否正确输出 TaskParams 键（keywords 换行保留 / pages / provider / posts_per_group / limit）。

## 测试

implementer 已跑过 tsc + API 冒烟。不要重跑。只有读代码产生具体疑问才跑聚焦检查。

## Part 1：Spec 合规

对照"需求是什么"检查 diff：缺失/多余/误解。无法仅凭 diff 验证的报 ⚠️ 项。

## Part 2：代码质量

关注点分离、DESIGN.md 合规（SelectTrigger h-8 font-medium、hint 样式）、边界情况、是否撑大既有文件（TaskFormDialog 已经较大——只看本次改动贡献）。

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
