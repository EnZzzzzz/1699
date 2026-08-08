// 调度器看板页：daemon 存活 + 队列深度 + 消费者状态（P4）
// 数据源 /api/dispatcher/status + /api/dispatcher/consumers，自适应轮询
//（daemon 在线 5s、离线 30s）。遵 DESIGN.md：PageHeader → 内容 → PageState 三态。
import { useEffect, useMemo, useState } from 'react'
import { Activity, Boxes, CircleDot, Clock } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { PageHeader, LoadingState, ErrorState } from '@/components/PageState'
import { api, useApiData, type DispatcherConsumer } from '@/lib/api'
import { workerChip } from './tasks/task-ui'
import { cn } from '@/lib/utils'

const OFFLINE_SECONDS = 30

function StatCard({ title, icon: Icon, children }: {
  title: string
  icon: React.ElementType
  children: React.ReactNode
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

// 冷却倒计时：本地 1s setInterval 倒数，展示「站点 mm:ss」
function CooldownCountdown({ until }: { until: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const sec = Math.max(0, Math.round((until * 1000 - now) / 1000))
  if (sec <= 0) return <span className="text-xs text-muted-foreground">已到期</span>
  const mm = Math.floor(sec / 60)
  const ss = String(sec % 60).padStart(2, '0')
  return (
    <span className="text-xs text-amber-600 dark:text-amber-400">
      {mm}:{ss}
    </span>
  )
}

// 消费者冷却徽标：cooldowns 中未到期的站点 → amber 徽标 + 倒计时
function CooldownBadges({ cooldowns }: { cooldowns: Record<string, number> }) {
  const entries = Object.entries(cooldowns ?? {})
    .filter(([, ts]) => ts * 1000 > Date.now())
    .sort((a, b) => a[0].localeCompare(b[0]))
  if (entries.length === 0) return <span className="text-xs text-muted-foreground">—</span>
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {entries.map(([site, ts]) => (
        <Badge
          key={site}
          variant="outline"
          className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400"
        >
          {site} <CooldownCountdown until={ts} />
        </Badge>
      ))}
    </div>
  )
}

// 消费者表：chip + kind + 通道/出口 IP + 当前队列+工作项 + 冷却
function ConsumersTable({ consumers }: { consumers: DispatcherConsumer[] }) {
  return (
    <div className="rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>消费者</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>通道 / 出口 IP</TableHead>
            <TableHead>当前工作项</TableHead>
            <TableHead>冷却中站点</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {consumers.map((c) => (
            <TableRow key={c.consumer_id} className={c.offline ? 'opacity-60' : undefined}>
              <TableCell>
                <div className="flex items-center gap-1.5">
                  {workerChip(c.consumer_id)}
                  <span className="text-xs text-muted-foreground">{c.consumer_id}</span>
                  {c.offline && <Badge variant="outline">已离线</Badge>}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant="secondary">{c.kind}</Badge>
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {c.tunnel ?? c.exit_ip ?? '—'}
              </TableCell>
              <TableCell>
                {c.current_queue ? (
                  <div className="text-xs">
                    <span className="font-mono">{c.current_queue}</span>
                    {c.current_item_id != null && (
                      <span className="text-muted-foreground"> #{c.current_item_id}</span>
                    )}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                <CooldownBadges cooldowns={c.cooldowns} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export default function Dispatcher() {
  // 自适应轮询：daemon 在线 5s、离线 30s（照抄 Tasks 模式）
  const [hasActive, setHasActive] = useState(true)
  const status = useApiData(
    api.dispatcherStatus,
    hasActive ? 5000 : 30000,
  )
  const consumers = useApiData(
    api.dispatcherConsumers,
    hasActive ? 5000 : 30000,
  )

  // daemon 存活状态回写轮询节奏
  useEffect(() => {
    setHasActive(status.data?.daemon_alive ?? false)
  }, [status.data?.daemon_alive])

  const pendingTotal = useMemo(() => {
    const d = status.data?.queue_depth ?? {}
    return Object.values(d).reduce(
      (sum, q) => sum + (q.pending ?? 0) + (q.claimed ?? 0), 0)
  }, [status.data])

  if (status.loading && !status.data) return <div className="p-6"><LoadingState /></div>
  if (status.error && !status.data) {
    return (
      <div className="p-6">
        <PageHeader title="调度器" />
        <ErrorState message={status.error} onRetry={status.reload} />
      </div>
    )
  }

  const st = status.data
  const queueRows = Object.entries(st?.queue_depth ?? {}).sort((a, b) =>
    a[0].localeCompare(b[0]))
  const online = st?.daemon_alive ?? false

  return (
    <div className="p-6">
      <PageHeader
        title="调度器"
        desc={online
          ? 'daemon 在线 · 每 5 秒自动刷新'
          : 'daemon 离线 · 每 30 秒自动刷新'}
      />

      {/* 顶部 StatCard 行 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard title="daemon 状态" icon={Activity}>
          <div className="flex items-center gap-2">
            <span className={cn('h-2.5 w-2.5 rounded-full',
              online ? 'bg-sky-500' : 'bg-muted')} />
            <span className={cn('text-2xl font-bold',
              online ? 'text-sky-600 dark:text-sky-400' : 'text-muted-foreground')}>
              {online ? '在线' : '离线'}
            </span>
          </div>
        </StatCard>
        <StatCard title="工作项积压" icon={Boxes}>
          <div className="text-2xl font-bold">
            {pendingTotal.toLocaleString()}
            <span className="ml-2 text-sm font-normal text-muted-foreground">pending+claimed</span>
          </div>
        </StatCard>
        <StatCard title="今日完成" icon={CircleDot}>
          <div className="text-2xl font-bold">
            {(st?.today_done ?? 0).toLocaleString()}
            <span className="ml-2 text-sm font-normal text-muted-foreground">工作项</span>
          </div>
        </StatCard>
      </div>

      {/* 队列深度表 */}
      <div className="mt-6">
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">队列深度</h2>
        <div className="rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>队列</TableHead>
                <TableHead className="text-right">pending</TableHead>
                <TableHead className="text-right">claimed</TableHead>
                <TableHead className="text-right">done</TableHead>
                <TableHead className="text-right">failed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {queueRows.map(([queue, counts]) => (
                <TableRow key={queue}>
                  <TableCell className="font-mono text-xs">{queue}</TableCell>
                  <TableCell className="text-right tabular-nums">{counts.pending ?? 0}</TableCell>
                  <TableCell className="text-right tabular-nums">{counts.claimed ?? 0}</TableCell>
                  <TableCell className="text-right tabular-nums">{counts.done ?? 0}</TableCell>
                  <TableCell className={cn('text-right tabular-nums',
                    (counts.failed ?? 0) > 0 && 'text-destructive')}>
                    {counts.failed ?? 0}
                  </TableCell>
                </TableRow>
              ))}
              {queueRows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                    暂无工作项
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* 消费者表 */}
      <div className="mt-6">
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">消费者</h2>
        {consumers.loading && !consumers.data ? (
          <LoadingState />
        ) : consumers.error && !consumers.data ? (
          <ErrorState message={consumers.error} onRetry={consumers.reload} />
        ) : (
          <ConsumersTable consumers={consumers.data ?? []} />
        )}
      </div>

      <p className="mt-4 flex items-center gap-1 text-xs text-muted-foreground">
        <Clock className="h-3 w-3" />
        daemon 日志：platform/logs/daemon.log · 心跳超 {OFFLINE_SECONDS}s 判定离线
      </p>
    </div>
  )
}
