// Dag ↔ React Flow 双向转换（画布模块与页面集成方的契约层）
import type { Node, Edge } from '@xyflow/react'
import type { AtomSpec, Dag, DagNode, NodeState, NodeStatus } from '@/api/types'

/** 自定义节点 data 载荷：atom/container 节点共用 */
export interface AtomNodeData extends Record<string, unknown> {
  dagNode: DagNode // 原始 DAG 节点（params/body/策略等原样带回）
  title: string // 原子显示名
  atomSpec?: AtomSpec // 原子目录项（inputs/outputs/param_spec）
  status?: NodeState // 运行状态（监控模式；缺省时节点保持编辑器白底样式）
  workers?: WorkerState[] // 容器节点的并行 worker 聚合状态（按 w 升序）
}

/** 运行状态覆盖层（监控模式）：key 规则同 progress.nodes（节点id / 容器id/子id / 容器id/子id#w0） */
export interface DagStatusOverlay {
  /** progress.nodes 状态表；提供时节点卡片显示状态色 */
  nodes?: Record<string, NodeState>
}

/** 容器单个并行 worker 的聚合状态 */
export interface WorkerState {
  w: number // worker 序号（#w 后缀的数字）
  status: NodeStatus // 该 worker 各子节点状态聚合后的整体状态
}

/** 自动布局：横向等距排布 */
const AUTO_X_GAP = 260
const AUTO_Y = 120

/**
 * Dag → React Flow：
 * - 每个顶层 DagNode → 一个 RF Node；body 非空为 'container'，否则 'atom'
 * - 位置优先取 dag.ui.positions[id]，缺失按横向等距自动排布
 * - dag.edges → RF Edge；edges 缺省时按 v1 线性语义补出相邻边
 * - overlay.nodes 提供时写入 data.status；容器节点额外聚合 data.workers（并行 worker 状态）
 */
export function dagToRF(
  dag: Dag,
  atomSpecs?: AtomSpec[],
  overlay?: DagStatusOverlay,
): { nodes: Node[]; edges: Edge[] } {
  const specOf = new Map(atomSpecs?.map((s) => [s.name, s]) ?? [])
  const positions = dag.ui?.positions ?? {}
  // 监控模式：预聚合容器并行 worker 状态（容器id → worker序号 → 子节点状态表）
  const workerGroups = groupWorkers(overlay?.nodes)
  const nodes = (dag.nodes ?? []).map((dagNode, i): Node => {
    const isContainer = !!dagNode.body && dagNode.body.length > 0
    const spec = specOf.get(dagNode.atom)
    const data: AtomNodeData = {
      dagNode,
      title: spec?.title ?? dagNode.atom,
      atomSpec: spec,
      status: overlay?.nodes?.[dagNode.id],
    }
    if (isContainer) {
      // 每 worker 聚合整体状态，按 w 升序（readonly 监控场景的并行进度主视觉）
      const wmap = workerGroups.get(dagNode.id)
      if (wmap && wmap.size > 0) {
        data.workers = [...wmap.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([w, children]) => ({ w, status: workerStatus(children) }))
      }
    }
    return {
      id: dagNode.id,
      type: isContainer ? 'container' : 'atom',
      position: positions[dagNode.id] ?? { x: i * AUTO_X_GAP, y: AUTO_Y },
      data,
    }
  })

  // 边：显式 edges 优先；缺省按 nodes 数组序补相邻边（v1 线性语义）
  const rawEdges: [string, string][] =
    dag.edges && dag.edges.length > 0
      ? dag.edges
      : (dag.nodes ?? []).slice(1).map((n, i): [string, string] => [dag.nodes[i].id, n.id])
  const edges = rawEdges.map(
    ([source, target]): Edge => ({
      id: `e-${source}-${target}`,
      source,
      target,
      animated: false,
    }),
  )

  return { nodes, edges }
}

/**
 * React Flow → Dag：
 * - nodes 数组按 edges 做 Kahn 拓扑排序（有环/缺边退回 base.nodes 原顺序）
 * - edges 写回 [source, target][]
 * - 各节点最新位置写入 ui.positions；base 的 version/resources/run_inputs 原样保留
 */
export function rfToDag(nodes: Node[], edges: Edge[], base: Dag): Dag {
  const ordered = topoSort(nodes, edges, base)
  return {
    ...base, // version/resources/run_inputs/其余键原样保留
    nodes: ordered.map((n) => (n.data as AtomNodeData).dagNode),
    edges: edges.map((e) => [e.source, e.target] as [string, string]),
    ui: {
      ...base.ui,
      positions: Object.fromEntries(nodes.map((n) => [n.id, { x: n.position.x, y: n.position.y }])),
    },
  }
}

/** Kahn 拓扑排序：无法覆盖全部节点（有环或悬空边）时退回 base.nodes 原顺序 */
function topoSort(nodes: Node[], edges: Edge[], base: Dag): Node[] {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const indegree = new Map<string, number>()
  const adj = new Map<string, string[]>()
  for (const n of nodes) {
    indegree.set(n.id, 0)
    adj.set(n.id, [])
  }
  let valid = true
  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) {
      valid = false // 悬空边：图与节点集不一致
      break
    }
    indegree.set(e.target, (indegree.get(e.target) ?? 0) + 1)
    adj.get(e.source)!.push(e.target)
  }

  const out: Node[] = []
  if (valid) {
    // 按 nodes 原顺序入队，保证同层节点顺序稳定
    const queue = nodes.filter((n) => (indegree.get(n.id) ?? 0) === 0).map((n) => n.id)
    while (queue.length > 0) {
      const id = queue.shift()!
      out.push(byId.get(id)!)
      for (const next of adj.get(id) ?? []) {
        const d = (indegree.get(next) ?? 0) - 1
        indegree.set(next, d)
        if (d === 0) queue.push(next)
      }
    }
  }

  if (!valid || out.length !== nodes.length) {
    // 有环或图不完整：退回 base.nodes 原顺序（新节点不在 base 中时排到最后，稳定保持 RF 数组序）
    const order = new Map((base.nodes ?? []).map((n, i) => [n.id, i]))
    return [...nodes].sort(
      (a, b) => (order.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (order.get(b.id) ?? Number.MAX_SAFE_INTEGER),
    )
  }
  return out
}

// ---------- 并行 worker 状态聚合（移植自 FlowGraph.tsx，FlowGraph 后续可能删除，勿从那里 import） ----------

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

/** worker 整体状态：任一 running > 任一 failed > aborted > stopped > 全部 ok > pending */
function workerStatus(children: Record<string, NodeState>): NodeStatus {
  const sts = Object.values(children).map((s) => s.status)
  if (sts.some((s) => s === 'running')) return 'running'
  if (sts.some((s) => s === 'failed')) return 'failed'
  if (sts.some((s) => s === 'aborted')) return 'aborted'
  if (sts.some((s) => s === 'stopped')) return 'stopped'
  if (sts.length > 0 && sts.every((s) => s === 'ok')) return 'ok'
  return 'pending'
}
