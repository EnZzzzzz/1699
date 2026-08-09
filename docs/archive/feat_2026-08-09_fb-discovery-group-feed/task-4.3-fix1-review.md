# Step 4.3 fix round 1 review
95ff95f fix(fb): Step 4.3 review 第1轮修复——validate() 补 keywords 空 warning + provider 防御校验
 .../task-4.3-report.md                             | 59 ++++++++++++++++++++++
 platform/web/src/pages/tasks/TaskFormDialog.tsx    | 10 ++++
 2 files changed, 69 insertions(+)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md
index 2747484..5f5d683 100644
--- a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md
@@ -102,10 +102,69 @@ fillFromParams 可正确从 params 键回填四个新状态。
 - ✅ 按钮：沿用现有 `variant="outline" size="sm"`
 - ✅ 无硬编码色值：全部使用 Tailwind utility classes
 - ✅ Textarea: `min-h-24 font-mono text-xs`
 
 ## 自查发现
 
 - 无
 - 所有 10 项 PLAN checkbox 均已满足
 - 五形态渲染顺序符合协调者裁定（isBatch → isWaCheck → isFbDiscover → isFbGroup → 默认）
 - fb_group 群数上限复用 batchLimit state（与 isBatch 共用，符合裁定）
+
+---
+
+# Step 4.3 修复记录（第 1 轮 review 发现）
+
+## 状态：FIXED
+
+## Review 发现与修复
+
+### 1. 缺失 keywords 空 toast 警告（validate() fb_discover 分支）
+
+**现象**：fb_discover 分支只校验了 pages，keywords 为空时静默放行，无任何提示。
+
+**修复**：在 fb_discover 分支顶部增加——
+
+```ts
+if (fbDiscoverKeywords.trim() === '') {
+  toast.warning('未填写查询词，将使用空关键词（后端幂等跳过）')
+}
+```
+
+符合裁定#5：keywords 空 → `toast.warning` 但不阻塞（后端 enqueue 空→0 幂等），
+pages 校验逻辑保持在其后，pages 非法仍 `toast.error + return false`。
+
+### 2. 缺失 provider 防御校验（validate() fb_group 分支）
+
+**现象**：fb_group 分支未对 provider 做代码级防御校验（Select UI 已限定，但无
+兜底）。
+
+**修复**：在 fb_group 分支顶部增加——
+
+```ts
+const provider = fbGroupProvider as string
+if (provider !== 'brightdata' && provider !== 'apify') {
+  toast.error('数据来源仅支持 Bright Data 或 Apify')
+  return false
+}
+```
+
+符合裁定#5：provider ∈ {brightdata, apify} 防御校验，非法 → `toast.error` 并
+`return false` 阻塞提交。`as string` 是为了通过 TS 严格类型（state 类型本身已限定
+为联合类型，直接比较非法值字面量会触发 TS 无重叠告警；运行时防御依然有效）。
+
+## TypeScript 编译
+
+```
+$ cd platform/web && npx tsc -b
+EXIT: 0
+```
+
+全绿，零错误零警告（含新增两处校验代码的严格类型检查）。
+
+## 回归影响
+
+- 仅改动 validate() 两个分支内部，未触及 buildParams / 渲染 / 其它分支。
+- fb_discover：空 keywords 现在会弹 warning toast，提交照常（行为从"静默放行"变为
+  "提示后放行"，不阻塞）。
+- fb_group：provider 非法（正常 UI 路径不可能触发，仅防 API 层或异常状态）会
+  toast.error 并阻止提交；合法 provider 路径行为不变。
diff --git a/platform/web/src/pages/tasks/TaskFormDialog.tsx b/platform/web/src/pages/tasks/TaskFormDialog.tsx
index dd623e7..90aadd3 100644
--- a/platform/web/src/pages/tasks/TaskFormDialog.tsx
+++ b/platform/web/src/pages/tasks/TaskFormDialog.tsx
@@ -333,30 +333,40 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
       if (waLimit.trim() !== '') {
         const n = Number(waLimit)
         if (!Number.isInteger(n) || n < 0) {
           toast.error('查号上限需为不小于 0 的整数（0 = 全部未查）')
           return false
         }
       }
       return true
     }
     if (isFbDiscover) {
+      // keywords 空 → 警告但不阻塞（后端 enqueue 空→0 幂等，裁定#5）
+      if (fbDiscoverKeywords.trim() === '') {
+        toast.warning('未填写查询词，将使用空关键词（后端幂等跳过）')
+      }
       if (fbDiscoverPages.trim() !== '') {
         const n = Number(fbDiscoverPages)
         if (!Number.isInteger(n) || n < 1 || n > 10) {
           toast.error('每词页数需为 1-10 的整数')
           return false
         }
       }
       return true
     }
     if (isFbGroup) {
+      // provider 防御校验：Select 已限定，代码级再兜底（裁定#5）
+      const provider = fbGroupProvider as string
+      if (provider !== 'brightdata' && provider !== 'apify') {
+        toast.error('数据来源仅支持 Bright Data 或 Apify')
+        return false
+      }
       if (fbGroupPostsPerGroup.trim() !== '') {
         const n = Number(fbGroupPostsPerGroup)
         if (!Number.isInteger(n) || n < 1) {
           toast.error('每群帖数上限需为不小于 1 的整数')
           return false
         }
       }
       if (batchLimit.trim() !== '') {
         const n = Number(batchLimit)
         if (!Number.isInteger(n) || n < 0) {
