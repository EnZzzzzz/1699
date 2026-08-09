# Step 4.1 review package
a8edfe3 feat(fb): Step 4.1 前端 api.ts 追加 fb_discover/fb_group 类型
 .../task-4.1-brief.md                              | 39 ++++++++++++++++++++
 .../task-4.1-report.md                             | 41 ++++++++++++++++++++++
 platform/web/src/lib/api.ts                        |  7 ++++
 3 files changed, 87 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-brief.md
new file mode 100644
index 0000000..2050955
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-brief.md
@@ -0,0 +1,39 @@
+# Step 4.1 — lib/api.ts 类型
+
+> 这是你的需求唯一来源。PLAN Step 4.1 原文 + SPEC §7.1 精确规格抄录如下。
+
+## PLAN Step 4.1 原文（验收以 checkbox 为准）
+
+- [ ] TaskType 追加 'fb_discover' | 'fb_group'；TaskParams 追加 keywords/pages/
+      provider/posts_per_group
+- 预估 10min；验收：tsc 通过
+
+## SPEC §7.1 lib/api.ts（精确规格）
+
+- `TaskType` 追加 `'fb_discover' | 'fb_group'`。
+- `TaskParams` 追加 `keywords?: string`（换行分隔原文）、`pages?: number`、
+  `provider?: string`、`posts_per_group?: number`。
+
+## 协调者裁定
+
+1. **插入位置**：`platform/web/src/lib/api.ts` 的 TaskType union 追加两成员（在
+   `'fb_post'` 之后）；TaskParams interface 在 `accounts?: string[]` 之后追加四字段
+   （带中文注释）。
+2. **只改 api.ts 类型**，不改其他文件（后续 Step 4.2-4.4 各自负责）。
+3. **验收**：`cd platform/web && npx tsc -b` 全绿（既有代码零回归——类型是纯增量，
+   应直接通过；若 tsc 报既有错误，先确认不是你引入的，report 里注明）。
+4. **TDD 说明**：类型声明无运行时逻辑，无单测可写。TDD 例外（配置/声明类）——验收
+   以 tsc 通过为准（plan 验收标准即此）。不写 mock 测试。
+
+## 代码库上下文
+
+- `platform/web/src/lib/api.ts`：TaskType union 在 78-86 行（'fb_post' 在 86 行），
+  TaskParams interface 在 93 行起（accounts 在 ~120 行）。
+- 类型检查：`cd platform/web && npx tsc -b`。
+
+## Commit 约束
+
+- 只 `git add`：`platform/web/src/lib/api.ts`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 4.1 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-report.md
new file mode 100644
index 0000000..1788b5d
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-report.md
@@ -0,0 +1,41 @@
+# Task 4.1 Report — lib/api.ts 类型
+
+## 改了什么
+
+`platform/web/src/lib/api.ts`（仅此一个文件，7 行纯增量，符合协调者裁定「只改 api.ts 类型」）：
+
+1. **TaskType union**：在 `'fb_post'` 之后追加 `'fb_discover' | 'fb_group'` 两个成员。
+2. **TaskParams interface**：在 `accounts?: string[]` 之后追加四字段，均带中文注释，
+   并新增分组注释 `// fb_discover / fb_group 专用`（对齐既有 `// wa_check 专用` 分组风格）：
+   - `keywords?: string` —— 注释注明「换行分隔的搜索原文」（SPEC：换行分隔原文）
+   - `pages?: number`
+   - `provider?: string`
+   - `posts_per_group?: number`
+
+## tsc 输出
+
+```
+cd platform/web && npx tsc -b
+EXIT: 0
+```
+
+全绿，既有代码零回归（纯增量类型，无消费方受影响；后续 Step 4.2-4.4 各自负责消费）。
+
+## 改动的文件
+
+- `platform/web/src/lib/api.ts`（+7）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-brief.md`（未改动，仅纳入 commit）
+- `docs/feat_2026-08-09_fb-discovery-group-feed/task-4.1-report.md`（本报告）
+
+## 自查发现
+
+- 完整性：TaskType 两成员 + TaskParams 四字段均已追加，无遗漏。
+- 质量：注释风格对齐既有代码（分组注释 + 行尾中文注释，如 `// 换行分隔的搜索原文`）。
+- 纪律：`git diff --stat` 确认仅 api.ts 有改动；commit 只显式 `git add` 三个文件，
+  未使用 `git add -A` / `git add .` / `git commit -am`；docs 目录下其他 Step 的
+  untracked 文件未纳入本 commit。
+- TDD 例外：类型声明无运行时逻辑，无单测可写，验收以 tsc 通过为准（协调者裁定明确）。
+
+## 疑虑
+
+无。
diff --git a/platform/web/src/lib/api.ts b/platform/web/src/lib/api.ts
index b04f87f..6f3aaf3 100644
--- a/platform/web/src/lib/api.ts
+++ b/platform/web/src/lib/api.ts
@@ -77,20 +77,22 @@ export interface Task {
 
 export type TaskType =
   | '1688_shop'
   | '1688_company'
   | '1688_contact'
   | 'madeinchina_contact'
   | 'madeinchina_shop'
   | 'yiwugo_search'
   | 'wa_check'
   | 'fb_post'
+  | 'fb_discover'
+  | 'fb_group'
 
 // 采集类参数全量可选键：留空即不传，由 CLI 默认值生效。
 // 批次类型（1688/madeinchina 采集 + wa_check）只读 limit / repeat_interval /
 // accounts，其余 daemon 级参数（workers/proxy/节奏等）已收敛到 daemon 启动，
 // 逐任务覆盖取消（SPEC §3.2 用户可见变化）；旧模板多余字段后端忽略。
 // wa_check 只使用 limit / accounts；旧模板多余字段后端忽略（加载时忽略未知键）。
 export interface TaskParams {
   batch_num?: number
   limit?: number
   max_batches?: number
@@ -110,20 +112,25 @@ export interface TaskParams {
   block_rest_min?: number
   block_rest_max?: number
   use_proxy?: boolean
   headless?: boolean
   auto_solve?: boolean
   retry_failed?: boolean // 仅 1688_contact；已不映射 CLI（build_command 分支已删），表单开关遗留
   // 任务结束后自动重启的间隔（秒）；0 或不传 = 不循环
   repeat_interval?: number
   // wa_check 专用
   accounts?: string[]
+  // fb_discover / fb_group 专用
+  keywords?: string // 换行分隔的搜索原文
+  pages?: number
+  provider?: string
+  posts_per_group?: number
 }
 
 export interface CreateTaskRequest {
   type: TaskType
   params: TaskParams
 }
 
 export interface TaskPreview {
   cmd: string[] | null // 批次类型（含 wa_check）返回 null
   cmdline: string // cmd 拼接的命令行，或批次类型的说明文案
