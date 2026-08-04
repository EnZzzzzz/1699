// 任务实时日志 SSE Hook：封装原生 EventSource
// - 打开时连接 /api/tasks/{id}/events（后端先回放后增量，按事件 id 去重，无缝衔接）
// - 收到自定义 status 事件时更新任务状态与结束时间
// - 关闭/切换任务/卸载时断开连接
import { useEffect, useRef, useState } from 'react'
import type { TaskEvent, TaskStatusEvent } from '@/lib/api'

export interface TaskEventsState {
  events: TaskEvent[]
  status: string | null
  finishedAt: string | null
  connected: boolean
}

export function useTaskEvents(
  taskId: number | null,
  open: boolean,
  onStatus?: (status: string, finishedAt: string | null) => void,
): TaskEventsState {
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [status, setStatus] = useState<string | null>(null)
  const [finishedAt, setFinishedAt] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const seenRef = useRef<Set<number>>(new Set())
  const onStatusRef = useRef(onStatus)
  onStatusRef.current = onStatus

  useEffect(() => {
    if (!open || taskId == null) return

    setEvents([])
    setStatus(null)
    setFinishedAt(null)
    setConnected(false)
    seenRef.current = new Set()

    const es = new EventSource(`/api/tasks/${taskId}/events`)

    es.onopen = () => setConnected(true)

    // 默认 message 事件：日志条目（回放 + 增量共用同一通道，按 id 去重）
    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data as string) as TaskEvent
        if (typeof ev.id !== 'number' || seenRef.current.has(ev.id)) return
        seenRef.current.add(ev.id)
        setEvents((prev) => [...prev, ev])
      } catch {
        // 忽略心跳注释/非 JSON 行
      }
    }

    // 自定义 status 事件：任务状态变更（同步通知外层，触发列表即时刷新）
    es.addEventListener('status', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data as string) as TaskStatusEvent
        setStatus(data.status)
        setFinishedAt(data.finished_at ?? null)
        onStatusRef.current?.(data.status, data.finished_at ?? null)
      } catch {
        // 忽略无法解析的状态帧
      }
    })

    es.onerror = () => setConnected(false)

    return () => {
      es.close()
      setConnected(false)
    }
  }, [taskId, open])

  return { events, status, finishedAt, connected }
}
