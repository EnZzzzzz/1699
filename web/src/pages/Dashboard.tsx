import { useCallback, useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { api, errorMessage, isNotImplemented } from '@/api/client'
import type { StatsOverview, WsMessage } from '@/api/types'
import { useRealtime } from '@/hooks/useRealtime'
import { MiniTrend } from '@/components/MiniTrend'
import { EmptyState, NotImplementedState } from '@/components/EmptyState'
import { Store, Clock3, Sparkles, Activity, Network, Gauge } from 'lucide-react'

export default function Dashboard() {
  const [stats, setStats] = useState<StatsOverview | null>(null)
  const [notImpl, setNotImpl] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const res = await api.get('/stats/overview')
      const d = res.data as Partial<StatsOverview>
      setStats({
        total_shops: d.total_shops ?? 0,
        pending_shops: d.pending_shops ?? 0,
        today_new: d.today_new ?? 0,
        running_tasks: d.running_tasks ?? 0,
        channels_total: d.channels_total ?? 0,
        channels_in_use: d.channels_in_use ?? 0,
        rate_last_hour: Array.isArray(d.rate_last_hour) ? d.rate_last_hour : [],
      })
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

  const onWsMessage = useCallback(
    (msg: WsMessage) => {
      // WS 推送池状态/任务进度时刷新总览（简单直接，1s 节流由后端保证）
      if (msg.type === 'task_progress' || msg.type === 'pool_status') void load()
    },
    [load],
  )

  useRealtime({ onMessage: onWsMessage, poll: load })

  if (loading) {
    return <div className="py-20 text-center text-muted-foreground">加载中…</div>
  }

  if (notImpl) {
    return (
      <PageShell title="Dashboard">
        <NotImplementedState feature="总览统计" />
      </PageShell>
    )
  }

  if (error || !stats) {
    return (
      <PageShell title="Dashboard">
        <EmptyState
          icon="error"
          title="无法获取统计数据"
          description={error ?? '未知错误'}
          actionLabel="重试"
          onAction={() => void load()}
        />
      </PageShell>
    )
  }

  const occupancy = stats.channels_total > 0 ? (stats.channels_in_use / stats.channels_total) * 100 : 0

  const cards = [
    { title: '总店铺数', value: stats.total_shops, icon: Store },
    { title: '待抓取数', value: stats.pending_shops, icon: Clock3 },
    { title: '今日新增', value: stats.today_new, icon: Sparkles },
    { title: '运行中任务', value: stats.running_tasks, icon: Activity },
  ]

  return (
    <PageShell title="Dashboard">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(({ title, value, icon: Icon }) => (
          <Card key={title}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
              <Icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold tabular-nums">{value.toLocaleString()}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">通道占用比</CardTitle>
            <Network className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {stats.channels_total > 0 ? (
              <>
                <div className="mb-2 text-3xl font-bold tabular-nums">
                  {stats.channels_in_use}
                  <span className="text-base font-normal text-muted-foreground"> / {stats.channels_total}</span>
                </div>
                <Progress value={occupancy} />
                <p className="mt-2 text-xs text-muted-foreground">{occupancy.toFixed(0)}% 通道使用中</p>
              </>
            ) : (
              <p className="py-4 text-sm text-muted-foreground">暂无通道，请先在厂商配置中添加代理厂商</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">近 1 小时采集速率</CardTitle>
            <Gauge className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {stats.rate_last_hour.length > 0 ? (
              <>
                <MiniTrend data={stats.rate_last_hour} width={520} height={80} className="w-full" />
                <p className="mt-2 text-xs text-muted-foreground">
                  当前 {stats.rate_last_hour[stats.rate_last_hour.length - 1]} 条/分钟
                </p>
              </>
            ) : (
              <p className="py-4 text-sm text-muted-foreground">暂无采集速率数据，运行任务后将在此展示</p>
            )}
          </CardContent>
        </Card>
      </div>
    </PageShell>
  )
}

function PageShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">{title}</h1>
      {children}
    </div>
  )
}
