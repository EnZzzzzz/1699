import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { api, errorMessage } from '@/api/client'
import { getParamSpecs, specsFor } from '@/api/paramSpecs'
import type { ParamSpec, ParamSpecs, TaskType } from '@/api/types'
import { toast } from 'sonner'
import { ChevronDown, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

const GROUP_ORDER = ['基本', '浏览器', '节奏控制', '重试策略']

type Values = Record<string, unknown>

export function NewTaskDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreated: () => void
}) {
  const [type, setType] = useState<TaskType>('shop_crawl')
  const [specs, setSpecs] = useState<ParamSpecs | null>(null)
  const [values, setValues] = useState<Values>({})
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ 基本: true })
  const [submitting, setSubmitting] = useState(false)

  // 打开时拉取参数规格（带缓存）；接口失败用本地兜底并提示
  useEffect(() => {
    if (!open) return
    let cancelled = false
    void getParamSpecs().then(({ specs: s, fallback }) => {
      if (cancelled) return
      setSpecs(s)
      if (fallback) toast.warning('参数规格加载失败，使用内置默认值')
    })
    return () => {
      cancelled = true
    }
  }, [open])

  const currentSpecs = useMemo(() => specsFor(specs, type), [specs, type])

  // 类型或规格变化时按 spec default 重置表单值
  useEffect(() => {
    const init: Values = {}
    for (const s of currentSpecs) init[s.name] = s.default
    setValues(init)
  }, [currentSpecs])

  const setValue = (name: string, v: unknown) => setValues((prev) => ({ ...prev, [name]: v }))

  const groups = useMemo(() => {
    const map = new Map<string, ParamSpec[]>()
    for (const s of currentSpecs) {
      const g = s.group || '其他'
      if (!map.has(g)) map.set(g, [])
      map.get(g)!.push(s)
    }
    return [...map.entries()].sort((a, b) => {
      const ia = GROUP_ORDER.indexOf(a[0])
      const ib = GROUP_ORDER.indexOf(b[0])
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    })
  }, [currentSpecs])

  const validate = useCallback((): string | null => {
    for (const s of currentSpecs) {
      const v = values[s.name]
      if (s.type === 'int' || s.type === 'float') {
        // 必填数值项（target/limit 等）：不能为空、必须是有限数
        if (v === undefined || v === null || v === '' || Number.isNaN(Number(v))) {
          return `「${s.label}」必须是数字`
        }
        const n = Number(v)
        if (s.type === 'int' && !Number.isInteger(n)) return `「${s.label}」必须是整数`
        if (s.min !== undefined && n < s.min) return `「${s.label}」不能小于 ${s.min}`
        if (s.max !== undefined && n > s.max) return `「${s.label}」不能大于 ${s.max}`
      }
    }
    // 启动前等待：上限必须 >= 下限
    const delayMin = Number(values.start_delay_min ?? 0)
    const delayMax = Number(values.start_delay_max ?? 0)
    if (!Number.isNaN(delayMin) && !Number.isNaN(delayMax) && delayMax < delayMin) {
      return '「启动前等待上限」不能小于「启动前等待下限」'
    }
    return null
  }, [currentSpecs, values])

  const submit = async () => {
    const err = validate()
    if (err) {
      toast.error(err)
      return
    }
    setSubmitting(true)
    try {
      // 全量提交（与后端缺省一致，直观可溯）
      const params: Record<string, unknown> = {}
      for (const s of currentSpecs) {
        const v = values[s.name]
        params[s.name] =
          s.type === 'int' || s.type === 'float' ? Number(v) : s.type === 'bool' ? Boolean(v) : (v ?? '')
      }
      const res = await api.post('/tasks', { type, params })
      const data = res.data as { warning?: string; dispatched?: boolean } | undefined
      if (data?.warning) {
        toast.warning(data.warning, { duration: 12000 })
      } else if (data && data.dispatched === false) {
        toast.warning('任务已创建，但 celery 派发失败，将滞留在待启动状态', { duration: 12000 })
      } else {
        toast.success('任务已创建')
      }
      onOpenChange(false)
      onCreated()
    } catch (e) {
      toast.error(`创建失败：${errorMessage(e)}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>新建任务</DialogTitle>
          <DialogDescription>参数定义来自后端 param-specs，非默认值会以琥珀色标出</DialogDescription>
        </DialogHeader>

        <div className="grid gap-2">
          <Label>任务类型</Label>
          <Select value={type} onValueChange={(v) => setType(v as TaskType)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="shop_crawl">店铺采集（shop_crawl）</SelectItem>
              <SelectItem value="contact_fetch">联系方式抓取（contact_fetch）</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="-mr-2 flex-1 space-y-3 overflow-y-auto py-2 pr-2">
          {specs == null ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              参数规格加载中…
            </div>
          ) : (
            groups.map(([group, fields]) => (
              <Collapsible
                key={`${type}-${group}`}
                open={openGroups[group] ?? group === '基本'}
                onOpenChange={(v) => setOpenGroups((prev) => ({ ...prev, [group]: v }))}
              >
                <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent">
                  <span>
                    {group}
                    <span className="ml-2 text-xs font-normal text-muted-foreground">{fields.length} 项</span>
                  </span>
                  <ChevronDown className="h-4 w-4 transition-transform [[data-state=open]>&]:rotate-180" />
                </CollapsibleTrigger>
                <CollapsibleContent className="space-y-3 px-1 pt-3">
                  <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                    {fields.map((s) => (
                      <ParamField
                        key={s.name}
                        spec={s}
                        value={values[s.name]}
                        onChange={(v) => setValue(s.name, v)}
                        extraHint={
                          // channels > workers 不生效：实际占用 = min(通道数, 并发数)（提示性，不拦截提交）
                          s.name === 'channels' &&
                          Number(values.channels ?? 0) > Number(values.workers ?? 0) &&
                          Number(values.workers ?? 0) > 0
                            ? '通道数超过并发数不会生效，实际将占用 = min(通道数, 并发数)'
                            : undefined
                        }
                      />
                    ))}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            ))
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={() => void submit()} disabled={submitting || specs == null}>
            {submitting ? '创建中…' : '创建任务'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ParamField({
  spec,
  value,
  onChange,
  extraHint,
}: {
  spec: ParamSpec
  value: unknown
  onChange: (v: unknown) => void
  /** 提示性警告（琥珀色，不拦截提交），渲染在 help 之前 */
  extraHint?: string
}) {
  const changed = value !== undefined && value !== spec.default
  const wide = spec.type === 'str' || spec.type === 'select' // 文本/下拉占满整行

  return (
    <div className={cn('grid gap-1.5', (wide || spec.type === 'bool') && 'col-span-2')}>
      <Label className={cn(changed && 'text-amber-600')}>
        {changed && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-500 align-middle" />}
        {spec.label}
        {(spec.type === 'int' || spec.type === 'float') && spec.min !== undefined && spec.max !== undefined && (
          <span className="ml-1 text-xs font-normal text-muted-foreground">
            ({spec.min}~{spec.max})
          </span>
        )}
      </Label>

      {spec.type === 'bool' ? (
        <div className="flex h-9 items-center rounded-md border px-3">
          <Switch checked={Boolean(value)} onCheckedChange={onChange} />
          <span className="ml-2 text-sm text-muted-foreground">{value ? '是' : '否'}</span>
        </div>
      ) : spec.type === 'select' ? (
        <Select value={String(value ?? '')} onValueChange={onChange}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(spec.options ?? []).map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          type={spec.type === 'str' ? 'text' : 'number'}
          min={spec.min}
          max={spec.max}
          step={spec.type === 'float' ? 'any' : 1}
          value={value === undefined || value === null ? '' : String(value)}
          onChange={(e) => {
            if (spec.type === 'str') return onChange(e.target.value)
            onChange(e.target.value === '' ? '' : Number(e.target.value))
          }}
        />
      )}

      {extraHint && <p className="text-xs leading-4 text-amber-600">{extraHint}</p>}
      {spec.help && <p className="text-xs leading-4 text-muted-foreground">{spec.help}</p>}
    </div>
  )
}
