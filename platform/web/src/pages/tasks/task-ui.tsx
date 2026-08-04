// 任务页共享展示件：状态徽标 / 日志级别徽标 / 任务类型标签
import { Badge } from '@/components/ui/badge'
import type { TaskEventLevel, TaskType } from '@/lib/api'

export function statusBadge(status: string) {
  switch (status) {
    case 'running':
      return <Badge className="bg-sky-600 hover:bg-sky-600">运行中</Badge>
    case 'pending':
      return <Badge variant="secondary">排队中</Badge>
    case 'done':
      return <Badge className="bg-emerald-600 hover:bg-emerald-600">已完成</Badge>
    case 'failed':
      return <Badge variant="destructive">失败</Badge>
    case 'stopped':
      return <Badge variant="outline">已停止</Badge>
    default:
      return <Badge variant="outline">{status}</Badge>
  }
}

export function levelBadge(level: TaskEventLevel) {
  switch (level) {
    case 'success':
      return (
        <Badge variant="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
          success
        </Badge>
      )
    case 'warning':
      return (
        <Badge variant="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400">
          warning
        </Badge>
      )
    case 'error':
      return <Badge variant="destructive">error</Badge>
    case 'info':
    default:
      return <Badge variant="secondary">info</Badge>
  }
}

export const TASK_TYPE_OPTIONS: { value: TaskType; label: string }[] = [
  { value: '1688_shop', label: '1688 店铺采集' },
  { value: '1688_contact', label: '1688 联系方式采集' },
  { value: 'yiwugo_search', label: '义乌购搜索' },
]

export function taskTypeLabel(type: string): string {
  return TASK_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type
}
