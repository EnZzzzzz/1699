// 画布自定义节点卡片：AtomNode（普通原子）+ ContainerNode（带 body 的容器）
// 编辑态（data.status 缺省）保持白底；监控态（data.status 存在）按 FlowGraph 的 STATUS_META 变色
import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import type { DagNode, NodeState, NodeStatus } from '@/api/types'
import type { AtomNodeData, WorkerState } from '@/lib/flowmap'
import { cn } from '@/lib/utils'

type RFNode = Node<AtomNodeData>

// ---------- 节点状态视觉（移植自 FlowGraph.tsx 的 STATUS_META） ----------

const STATUS_META: Record<NodeStatus, { label: string; card: string; dot: string; text: string }> = {
  pending: {
    label: '待执行',
    card: 'border-slate-200 bg-white text-slate-500',
    dot: 'bg-slate-300',
    text: 'text-slate-500',
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

/** 公共卡片壳：头部（显示名 + 注册名 + 状态圆点/徽标）+ params 摘要 + 失败原因 */
function NodeShell({
  selected,
  dagNode,
  title,
  badge,
  status,
  workers,
}: {
  selected?: boolean
  dagNode: DagNode
  title: string
  badge?: string
  status?: NodeState
  workers?: WorkerState[]
}) {
  const entries = paramEntries(dagNode, 4)
  const total = Object.keys(dagNode.params ?? {}).length
  const meta = status ? metaOf(status) : undefined
  return (
    <div
      className={cn(
        'w-[220px] rounded-lg border px-3 py-2 shadow-sm transition-colors',
        // 监控态按状态变色；编辑态保持白底 + 选中高亮
        meta ? meta.card : selected ? 'border-blue-500 bg-white ring-1 ring-blue-500/40' : 'border-slate-200 bg-white',
        meta && selected && 'ring-1 ring-blue-500/40',
      )}
    >
      <div className="flex items-center gap-1.5">
        {meta && <span className={cn('h-2 w-2 shrink-0 rounded-full', meta.dot)} />}
        <span className="truncate text-sm font-medium text-slate-800">{title}</span>
        {badge && (
          <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">
            {badge}
          </span>
        )}
        {meta && <span className={cn('ml-auto shrink-0 text-[10px] font-medium', meta.text)}>{meta.label}</span>}
      </div>
      <div className="font-mono text-[11px] text-slate-400">{dagNode.atom}</div>
      {/* 并行 worker 状态点：一排最多 10 个，超出省略 */}
      {workers && workers.length > 0 && (
        <div className="mt-1 flex items-center gap-1">
          <span className="text-[10px] text-slate-400">worker</span>
          {workers.slice(0, 10).map((wk) => {
            const wm = STATUS_META[wk.status] ?? STATUS_META.pending
            return (
              <span
                key={wk.w}
                title={`worker ${wk.w} · ${wm.label}`}
                className={cn('h-2 w-2 shrink-0 rounded-full', wm.dot, wk.status === 'running' && 'animate-pulse')}
              />
            )
          })}
          {workers.length > 10 && <span className="text-[10px] text-slate-400">+{workers.length - 10}</span>}
        </div>
      )}
      {entries.length > 0 && (
        <div className="mt-1.5 space-y-0.5 border-t border-slate-100 pt-1.5">
          {entries.map(([k, v]) => (
            <div key={k} className="flex items-baseline gap-1 text-[11px]">
              <span className="shrink-0 font-mono text-slate-400">{k}</span>
              <span className="truncate text-slate-600">{v}</span>
            </div>
          ))}
          {total > entries.length && (
            <div className="text-[11px] text-slate-400">+{total - entries.length}</div>
          )}
        </div>
      )}
      {/* 失败节点：卡片底部一行截断的失败原因（title 放全文） */}
      {status?.status === 'failed' && status.detail && (
        <div className="mt-1 truncate border-t border-red-100 pt-1 text-[11px] text-red-600" title={status.detail}>
          {status.detail}
        </div>
      )}
    </div>
  )
}

/** 普通原子节点：左 target / 右 source Handle */
export const AtomNode = memo(function AtomNode({ data, selected }: NodeProps<RFNode>) {
  return (
    <>
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-slate-300 !bg-slate-400" />
      <NodeShell selected={selected} dagNode={data.dagNode} title={data.title} status={data.status} />
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-slate-300 !bg-slate-400" />
    </>
  )
})

/** 容器节点（body 非空）：额外显示子节点数量徽标 + 并行 worker 状态点 */
export const ContainerNode = memo(function ContainerNode({ data, selected }: NodeProps<RFNode>) {
  const childCount = data.dagNode.body?.length ?? 0
  return (
    <>
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-slate-300 !bg-slate-400" />
      <NodeShell
        selected={selected}
        dagNode={data.dagNode}
        title={data.title}
        badge={`容器 · ${childCount} 个子节点`}
        status={data.status}
        workers={data.workers}
      />
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-slate-300 !bg-slate-400" />
    </>
  )
})

/** params 键值摘要：只取标量值，最多 max 条 */
function paramEntries(dagNode: DagNode, max: number): [string, string][] {
  return Object.entries(dagNode.params ?? {})
    .filter(([, v]) => typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean')
    .slice(0, max)
    .map(([k, v]) => [k, String(v)])
}
