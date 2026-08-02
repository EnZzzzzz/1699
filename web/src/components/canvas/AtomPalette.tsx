// 画布左侧原子列表面板：搜索过滤 + 拖拽/双击两种添加方式
import { useMemo, useState } from 'react'
import type { AtomSpec } from '@/api/types'

export const ATOM_DRAG_MIME = 'application/atom-name'

export function AtomPalette({
  atomSpecs,
  onAdd,
}: {
  atomSpecs: AtomSpec[]
  /** 双击原子项时通知父级（由父级决定落点，如画布中央） */
  onAdd?: (spec: AtomSpec) => void
}) {
  const [kw, setKw] = useState('')
  const filtered = useMemo(() => {
    const q = kw.trim().toLowerCase()
    if (!q) return atomSpecs
    return atomSpecs.filter(
      (s) => s.name.toLowerCase().includes(q) || s.title.toLowerCase().includes(q),
    )
  }, [atomSpecs, kw])

  return (
    <div className="flex w-56 shrink-0 flex-col rounded-lg border bg-white">
      <div className="border-b px-3 py-2">
        <input
          value={kw}
          onChange={(e) => setKw(e.target.value)}
          placeholder="搜索原子…"
          className="h-7 w-full rounded-md border border-slate-200 bg-slate-50 px-2 text-xs outline-none placeholder:text-slate-400 focus:border-blue-400"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <p className="px-1 py-3 text-center text-xs text-slate-400">无匹配原子</p>
        )}
        {filtered.map((spec) => (
          <div
            key={spec.name}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData(ATOM_DRAG_MIME, spec.name)
              e.dataTransfer.effectAllowed = 'move'
            }}
            onDoubleClick={() => onAdd?.(spec)}
            title={`${spec.name}（拖到画布或双击添加）`}
            className="mb-1 cursor-grab select-none rounded-md border border-slate-200 bg-slate-50/60 px-2.5 py-1.5 transition-colors hover:border-blue-300 hover:bg-blue-50/50 active:cursor-grabbing"
          >
            <div className="truncate text-xs font-medium text-slate-700">{spec.title}</div>
            <div className="truncate font-mono text-[10px] text-slate-400">{spec.name}</div>
          </div>
        ))}
      </div>
      <div className="border-t px-3 py-1.5 text-[10px] text-slate-400">拖到画布 / 双击添加</div>
    </div>
  )
}
