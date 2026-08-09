# Step 4.4 review package
e4a6866 feat(fb): Step 4.4 BATCH_TYPE_NAMES 追加 fb_discover/fb_group（批次进度渲染）
 .../task-4.4-brief.md                              | 30 +++++++++++++++++
 .../task-4.4-report.md                             | 39 ++++++++++++++++++++++
 platform/web/src/pages/Tasks.tsx                   |  2 +-
 3 files changed, 70 insertions(+), 1 deletion(-)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-brief.md
new file mode 100644
index 0000000..03f4415
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-brief.md
@@ -0,0 +1,30 @@
+# Step 4.4 — Tasks.tsx BATCH_TYPE_NAMES
+
+> 这是你的需求唯一来源。PLAN Step 4.4 原文 + SPEC §7.5 精确规格抄录如下。
+
+## PLAN Step 4.4 原文（验收以 checkbox 为准）
+
+- [ ] BATCH_TYPE_NAMES 追加 'fb_discover' | 'fb_group'（批次进度渲染；归档 SPEC
+      §6.2 的坑）
+- 预估 5min；验收：tsc 通过 + 任务列表进度列对两新类型生效
+
+## SPEC §7.5 Tasks.tsx（精确规格）
+
+`BATCH_TYPE_NAMES` 追加 `'fb_discover' | 'fb_group'`（启用批次进度渲染；归档
+SPEC §6.2 记录的坑：漏加则任务列表进度列不显示批次进度）。
+
+## 协调者裁定
+
+1. **位置**：`platform/web/src/pages/Tasks.tsx` 的 `BATCH_TYPE_NAMES` 集合（92-94 行）
+   追加两成员（'fb_post' 之后）。
+2. **只改 Tasks.tsx 这一行集合**，不改其他文件。
+3. **验收**：cd platform/web && npx tsc -b 全绿。运行时进度列渲染由 Step 4.5 冒烟
+   验证（本 Step 不做运行时冒烟）。
+4. **TDD 例外**：集合成员声明无运行时逻辑，无单测可写；验收以 tsc 通过为准。
+
+## Commit 约束
+
+- 只 `git add`：`platform/web/src/pages/Tasks.tsx`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 4.4 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-report.md
new file mode 100644
index 0000000..5bed6a0
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-report.md
@@ -0,0 +1,39 @@
+# Step 4.4 报告 — Tasks.tsx BATCH_TYPE_NAMES
+
+## 改了什么
+
+`platform/web/src/pages/Tasks.tsx` 的 `BATCH_TYPE_NAMES` 集合（原 92-94 行）追加
+`'fb_discover'`、`'fb_group'` 两个成员（置于 `'fb_post'` 之后）：
+
+```ts
+const BATCH_TYPE_NAMES = new Set(['1688_shop', '1688_company', '1688_contact',
+                                  'madeinchina_shop', 'madeinchina_contact',
+                                  'wa_check', 'fb_post', 'fb_discover', 'fb_group'])
+```
+
+仅此一行集合，未改动其他文件、其他代码。
+
+## 验收
+
+`cd platform/web && npx tsc -b`：EXIT 0，全绿无报错。
+
+运行时批次进度列渲染由 Step 4.5 冒烟验证（本 Step 按 brief 不做运行时冒烟）。
+
+## 改动的文件
+
+- `platform/web/src/pages/Tasks.tsx`（BATCH_TYPE_NAMES 一行）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-brief.md`（已存在，随 commit 纳入）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-4.4-report.md`（本报告）
+
+## 自查
+
+- 只改了 Tasks.tsx 的 BATCH_TYPE_NAMES 集合，符合协调者裁定「只改这一行集合」。
+- `bp = BATCH_TYPE_NAMES.has(task.type) ? batchProgress(task) : null` 消费点无需改动，
+  新增成员即自动生效（归档 SPEC §6.2 的坑已规避）。
+- `task.type` 为字符串，Set 成员为字面量字符串，tsc 类型检查通过。
+- commit 严格按约束：仅 `git add` Tasks.tsx 与 docs 下本 Step 的 brief/report，
+  未用 `-A`/`.`/`-am`。
+
+## 疑虑
+
+- 无。任务列表进度列对两新类型的实际渲染需 Step 4.5 冒烟确认（brief 已声明）。
diff --git a/platform/web/src/pages/Tasks.tsx b/platform/web/src/pages/Tasks.tsx
index 0e5abaf..b7ae2df 100644
--- a/platform/web/src/pages/Tasks.tsx
+++ b/platform/web/src/pages/Tasks.tsx
@@ -84,21 +84,21 @@ function batchProgress(task: Task): { done: number; total: number; failed: numbe
   const done = p.done
   if (typeof total !== 'number' || typeof done !== 'number') return null
   const failed = typeof p.failed === 'number' ? (p.failed as number) : 0
   if (total <= 0) return null
   return { done, total, failed }
 }
 
 // P4 批次采集类型（progress 为 work_items 聚合，非 last_line）
 const BATCH_TYPE_NAMES = new Set(['1688_shop', '1688_company', '1688_contact',
                                   'madeinchina_shop', 'madeinchina_contact',
-                                  'wa_check', 'fb_post'])
+                                  'wa_check', 'fb_post', 'fb_discover', 'fb_group'])
 
 function TaskRow({
   task,
   selected,
   onSelect,
   onChanged,
   onShowLogs,
 }: {
   task: Task
   selected: boolean
