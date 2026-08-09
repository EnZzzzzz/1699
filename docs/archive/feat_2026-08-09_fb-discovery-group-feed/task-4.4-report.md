# Step 4.4 报告 — Tasks.tsx BATCH_TYPE_NAMES

## 改了什么

`platform/web/src/pages/Tasks.tsx` 的 `BATCH_TYPE_NAMES` 集合（原 92-94 行）追加
`'fb_discover'`、`'fb_group'` 两个成员（置于 `'fb_post'` 之后）：

```ts
const BATCH_TYPE_NAMES = new Set(['1688_shop', '1688_company', '1688_contact',
                                  'madeinchina_shop', 'madeinchina_contact',
                                  'wa_check', 'fb_post', 'fb_discover', 'fb_group'])
```

仅此一行集合，未改动其他文件、其他代码。

## 验收

`cd platform/web && npx tsc -b`：EXIT 0，全绿无报错。

运行时批次进度列渲染由 Step 4.5 冒烟验证（本 Step 按 brief 不做运行时冒烟）。

## 改动的文件

- `platform/web/src/pages/Tasks.tsx`（BATCH_TYPE_NAMES 一行）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-brief.md`（已存在，随 commit 纳入）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-report.md`（本报告）

## 自查

- 只改了 Tasks.tsx 的 BATCH_TYPE_NAMES 集合，符合协调者裁定「只改这一行集合」。
- `bp = BATCH_TYPE_NAMES.has(task.type) ? batchProgress(task) : null` 消费点无需改动，
  新增成员即自动生效（归档 SPEC §6.2 的坑已规避）。
- `task.type` 为字符串，Set 成员为字面量字符串，tsc 类型检查通过。
- commit 严格按约束：仅 `git add` Tasks.tsx 与 docs 下本 Step 的 brief/report，
  未用 `-A`/`.`/`-am`。

## 疑虑

- 无。任务列表进度列对两新类型的实际渲染需 Step 4.5 冒烟确认（brief 已声明）。
