// 任务行操作按钮：启动 / 停止（二次确认）/ 日志
import { useState } from 'react'
import { toast } from 'sonner'
import { api, ApiError, type Task } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Play, ScrollText, Square } from 'lucide-react'

interface TaskActionsProps {
  task: Task
  onChanged: () => void
  onShowLogs: () => void
}

export function TaskActions({ task, onChanged, onShowLogs }: TaskActionsProps) {
  const [busy, setBusy] = useState(false)

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

  const canStop = task.status === 'running'
  const canStart = task.status === 'pending' || task.status === 'failed' || task.status === 'stopped'

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
                正在运行的采集进程会被终止，已采集的数据会保留。该操作不可撤销。
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

      <Button variant="ghost" size="sm" onClick={onShowLogs}>
        <ScrollText className="mr-1 h-3.5 w-3.5" />
        日志
      </Button>
    </div>
  )
}
