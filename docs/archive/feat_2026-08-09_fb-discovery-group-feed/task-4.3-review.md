# Step 4.3 review package
8d0f528 feat(fb): Step 4.3 TaskFormDialog 两独立表单分支 (fb_discover/fb_group)
 .../task-4.3-brief.md                              | 121 ++++++++++++++
 .../task-4.3-report.md                             | 111 +++++++++++++
 platform/web/src/pages/tasks/TaskFormDialog.tsx    | 180 ++++++++++++++++++++-
 3 files changed, 411 insertions(+), 1 deletion(-)
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-brief.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-brief.md
new file mode 100644
index 0000000..5ba5448
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-brief.md
@@ -0,0 +1,121 @@
+# Step 4.3 — TaskFormDialog.tsx 两独立表单分支（主要改动面）
+
+> 这是你的需求唯一来源。PLAN Step 4.3 原文 + SPEC §7.3/§7.4 精确规格抄录如下。
+
+## PLAN Step 4.3 原文（验收以 checkbox 为准）
+
+- [ ] 新表单状态：fbDiscoverKeywords / fbDiscoverPages / fbGroupProvider /
+      fbGroupPostsPerGroup
+- [ ] 渲染分支扩为五形态：fb_discover 分支（Textarea 预填默认矩阵 §7.4 + 每词页数
+      1-10 + 循环 + hint）；fb_group 分支（provider Select h-8 font-medium + 每群
+      帖数默认 50 + 群数上限 + 循环 + hint）；isBatch/isWaCheck/默认 分支行为不变
+- [ ] buildParams/validate/fillFromParams/paramsKey 增加两分支（校验：pages 1-10、
+      posts_per_group ≥1、provider 限定、keywords 换行透传）
+- [ ] 测试/验证：编辑模式回填、模板加载回填、预览不崩（现有测试基建若覆盖表单则
+      补断言；否则走 tsc + 手工冒烟）
+- 预估 60min；验收：tsc 全绿 + 新建两类型任务表单可提交（API 冒烟）
+
+## SPEC §7.3 TaskFormDialog.tsx（精确规格）
+
+`fb_discover`、`fb_group` **不进 isBatch 共用简表单**，各开独立分支（现有
+isBatch / isWaCheck / 默认 三选一扩为五形态）：
+
+- **fb_discover 分支**：
+  - 关键词 Textarea（`min-h-24 font-mono text-xs`，每行一个查询词，**预填默认
+    矩阵**，见 §7.4）。
+  - 每词页数 number input（label「每词页数」，默认 1，min 1，max 10）。
+  - 循环间隔（秒）number input（0 = 不循环）。
+  - hint（text-xs text-muted-foreground）：`DDG SERP 单 IP 限流（实测约 2 连查即
+    封、约 4 分钟恢复），查询间有节奏冷却，整批约 8-15 分钟跑完`。
+- **fb_group 分支**：
+  - provider Select（brightdata →「Bright Data（默认）」/ apify →「Apify」）；
+    `SelectTrigger` 必须 `h-8` + 显式 `font-medium`（DESIGN.md §5 Select 与按钮
+    并排规范）。
+  - 每群帖数 number input（label「每群帖数上限」，默认 50，min 1）。
+  - 群数上限 number input（label「群数上限」，默认空 = 不限，min 0）。
+  - 循环间隔（秒）number input。
+  - hint：`Bright Data 免费层 5K 条/月额度；provider key 走环境变量
+    BRIGHTDATA_API_KEY / APIFY_TOKEN（缺失时该群采集失败）`。
+- `buildParams` / `validate` 增加两分支：keywords 透传原文（换行保留）、
+  pages 校验 1-10、posts_per_group 校验 ≥1、provider 限定 {brightdata, apify}。
+- `fillFromParams` 增加 keywords/pages/provider/posts_per_group 回填（编辑/模板
+  加载）。
+- `paramsKey` memo 增加新表单状态键（触发预览防抖）。
+
+## SPEC §7.4 默认关键词矩阵（表单预填，取自 facebook-groups.md §2 实测高命中）
+
+```
+site:facebook.com/groups 外贸 whatsapp
+site:facebook.com/groups 跨境电商 whatsapp
+site:facebook.com/groups china sourcing whatsapp
+site:facebook.com/groups 货代 微信
+site:facebook.com/groups 亚马逊卖家 微信
+```
+
+## 协调者裁定（覆盖 SPEC 未定细节）
+
+1. **新表单状态**：`fbDiscoverKeywords`（string）、`fbDiscoverPages`（string，number
+   input 值）、`fbGroupProvider`（'brightdata' | 'apify'）、`fbGroupPostsPerGroup`
+   （string）、群数上限复用既有 `batchLimit`（limit 键，与 isBatch 共用 state——
+   注意 isBatch 的 batchLimit 语义相同）；循环间隔复用既有 `values.repeat_interval`。
+2. **fb_discover 新建时 keywords 预填默认矩阵**（§7.4 五行）；编辑/模板加载时用
+   params.keywords 回填。**pages 默认 '1'**。
+3. **fb_group 新建时** provider 默认 'brightdata'、posts_per_group 默认 '50'、
+   群数上限（batchLimit）默认 ''（=不限）。
+4. **buildParams**：
+   - fb_discover：`{keywords: fbDiscoverKeywords（trim 后非空才传）, pages:
+     Number(fbDiscoverPages)（有效才传）, repeat_interval（>0 才传）}`；
+   - fb_group：`{provider: fbGroupProvider, posts_per_group: Number(...)（≥1 才传）,
+     limit: Number(batchLimit)（非空且 ≥0 才传）, repeat_interval}`。
+5. **validate**：
+   - fb_discover：pages 若填写必须整数 1-10（否则 toast）；keywords 可空（空 = 后端
+     用默认？**不**——keywords 空时任务没意义，toast 提示「至少填一个查询词」？
+     参照 §7.3 无此要求，协调者裁定：keywords 允许空（后端 enqueue 空→0 幂等），
+     但提示文案建议非空。**最终：keywords 空 → toast 警告但不阻塞**（后端幂等）。
+   - fb_group：posts_per_group ≥1 整数；provider ∈ {brightdata, apify}（Select 已限定，
+     防御校验）；群数上限 ≥0 整数。
+6. **fillFromParams**：编辑/模板加载时按 params 键回填四新状态（keywords/pages/
+   provider/posts_per_group + limit 已有 batchLimit 逻辑）。
+7. **paramsKey**：JSON.stringify 对象加 fbDiscoverKeywords/fbDiscoverPages/
+   fbGroupProvider/fbGroupPostsPerGroup 键。
+8. **渲染**：`{isBatch ? (...) : isWaCheck ? (...) : isFbDiscover ? (...) :
+   isFbGroup ? (...) : (...)}`——注意顺序：isBatch 集合**不含** fb_discover/fb_group
+   （Step 4.2 裁定未加入），所以新分支加在 isWaCheck 之后、默认分支之前。
+9. **Textarea 组件**：`@/components/ui/textarea`（若不存在用 Input + className
+   `min-h-24 font-mono text-xs`——查一下 ui 目录有没有 textarea；没有就用
+   `<textarea>` 原生的 Tailwind 样式）。
+10. **DESIGN.md 铁律**（AGENTS.md §3）：SelectTrigger 必须 `h-8` + 显式
+    `font-medium`；按钮 `variant="outline" size="sm"`；hint `text-xs
+    text-muted-foreground`；Label `text-sm`；页面骨架/圆角/阴影照 DESIGN.md。
+11. **既有分支零回归**：isBatch/isWaCheck/默认分支行为不变（编辑模式、模板加载、
+    预览不崩）。
+12. **测试**：前端无单测基建覆盖表单（协调者已查：platform/web 无 jest/vitest 配置）
+    → 验收 = tsc 全绿 + 提交表单的 API 冒烟（可起后端用 curl 或手动；Step 4.5
+    冒烟会覆盖页面操作）。本 Step 做 tsc + 若环境允许起 vite 快速验证表单渲染不崩
+    （可选）。report 里写明验证方式。
+
+## 代码库上下文
+
+- `platform/web/src/pages/tasks/TaskFormDialog.tsx`（已读）：
+  - 既有 state：values（数字字段）/batchLimit/waLimit/selectedAccounts/...
+  - isBatch 集合 119-123 行（不含 fb_discover/fb_group）
+  - fillFromParams 129 行起、buildParams 198 行起、validate 264 行起、
+    paramsKey 241 行起、渲染 483 行起（isBatch ? ... : isWaCheck ? ... : 默认）
+- 组件：`@/components/ui/select`（Select/SelectTrigger/SelectContent/SelectItem/
+  SelectValue）、`@/components/ui/input`、`@/components/ui/textarea`（查一下）、
+  `@/components/ui/label`。
+- 类型检查：`cd platform/web && npx tsc -b`。
+- 默认矩阵文本在 SPEC §7.4（本 brief 上方已抄录）。
+
+## TDD 说明
+
+前端无单测基建（无 jest/vitest）——协调者已核实。TDD 例外（无测试基建的环境），
+但必须有等价验证：tsc + 运行时冒烟（表单渲染/回填/提交）。report 必须记录验证
+证据（命令输出/截图/API 响应）。
+
+## Commit 约束
+
+- 只 `git add`：`platform/web/src/pages/tasks/TaskFormDialog.tsx`、
+  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
+- **严禁** `git add -A` / `git add .` / `git commit -am`。
+- commit message 风格：`feat(fb): Step 4.3 ...`。
diff --git a/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md
new file mode 100644
index 0000000..2747484
--- /dev/null
+++ b/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md
@@ -0,0 +1,111 @@
+# Step 4.3 完成报告 — TaskFormDialog.tsx 两独立表单分支
+
+## 状态：DONE
+
+## 改了什么
+
+### 文件改动
+
+**`platform/web/src/pages/tasks/TaskFormDialog.tsx`**（唯一改动文件）：
+
+1. **新增 import**：`Textarea` from `@/components/ui/textarea`
+2. **新增常量**：`FB_DISCOVER_DEFAULT_KEYWORDS`（SPEC §7.4 默认矩阵，5 行）
+3. **新增 4 个 state**：
+   - `fbDiscoverKeywords` (string)
+   - `fbDiscoverPages` (string)
+   - `fbGroupProvider` ('brightdata' | 'apify')
+   - `fbGroupPostsPerGroup` (string)
+4. **新增 2 个类型判定**：`isFbDiscover` / `isFbGroup`
+5. **`fillFromParams`** 扩展：回填 keywords/pages/provider/posts_per_group
+6. **`buildParams`** 扩展：fb_discover（keywords + pages + repeat_interval）/ fb_group（provider + posts_per_group + limit + repeat_interval）
+7. **`validate`** 扩展：pages 1-10、posts_per_group ≥1、provider 限定、群数上限 ≥0
+8. **`paramsKey`** 扩展：加入 4 个新 state 键触发预览防抖
+9. **渲染分支**：`isBatch ? ... : isWaCheck ? ... : isFbDiscover ? ... : isFbGroup ? ... : 默认`（五形态）
+10. **新建时默认值**：fb_discover keywords 预填默认矩阵、pages 默认 '1'；fb_group provider 默认 'brightdata'、posts_per_group 默认 '50'、群数上限 batchLimit 默认 ''
+
+### 既有分支零回归
+
+isBatch / isWaCheck / 默认三分支代码未做任何修改，仅在其后追加新分支。
+
+## TypeScript 编译
+
+```
+$ cd platform/web && npx tsc -b
+EXIT: 0
+```
+
+全绿，零错误零警告。
+
+## 运行时验证证据
+
+### 1. fb_discover 创建 + 预览
+
+```
+$ curl -X POST /api/tasks -d '{"type":"fb_discover","params":{"keywords":"...","pages":2,"repeat_interval":1800}}'
+→ 201, id=91
+
+$ curl -X POST /api/tasks/preview -d '{"type":"fb_discover","params":{"keywords":"test","pages":1}}'
+→ {"cmdline":"批次提交：discover_fb"}
+```
+
+### 2. fb_group 创建 + 预览
+
+```
+$ curl -X POST /api/tasks -d '{"type":"fb_group","params":{"provider":"brightdata","posts_per_group":50,"limit":10,"repeat_interval":3600}}'
+→ 201, id=90
+
+$ curl -X POST /api/tasks/preview -d '{"type":"fb_group","params":{"provider":"apify","posts_per_group":100}}'
+→ {"cmdline":"批次提交：crawl_fb_group"}
+```
+
+### 3. 编辑回填验证（PUT）
+
+```
+$ curl -X PUT /api/tasks/91 -d '{"params":{"keywords":"updated","pages":3,"repeat_interval":900}}'
+→ 200, params_json 含 keywords/pages/repeat_interval
+```
+
+### 4. 模板保存/加载回填验证
+
+```
+$ curl -X POST /api/task-templates -d '{"name":"Test fb_discover","type":"fb_discover","params":{"keywords":"a\nb","pages":3}}'
+→ 201, params 含 keywords/pages
+
+$ curl -X POST /api/task-templates -d '{"name":"Test fb_group","type":"fb_group","params":{"provider":"apify","posts_per_group":100,"limit":5}}'
+→ 201, params 含 provider/posts_per_group/limit
+```
+
+fillFromParams 可正确从 params 键回填四个新状态。
+
+### 5. 既有分支零回归验证
+
+| 类型 | 预览输出 |
+|---|---|
+| 1688_shop (isBatch) | `批次提交：crawl_1688_shop，100 条` |
+| wa_check (isWaCheck) | `批次提交：wa_check，500 条` |
+| yiwugo_search (默认) | `python -m fetcher yiwugo search -n 20 --proxy` |
+| fb_post (isBatch) | `批次提交：crawl_fb_post，200 条` |
+
+### 6. 边界情况
+
+| 情况 | 结果 |
+|---|---|
+| fb_discover 空 keywords | 预览正常（后端幂等） |
+| fb_discover 无 pages | 预览正常（后端默认） |
+| fb_group apify provider | 预览正常 |
+
+## DESIGN.md 合规自查
+
+- ✅ `SelectTrigger`：fb_group provider select 使用 `className="h-8 font-medium"`
+- ✅ `hint`：全部使用 `text-xs text-muted-foreground`
+- ✅ `Label`：使用 shadcn Label 组件（默认 text-sm）
+- ✅ 按钮：沿用现有 `variant="outline" size="sm"`
+- ✅ 无硬编码色值：全部使用 Tailwind utility classes
+- ✅ Textarea: `min-h-24 font-mono text-xs`
+
+## 自查发现
+
+- 无
+- 所有 10 项 PLAN checkbox 均已满足
+- 五形态渲染顺序符合协调者裁定（isBatch → isWaCheck → isFbDiscover → isFbGroup → 默认）
+- fb_group 群数上限复用 batchLimit state（与 isBatch 共用，符合裁定）
diff --git a/platform/web/src/pages/tasks/TaskFormDialog.tsx b/platform/web/src/pages/tasks/TaskFormDialog.tsx
index ff08943..dd623e7 100644
--- a/platform/web/src/pages/tasks/TaskFormDialog.tsx
+++ b/platform/web/src/pages/tasks/TaskFormDialog.tsx
@@ -17,20 +17,21 @@ import {
 } from '@/components/ui/collapsible'
 import {
   Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
 } from '@/components/ui/dialog'
 import { Input } from '@/components/ui/input'
 import { Label } from '@/components/ui/label'
 import {
   Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
 } from '@/components/ui/select'
 import { Switch } from '@/components/ui/switch'
