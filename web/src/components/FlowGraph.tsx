import { Fragment, useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { Dag, DagNode, NodeState, NodeStatus } from '@/api/types'
import { cn } from '@/lib/utils'
import { ChevronDown } from 'lucide-react'

/**
 * 只读 DAG 流程图（docs/flow-architecture.md §8 v1）：
 * 垂直流式布局，顶层节点卡片 + 箭头连线；容器节点（带 body）渲染为分组框，
 * body 子节点垂直嵌套；parallel>1 时显示 "×N" 徽标并可下钻 worker 明细。
 * 状态来自 props.nodes（progress.nodes）：key = 节点id / 容器id/子id / 容器id/子id#w0。
 * v1 线性执行，连线按 nodes 数组序绘制，edges 字段不参与布局。
 */
export function FlowGraph({
  dag,
  nodes,
  atomTitles,
  highlightWorker = null,
}: {
  dag: Dag
  nodes?: Record<string, NodeState>
  /** 原子注册名 → 显示名（/api/atoms）；缺省退回注册名 */
  atomTitles?: Record<string, string>
  /** 高亮某个并行 worker（其余淡显）；null = 不高亮 */
  highlightWorker?: number | null
}) {
  const titleOf = (atom: string) => atomTitles?.[atom] ?? atom
  const workerGroups = useMemo(() => groupWorkers(nodes), [nodes])

  return (
    <div className="flex flex-col">
      {(dag.nodes ?? []).map((node, i) => (
        <Fragment key={node.id}>
          {i > 0 && <Connector />}
          {node.body && node.body.length > 0 ? (
            <ContainerCard
              node={node}
              nodeKey={node.id}
              nodes={nodes}
              titleOf={titleOf}
              workers={workerGroups.get(node.id)}
              highlightWorker={highlightWorker}
            />
          ) : (
            <NodeCard node={node} state={nodes?.[node.id]} titleOf={titleOf} />
          )}
        </Fragment>
      ))}
    </div>
  )
}

// ---------- 节点状态视觉 ----------

const STATUS_META: Record<NodeStatus, { label: string; card: string; dot: string; text: string }> = {
  pending: {
    label: '待执行',
    card: 'border-slate-200 bg-background text-muted-foreground',
    dot: 'bg-slate-300',
    text: 'text-muted-foreground',
  },
  running: {
    label: '运行中',
    card: 'border-blue-400 bg-blue-50/60 animate-pulse',
    dot: 'bg-blue-500',
    text: 'text-blue-700',
  },
  ok: {
    label: '完成',
    card: 'border-emerald-300 bg-emerald-50/50',
    dot: 'bg-emerald-500',
    text: 'text-emerald-700',
  },
  failed: {
    label: '失败',
    card: 'border-red-400 bg-red-50/60',
    dot: 'bg-red-500',
    text: 'text-red-700',
  },
  aborted: {
    label: '已中止',
    card: 'border-orange-400 bg-orange-50/60',
    dot: 'bg-orange-500',
    text: 'text-orange-700',
  },
  stopped: {
    label: '已停止',
    card: 'border-orange-300 bg-orange-50/50',
    dot: 'bg-orange-400',
    text: 'text-orange-700',
  },
}

function metaOf(state: NodeState | undefined) {
  return STATUS_META[state?.status ?? 'pending'] ?? STATUS_META.pending
}

/** 节点间连接箭头 */
function Connector({ small }: { small?: boolean }) {
  return (
    <div className={cn('flex justify-center', small ? 'py-0' : 'py-0.5')}>
      <ChevronDown className={cn('text-muted-foreground/50', small ? 'h-3.5 w-3.5' : 'h-4 w-4')} />
    </div>
  )
}

// ---------- 普通节点卡片 ----------

function NodeCard({
  node,
  state,
  titleOf,
  compact,
}: {
  node: DagNode
  state: NodeState | undefined
  titleOf: (atom: string) => string
  /** 容器内子节点：更紧凑的内边距 */
  compact?: boolean
}) {
  const meta = metaOf(state)
  const summary = paramSummary(node)
  const badges = policyBadges(node, titleOf)
  return (
    <div className={cn('rounded-lg border px-4 shadow-sm transition-colors', compact ? 'py-2' : 'py-3', meta.card)}>
      <div className="flex items-center gap-2">
        <span className={cn('h-2 w-2 shrink-0 rounded-full', meta.dot)} />
        <span className="text-sm font-medium">{titleOf(node.atom)}</span>
        <span className="font-mono text-xs text-muted-foreground">{node.atom}</span>
        <span className={cn('ml-auto text-xs font-medium', meta.text)}>{meta.label}</span>
      </div>

      {(summary || badges.length > 0) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 pl-4">
          {summary && <span className="text-xs text-muted-foreground">{summary}</span>}
          {badges.map((b) => (
            <Badge key={b} variant="outline" className="text-[11px] font-normal">
              {b}
            </Badge>
          ))}
        </div>
      )}

      <NodeProgress state={state} />
    </div>
  )
}

