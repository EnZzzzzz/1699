// ComfyUI 风格可拖拽节点画板（P1 核心画布模块）
// 编辑模式：左侧原子面板 + 拖拽/连线/删除编辑；readonly：纯展示
import { useCallback, useEffect, useMemo, useRef, type DragEvent, type JSX } from 'react'
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { AtomSpec, Dag, DagNode, NodeState } from '@/api/types'
import { dagToRF, rfToDag, type AtomNodeData } from '@/lib/flowmap'
import { cn } from '@/lib/utils'
import { AtomPalette, ATOM_DRAG_MIME } from './AtomPalette'
import { AtomNode, ContainerNode } from './nodes/AtomNode'

export interface FlowCanvasProps {
  dag: Dag
  atomSpecs: AtomSpec[]
  /** 编辑模式必填；readonly 时忽略 */
  onChange?: (dag: Dag) => void
  readonly?: boolean
  className?: string
  /** 运行状态覆盖层（监控模式）：key 规则同 progress.nodes；变化时节点变色 */
  statusNodes?: Record<string, NodeState>
}

/** 自定义节点类型注册（模块级常量，避免每次渲染重建） */
const nodeTypes = { atom: AtomNode, container: ContainerNode }

/** 外层：包 ReactFlowProvider（screenToFlowPosition 等 hook 依赖 Provider） */
export function FlowCanvas(props: FlowCanvasProps): JSX.Element {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner {...props} />
    </ReactFlowProvider>
  )
}

