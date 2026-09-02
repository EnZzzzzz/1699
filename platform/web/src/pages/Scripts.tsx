// 采集脚本管理页：四脚本卡片（状态/额度/产量）+ 启停/重启 + 参数配置 + 实时日志
import { useState } from 'react'
import { toast } from 'sonner'
import { api, useApiData, type ScriptInfo } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import {
  Loader2, Play, RotateCw, ScrollText, SlidersHorizontal, Square, TerminalSquare,
} from 'lucide-react'
import { ScriptParamsDialog } from './scripts/ScriptParamsDialog'
import { ScriptLogDialog } from './scripts/ScriptLogDialog'
import { ScriptStartDialog } from './scripts/ScriptStartDialog'

// 数值展示：null/undefined 为 —
function num(v: number | null | undefined): string {
  return v == null ? '—' : v.toLocaleString()
}

// 状态徽标：运行中=成功态 emerald，已停止=中性 secondary（DESIGN.md §5）
function runBadge(running: boolean) {
  return running ? (
    <Badge variant="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
      运行中
    </Badge>
  ) : (
    <Badge variant="secondary">已停止</Badge>
  )
}

// 额度行：标签 + 进度条 + 已用/上限/剩余
function QuotaRow({ label, used, limit }: { label: string; used: number | null | undefined; limit: number | null | undefined }) {
  const pct = used != null && limit ? Math.min(100, (used / limit) * 100) : 0
  const remaining = used != null && limit != null ? limit - used : null
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span>
          {num(used)} / {num(limit)}
          {remaining != null && (
            <span className={remaining < 0 ? 'ml-2 text-danger' : 'ml-2 text-muted-foreground'}>
              剩余 {num(remaining)}
            </span>
          )}
        </span>
      </div>
      <Progress value={pct} className="h-1.5" />
    </div>
  )
}

// 指标行：标签 + 数值（WA 等无额度概念的纯数值指标）
function MetricRow({ label, value, highlight }: { label: string; value: number | null | undefined; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={highlight ? 'font-medium text-backlog' : ''}>{num(value)}</span>
    </div>
  )
}

