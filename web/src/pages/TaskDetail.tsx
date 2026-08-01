import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, errorMessage, isNotImplemented } from '@/api/client'
import { getParamSpecs, paramLabel } from '@/api/paramSpecs'
import type { Board, ContactFetchStatusCounts, ParamSpecs, TaskDetail, WsMessage } from '@/api/types'
import { TaskStatusBadge, TaskTypeLabel, ChannelStatusBadge } from '@/components/StatusBadge'
import { EmptyState, NotImplementedState } from '@/components/EmptyState'
import { useRealtime } from '@/hooks/useRealtime'
import { useTaskActions, canStop, needsConfirm } from '@/hooks/useTaskActions'
import { TaskEventsCard } from '@/components/TaskEventsCard'
import { ArrowLeft, HandMetal, AlertCircle, CheckCircle2 } from 'lucide-react'

const ACTIVE_STATUSES = new Set(['running', 'waiting_channel', 'stopping'])
const TERMINAL_STATUSES = new Set(['done', 'failed', 'stopped'])

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [notImpl, setNotImpl] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/tasks/${id}`)
      setTask(res.data as TaskDetail)
      setNotFound(false)
      setNotImpl(false)
      setError(null)
    } catch (e) {
      if (isNotImplemented(e)) {
        // 区分 404（任务不存在）与 501（端点未实现）
        if ((e as { response?: { status?: number } }).response?.status === 404) {
          setNotFound(true)
        } else {
          setNotImpl(true)
        }
      } else {
        setError(errorMessage(e))
      }
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const active = task != null && ACTIVE_STATUSES.has(task.status)

  const onWsMessage = useCallback(
    (msg: WsMessage) => {
      if (msg.type === 'task_progress' && msg.task.id === Number(id)) void load()
    },
    [id, load],
  )

  useRealtime({ onMessage: onWsMessage })

  // 活动状态期间 2s 轮询刷新 board/状态（WS 不保证推送终态，故不依赖 WS）；
  // 到达终态（active 变 false）后自动停止
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => void load(), 2000)
    return () => clearInterval(timer)
  }, [active, load])

  const { stopTask, confirmTask, confirmingId } = useTaskActions(() => void load())

  if (loading) return <div className="py-20 text-center text-muted-foreground">加载中…</div>
  if (notImpl) return <NotImplementedState feature="任务详情" />
  if (notFound) {
    return <EmptyState icon="error" title="任务不存在" description={`未找到任务 #${id}`} actionLabel="返回列表" onAction={() => navigate('/tasks')} />
  }
  if (error || !task) {
    return <EmptyState icon="error" title="无法获取任务详情" description={error ?? '未知错误'} actionLabel="重试" onAction={() => void load()} />
  }

  const board = task.board

  return (
    <div className="space-y-4">
      {/* 头部 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={() => navigate('/tasks')}>
            <ArrowLeft className="mr-1.5 h-4 w-4" />
            返回列表
          </Button>
          <h1 className="text-2xl font-semibold">
            任务 <span className="font-mono">#{task.id}</span>
          </h1>
          <Badge variant="outline">
            <TaskTypeLabel type={task.type} />
          </Badge>
          <TaskStatusBadge status={task.status} />
          {/* 终态后以 status 为准，不再展示运行中的 phase 过程态 */}
          {!TERMINAL_STATUSES.has(task.status) && (
            <PhaseChip phase={board?.phase ?? task.progress?.phase ?? null} />
          )}
        </div>
        <div className="flex gap-2">
          {needsConfirm(task) && (
            <Button
              size="sm"
              className="animate-pulse bg-amber-500 text-white hover:bg-amber-600"
              disabled={confirmingId === task.id}
              onClick={() => void confirmTask(task)}
            >
              <HandMetal className="mr-1.5 h-4 w-4" />
              {confirmingId === task.id ? '确认中…' : '确认开始采集'}
            </Button>
          )}
          {canStop(task) && (
            <Button variant="destructive" size="sm" onClick={() => void stopTask(task)}>
              停止
            </Button>
          )}
        </div>
      </div>

      {task.error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>错误信息</AlertTitle>
          <AlertDescription>{task.error}</AlertDescription>
        </Alert>
      )}

      {board ? (
        <>
          <OverviewSection task={task} board={board} />
          <ChannelsSection board={board} />
        </>
      ) : (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            实时看板数据暂不可用（后端未返回 board 对象），下方展示任务基础信息。
          </CardContent>
        </Card>
      )}

      <TaskEventsCard taskId={task.id} status={task.status} />

      {board && (board.type === 'shop_crawl' ? <ShopCrawlSection board={board} /> : <ContactFetchSection board={board} />)}

      <ParamsSection task={task} />
    </div>
  )
}

