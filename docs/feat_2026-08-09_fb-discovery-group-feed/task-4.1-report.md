# Task 4.1 Report — lib/api.ts 类型

## 改了什么

`platform/web/src/lib/api.ts`（仅此一个文件，7 行纯增量，符合协调者裁定「只改 api.ts 类型」）：

1. **TaskType union**：在 `'fb_post'` 之后追加 `'fb_discover' | 'fb_group'` 两个成员。
2. **TaskParams interface**：在 `accounts?: string[]` 之后追加四字段，均带中文注释，
   并新增分组注释 `// fb_discover / fb_group 专用`（对齐既有 `// wa_check 专用` 分组风格）：
   - `keywords?: string` —— 注释注明「换行分隔的搜索原文」（SPEC：换行分隔原文）
   - `pages?: number`
   - `provider?: string`
   - `posts_per_group?: number`

## tsc 输出

```
cd platform/web && npx tsc -b
EXIT: 0
```

全绿，既有代码零回归（纯增量类型，无消费方受影响；后续 Step 4.2-4.4 各自负责消费）。

## 改动的文件

- `platform/web/src/lib/api.ts`（+7）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-brief.md`（未改动，仅纳入 commit）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-report.md`（本报告）

## 自查发现

- 完整性：TaskType 两成员 + TaskParams 四字段均已追加，无遗漏。
- 质量：注释风格对齐既有代码（分组注释 + 行尾中文注释，如 `// 换行分隔的搜索原文`）。
- 纪律：`git diff --stat` 确认仅 api.ts 有改动；commit 只显式 `git add` 三个文件，
  未使用 `git add -A` / `git add .` / `git commit -am`；docs 目录下其他 Step 的
  untracked 文件未纳入本 commit。
- TDD 例外：类型声明无运行时逻辑，无单测可写，验收以 tsc 通过为准（协调者裁定明确）。

## 疑虑

无。
