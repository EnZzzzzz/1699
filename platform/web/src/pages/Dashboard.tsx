import { useState } from 'react'
import { api, useApiData, formatTime, type PipelinePeriod } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { format } from 'date-fns'
import type { DateRange } from 'react-day-picker'
import { zhCN } from 'react-day-picker/locale'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { Store, Contact, Hourglass, ArrowDownUp, Timer, MessagesSquare, AtSign, BadgeCheck, CalendarIcon } from 'lucide-react'

const REFRESH_MS = 30_000 // 30 秒自动刷新

const PERIOD_OPTIONS: { value: PipelinePeriod; label: string }[] = [
  { value: '1h', label: '最近 1 小时' },
  { value: '3h', label: '最近 3 小时' },
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
  // 自定义时间段：范围日历一次选齐起止日期，选齐后才发起请求（避免半截区间打后端）
  const [range, setRange] = useState<DateRange | undefined>()
  // 点「自定义时间段」直接弹出范围选择器；选齐起止后自动收起
  const [pickerOpen, setPickerOpen] = useState(false)
  const rangeComplete = Boolean(range?.from && range?.to)
  const customStart = range?.from ? format(range.from, 'yyyy-MM-dd') : ''
  const customEnd = range?.to ? format(range.to, 'yyyy-MM-dd') : ''
  const customReady = period !== 'custom' || rangeComplete
  const pipeline = useApiData(
    () => (customReady ? api.pipeline(period, customStart, customEnd) : Promise.resolve(null)),
    customReady ? REFRESH_MS : 0,
    [period, customStart, customEnd],
  )
  const fbPipeline = useApiData(
    () => (customReady ? api.fbPipeline(period, customStart, customEnd) : Promise.resolve(null)),
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
  const fp = customReady ? fbPipeline.data : null
  const periodLabel = PERIOD_OPTIONS.find((o) => o.value === period)?.label ?? period
  const rateUnit = pp?.rates.unit ?? '每小时'
  const fbRateUnit = fp?.rates.unit ?? '每小时'
  // 窗口内 WA 注册率（查号口径）
  const waCheckedTotal = fp ? fp.totals.wa_registered + fp.totals.wa_unregistered : 0
  const waWindowRate = fp && waCheckedTotal > 0
    ? `${((fp.totals.wa_registered / waCheckedTotal) * 100).toFixed(1)}%`
    : '—'
  // 汇总卡粒度标签：FB/X 与 1688 管道窗口一致，任取其一
  const windowBucket = (fp ?? pp)?.window.bucket
  const bucketLabel = windowBucket ? ` · 按${windowBucket === 'hour' ? '小时' : '天'}` : ''
  // 窗口采集汇总：FB/X 均为采集口径——窗口内采集数 = 已注册 + 未注册 + 待查；剩余待查为全表快照
  const collectSummary = [
    {
      label: 'FB 采号', value: fp?.totals.fb, cls: 'text-chart-fb',
      sub: fp ? `已注册 ${fp.totals.fb_wa_registered.toLocaleString()} · 未注册 ${fp.totals.fb_wa_unregistered.toLocaleString()} · 待查 ${fp.totals.fb_pending.toLocaleString()}` : undefined,
    },
    {
      label: 'X 采号', value: fp?.totals.x, cls: 'text-chart-x',
      sub: fp ? `已注册 ${fp.totals.x_wa_registered.toLocaleString()} · 未注册 ${fp.totals.x_wa_unregistered.toLocaleString()} · 待查 ${fp.totals.x_pending.toLocaleString()}` : undefined,
    },
    {
      label: '剩余待查', value: fp?.snapshot.pending, cls: 'text-amber-400',
      sub: fp ? `FB 未核实 ${fp.snapshot.fb_pending.toLocaleString()} · X 未核实 ${fp.snapshot.x_pending.toLocaleString()}` : undefined,
    },
  ]

  return (
    <div className="p-6">
      <PageHeader
        title="整体看板"
        desc={ov ? `数据时间：${formatTime(ov.ts)} · 每 30 秒自动刷新` : '每 30 秒自动刷新'}
      />

      {/* 时间段选择：预设快捷按钮 + 自定义区间（sticky 吸顶，滚动时不消失） */}
      <div className="sticky top-0 z-10 mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted px-4 py-3 shadow-xs">
        <span className="mr-1 text-sm text-muted-foreground">时间范围</span>
        {PERIOD_OPTIONS.map((o) => (
          <Button
            key={o.value}
            size="sm"
            variant={period === o.value ? 'default' : 'outline'}
            onClick={() => {
              setPeriod(o.value)
              if (o.value === 'custom') setPickerOpen(true)
            }}
          >
            {o.label}
          </Button>
        ))}
        {period === 'custom' && (
          <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5">
                <CalendarIcon className="h-4 w-4" />
                {rangeComplete
                  ? `${customStart} ~ ${customEnd}`
                  : '选择起止日期'}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="range"
                locale={zhCN}
                selected={range}
                onSelect={(r, day) => {
                  // DayPicker v9 首点即补成单日区间，接管为「首点定起点、次点定终点」，
                  // 选齐后收起弹层；已有完整区间时再点任意日期重新开始
                  const restarting = !range?.from || Boolean(range.from && range.to)
                  const next = restarting ? { from: day, to: undefined } : r
                  setRange(next)
                  if (next?.from && next?.to) setPickerOpen(false)
                }}
                numberOfMonths={2}
                defaultMonth={range?.from}
              />
            </PopoverContent>
          </Popover>
        )}
        {pp && (
          <span className="ml-auto text-xs text-muted-foreground">
            窗口：{pp.window.start} ~ {pp.window.end} · 按{pp.window.bucket === 'hour' ? '小时' : '天'}统计
          </span>
        )}
      </div>

      {/* ==================== FB / X 采号管道（置顶） ==================== */}
      <h2 className="mt-6 text-base font-semibold">FB / X 采号管道</h2>

      {/* 总数 + 速率卡片行 */}
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard title="FB 采号总数" icon={MessagesSquare}>
          <div className="text-3xl font-bold text-chart-fb">
            {fp ? `${fp.snapshot.fb_registered.toLocaleString()}/${fp.snapshot.fb_total.toLocaleString()}` : '—'}
            <span className="ml-1 text-sm font-normal text-muted-foreground">条</span>
          </div>
          {fp && (
            <p className="mt-1 text-xs text-muted-foreground">
              已注册/总数 · 速率 {fp.rates.fb.toFixed(1)} 条/{fbRateUnit.replace('每', '')} · 窗口内 {fp.totals.fb.toLocaleString()} 条（{periodLabel}）
            </p>
          )}
        </StatCard>

        <StatCard title="X 采号总数" icon={AtSign}>
          <div className="text-3xl font-bold text-chart-x">
            {fp ? `${fp.snapshot.x_registered.toLocaleString()}/${fp.snapshot.x_total.toLocaleString()}` : '—'}
            <span className="ml-1 text-sm font-normal text-muted-foreground">条</span>
          </div>
          {fp && (
            <p className="mt-1 text-xs text-muted-foreground">
              已注册/总数 · 速率 {fp.rates.x.toFixed(1)} 条/{fbRateUnit.replace('每', '')} · 窗口内 {fp.totals.x.toLocaleString()} 条（{periodLabel}）
            </p>
          )}
        </StatCard>

        <StatCard title="WA 查号速率" icon={BadgeCheck}>
          <div className="text-3xl font-bold text-emerald-400">
            {fp ? fp.rates.wa_check.toFixed(1) : '—'}
            <span className="ml-1 text-sm font-normal text-muted-foreground">号/{fbRateUnit.replace('每', '')}</span>
          </div>
          {fp && (
            <p className="mt-1 text-xs text-muted-foreground">
              窗口注册率 {waWindowRate} · 待确认 {fp.snapshot.pending.toLocaleString()}
              {fp.snapshot.reg_rate !== null && ` · 全表注册率 ${(fp.snapshot.reg_rate * 100).toFixed(1)}%`}
            </p>
          )}
        </StatCard>
      </div>

      {/* 窗口采集数量汇总卡 */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-sm font-medium">采集数量（{periodLabel}{bucketLabel}）</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {collectSummary.map((s) => (
              <div key={s.label}>
                <div className={`text-3xl font-bold ${s.cls}`}>
                  {s.value !== undefined ? s.value.toLocaleString() : '—'}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{s.label}</div>
                {s.sub && <div className="mt-0.5 text-xs text-muted-foreground">{s.sub}</div>}
              </div>
            ))}
          </div>
          {/* 窗口成本估算：FB/X 采集按当日单号成本折算，WA 按真实单价 × 窗口查号数 */}
          {fp?.costs && (
            <div className="mt-4 border-t border-border pt-4">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {[
                  { label: 'FB 采集成本', value: fp.costs.fb, per: fp.costs.fb_per, cls: 'text-chart-fb' },
                  { label: 'X 采集成本', value: fp.costs.x, per: fp.costs.x_per, cls: 'text-chart-x' },
                  { label: 'WA 校验成本', value: fp.costs.wa, per: fp.costs.wa_per, cls: 'text-emerald-400' },
                  { label: '合计', value: fp.costs.total, per: fp.costs.per_registered, cls: '' },
                ].map((c) => (
                  <div key={c.label}>
                    <div className={`text-xl font-semibold ${c.cls}`}>
                      ${c.value.toFixed(2)}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">{c.label}（估算）</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      每个样本约 {c.per !== null ? `$${c.per.toFixed(4)}` : '—'}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                口径：FB/X 为当日费用按窗口采集量折算，WA 为窗口实查数 × 单价；每个样本 = 该渠道窗口成本 ÷ 窗口已注册样本数（WA 为校验号数）
                 · memo23 $0.0019/结果 + SERP $1.50/1k 条 + X $0.15/1k 行 + WA $0.004/号
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* FB / X 采集量对比柱状图 */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            FB / X 采集量（{periodLabel}{fp ? ` · 按${fp.window.bucket === 'hour' ? '小时' : '天'}` : ''}）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!customReady ? (
            <EmptyState text="请选择完整的起止日期" />
          ) : fbPipeline.error && !fp ? (
            <ErrorState message={fbPipeline.error} onRetry={fbPipeline.reload} />
          ) : !fp || fp.buckets.length === 0 ? (
            <EmptyState text="该时间窗口内暂无 FB/X 采集数据" />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={fp.buckets} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" />
                  <XAxis dataKey="label" tick={{ fontSize: 12, fill: 'hsl(var(--chart-axis))' }} />
                  <YAxis tick={{ fontSize: 12, fill: 'hsl(var(--chart-axis))' }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: 'hsl(var(--chart-tooltip-bg))', border: '1px solid hsl(var(--chart-tooltip-border))', borderRadius: 8 }}
                    labelStyle={{ color: 'hsl(var(--foreground))' }}
                  />
                  <Legend />
                  <Bar dataKey="fb" name="FB" fill="hsl(var(--chart-fb))" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="x" name="X" fill="hsl(var(--chart-x))" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      {/* WA 查号转化堆叠柱状图 */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            WA 查号转化（{periodLabel}{fp ? ` · 按${fp.window.bucket === 'hour' ? '小时' : '天'}` : ''} · 窗口注册率 {waWindowRate}）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!customReady ? (
            <EmptyState text="请选择完整的起止日期" />
          ) : fbPipeline.error && !fp ? (
            <ErrorState message={fbPipeline.error} onRetry={fbPipeline.reload} />
          ) : !fp || fp.buckets.length === 0 ? (
            <EmptyState text="该时间窗口内暂无 WA 查号数据" />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={fp.buckets} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--chart-grid))" />
                  <XAxis dataKey="label" tick={{ fontSize: 12, fill: 'hsl(var(--chart-axis))' }} />
                  <YAxis tick={{ fontSize: 12, fill: 'hsl(var(--chart-axis))' }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: 'hsl(var(--chart-tooltip-bg))', border: '1px solid hsl(var(--chart-tooltip-border))', borderRadius: 8 }}
                    labelStyle={{ color: 'hsl(var(--foreground))' }}
                  />
                  <Legend />
                  <Bar dataKey="wa_registered" name="已注册" stackId="wa" fill="hsl(var(--chart-consumed))" radius={[0, 0, 0, 0]} />
                  <Bar dataKey="wa_unregistered" name="未注册" stackId="wa" fill="hsl(var(--status-danger))" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ==================== 1688 / 其他来源 ==================== */}
      <h2 className="mt-8 text-base font-semibold">1688 店铺采集管道</h2>

      {/* 状态卡片行 */}
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
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
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted-foreground">WhatsApp：</span>
                <Badge variant="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">已注册 {ov.contacts.wa_registered.toLocaleString()}</Badge>
                <Badge variant="secondary">未注册 {ov.contacts.wa_unregistered.toLocaleString()}</Badge>
                <Badge variant="outline" className="text-muted-foreground">未查 {ov.contacts.wa_unchecked.toLocaleString()}</Badge>
              </div>
            </div>
          )}
        </StatCard>
      </div>

      {/* 管道指标行 */}
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="border-amber-500/40">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">待采集</CardTitle>
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

        <StatCard title="已入库商店数量" icon={Timer}>
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

        <StatCard title="已采集" icon={ArrowDownUp}>
          <div className="text-3xl font-bold text-emerald-400">
            {pp ? pp.totals.consumed.toLocaleString() : '—'}
            <span className="ml-1 text-sm font-normal text-muted-foreground">条</span>
          </div>
          {pp && pp.rates.collect > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              速率 {pp.rates.consume.toFixed(1)} 条/{rateUnit.replace('每', '')} · 已采集/入库比：{(pp.rates.consume / pp.rates.collect).toFixed(2)}
              {pp.rates.consume >= pp.rates.collect ? ' · 进度跟得上' : ' · 待采集在增长'}
            </p>
          )}
        </StatCard>
      </div>

      {/* 采集/消耗对比柱状图 */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            已入库商店 / 已采集对比（{periodLabel}{pp ? ` · 按${pp.window.bucket === 'hour' ? '小时' : '天'}` : ''}）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!customReady ? (
            <EmptyState text="请选择完整的起止日期" />
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
                  <Bar dataKey="collected" name="已入库商店" fill="hsl(var(--chart-collected))" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="consumed" name="已采集" fill="hsl(var(--chart-consumed))" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
