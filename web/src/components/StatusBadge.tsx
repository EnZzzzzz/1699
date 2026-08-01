import { Badge } from '@/components/ui/badge'
import type { TaskStatus, ChannelStatus, TaskType } from '@/api/types'

const TASK_STATUS: Record<TaskStatus, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  pending: { label: '待启动', variant: 'secondary' },
  waiting_channel: { label: '等待通道', variant: 'outline' },
  running: { label: '运行中', variant: 'default' },
  stopping: { label: '停止中', variant: 'outline' },
  done: { label: '已完成', variant: 'secondary' },
  failed: { label: '失败', variant: 'destructive' },
  stopped: { label: '已停止', variant: 'outline' },
}

const CHANNEL_STATUS: Record<ChannelStatus, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  idle: { label: '空闲', variant: 'secondary' },
  in_use: { label: '使用中', variant: 'default' },
  error: { label: '异常', variant: 'destructive' },
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const conf = TASK_STATUS[status] ?? { label: status, variant: 'outline' as const }
  return (
    <Badge variant={conf.variant} className={status === 'running' ? 'bg-emerald-600 hover:bg-emerald-600' : undefined}>
      {conf.label}
    </Badge>
  )
}

export function ChannelStatusBadge({ status }: { status: ChannelStatus }) {
  const conf = CHANNEL_STATUS[status] ?? { label: status, variant: 'outline' as const }
  return (
    <Badge variant={conf.variant} className={status === 'in_use' ? 'bg-emerald-600 hover:bg-emerald-600' : undefined}>
      {conf.label}
    </Badge>
  )
}

export function TaskTypeLabel({ type }: { type: TaskType | string | null | undefined }) {
  const label =
    type === 'shop_crawl'
      ? '店铺采集'
      : type === 'contact_fetch'
        ? '联系方式抓取'
        : type === 'flow'
          ? '流水线'
          : (type ?? '-')
  return <span>{label}</span>
}
