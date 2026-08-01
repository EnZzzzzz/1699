import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, errorMessage } from '@/api/client'
import type { QueueMessage, QueueOverview, WorkersOverview } from '@/api/types'
import { EmptyState } from '@/components/EmptyState'
import { TaskStatusBadge } from '@/components/StatusBadge'
import { toast } from 'sonner'
import { RefreshCw, Server, ServerOff, Activity, ListOrdered, Trash2 } from 'lucide-react'

const POLL_INTERVAL = 3000

function formatUptime(seconds?: number | null): string {
  if (seconds == null) return '-'
  const s = Math.floor(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h} 小时 ${m} 分`
  if (m > 0) return `${m} 分 ${s % 60} 秒`
  return `${s} 秒`
}

export default function Workers() {
  const [data, setData] = useState<WorkersOverview | null>(null)
  const [queue, setQueue] = useState<QueueOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const [wRes, qRes] = await Promise.allSettled([
      api.get<WorkersOverview>('/workers'),
      api.get<QueueOverview>('/workers/queue'),
    ])
    if (wRes.status === 'fulfilled') {
      setData(wRes.value.data)
      setError(null)
    } else {
      setError(errorMessage(wRes.reason))
    }
    if (qRes.status === 'fulfilled') {
      setQueue(qRes.value.data)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [load])

  if (loading) return <div className="py-20 text-center text-muted-foreground">加载中…</div>

  if (error && !data) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold">Worker 看板</h1>
        <EmptyState icon="error" title="无法获取 Worker 状态" description={error} actionLabel="重试" onAction={() => void load()} />
      </div>
    )
  }

  const workers = data?.workers ?? []
  const activeCount = workers.reduce((n, w) => n + w.active.length, 0)
  const totalConcurrency = workers.reduce((n, w) => n + (w.concurrency ?? 0), 0)

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Worker 看板</h1>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新
        </Button>
      </div>

      {/* 汇总卡片 */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">在线 Worker</CardTitle>
            {data?.online ? (
              <Server className="h-4 w-4 text-emerald-500" />
            ) : (
              <ServerOff className="h-4 w-4 text-destructive" />
            )}
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold tabular-nums">{data?.count ?? 0}</div>
            <p className="mt-1 text-xs text-muted-foreground">
              {data?.online ? 'broker 连接正常' : (data?.error ?? '无 worker 响应')}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">总并发槽位</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold tabular-nums">{totalConcurrency}</div>
            <p className="mt-1 text-xs text-muted-foreground">全部 worker 并发上限之和</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">正在执行的任务</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold tabular-nums">{activeCount}</div>
            <p className="mt-1 text-xs text-muted-foreground">
              {data?.checked_at ? `更新于 ${data.checked_at.split(' ')[1] ?? data.checked_at}` : ''}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* 离线警告 */}
      {data && !data.online && (
        <div className="mb-6 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          <p className="font-medium">当前没有在线的 celery worker</p>
          <p className="mt-1">
            新建任务会滞留在队列中无人执行。请在项目根目录执行
            <code className="mx-1 rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs dark:bg-amber-900/60">./start.sh</code>
            启动 worker{data.error ? `（${data.error}）` : '。'}
          </p>
        </div>
      )}

      {/* Worker 明细 */}
      {workers.length > 0 && (
        <div className="space-y-4">
          {workers.map((w) => (
            <Card key={w.hostname}>
              <CardHeader className="pb-3">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
                    </span>
                    <span className="font-mono">{w.hostname}</span>
                  </CardTitle>
                  <Badge variant="secondary">并发 {w.concurrency ?? '-'}</Badge>
                  {w.pool_impl && <Badge variant="outline">{w.pool_impl}</Badge>}
                  <span className="text-xs text-muted-foreground">
                    PID {w.pid ?? '-'} · 已运行 {formatUptime(w.uptime_seconds)}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">正在执行</p>
                  {w.active.length === 0 ? (
                    <p className="text-sm text-muted-foreground">空闲</p>
                  ) : (
                    <div className="rounded-md border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>任务</TableHead>
                            <TableHead>Celery ID</TableHead>
                            <TableHead className="text-right">平台任务</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {w.active.map((t) => (
                            <TableRow key={t.celery_id ?? t.name}>
                              <TableCell className="font-mono text-sm">{t.name ?? '-'}</TableCell>
                              <TableCell className="font-mono text-xs text-muted-foreground">
                                {t.celery_id ? `${t.celery_id.slice(0, 8)}…` : '-'}
                              </TableCell>
                              <TableCell className="text-right">
                                {t.task_id != null ? (
                                  <Button asChild variant="outline" size="sm">
                                    <Link to={`/tasks/${t.task_id}`}>#{t.task_id} 详情</Link>
                                  </Button>
                                ) : (
                                  <span className="text-muted-foreground">-</span>
                                )}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </div>
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">已注册任务类型</p>
                  <div className="flex flex-wrap gap-1.5">
                    {w.registered.map((name) => (
                      <Badge key={name} variant="outline" className="font-mono text-xs">
                        {name}
                      </Badge>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* broker 任务队列（Redis celery list，第 1 条 = 下一个被消费） */}
      <QueueSection queue={queue} onChanged={() => void load()} />
    </div>
  )
}

function QueueSection({ queue, onChanged }: { queue: QueueOverview | null; onChanged: () => void }) {
  const [pendingDelete, setPendingDelete] = useState<QueueMessage | null>(null)
  const [deleting, setDeleting] = useState(false)

  const doDelete = async () => {
    if (!pendingDelete?.celery_id) return
    setDeleting(true)
    try {
      const res = await api.delete(`/workers/queue/${encodeURIComponent(pendingDelete.celery_id)}`)
      const d = res.data as { removed: number; task_marked_stopped?: boolean }
      toast.success(
        d.task_marked_stopped
          ? '队列消息已清除，对应任务已标记为已停止'
          : '队列消息已清除',
      )
      setPendingDelete(null)
      onChanged()
    } catch (e) {
      toast.error(`清除失败：${errorMessage(e)}`)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Card className="mt-6">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <ListOrdered className="h-4 w-4 text-muted-foreground" />
            任务队列
            <Badge variant="secondary" className="tabular-nums">{queue?.count ?? 0}</Badge>
          </CardTitle>
          <span className="font-mono text-xs text-muted-foreground">Redis · celery list</span>
        </div>
        <p className="text-xs text-muted-foreground">
          已派发但尚未被 worker 领取的消息，第 1 条下一个被消费；清除 = 从 Redis 队列删除该消息，对应 pending 任务会一并标记为已停止
        </p>
      </CardHeader>
      <CardContent>
        {!queue ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : !queue.available ? (
          <p className="text-sm text-destructive">队列不可用：{queue.error}</p>
        ) : queue.messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">队列为空，没有滞留消息</p>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-14">顺位</TableHead>
                  <TableHead>任务类型</TableHead>
                  <TableHead>Celery ID</TableHead>
                  <TableHead className="text-right">平台任务</TableHead>
                  <TableHead>任务状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {queue.messages.map((m, i) => (
                  <TableRow key={m.celery_id ?? i} className={m.stale ? 'bg-amber-50/60 dark:bg-amber-950/20' : undefined}>
                    <TableCell className="font-mono text-muted-foreground">#{i + 1}</TableCell>
                    <TableCell className="font-mono text-sm">{m.name ?? (m.unparseable ? '（无法解析）' : '-')}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {m.celery_id ? `${m.celery_id.slice(0, 8)}…` : '-'}
                    </TableCell>
                    <TableCell className="text-right">
                      {m.task_id != null ? (
                        <Button asChild variant="outline" size="sm">
                          <Link to={`/tasks/${m.task_id}`}>#{m.task_id} 详情</Link>
                        </Button>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {m.db_status ? <TaskStatusBadge status={m.db_status} /> : <span className="text-muted-foreground">-</span>}
                        {m.stale && (
                          <span className="text-xs font-medium text-amber-600">滞留，建议清除</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={!m.celery_id}
                        onClick={() => setPendingDelete(m)}
                      >
                        <Trash2 className="mr-1.5 h-4 w-4" />
                        清除
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      <AlertDialog open={pendingDelete !== null} onOpenChange={(v) => !v && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>清除这条队列消息？</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete?.name ?? '该消息'}
              {pendingDelete?.task_id != null ? `（平台任务 #${pendingDelete.task_id}）` : ''}
              将从 Redis 队列中删除，不会再被 worker 执行。
              {pendingDelete?.db_status === 'pending'
                ? ' 对应任务仍在等待执行，会一并标记为已停止。'
                : ''}
              此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                void doDelete()
              }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? '清除中…' : '确认清除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
