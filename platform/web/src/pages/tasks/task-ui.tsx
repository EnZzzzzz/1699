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
  { value: 'wa_check', label: 'WhatsApp 查号' },
]

export function taskTypeLabel(type: string): string {
  return TASK_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type
}

// 任务参数摘要：表格 params 列的小字展示
// 采集类示例：n=10 批=4 代理 无头；wa_check：上限=500 账号=a,b
export function paramsSummary(task: { type: string; params: Record<string, unknown> }): string {
  const p = task.params ?? {}
  const num = (k: string): number | null =>
    typeof p[k] === 'number' && Number.isFinite(p[k] as number) ? (p[k] as number) : null

  if (task.type === 'wa_check') {
    const parts: string[] = []
    const limit = num('limit')
    if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '全部未查')
    const accs = Array.isArray(p.accounts) ? (p.accounts as unknown[]).filter((a) => typeof a === 'string') : []
    if (accs.length > 0) parts.push(`账号=${accs.join(',')}`)
    const interval = num('interval')
    if (interval !== null) parts.push(`间隔=${interval}s`)
    return parts.length > 0 ? parts.join(' ') : '默认参数'
  }

  const parts: string[] = []
  const batchNum = num('batch_num')
  if (batchNum !== null) parts.push(`n=${batchNum}`)
  const maxBatches = num('max_batches')
  if (maxBatches !== null) parts.push(maxBatches > 0 ? `批=${maxBatches}` : '批=∞')
  const limit = num('limit')
  if (limit !== null && limit > 0) parts.push(`上限=${limit}`)
  const workers = num('workers')
  if (workers !== null) parts.push(`w=${workers}`)
  if (p.use_proxy === true) parts.push('代理')
  if (p.headless === true) parts.push('无头')
  else if (p.headless === false) parts.push('有头')
  if (p.retry_failed === true) parts.push('重试失败')
  return parts.length > 0 ? parts.join(' ') : '默认参数'
}
