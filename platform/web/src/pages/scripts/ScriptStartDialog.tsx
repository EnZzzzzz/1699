// 选词启动对话框（fb/x）：勾选本次要跑的关键词子集，全选=默认词库；重启沿用本次选词
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { api, type ScriptInfo } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2, Play } from 'lucide-react'

interface ScriptStartDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 目标脚本（仅 fb/x 使用本对话框），null 时不渲染内容 */
  script: ScriptInfo | null
  onStarted: () => void
}

export function ScriptStartDialog({ open, onOpenChange, script, onStarted }: ScriptStartDialogProps) {
  const [words, setWords] = useState<{ word: string; retired: boolean }[]>([])
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // 打开时拉取词库，默认全选
  useEffect(() => {
    if (!open || !script) return
    setFilter('')
    setLoading(true)
    api.scriptKeywords(script.name)
      .then((res) => {
        setWords(res.keywords)
        setChecked(new Set(res.keywords.map((k) => k.word)))
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : '词库加载失败'))
      .finally(() => setLoading(false))
  }, [open, script])

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return words
    return words.filter((k) => k.word.toLowerCase().includes(q))
  }, [words, filter])

  if (!script) return null

  const toggle = (word: string, on: boolean) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (on) next.add(word)
      else next.delete(word)
      return next
    })
  }

  const handleStart = async () => {
    setSubmitting(true)
    try {
      // 全选 = 默认词库（清除选词记录），否则传选中的子集
      const all = checked.size === words.length
      await api.scriptStart(script.name, all
        ? { clearKeywords: true }
        : { keywords: words.map((k) => k.word).filter((w) => checked.has(w)) })
      toast.success(all
        ? `「${script.title}」已启动（默认词库 ${words.length} 词）`
        : `「${script.title}」已启动（选词 ${checked.size} / ${words.length}）`)
      onOpenChange(false)
      onStarted()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '启动失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>启动 · {script.title}</DialogTitle>
          <DialogDescription>
            勾选本次要跑的关键词，重启会沿用本次选词；已退役的词会被脚本自动跳过。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="flex items-center gap-2">
            <Input
              className="w-64"
              placeholder="搜索关键词"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <Button
              variant="outline" size="sm"
              onClick={() => setChecked(new Set(words.map((k) => k.word)))}
              disabled={loading || words.length === 0}
            >
              全选
            </Button>
            <Button
              variant="outline" size="sm"
              onClick={() => setChecked(new Set())}
              disabled={loading || checked.size === 0}
            >
              清空
            </Button>
            <span className="ml-auto text-xs text-muted-foreground">
              已选 {checked.size} / {words.length}
            </span>
          </div>

          <div className="rounded-lg border border-border">
            <ScrollArea className="h-72">
              {loading ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />词库加载中…
                </div>
              ) : visible.length === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  无匹配关键词
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-x-4 p-2">
                  {visible.map((k) => (
                    <label
                      key={k.word}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
                    >
                      <Checkbox
                        checked={checked.has(k.word)}
                        onCheckedChange={(v) => toggle(k.word, v === true)}
                      />
                      <span className="truncate">{k.word}</span>
                      {k.retired && (
                        <Badge variant="secondary" className="ml-auto shrink-0">已退役</Badge>
                      )}
                    </label>
                  ))}
                </div>
              )}
            </ScrollArea>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={handleStart} disabled={submitting || loading || checked.size === 0}>
            {submitting
              ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              : <Play className="mr-2 h-4 w-4" />}
            {submitting ? '启动中…' : `启动（${checked.size} 词）`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