function PhaseChip({ phase }: { phase: string | null | undefined }) {
  if (!phase) return null
  if (phase === 'waiting_confirm') {
    return <Badge className="bg-amber-500 text-white hover:bg-amber-500">等待人工确认</Badge>
  }
  return <Badge variant="outline">{phase}</Badge>
}

/** 公共看板区 */
function OverviewSection({ task, board }: { task: TaskDetail; board: Board }) {
  const pct = board.total && board.total > 0 ? Math.min(100, (board.collected / board.total) * 100) : task.status === 'done' ? 100 : 0
  const stats: { label: string; value: string }[] = [
    { label: '已采集', value: board.collected.toLocaleString() },
    { label: '目标', value: board.total != null ? board.total.toLocaleString() : '-' },
    { label: '剩余', value: board.remaining != null ? Math.max(0, board.remaining).toLocaleString() : '-' },
    { label: '每分钟速率', value: board.per_minute > 0 ? board.per_minute.toFixed(1) : '0' },
    { label: '已运行时长', value: fmtSec(board.elapsed_seconds) },
    { label: '预计剩余', value: fmtSec(board.eta_seconds) },
  ]
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">采集进度</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {stats.map((s) => (
            <div key={s.label}>
              <p className="text-xs text-muted-foreground">{s.label}</p>
              <p className="mt-1 text-xl font-semibold tabular-nums">{s.value}</p>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Progress value={pct} className="h-3" />
          <span className="w-12 text-sm tabular-nums text-muted-foreground">{pct.toFixed(0)}%</span>
        </div>
      </CardContent>
    </Card>
  )
}

