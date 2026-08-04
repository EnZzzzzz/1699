import { api, useApiData, formatTime, formatDuration, type Task } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from '@/components/ui/tooltip'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { RefreshCw, Play, Square, Eye } from 'lucide-react'

function statusBadge(status: string) {
  switch (status) {
    case 'running':
      return <Badge className="bg-sky-600 hover:bg-sky-600">运行中</Badge>
    case 'pending':
      return <Badge variant="secondary">排队中</Badge>
    case 'done':
      return <Badge className="bg-emerald-600 hover:bg-emerald-600">已完成</Badge>
    case 'failed':
      return <Badge variant="destructive">失败</Badge>
    default:
      return <Badge variant="outline">{status}</Badge>
  }
}

function TaskRow({ task }: { task: Task }) {
  return (
    <TableRow>
      <TableCell className="font-mono text-xs text-muted-foreground">#{task.id}</TableCell>
      <TableCell className="font-medium">{task.type}</TableCell>
      <TableCell>{statusBadge(task.status)}</TableCell>
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
      {/* 操作列：P0 只读，占位按钮 */}
      <TableCell>
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" disabled title="查看详情（即将上线）">
            <Eye className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" disabled title="重跑（即将上线）">
            <Play className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" disabled title="终止（即将上线）">
            <Square className="h-4 w-4" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}

export default function Tasks() {
  const { data, loading, error, reload } = useApiData(api.tasks, 30_000)

  return (
    <div className="p-6">
      <PageHeader
        title="任务管理"
        desc="采集与处理任务的运行记录（P0 只读）"
        extra={
          <Button variant="outline" size="sm" onClick={reload}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
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
                <TableHead className="w-32">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((t) => (
                <TaskRow key={t.id} task={t} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
