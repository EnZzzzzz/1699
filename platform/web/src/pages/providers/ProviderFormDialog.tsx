// 供应商添加/编辑对话框：名称 + 类型 + 启用开关 + config 键值对动态行
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api, type Provider } from '@/lib/api'
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
import { Plus, X } from 'lucide-react'

interface ConfigRow {
  key: string
  value: string
}

interface ProviderFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 传入则为编辑模式，null 为新增 */
  provider: Provider | null
  onSaved: () => void
}

export function ProviderFormDialog({ open, onOpenChange, provider, onSaved }: ProviderFormDialogProps) {
  const editing = provider !== null
  const [name, setName] = useState('')
  const [kind, setKind] = useState('qingguo')
  const [enabled, setEnabled] = useState(true)
  const [rows, setRows] = useState<ConfigRow[]>([])
  const [schemaKeys, setSchemaKeys] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  // 打开时回填
  useEffect(() => {
    if (!open) return
    setName(provider?.name ?? '')
    setKind(provider?.kind ?? 'qingguo')
    setEnabled(provider ? provider.enabled === 1 : true)
    const config = provider?.config ?? {}
    const entries = Object.entries(config)
    setRows(entries.length > 0 ? entries.map(([key, value]) => ({ key, value: String(value) })) : [{ key: '', value: '' }])
  }, [open, provider])

  // kind 确定后拉对应 config-schema 提示（新增模式切换类型时也会触发）
  useEffect(() => {
    if (!open) return
    setSchemaKeys([])
    api
      .providerConfigSchema(kind)
      .then((res) => setSchemaKeys(Object.keys(res.provider_config_structure ?? {})))
      .catch(() => setSchemaKeys([]))
  }, [open, kind])

  // 切换类型：apify 且当前配置行为空时预填 api_token 行
  const handleKindChange = (next: string) => {
    setKind(next)
    const blank = rows.every((r) => !r.key.trim() && !r.value.trim())
    if (next === 'apify' && blank) setRows([{ key: 'api_token', value: '' }])
  }

  const setRow = (idx: number, patch: Partial<ConfigRow>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  const removeRow = (idx: number) => {
    setRows((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev))
  }

  const handleSubmit = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast.error('请输入供应商名称')
      return
    }
    const config: Record<string, unknown> = {}
    const seen = new Set<string>()
    for (const row of rows) {
      const k = row.key.trim()
      if (!k && !row.value.trim()) continue
      if (!k) {
        toast.error('存在未填写键名的配置行')
        return
      }
      if (seen.has(k)) {
        toast.error(`配置键「${k}」重复`)
        return
      }
      seen.add(k)
      config[k] = row.value
    }
    setSubmitting(true)
    try {
      if (editing) {
        await api.updateProvider(provider.id, { name: trimmed, config, enabled })
        toast.success(`供应商「${trimmed}」已更新`)
      } else {
        await api.createProvider({ kind, name: trimmed, config, enabled })
        toast.success(`供应商「${trimmed}」已创建`)
      }
      onOpenChange(false)
      onSaved()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? `编辑供应商「${provider.name}」` : '添加供应商'}</DialogTitle>
          <DialogDescription>
            {schemaKeys.length > 0
              ? `需要的字段：${schemaKeys.join(', ')}`
              : '填写供应商配置（键值对），保存后可探测/同步通道。'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="provider-name">名称</Label>
              <Input
                id="provider-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如 青果-主用"
              />
            </div>
            <div className="space-y-2">
              <Label>类型</Label>
              {editing ? (
                <Input value={kind} disabled />
              ) : (
                <Select value={kind} onValueChange={handleKindChange}>
                  <SelectTrigger>
                    <SelectValue placeholder="选择类型" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="qingguo">qingguo（青果）</SelectItem>
                    <SelectItem value="apify">apify（WhatsApp 查号 API）</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Switch id="provider-enabled" checked={enabled} onCheckedChange={setEnabled} />
            <Label htmlFor="provider-enabled">启用该供应商</Label>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>配置（键值对）</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setRows((prev) => [...prev, { key: '', value: '' }])}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                加一行
              </Button>
            </div>
            <div className="space-y-2">
              {rows.map((row, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <Input
                    className="w-2/5 font-mono text-sm"
                    value={row.key}
                    onChange={(e) => setRow(idx, { key: e.target.value })}
                    placeholder="键，如 api_key"
                  />
                  <Input
                    className="flex-1 font-mono text-sm"
                    value={row.value}
                    onChange={(e) => setRow(idx, { value: e.target.value })}
                    placeholder="值"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => removeRow(idx)}
                    disabled={rows.length <= 1}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            {schemaKeys.length > 0 && kind === 'qingguo' && (
              <p className="text-xs text-muted-foreground">
                提示：缺失字段会导致通道创建失败，请按上方字段清单填写。
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? '保存中…' : editing ? '保存修改' : '创建'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