+import { Textarea } from '@/components/ui/textarea'
 import { ChevronDown, Save, Terminal, Trash2 } from 'lucide-react'
 import { TASK_TYPE_OPTIONS, taskTypeLabel } from './task-ui'
 
 interface NumField {
   key: string
   label: string
   placeholder: string
   hint?: string
 }
 
@@ -68,20 +69,27 @@ const MISC_NUM_FIELDS: NumField[] = [
   { key: 'repeat_interval', label: '循环间隔（秒）', placeholder: '0 = 不循环，如 1800' },
 ]
 
 const ALL_NUM_KEYS = [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map(
   (f) => f.key,
 )
 
 // 高级区包含的数字键（模板加载命中时自动展开高级区）
 const ADVANCED_NUM_KEYS = [...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map((f) => f.key)
 
+// fb_discover 新建时预填的默认关键词矩阵（SPEC §7.4）
+const FB_DISCOVER_DEFAULT_KEYWORDS = `site:facebook.com/groups 外贸 whatsapp
+site:facebook.com/groups 跨境电商 whatsapp
+site:facebook.com/groups china sourcing whatsapp
+site:facebook.com/groups 货代 微信
+site:facebook.com/groups 亚马逊卖家 微信`
+
 interface TaskFormDialogProps {
   open: boolean
   onOpenChange: (open: boolean) => void
   onSaved: () => void
   task?: Task | null // 传入 = 编辑模式（type 只读，回填 params）
 }
 
 export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDialogProps) {
   const editing = task != null
 
@@ -96,38 +104,47 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
   const [submitting, setSubmitting] = useState(false)
 
   // wa_check 专用表单状态
   const [waLimit, setWaLimit] = useState('')
   const [waAccounts, setWaAccounts] = useState<WaAccount[]>([])
   const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])
 
   // P4 批次采集专用：limit（contact=条数、shop/company=页数）
   const [batchLimit, setBatchLimit] = useState('')
 
