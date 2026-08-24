// FB / X 联系方式导出对话框：字段勾选（默认 号码/用户名/发现时间）+ 时间范围 + 首次/重复 + 格式（默认 xlsx）
import { useState } from 'react'
import { toast } from 'sonner'
import { dataApi, type FbBucket, type WaFilter } from '@/lib/api-data'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

// 可选字段白名单与后端 _EXPORT_FIELDS 一致；来源/帖子链接/群组为内部信息，不提供导出
const FIELD_OPTIONS = [
  { key: 'number', label: '号码' },
  { key: 'author_name', label: '用户名' },
  { key: 'first_seen_at', label: '发现时间' },
  { key: 'bucket', label: '分桶' },
  { key: 'wa_status', label: 'WhatsApp 状态' },
  { key: 'wa_checked_at', label: '查询时间' },
] as const

const DEFAULT_FIELDS = ['number', 'author_name', 'first_seen_at']

interface FbExportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 当前 Tab 的筛选条件（导出沿用） */
  filters: {
    wa: WaFilter | ''
    bucket: FbBucket | ''
    source: 'fb' | 'x' | ''
    q: string
  }
}

export function FbExportDialog({ open, onOpenChange, filters }: FbExportDialogProps) {
  const [selected, setSelected] = useState<string[]>(DEFAULT_FIELDS)
  const [format, setFormat] = useState<'xlsx' | 'csv'>('xlsx')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [mode, setMode] = useState<'first' | 'repeat'>('first')
  const [limit, setLimit] = useState('')
  const [exporting, setExporting] = useState(false)

  const toggle = (key: string, checked: boolean) =>
    setSelected((prev) => (checked ? [...prev, key] : prev.filter((k) => k !== key)))

  const handleExport = async () => {
    if (selected.length === 0) {
      toast.error('请至少选择一个字段')
      return
    }
    if (dateFrom && dateTo && dateFrom > dateTo) {
      toast.error('开始日期不能晚于结束日期')
      return
    }
    const limitNum = limit.trim() === '' ? 0 : Number(limit)
    if (!Number.isInteger(limitNum) || limitNum < 0) {
      toast.error('导出数量需为正整数')
      return
    }
    // 列顺序固定按 FIELD_OPTIONS 展示顺序，不受勾选先后影响
    const fields = FIELD_OPTIONS.filter((f) => selected.includes(f.key)).map((f) => f.key)
    setExporting(true)
    try {
      const { filename, count } = await dataApi.exportFbContacts({
        ...filters, fields, format, dateFrom, dateTo, mode, limit: limitNum,
      })
      toast.success(`已导出 ${count} 条 → ${filename}`)
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>导出联系方式</DialogTitle>
          <DialogDescription>
            按当前筛选条件导出全部匹配数据，导出后号码自动标记为已导出；来源（FB / X）、帖子链接、群组为内部信息，不提供导出。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <p className="text-sm font-medium">导出字段</p>
            <div className="grid grid-cols-2 gap-2">
              {FIELD_OPTIONS.map((f) => (
                <div key={f.key} className="flex items-center gap-2">
                  <Checkbox
                    id={`export-${f.key}`}
                    checked={selected.includes(f.key)}
                    onCheckedChange={(c) => toggle(f.key, c === true)}
                  />
                  <Label htmlFor={`export-${f.key}`} className="text-sm font-normal">
                    {f.label}
                  </Label>
                </div>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">发现时间范围</p>
            <div className="flex items-center gap-2">
              <Input
                type="date"
                className="w-40"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
              <span className="text-sm text-muted-foreground">至</span>
              <Input
                type="date"
                className="w-40"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
              <span className="text-xs text-muted-foreground">留空不限</span>
            </div>
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">导出数量</p>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={1}
                className="w-40"
                placeholder="不限"
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              />
              <span className="text-xs text-muted-foreground">留空不限，按最新优先取前 N 条</span>
            </div>
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">导出模式</p>
            <RadioGroup
              value={mode}
              onValueChange={(v) => setMode(v as 'first' | 'repeat')}
              className="flex gap-4"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="first" id="mode-first" />
                <Label htmlFor="mode-first" className="text-sm font-normal">
                  首次导出（仅未导出过的）
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="repeat" id="mode-repeat" />
                <Label htmlFor="mode-repeat" className="text-sm font-normal">
                  重复导出（含已导出过的）
                </Label>
              </div>
            </RadioGroup>
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">导出格式</p>
            <RadioGroup
              value={format}
              onValueChange={(v) => setFormat(v as 'xlsx' | 'csv')}
              className="flex gap-4"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="xlsx" id="fmt-xlsx" />
                <Label htmlFor="fmt-xlsx" className="text-sm font-normal">
                  xlsx（默认）
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="csv" id="fmt-csv" />
                <Label htmlFor="fmt-csv" className="text-sm font-normal">
                  csv
                </Label>
              </div>
            </RadioGroup>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button size="sm" disabled={exporting || selected.length === 0} onClick={handleExport}>
            {exporting ? '导出中…' : '导出'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
