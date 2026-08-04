// 新建任务对话框：任务类型 Select + 采集参数表单
import { useState } from 'react'
import { toast } from 'sonner'
import { api, type TaskType } from '@/lib/api'
import { Button } from '@/components/ui/button'
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

  const handleSubmit = async () => {
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

    setSubmitting(true)
    try {
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
                {TASK_TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

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
