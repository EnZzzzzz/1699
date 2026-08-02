import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { errorMessage, flowApi, getAtomCatalog } from '@/api/client'
import type { AtomSpec, Dag } from '@/api/types'
import { FlowCanvas } from '@/components/canvas/FlowCanvas'
import { toast } from 'sonner'
import { LayoutGrid, List, Loader2 } from 'lucide-react'

/** 新建模板时的最小空 DAG（节点在画布上拖拽添加） */
const EMPTY_DAG: Dag = { version: 1, nodes: [] }

/**
 * 流水线模板编辑器（画布模式）：ComfyUI 风格节点画板。
 * - 编辑模式加载 FlowDetail + 原子目录；新建模式从空 DAG 开始
 * - FlowCanvas 通过 onChange 抛出完整新 DAG（含 ui.positions 位置持久化），本地 state 持有
 * - 保存前强制走 /api/flows/validate，errors 用 toast 逐条列出且不提交
 * - 头部 ToggleGroup 可切换到表单兜底（新建=JSON 对话框，编辑=FlowEditor）
 */
export function FlowCanvasEditor({
  open,
  flowId,
  onSwitchToForm,
  onClose,
  onSaved,
}: {
  /** 是否打开（模式切换由父组件控制） */
  open: boolean
  /** 编辑的模板 id；null = 新建模式（从空 DAG 开始） */
  flowId: number | null
  /** 切换到表单模式（父组件决定打开 JSON 对话框或 FlowEditor） */
  onSwitchToForm: () => void
  onClose: () => void
  onSaved: () => void
}) {
  const [dag, setDag] = useState<Dag | null>(null)
  const [atomSpecs, setAtomSpecs] = useState<AtomSpec[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) {
      setDag(null)
      return
    }
    let cancelled = false
    setLoading(true)
    const detailPromise = flowId != null ? flowApi.get(flowId) : Promise.resolve(null)
    Promise.all([detailPromise, getAtomCatalog()])
      .then(([d, catalog]) => {
        if (cancelled) return
        setAtomSpecs(catalog)
        if (d) {
          setName(d.name)
          setDescription(d.description ?? '')
          setDag(structuredClone(d.dag))
        } else {
          setName('')
          setDescription('')
          setDag(structuredClone(EMPTY_DAG))
        }
      })
      .catch((e) => toast.error(`加载模板失败：${errorMessage(e)}`))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [open, flowId])

  /** 保存：先校验，errors 逐条 toast 不提交；通过则走 create/update */
  const doSave = useCallback(async () => {
    if (!dag) return
    setSaving(true)
    try {
      const v = await flowApi.validate(dag)
      if (v.errors.length > 0) {
        toast.error(`DAG 校验未通过：${v.errors.length} 个错误`, {
          description: v.errors.map((err, i) => `${i + 1}. ${err}`).join('\n'),
          duration: 12000,
        })
        return
      }
      if (v.warnings.length > 0) {
        toast.warning(`校验通过，有 ${v.warnings.length} 条警告`, {
          description: v.warnings.map((w, i) => `${i + 1}. ${w}`).join('\n'),
          duration: 8000,
        })
      }
      const payload = { name: name.trim(), description: description.trim() || undefined, dag }
      const res = flowId != null ? await flowApi.update(flowId, payload) : await flowApi.create(payload)
      toast.success(flowId != null ? `模板「${res.name}」已保存` : `模板「${res.name}」已创建`)
      onSaved()
      onClose()
    } catch (e) {
      toast.error(`保存失败：${errorMessage(e)}`, { duration: 8000 })
    } finally {
      setSaving(false)
    }
  }, [dag, flowId, name, description, onSaved, onClose])

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-[92vw]">
        <SheetHeader>
          <div className="flex items-center justify-between gap-4 pr-8">
            <SheetTitle>{flowId != null ? '编辑流水线模板' : '新建流水线模板'}</SheetTitle>
            {/* 模式切换：画布（默认）/ 表单兜底 */}
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value="canvas"
              onValueChange={(v) => {
                if (v === 'form') onSwitchToForm()
              }}
            >
              <ToggleGroupItem value="canvas" aria-label="画布模式">
                <LayoutGrid className="mr-1 h-3.5 w-3.5" />
                画布
              </ToggleGroupItem>
              <ToggleGroupItem value="form" aria-label="表单模式">
                <List className="mr-1 h-3.5 w-3.5" />
                表单
              </ToggleGroupItem>
            </ToggleGroup>
          </div>
          <SheetDescription>
            从左侧拖入原子节点并连线编排；节点位置随模板保存。保存前自动校验 DAG。
          </SheetDescription>
        </SheetHeader>

        {loading || dag == null ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            模板加载中…
          </div>
        ) : (
          <>
            {/* 名称 / 描述 */}
            <div className="grid grid-cols-2 gap-3 py-3">
              <div className="grid gap-1.5">
                <Label>名称</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：联系人提取·激进版" />
              </div>
              <div className="grid gap-1.5">
                <Label>描述（可选）</Label>
                <Textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={1}
                  className="min-h-9"
                  placeholder="模板用途说明"
                />
              </div>
            </div>

            {/* 画布主体 */}
            <div className="min-h-0 flex-1">
              <FlowCanvas dag={dag} atomSpecs={atomSpecs} onChange={setDag} className="h-full" />
            </div>

            <div className="flex justify-end gap-2 border-t pt-4">
              <Button variant="outline" onClick={onClose} disabled={saving}>
                取消
              </Button>
              <Button onClick={() => void doSave()} disabled={saving || name.trim().length === 0}>
                {saving ? '保存中…' : '保存模板'}
              </Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
