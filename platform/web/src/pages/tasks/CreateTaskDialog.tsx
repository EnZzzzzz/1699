// 新建任务对话框：任务类型 Select + 采集参数表单
// wa_check（WhatsApp 查号）为进程内任务，表单切换为 limit/interval/accounts
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api, type TaskParams, type TaskType, type WaAccount } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { TASK_TYPE_OPTIONS } from './task-ui'

// task-ui.tsx 的选项 + 本对话框新增的 WhatsApp 查号
const TYPE_OPTIONS: { value: TaskType; label: string }[] = [
  ...TASK_TYPE_OPTIONS,
  { value: 'wa_check', label: 'WhatsApp 查号' },
]

interface CreateTaskDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}

export function CreateTaskDialog({ open, onOpenChange, onCreated }: CreateTaskDialogProps) {
  const [type, setType] = useState<TaskType>('1688_shop')
  const [batchNum, setBatchNum] = useState('10')
  const [maxBatches, setMaxBatches] = useState('0')
  const [limit, setLimit] = useState('0')
  const [useProxy, setUseProxy] = useState(true)
  const [headless, setHeadless] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  // wa_check 专用表单状态
  const [waLimit, setWaLimit] = useState('0')
  const [waInterval, setWaInterval] = useState('2.0')
  const [waAccounts, setWaAccounts] = useState<WaAccount[]>([])
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])

  // 打开对话框时拉取 WhatsApp 账号列表（仅 logged_in 可选）
  useEffect(() => {
    if (!open) return
    api.waAccounts()
      .then((accs) => setWaAccounts(accs.filter((a) => a.logged_in)))
      .catch(() => setWaAccounts([]))
  }, [open])

  const isWaCheck = type === 'wa_check'

  const toggleAccount = (name: string, checked: boolean) => {
    setSelectedAccounts((prev) =>
      checked ? [...prev, name] : prev.filter((n) => n !== name))
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    try {
      if (isWaCheck) {
        const limitN = Number(waLimit)
        const intervalN = Number(waInterval)
        if (!Number.isInteger(limitN) || limitN < 0) {
          toast.error('查号上限需为不小于 0 的整数（0 = 全部未查）')
          return
        }
        if (!Number.isFinite(intervalN) || intervalN < 0) {
          toast.error('批间间隔需为不小于 0 的数字（秒）')
          return
        }
        const task = await api.createTask({
          type,
          params: {
            limit: limitN,
            interval: intervalN,
            accounts: selectedAccounts,
          } as unknown as TaskParams,
        })
        toast.success(`任务 #${task.id} 创建成功`)
      } else {
        const batchNumN = Number(batchNum)
        const maxBatchesN = Number(maxBatches)
        const limitN = Number(limit)
        if (!Number.isInteger(batchNumN) || batchNumN < 1) {
          toast.error('每批数量需为不小于 1 的整数')
          return
        }
        if (!Number.isInteger(maxBatchesN) || maxBatchesN < 0) {
          toast.error('最大批数需为不小于 0 的整数（0 = 不限）')
          return
        }
        if (!Number.isInteger(limitN) || limitN < 0) {
          toast.error('采集上限需为不小于 0 的整数（0 = 不限）')
          return
        }
        const task = await api.createTask({
          type,
          params: {
            batch_num: batchNumN,
            max_batches: maxBatchesN,
            limit: limitN,
            use_proxy: useProxy,
            headless,
          },
        })
        toast.success(`任务 #${task.id} 创建成功`)
      }
      onOpenChange(false)
      onCreated()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '创建任务失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>新建任务</DialogTitle>
          <DialogDescription>选择任务类型并配置采集参数，创建后进入排队。</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>任务类型</Label>
            <Select value={type} onValueChange={(v) => setType(v as TaskType)}>
              <SelectTrigger>
                <SelectValue placeholder="选择任务类型" />
              </SelectTrigger>
              <SelectContent>
                {TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isWaCheck ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="wa-limit">查号上限</Label>
                  <Input
                    id="wa-limit"
                    type="number"
                    min={0}
                    value={waLimit}
                    onChange={(e) => setWaLimit(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">0 = 全部未查</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="wa-interval">批间间隔（秒）</Label>
                  <Input
                    id="wa-interval"
                    type="number"
                    min={0}
                    step={0.5}
                    value={waInterval}
                    onChange={(e) => setWaInterval(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">默认 2.0 秒</p>
                </div>
              </div>

              <div className="space-y-2 rounded-md border border-border px-3 py-2">
                <Label>查号账号</Label>
                {waAccounts.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    暂无已登录账号，将使用默认账号
                  </p>
                ) : (
                  <div className="space-y-2">
                    {waAccounts.map((a) => (
                      <div key={a.name} className="flex items-center gap-2">
                        <Checkbox
                          id={`wa-acc-${a.name}`}
                          checked={selectedAccounts.includes(a.name)}
                          onCheckedChange={(c) => toggleAccount(a.name, c === true)}
                        />
                        <Label htmlFor={`wa-acc-${a.name}`} className="cursor-pointer font-normal">
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
          ) : (
            <>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="batch-num">每批数量</Label>
                  <Input
                    id="batch-num"
                    type="number"
                    min={1}
                    value={batchNum}
                    onChange={(e) => setBatchNum(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="max-batches">最大批数</Label>
                  <Input
                    id="max-batches"
                    type="number"
                    min={0}
                    value={maxBatches}
                    onChange={(e) => setMaxBatches(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">0 = 不限</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="limit">采集上限</Label>
                  <Input
                    id="limit"
                    type="number"
                    min={0}
                    value={limit}
                    onChange={(e) => setLimit(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">0 = 不限</p>
                </div>
              </div>

              <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                <div>
                  <Label htmlFor="use-proxy" className="cursor-pointer">使用代理</Label>
                  <p className="text-xs text-muted-foreground">通过代理通道发起请求</p>
                </div>
                <Switch id="use-proxy" checked={useProxy} onCheckedChange={setUseProxy} />
              </div>

              <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                <div>
                  <Label htmlFor="headless" className="cursor-pointer">无头浏览器</Label>
                  <p className="text-xs text-muted-foreground">后台运行，不弹出浏览器窗口</p>
                </div>
                <Switch id="headless" checked={headless} onCheckedChange={setHeadless} />
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? '创建中…' : '创建任务'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
