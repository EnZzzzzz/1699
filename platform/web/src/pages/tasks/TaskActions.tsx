// 任务行操作按钮：启动 / 停止（二次确认）/ 编辑参数 / 删除（二次确认）/ 日志
import { useState } from 'react'
import { toast } from 'sonner'
import { api, ApiError, type Task } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Pencil, Play, ScrollText, Square, Trash2 } from 'lucide-react'
import { TaskFormDialog } from './TaskFormDialog'

interface TaskActionsProps {
  task: Task
  onChanged: () => void
  onShowLogs: () => void
}

export function TaskActions({ task, onChanged, onShowLogs }: TaskActionsProps) {
  const [busy, setBusy] = useState(false)
  const [editOpen, setEditOpen] = useState(false)

  const run = async (fn: () => Promise<unknown>, okMsg: string) => {
    setBusy(true)
    try {
      await fn()
      toast.success(okMsg)
      onChanged() // 乐观刷新：操作成功后立即重载列表
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.warning('任务状态已变化，已刷新列表')
        onChanged()
      } else {
        toast.error(e instanceof Error ? e.message : '操作失败')
      }
    } finally {
      setBusy(false)
    }
  }

  const isRunning = task.status === 'running'
  const isWaiting = task.status === 'waiting' // 循环模式轮间等待中（可停止以取消自动重启）
  const canStop = isRunning || isWaiting
  const canStart = task.status === 'pending' || task.status === 'failed' || task.status === 'stopped'
  const canEdit = canStart // pending / failed / stopped 可编辑参数
  const canDelete = !isRunning // 非运行中可删除（等待重启也会随删除 cancel Timer）

  return (
    <div className="flex items-center gap-1">
      {canStop && (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="ghost" size="sm" disabled={busy} className="text-destructive hover:text-destructive">
              <Square className="mr-1 h-3.5 w-3.5" />
              停止
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>停止任务 #{task.id}？</AlertDialogTitle>
              <AlertDialogDescription>
                运行中的采集进程会被终止；等待重启的循环任务会取消自动重启。已采集的数据会保留。该操作不可撤销。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                onClick={() => run(() => api.stopTask(task.id), `任务 #${task.id} 已请求停止`)}
              >
                确认停止
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}

      {canStart && (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => run(() => api.startTask(task.id), `任务 #${task.id} 已启动`)}
        >
          <Play className="mr-1 h-3.5 w-3.5" />
          启动
        </Button>
      )}

      {canEdit && (
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => setEditOpen(true)}>
          <Pencil className="mr-1 h-3.5 w-3.5" />
          编辑
        </Button>
      )}

      <Button variant="ghost" size="sm" onClick={onShowLogs}>
        <ScrollText className="mr-1 h-3.5 w-3.5" />
        日志
      </Button>

      {canDelete && (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="ghost" size="sm" disabled={busy} className="text-destructive hover:text-destructive">
              <Trash2 className="mr-1 h-3.5 w-3.5" />
              删除
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>删除任务 #{task.id}？</AlertDialogTitle>
              <AlertDialogDescription>
                任务记录与全部日志事件将被永久清除，已采集到库里的业务数据不受影响。该操作不可撤销。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                onClick={() => run(() => api.deleteTask(task.id), `任务 #${task.id} 已删除`)}
              >
                确认删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}

      <TaskFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        task={task}
        onSaved={onChanged}
      />
    </div>
  )
}