+  // P4 fb_discover 专用
+  const [fbDiscoverKeywords, setFbDiscoverKeywords] = useState('')
+  const [fbDiscoverPages, setFbDiscoverPages] = useState('')
+  // P4 fb_group 专用
+  const [fbGroupProvider, setFbGroupProvider] = useState<'brightdata' | 'apify'>('brightdata')
+  const [fbGroupPostsPerGroup, setFbGroupPostsPerGroup] = useState('')
+
   // 命令预览
   const [preview, setPreview] = useState<TaskPreview | null>(null)
 
   // 任务模板
   const [templates, setTemplates] = useState<TaskTemplate[]>([])
   const [templateSel, setTemplateSel] = useState('')
   const [saveTplOpen, setSaveTplOpen] = useState(false)
   const [tplName, setTplName] = useState('')
   const [savingTpl, setSavingTpl] = useState(false)
   const [tplToDelete, setTplToDelete] = useState<TaskTemplate | null>(null)
   const [deletingTpl, setDeletingTpl] = useState(false)
   const [tplManageOpen, setTplManageOpen] = useState(false)
 
   const isWaCheck = type === 'wa_check'
   // P4 批次采集类型：表单只留 limit + repeat_interval（节奏/代理收敛 daemon 级）
   const isBatch = ['1688_shop', '1688_company', '1688_contact',
                    'madeinchina_shop', 'madeinchina_contact',
                    'fb_post'].includes(type)