/** 节点实时进度：running 且有 total/elapsed 时画进度条；其余字段小字展示；终态显示耗时/失败原因 */
function NodeProgress({ state }: { state: NodeState | undefined }) {
  if (!state) return null
  const p = state.progress ?? {}
  const total = numOf(p.total)
  const elapsed = numOf(p.elapsed)
  const showBar = state.status === 'running' && total != null && total > 0 && elapsed != null
  const extras = Object.entries(p).filter(
    ([k, v]) => k !== 'total' && k !== 'elapsed' && (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean'),
  )
  return (
    <div className="mt-2 space-y-1 pl-4">
      {showBar && (
        <div className="flex items-center gap-2">
          <Progress value={Math.min(100, (elapsed / total) * 100)} className="h-1.5" />
          <span className="w-24 shrink-0 text-xs tabular-nums text-muted-foreground">
            {fmtNum(elapsed)} / {fmtNum(total)} 秒
          </span>
        </div>
      )}
      {extras.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {extras.map(([k, v]) => `${k}: ${typeof v === 'number' ? fmtNum(v) : String(v)}`).join(' · ')}
        </p>
      )}
      {state.status !== 'running' && state.elapsed != null && (
        <p className="text-xs text-muted-foreground">耗时 {fmtNum(state.elapsed)} 秒</p>
      )}
      {(state.status === 'failed' || state.status === 'aborted') && state.detail && (
        <p className="text-xs text-red-600">{state.detail}</p>
      )}
    </div>
  )
}

// ---------- 容器节点（for_each_shop） ----------

