import { useState } from 'react'
import { api, useApiData, formatTime, type PipelinePeriod } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { Store, Contact, Activity, Hourglass, ArrowDownUp, Timer } from 'lucide-react'

const REFRESH_MS = 30_000 // 30 秒自动刷新

const PERIOD_OPTIONS: { value: PipelinePeriod; label: string }[] = [
  { value: '12h', label: '最近 12 小时' },
  { value: 'today', label: '今天' },
  { value: 'yesterday', label: '昨天' },
  { value: '7d', label: '最近 7 天' },
  { value: '30d', label: '最近 30 天' },
  { value: 'custom', label: '自定义时间段' },
]

function StatCard({ title, children, icon: Icon }: { title: string; children: React.ReactNode; icon: React.ElementType }) {
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

export default function Dashboard() {
  const overview = useApiData(api.overview, REFRESH_MS)
  const [period, setPeriod] = useState<PipelinePeriod>('12h')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const customReady = period !== 'custom' || customStart !== ''
  const pipeline = useApiData(
    () => api.pipeline(period, customStart, customEnd),
    customReady ? REFRESH_MS : 0,
    [period, customStart, customEnd],
  )

  if (overview.loading && !overview.data) return <div className="p-6"><LoadingState /></div>
  if (overview.error && !overview.data) {
    return (
      <div className="p-6">
        <PageHeader title="整体看板" />
        <ErrorState message={overview.error} onRetry={overview.reload} />
      </div>
    )
  }

  const ov = overview.data
  const pp = customReady ? pipeline.data : null
  const periodLabel = PERIOD_OPTIONS.find((o) => o.value === period)?.label ?? period
  const rateUnit = pp?.rates.unit ?? '每小时'

  return (
    <div className="p-6">
      <PageHeader
        title="整体看板"
        desc={ov ? `数据时间：${formatTime(ov.ts)} · 每 30 秒自动刷新` : '每 30 秒自动刷新'}
      />

      {/* 状态卡片行 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard title="店铺采集状态" icon={Store}>
          {ov && (
            <div>
              <div className="mb-2 text-2xl font-bold">{ov.shops.total.toLocaleString()} <span className="text-sm font-normal text-muted-foreground">总数</span></div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">待采集 {ov.shops.pending}</Badge>
                <Badge className="bg-emerald-600 hover:bg-emerald-600">已完成 {ov.shops.done}</Badge>
                <Badge className="bg-amber-600 hover:bg-amber-600">无联系方式 {ov.shops.no_contact}</Badge>
                <Badge variant="destructive">失败 {ov.shops.failed}</Badge>
              </div>
            </div>
          )}
        </StatCard>

        <StatCard title="联系方式" icon={Contact}>
          {ov && (
            <div>
              <div className="mb-2 text-2xl font-bold">{ov.contacts.total.toLocaleString()} <span className="text-sm font-normal text-muted-foreground">总数</span></div>
              <div className="text-sm text-muted-foreground">
                含手机号 <span className="font-semibold text-foreground">{ov.contacts.with_mobile.toLocaleString()}</span>
                {ov.contacts.total > 0 && `（${((ov.contacts.with_mobile / ov.contacts.total) * 100).toFixed(1)}%）`}
              </div>
            </div>
          )}
        </StatCard>

        <StatCard title="任务运行" icon={Activity}>
          {ov && (
            <div>
              <div className="mb-2 text-2xl font-bold">{ov.tasks.running} <span className="text-sm font-normal text-muted-foreground">运行中</span></div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">排队 {ov.tasks.pending}</Badge>
                <Badge className="bg-emerald-600 hover:bg-emerald-600">完成 {ov.tasks.done}</Badge>
                <Badge variant="destructive">失败 {ov.tasks.failed}</Badge>
              </div>
            </div>
          )}
        </StatCard>
      </div>

      {/* 时间段选择：预设快捷按钮 + 自定义区间 */}
      <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3">
        <span className="mr-1 text-sm text-muted-foreground">时间范围</span>
        {PERIOD_OPTIONS.map((o) => (
          <Button
            key={o.value}
            size="sm"
            variant={period === o.value ? 'default' : 'outline'}
            onClick={() => setPeriod(o.value)}
          >
            {o.label}
          </Button>
        ))}
        {period === 'custom' && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Input
              type="datetime-local"
              className="h-9 w-52 bg-background"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
            />
            至
            <Input
              type="datetime-local"
              className="h-9 w-52 bg-background"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
            />
          </div>
        )}
        {pp && (
          <span className="ml-auto text-xs text-muted-foreground">
            窗口：{pp.window.start} ~ {pp.window.end} · 按{pp.window.bucket === 'hour' ? '小时' : '天'}统计
          </span>
        )}
      </div>

      {/* 管道指标行 */}
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="border-amber-500/40">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">待处理积压（pending 队列）</CardTitle>
            <Hourglass className="h-4 w-4 text-amber-400" />
          </CardHeader>
          <CardContent>
            <div className="text-4xl font-bold text-amber-400">
              {pp ? pp.backlog.toLocaleString() : '—'}
            </div>
            {pp && (
              <p className="mt-1 text-xs text-muted-foreground">
                统计窗口：{periodLabel}
              </p>
            )}
          </CardContent>
        </Card>

        <StatCard title="采集" icon={Timer}>
          <div className="text-3xl font-bold text-sky-400">
            {pp ? pp.totals.collected.toLocaleString() : '—'}
            <span className="ml-1 text-sm font-normal text-muted-foreground">条</span>
          </div>
          {pp && (
            <p className="mt-1 text-xs text-muted-foreground">
              速率 {pp.rates.collect.toFixed(1)} 条/{rateUnit.replace('每', '')}
            </p>
          )}
        </StatCard>

        <StatCard title="消耗" icon={ArrowDownUp}>
          <div className="text-3xl font-bold text-emerald-400">
            {pp ? pp.totals.consumed.toLocaleString() : '—'}
            <span className="ml-1 text-sm font-normal text-muted-foreground">条</span>
          </div>
          {pp && pp.rates.collect > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              速率 {pp.rates.consume.toFixed(1)} 条/{rateUnit.replace('每', '')} · 消耗/采集比：{(pp.rates.consume / pp.rates.collect).toFixed(2)}
              {pp.rates.consume >= pp.rates.collect ? ' · 消化能力充足' : ' · 积压在增长'}
            </p>
          )}
        </StatCard>
      </div>

      {/* 采集/消耗对比柱状图 */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            采集 / 消耗对比（{periodLabel}{pp ? ` · 按${pp.window.bucket === 'hour' ? '小时' : '天'}` : ''}）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!customReady ? (
            <EmptyState text="请选择自定义的开始时间" />
          ) : pipeline.error && !pp ? (
            <ErrorState message={pipeline.error} onRetry={pipeline.reload} />
          ) : !pp || pp.buckets.length === 0 ? (
            <EmptyState text="该时间窗口内暂无采集/消耗数据" />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pp.buckets} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" />
                  <XAxis dataKey="label" tick={{ fontSize: 12, fill: 'hsl(var(--chart-axis))' }} />
                  <YAxis tick={{ fontSize: 12, fill: 'hsl(var(--chart-axis))' }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: 'hsl(var(--chart-tooltip-bg))', border: '1px solid hsl(var(--chart-tooltip-border))', borderRadius: 8 }}
                    labelStyle={{ color: 'hsl(var(--foreground))' }}
                  />
                  <Legend />
                  <Bar dataKey="collected" name="采集" fill="hsl(var(--chart-collected))" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="consumed" name="消耗" fill="hsl(var(--chart-consumed))" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
