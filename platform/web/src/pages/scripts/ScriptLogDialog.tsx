// 采集脚本日志查看器：2s 轮询增量 tail，自动滚动到底，可暂停
import { useEffect, useRef, useState } from 'react'
import { api, type ScriptInfo } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { ArrowDownToLine, Pause, Play } from 'lucide-react'

// 前端日志缓冲上限（超出截掉头部，防长时间挂页内存膨胀）
const MAX_BUFFER = 200_000
const POLL_MS = 2000

interface ScriptLogDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 目标脚本，null 时不渲染内容 */
  script: ScriptInfo | null
}

export function ScriptLogDialog({ open, onOpenChange, script }: ScriptLogDialogProps) {
  const [content, setContent] = useState('')
  const [paused, setPaused] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const offsetRef = useRef(0)
  const pausedRef = useRef(false)
  const stickRef = useRef(true) // 视口是否贴底（贴底时新数据自动跟随滚动）
  const boxRef = useRef<HTMLDivElement>(null)

  // 打开时重置并拉最后约 200 行（offset=0）
  useEffect(() => {
    if (!open || !script) return
    setContent('')
    setError(null)
    setPaused(false)
    pausedRef.current = false
    offsetRef.current = 0
    stickRef.current = true
    let cancelled = false
    api
      .scriptLogs(script.name, 0)
      .then((res) => {
        if (cancelled) return
        offsetRef.current = res.offset
        setContent(res.content)
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : '日志加载失败'))
    return () => {
      cancelled = true
    }
  }, [open, script])

  // 2s 增量轮询（暂停时跳过，失败静默等下轮）
  useEffect(() => {
    if (!open || !script) return
    const timer = setInterval(async () => {
      if (pausedRef.current) return
      try {
        const res = await api.scriptLogs(script.name, offsetRef.current)
        offsetRef.current = res.offset
        if (res.content) {
          setContent((prev) => {
            let next = prev ? `${prev}\n${res.content}` : res.content
            if (next.length > MAX_BUFFER) next = next.slice(-MAX_BUFFER)
            return next
          })
        }
      } catch {
        /* 静默，下轮重试 */
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [open, script])

  // 新数据到达且视口贴底时自动滚到底
  useEffect(() => {
    const box = boxRef.current
    if (box && stickRef.current) box.scrollTop = box.scrollHeight
  }, [content])

  const handleScroll = () => {
    const box = boxRef.current
    if (!box) return
    stickRef.current = box.scrollTop + box.clientHeight >= box.scrollHeight - 40
  }

  const togglePause = () => {
    setPaused((prev) => {
      pausedRef.current = !prev
      return !prev
    })
  }

  const scrollToBottom = () => {
    const box = boxRef.current
    if (box) box.scrollTop = box.scrollHeight
    stickRef.current = true
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>实时日志 · {script?.title}</DialogTitle>
          <DialogDescription>
            {script?.log_file} · 每 {POLL_MS / 1000}s 增量刷新
            {paused ? '（已暂停）' : ''}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={togglePause}>
            {paused ? <Play className="mr-2 h-4 w-4" /> : <Pause className="mr-2 h-4 w-4" />}
            {paused ? '继续' : '暂停'}
          </Button>
          <Button variant="outline" size="sm" onClick={scrollToBottom}>
            <ArrowDownToLine className="mr-2 h-4 w-4" />
            回到底部
          </Button>
        </div>

        <div
          ref={boxRef}
          onScroll={handleScroll}
          className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap"
        >
          {error ? (
            <p className="text-destructive">{error}</p>
          ) : content ? (
            content
          ) : (
            <p className="text-muted-foreground">暂无日志</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
