# Step 4.4 — Tasks.tsx BATCH_TYPE_NAMES

> 这是你的需求唯一来源。PLAN Step 4.4 原文 + SPEC §7.5 精确规格抄录如下。

## PLAN Step 4.4 原文（验收以 checkbox 为准）

- [ ] BATCH_TYPE_NAMES 追加 'fb_discover' | 'fb_group'（批次进度渲染；归档 SPEC
      §6.2 的坑）
- 预估 5min；验收：tsc 通过 + 任务列表进度列对两新类型生效

## SPEC §7.5 Tasks.tsx（精确规格）

`BATCH_TYPE_NAMES` 追加 `'fb_discover' | 'fb_group'`（启用批次进度渲染；归档
SPEC §6.2 记录的坑：漏加则任务列表进度列不显示批次进度）。

## 协调者裁定

1. **位置**：`platform/web/src/pages/Tasks.tsx` 的 `BATCH_TYPE_NAMES` 集合（92-94 行）
   追加两成员（'fb_post' 之后）。
2. **只改 Tasks.tsx 这一行集合**，不改其他文件。
3. **验收**：cd platform/web && npx tsc -b 全绿。运行时进度列渲染由 Step 4.5 冒烟
   验证（本 Step 不做运行时冒烟）。
4. **TDD 例外**：集合成员声明无运行时逻辑，无单测可写；验收以 tsc 通过为准。

## Commit 约束

- 只 `git add`：`platform/web/src/pages/Tasks.tsx`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 4.4 ...`。
