import { api, useApiData, formatTime, type Provider, type ProviderChannel } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { Network } from 'lucide-react'

function channelStatusBadge(status: string) {
  switch (status) {
    case 'ok':
    case 'active':
    case 'ready':
      return <Badge className="bg-emerald-600 hover:bg-emerald-600">{status}</Badge>
    case 'failed':
    case 'down':
    case 'error':
      return <Badge variant="destructive">{status}</Badge>
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

function ProviderCard({ provider }: { provider: Provider }) {
  const enabled = provider.enabled === 1
  const okCount = provider.channels.filter((c) => ['ok', 'active', 'ready'].includes(c.status)).length
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
        {enabled ? (
          <Badge className="bg-emerald-600 hover:bg-emerald-600">已启用</Badge>
        ) : (
          <Badge variant="secondary">已停用</Badge>
        )}
      </CardHeader>
      <CardContent>
        <ChannelTable channels={provider.channels} />
      </CardContent>
    </Card>
  )
}

export default function Providers() {
  const { data, loading, error, reload } = useApiData(api.providers, 60_000)

  return (
    <div className="p-6">
      <PageHeader title="供应商" desc="代理供应商（青果等）与通道状态" />

      {loading && !data ? (
        <LoadingState />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState text="暂无供应商配置" />
      ) : (
        <div className="space-y-4">
          {data.map((p) => (
            <ProviderCard key={p.id} provider={p} />
          ))}
        </div>
      )}
    </div>
  )
}
