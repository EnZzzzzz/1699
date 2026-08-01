import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { api, errorMessage } from '@/api/client'
import type { TaskEvent, TaskEventLevel, TaskEventsResponse, WsMessage } from '@/api/types'
import { useRealtime } from '@/hooks/useRealtime'
import { ArrowDown, Eraser, TerminalSquare } from 'lucide-react'

const MAX_EVENTS = 500
const TERMINAL_STATUSES = new Set(['done', 'failed', 'stopped'])

const LEVEL_STYLE: Record<TaskEventLevel, { label: string; text: string; dot: string }> = {
  info: { label: 'INFO', text: 'text-zinc-400', dot: 'bg-zinc-500' },
  success: { label: 'OK', text: 'text-emerald-400', dot: 'bg-emerald-500' },
  warning: { label: 'WARN', text: 'text-amber-400', dot: 'bg-amber-500' },
  error: { label: 'ERR', text: 'text-red-400', dot: 'bg-red-500' },
}

type Filter = 'all' | TaskEventLevel

/**
 * 任务实时事件控制台：
 * 进页 REST 拉最近 200 条 → WS subscribe_task(after_id=latest_id) 增量追加；
 * WS 断开降级 2s 增量轮询 REST（终态后停止）；最多保留 500 条。
 */
export function TaskEventsCard({ taskId, status }: { taskId: number; status: string }) {
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [hasNew, setHasNew] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const latestIdRef = useRef(0)
  const atBottomRef = useRef(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const seenRef = useRef<Set<number>>(new Set())

  const terminal = TERMINAL_STATUSES.has(status)

  const appendEvents = useCallback((incoming: TaskEvent[]) => {
    const fresh = incoming.filter((e) => !seenRef.current.has(e.id))
    if (fresh.length === 0) return
    for (const e of fresh) {
      seenRef.current.add(e.id)
      if (e.id > latestIdRef.current) latestIdRef.current = e.id
    }
    setEvents((prev) => [...prev, ...fresh].sort((a, b) => a.id - b.id).slice(-MAX_EVENTS))
    if (atBottomRef.current) {
      requestAnimationFrame(() => {
        const el = scrollRef.current
        if (el) el.scrollTop = el.scrollHeight
      })
    } else {
      setHasNew(true)
    }
  }, [])

  // 初始：REST 拉最近 200 条
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await api.get<TaskEventsResponse>(`/tasks/${taskId}/events`, {
          params: { after_id: 0, limit: 200 },
        })
        if (cancelled) return
        latestIdRef.current = res.data.latest_id ?? 0
        appendEvents(res.data.items ?? [])
        setLoadError(null)
      } catch (e) {
        if (!cancelled) setLoadError(errorMessage(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [taskId, appendEvents])

  // WS 断开时的降级：2s 增量轮询 REST（终态后不再发起）
  const pollIncrement = useCallback(async () => {
    try {
      const res = await api.get<TaskEventsResponse>(`/tasks/${taskId}/events`, {
        params: { after_id: latestIdRef.current, limit: 200 },
      })
      appendEvents(res.data.items ?? [])
    } catch {
      // 降级轮询失败静默，下一拍重试
    }
  }, [taskId, appendEvents])

  const onWsMessage = useCallback(
    (msg: WsMessage) => {
      if (msg.type === 'task_event' && msg.task_id === taskId) {
        appendEvents([msg.event])
      }
    },
    [taskId, appendEvents],
  )

  // 每次（重）连上 WS 后订阅本任务，从最新事件 id 起收
  const onWsOpen = useCallback(
    (send: (msg: unknown) => void) => {
      send({ subscribe_task: taskId, after_id: latestIdRef.current })
    },
    [taskId],
  )

  useRealtime({
    onMessage: onWsMessage,
    onOpen: onWsOpen,
    poll: terminal ? undefined : pollIncrement,
  })

  const filtered = useMemo(
    () => (filter === 'all' ? events : events.filter((e) => e.level === filter)),
    [events, filter],
  )

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    atBottomRef.current = atBottom
    if (atBottom) setHasNew(false)
  }

  const scrollToBottom = () => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
    atBottomRef.current = true
    setHasNew(false)
  }

  const clear = () => {
    // 仅清前端显示；seen/latestId 保留，增量拉取不会把旧事件拉回来
    setEvents([])
    setHasNew(false)
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <TerminalSquare className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">实时事件</CardTitle>
            <Badge variant="secondary">{events.length} 条</Badge>
            {terminal && <span className="text-xs text-muted-foreground">任务已结束，事件流已停止</span>}
          </div>
          <div className="flex items-center gap-2">
            <ToggleGroup
              type="single"
              size="sm"
              value={filter}
              onValueChange={(v) => v && setFilter(v as Filter)}
            >
              <ToggleGroupItem value="all">全部</ToggleGroupItem>
              <ToggleGroupItem value="info">info</ToggleGroupItem>
              <ToggleGroupItem value="success">success</ToggleGroupItem>
              <ToggleGroupItem value="warning">warning</ToggleGroupItem>
              <ToggleGroupItem value="error">error</ToggleGroupItem>
            </ToggleGroup>
            <Button variant="outline" size="sm" onClick={clear}>
              <Eraser className="mr-1.5 h-4 w-4" />
              清空
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {loadError ? (
          <p className="py-4 text-sm text-muted-foreground">事件加载失败：{loadError}</p>
        ) : (
          <div className="relative">
            <div
              ref={scrollRef}
              onScroll={onScroll}
              className="h-80 overflow-y-auto rounded-lg bg-zinc-950 p-3 font-mono text-xs leading-6 text-zinc-200"
            >
              {filtered.length === 0 ? (
                <p className="py-8 text-center text-zinc-500">
                  {events.length === 0 ? '暂无事件' : '当前级别无匹配事件'}
                </p>
              ) : (
                filtered.map((e) => {
                  const style = LEVEL_STYLE[e.level] ?? LEVEL_STYLE.info
                  return (
                    <div key={e.id} className="flex gap-2 whitespace-pre-wrap break-all">
                      <span className="shrink-0 text-zinc-500">{formatTs(e.ts)}</span>
                      <span className={`shrink-0 w-11 font-semibold ${style.text}`}>{style.label}</span>
                      <span className={e.level === 'error' ? 'text-red-300' : undefined}>{e.message}</span>
                    </div>
                  )
                })
              )}
            </div>
            {hasNew && (
              <Button
                size="sm"
                className="absolute bottom-3 right-3 shadow-lg"
                onClick={scrollToBottom}
              >
                <ArrowDown className="mr-1 h-4 w-4" />
                有新事件
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** "2026-08-01 02:03:42" -> "02:03:42"；异常格式原样返回 */
function formatTs(ts: string): string {
  return ts.length >= 19 ? ts.slice(11, 19) : ts
}