function ContainerCard({
  node,
  nodeKey,
  nodes,
  titleOf,
  workers,
  highlightWorker,
}: {
  node: DagNode
  nodeKey: string
  nodes?: Record<string, NodeState>
  titleOf: (atom: string) => string
  workers?: Map<number, Record<string, NodeState>>
  highlightWorker: number | null
}) {
  const state = nodes?.[nodeKey]
  const meta = metaOf(state)
  const parallel = numOf(node.params?.parallel) ?? 1
  const [open, setOpen] = useState(true)
  const cp = state?.progress ?? {}
  const quotaLine = containerQuotaLine(cp)

  return (
    <div className={cn('rounded-lg border-2 px-4 py-3 transition-colors', meta.card)}>
      {/* 容器头 */}
      <div className="flex items-center gap-2">
        <span className={cn('h-2 w-2 shrink-0 rounded-full', meta.dot)} />
        <span className="text-sm font-medium">{titleOf(node.atom)}</span>
        <span className="font-mono text-xs text-muted-foreground">{node.atom}</span>
        {parallel > 1 && (
          <Badge className="bg-blue-600 text-white hover:bg-blue-600">×{parallel}</Badge>
        )}
        <span className={cn('ml-auto text-xs font-medium', meta.text)}>{meta.label}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 pl-4 text-xs text-muted-foreground">
        <span>{paramSummary(node)}</span>
        {quotaLine && <span>{quotaLine}</span>}
      </div>
      <NodeProgress state={state} />

      {/* body 子图 */}
      <div className="mt-3 flex flex-col rounded-md border border-dashed bg-background/60 p-3">
        {node.body!.map((child, i) => (
          <Fragment key={child.id}>
            {i > 0 && <Connector small />}
            <NodeCard
              node={child}
              state={nodes?.[`${nodeKey}/${child.id}`]}
              titleOf={titleOf}
              compact
            />
          </Fragment>
        ))}
      </div>

      {/* 并行 worker 下钻 */}
      {workers && workers.size > 0 && (
        <Collapsible open={open} onOpenChange={setOpen} className="mt-3">
          <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent">
            <span>
              Worker 明细
              <span className="ml-2 font-normal text-muted-foreground">{workers.size} 个并行 worker</span>
            </span>
            <ChevronDown className="h-3.5 w-3.5 transition-transform [[data-state=open]>&]:rotate-180" />
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-2 pt-2">
            {[...workers.entries()]
              .sort((a, b) => a[0] - b[0])
              .map(([w, children]) => (
                <WorkerRow
                  key={w}
                  worker={w}
                  body={node.body!}
                  childrenStates={children}
                  titleOf={titleOf}
                  dimmed={highlightWorker != null && highlightWorker !== w}
                  highlighted={highlightWorker === w}
                />
              ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

/** 单个 worker：状态总览 + 各子节点状态 chip（当前运行节点高亮） */
function WorkerRow({
  worker,
  body,
  childrenStates,
  titleOf,
  dimmed,
  highlighted,
}: {
  worker: number
  body: DagNode[]
  childrenStates: Record<string, NodeState>
  titleOf: (atom: string) => string
  dimmed: boolean
  highlighted: boolean
}) {
  const overall = workerStatus(childrenStates)
  const meta = metaOf({ status: overall })
  return (
    <div
      className={cn(
        'rounded-md border bg-background px-3 py-2 transition-opacity',
        highlighted && 'ring-2 ring-blue-500',
        dimmed && 'opacity-50',
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cn('h-1.5 w-1.5 rounded-full', meta.dot)} />
        <span className="text-xs font-medium">worker {worker}</span>
        <span className={cn('text-xs', meta.text)}>{STATUS_META[overall].label}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {body.map((child) => {
          const st = childrenStates[child.id]
          const m = metaOf(st)
          const running = st?.status === 'running'
          return (
            <span
              key={child.id}
              title={st?.detail ?? undefined}
              className={cn(
                'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]',
                running ? 'border-blue-400 bg-blue-50 text-blue-700' : m.text,
                !running && 'bg-background',
              )}
            >
              <span className={cn('h-1.5 w-1.5 rounded-full', m.dot, running && 'animate-pulse')} />
              {titleOf(child.atom)}
              {running && st?.progress && progressHint(st.progress) && (
                <span className="tabular-nums text-muted-foreground">{progressHint(st.progress)}</span>
              )}
            </span>
          )
        })}
      </div>
    </div>
  )
}

// ---------- 工具函数 ----------

/** 解析 nodes 字典中带 #w 后缀的 key：容器id → worker 序号 → 子节点 id → 状态 */
function groupWorkers(nodes?: Record<string, NodeState>): Map<string, Map<number, Record<string, NodeState>>> {
  const out = new Map<string, Map<number, Record<string, NodeState>>>()
  if (!nodes) return out
  for (const [key, st] of Object.entries(nodes)) {
    const m = /^(.+)\/([^/]+)#w(\d+)$/.exec(key)
    if (!m) continue
    const [, containerId, childId, w] = m
    const worker = Number(w)
    if (!out.has(containerId)) out.set(containerId, new Map())
    const wmap = out.get(containerId)!
    if (!wmap.has(worker)) wmap.set(worker, {})
    wmap.get(worker)![childId] = st
  }
  return out
}

/** worker 整体状态：任一 running > 任一 failed/aborted > 全部 ok > pending */
function workerStatus(children: Record<string, NodeState>): NodeStatus {
  const sts = Object.values(children).map((s) => s.status)
  if (sts.some((s) => s === 'running')) return 'running'
  if (sts.some((s) => s === 'failed')) return 'failed'
  if (sts.some((s) => s === 'aborted')) return 'aborted'
  if (sts.some((s) => s === 'stopped')) return 'stopped'
  if (sts.length > 0 && sts.every((s) => s === 'ok')) return 'ok'
  return 'pending'
}

/** 关键参数摘要（节点卡片上的小字） */
function paramSummary(node: DagNode): string | null {
  const p = node.params ?? {}
  switch (node.atom) {
    case 'sleep':
    case 'human_pause': {
      const min = numOf(p.min) ?? 0
      const max = numOf(p.max) ?? min
      return min === max ? `等待 ${fmtNum(min)} 秒` : `等待 ${fmtNum(min)}~${fmtNum(max)} 秒`
    }
    case 'acquire_channel':
      return `通道 ×${numOf(p.n) ?? 1}${p.proxy ? '（走代理）' : '（直连）'}`
    case 'launch_browser':
      return p.headed ? '有头浏览器（可视）' : '无头浏览器'
    case 'confirm_human':
      return `人工确认（超时 ${numOf(p.timeout) ?? 600} 秒）`
    case 'claim_shops':
      return `每批认领 ${numOf(p.n) ?? 1} 家`
    case 'ensure_fresh_ip':
      return `IP 保鲜检查（换 IP 重试 ${numOf(p.ip_retry) ?? 3} 次）`
    case 'crawl_category':
      return `翻页间隔 ${fmtNum(numOf(p.delay_min) ?? 0)}~${fmtNum(numOf(p.delay_max) ?? 0)} 秒`
    case 'for_each_shop': {
      const parts = [`每批 ${numOf(p.num) ?? 10} 个`]
      const rest = numOf(p.batch_rest)
      if (rest) parts.push(`批间休 ${fmtNum(rest)} 秒`)
      const maxBatches = numOf(p.max_batches)
      if (maxBatches) parts.push(`最多 ${maxBatches} 批`)
      const limit = numOf(p.limit)
      if (limit) parts.push(`上限 ${limit} 个`)
      return parts.join(' · ')
    }
    default: {
      const entries = Object.entries(p)
        .filter(([, v]) => typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean')
        .slice(0, 3)
      if (entries.length === 0) return null
      return entries.map(([k, v]) => `${k}=${String(v)}`).join(' · ')
    }
  }
}

/** 策略徽标：on_blocked/on_net_error → 「风控换IP×2」；circuit_breaker → 「熔断5」 */
function policyBadges(node: DagNode, titleOf: (atom: string) => string): string[] {
  const out: string[] = []
  const OUTCOME_LABEL: Record<string, string> = {
    blocked: '风控',
    net_error: '网络',
    empty: '空结果',
  }
  for (const [key, val] of Object.entries(node)) {
    if (!key.startsWith('on_') || !val || typeof val !== 'object') continue
    const policy = val as { do?: string; retry?: number }
    if (!policy.do) continue
    const outcome = OUTCOME_LABEL[key.slice(3)] ?? key.slice(3)
    out.push(`${outcome}${titleOf(policy.do)}×${policy.retry ?? 0}`)
  }
  if (node.circuit_breaker?.consecutive_fail) {
    out.push(`熔断${node.circuit_breaker.consecutive_fail}`)
  }
  return out
}

/** 容器配额进度行（parallel>1 时引擎上报 batch/done/fetched/ok/empty/failed） */
function containerQuotaLine(p: Record<string, unknown>): string | null {
  const batch = numOf(p.batch)
  const fetched = numOf(p.fetched)
  if (batch == null && fetched == null) return null
  const parts: string[] = []
  if (batch != null) parts.push(`批次 ${batch}`)
  if (fetched != null) parts.push(`已抓 ${fetched}`)
  const ok = numOf(p.ok)
  const failed = numOf(p.failed)
  if (ok != null || failed != null) parts.push(`成功 ${ok ?? 0} / 失败 ${failed ?? 0}`)
  return parts.join(' · ')
}

/** worker chip 上的运行进度提示（sleep 显示 x/y 秒；fetch 显示出口 IP） */
function progressHint(p: Record<string, unknown>): string | null {
  const total = numOf(p.total)
  const elapsed = numOf(p.elapsed)
  if (total != null && total > 0 && elapsed != null) return `${fmtNum(elapsed)}/${fmtNum(total)}s`
  if (typeof p.exit_ip === 'string' && p.exit_ip) return p.exit_ip
  return null
}

function numOf(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function fmtNum(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}
