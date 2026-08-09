# Step 4.3 — TaskFormDialog.tsx 两独立表单分支（主要改动面）

> 这是你的需求唯一来源。PLAN Step 4.3 原文 + SPEC §7.3/§7.4 精确规格抄录如下。

## PLAN Step 4.3 原文（验收以 checkbox 为准）

- [ ] 新表单状态：fbDiscoverKeywords / fbDiscoverPages / fbGroupProvider /
      fbGroupPostsPerGroup
- [ ] 渲染分支扩为五形态：fb_discover 分支（Textarea 预填默认矩阵 §7.4 + 每词页数
      1-10 + 循环 + hint）；fb_group 分支（provider Select h-8 font-medium + 每群
      帖数默认 50 + 群数上限 + 循环 + hint）；isBatch/isWaCheck/默认 分支行为不变
- [ ] buildParams/validate/fillFromParams/paramsKey 增加两分支（校验：pages 1-10、
      posts_per_group ≥1、provider 限定、keywords 换行透传）
- [ ] 测试/验证：编辑模式回填、模板加载回填、预览不崩（现有测试基建若覆盖表单则
      补断言；否则走 tsc + 手工冒烟）
- 预估 60min；验收：tsc 全绿 + 新建两类型任务表单可提交（API 冒烟）

## SPEC §7.3 TaskFormDialog.tsx（精确规格）

`fb_discover`、`fb_group` **不进 isBatch 共用简表单**，各开独立分支（现有
isBatch / isWaCheck / 默认 三选一扩为五形态）：

- **fb_discover 分支**：
  - 关键词 Textarea（`min-h-24 font-mono text-xs`，每行一个查询词，**预填默认
    矩阵**，见 §7.4）。
  - 每词页数 number input（label「每词页数」，默认 1，min 1，max 10）。
  - 循环间隔（秒）number input（0 = 不循环）。
  - hint（text-xs text-muted-foreground）：`DDG SERP 单 IP 限流（实测约 2 连查即
    封、约 4 分钟恢复），查询间有节奏冷却，整批约 8-15 分钟跑完`。
- **fb_group 分支**：
  - provider Select（brightdata →「Bright Data（默认）」/ apify →「Apify」）；
    `SelectTrigger` 必须 `h-8` + 显式 `font-medium`（DESIGN.md §5 Select 与按钮
    并排规范）。
  - 每群帖数 number input（label「每群帖数上限」，默认 50，min 1）。
  - 群数上限 number input（label「群数上限」，默认空 = 不限，min 0）。
  - 循环间隔（秒）number input。
  - hint：`Bright Data 免费层 5K 条/月额度；provider key 走环境变量
    BRIGHTDATA_API_KEY / APIFY_TOKEN（缺失时该群采集失败）`。
- `buildParams` / `validate` 增加两分支：keywords 透传原文（换行保留）、
  pages 校验 1-10、posts_per_group 校验 ≥1、provider 限定 {brightdata, apify}。
- `fillFromParams` 增加 keywords/pages/provider/posts_per_group 回填（编辑/模板
  加载）。
- `paramsKey` memo 增加新表单状态键（触发预览防抖）。

## SPEC §7.4 默认关键词矩阵（表单预填，取自 facebook-groups.md §2 实测高命中）

```
site:facebook.com/groups 外贸 whatsapp
site:facebook.com/groups 跨境电商 whatsapp
site:facebook.com/groups china sourcing whatsapp
site:facebook.com/groups 货代 微信
site:facebook.com/groups 亚马逊卖家 微信
```

## 协调者裁定（覆盖 SPEC 未定细节）

1. **新表单状态**：`fbDiscoverKeywords`（string）、`fbDiscoverPages`（string，number
   input 值）、`fbGroupProvider`（'brightdata' | 'apify'）、`fbGroupPostsPerGroup`
   （string）、群数上限复用既有 `batchLimit`（limit 键，与 isBatch 共用 state——
   注意 isBatch 的 batchLimit 语义相同）；循环间隔复用既有 `values.repeat_interval`。
2. **fb_discover 新建时 keywords 预填默认矩阵**（§7.4 五行）；编辑/模板加载时用
   params.keywords 回填。**pages 默认 '1'**。
