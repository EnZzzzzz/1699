# Review package — Step 2.1 (BASE cc5c163de336149e96452f04ab7ebdfc488b7465..HEAD)

## git log
63e758d chore(p5): 同步 TaskParams.retry_failed 注释（build_command 分支已删）
b9ee35d refactor(p5): 前端同步——wa 表单裁剪 + 删从命令导入 UI + api.ts 类型失配修复

## git diff --stat
 platform/server/app/api/tasks.py                |   2 +-
 platform/web/src/lib/api.ts                     |  26 +--
 platform/web/src/pages/tasks/TaskFormDialog.tsx | 239 +++---------------------
 platform/web/src/pages/tasks/task-ui.tsx        |  20 +-
 4 files changed, 36 insertions(+), 251 deletions(-)

## git diff -U10
diff --git a/platform/server/app/api/tasks.py b/platform/server/app/api/tasks.py
index f53f209..4378964 100644
--- a/platform/server/app/api/tasks.py
+++ b/platform/server/app/api/tasks.py
@@ -106,21 +106,21 @@ class TaskParams(BaseModel):
     stagger_max: float | None = None        # → --stagger-max
     ip_retry: int | None = None             # → --ip-retry
     net_retry: int | None = None            # → --net-retry
     max_consecutive_fail: int | None = None  # → --max-consecutive-fail
     block_rest_min: float | None = None     # → --block-rest-min
     block_rest_max: float | None = None     # → --block-rest-max
     # 开关
     use_proxy: bool | None = None           # true → --proxy
     headless: bool | None = None            # false → --headed
     auto_solve: bool | None = None          # false → --no-auto-solve
-    retry_failed: bool | None = None        # true 且 1688_contact → --retry-failed
+    retry_failed: bool | None = None        # 前端 1688_contact 表单开关遗留，不映射 CLI
     # wa_check 专用：
     accounts: list[str] | None = None       # 账号池，空 = 仅默认账号
     # 注：wa_check 复用上方 batch_num（每批调用次数）、
     # sample_min / sample_max（调用间隔范围）三个字段
     # 循环模式：本轮正常结束（done/failed）后 N 秒自动重启；None/<=0 = 不循环
     repeat_interval: int | None = None
 
 
 class TaskCreate(BaseModel):
     type: str = Field(...)
diff --git a/platform/web/src/lib/api.ts b/platform/web/src/lib/api.ts
index b952d12..d6c434d 100644
--- a/platform/web/src/lib/api.ts
+++ b/platform/web/src/lib/api.ts
@@ -81,69 +81,58 @@ export type TaskType =
   | '1688_contact'
   | 'madeinchina_contact'
   | 'madeinchina_shop'
   | 'yiwugo_search'
   | 'wa_check'
 
 // 采集类参数全量可选键：留空即不传，由 CLI 默认值生效。
 // 批次类型（1688/madeinchina 采集 + wa_check）只读 limit / repeat_interval /
 // accounts，其余 daemon 级参数（workers/proxy/节奏等）已收敛到 daemon 启动，
 // 逐任务覆盖取消（SPEC §3.2 用户可见变化）；旧模板多余字段后端忽略。
