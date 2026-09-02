import { useState } from 'react'
import { toast } from 'sonner'
import { api, useApiData, formatTime, type Provider, type ProviderChannel } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Activity, Loader2, MessageCircle, Network, Pencil, Plus, RefreshCw } from 'lucide-react'
import { ProviderFormDialog } from './providers/ProviderFormDialog'

// 有代理通道概念的供应商类型；其他类型（如 apify 查号 API）不显示通道相关 UI
const PROXY_KINDS = new Set(['qingguo'])

// 支持卡片级费用同步的供应商类型（对应后端 /costs/sync?provider=...）
const SYNCABLE_KINDS = new Set(['apify', 'brightdata', 'numberchecker'])

// 配置值打码展示：长字符串保留前 4 位 + ****（仅卡片摘要，编辑表单仍回显明文）
function maskConfigValue(value: unknown): string {
  const s = String(value ?? '')
  return s.length > 4 ? `${s.slice(0, 4)}****` : s
}

function channelStatusBadge(status: string) {
  switch (status) {
    case 'ok':
    case 'active':
    case 'ready':
      return <Badge className="bg-success text-success-foreground hover:bg-success">{status}</Badge>
    case 'failed':
    case 'down':
    case 'error':
      return <Badge className="bg-danger text-danger-foreground hover:bg-danger">{status}</Badge>
    case 'disabled':
      return (
        <Badge variant="outline" className="text-muted-foreground">
          {status}
        </Badge>
      )
    case 'idle':
    default:
      return <Badge variant="secondary">{status}</Badge>
  }
}