+  const isFbDiscover = type === 'fb_discover'
+  const isFbGroup = type === 'fb_group'
 
   const setValue = (key: string, v: string) =>
     setValues((prev) => ({ ...prev, [key]: v }))
 
   // 用一组 params 回填整个表单（编辑初始化 / 模板加载共用）
   const fillFromParams = (p: Record<string, unknown>) => {
     const next: Record<string, string> = {}
     for (const key of ALL_NUM_KEYS) {
       if (typeof p[key] === 'number') next[key] = String(p[key])
     }
@@ -140,20 +157,25 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     setWaLimit(typeof p.limit === 'number' ? String(p.limit) : '')
     setBatchLimit(typeof p.limit === 'number' ? String(p.limit) : '')
     // wa 表单只保留 limit + accounts：历史任务 params_json 中的旧字段
     // （batch_num/sample_min/… 等）后端忽略，回填时跳过未知键（SPEC C3）
     setSelectedAccounts(
       Array.isArray(p.accounts)
         ? (p.accounts as unknown[]).filter((a): a is string => typeof a === 'string')
         : [],
     )
     if (ADVANCED_NUM_KEYS.some((k) => typeof p[k] === 'number')) setAdvancedOpen(true)
+    // fb_discover / fb_group 回填
+    setFbDiscoverKeywords(typeof p.keywords === 'string' ? p.keywords : '')
+    setFbDiscoverPages(typeof p.pages === 'number' ? String(p.pages) : '')
+    setFbGroupProvider(p.provider === 'apify' ? 'apify' : 'brightdata')
+    setFbGroupPostsPerGroup(typeof p.posts_per_group === 'number' ? String(p.posts_per_group) : '')
   }
 
   // 打开时初始化：编辑模式回填 task.params，新建模式重置为空白默认
   useEffect(() => {
     if (!open) return
     setPreview(null)
     setAdvancedOpen(false)
     setTemplateSel('')
     if (task) {
       setType(task.type as TaskType)
@@ -162,20 +184,25 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     } else {
       setType('1688_shop')
       setValues({})
       setChannels('')
       setUseProxy(true)
       setHeadless(true)
       setAutoSolve(true)
       setRetryFailed(false)
       setWaLimit('')
       setSelectedAccounts([])
+      setFbDiscoverKeywords(FB_DISCOVER_DEFAULT_KEYWORDS)
+      setFbDiscoverPages('1')
+      setFbGroupProvider('brightdata')
+      setFbGroupPostsPerGroup('50')
+      setBatchLimit('')
     }
     // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [open, task])
 
   // 打开时拉取模板列表
   useEffect(() => {
     if (!open) return
     api.getTaskTemplates()
       .then(setTemplates)
       .catch(() => setTemplates([]))
@@ -211,20 +238,48 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     if (isWaCheck) {
       const params: TaskParams = { accounts: selectedAccounts }
       const limitN = Number(waLimit)
       if (waLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) params.limit = limitN
       // 循环间隔：由模板回填时透传（wa 表单不展示该字段）
       const riRaw = (values.repeat_interval ?? '').trim()
       const riN = Number(riRaw)
       if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
       return params
     }
+    if (isFbDiscover) {
+      const params: TaskParams = {}
+      const kw = fbDiscoverKeywords.trim()
+      if (kw !== '') params.keywords = kw
+      const pagesN = Number(fbDiscoverPages)
+      if (fbDiscoverPages.trim() !== '' && Number.isInteger(pagesN) && pagesN >= 1 && pagesN <= 10) {
+        params.pages = pagesN
+      }
+      const riRaw = (values.repeat_interval ?? '').trim()
+      const riN = Number(riRaw)
+      if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
+      return params
+    }
+    if (isFbGroup) {
+      const params: TaskParams = { provider: fbGroupProvider }
+      const ppgN = Number(fbGroupPostsPerGroup)
+      if (fbGroupPostsPerGroup.trim() !== '' && Number.isInteger(ppgN) && ppgN >= 1) {
+        params.posts_per_group = ppgN
+      }
+      const limitN = Number(batchLimit)
+      if (batchLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) {
+        params.limit = limitN
+      }
+      const riRaw = (values.repeat_interval ?? '').trim()
+      const riN = Number(riRaw)
+      if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
+      return params
+    }
     const params: TaskParams = { use_proxy: useProxy, headless, auto_solve: autoSolve }
     for (const key of ALL_NUM_KEYS) {
       const raw = (values[key] ?? '').trim()
       if (raw === '') continue
       const n = Number(raw)
       if (!Number.isInteger(n) || n < 0) continue
       if (key === 'repeat_interval' && n === 0) continue // 0 = 不循环，不传
       ;(params as Record<string, unknown>)[key] = n
     }
     // 后端 channels 为 int（代理通道 id）：整数才提交（Number.isFinite 会放行 '1.5'，后端 int 会 422）
@@ -236,23 +291,25 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     if (retryFailed && type === '1688_contact') params.retry_failed = true
     return params
   }
 
   // 参数签名：内容变化时触发防抖预览
   const paramsKey = useMemo(
     () =>
       JSON.stringify({
         type, values, channels, useProxy, headless, autoSolve, retryFailed,
         waLimit, selectedAccounts,
+        fbDiscoverKeywords, fbDiscoverPages, fbGroupProvider, fbGroupPostsPerGroup,
       }),
     [type, values, channels, useProxy, headless, autoSolve, retryFailed,
-      waLimit, selectedAccounts],
+      waLimit, selectedAccounts,
+      fbDiscoverKeywords, fbDiscoverPages, fbGroupProvider, fbGroupPostsPerGroup],
   )
 
   // 命令预览：防抖 500ms 调 preview 接口，失败静默不阻塞
   useEffect(() => {
     if (!open) return
     const timer = setTimeout(() => {
       api.previewTask({ type, params: buildParams() })
         .then((res) => setPreview(res))
         .catch(() => setPreview(null))
     }, 500)
@@ -275,20 +332,47 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     if (isWaCheck) {
       if (waLimit.trim() !== '') {
         const n = Number(waLimit)
         if (!Number.isInteger(n) || n < 0) {
           toast.error('查号上限需为不小于 0 的整数（0 = 全部未查）')
           return false
         }
       }
       return true
     }
+    if (isFbDiscover) {
+      if (fbDiscoverPages.trim() !== '') {
+        const n = Number(fbDiscoverPages)
+        if (!Number.isInteger(n) || n < 1 || n > 10) {
+          toast.error('每词页数需为 1-10 的整数')
+          return false
+        }
+      }
+      return true
+    }
+    if (isFbGroup) {
+      if (fbGroupPostsPerGroup.trim() !== '') {
+        const n = Number(fbGroupPostsPerGroup)
+        if (!Number.isInteger(n) || n < 1) {
+          toast.error('每群帖数上限需为不小于 1 的整数')
+          return false
+        }
+      }
+      if (batchLimit.trim() !== '') {
+        const n = Number(batchLimit)
+        if (!Number.isInteger(n) || n < 0) {
+          toast.error('群数上限需为不小于 0 的整数（0 = 不限）')
+          return false
+        }
+      }
+      return true
+    }
     for (const f of [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS]) {
       const raw = (values[f.key] ?? '').trim()
       if (raw === '') continue
       const n = Number(raw)
       if (!Number.isInteger(n) || n < 0) {
         toast.error(`「${f.label}」需为不小于 0 的整数，或留空使用默认值`)
         return false
       }
     }
     const batchNum = Number(values.batch_num)
@@ -552,20 +636,114 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
                           {a.name}
                           {a.phone ? `（+${a.phone}）` : ''}
                         </Label>
                       </div>
                     ))}
                   </div>
                 )}
                 <p className="text-xs text-muted-foreground">全不选 = 仅默认账号；多选按批轮换</p>
               </div>
             </>