// 各脚本指标区
function ScriptStats({ script }: { script: ScriptInfo }) {
  const s = script.stats
  if (script.name === 'fb') {
    return (
      <div className="space-y-3">
        <QuotaRow label="memo23 今日用量" used={s.memo23_used} limit={s.memo23_limit} />
        <MetricRow label="SERP 查询数（今日）" value={s.serp_queries} />
        <MetricRow label="今日采集" value={s.collected_today} />
      </div>
    )
  }
  if (script.name === 'x') {
    return (
      <div className="space-y-3">
        <QuotaRow label="今日结果用量" used={s.x_used} limit={s.x_limit} />
        <QuotaRow label="总预算用量（行）" used={s.total_results} limit={s.total_cap} />
        <MetricRow label="今日采集" value={s.collected_today} />
      </div>
    )
  }
  if (script.name === 'li') {
    return (
      <div className="space-y-3">
        <QuotaRow label="WA 已注册进度" used={s.li_wa_registered} limit={s.li_target} />
        <QuotaRow label="累计费用（美元）" used={s.li_cost} limit={s.li_budget} />
        <MetricRow label="总 leads" value={s.li_leads} />
        <MetricRow label="总号码" value={s.li_contacts} />
        <MetricRow label="待查 WA" value={s.li_pending} />
        <MetricRow label="已搜组合" value={s.li_combos} />
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <MetricRow label="今日已查" value={s.checked_today} />
      <MetricRow label="待查积压" value={s.backlog} highlight />
    </div>
  )
}

function ScriptCard({ script, onChanged, onStart, onEditParams, onShowLogs }: {
  script: ScriptInfo
  onChanged: () => void
  /** fb/x 启动走选词面板；wa/li 无词库直接启动（不传 onStart） */
  onStart?: (script: ScriptInfo) => void
  onEditParams: (script: ScriptInfo) => void
  onShowLogs: (script: ScriptInfo) => void
}) {
  const [acting, setActing] = useState<'start' | 'stop' | 'restart' | null>(null)
  const [stopConfirm, setStopConfirm] = useState(false)

  const handleAction = async (action: 'start' | 'stop' | 'restart') => {
    setActing(action)
    try {
      if (action === 'start') {
        await api.scriptStart(script.name)
        toast.success(`「${script.title}」已启动`)
      } else if (action === 'stop') {
        await api.scriptStop(script.name)
        toast.success(`「${script.title}」已停止`)
      } else {
        await api.scriptRestart(script.name)
        toast.success(`「${script.title}」已重启`)
      }
      onChanged()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '操作失败')
    } finally {
      setActing(null)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent">
            <TerminalSquare className="h-4 w-4" />
          </div>
          <div>
            <CardTitle className="text-base">{script.title}</CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {script.running
                ? `PID ${script.pid}${script.uptime ? ` · 已运行 ${script.uptime}` : ''}`
                : script.log_file}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {runBadge(script.running)}
          <div className="flex items-center gap-2">
            <Button
              variant="outline" size="sm"
              onClick={() => (onStart ? onStart(script) : handleAction('start'))}
              disabled={script.running || acting !== null}
            >
              {acting === 'start' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
              启动
            </Button>
            <Button
              variant="destructive" size="sm"
              onClick={() => setStopConfirm(true)}
              disabled={!script.running || acting !== null}
            >
              {acting === 'stop' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Square className="mr-2 h-4 w-4" />}
              停止
            </Button>
            <Button
              variant="outline" size="sm"
              onClick={() => handleAction('restart')}
              disabled={!script.running || acting !== null}
            >
              {acting === 'restart' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RotateCw className="mr-2 h-4 w-4" />}
              重启
            </Button>
            <Button variant="outline" size="sm" onClick={() => onEditParams(script)} disabled={acting !== null}>
              <SlidersHorizontal className="mr-2 h-4 w-4" />
              参数
            </Button>
            <Button variant="outline" size="sm" onClick={() => onShowLogs(script)}>
              <ScrollText className="mr-2 h-4 w-4" />
              日志
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ScriptStats script={script} />
      </CardContent>

      {/* 停止确认（WA 会连 bash 循环壳一起杀） */}
      <AlertDialog open={stopConfirm} onOpenChange={setStopConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>停止「{script.title}」？</AlertDialogTitle>
            <AlertDialogDescription>
              将终止该脚本的全部进程（SIGTERM，5s 未退出则 SIGKILL），采集随即中断。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => handleAction('stop')}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              确认停止
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

export default function Scripts() {
  const { data, loading, error, reload } = useApiData(api.scriptsList, 5000)
  const [startTarget, setStartTarget] = useState<ScriptInfo | null>(null)
  const [paramsTarget, setParamsTarget] = useState<ScriptInfo | null>(null)
  const [logsTarget, setLogsTarget] = useState<ScriptInfo | null>(null)
  const [startOpen, setStartOpen] = useState(false)
  const [paramsOpen, setParamsOpen] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)

  // fb/x 启动前弹选词面板；wa/li 无词库概念，由卡片内直接启动
  const openStart = (script: ScriptInfo) => {
    setStartTarget(script)
    setStartOpen(true)
  }

  const openParams = (script: ScriptInfo) => {
    setParamsTarget(script)
    setParamsOpen(true)
  }
  const openLogs = (script: ScriptInfo) => {
    setLogsTarget(script)
    setLogsOpen(true)
  }

  return (
    <div className="p-6">
      <PageHeader
        title="采集脚本"
        desc="四个常驻采集脚本的启停、额度配置与实时日志（5s 自动刷新）"
      />

      {loading && !data ? (
        <LoadingState />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState text="暂无脚本配置" />
      ) : (
        <div className="space-y-4">
          {data.map((s) => (
            <ScriptCard
              key={s.name}
              script={s}
              onChanged={reload}
              onStart={s.name === 'fb' || s.name === 'x' ? openStart : undefined}
              onEditParams={openParams}
              onShowLogs={openLogs}
            />
          ))}
        </div>
      )}

      <ScriptStartDialog
        open={startOpen}
        onOpenChange={setStartOpen}
        script={startTarget}
        onStarted={reload}
      />
      <ScriptParamsDialog
        open={paramsOpen}
        onOpenChange={setParamsOpen}
        script={paramsTarget}
        onSaved={reload}
      />
      <ScriptLogDialog
        open={logsOpen}
        onOpenChange={setLogsOpen}
        script={logsTarget}
      />
    </div>
  )
}
