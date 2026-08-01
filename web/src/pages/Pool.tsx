import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, asArray, errorMessage, isNotImplemented } from '@/api/client'
import type { Channel, WsMessage } from '@/api/types'
import { ChannelStatusBadge, TaskTypeLabel } from '@/components/StatusBadge'
import { EmptyState, NotImplementedState } from '@/components/EmptyState'
import { MiniTrend, Countdown } from '@/components/MiniTrend'
import { useRealtime } from '@/hooks/useRealtime'
import { RefreshCw, Home } from 'lucide-react'

export default function Pool() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [loading, setLoading] = useState(true)
  const [notImpl, setNotImpl] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await api.get('/pool/channels')
      setChannels(normalizeChannels(res.data))
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

  const onWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type === 'pool_status') {
      setChannels(normalizeChannels(msg.channels))
    }
  }, [])

  useRealtime({ onMessage: onWsMessage, poll: load })

  // 按厂商分组；直连（provider_id 为 null）置顶
  const groups = useMemo(() => {
    const map = new Map<string, Channel[]>()
    for (const ch of channels) {
      const key = ch.provider_id === null ? '__direct__' : ch.provider_name || `厂商 #${ch.provider_id}`
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(ch)
    }
    const entries = [...map.entries()]
    entries.sort((a, b) => {
      if (a[0] === '__direct__') return -1
      if (b[0] === '__direct__') return 1
      return a[0].localeCompare(b[0])
    })
    return entries
  }, [channels])

  if (loading) return <div className="py-20 text-center text-muted-foreground">加载中…</div>

  if (notImpl) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold">IP 池</h1>
        <NotImplementedState feature="IP 池监控" />
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold">IP 池</h1>
        <EmptyState icon="error" title="无法获取通道列表" description={error} actionLabel="重试" onAction={() => void load()} />
      </div>
    )
  }

  const defaultTab = groups[0]?.[0] ?? '__direct__'

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">IP 池</h1>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新
        </Button>
      </div>

      {groups.length === 0 ? (
        <EmptyState title="暂无通道" description="请先在「厂商配置」中添加代理厂商并同步通道" />
      ) : (
        <Tabs defaultValue={defaultTab}>
          <TabsList>
            {groups.map(([key, list]) => (
              <TabsTrigger key={key} value={key} className="gap-1.5">
                {key === '__direct__' && <Home className="h-3.5 w-3.5" />}
                {key === '__direct__' ? '直连 · 本机 IP' : key}
                <span className="text-xs text-muted-foreground">({list.length})</span>
              </TabsTrigger>
            ))}
          </TabsList>
          {groups.map(([key, list]) => (
            <TabsContent key={key} value={key}>
              <ChannelTable channels={list} direct={key === '__direct__'} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  )
}

function ChannelTable({ channels, direct }: { channels: Channel[]; direct: boolean }) {
  return (
    <div className="rounded-lg border bg-background">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>隧道入口</TableHead>
            <TableHead>当前出口 IP</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>占用任务</TableHead>
            <TableHead className="text-right">近 5 分钟请求</TableHead>
            <TableHead>频率趋势</TableHead>
            <TableHead>过期倒计时</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {channels.map((ch) => (
            <TableRow key={ch.id}>
              <TableCell className="font-mono text-sm">{direct ? '本机直连' : ch.tunnel ?? '-'}</TableCell>
              <TableCell className="font-mono text-sm">{ch.exit_ip ?? '-'}</TableCell>
              <TableCell>
                <ChannelStatusBadge status={ch.status} />
              </TableCell>
              <TableCell>
                {ch.used_by_task != null ? (
                  <span className="text-sm">
                    <TaskTypeLabel type={ch.used_by_task_type} /> #{ch.used_by_task}
                  </span>
                ) : (
                  <span className="text-muted-foreground">-</span>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">{ch.requests_5m.toLocaleString()}</TableCell>
              <TableCell>
                <MiniTrend data={ch.freq_5m} width={110} height={28} />
              </TableCell>
              <TableCell>
                <Countdown target={ch.ip_expires_at} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/** 兼容字段命名差异，归一化为前端 Channel 结构 */
function normalizeChannels(data: unknown): Channel[] {
  return asArray<Record<string, unknown>>(data).map((raw) => ({
    id: Number(raw.id),
    provider_id: raw.provider_id === null || raw.provider_id === undefined ? null : Number(raw.provider_id),
    provider_name: String(raw.provider_name ?? (raw.provider_id == null ? '直连' : '')),
    tunnel: (raw.tunnel as string | null) ?? null,
    exit_ip: (raw.exit_ip as string | null) ?? null,
    status: (raw.status as Channel['status']) ?? 'idle',
    used_by_task: raw.used_by_task == null ? null : Number(raw.used_by_task),
    used_by_task_type: (raw.used_by_task_type as Channel['used_by_task_type']) ?? null,
    ip_expires_at: (raw.ip_expires_at as string | null) ?? null,
    last_probe_at: (raw.last_probe_at as string | null) ?? null,
    requests_5m: Number(raw.requests_5m ?? raw.requests ?? 0),
    freq_5m: Array.isArray(raw.freq_5m) ? (raw.freq_5m as number[]) : Array.isArray(raw.freq) ? (raw.freq as number[]) : [],
  }))
}
