import { useEffect, useState } from 'react'

/** 轻量 SVG 迷你趋势图（不引入重型图表库） */
export function MiniTrend({ data, width = 120, height = 32, className }: { data: number[]; width?: number; height?: number; className?: string }) {
  if (!data.length) {
    return <span className="text-xs text-muted-foreground">-</span>
  }
  const max = Math.max(...data, 1)
  const stepX = data.length > 1 ? width / (data.length - 1) : width
  const points = data.map((v, i) => `${(i * stepX).toFixed(1)},${(height - (v / max) * (height - 4) - 2).toFixed(1)}`).join(' ')
  const areaPoints = `0,${height} ${points} ${width},${height}`
  return (
    <svg width={width} height={height} className={className} role="img" aria-label="趋势图">
      <polygon points={areaPoints} className="fill-primary/10" />
      <polyline points={points} fill="none" className="stroke-primary" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

/** 倒计时渲染：目标时间 - 当前时间；过期显示"已过期"，无数据显示 - */
export function Countdown({ target }: { target: string | null | undefined }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!target) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [target])

  if (!target) return <span className="text-muted-foreground">-</span>

  const ts = new Date(target).getTime()
  if (Number.isNaN(ts)) return <span className="text-muted-foreground">-</span>

  const diff = ts - now
  if (diff <= 0) return <span className="text-destructive">已过期</span>

  const totalSec = Math.floor(diff / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  const text = h > 0 ? `${h}时${String(m).padStart(2, '0')}分` : `${m}分${String(s).padStart(2, '0')}秒`
  return <span className="tabular-nums">{text}</span>
}

/** 秒数 -> 可读耗时 */
export function formatDuration(start?: string | null, end?: string | null): string {
  if (!start) return '-'
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  if (Number.isNaN(s) || Number.isNaN(e) || e < s) return '-'
  const sec = Math.floor((e - s) / 1000)
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (h > 0) return `${h}时${m}分`
  if (m > 0) return `${m}分${sec % 60}秒`
  return `${sec}秒`
}