3. **fb_group 新建时** provider 默认 'brightdata'、posts_per_group 默认 '50'、
   群数上限（batchLimit）默认 ''（=不限）。
4. **buildParams**：
   - fb_discover：`{keywords: fbDiscoverKeywords（trim 后非空才传）, pages:
     Number(fbDiscoverPages)（有效才传）, repeat_interval（>0 才传）}`；
   - fb_group：`{provider: fbGroupProvider, posts_per_group: Number(...)（≥1 才传）,
     limit: Number(batchLimit)（非空且 ≥0 才传）, repeat_interval}`。
5. **validate**：
   - fb_discover：pages 若填写必须整数 1-10（否则 toast）；keywords 可空（空 = 后端
     用默认？**不**——keywords 空时任务没意义，toast 提示「至少填一个查询词」？
     参照 §7.3 无此要求，协调者裁定：keywords 允许空（后端 enqueue 空→0 幂等），
     但提示文案建议非空。**最终：keywords 空 → toast 警告但不阻塞**（后端幂等）。
   - fb_group：posts_per_group ≥1 整数；provider ∈ {brightdata, apify}（Select 已限定，
     防御校验）；群数上限 ≥0 整数。
6. **fillFromParams**：编辑/模板加载时按 params 键回填四新状态（keywords/pages/
   provider/posts_per_group + limit 已有 batchLimit 逻辑）。
7. **paramsKey**：JSON.stringify 对象加 fbDiscoverKeywords/fbDiscoverPages/
   fbGroupProvider/fbGroupPostsPerGroup 键。
8. **渲染**：`{isBatch ? (...) : isWaCheck ? (...) : isFbDiscover ? (...) :
   isFbGroup ? (...) : (...)}`——注意顺序：isBatch 集合**不含** fb_discover/fb_group
   （Step 4.2 裁定未加入），所以新分支加在 isWaCheck 之后、默认分支之前。
9. **Textarea 组件**：`@/components/ui/textarea`（若不存在用 Input + className
   `min-h-24 font-mono text-xs`——查一下 ui 目录有没有 textarea；没有就用
   `<textarea>` 原生的 Tailwind 样式）。
10. **DESIGN.md 铁律**（AGENTS.md §3）：SelectTrigger 必须 `h-8` + 显式
    `font-medium`；按钮 `variant="outline" size="sm"`；hint `text-xs
    text-muted-foreground`；Label `text-sm`；页面骨架/圆角/阴影照 DESIGN.md。
11. **既有分支零回归**：isBatch/isWaCheck/默认分支行为不变（编辑模式、模板加载、
    预览不崩）。
12. **测试**：前端无单测基建覆盖表单（协调者已查：platform/web 无 jest/vitest 配置）
    → 验收 = tsc 全绿 + 提交表单的 API 冒烟（可起后端用 curl 或手动；Step 4.5
    冒烟会覆盖页面操作）。本 Step 做 tsc + 若环境允许起 vite 快速验证表单渲染不崩
    （可选）。report 里写明验证方式。

## 代码库上下文

- `platform/web/src/pages/tasks/TaskFormDialog.tsx`（已读）：
  - 既有 state：values（数字字段）/batchLimit/waLimit/selectedAccounts/...
  - isBatch 集合 119-123 行（不含 fb_discover/fb_group）
  - fillFromParams 129 行起、buildParams 198 行起、validate 264 行起、
    paramsKey 241 行起、渲染 483 行起（isBatch ? ... : isWaCheck ? ... : 默认）
- 组件：`@/components/ui/select`（Select/SelectTrigger/SelectContent/SelectItem/
  SelectValue）、`@/components/ui/input`、`@/components/ui/textarea`（查一下）、
  `@/components/ui/label`。
- 类型检查：`cd platform/web && npx tsc -b`。
- 默认矩阵文本在 SPEC §7.4（本 brief 上方已抄录）。

## TDD 说明

前端无单测基建（无 jest/vitest）——协调者已核实。TDD 例外（无测试基建的环境），
但必须有等价验证：tsc + 运行时冒烟（表单渲染/回填/提交）。report 必须记录验证
证据（命令输出/截图/API 响应）。

## Commit 约束

- 只 `git add`：`platform/web/src/pages/tasks/TaskFormDialog.tsx`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 4.3 ...`。
