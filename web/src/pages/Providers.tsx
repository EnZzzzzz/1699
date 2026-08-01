import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { api, asArray, errorMessage, isNotImplemented } from '@/api/client'
import type { ConfigField, Provider, ProviderPayload, TestResult } from '@/api/types'
import { EmptyState, NotImplementedState } from '@/components/EmptyState'
import { toast } from 'sonner'
import { Plus, Pencil, PlugZap, RefreshCw, CheckCircle2, XCircle, Loader2 } from 'lucide-react'

// [待后端确认] 后端未返回 config_schema 时的兜底表单定义（依据 §4 providers.config_json）
const FALLBACK_SCHEMAS: Record<string, ConfigField[]> = {
  qingguo: [
    { key: 'key', label: '业务 Key', type: 'string', required: true },
    { key: 'auth_key', label: '认证账号', type: 'string', required: true },
    { key: 'auth_pwd', label: '认证密码', type: 'password', required: true },
    { key: 'channels', label: '通道数', type: 'number', default: 2 },
    { key: 'area', label: '地区', type: 'string', placeholder: '可选' },
    { key: 'isp', label: '运营商', type: 'string', placeholder: '可选' },
  ],
  default: [
    { key: 'key', label: '密钥', type: 'password', required: true },
    { key: 'channels', label: '通道数', type: 'number', default: 1 },
  ],
}

