# Step 4.1 — lib/api.ts 类型

> 这是你的需求唯一来源。PLAN Step 4.1 原文 + SPEC §7.1 精确规格抄录如下。

## PLAN Step 4.1 原文（验收以 checkbox 为准）

- [ ] TaskType 追加 'fb_discover' | 'fb_group'；TaskParams 追加 keywords/pages/
      provider/posts_per_group
- 预估 10min；验收：tsc 通过

## SPEC §7.1 lib/api.ts（精确规格）

- `TaskType` 追加 `'fb_discover' | 'fb_group'`。
- `TaskParams` 追加 `keywords?: string`（换行分隔原文）、`pages?: number`、
  `provider?: string`、`posts_per_group?: number`。

## 协调者裁定

1. **插入位置**：`platform/web/src/lib/api.ts` 的 TaskType union 追加两成员（在
   `'fb_post'` 之后）；TaskParams interface 在 `accounts?: string[]` 之后追加四字段
   （带中文注释）。
2. **只改 api.ts 类型**，不改其他文件（后续 Step 4.2-4.4 各自负责）。
3. **验收**：`cd platform/web && npx tsc -b` 全绿（既有代码零回归——类型是纯增量，
   应直接通过；若 tsc 报既有错误，先确认不是你引入的，report 里注明）。
4. **TDD 说明**：类型声明无运行时逻辑，无单测可写。TDD 例外（配置/声明类）——验收
   以 tsc 通过为准（plan 验收标准即此）。不写 mock 测试。

## 代码库上下文

- `platform/web/src/lib/api.ts`：TaskType union 在 78-86 行（'fb_post' 在 86 行），
  TaskParams interface 在 93 行起（accounts 在 ~120 行）。
- 类型检查：`cd platform/web && npx tsc -b`。

## Commit 约束

- 只 `git add`：`platform/web/src/lib/api.ts`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 4.1 ...`。