function FlowCanvasInner({ dag, atomSpecs, onChange, readonly = false, className, statusNodes }: FlowCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const { screenToFlowPosition, getNodes, getEdges } = useReactFlow()
  const wrapperRef = useRef<HTMLDivElement>(null)
  /** 节点拖拽中不 emit，待 onNodeDragStop 统一抛出 */
  const draggingRef = useRef(false)
  /** 最近一次同步进画板的 dag 结构 key，用于跳过 onChange 回灌 */
  const lastSyncKeyRef = useRef('')
  /** 最近一次从画板抛出的 RF 结构 key（含位置），用于抑制无变化 emit */
  const lastEmitKeyRef = useRef('')
  /** emit 时 rfToDag 的 base 取最新 props.dag */
  const dagRef = useRef(dag)
  dagRef.current = dag
  /** emit 预告回灌 key 时附带的最新状态覆盖层 key（与同步 effect 的 key 格式一致） */
  const statusKeyRef = useRef('')
  statusKeyRef.current = statusNodes ? JSON.stringify(statusNodes) : ''

  const specMap = useMemo(() => new Map(atomSpecs.map((s) => [s.name, s])), [atomSpecs])

  /** dag 结构序列化 key（不含 ui 位置，避免自身拖放回灌） */
  const syncKeyOf = (d: Dag) => JSON.stringify({ nodes: d.nodes ?? [], edges: d.edges ?? [] })
  /** 状态覆盖层序列化 key：监控模式 dag 不变、只有状态变，状态变化必须触发重新同步 */
  const statusKeyOf = (s?: Record<string, NodeState>) => (s ? JSON.stringify(s) : '')
  /** RF 状态序列化 key（含位置；不含选中态等瞬态） */
  const emitKeyOf = (ns: Node[], es: Edge[]) =>
    JSON.stringify({
      nodes: ns.map((n) => [
        n.id,
        n.type,
        Math.round(n.position.x),
        Math.round(n.position.y),
        (n.data as AtomNodeData).dagNode,
      ]),
      edges: es.map((e) => [e.source, e.target]),
    })

  // props.dag（引用）或状态覆盖层变化时重新同步进画板；自身 onChange 造成的回灌按 key 跳过
  useEffect(() => {
    const key = `${syncKeyOf(dag)}|${statusKeyOf(statusNodes)}`
    if (key === lastSyncKeyRef.current) return
    lastSyncKeyRef.current = key
    const rf = dagToRF(dag, atomSpecs, statusNodes ? { nodes: statusNodes } : undefined)
    lastEmitKeyRef.current = emitKeyOf(rf.nodes, rf.edges)
    setNodes(rf.nodes)
    setEdges(rf.edges)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dag, atomSpecs, statusNodes, setNodes, setEdges])

  /** 统一出口：结构有变化才 rfToDag 并上抛；同时预告回灌 key */
  const emit = useCallback(
    (ns: Node[], es: Edge[]) => {
      if (readonly || !onChange) return
      const key = emitKeyOf(ns, es)
      if (key === lastEmitKeyRef.current) return
      lastEmitKeyRef.current = key
      const next = rfToDag(ns, es, dagRef.current)
      lastSyncKeyRef.current = `${syncKeyOf(next)}|${statusKeyRef.current}`
      onChange(next)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [readonly, onChange],
  )

  // nodes/edges 任何变化（连线/删除/落子）后统一 emit；
  // 直接读 store 最新状态，规避 effect 闭包里的过期数组
  useEffect(() => {
    if (draggingRef.current) return
    emit(getNodes(), getEdges())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges, emit, getNodes, getEdges])

  // ---------- 连线规则：禁自连、禁重复边 ----------
  const isValidConnection = useCallback(
    (conn: Edge | Connection) => {
      if (!conn.source || !conn.target || conn.source === conn.target) return false
      return !getEdges().some((e) => e.source === conn.source && e.target === conn.target)
    },
    [getEdges],
  )

  const onConnect = useCallback(
    (conn: Connection) => {
      if (readonly) return
      if (!isValidConnection(conn)) return
      setEdges((eds) => addEdge({ ...conn, animated: false }, eds))
    },
    [readonly, isValidConnection, setEdges],
  )

  // ---------- 从原子面板添加节点 ----------
  const addAtomNode = useCallback(
    (spec: AtomSpec, position: { x: number; y: number }) => {
      if (readonly) return
      // id 形式 ${atom}-${毫秒base36}${随机后缀}，保证快速连续添加也唯一
      const id = `${spec.name}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`
      const dagNode: DagNode = { id, atom: spec.name }
      const data: AtomNodeData = { dagNode, title: spec.title, atomSpec: spec }
      setNodes((ns) => ns.concat({ id, type: 'atom', position, data }))
    },
    [readonly, setNodes],
  )

  const onDragOver = useCallback((e: DragEvent) => {
    if (e.dataTransfer.types.includes(ATOM_DRAG_MIME)) {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
    }
  }, [])

  const onDrop = useCallback(
    (e: DragEvent) => {
      if (readonly) return
      const name = e.dataTransfer.getData(ATOM_DRAG_MIME)
      if (!name) return
      e.preventDefault()
      const spec = specMap.get(name)
      if (!spec) return
      addAtomNode(spec, screenToFlowPosition({ x: e.clientX, y: e.clientY }))
    },
    [readonly, specMap, addAtomNode, screenToFlowPosition],
  )

  /** 面板双击添加：落在画布可视区中心附近（加小偏移防完全重叠） */
  const onPaletteAdd = useCallback(
    (spec: AtomSpec) => {
      const bounds = wrapperRef.current?.getBoundingClientRect()
      const center = bounds
        ? screenToFlowPosition({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 })
        : { x: 120, y: 120 }
      addAtomNode(spec, { x: center.x + Math.random() * 40 - 20, y: center.y + Math.random() * 40 - 20 })
    },
    [addAtomNode, screenToFlowPosition],
  )

  return (
    <div className={cn('flex h-[560px] w-full overflow-hidden rounded-lg border bg-slate-50', className)}>
      {!readonly && <AtomPalette atomSpecs={atomSpecs} onAdd={onPaletteAdd} />}
      <div ref={wrapperRef} className="relative min-w-0 flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onNodeDragStart={() => {
            draggingRef.current = true
          }}
          onNodeDragStop={() => {
            draggingRef.current = false
            emit(getNodes(), getEdges())
          }}
          onDragOver={onDragOver}
          onDrop={onDrop}
          deleteKeyCode={readonly ? null : ['Delete', 'Backspace']}
          nodesDraggable={!readonly}
          nodesConnectable={!readonly}
          elementsSelectable={!readonly}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
          <MiniMap pannable zoomable className="!bg-white/80" />
        </ReactFlow>
      </div>
    </div>
  )
}