function ChannelTable({ channels }: { channels: ProviderChannel[] }) {
  if (channels.length === 0) {
    return <p className="py-4 text-center text-sm text-muted-foreground">暂无通道</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">ID</TableHead>
          <TableHead>Tunnel</TableHead>
          <TableHead>出口 IP</TableHead>
          <TableHead>状态</TableHead>
          <TableHead>IP 到期时间</TableHead>
          <TableHead>最近探测</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {channels.map((c) => (
          <TableRow key={c.id}>
            <TableCell className="font-mono text-xs text-muted-foreground">#{c.id}</TableCell>
            <TableCell className="font-mono text-sm">{c.tunnel}</TableCell>
            <TableCell className="font-mono text-sm">{c.exit_ip ?? '—'}</TableCell>
            <TableCell>{channelStatusBadge(c.status)}</TableCell>
            <TableCell className="text-sm">{formatTime(c.ip_expires_at)}</TableCell>
            <TableCell className="text-sm">{formatTime(c.last_probe_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

interface ProviderCardProps {
  provider: Provider
  onEdit: (provider: Provider) => void
  onChanged: () => void
}

function ProviderCard({ provider, onEdit, onChanged }: ProviderCardProps) {
  const enabled = provider.enabled === 1
  const isProxy = PROXY_KINDS.has(provider.kind)
  const okCount = provider.channels.filter((c) => ['ok', 'active', 'ready'].includes(c.status)).length
  const configEntries = Object.entries(provider.config ?? {})
  const [toggling, setToggling] = useState(false)
  const [probing, setProbing] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [syncing, setSyncing] = useState(false)

  // 卡片级费用同步：只刷新该供应商的余额/账单（后端 /costs/sync?provider=...）
  const handleSyncCosts = async () => {
    setSyncing(true)
    try {
      const res = await api.syncProviderCosts(provider.kind, provider.name)
      const block = res.brightdata ?? res.apify ?? res.numberchecker
      if (block && block.ok === false) {
        toast.warning(`「${provider.name}」费用同步失败，详见后端日志`)
      } else {
        toast.success(`「${provider.name}」费用已同步`)
      }
      onChanged()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '费用同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const handleToggle = async (next: boolean) => {
    setToggling(true)
    try {
      await api.updateProvider(provider.id, { enabled: next })
      toast.success(next ? `已启用「${provider.name}」` : `已停用「${provider.name}」`)
      onChanged()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '操作失败')
    } finally {
      setToggling(false)
    }
  }

  const handleProbe = async () => {
    setProbing(true)
    try {
      const res = await api.probeProvider(provider.id)
      if (res.fail === 0) {
        toast.success(`探测完成：${res.ok} 条通道全部正常`)
      } else {
        toast.warning(`探测完成：成功 ${res.ok} 条，失败 ${res.fail} 条`)
      }
      onChanged()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '探测失败')
    } finally {
      setProbing(false)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.refreshProviderChannels(provider.id)
      toast.success(`「${provider.name}」通道已同步`)
      onChanged()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '同步失败')
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent">
            <Network className="h-4 w-4" />
          </div>
          <div>
            <CardTitle className="text-base">{provider.name}</CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {isProxy
                ? `类型 ${provider.kind} · 通道 ${provider.channels.length} 条（可用 ${okCount}）`
                : `类型 ${provider.kind}`}
              {provider.billing &&
                ` · ${provider.billing.label} $${provider.billing.usd.toFixed(2)}${
                  provider.billing.consumed != null
                    ? ` · 本账期消耗 $${provider.billing.consumed.toFixed(2)}`
                    : ''
                }${
                  provider.billing.limit ? ` / 上限 $${provider.billing.limit}` : ''
                }${provider.billing.as_of ? `（截至 ${provider.billing.as_of}）` : ''}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch
              checked={enabled}
              disabled={toggling}
              onCheckedChange={handleToggle}
              aria-label="启用/停用"
            />
            {enabled ? (
              <Badge className="bg-success text-success-foreground hover:bg-success">已启用</Badge>
            ) : (
              <Badge variant="secondary">已停用</Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {SYNCABLE_KINDS.has(provider.kind) && (
              <Button variant="outline" size="sm" onClick={handleSyncCosts} disabled={syncing}>
                {syncing ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                {syncing ? '同步中…' : provider.kind === 'apify' ? '同步用量' : '同步余额'}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => onEdit(provider)}>
              <Pencil className="mr-2 h-4 w-4" />
              编辑
            </Button>
            {isProxy && (
              <>
                <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing || probing}>
                  {refreshing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-2 h-4 w-4" />
                  )}
                  同步通道
                </Button>
                <Button size="sm" onClick={handleProbe} disabled={probing || refreshing}>
                  {probing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Activity className="mr-2 h-4 w-4" />
                  )}
                  {probing ? '探测中…' : '探测全部通道'}
                </Button>
              </>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isProxy ? (
          <ChannelTable channels={provider.channels} />
        ) : configEntries.length > 0 ? (
          <div className="space-y-1.5">
            {configEntries.map(([key, value]) => (
              <div key={key} className="flex items-center gap-3 text-sm">
                <span className="w-36 shrink-0 font-mono text-muted-foreground">{key}</span>
                <span className="font-mono">{maskConfigValue(value)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-2 text-sm text-muted-foreground">暂无配置</p>
        )}
      </CardContent>
    </Card>
  )
}

// 微信本机账号状态卡（chatbot 子仓容器扫描，走 /wechat/status，不在 providers 表）
function WechatCard() {
  const { data, error } = useApiData(api.wechatStatus, 60_000)
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent">
            <MessageCircle className="h-4 w-4" />
          </div>
          <div>
            <CardTitle className="text-base">微信</CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              本机账号（chatbot 子仓扫描） · 在线 {data ? `${data.online}/${data.total}` : '—'}
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {error && !data ? (
          <p className="py-2 text-sm text-muted-foreground">{error}</p>
        ) : !data ? (
          <p className="py-2 text-sm text-muted-foreground">扫描中…</p>
        ) : (
          <div className="space-y-1.5">
            {data.accounts.map((a) => (
              <div key={a.name} className="flex items-center gap-3 text-sm">
                <span className="w-36 shrink-0 font-mono text-muted-foreground">{a.name}</span>
                <span className="font-mono">{a.wxid}</span>
                {a.online ? (
                  <Badge variant="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">在线</Badge>
                ) : (
                  <Badge variant="secondary">离线</Badge>
                )}
                {!a.keys_ok && (
                  <Badge variant="outline" className="text-muted-foreground">无密钥</Badge>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function Providers() {
  const { data, loading, error, reload } = useApiData(api.providers, 60_000)
  const [formOpen, setFormOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null)

  const openAdd = () => {
    setEditingProvider(null)
    setFormOpen(true)
  }

  const openEdit = (provider: Provider) => {
    setEditingProvider(provider)
    setFormOpen(true)
  }

  // 代理类供应商（有通道概念）与第三方 API 供应商（纯凭证，如 apify）分 Tab 展示
  const proxyProviders = (data ?? []).filter((p) => PROXY_KINDS.has(p.kind))
  const apiProviders = (data ?? []).filter((p) => !PROXY_KINDS.has(p.kind))

  const renderCards = (providers: Provider[], emptyText: string) => {
    if (loading && !data) return <LoadingState />
    if (error && !data) return <ErrorState message={error} onRetry={reload} />
    if (providers.length === 0) return <EmptyState text={emptyText} />
    return (
      <div className="space-y-4">
        {providers.map((p) => (
          <ProviderCard key={p.id} provider={p} onEdit={openEdit} onChanged={reload} />
        ))}
      </div>
    )
  }

  return (
    <div className="p-6">
      <PageHeader title="供应商" desc="代理池与第三方 API 凭证管理" />

      {/* 微信本机账号状态（常驻显示，不随 Tab 切换） */}
      <div className="mt-4">
        <WechatCard />
      </div>

      <Tabs defaultValue="proxy" className="mt-4">
        <TabsList>
          <TabsTrigger value="proxy">代理池</TabsTrigger>
          <TabsTrigger value="api">第三方 API</TabsTrigger>
        </TabsList>

        <TabsContent value="proxy" className="mt-4 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              代理供应商（青果等）与通道状态
            </p>
            <Button size="sm" onClick={openAdd}>
              <Plus className="mr-2 h-4 w-4" />
              添加供应商
            </Button>
          </div>
          {renderCards(proxyProviders, '暂无代理供应商，点击右上角「添加供应商」开始')}
        </TabsContent>

        <TabsContent value="api" className="mt-4 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              第三方 API 供应商（Apify 等）的凭证管理
            </p>
            <Button size="sm" onClick={openAdd}>
              <Plus className="mr-2 h-4 w-4" />
              添加供应商
            </Button>
          </div>
          {renderCards(apiProviders, '暂无第三方 API 供应商，点击右上角「添加供应商」开始')}
        </TabsContent>
      </Tabs>

      <ProviderFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        provider={editingProvider}
        onSaved={reload}
      />
    </div>
  )
}
