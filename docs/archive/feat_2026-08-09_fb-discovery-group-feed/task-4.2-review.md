# Step 4.2 review package
9c20140 feat(fb): Step 4.2 task-ui.tsx 追加 fb_discover/fb_group 类型标签与参数摘要
 .../task-4.2-brief.md                              | 62 ++++++++++++++++++++
 .../task-4.2-report.md                             | 67 ++++++++++++++++++++++
 platform/web/src/pages/tasks/task-ui.tsx           | 30 ++++++++++
 3 files changed, 159 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-brief.md
new file mode 100644
index 0000000..4be652d
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-brief.md
@@ -0,0 +1,62 @@
+# Step 4.2 — task-ui.tsx
+
+> 这是你的需求唯一来源。PLAN Step 4.2 原文 + SPEC §7.2 精确规格抄录如下。
+
+## PLAN Step 4.2 原文（验收以 checkbox 为准）
+
+- [ ] TASK_TYPE_OPTIONS 追加两项（label「Facebook 帖子发现」/「Facebook 群帖采集」）
+- [ ] paramsSummary 追加两分支（N 词 × M 页；provider=… 每群≤N帖 群数上限=M）
+- 预估 15min；验收：tsc 通过 + 类型标签渲染
+
+## SPEC §7.2 task-ui.tsx（精确规格）
+
+- `TASK_TYPE_OPTIONS` 追加两项：
+  - `fb_discover` → label **「Facebook 帖子发现」**
+  - `fb_group` → label **「Facebook 群帖采集」**
+- `paramsSummary` 追加两分支：
+  - `fb_discover` → `N 词 × M 页` + 循环（N=keywords 按换行拆词计数，M=pages 缺省 1）。
+  - `fb_group` → `provider=Bright Data|Apify` + `每群≤N帖`（posts_per_group）+
+    `群数上限=M`（limit，0=不限）+ 循环。
+
+## 协调者裁定（覆盖 SPEC 未定细节）
+
+1. **paramsSummary 分支位置（重要）**：fb_discover/fb_group 的新分支必须**置于既有
+   `BATCH_TYPES` 集合检查之前**（task-ui.tsx 约 147-151 行有一个 `const BATCH_TYPES =
+   new Set(['1688_shop', ..., 'fb_post'])` 集合用于「只读 limit+repeat」通用摘要）——
+   否则 fb_discover/fb_group 会落入通用 limit 摘要，而不是自定义摘要。实现方式：
+   在函数开头（wa_check 分支之后）加 `if (task.type === 'fb_discover') {...}` 与
+   `if (task.type === 'fb_group') {...}` 两个独立分支，再走既有 BATCH_TYPES 检查。
+   **不要**把 fb_discover/fb_group 加进那个 BATCH_TYPES 集合。
+2. **fb_discover 摘要格式**：
+   - N = `(task.params.keywords ?? '')` 按 `\n` split 后 strip 过滤空行的数量；
+     keywords 缺省/空 → 视为 1 词（`N 词` 显示实际数量，空时显示 1）。
+   - M = pages（number 才有效，否则 1）；`M 页`（M=1 时显示「1 页」）。
+   - 组合：`2 词 × 1 页`；有循环时追 ` 循环30分钟`（用既有 humanizeSeconds）。
+   - 空 keywords（无值）：显示 `默认矩阵 × 1 页`（前端新建时预填默认矩阵，但
+     params 可能为空——此时摘要显示「默认矩阵」合理）。
+3. **fb_group 摘要格式**：
+   - provider：`brightdata` → `Bright Data`；`apify` → `Apify`；缺省/其他 →
+     `Bright Data`（后端缺省 brightdata）。
+   - `每群≤50帖`（posts_per_group 缺省 50）；`群数上限=10`（limit>0 时）或
+     `群数不限`（limit 缺省/0）。
+   - 组合：`provider=Bright Data 每群≤50帖 群数不限`；有循环追 ` 循环N`。
+4. **复用既有 humanizeSeconds**（task-ui.tsx 内已有，勿重复定义）。
+5. **测试/验证**：paramsSummary 是纯函数，但前端无单测基建（现有测试基建若覆盖
+   则补断言；否则走 tsc + Step 4.5 手工冒烟）。验收以 tsc 全绿 + Step 4.5 冒烟
+   渲染为准。**本 Step 只做 tsc + 自查**（可以用 node 直接跑一下纯函数做快速
+   验证，可选——不强求）。
+6. **只改 task-ui.tsx**（TASK_TYPE_OPTIONS + paramsSummary），不改其他文件。
+
+## 代码库上下文
+
+- `platform/web/src/pages/tasks/task-ui.tsx`：TASK_TYPE_OPTIONS 在 72-81 行（fb_post
+  在 80 行）；paramsSummary 在 130 行起（wa_check 分支 137 行起、BATCH_TYPES 集合
+  147-151 行、通用分支其后）；humanizeSeconds 在 ~120 行。
+- 类型检查：`cd platform/web && npx tsc -b`。
+
+## Commit 约束
+
+- 只 `git add`：`platform/web/src/pages/tasks/task-ui.tsx`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 4.2 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-report.md
new file mode 100644
index 0000000..0db4f3e
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.2-report.md
@@ -0,0 +1,67 @@
+# Task 4.2 报告 — task-ui.tsx 前端接线
+
+## 结论
+
+**DONE** — 两处改动完成，tsc 全绿，纯函数冒烟测试全过。
+
+## 改了什么
+
+仅改 `platform/web/src/pages/tasks/task-ui.tsx`：
+
+### 1. TASK_TYPE_OPTIONS 追加两项（fb_post 之后）
+
+```ts
+{ value: 'fb_post', label: 'Facebook 帖子采集' },
+{ value: 'fb_discover', label: 'Facebook 帖子发现' },
+{ value: 'fb_group', label: 'Facebook 群帖采集' },
+```
+
+### 2. paramsSummary 追加两分支（wa_check 分支之后、BATCH_TYPES 检查之前，裁定 1）
+
+- **fb_discover**：`N 词 × M 页`。
+  - N = `p.keywords` 按 `\n` split → trim → 过滤空行后的数量；空 keywords 显示
+    `默认矩阵 × M 页`（裁定 2）。
+  - M = `p.pages`（number 且有限才生效，否则 1）。
+  - 有循环追 `循环X`（复用既有 `repeatPart` / `humanizeSeconds`，裁定 4）。
+- **fb_group**：`provider=Bright Data|Apify 每群≤N帖 群数上限=M|群数不限`。
+  - provider：`apify` → `Apify`，其余（含缺省）→ `Bright Data`（后端缺省 brightdata）。
+  - `每群≤N帖`：posts_per_group 缺省 50。
+  - `群数上限=M`（limit>0）或 `群数不限`（limit 缺省/0）。
+  - 有循环追 `循环X`。
+
+两个分支均**未**加入 BATCH_TYPES 集合，通用 limit 摘要分支不受影响（fb_post 等
+原有类型行为不变）。
+
+## tsc 输出
+
+```
+cd platform/web && npx tsc -b
+EXIT=0（无输出，全绿）
+```
+
+## 自查验证（可选，用 esbuild bundle + React stub 跑纯函数）
+
+```
+fb_discover 空           => 默认矩阵 × 1 页
+fb_discover 2词1页+循环  => 2 词 × 1 页 循环30分钟
+fb_discover 2词3页       => 2 词 × 3 页
+fb_discover 1词单行      => 1 词 × 1 页
+fb_group 默认            => provider=Bright Data 每群≤50帖 群数不限
+fb_group apify+自定义    => provider=Apify 每群≤20帖 群数上限=10
+fb_group brightdata+循环 => provider=Bright Data 每群≤50帖 群数不限 循环1分钟
+fb_post 对照(通用BATCH分支) => 上限=200   # 确认 fb_discover/fb_group 未落入通用分支
+TASK_TYPE_OPTIONS 尾部   => fb_post / fb_discover / fb_group 三项齐全
+```
+
+## 改动的文件
+
+- `platform/web/src/pages/tasks/task-ui.tsx`（唯一代码改动，符合裁定 6「只改
+  task-ui.tsx」）
+- 本 brief / report（docs/ 下 Step 4.2 文档）
+
+## 自查发现 / 疑虑
+
+- 无功能性疑虑。仅两点说明：
+  1. 本 Step 为纯字符串/标签逻辑改动，不涉及 DESIGN.md 约束的颜色 token、布局、
+     组件样式，故无需走 tokens.css 流程。
+  2. 前端无单测基建，冒烟渲染留给 Step 4.5（brief 裁定 5 一致）。
diff --git a/platform/web/src/pages/tasks/task-ui.tsx b/platform/web/src/pages/tasks/task-ui.tsx
index 32e3f00..b9c84cd 100644
--- a/platform/web/src/pages/tasks/task-ui.tsx
+++ b/platform/web/src/pages/tasks/task-ui.tsx
@@ -71,20 +71,22 @@ export function levelBadge(level: TaskEventLevel) {
 
 export const TASK_TYPE_OPTIONS: { value: TaskType; label: string }[] = [
   { value: '1688_shop', label: '1688 店铺采集' },
   { value: '1688_company', label: '1688 公司采集' },
   { value: '1688_contact', label: '1688 联系方式采集' },
   { value: 'madeinchina_shop', label: '中国制造网 展厅采集' },
   { value: 'madeinchina_contact', label: '中国制造网 联系方式采集' },
   { value: 'yiwugo_search', label: '义乌购搜索' },
   { value: 'wa_check', label: 'WhatsApp 查号' },
   { value: 'fb_post', label: 'Facebook 帖子采集' },
+  { value: 'fb_discover', label: 'Facebook 帖子发现' },
+  { value: 'fb_group', label: 'Facebook 群帖采集' },
 ]
 
 export function taskTypeLabel(type: string): string {
   return TASK_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type
 }
 
 /** worker 标识徽标：同一 worker 恒同色（哈希取色相，明暗主题通用）。 */
 export function workerChip(worker: number | string | undefined | null) {
   if (worker === undefined || worker === null || worker === '') return null
   const s = String(worker)
@@ -137,20 +139,48 @@ export function paramsSummary(task: { type: string; params: Record<string, unkno
   if (task.type === 'wa_check') {
     const parts: string[] = []
     const limit = num('limit')
     if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '全部未查')
     const accs = Array.isArray(p.accounts) ? (p.accounts as unknown[]).filter((a) => typeof a === 'string') : []
     if (accs.length > 0) parts.push(`账号=${accs.join(',')}`)
     if (repeatPart) parts.push(repeatPart)
     return parts.length > 0 ? parts.join(' ') : '默认参数'
   }
 
+  // fb_discover：N 词 × M 页（keywords 按换行拆词计数、空视为 1；pages 缺省 1）
+  if (task.type === 'fb_discover') {
+    const raw = typeof p.keywords === 'string' ? p.keywords : ''
+    const wordCount = raw
+      .split('\n')
+      .map((s) => s.trim())
+      .filter((s) => s.length > 0).length
+    const m = typeof p.pages === 'number' && Number.isFinite(p.pages) ? p.pages : 1
+    const parts: string[] = []
+    parts.push(wordCount > 0 ? `${wordCount} 词 × ${m} 页` : `默认矩阵 × ${m} 页`)
+    if (repeatPart) parts.push(repeatPart)
+    return parts.join(' ')
+  }
+
+  // fb_group：provider + 每群≤N帖 + 群数上限（limit，0=不限）
+  if (task.type === 'fb_group') {
+    const provider = p.provider === 'apify' ? 'Apify' : 'Bright Data'
+    const ppg =
+      typeof p.posts_per_group === 'number' && Number.isFinite(p.posts_per_group)
+        ? p.posts_per_group
+        : 50
+    const limit = num('limit')
+    const parts: string[] = [`provider=${provider}`, `每群≤${ppg}帖`]
+    parts.push(limit !== null && limit > 0 ? `群数上限=${limit}` : '群数不限')
+    if (repeatPart) parts.push(repeatPart)
+    return parts.join(' ')
+  }
+
   // P4 批次采集类型（1688/madeinchina shop/company/contact + fb_post）：
   // 只读 limit（contact=条数、shop/company=页数）+ repeat_interval
   const BATCH_TYPES = new Set(['1688_shop', '1688_company', '1688_contact',
                                'madeinchina_shop', 'madeinchina_contact',
                                'fb_post'])
   if (BATCH_TYPES.has(task.type)) {
     const parts: string[] = []
     const limit = num('limit')
     if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '不限量')
     if (repeatPart) parts.push(repeatPart)
