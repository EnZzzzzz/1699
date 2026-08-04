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
import { Activity, Loader2, Network, Pencil, Plus, RefreshCw } from 'lucide-react'
import { ProviderFormDialog } from './providers/ProviderFormDialog'

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
  const okCount = provider.channels.filter((c) => ['ok', 'active', 'ready'].includes(c.status)).length
  const [toggling, setToggling] = useState(false)
  const [probing, setProbing] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

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
              类型 {provider.kind} · 通道 {provider.channels.length} 条（可用 {okCount}）
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
            <Button variant="outline" size="sm" onClick={() => onEdit(provider)}>
              <Pencil className="mr-2 h-4 w-4" />
              编辑
            </Button>
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
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ChannelTable channels={provider.channels} />
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

  return (
    <div className="p-6">
      <PageHeader
        title="供应商"
        desc="代理供应商（青果等）与通道状态"
        extra={
          <Button size="sm" onClick={openAdd}>
            <Plus className="mr-2 h-4 w-4" />
            添加供应商
          </Button>
        }
      />

      {loading && !data ? (
        <LoadingState />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState text="暂无供应商配置，点击右上角「添加供应商」开始" />
      ) : (
        <div className="space-y-4">
          {data.map((p) => (
            <ProviderCard key={p.id} provider={p} onEdit={openEdit} onChanged={reload} />
          ))}
        </div>
      )}

      <ProviderFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        provider={editingProvider}
        onSaved={reload}
      />
    </div>
  )
}
