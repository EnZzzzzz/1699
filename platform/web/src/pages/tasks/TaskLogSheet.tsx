// 任务实时日志抽屉：右侧 Sheet + SSE 事件流
import { useEffect, useRef, useState } from 'react'
import { useTaskEvents } from '@/hooks/useTaskEvents'
import type { Task } from '@/lib/api'
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { ArrowDown, Loader2 } from 'lucide-react'
import { levelBadge, statusBadge, taskTypeLabel } from './task-ui'

interface TaskLogSheetProps {
  task: Task | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function TaskLogSheet({ task, open, onOpenChange }: TaskLogSheetProps) {
  const { events, status, connected } = useTaskEvents(open ? (task?.id ?? null) : null, open)
  const scrollRef = useRef<HTMLDivElement>(null)
  const autoRef = useRef(true)
  const [autoScroll, setAutoScroll] = useState(true)

  // 打开/切换任务时恢复自动滚动
  useEffect(() => {
    if (open) {
      autoRef.current = true
      setAutoScroll(true)
    }
  }, [open, task?.id])

  // 新事件到达时，若处于自动滚动状态则滚到底部
  useEffect(() => {
    if (!autoRef.current) return
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [events])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    // 距底部 40px 以内视为"在底部"：恢复自动滚动；上翻则暂停
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    autoRef.current = atBottom
    setAutoScroll(atBottom)
  }

  const scrollToBottom = () => {
    autoRef.current = true
    setAutoScroll(true)
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }

  const displayStatus = status ?? task?.status ?? ''

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-2xl">
        <SheetHeader>
          <div className="flex items-center gap-2 pr-6">
            <SheetTitle className="text-base">
              任务 #{task?.id} 日志
            </SheetTitle>
            {displayStatus && statusBadge(displayStatus)}
            <span
              className={`ml-auto inline-flex items-center gap-1.5 text-xs ${
                connected ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  connected ? 'bg-emerald-500' : 'bg-muted-foreground/50'
                }`}
              />
              {connected ? '已连接' : '连接中…'}
            </span>
          </div>
          <SheetDescription>
            {task ? `${taskTypeLabel(task.type)} · 实时事件流（自动滚动到底，上翻可暂停）` : '实时事件流'}
          </SheetDescription>
        </SheetHeader>

        <div className="relative mt-4 min-h-0 flex-1">
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="h-full overflow-y-auto rounded-md border border-border bg-muted/30 p-3"
          >
            {events.length === 0 ? (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                等待日志事件…
              </div>
            ) : (
              <ul className="space-y-1.5">
                {events.map((ev) => (
                  <li key={ev.id} className="flex items-start gap-2">
                    <span className="shrink-0 pt-px">{levelBadge(ev.level)}</span>
                    <span className="shrink-0 pt-0.5 font-mono text-xs text-muted-foreground">
                      {ev.ts}
                    </span>
                    <span className="min-w-0 flex-1 whitespace-pre-wrap break-all pt-0.5 font-mono text-xs leading-relaxed">
                      {ev.message}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {!autoScroll && (
            <Button
              size="sm"
              variant="secondary"
              className="absolute bottom-3 right-3 shadow-md"
              onClick={scrollToBottom}
            >
              <ArrowDown className="mr-1 h-3.5 w-3.5" />
              回到底部
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
