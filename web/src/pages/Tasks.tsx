import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, asArray, errorMessage, isNotImplemented } from '@/api/client'
import type { Task, WsMessage } from '@/api/types'
import { TaskStatusBadge, TaskTypeLabel } from '@/components/StatusBadge'
import { EmptyState, NotImplementedState } from '@/components/EmptyState'
import { NewTaskDialog } from '@/components/NewTaskDialog'
import { formatDuration } from '@/components/MiniTrend'
import { useRealtime } from '@/hooks/useRealtime'
import { useTaskActions, canStop, needsConfirm } from '@/hooks/useTaskActions'
import { Plus, RefreshCw, HandMetal } from 'lucide-react'

export default function Tasks() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [notImpl, setNotImpl] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await api.get('/tasks')
      setTasks(asArray<Task>(res.data))
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
    if (msg.type === 'task_progress') {
      const updated = msg.task
      setTasks((prev) => {
        const idx = prev.findIndex((t) => t.id === updated.id)
        if (idx === -1) return prev
        const next = [...prev]
        next[idx] = updated
        return next
      })
    }
  }, [])

  useRealtime({ onMessage: onWsMessage, poll: load })

  const { stopTask, confirmTask, confirmingId } = useTaskActions(() => void load())

  if (loading) return <div className="py-20 text-center text-muted-foreground">加载中…</div>

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">任务</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
          {!notImpl && (
            <Button size="sm" onClick={() => setDialogOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              新建任务
            </Button>
          )}
        </div>
      </div>

      {notImpl ? (
        <NotImplementedState feature="任务管理" />
      ) : error ? (
        <EmptyState icon="error" title="无法获取任务列表" description={error} actionLabel="重试" onAction={() => void load()} />
      ) : tasks.length === 0 ? (
        <EmptyState
          title="暂无任务"
          description="点击右上角「新建任务」开始店铺采集或联系方式抓取"
          actionLabel="新建任务"
          onAction={() => setDialogOpen(true)}
        />
      ) : (
        <div className="rounded-lg border bg-background">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="w-40">进度</TableHead>
                <TableHead className="text-right">已采</TableHead>
                <TableHead className="text-right">待采</TableHead>
                <TableHead className="text-right">每分钟</TableHead>
                <TableHead>耗时</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((t) => {
                const collected = t.progress?.collected ?? 0
                const pending = t.progress?.pending ?? 0
                const total = t.progress?.total ?? collected + pending
                const pct = Math.min(100, total > 0 ? (collected / total) * 100 : t.status === 'done' ? 100 : 0)
                return (
                  <TableRow key={t.id} className="cursor-pointer" onClick={() => navigate(`/tasks/${t.id}`)}>
                    <TableCell className="font-mono text-muted-foreground">#{t.id}</TableCell>
                    <TableCell>
                      <TaskTypeLabel type={t.type} />
                    </TableCell>
                    <TableCell>
                      <TaskStatusBadge status={t.status} />
                      {needsConfirm(t) && (
                        <span className="ml-2 text-xs font-medium text-amber-600">等待人工确认</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Progress value={pct} className="h-2" />
                        <span className="w-10 text-xs tabular-nums text-muted-foreground">{pct.toFixed(0)}%</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{collected.toLocaleString()}</TableCell>
                    <TableCell className="text-right tabular-nums">{pending.toLocaleString()}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.progress?.per_minute ?? '-'}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{formatDuration(t.started_at, t.finished_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        {needsConfirm(t) && (
                          <Button
                            size="sm"
                            className="animate-pulse bg-amber-500 text-white hover:bg-amber-600"
                            disabled={confirmingId === t.id}
                            onClick={(e) => {
                              e.stopPropagation()
                              void confirmTask(t)
                            }}
                          >
                            <HandMetal className="mr-1.5 h-4 w-4" />
                            {confirmingId === t.id ? '确认中…' : '确认开始采集'}
                          </Button>
                        )}
                        {canStop(t) && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation()
                              void stopTask(t)
                            }}
                          >
                            停止
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            navigate(`/tasks/${t.id}`)
                          }}
                        >
                          详情
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <NewTaskDialog open={dialogOpen} onOpenChange={setDialogOpen} onCreated={() => void load()} />
    </div>
  )
}