export default function Providers() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [loading, setLoading] = useState(true)
  const [notImpl, setNotImpl] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Provider | null>(null)
  const [testResults, setTestResults] = useState<Record<number, TestResult | 'loading'>>({})

  const load = useCallback(async () => {
    try {
      const res = await api.get('/providers')
      setProviders(asArray<Provider>(res.data).map(normalizeProvider))
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

  const testConnectivity = async (p: Provider) => {
    setTestResults((prev) => ({ ...prev, [p.id]: 'loading' }))
    try {
      const res = await api.post(`/providers/${p.id}/test`)
      setTestResults((prev) => ({ ...prev, [p.id]: res.data as TestResult }))
    } catch (e) {
      setTestResults((prev) => ({ ...prev, [p.id]: { ok: false, message: errorMessage(e) } }))
    }
  }

  if (loading) return <div className="py-20 text-center text-muted-foreground">加载中…</div>

  if (notImpl) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold">厂商配置</h1>
        <NotImplementedState feature="厂商配置" />
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold">厂商配置</h1>
        <EmptyState icon="error" title="无法获取厂商列表" description={error} actionLabel="重试" onAction={() => void load()} />
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">厂商配置</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setEditing(null)
              setDialogOpen(true)
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            新增厂商
          </Button>
        </div>
      </div>

      {providers.length === 0 ? (
        <EmptyState title="暂无厂商配置" description="添加代理厂商（首期支持青果网络）后即可使用代理池" />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {providers.map((p) => {
            const result = testResults[p.id]
            return (
              <Card key={p.id}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">{p.name}</CardTitle>
                    <Badge variant={p.enabled ? 'default' : 'secondary'}>{p.enabled ? '已启用' : '已停用'}</Badge>
                  </div>
                  <CardDescription className="font-mono text-xs">{p.kind}</CardDescription>
                </CardHeader>
                <CardContent>
                  <dl className="mb-4 space-y-1 text-sm">
                    {Object.entries(p.config).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-4">
                        <dt className="text-muted-foreground">{k}</dt>
                        <dd className="truncate font-mono text-xs" title={String(v)}>
                          {isSecretKey(k) ? '••••••' : String(v)}
                        </dd>
                      </div>
                    ))}
                  </dl>

                  {result && result !== 'loading' && (
                    <div
                      className={
                        'mb-3 flex items-start gap-2 rounded-md border p-2 text-sm ' +
                        (result.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30' : 'border-destructive/30 bg-destructive/5 text-destructive')
                      }
                    >
                      {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
                      <span>
                        {result.ok
                          ? `连通正常${result.channels != null ? `，通道 ${result.channels} 个` : ''}${result.exit_ip ? `，出口 IP ${result.exit_ip}` : ''}${result.latency_ms != null ? `，${result.latency_ms}ms` : ''}`
                          : `连接失败：${result.message ?? '未知原因'}`}
                      </span>
                    </div>
                  )}

                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => void testConnectivity(p)} disabled={result === 'loading'}>
                      {result === 'loading' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PlugZap className="mr-2 h-4 w-4" />}
                      测试连通性
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setEditing(p)
                        setDialogOpen(true)
                      }}
                    >
                      <Pencil className="mr-2 h-4 w-4" />
                      编辑
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      <ProviderDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
        onSaved={() => void load()}
      />
    </div>
  )
}

// 与后端掩码规则一致（后端仅掩码含 pwd/secret 的字段）
function isSecretKey(key: string): boolean {
  return /pwd|password|secret/i.test(key)
}

function normalizeProvider(raw: unknown): Provider {
  const r = raw as Record<string, unknown>
  let config: Provider['config'] = {}
  if (typeof r.config_json === 'string') {
    try {
      config = JSON.parse(r.config_json) as Provider['config']
    } catch {
      config = {}
    }
  } else if (r.config && typeof r.config === 'object') {
    config = r.config as Provider['config']
  }
  return {
    id: Number(r.id),
    kind: String(r.kind ?? ''),
    name: String(r.name ?? ''),
    config,
    config_schema: Array.isArray(r.config_schema) ? (r.config_schema as ConfigField[]) : undefined,
    enabled: Boolean(r.enabled ?? true),
    created_at: String(r.created_at ?? ''),
    updated_at: String(r.updated_at ?? ''),
  }
}

function ProviderDialog({
  open,
  onOpenChange,
  editing,
  onSaved,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  editing: Provider | null
  onSaved: () => void
}) {
  const [kind, setKind] = useState('qingguo')
  const [name, setName] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [config, setConfig] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)

  // 编辑态回填
  useEffect(() => {
    if (open) {
      if (editing) {
        setKind(editing.kind)
        setName(editing.name)
        setEnabled(editing.enabled)
        setConfig({ ...editing.config })
      } else {
        setKind('qingguo')
        setName('')
        setEnabled(true)
        setConfig({})
      }
    }
  }, [open, editing])

  // 表单字段：优先后端 config_schema，否则按 kind 使用兜底 schema
  const schema: ConfigField[] = editing?.config_schema ?? FALLBACK_SCHEMAS[kind] ?? FALLBACK_SCHEMAS.default

  const setField = (key: string, value: string | number | boolean) => {
    setConfig((c) => ({ ...c, [key]: value }))
  }

  const submit = async () => {
    if (!name.trim()) {
      toast.error('请填写厂商显示名')
      return
    }
    for (const f of schema) {
      if (f.required && (config[f.key] === undefined || config[f.key] === '')) {
        toast.error(`请填写「${f.label}」`)
        return
      }
    }
    setSubmitting(true)
    const payload: ProviderPayload = { kind, name: name.trim(), config, enabled }
    try {
      if (editing) {
        await api.put(`/providers/${editing.id}`, payload)
        toast.success('厂商配置已更新')
      } else {
        await api.post('/providers', payload)
        toast.success('厂商已添加')
      }
      onOpenChange(false)
      onSaved()
    } catch (e) {
      toast.error(`保存失败：${errorMessage(e)}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? '编辑厂商' : '新增厂商'}</DialogTitle>
          <DialogDescription>按厂商配置项填写密钥与参数，密码类字段已掩码</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label>厂商类型</Label>
              <Select value={kind} onValueChange={setKind} disabled={!!editing}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="qingguo">青果网络</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>显示名 *</Label>
              <Input placeholder="如：青果-长效动态" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          </div>

          {schema.map((f) => (
            <div key={f.key} className="grid gap-2">
              <Label>
                {f.label}
                {f.required && <span className="text-destructive"> *</span>}
              </Label>
              {f.type === 'boolean' ? (
                <div className="flex h-9 items-center">
                  <Switch checked={Boolean(config[f.key] ?? f.default ?? false)} onCheckedChange={(v) => setField(f.key, v)} />
                </div>
              ) : (
                <Input
                  type={f.type === 'password' ? 'password' : f.type === 'number' ? 'number' : 'text'}
                  placeholder={f.placeholder}
                  value={config[f.key] !== undefined ? String(config[f.key]) : f.default !== undefined ? String(f.default) : ''}
                  onChange={(e) => setField(f.key, f.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)}
                />
              )}
            </div>
          ))}

          <div className="flex items-center justify-between rounded-md border p-3">
            <Label>启用该厂商</Label>
            <Switch checked={enabled} onCheckedChange={setEnabled} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={() => void submit()} disabled={submitting}>
            {submitting ? '保存中…' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