/** 占用通道卡 */
function ChannelsSection({ board }: { board: Board }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">占用通道（{board.channels.length}）</CardTitle>
      </CardHeader>
      <CardContent>
        {board.channels.length === 0 ? (
          <p className="py-2 text-sm text-muted-foreground">未占用通道</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>隧道入口</TableHead>
                <TableHead>出口 IP</TableHead>
                <TableHead>厂商</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">近 5 分钟请求</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {board.channels.map((ch) => {
                const direct = ch.tunnel == null
                return (
                  <TableRow key={ch.id}>
                    <TableCell className="font-mono text-sm">{direct ? '本机直连' : ch.tunnel}</TableCell>
                    <TableCell className="font-mono text-sm">{ch.exit_ip ?? '-'}</TableCell>
                    <TableCell>{ch.provider_name}</TableCell>
                    <TableCell>
                      <ChannelStatusBadge status={ch.status} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{ch.requests_5m.toLocaleString()}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

/** shop_crawl 专属区 */
function ShopCrawlSection({ board }: { board: Extract<Board, { type: 'shop_crawl' }> }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">店铺采集</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">目标店铺数</span>
            <span className="font-semibold tabular-nums">{board.target.toLocaleString()}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">下游待抓联系方式（全库）</span>
            <span className="font-semibold tabular-nums">{board.pending_contacts.toLocaleString()}</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">类目进度（Top {board.categories.length}）</CardTitle>
        </CardHeader>
        <CardContent>
          {board.categories.length === 0 ? (
            <p className="py-2 text-sm text-muted-foreground">暂无类目进度数据</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>类目关键词</TableHead>
                  <TableHead className="text-right">下一页</TableHead>
                  <TableHead className="text-right">状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {board.categories.map((c) => (
                  <TableRow key={c.keyword}>
                    <TableCell>{c.keyword}</TableCell>
                    <TableCell className="text-right tabular-nums">第 {c.next_page} 页</TableCell>
                    <TableCell className="text-right">
                      {c.exhausted ? (
                        <Badge variant="secondary" className="gap-1">
                          <CheckCircle2 className="h-3 w-3" />
                          已采完
                        </Badge>
                      ) : (
                        <Badge variant="outline">采集中</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/** contact_fetch 专属区 */
const STATUS_META: { key: keyof ContactFetchStatusCounts; label: string; color: string }[] = [
  { key: 'pending', label: '待抓取', color: 'bg-slate-400' },
  { key: 'in_progress', label: '进行中', color: 'bg-blue-500' },
  { key: 'done', label: '已完成', color: 'bg-emerald-500' },
  { key: 'no_contact', label: '无联系方式', color: 'bg-amber-500' },
  { key: 'failed', label: '失败', color: 'bg-red-500' },
  { key: 'blocked', label: '被风控', color: 'bg-zinc-800' },
]

function ContactFetchSection({ board }: { board: Extract<Board, { type: 'contact_fetch' }> }) {
  const counts = board.status_counts
  const totalAll = STATUS_META.reduce((sum, m) => sum + (counts[m.key] ?? 0), 0)
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">联系方式抓取</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4 sm:max-w-md">
          <div>
            <p className="text-xs text-muted-foreground">本任务成功</p>
            <p className="mt-1 text-xl font-semibold tabular-nums text-emerald-600">{board.task_done.toLocaleString()}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">本任务失败</p>
            <p className="mt-1 text-xl font-semibold tabular-nums text-red-600">{board.task_failed.toLocaleString()}</p>
          </div>
        </div>

        <div>
          <p className="mb-2 text-xs text-muted-foreground">全库状态分布（共 {totalAll.toLocaleString()} 家店铺）</p>
          {totalAll > 0 && (
            <div className="mb-3 flex h-3 w-full overflow-hidden rounded-full">
              {STATUS_META.map((m) => {
                const v = counts[m.key] ?? 0
                if (v === 0) return null
                return (
                  <div
                    key={m.key}
                    className={`${m.color} h-full`}
                    style={{ width: `${(v / totalAll) * 100}%` }}
                    title={`${m.label} ${v.toLocaleString()}`}
                  />
                )
              })}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {STATUS_META.map((m) => (
              <Badge key={m.key} variant="outline" className="gap-1.5">
                <span className={`h-2 w-2 rounded-full ${m.color}`} />
                {m.label} {(counts[m.key] ?? 0).toLocaleString()}
              </Badge>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/** 参数卡（键中文化：优先 param-specs 的 label，取不到用内置映射兜底） */
function ParamsSection({ task }: { task: TaskDetail }) {
  const entries = Object.entries(task.params ?? {})
  const [specs, setSpecs] = useState<ParamSpecs | null>(null)

  useEffect(() => {
    let cancelled = false
    void getParamSpecs().then(({ specs: s }) => {
      if (!cancelled) setSpecs(s)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">任务参数</CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">无参数</p>
        ) : (
          <dl className="grid gap-x-8 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
            {entries.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 text-sm">
                <dt className="text-muted-foreground">{paramLabel(k, specs)}</dt>
                <dd className="font-medium">
                  {typeof v === 'boolean' ? (v ? '是' : '否') : String(v)}
                </dd>
              </div>
            ))}
          </dl>
        )}
        <div className="mt-4 flex flex-wrap gap-x-8 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
          <span>创建时间 {task.created_at}</span>
          <span>开始时间 {task.started_at ?? '-'}</span>
          <span>结束时间 {task.finished_at ?? '-'}</span>
          {task.celery_id && <span className="font-mono">celery: {task.celery_id}</span>}
        </div>
      </CardContent>
    </Card>
  )
}

/** 秒数 -> x分x秒 / x时x分；null 显示 - */
function fmtSec(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return '-'
  if (sec >= 3600) return `${Math.floor(sec / 3600)}时${Math.floor((sec % 3600) / 60)}分`
  if (sec >= 60) return `${Math.floor(sec / 60)}分${sec % 60}秒`
  return `${sec}秒`
}
