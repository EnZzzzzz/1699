// 任务页共享展示件：状态徽标 / 日志级别徽标 / 任务类型标签
import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import type { TaskEventLevel, TaskType } from '@/lib/api'

export function statusBadge(status: string) {
  switch (status) {
    case 'running':
      return <Badge className="bg-sky-600 hover:bg-sky-600">运行中</Badge>
    case 'pending':
      return <Badge variant="secondary">排队中</Badge>
    case 'waiting':
      // 循环模式轮间等待：done/failed 后按 repeat_interval 等待自动重启
      return <Badge className="bg-amber-500 hover:bg-amber-500">等待重启</Badge>
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

// 循环等待倒计时：显示「X分Y秒后重启」，到点显示「正在重启…」
// next_restart_at 为 "YYYY-MM-DD HH:MM:SS"（北京时间，机器时区一致）。
export function RestartCountdown({
  nextRestartAt,
  className,
}: {
  nextRestartAt?: string | null
  className?: string
}) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  if (!nextRestartAt) return null
  const ts = Date.parse(nextRestartAt.replace(' ', 'T'))
  if (Number.isNaN(ts)) return null
  const sec = Math.max(0, Math.round((ts - now) / 1000))
  const text = sec <= 0
    ? '正在重启…'
    : `${Math.floor(sec / 60)}分${String(sec % 60).padStart(2, '0')}秒后重启`
  return <span className={className}>{text}</span>
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
  { value: '1688_company', label: '1688 公司采集' },
  { value: '1688_contact', label: '1688 联系方式采集' },
  { value: 'madeinchina_shop', label: '中国制造网 展厅采集' },
  { value: 'madeinchina_contact', label: '中国制造网 联系方式采集' },
  { value: 'yiwugo_search', label: '义乌购搜索' },
  { value: 'wa_check', label: 'WhatsApp 查号' },
  { value: 'fb_post', label: 'Facebook 帖子采集' },
]

export function taskTypeLabel(type: string): string {
  return TASK_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type
}

/** worker 标识徽标：同一 worker 恒同色（哈希取色相，明暗主题通用）。 */
export function workerChip(worker: number | string | undefined | null) {
  if (worker === undefined || worker === null || worker === '') return null
  const s = String(worker)
  let hash = 0
  for (let i = 0; i < s.length; i++) hash = (hash * 31 + s.charCodeAt(i)) >>> 0
  const hue = (hash * 47) % 360
  const label = typeof worker === 'number' ? `W${worker}` : s
  return (
    <span
      className="inline-flex shrink-0 items-center rounded px-1 py-px font-mono text-[10px] font-semibold"
      style={{
        color: `hsl(${hue} 75% 45%)`,
        background: `hsl(${hue} 75% 45% / 0.12)`,
        border: `1px solid hsl(${hue} 75% 45% / 0.35)`,
      }}
      title={`worker ${s}`}
    >
      {label}
    </span>
  )
}

/** 从日志事件取 worker：优先 data.worker，回退解析消息（行首 [N] 或 identity=xxx）。 */
export function eventWorker(ev: { message: string; data?: { worker?: number | string } | null }): number | string | null {
  if (ev.data?.worker !== undefined && ev.data?.worker !== null) return ev.data.worker
  const num = /^\s*\[(\d+)\]/.exec(ev.message)
  if (num) return Number(num[1])
  const id = /identity=([^\s)，、]+)/.exec(ev.message)
  return id ? id[1] : null
}

// 秒数人性化：>=3600 显小时、>=60 显分钟、否则显秒（最多 1 位小数）
function humanizeSeconds(sec: number): string {
  const trim = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))
  if (sec >= 3600) return `${trim(sec / 3600)}小时`
  if (sec >= 60) return `${trim(sec / 60)}分钟`
  return `${sec}秒`
}

// 任务参数摘要：表格 params 列的小字展示
// 采集类示例：n=10 批=4 代理 无头 循环30分钟；wa_check：上限=500 账号=xiaohao-1
// 批次类型：上限=200 循环30分钟
export function paramsSummary(task: { type: string; params: Record<string, unknown> }): string {
  const p = task.params ?? {}
  const num = (k: string): number | null =>
    typeof p[k] === 'number' && Number.isFinite(p[k] as number) ? (p[k] as number) : null
  const repeat = num('repeat_interval')
  const repeatPart = repeat !== null && repeat > 0 ? `循环${humanizeSeconds(repeat)}` : null

  if (task.type === 'wa_check') {
    const parts: string[] = []
    const limit = num('limit')
    if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '全部未查')
    const accs = Array.isArray(p.accounts) ? (p.accounts as unknown[]).filter((a) => typeof a === 'string') : []
    if (accs.length > 0) parts.push(`账号=${accs.join(',')}`)
    if (repeatPart) parts.push(repeatPart)
    return parts.length > 0 ? parts.join(' ') : '默认参数'
  }

  // P4 批次采集类型（1688/madeinchina shop/company/contact + fb_post）：
  // 只读 limit（contact=条数、shop/company=页数）+ repeat_interval
  const BATCH_TYPES = new Set(['1688_shop', '1688_company', '1688_contact',
                               'madeinchina_shop', 'madeinchina_contact',
                               'fb_post'])
  if (BATCH_TYPES.has(task.type)) {
    const parts: string[] = []
    const limit = num('limit')
    if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '不限量')
    if (repeatPart) parts.push(repeatPart)
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
  if (repeatPart) parts.push(repeatPart)
  return parts.length > 0 ? parts.join(' ') : '默认参数'
}
