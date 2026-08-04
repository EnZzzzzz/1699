import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api, useApiData, formatTime, formatDuration, type Task } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { Play, Plus, RefreshCw, Square, Trash2, X } from 'lucide-react'
import { statusBadge, taskTypeLabel, paramsSummary } from './tasks/task-ui'
import { TaskFormDialog } from './tasks/TaskFormDialog'
import { TaskActions } from './tasks/TaskActions'
import { TaskLogSheet } from './tasks/TaskLogSheet'

type BatchAction = 'start' | 'stop' | 'delete'

function lastLine(task: Task): string | null {
  const v = task.progress?.last_line
  if (typeof v !== 'string' || v.length === 0) return null
  return v.length > 60 ? `${v.slice(0, 60)}…` : v
}

function TaskRow({
  task,
  selected,
  onSelect,
  onChanged,
  onShowLogs,
}: {
  task: Task
  selected: boolean
  onSelect: (checked: boolean) => void
  onChanged: () => void
  onShowLogs: () => void
}) {
  const line = lastLine(task)
  return (
    <TableRow data-state={selected ? 'selected' : undefined}>
      <TableCell className="w-10">
        <Checkbox
          checked={selected}
          onCheckedChange={(v) => onSelect(v === true)}
          aria-label={`选择任务 ${task.id}`}
        />
      </TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">#{task.id}</TableCell>
      <TableCell className="font-medium">{taskTypeLabel(task.type)}</TableCell>
      <TableCell className="max-w-40">
        <span className="block truncate text-xs text-muted-foreground" title={paramsSummary(task)}>
          {paramsSummary(task)}
        </span>
      </TableCell>
      <TableCell>
        {statusBadge(task.status)}
        {line && (
          <div className="mt-1 max-w-64 truncate text-xs text-muted-foreground" title={line}>
            {line}
          </div>
        )}
      </TableCell>
      <TableCell className="text-sm">{formatTime(task.created_at)}</TableCell>
      <TableCell className="text-sm">{formatDuration(task.started_at, task.finished_at)}</TableCell>
      <TableCell className="max-w-56">
        {task.error ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="block truncate text-sm text-destructive">{task.error}</span>
              </TooltipTrigger>
              <TooltipContent className="max-w-md">
                <p className="whitespace-pre-wrap text-xs">{task.error}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <span className="text-sm text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell>
        <TaskActions task={task} onChanged={onChanged} onShowLogs={onShowLogs} />
      </TableCell>
    </TableRow>
  )
}

const ACTION_LABEL: Record<BatchAction, string> = {
  start: '启动',
  stop: '停止',
  delete: '删除',
}

export default function Tasks() {
  // 有任务在跑时加快轮询（5s），空闲时 30s；日志抽屉收到 SSE 状态事件也会即时触发刷新
  const [hasRunning, setHasRunning] = useState(false)
  const { data, loading, error, reload } = useApiData(api.tasks, hasRunning ? 5_000 : 30_000)
  const [createOpen, setCreateOpen] = useState(false)
  const [logTask, setLogTask] = useState<Task | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [batchBusy, setBatchBusy] = useState(false)
  const [confirmAction, setConfirmAction] = useState<BatchAction | null>(null)

  useEffect(() => {
    setHasRunning((data ?? []).some((t) => t.status === 'running'))
    // 列表刷新后剔除已不存在的选中项（如被删除）
    setSelected((prev) => {
      const alive = new Set((data ?? []).map((t) => t.id))
      const next = new Set([...prev].filter((id) => alive.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [data])

  const tasks = data ?? []
  const allChecked = tasks.length > 0 && selected.size === tasks.length
  const someChecked = selected.size > 0 && !allChecked

  const toggleAll = (checked: boolean) => {
    setSelected(checked ? new Set(tasks.map((t) => t.id)) : new Set())
  }
  const toggleOne = (id: number, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const runBatch = async (action: BatchAction) => {
    const ids = [...selected]
    if (ids.length === 0) return
    setBatchBusy(true)
    try {
      const r = await api.batchTasks(action, ids)
      if (r.failed === 0) {
        toast.success(`批量${ACTION_LABEL[action]}成功 ${r.ok} 个`)
      } else {
        toast.warning(`批量${ACTION_LABEL[action]}：成功 ${r.ok} 个，跳过/失败 ${r.failed} 个`, {
          description: r.results.filter((x) => !x.ok).slice(0, 3)
            .map((x) => `#${x.id} ${x.detail}`).join('；') || undefined,
        })
      }
      setSelected(new Set())
      reload()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '批量操作失败')
    } finally {
      setBatchBusy(false)
      setConfirmAction(null)
    }
  }

  return (
    <div className="p-6">
      <PageHeader
        title="任务管理"
        desc="采集与处理任务的创建、启停与实时日志"
        extra={
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={reload}>
              <RefreshCw className="mr-2 h-4 w-4" />
              刷新
            </Button>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              新建任务
            </Button>
          </div>
        }
      />

      {selected.size > 0 && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-4 py-2">
          <span className="text-sm text-muted-foreground">已选 {selected.size} 项</span>
          <div className="ml-auto flex gap-2">
            <Button size="sm" variant="outline" disabled={batchBusy}
              onClick={() => runBatch('start')}>
              <Play className="mr-1 h-3.5 w-3.5" />
              批量启动
            </Button>
            <Button size="sm" variant="outline" disabled={batchBusy}
              onClick={() => setConfirmAction('stop')}>
              <Square className="mr-1 h-3.5 w-3.5" />
              批量停止
            </Button>
            <Button size="sm" variant="outline" disabled={batchBusy}
              className="text-destructive hover:text-destructive"
              onClick={() => setConfirmAction('delete')}>
              <Trash2 className="mr-1 h-3.5 w-3.5" />
              批量删除
            </Button>
            <Button size="sm" variant="ghost" disabled={batchBusy}
              onClick={() => setSelected(new Set())}>
              <X className="mr-1 h-3.5 w-3.5" />
              清除选择
            </Button>
          </div>
        </div>
      )}

      {loading && !data ? (
        <LoadingState />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={reload} />
      ) : tasks.length === 0 ? (
        <EmptyState text="暂无任务记录" />
      ) : (
        <div className="rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox
                    checked={allChecked ? true : someChecked ? 'indeterminate' : false}
                    onCheckedChange={(v) => toggleAll(v === true)}
                    aria-label="全选"
                  />
                </TableHead>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>参数</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead>耗时</TableHead>
                <TableHead>错误</TableHead>
                <TableHead className="w-60">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((t) => (
                <TaskRow
                  key={t.id}
                  task={t}
                  selected={selected.has(t.id)}
                  onSelect={(v) => toggleOne(t.id, v)}
                  onChanged={reload}
                  onShowLogs={() => setLogTask(t)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <AlertDialog open={confirmAction !== null} onOpenChange={(o) => !o && setConfirmAction(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              批量{confirmAction ? ACTION_LABEL[confirmAction] : ''} {selected.size} 个任务？
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmAction === 'delete'
                ? '任务记录与全部日志事件将被永久清除，已入库的业务数据不受影响。该操作不可撤销。'
                : '将终止所选任务的运行进程，已采集的数据会保留。'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => confirmAction && runBatch(confirmAction)}
            >
              确认{confirmAction ? ACTION_LABEL[confirmAction] : ''}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <TaskFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSaved={reload}
      />
      <TaskLogSheet
        task={logTask}
        open={logTask !== null}
        onOpenChange={(open) => {
          if (!open) setLogTask(null)
        }}
        onStatus={() => reload()}
      />
    </div>
  )
}
