import { Fragment, useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { errorMessage, flowApi, getAtomCatalog } from '@/api/client'
import type { AtomSpec, Dag, DagNode, DagValidation, FlowDetail } from '@/api/types'
import { toast } from 'sonner'
import { ChevronDown, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * 流水线模板编辑器（v1）：垂直节点列表 + 按原子 param_spec 动态生成的参数表单。
 * - 节点 params 中的 "${xxx}" 引用 run_inputs，渲染为只读徽标，保存时原样保留
 * - 策略区：on_<outcome> 只改 retry（do 只读）；circuit_breaker 只改 consecutive_fail
 * - 容器节点（body）递归渲染嵌套卡片；run_inputs 定义本身只读
 * - 保存前强制走 /api/flows/validate，errors 不通过不提交
 */
export function FlowEditor({
  flowId,
  onClose,
  onSaved,
}: {
  /** 打开编辑器的模板 id；null = 关闭 */
  flowId: number | null
  onClose: () => void
  onSaved: () => void
}) {
  const [detail, setDetail] = useState<FlowDetail | null>(null)
  const [atoms, setAtoms] = useState<AtomSpec[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [nodes, setNodes] = useState<DagNode[]>([])
  const [validation, setValidation] = useState<DagValidation | null>(null)
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (flowId == null) {
      setDetail(null)
      setValidation(null)
      return
    }
    let cancelled = false
    Promise.all([flowApi.get(flowId), getAtomCatalog()])
      .then(([d, catalog]) => {
        if (cancelled) return
        setDetail(d)
        setAtoms(catalog)
        setName(d.name)
        setDescription(d.description ?? '')
        setNodes(structuredClone(d.dag.nodes ?? []))
        setValidation(null)
      })
      .catch((e) => toast.error(`加载模板失败：${errorMessage(e)}`))
    return () => {
      cancelled = true
    }
  }, [flowId])

  const atomOf = useCallback(
    (atomName: string): AtomSpec | undefined => atoms.find((a) => a.name === atomName),
    [atoms],
  )
  const titleOf = useCallback((atomName: string) => atomOf(atomName)?.title ?? atomName, [atomOf])

  /** 组装当前编辑态为完整 DAG（nodes 之外的字段原样保留） */
  const assemble = useCallback((): Dag | null => {
    if (!detail) return null
    return { ...detail.dag, nodes }
  }, [detail, nodes])

  const setNode = (index: number, next: DagNode) =>
    setNodes((prev) => prev.map((n, i) => (i === index ? next : n)))

  const doValidate = useCallback(async (): Promise<DagValidation | null> => {
    const dag = assemble()
    if (!dag) return null
    setValidating(true)
    try {
      const v = await flowApi.validate(dag)
      setValidation(v)
      if (v.errors.length > 0) toast.error(`校验未通过：${v.errors.length} 个错误`)
      else if (v.warnings.length > 0) toast.warning(`校验通过，有 ${v.warnings.length} 条警告`)
      else toast.success('DAG 校验通过')
      return v
    } catch (e) {
      toast.error(`校验请求失败：${errorMessage(e)}`)
      return null
    } finally {
      setValidating(false)
    }
  }, [assemble])

  const doSave = async () => {
    if (flowId == null || !detail) return
    // 保存前强制校验：有 errors 逐条展示，不提交
    const v = await doValidate()
    if (!v || v.errors.length > 0) return
    setSaving(true)
    try {
      const res = await flowApi.update(flowId, {
        name: name.trim() || detail.name,
        description: description.trim(),
        dag: assemble()!,
      })
      if (res.warnings && res.warnings.length > 0) {
        toast.warning(`已保存「${res.name}」（${res.warnings.length} 条警告）`)
      } else {
        toast.success(`模板「${res.name}」已保存`)
      }
      onSaved()
      onClose()
    } catch (e) {
      toast.error(`保存失败：${errorMessage(e)}`, { duration: 8000 })
    } finally {
      setSaving(false)
    }
  }

  const runInputs = detail?.dag.run_inputs ?? {}

  return (
    <Sheet open={flowId != null} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>编辑流水线模板</SheetTitle>
          <SheetDescription>
            按原子参数规格编辑节点参数；<span className="font-mono">${'{'}xxx{'}'}</span> 引用运行时变量，保存时原样保留
          </SheetDescription>
        </SheetHeader>

        {detail == null ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            模板加载中…
          </div>
        ) : (
          <>
            <div className="-mr-2 flex-1 space-y-4 overflow-y-auto py-4 pr-2">
              {/* 名称 / 描述 */}
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1.5">
                  <Label>名称</Label>
                  <Input value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="grid gap-1.5">
                  <Label>描述</Label>
                  <Textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={1}
                    className="min-h-9"
                  />
                </div>
              </div>

              {/* run_inputs 只读展示（v1 不可编辑） */}
              {Object.keys(runInputs).length > 0 && (
                <div className="rounded-md border border-dashed p-3">
                  <p className="mb-2 text-xs font-medium text-muted-foreground">运行时变量（run_inputs，运行模板时填写，此处只读）</p>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(runInputs).map(([k, spec]) => (
                      <Badge key={k} variant="secondary" className="font-normal">
                        {spec.label ?? k}
                        <span className="ml-1 font-mono text-muted-foreground">
                          {k}: {spec.type} = {String(spec.default)}
                        </span>
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* 节点列表 */}
              <div className="flex flex-col">
                {nodes.map((node, i) => (
                  <Fragment key={node.id}>
                    {i > 0 && <EditorConnector />}
                    <NodeEditor node={node} atomOf={atomOf} titleOf={titleOf} onChange={(next) => setNode(i, next)} />
                  </Fragment>
                ))}
              </div>

              {/* 校验结果 */}
              {validation && (
                <div className="space-y-2 rounded-md border p-3 text-xs">
                  {validation.errors.length === 0 ? (
                    <p className="font-medium text-emerald-600">校验通过</p>
                  ) : (
                    <div>
                      <p className="font-medium text-red-600">{validation.errors.length} 个错误（修正后重新校验才能保存）：</p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-red-600">
                        {validation.errors.map((err, i) => (
                          <li key={i}>{err}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {validation.warnings.length > 0 && (
                    <div>
                      <p className="font-medium text-amber-600">{validation.warnings.length} 条警告（不阻断保存）：</p>
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

            <div className="flex justify-end gap-2 border-t pt-4">
              <Button variant="outline" onClick={onClose} disabled={saving}>
                取消
              </Button>
              <Button variant="outline" onClick={() => void doValidate()} disabled={validating || saving}>
                {validating ? '校验中…' : '校验'}
              </Button>
              <Button onClick={() => void doSave()} disabled={validating || saving || name.trim().length === 0}>
                {saving ? '保存中…' : '保存模板'}
              </Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

// ---------- 单个节点编辑卡 ----------

function NodeEditor({
  node,
  atomOf,
  titleOf,
  onChange,
  nested,
}: {
  node: DagNode
  atomOf: (name: string) => AtomSpec | undefined
  titleOf: (name: string) => string
  onChange: (next: DagNode) => void
  /** 容器内子节点：更紧凑 */
  nested?: boolean
}) {
  const [open, setOpen] = useState(true)
  const isContainer = Array.isArray(node.body) && node.body.length > 0

  const setParam = (key: string, value: unknown) =>
    onChange({ ...node, params: { ...(node.params ?? {}), [key]: value } })
  const setPolicyRetry = (policyKey: string, retry: unknown) => {
    const policy = node[policyKey as `on_${string}`]
    if (!policy || typeof policy !== 'object') return
    onChange({ ...node, [policyKey]: { ...(policy as Record<string, unknown>), retry } })
  }
  const setBreaker = (consecutiveFail: unknown) => {
    if (!node.circuit_breaker) return
    onChange({ ...node, circuit_breaker: { ...node.circuit_breaker, consecutive_fail: Number(consecutiveFail) || 0 } })
  }
  const setChild = (index: number, next: DagNode) =>
    onChange({ ...node, body: (node.body ?? []).map((c, i) => (i === index ? next : c)) })

  const fields = editableFields(node, atomOf(node.atom))
  const policies = policyEntries(node)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className={cn('rounded-lg border bg-background', nested && 'bg-muted/30')}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/50">
          <span className="text-sm font-medium">{titleOf(node.atom)}</span>
          <span className="font-mono text-xs text-muted-foreground">{node.atom}</span>
          <span className="font-mono text-xs text-muted-foreground/60">#{node.id}</span>
          {isContainer && <Badge className="bg-blue-600 text-white hover:bg-blue-600">容器</Badge>}
          <ChevronDown className="ml-auto h-4 w-4 text-muted-foreground transition-transform [[data-state=open]>&]:rotate-180" />
        </CollapsibleTrigger>

        <CollapsibleContent className="space-y-3 px-3 pb-3">
          {/* 参数表单 */}
          {fields.length > 0 ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              {fields.map((f) => (
                <ParamFieldEditor key={f.key} field={f} value={(node.params ?? {})[f.key]} onChange={(v) => setParam(f.key, v)} />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">该原子无可编辑参数</p>
          )}

          {/* 策略区：on_<outcome> 改 retry；熔断改 consecutive_fail */}
          {(policies.length > 0 || node.circuit_breaker) && (
            <div className="space-y-2 rounded-md border border-dashed p-2.5">
              <p className="text-xs font-medium text-muted-foreground">节点策略</p>
              {policies.map(([key, policy]) => (
                <div key={key} className="flex items-center gap-2 text-xs">
                  <Badge variant="outline" className="font-normal">
                    {outcomeLabel(key)}
                  </Badge>
                  <span className="text-muted-foreground">执行</span>
                  <Badge variant="secondary" className="font-normal">
                    {titleOf(policy.do ?? '')}
                  </Badge>
                  <span className="ml-auto flex items-center gap-1.5">
                    <span className="text-muted-foreground">重试</span>
                    <Input
                      type="number"
                      min={0}
                      step={1}
                      className="h-7 w-20"
                      value={policy.retry === undefined ? '' : String(policy.retry)}
                      onChange={(e) => setPolicyRetry(key, e.target.value === '' ? '' : Number(e.target.value))}
                    />
                    <span className="text-muted-foreground">次</span>
                  </span>
                </div>
              ))}
              {node.circuit_breaker && (
                <div className="flex items-center gap-2 text-xs">
                  <Badge variant="outline" className="font-normal">
                    熔断
                  </Badge>
                  <span className="text-muted-foreground">连续失败</span>
                  <Input
                    type="number"
                    min={0}
                    step={1}
                    className="h-7 w-20"
                    value={String(node.circuit_breaker.consecutive_fail ?? '')}
                    onChange={(e) => setBreaker(e.target.value === '' ? '' : Number(e.target.value))}
                  />
                  <span className="text-muted-foreground">次即 {node.circuit_breaker.action}</span>
                </div>
              )}
            </div>
          )}

          {/* 容器 body 递归 */}
          {isContainer && (
            <div className="flex flex-col rounded-md border border-dashed p-2.5">
              <p className="mb-2 text-xs font-medium text-muted-foreground">循环体（每次迭代依次执行）</p>
              {node.body!.map((child, i) => (
                <Fragment key={child.id}>
                  {i > 0 && <EditorConnector small />}
                  <NodeEditor node={child} atomOf={atomOf} titleOf={titleOf} onChange={(next) => setChild(i, next)} nested />
                </Fragment>
              ))}
            </div>
          )}
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

// ---------- 参数字段 ----------

interface EditableField {
  key: string
  type: 'number' | 'boolean' | 'string'
  /** param_spec 里的描述（help 小字） */
  help?: string
  /** param_spec 默认值（当前未设时预填） */
  fallback?: unknown
}

/** 可编辑字段 = param_spec.properties 中标量类型 + 当前 params 里 spec 未覆盖的标量键 */
function editableFields(node: DagNode, atom: AtomSpec | undefined): EditableField[] {
  const out: EditableField[] = []
  const seen = new Set<string>()
  const props = (atom?.param_spec?.properties ?? {}) as Record<
    string,
    { type?: string; description?: string; default?: unknown }
  >
  for (const [key, spec] of Object.entries(props)) {
    if (key === 'body') continue // 容器子图由编辑器结构化管理
    if (spec.type === 'integer' || spec.type === 'number') {
      out.push({ key, type: 'number', help: spec.description, fallback: spec.default })
      seen.add(key)
    } else if (spec.type === 'boolean') {
      out.push({ key, type: 'boolean', help: spec.description, fallback: spec.default })
      seen.add(key)
    } else if (spec.type === 'string') {
      out.push({ key, type: 'string', help: spec.description, fallback: spec.default })
      seen.add(key)
    }
    // object / array 等结构化参数不在 v1 表单内编辑
  }
  for (const [key, value] of Object.entries(node.params ?? {})) {
    if (seen.has(key) || key === 'body') continue
    if (typeof value === 'number') out.push({ key, type: 'number' })
    else if (typeof value === 'boolean') out.push({ key, type: 'boolean' })
    else if (typeof value === 'string') out.push({ key, type: 'string' })
  }
  return out
}

/** "${xxx}" 形式的 run_inputs 引用：只读展示，保存时原样保留 */
const REF_RE = /^\$\{(\w+)\}$/

function ParamFieldEditor({
  field,
  value,
  onChange,
}: {
  field: EditableField
  value: unknown
  onChange: (v: unknown) => void
}) {
  const current = value === undefined ? field.fallback : value
  const refMatch = typeof current === 'string' ? REF_RE.exec(current) : null

  return (
    <div className={cn('grid gap-1.5', field.type !== 'number' && 'col-span-2')}>
      <Label className="text-xs">
        <span className="font-mono">{field.key}</span>
      </Label>
      {refMatch ? (
        <div className="flex h-9 items-center rounded-md border border-dashed px-3">
          <Badge variant="secondary" className="font-normal">
            引用 run_inputs.{refMatch[1]}
          </Badge>
          <span className="ml-2 font-mono text-xs text-muted-foreground">{String(current)}</span>
        </div>
      ) : field.type === 'boolean' ? (
        <div className="flex h-9 items-center rounded-md border px-3">
          <Switch checked={Boolean(current)} onCheckedChange={onChange} />
          <span className="ml-2 text-sm text-muted-foreground">{current ? '是' : '否'}</span>
        </div>
      ) : field.type === 'number' ? (
        <Input
          type="number"
          step="any"
          value={current === undefined || current === null ? '' : String(current)}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        />
      ) : (
        <Input
          type="text"
          value={current === undefined || current === null ? '' : String(current)}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {field.help && <p className="text-xs leading-4 text-muted-foreground">{field.help}</p>}
    </div>
  )
}

// ---------- 工具 ----------

function policyEntries(node: DagNode): [string, { do?: string; retry?: number }][] {
  return Object.entries(node)
    .filter(([k, v]) => k.startsWith('on_') && v != null && typeof v === 'object')
    .map(([k, v]) => [k, v as { do?: string; retry?: number }])
}

function outcomeLabel(policyKey: string): string {
  const outcome = policyKey.slice(3)
  const labels: Record<string, string> = {
    blocked: '被风控时',
    net_error: '网络错误时',
    empty: '空结果时',
  }
  return labels[outcome] ?? `${outcome} 时`
}

function EditorConnector({ small }: { small?: boolean }) {
  return (
    <div className={cn('flex justify-center', small ? 'py-0' : 'py-0.5')}>
      <ChevronDown className={cn('text-muted-foreground/50', small ? 'h-3.5 w-3.5' : 'h-4 w-4')} />
    </div>
  )
}