-// wa_check 使用 limit / accounts / sample_min / sample_max / batch_num /
-// batch_rest_min / batch_rest_max（interval 为旧参数，向后兼容）。
+// wa_check 只使用 limit / accounts；旧模板多余字段后端忽略（加载时忽略未知键）。
 export interface TaskParams {
   batch_num?: number
   limit?: number
   max_batches?: number
   workers?: number
-  channels?: string
+  channels?: number
   batch_rest?: number
   sample_min?: number
   sample_max?: number
   rest_every?: number
   rest_min?: number
   rest_max?: number
   stagger_min?: number
   stagger_max?: number
   ip_retry?: number
   net_retry?: number
   max_consecutive_fail?: number
   block_rest_min?: number
   block_rest_max?: number
   use_proxy?: boolean
   headless?: boolean
   auto_solve?: boolean
-  retry_failed?: boolean // 仅 1688_contact
+  retry_failed?: boolean // 仅 1688_contact；已不映射 CLI（build_command 分支已删），表单开关遗留
   // 任务结束后自动重启的间隔（秒）；0 或不传 = 不循环
   repeat_interval?: number
   // wa_check 专用
-  interval?: number // 旧参数：固定调用间隔（等价 sample_min == sample_max）
   accounts?: string[]
-  batch_rest_min?: number // wa_check 批间休息下限（秒）
-  batch_rest_max?: number // wa_check 批间休息上限（秒）
 }
 
 export interface CreateTaskRequest {
   type: TaskType
   params: TaskParams
 }
 
 export interface TaskPreview {
-  cmd: string[] | null // wa_check 为进程内任务，返回 null
-  cmdline: string // cmd 拼接的命令行，或 wa_check 的说明文案
-}
-
-// 命令解析结果：422 时 request() 抛出带后端 detail 的 ApiError
-export interface TaskParseResult {
-  type: TaskType
-  params: TaskParams
-  warnings: string[]
+  cmd: string[] | null // 批次类型（含 wa_check）返回 null
+  cmdline: string // cmd 拼接的命令行，或批次类型的说明文案
 }
 
 export interface TaskTemplate {
   id: number
   name: string
   type: TaskType
   params: TaskParams
   created_at: string
 }
 
@@ -318,25 +307,20 @@ export const api = {
     if (period === '12h') qs = 'hours=12'
     else if (period === 'custom') qs = `period=custom&start=${encodeURIComponent(start ?? '')}&end=${encodeURIComponent(end ?? '')}`
     else qs = `period=${period}`
     return request<Pipeline>(`/dashboard/pipeline?${qs}`)
   },
   tasks: async () => (await request<unknown[]>('/tasks')).map(normalizeTask),
   createTask: async (body: CreateTaskRequest) =>
     normalizeTask(await request<unknown>('/tasks', { method: 'POST', body: JSON.stringify(body) })),
   previewTask: (body: CreateTaskRequest) =>
     request<TaskPreview>('/tasks/preview', { method: 'POST', body: JSON.stringify(body) }),