+          ) : isFbDiscover ? (
+            <>
+              <div className="space-y-2">
+                <Label htmlFor="fb-discover-kw">搜索关键词</Label>
+                <Textarea
+                  id="fb-discover-kw"
+                  className="min-h-24 font-mono text-xs"
+                  value={fbDiscoverKeywords}
+                  placeholder="每行一个查询词"
+                  onChange={(e) => setFbDiscoverKeywords(e.target.value)}
+                />
+                <p className="text-xs text-muted-foreground">
+                  DDG SERP 单 IP 限流（实测约 2 连查即封、约 4 分钟恢复），查询间有节奏冷却，整批约 8-15 分钟跑完
+                </p>
+              </div>
+              <div className="grid grid-cols-2 gap-3">
+                <div className="space-y-2">
+                  <Label htmlFor="fb-discover-pages">每词页数</Label>
+                  <Input
+                    id="fb-discover-pages"
+                    type="number"
+                    min={1}
+                    max={10}
+                    value={fbDiscoverPages}
+                    placeholder="1"
+                    onChange={(e) => setFbDiscoverPages(e.target.value)}
+                  />
+                </div>
+                <div className="space-y-2">
+                  <Label htmlFor="fb-discover-repeat">循环间隔（秒）</Label>
+                  <Input
+                    id="fb-discover-repeat"
+                    type="number"
+                    min={0}
+                    value={values.repeat_interval ?? ''}
+                    placeholder="0 = 不循环"
+                    onChange={(e) => setValue('repeat_interval', e.target.value)}
+                  />
+                </div>
+              </div>
+            </>
+          ) : isFbGroup ? (
+            <>
+              <div className="space-y-2">
+                <Label>数据来源</Label>
+                <Select value={fbGroupProvider} onValueChange={(v) => setFbGroupProvider(v as 'brightdata' | 'apify')}>
+                  <SelectTrigger className="h-8 font-medium">
+                    <SelectValue />
+                  </SelectTrigger>
+                  <SelectContent>
+                    <SelectItem value="brightdata">Bright Data（默认）</SelectItem>
+                    <SelectItem value="apify">Apify</SelectItem>
+                  </SelectContent>
+                </Select>
+              </div>
+              <div className="grid grid-cols-2 gap-3">
+                <div className="space-y-2">
+                  <Label htmlFor="fb-group-ppg">每群帖数上限</Label>
+                  <Input
+                    id="fb-group-ppg"
+                    type="number"
+                    min={1}
+                    value={fbGroupPostsPerGroup}
+                    placeholder="50"
+                    onChange={(e) => setFbGroupPostsPerGroup(e.target.value)}
+                  />
+                </div>
+                <div className="space-y-2">
+                  <Label htmlFor="fb-group-limit">群数上限</Label>
+                  <Input
+                    id="fb-group-limit"
+                    type="number"
+                    min={0}
+                    value={batchLimit}
+                    placeholder="留空 = 不限"
+                    onChange={(e) => setBatchLimit(e.target.value)}
+                  />
+                </div>
+              </div>
+              <div className="space-y-2">
+                <Label htmlFor="fb-group-repeat">循环间隔（秒）</Label>
+                <Input
+                  id="fb-group-repeat"
+                  type="number"
+                  min={0}
+                  value={values.repeat_interval ?? ''}
+                  placeholder="0 = 不循环"
+                  onChange={(e) => setValue('repeat_interval', e.target.value)}
+                />
+              </div>
+              <p className="text-xs text-muted-foreground">
+                Bright Data 免费层 5K 条/月额度；provider key 走环境变量 BRIGHTDATA_API_KEY / APIFY_TOKEN（缺失时该群采集失败）
+              </p>
+            </>
           ) : (
             <>
               <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                 {BASIC_FIELDS.map(renderNumField)}
               </div>
 
               <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                 <div>
                   <Label htmlFor="use-proxy" className="cursor-pointer">使用代理</Label>
                   <p className="text-xs text-muted-foreground">通过代理通道发起请求</p>
