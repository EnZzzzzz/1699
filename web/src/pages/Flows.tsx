import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { createFlowTask, errorMessage, flowApi, getAtomCatalog, isNotImplemented } from '@/api/client'
import type { AtomSpec, Dag, DagRunInput, DagValidation, Flow, FlowDetail } from '@/api/types'
import { EmptyState, NotImplementedState } from '@/components/EmptyState'
import { FlowCanvas } from '@/components/canvas/FlowCanvas'
import { FlowEditor } from '@/components/FlowEditor'
import { FlowCanvasEditor } from '@/components/FlowCanvasEditor'
import { toast } from 'sonner'
import { Plus, RefreshCw, Play, Eye, Copy, Trash2, Loader2, Pencil, CopyPlus } from 'lucide-react'

export default function Flows() {
  const [flows, setFlows] = useState<Flow[]>([])
  const [loading, setLoading] = useState(true)
  const [notImpl, setNotImpl] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [runTarget, setRunTarget] = useState<Flow | null>(null)
  const [viewTarget, setViewTarget] = useState<Flow | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Flow | null>(null)
  const [deleting, setDeleting] = useState(false)
  // 编辑器状态：flowId=null 为新建；mode 默认画布（表单为兜底）
  const [editor, setEditor] = useState<{ flowId: number | null; mode: 'canvas' | 'form' } | null>(null)
  const [duplicatingForEdit, setDuplicatingForEdit] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      const list = await flowApi.list()
      setFlows(list)
      setNotImpl(false)
      setError(null)
    } catch (e) {
      if (isNotImplemented(e)) {
        setNotImpl(true)
      } else {
        setError(errorMessage(e))
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const doDuplicate = async (f: Flow) => {
    try {
      const dup = await flowApi.duplicate(f.id)
      toast.success(`已复制为「${dup.name}」`)
      void load()
    } catch (e) {
      toast.error(`复制失败：${errorMessage(e)}`)
    }
  }

  /** 内置模板为只读：复制副本后打开副本的编辑器 */
  const duplicateThenEdit = async (f: Flow) => {
    setDuplicatingForEdit(f.id)
    try {
      const dup = await flowApi.duplicate(f.id)
      toast.info(`内置模板为只读，已创建副本「${dup.name}」，正在编辑副本`)
      setEditor({ flowId: dup.id, mode: 'canvas' })
      void load()
    } catch (e) {
      toast.error(`复制失败：${errorMessage(e)}`)
    } finally {
      setDuplicatingForEdit(null)
    }
  }

  const doDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await flowApi.remove(deleteTarget.id)
      toast.success(`已删除模板「${deleteTarget.name}」`)
      setDeleteTarget(null)
      void load()
    } catch (e) {
      // builtin（400）/ 被任务引用（409）时展示后端原始错误信息
      toast.error(errorMessage(e), { duration: 8000 })
    } finally {
      setDeleting(false)
    }
  }

  if (loading) return <div className="py-20 text-center text-muted-foreground">加载中…</div>

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">流水线</h1>
          <p className="mt-1 text-sm text-muted-foreground">原子能力 + DAG 编排的任务模板，选模板补运行时变量一键运行</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          {!notImpl && (
            <Button size="sm" onClick={() => setEditor({ flowId: null, mode: 'canvas' })}>
              <Plus className="mr-2 h-4 w-4" />
              新建模板
            </Button>
          )}
        </div>
      </div>

      {notImpl ? (
        <NotImplementedState feature="流水线" />
      ) : error ? (
        <EmptyState icon="error" title="无法获取流水线模板" description={error} actionLabel="重试" onAction={() => void load()} />
      ) : flows.length === 0 ? (
        <EmptyState
          title="暂无流水线模板"
          description="点击右上角「新建模板」，或等待后端初始化内置模板"
          actionLabel="新建模板"
          onAction={() => setEditor({ flowId: null, mode: 'canvas' })}
        />
      ) : (
        <div className="rounded-lg border bg-background">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>名称</TableHead>
                <TableHead className="hidden md:table-cell">描述</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {flows.map((f) => (
                <TableRow key={f.id}>
                  <TableCell className="font-mono text-muted-foreground">#{f.id}</TableCell>
                  <TableCell>
                    <span className="font-medium">{f.name}</span>
                    {f.builtin && (
                      <Badge variant="secondary" className="ml-2">
                        内置
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="hidden max-w-md truncate text-sm text-muted-foreground md:table-cell">
                    {f.description ?? '-'}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{f.updated_at}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1.5">
                      <Button size="sm" onClick={() => setRunTarget(f)}>
                        <Play className="mr-1 h-3.5 w-3.5" />
                        运行
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => setViewTarget(f)}>
                        <Eye className="mr-1 h-3.5 w-3.5" />
                        查看
                      </Button>
                      {f.builtin ? (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={duplicatingForEdit === f.id}
                          onClick={() => void duplicateThenEdit(f)}
                        >
                          <CopyPlus className="mr-1 h-3.5 w-3.5" />
                          {duplicatingForEdit === f.id ? '复制中…' : '复制并编辑'}
                        </Button>
                      ) : (
                        <Button variant="outline" size="sm" onClick={() => setEditor({ flowId: f.id, mode: 'canvas' })}>
                          <Pencil className="mr-1 h-3.5 w-3.5" />
                          编辑
                        </Button>
                      )}
                      <Button variant="outline" size="sm" onClick={() => void doDuplicate(f)}>
                        <Copy className="mr-1 h-3.5 w-3.5" />
                        复制
                      </Button>
                      {!f.builtin && (
                        <Button variant="destructive" size="sm" onClick={() => setDeleteTarget(f)}>
                          <Trash2 className="mr-1 h-3.5 w-3.5" />
                          删除
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <RunFlowDialog flow={runTarget} onClose={() => setRunTarget(null)} />
      <FlowViewSheet flow={viewTarget} onClose={() => setViewTarget(null)} />
      {/* 画布模式编辑器（默认）：新建=空 DAG，编辑=加载 FlowDetail */}
      <FlowCanvasEditor
        open={editor?.mode === 'canvas'}
        flowId={editor?.flowId ?? null}
        onSwitchToForm={() => setEditor((e) => (e ? { ...e, mode: 'form' } : e))}
        onClose={() => setEditor(null)}
        onSaved={() => void load()}
      />
      {/* 表单兜底：新建=JSON 对话框，编辑=FlowEditor（行为不变） */}
      <NewFlowDialog
        open={editor?.mode === 'form' && editor.flowId == null}
        onOpenChange={(v) => !v && setEditor(null)}
        onCreated={() => void load()}
      />
      <FlowEditor
        flowId={editor?.mode === 'form' ? editor.flowId : null}
        onClose={() => setEditor(null)}
        onSaved={() => void load()}
      />

      <AlertDialog open={deleteTarget != null} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除流水线模板</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除「{deleteTarget?.name}」？被历史任务引用的模板会被后端拒绝删除（保留可追溯性）。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleting}
              onClick={(e) => {
                e.preventDefault()
                void doDelete()
              }}
            >
              {deleting ? '删除中…' : '确认删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// ---------- 运行：按 dag.run_inputs 动态生成表单 ----------

function RunFlowDialog({ flow, onClose }: { flow: Flow | null; onClose: () => void }) {
  const navigate = useNavigate()
  const [detail, setDetail] = useState<FlowDetail | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!flow) {
      setDetail(null)
      return
    }
    let cancelled = false
    flowApi
      .get(flow.id)
      .then((d) => {
        if (cancelled) return
        setDetail(d)
        const init: Record<string, unknown> = {}
        for (const [k, spec] of Object.entries(d.dag.run_inputs ?? {})) init[k] = spec.default
        setValues(init)
      })
      .catch((e) => toast.error(`加载模板失败：${errorMessage(e)}`))
    return () => {
      cancelled = true
    }
  }, [flow])

  const submit = async () => {
    if (!flow) return
    setSubmitting(true)
    try {
      const data = await createFlowTask(flow.id, values)
      if (data.warning) {
        toast.warning(data.warning, { duration: 12000 })
      } else if (data.dispatched === false) {
        toast.warning('任务已创建，但 celery 派发失败，将滞留在待启动状态', { duration: 12000 })
      } else {
        toast.success(`流水线任务 #${data.id} 已创建`)
      }
      onClose()
      navigate(`/tasks/${data.id}`)
    } catch (e) {
      toast.error(`创建失败：${errorMessage(e)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const runInputs = detail?.dag.run_inputs ?? {}

  return (
    <Dialog open={flow != null} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>运行流水线</DialogTitle>
          <DialogDescription>{flow?.name} —— 按模板声明的运行时变量补参数</DialogDescription>
        </DialogHeader>

        {detail == null ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            模板加载中…
          </div>
        ) : Object.keys(runInputs).length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">该模板无需运行时参数，直接启动即可。</p>
        ) : (
          <div className="space-y-3 py-2">
            {Object.entries(runInputs).map(([key, spec]) => (
              <RunInputField
                key={key}
                name={key}
                spec={spec}
                value={values[key]}
                onChange={(v) => setValues((prev) => ({ ...prev, [key]: v }))}
              />
            ))}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button onClick={() => void submit()} disabled={submitting || detail == null}>
            {submitting ? '创建中…' : '创建并运行'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RunInputField({
  name,
  spec,
  value,
  onChange,
}: {
  name: string
  spec: DagRunInput
  value: unknown
  onChange: (v: unknown) => void
}) {
  const changed = value !== undefined && value !== spec.default
  return (
    <div className="grid gap-1.5">
      <Label className={changed ? 'text-amber-600' : undefined}>
        {changed && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-500 align-middle" />}
        {spec.label ?? name}
        <span className="ml-1.5 font-mono text-xs font-normal text-muted-foreground">{name}</span>
      </Label>
      {spec.type === 'bool' ? (
        <div className="flex h-9 items-center rounded-md border px-3">
          <Switch checked={Boolean(value)} onCheckedChange={onChange} />
          <span className="ml-2 text-sm text-muted-foreground">{value ? '是' : '否'}</span>
        </div>
      ) : (
        <Input
          type={spec.type === 'int' ? 'number' : 'text'}
          step={1}
          value={value === undefined || value === null ? '' : String(value)}
          onChange={(e) =>
            onChange(spec.type === 'int' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)
          }
        />
      )}
    </div>
  )
}

// ---------- 查看：抽屉展示只读画板（FlowCanvas readonly，可缩放/拖动查看） ----------

function FlowViewSheet({
  flow,
  onClose,
}: {
  flow: Flow | null
  onClose: () => void
}) {
  const [detail, setDetail] = useState<FlowDetail | null>(null)
  const [atomSpecs, setAtomSpecs] = useState<AtomSpec[]>([])

  useEffect(() => {
    if (!flow) {
      setDetail(null)
      return
    }
    let cancelled = false
    Promise.all([
      flowApi.get(flow.id),
      getAtomCatalog().catch(() => [] as AtomSpec[]), // 原子目录失败不阻塞，退回注册名
    ])
      .then(([d, specs]) => {
        if (cancelled) return
        setDetail(d)
        setAtomSpecs(specs)
      })
      .catch((e) => toast.error(`加载模板失败：${errorMessage(e)}`))
    return () => {
      cancelled = true
    }
  }, [flow])

  return (
    <Sheet open={flow != null} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-[92vw]">
        <SheetHeader>
          <SheetTitle>
            {flow?.name}
            {flow?.builtin && (
              <Badge variant="secondary" className="ml-2 align-middle">
                内置
              </Badge>
            )}
          </SheetTitle>
          <SheetDescription>{flow?.description ?? '只读画板视图（可缩放 / 拖动查看）'}</SheetDescription>
        </SheetHeader>
        <div className="mt-6 px-1">
          {detail == null ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              模板加载中…
            </div>
          ) : (
            <>
              {detail.dag.resources && detail.dag.resources.length > 0 && (
                <p className="mb-3 text-xs text-muted-foreground">
                  资源声明：{detail.dag.resources.join('、')}（引擎统一申请 / 释放）
                </p>
              )}
              <FlowCanvas dag={detail.dag} atomSpecs={atomSpecs} readonly className="h-[70vh] w-full rounded-lg border bg-slate-50" />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

// ---------- 新建模板：DAG JSON + 校验（高级用户，UI 从简） ----------

const DAG_PLACEHOLDER = `{
  "version": 1,
  "resources": ["channel", "browser"],
  "run_inputs": {
    "limit": { "type": "int", "default": 0, "label": "本次最多抓取" }
  },
  "nodes": [
    { "id": "start_delay", "atom": "sleep", "params": { "min": 0, "max": 0 } },
    { "id": "acquire", "atom": "acquire_channel", "params": { "n": 1, "proxy": true } },
    { "id": "browser", "atom": "launch_browser", "params": { "headed": false } }
  ]
}`

function NewFlowDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [dagText, setDagText] = useState(DAG_PLACEHOLDER)
  const [validation, setValidation] = useState<DagValidation | null>(null)
  const [validatedText, setValidatedText] = useState<string | null>(null) // 校验通过时对应的文本
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)

  // 文本变动后需重新校验
  const dirty = validatedText !== dagText
  const canSave = !dirty && validation?.ok === true && name.trim().length > 0

  useEffect(() => {
    if (!open) return
    setName('')
    setDescription('')
    setDagText(DAG_PLACEHOLDER)
    setValidation(null)
    setValidatedText(null)
  }, [open])

  const parsedDag = useMemo((): { dag?: unknown; error?: string } => {
    try {
      return { dag: JSON.parse(dagText) as unknown }
    } catch (e) {
      return { error: e instanceof Error ? e.message : 'JSON 解析失败' }
    }
  }, [dagText])

  const doValidate = async () => {
    if (parsedDag.error) {
      toast.error(`JSON 语法错误：${parsedDag.error}`)
      return
    }
    setValidating(true)
    try {
      const v = await flowApi.validate(parsedDag.dag)
      setValidation(v)
      if (v.ok) setValidatedText(dagText)
      if (v.errors.length > 0) toast.error(`校验未通过：${v.errors.length} 个错误`)
      else if (v.warnings.length > 0) toast.warning(`校验通过，有 ${v.warnings.length} 条警告`)
      else toast.success('DAG 校验通过')
    } catch (e) {
      toast.error(`校验请求失败：${errorMessage(e)}`)
    } finally {
      setValidating(false)
    }
  }

  const doSave = async () => {
    if (parsedDag.error || parsedDag.dag === undefined) return
    setSaving(true)
    try {
      const created = await flowApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
        dag: parsedDag.dag as Dag,
      })
      toast.success(`模板「${created.name}」已创建`)
      onOpenChange(false)
      onCreated()
    } catch (e) {
      // 后端 400 detail 为 {errors, warnings} 结构，逐条展示
      const detail =
        axios.isAxiosError(e) && e.response?.data && typeof e.response.data === 'object'
          ? (e.response.data as { detail?: unknown }).detail
          : undefined
      if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        const d = detail as { errors?: string[]; warnings?: string[] }
        setValidation({ ok: false, errors: d.errors ?? ['保存被拒绝'], warnings: d.warnings ?? [] })
        toast.error('保存失败：DAG 校验未通过')
      } else {
        toast.error(`保存失败：${errorMessage(e)}`)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>新建流水线模板</DialogTitle>
          <DialogDescription>面向高级用户：直接编辑 DAG JSON，保存前必须通过校验</DialogDescription>
        </DialogHeader>

        <div className="-mr-2 flex-1 space-y-3 overflow-y-auto py-2 pr-2">
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label>名称</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：联系人提取·激进版" />
            </div>
            <div className="grid gap-1.5">
              <Label>描述（可选）</Label>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="模板用途说明" />
            </div>
          </div>

          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <Label>DAG JSON</Label>
              <Button variant="outline" size="sm" onClick={() => void doValidate()} disabled={validating || !!parsedDag.error}>
                {validating ? '校验中…' : '校验'}
              </Button>
            </div>
            <Textarea
              value={dagText}
              onChange={(e) => setDagText(e.target.value)}
              className="min-h-72 font-mono text-xs"
              spellCheck={false}
            />
            {parsedDag.error && <p className="text-xs text-red-600">JSON 语法错误：{parsedDag.error}</p>}
            {dirty && validation != null && <p className="text-xs text-amber-600">DAG 已修改，需重新校验后才能保存</p>}
          </div>

          {validation && (
            <div className="space-y-2 rounded-md border p-3 text-xs">
              {validation.errors.length === 0 ? (
                <p className="font-medium text-emerald-600">校验通过{dirty ? '（内容已变更，需重新校验）' : ''}</p>
              ) : (
                <div>
                  <p className="font-medium text-red-600">{validation.errors.length} 个错误：</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-red-600">
                    {validation.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
              {validation.warnings.length > 0 && (
                <div>
                  <p className="font-medium text-amber-600">{validation.warnings.length} 条警告：</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-amber-600">
                    {validation.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            取消
          </Button>
          <Button onClick={() => void doSave()} disabled={!canSave || saving}>
            {saving ? '保存中…' : '保存模板'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
