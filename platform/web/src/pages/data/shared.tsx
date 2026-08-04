// 数据浏览页共享件：防抖 Hook + 分页条
import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function useDebouncedValue<T>(value: T, delayMs = 500): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

export function PaginationBar({
  page,
  size,
  total,
  onPageChange,
}: {
  page: number
  size: number
  total: number
  onPageChange: (page: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / size))
  const [jumpTo, setJumpTo] = useState('')

  // 翻页后同步输入框（清空，等待下一次输入）
  useEffect(() => {
    setJumpTo('')
  }, [page])

  const jump = () => {
    const n = Number(jumpTo)
    if (!Number.isInteger(n) || n < 1) return
    onPageChange(Math.min(n, pages))
  }

  return (
    <div className="flex items-center justify-between pt-4">
      <p className="text-sm text-muted-foreground">
        第 {page} / {pages} 页 · 共 {total} 条
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft className="mr-1 h-4 w-4" />
          上一页
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= pages}
          onClick={() => onPageChange(page + 1)}
        >
          下一页
          <ChevronRight className="ml-1 h-4 w-4" />
        </Button>
        <div className="ml-2 flex items-center gap-1.5 text-sm text-muted-foreground">
          跳至
          <Input
            className="h-8 w-16 px-2 text-center text-sm"
            value={jumpTo}
            placeholder={String(page)}
            inputMode="numeric"
            onChange={(e) => setJumpTo(e.target.value.replace(/\D/g, ''))}
            onKeyDown={(e) => {
              if (e.key === 'Enter') jump()
            }}
          />
          页
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            disabled={!jumpTo || Number(jumpTo) < 1}
            onClick={jump}
          >
            跳转
          </Button>
        </div>
      </div>
    </div>
  )
}

/** 库内时间戳已是北京时间字符串（YYYY-MM-DD HH:MM:SS），直接展示，不做时区换算。 */
export function showTime(ts: string | null): string {
  return ts && ts.length > 0 ? ts : '—'
}