-  parseCommand: (command: string) =>
-    request<TaskParseResult>('/tasks/parse', {
-      method: 'POST',
-      body: JSON.stringify({ command }),
-    }),
   putTask: async (id: number, params: TaskParams) =>
     normalizeTask(
       await request<unknown>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify({ params }) })),
   getTask: async (id: number) => normalizeTask(await request<unknown>(`/tasks/${id}`)),
   startTask: (id: number) => request<StartTaskResult>(`/tasks/${id}/start`, { method: 'POST' }),
   stopTask: (id: number) => request<{ ok: boolean }>(`/tasks/${id}/stop`, { method: 'POST' }),
   deleteTask: (id: number) => request<{ ok: boolean }>(`/tasks/${id}`, { method: 'DELETE' }),
   batchTasks: (action: 'start' | 'stop' | 'delete', ids: number[]) =>
     request<TaskBatchResult>('/tasks/batch', {
       method: 'POST',
diff --git a/platform/web/src/pages/tasks/TaskFormDialog.tsx b/platform/web/src/pages/tasks/TaskFormDialog.tsx
index f21175b..4413d01 100644
--- a/platform/web/src/pages/tasks/TaskFormDialog.tsx
+++ b/platform/web/src/pages/tasks/TaskFormDialog.tsx
@@ -17,22 +17,21 @@ import {
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
-import { Textarea } from '@/components/ui/textarea'
-import { ChevronDown, Save, Terminal, Trash2, Wand2 } from 'lucide-react'
+import { ChevronDown, Save, Terminal, Trash2 } from 'lucide-react'
 import { TASK_TYPE_OPTIONS, taskTypeLabel } from './task-ui'
 
 interface NumField {
   key: string
   label: string
   placeholder: string
   hint?: string
 }
 
 // 基础区常用数字参数
@@ -66,21 +65,21 @@ const RETRY_FIELDS: NumField[] = [
 
 // 高级参数：其他（数字类）
 const MISC_NUM_FIELDS: NumField[] = [
   { key: 'repeat_interval', label: '循环间隔（秒）', placeholder: '0 = 不循环，如 1800' },
 ]
 
 const ALL_NUM_KEYS = [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map(
   (f) => f.key,
 )
 
-// 高级区包含的数字键（命令导入 / 模板加载命中时自动展开高级区）
+// 高级区包含的数字键（模板加载命中时自动展开高级区）
 const ADVANCED_NUM_KEYS = [...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map((f) => f.key)
 
 interface TaskFormDialogProps {
   open: boolean
   onOpenChange: (open: boolean) => void
   onSaved: () => void
   task?: Task | null // 传入 = 编辑模式（type 只读，回填 params）
 }
 
 export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDialogProps) {
@@ -91,112 +90,90 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
   const [channels, setChannels] = useState('')
   const [useProxy, setUseProxy] = useState(true)
   const [headless, setHeadless] = useState(true)
   const [autoSolve, setAutoSolve] = useState(true)
   const [retryFailed, setRetryFailed] = useState(false)
   const [advancedOpen, setAdvancedOpen] = useState(false)
   const [submitting, setSubmitting] = useState(false)
 
   // wa_check 专用表单状态
   const [waLimit, setWaLimit] = useState('')
-  const [waSampleMin, setWaSampleMin] = useState('')
-  const [waSampleMax, setWaSampleMax] = useState('')
-  const [waBatchNum, setWaBatchNum] = useState('')
-  const [waRestMin, setWaRestMin] = useState('')
-  const [waRestMax, setWaRestMax] = useState('')
   const [waAccounts, setWaAccounts] = useState<WaAccount[]>([])
   const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])
 
   // P4 批次采集专用：limit（contact=条数、shop/company=页数）
   const [batchLimit, setBatchLimit] = useState('')
 
   // 命令预览
   const [preview, setPreview] = useState<TaskPreview | null>(null)
 
-  // 从命令导入
-  const [importOpen, setImportOpen] = useState(false)
-  const [importText, setImportText] = useState('')
-  const [parsing, setParsing] = useState(false)
-
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
                    'madeinchina_shop', 'madeinchina_contact'].includes(type)
 
   const setValue = (key: string, v: string) =>
     setValues((prev) => ({ ...prev, [key]: v }))
 
-  // 用一组 params 回填整个表单（编辑初始化 / 命令导入 / 模板加载共用）
+  // 用一组 params 回填整个表单（编辑初始化 / 模板加载共用）
   const fillFromParams = (p: Record<string, unknown>) => {
     const next: Record<string, string> = {}
     for (const key of ALL_NUM_KEYS) {
       if (typeof p[key] === 'number') next[key] = String(p[key])
     }
     setValues(next)
-    setChannels(typeof p.channels === 'string' ? (p.channels as string) : '')
+    setChannels(typeof p.channels === 'number' ? String(p.channels) : '')
     setUseProxy(p.use_proxy !== false)
     setHeadless(p.headless !== false)
     setAutoSolve(p.auto_solve !== false)
     setRetryFailed(p.retry_failed === true)
     setWaLimit(typeof p.limit === 'number' ? String(p.limit) : '')
     setBatchLimit(typeof p.limit === 'number' ? String(p.limit) : '')
-    // 节奏参数：sample_min/max 缺省时用旧参数 interval 回填（向后兼容）
-    const legacyInterval = typeof p.interval === 'number' ? String(p.interval) : ''
-    setWaSampleMin(typeof p.sample_min === 'number' ? String(p.sample_min) : legacyInterval)
-    setWaSampleMax(typeof p.sample_max === 'number' ? String(p.sample_max) : legacyInterval)
-    setWaBatchNum(typeof p.batch_num === 'number' ? String(p.batch_num) : '')
-    setWaRestMin(typeof p.batch_rest_min === 'number' ? String(p.batch_rest_min) : '')
-    setWaRestMax(typeof p.batch_rest_max === 'number' ? String(p.batch_rest_max) : '')
+    // wa 表单只保留 limit + accounts：历史任务 params_json 中的旧字段
+    // （batch_num/sample_min/… 等）后端忽略，回填时跳过未知键（SPEC C3）
     setSelectedAccounts(
       Array.isArray(p.accounts)
         ? (p.accounts as unknown[]).filter((a): a is string => typeof a === 'string')
         : [],
     )
     if (ADVANCED_NUM_KEYS.some((k) => typeof p[k] === 'number')) setAdvancedOpen(true)
   }
 
   // 打开时初始化：编辑模式回填 task.params，新建模式重置为空白默认
   useEffect(() => {
     if (!open) return
     setPreview(null)
     setAdvancedOpen(false)
-    setImportOpen(false)
-    setImportText('')
     setTemplateSel('')
     if (task) {
       setType(task.type as TaskType)
       fillFromParams((task.params ?? {}) as Record<string, unknown>)
       setAdvancedOpen(false) // 编辑初始化不强制展开高级区
     } else {
       setType('1688_shop')
       setValues({})
       setChannels('')
       setUseProxy(true)
       setHeadless(true)
       setAutoSolve(true)
       setRetryFailed(false)
       setWaLimit('')
-      setWaSampleMin('')
-      setWaSampleMax('')
-      setWaBatchNum('')
-      setWaRestMin('')
-      setWaRestMax('')
       setSelectedAccounts([])
     }
     // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [open, task])
 
   // 打开时拉取模板列表
   useEffect(() => {
     if (!open) return
     api.getTaskTemplates()
       .then(setTemplates)
@@ -227,66 +204,54 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
       }
       const riRaw = (values.repeat_interval ?? '').trim()
       const riN = Number(riRaw)
       if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
       return params
     }
     if (isWaCheck) {
       const params: TaskParams = { accounts: selectedAccounts }
       const limitN = Number(waLimit)
       if (waLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) params.limit = limitN
-      const numOrUndef = (raw: string): number | undefined => {
-        if (raw.trim() === '') return undefined
-        const n = Number(raw)
-        return Number.isFinite(n) && n >= 0 ? n : undefined
-      }
-      const sampleMin = numOrUndef(waSampleMin)
-      if (sampleMin !== undefined) params.sample_min = sampleMin
-      const sampleMax = numOrUndef(waSampleMax)
-      if (sampleMax !== undefined) params.sample_max = sampleMax
-      const batchNum = numOrUndef(waBatchNum)
-      if (batchNum !== undefined && Number.isInteger(batchNum)) params.batch_num = batchNum
-      const restMin = numOrUndef(waRestMin)
-      if (restMin !== undefined) params.batch_rest_min = restMin
-      const restMax = numOrUndef(waRestMax)
-      if (restMax !== undefined) params.batch_rest_max = restMax
-      // 循环间隔：由命令导入 / 模板回填时透传（wa 表单不展示该字段）
+      // 循环间隔：由模板回填时透传（wa 表单不展示该字段）
       const riRaw = (values.repeat_interval ?? '').trim()
       const riN = Number(riRaw)
       if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
       return params
     }
     const params: TaskParams = { use_proxy: useProxy, headless, auto_solve: autoSolve }
     for (const key of ALL_NUM_KEYS) {
       const raw = (values[key] ?? '').trim()
       if (raw === '') continue
       const n = Number(raw)
       if (!Number.isInteger(n) || n < 0) continue
       if (key === 'repeat_interval' && n === 0) continue // 0 = 不循环，不传
       ;(params as Record<string, unknown>)[key] = n
     }
-    if (channels.trim() !== '') params.channels = channels.trim()
+    // 后端 channels 为 int（代理通道 id）：非空才转 Number 提交，NaN 丢弃
+    const channelsRaw = channels.trim()
+    if (channelsRaw !== '') {
+      const channelsN = Number(channelsRaw)
+      if (Number.isFinite(channelsN)) params.channels = channelsN
+    }
     if (retryFailed && type === '1688_contact') params.retry_failed = true
     return params
   }
 
   // 参数签名：内容变化时触发防抖预览
   const paramsKey = useMemo(
     () =>
       JSON.stringify({
         type, values, channels, useProxy, headless, autoSolve, retryFailed,
-        waLimit, waSampleMin, waSampleMax, waBatchNum, waRestMin, waRestMax,
-        selectedAccounts,
+        waLimit, selectedAccounts,
       }),
     [type, values, channels, useProxy, headless, autoSolve, retryFailed,
-      waLimit, waSampleMin, waSampleMax, waBatchNum, waRestMin, waRestMax,
-      selectedAccounts],
+      waLimit, selectedAccounts],
   )
 
   // 命令预览：防抖 500ms 调 preview 接口，失败静默不阻塞
   useEffect(() => {
     if (!open) return
     const timer = setTimeout(() => {
       api.previewTask({ type, params: buildParams() })
         .then((res) => setPreview(res))
         .catch(() => setPreview(null))
     }, 500)
@@ -307,45 +272,20 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
       return true
     }
     if (isWaCheck) {
       if (waLimit.trim() !== '') {
         const n = Number(waLimit)
         if (!Number.isInteger(n) || n < 0) {
           toast.error('查号上限需为不小于 0 的整数（0 = 全部未查）')
           return false
         }
       }
-      const ranges: [string, string, string][] = [
-        ['查号间隔', waSampleMin, waSampleMax],
-        ['批间休息', waRestMin, waRestMax],
-      ]
-      for (const [label, loRaw, hiRaw] of ranges) {
-        for (const [side, raw] of [['下限', loRaw], ['上限', hiRaw]] as const) {
-          if (raw.trim() === '') continue
-          const n = Number(raw)
-          if (!Number.isFinite(n) || n < 0) {
-            toast.error(`${label}${side}需为不小于 0 的数字（秒）`)
-            return false
-          }
-        }
-        if (loRaw.trim() !== '' && hiRaw.trim() !== '' && Number(loRaw) > Number(hiRaw)) {
-          toast.error(`${label}下限不能大于上限`)
-          return false
-        }
-      }
-      if (waBatchNum.trim() !== '') {
-        const n = Number(waBatchNum)
-        if (!Number.isInteger(n) || n < 0) {
-          toast.error('每批查号数量需为不小于 0 的整数（0 = 不分批）')
-          return false
-        }
-      }
       return true
     }
     for (const f of [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS]) {
       const raw = (values[f.key] ?? '').trim()
       if (raw === '') continue
       const n = Number(raw)
       if (!Number.isInteger(n) || n < 0) {
         toast.error(`「${f.label}」需为不小于 0 的整数，或留空使用默认值`)
         return false
       }
@@ -377,56 +317,35 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
         toast.warning('任务状态已变化，当前状态不允许修改参数')
         onSaved() // 刷新列表反映最新状态
       } else {
         toast.error(e instanceof Error ? e.message : editing ? '保存参数失败' : '创建任务失败')
       }
     } finally {
       setSubmitting(false)
     }
   }
 
-  // 编辑模式类型只读：导入 / 模板类型与当前任务不同时忽略 type，仅回填参数
+  // 编辑模式类型只读：模板类型与当前任务不同时忽略 type，仅回填参数
   const applyImportedType = (incoming: TaskType): boolean => {
     if (!editing) {
       setType(incoming)
       return true
     }
     if (incoming !== task.type) {
       toast.info(
         `类型不可修改，已忽略「${taskTypeLabel(incoming)}」，仅回填参数`,
       )
       return false
     }
     return true
   }
 
-  // 从命令导入：调 parse 接口，成功回填 type + 全部参数
-  const handleParse = async () => {
-    const command = importText.trim()
-    if (command === '') {
-      toast.warning('请先粘贴命令')
-      return
-    }
-    setParsing(true)
-    try {
-      const res = await api.parseCommand(command)
-      const applied = applyImportedType(res.type)
-      fillFromParams((res.params ?? {}) as Record<string, unknown>)
-      for (const w of res.warnings ?? []) toast.warning(w)
-      toast.success(applied ? '命令解析成功，已回填类型与参数' : '命令解析成功，已回填参数')
-    } catch (e) {
-      toast.error(e instanceof Error ? e.message : '命令解析失败')
-    } finally {
-      setParsing(false)
-    }
-  }
-
   // 从模板加载：选中即回填
   const handleLoadTemplate = (idStr: string) => {
     setTemplateSel('') // 加载动作而非选中态，复位占位
     const tpl = templates.find((t) => String(t.id) === idStr)
     if (!tpl) return
     applyImportedType(tpl.type)
     fillFromParams((tpl.params ?? {}) as Record<string, unknown>)
     toast.success(`已加载模板「${tpl.name}」`)
   }
 
@@ -500,50 +419,20 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
         <DialogHeader>
           <DialogTitle>{editing ? `编辑任务 #${task.id} 参数` : '新建任务'}</DialogTitle>
           <DialogDescription>
             {editing
               ? '任务类型不可修改；留空的参数将使用 CLI 默认值。'
               : '选择任务类型并配置参数，留空即使用 CLI 默认值，创建后进入排队。'}
           </DialogDescription>
         </DialogHeader>
 
         <div className="space-y-4">
-          {/* 从命令导入：折叠区 */}
-          <Collapsible open={importOpen} onOpenChange={setImportOpen}>
-            <CollapsibleTrigger asChild>
-              <Button variant="outline" size="sm" className="w-full justify-between">
-                <span className="flex items-center gap-1.5">
-                  <Wand2 className="h-3.5 w-3.5" />
-                  从命令导入
-                </span>
-                <ChevronDown
-                  className={`h-4 w-4 transition-transform ${importOpen ? 'rotate-180' : ''}`}
-                />
-              </Button>
-            </CollapsibleTrigger>
-            <CollapsibleContent className="space-y-2 pt-2">
-              <Textarea
-                value={importText}
-                onChange={(e) => setImportText(e.target.value)}
-                placeholder="python -m fetcher 1688 company --proxy --headed -n 50 --worker 1"
-                rows={3}
-                className="font-mono text-xs"
-              />
-              <p className="text-xs text-muted-foreground">
-                支持 while 循环 + sleep 写法（解析为循环间隔）
-              </p>
-              <Button size="sm" onClick={handleParse} disabled={parsing}>
-                {parsing ? '解析中…' : '解析'}
-              </Button>
-            </CollapsibleContent>
-          </Collapsible>
-
           {/* 从模板加载 */}
           <div className="space-y-2">
             <Label>从模板加载</Label>
             <div className="flex gap-2">
               <Select value={templateSel} onValueChange={handleLoadTemplate}>
                 <SelectTrigger className="flex-1">
                   <SelectValue
                     placeholder={templates.length > 0 ? '选择模板，立即回填表单' : '暂无已保存模板'}
                   />
                 </SelectTrigger>
@@ -621,104 +510,32 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
                 <p className="text-xs text-muted-foreground">
                   批次跑完后 N 秒自动重启同参数批次（0 = 不循环）
                 </p>
               </div>
               <p className="text-xs text-muted-foreground">
                 节奏/代理/并发已收敛到 daemon 启动参数，不再逐任务下发。
               </p>
             </>
           ) : isWaCheck ? (
             <>
-              <div className="grid grid-cols-2 gap-3">
-                <div className="space-y-2">
-                  <Label htmlFor="wa-limit">查号上限</Label>
-                  <Input
-                    id="wa-limit"
-                    type="number"
-                    min={0}
-                    value={waLimit}
-                    placeholder="0 = 全部未查"
-                    onChange={(e) => setWaLimit(e.target.value)}
-                  />
-                  <p className="text-xs text-muted-foreground">0 = 全部未查</p>
-                </div>
-                <div className="space-y-2">
-                  <Label htmlFor="wa-batch-num">每批查号数量（个）</Label>
-                  <Input
-                    id="wa-batch-num"
-                    type="number"
-                    min={0}
-                    value={waBatchNum}
-                    placeholder="默认 500"
-                    onChange={(e) => setWaBatchNum(e.target.value)}
-                  />
-                  <p className="text-xs text-muted-foreground">默认 500 个号码/批，0 = 不分批</p>
-                </div>
-              </div>
-
-              <div className="grid grid-cols-2 gap-3">
-                <div className="space-y-2">
-                  <Label htmlFor="wa-sample-min">查号间隔下限（秒）</Label>
-                  <Input
-                    id="wa-sample-min"
-                    type="number"
-                    min={0}
-                    step={0.5}
-                    value={waSampleMin}
-                    placeholder="默认 1.5"
-                    onChange={(e) => setWaSampleMin(e.target.value)}
-                  />
-                </div>
-                <div className="space-y-2">
-                  <Label htmlFor="wa-sample-max">查号间隔上限（秒）</Label>
-                  <Input
-                    id="wa-sample-max"
-                    type="number"
-                    min={0}
-                    step={0.5}
-                    value={waSampleMax}
-                    placeholder="默认 1.5"
-                    onChange={(e) => setWaSampleMax(e.target.value)}
-                  />
-                </div>
-              </div>
-              <p className="-mt-1.5 text-xs text-muted-foreground">
-                每个号码查询之间随机停顿，上下限相等 = 固定间隔
-              </p>
-
-              <div className="grid grid-cols-2 gap-3">
-                <div className="space-y-2">
-                  <Label htmlFor="wa-rest-min">批间休息下限（秒）</Label>
-                  <Input
-                    id="wa-rest-min"
-                    type="number"
-                    min={0}
-                    value={waRestMin}
-                    placeholder="默认 60"
-                    onChange={(e) => setWaRestMin(e.target.value)}
-                  />
-                </div>
-                <div className="space-y-2">
-                  <Label htmlFor="wa-rest-max">批间休息上限（秒）</Label>
-                  <Input
-                    id="wa-rest-max"
-                    type="number"
-                    min={0}
-                    value={waRestMax}
-                    placeholder="默认 180"
-                    onChange={(e) => setWaRestMax(e.target.value)}
-                  />
-                </div>
+              <div className="max-w-xs space-y-2">
+                <Label htmlFor="wa-limit">查号上限</Label>
+                <Input
+                  id="wa-limit"
+                  type="number"
+                  min={0}
+                  value={waLimit}
+                  placeholder="0 = 全部未查"
+                  onChange={(e) => setWaLimit(e.target.value)}
+                />
+                <p className="text-xs text-muted-foreground">0 = 全部未查</p>
               </div>
-              <p className="-mt-1.5 text-xs text-muted-foreground">
-                每采满一批后随机长休息（防风控），随后自动开始下一批
-              </p>
 
               <div className="space-y-2 rounded-md border border-border px-3 py-2">
                 <Label>查号账号</Label>
                 {waAccounts.length === 0 ? (
                   <p className="text-xs text-muted-foreground">
                     暂无已登录账号，将使用默认账号
                   </p>
                 ) : (
                   <div className="space-y-2">
                     {waAccounts.map((a) => (
@@ -807,21 +624,21 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
                           onCheckedChange={setRetryFailed}
                         />
                       </div>
                     )}
                   </div>
                 </CollapsibleContent>
               </Collapsible>
             </>
           )}
 
-          {/* 命令预览：wa_check 返回 cmd=null + 说明文案 */}
+          {/* 命令预览：批次类型（含 wa_check）返回 cmd=null + 批次文案 */}
           <div className="space-y-1.5">
             <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
               <Terminal className="h-3.5 w-3.5" />
               命令预览
             </div>
             <div className="min-h-12 rounded-md border border-border bg-muted/50 px-3 py-2">
               {preview ? (
                 <code className="block whitespace-pre-wrap break-all font-mono text-xs text-foreground">
                   {preview.cmdline}
                 </code>
diff --git a/platform/web/src/pages/tasks/task-ui.tsx b/platform/web/src/pages/tasks/task-ui.tsx
index 8f1e886..c8aa31e 100644
--- a/platform/web/src/pages/tasks/task-ui.tsx
+++ b/platform/web/src/pages/tasks/task-ui.tsx
@@ -117,50 +117,35 @@ export function eventWorker(ev: { message: string; data?: { worker?: number | st
 
 // 秒数人性化：>=3600 显小时、>=60 显分钟、否则显秒（最多 1 位小数）
 function humanizeSeconds(sec: number): string {
   const trim = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))
   if (sec >= 3600) return `${trim(sec / 3600)}小时`
   if (sec >= 60) return `${trim(sec / 60)}分钟`
   return `${sec}秒`
 }
 
 // 任务参数摘要：表格 params 列的小字展示
-// 采集类示例：n=10 批=4 代理 无头 循环30分钟；wa_check：上限=500 间隔=2~5s 批=10次
+// 采集类示例：n=10 批=4 代理 无头 循环30分钟；wa_check：上限=500 账号=xiaohao-1
+// 批次类型：上限=200 循环30分钟
 export function paramsSummary(task: { type: string; params: Record<string, unknown> }): string {
   const p = task.params ?? {}
   const num = (k: string): number | null =>
     typeof p[k] === 'number' && Number.isFinite(p[k] as number) ? (p[k] as number) : null
   const repeat = num('repeat_interval')
   const repeatPart = repeat !== null && repeat > 0 ? `循环${humanizeSeconds(repeat)}` : null
-  const range = (loK: string, hiK: string): string | null => {
-    const lo = num(loK)
-    const hi = num(hiK)
-    if (lo === null && hi === null) return null
-    if (lo !== null && hi !== null) return lo === hi ? `${lo}` : `${lo}~${hi}`
-    return `${lo ?? ''}~${hi ?? ''}`
-  }
 
   if (task.type === 'wa_check') {
     const parts: string[] = []
     const limit = num('limit')
     if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '全部未查')
     const accs = Array.isArray(p.accounts) ? (p.accounts as unknown[]).filter((a) => typeof a === 'string') : []
     if (accs.length > 0) parts.push(`账号=${accs.join(',')}`)
-    const interval = num('interval') // 旧参数：固定间隔
-    const sample = range('sample_min', 'sample_max')
-    if (sample !== null) parts.push(`间隔=${sample}s`)
-    else if (interval !== null) parts.push(`间隔=${interval}s`)
-    const batchNum = num('batch_num')
-    const rest = range('batch_rest_min', 'batch_rest_max')
-    if (batchNum !== null && batchNum > 0) {
-      parts.push(`批=${batchNum}个` + (rest !== null ? `·休${rest}s` : ''))
-    }
     if (repeatPart) parts.push(repeatPart)
     return parts.length > 0 ? parts.join(' ') : '默认参数'
   }
 
   // P4 批次采集类型（1688/madeinchina shop/company/contact）：
   // 只读 limit（contact=条数、shop/company=页数）+ repeat_interval
   const BATCH_TYPES = new Set(['1688_shop', '1688_company', '1688_contact',
                                'madeinchina_shop', 'madeinchina_contact'])
   if (BATCH_TYPES.has(task.type)) {
     const parts: string[] = []
@@ -175,14 +160,13 @@ export function paramsSummary(task: { type: string; params: Record<string, unkno
   if (batchNum !== null) parts.push(`n=${batchNum}`)
   const maxBatches = num('max_batches')
   if (maxBatches !== null) parts.push(maxBatches > 0 ? `批=${maxBatches}` : '批=∞')
   const limit = num('limit')
   if (limit !== null && limit > 0) parts.push(`上限=${limit}`)
   const workers = num('workers')
   if (workers !== null) parts.push(`w=${workers}`)
   if (p.use_proxy === true) parts.push('代理')
   if (p.headless === true) parts.push('无头')
   else if (p.headless === false) parts.push('有头')
-  if (p.retry_failed === true) parts.push('重试失败')
   if (repeatPart) parts.push(repeatPart)
   return parts.length > 0 ? parts.join(' ') : '默认参数'
 }
