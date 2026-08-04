import { api, useApiData, formatTime } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { Store, Contact, Activity, Hourglass, ArrowDownUp, Timer } from 'lucide-react'

const REFRESH_MS = 30_000 // 30 秒自动刷新

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
  const pipeline = useApiData(() => api.pipeline(12), REFRESH_MS)

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
  const pp = pipeline.data

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
                统计窗口：近 {pp.window.hours} 小时
              </p>
            )}
          </CardContent>
        </Card>

        <StatCard title="采集速率" icon={Timer}>
          <div className="text-3xl font-bold text-sky-400">
            {pp ? pp.rates.collect_per_hour.toFixed(1) : '—'}
            <span className="ml-1 text-sm font-normal text-muted-foreground">条/小时</span>
          </div>
        </StatCard>

        <StatCard title="消耗速率" icon={ArrowDownUp}>
          <div className="text-3xl font-bold text-emerald-400">
            {pp ? pp.rates.consume_per_hour.toFixed(1) : '—'}
            <span className="ml-1 text-sm font-normal text-muted-foreground">条/小时</span>
          </div>
          {pp && pp.rates.collect_per_hour > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              消耗/采集比：{(pp.rates.consume_per_hour / pp.rates.collect_per_hour).toFixed(2)}
              {pp.rates.consume_per_hour >= pp.rates.collect_per_hour ? ' · 消化能力充足' : ' · 积压在增长'}
            </p>
          )}
        </StatCard>
      </div>

      {/* 逐小时对比柱状图 */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-sm font-medium">逐小时采集 / 消耗对比（近 12 小时）</CardTitle>
        </CardHeader>
        <CardContent>
          {pipeline.error && !pp ? (
            <ErrorState message={pipeline.error} onRetry={pipeline.reload} />
          ) : !pp || pp.hourly.length === 0 ? (
            <EmptyState text="该时间窗口内暂无采集/消耗数据" />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pp.hourly} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
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
