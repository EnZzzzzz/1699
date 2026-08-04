import { useState } from 'react'
import { api, useApiData, formatTime, formatDuration, type Task } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from '@/components/ui/tooltip'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { Plus, RefreshCw } from 'lucide-react'
import { statusBadge, taskTypeLabel } from './tasks/task-ui'
import { CreateTaskDialog } from './tasks/CreateTaskDialog'
import { TaskActions } from './tasks/TaskActions'
import { TaskLogSheet } from './tasks/TaskLogSheet'

function lastLine(task: Task): string | null {
  const v = task.progress?.last_line
  if (typeof v !== 'string' || v.length === 0) return null
  return v.length > 60 ? `${v.slice(0, 60)}…` : v
}

function TaskRow({
  task,
  onChanged,
  onShowLogs,
}: {
  task: Task
  onChanged: () => void
  onShowLogs: () => void
}) {
  const line = lastLine(task)
  return (
    <TableRow>
      <TableCell className="font-mono text-xs text-muted-foreground">#{task.id}</TableCell>
      <TableCell className="font-medium">{taskTypeLabel(task.type)}</TableCell>
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

export default function Tasks() {
  const { data, loading, error, reload } = useApiData(api.tasks, 30_000)
  const [createOpen, setCreateOpen] = useState(false)
  const [logTask, setLogTask] = useState<Task | null>(null)

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

      {loading && !data ? (
        <LoadingState />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState text="暂无任务记录" />
      ) : (
        <div className="rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead>耗时</TableHead>
                <TableHead>错误</TableHead>
                <TableHead className="w-44">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((t) => (
                <TaskRow
                  key={t.id}
                  task={t}
                  onChanged={reload}
                  onShowLogs={() => setLogTask(t)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateTaskDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={reload}
      />
      <TaskLogSheet
        task={logTask}
        open={logTask !== null}
        onOpenChange={(open) => {
          if (!open) setLogTask(null)
        }}
      />
    </div>
  )
}
