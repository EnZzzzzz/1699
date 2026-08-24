// 词库产量页：各关键词在 X / FB 两平台的上轮/累计/轮数（数据来自脚本 kw_stats，服务端分页/搜索/筛选/排序）
import { useCallback, useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import {
  api, useApiData,
  type KeywordPlatformStat, type KeywordSort,
  type KeywordPlatformFilter, type KeywordStatusFilter,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { PaginationBar, showTime, useDebouncedValue } from './data/shared'

// 数值展示：null/undefined 为 —，0 照常显示
function num(v: number | null | undefined): string {
  return v == null ? '—' : v.toLocaleString()
}

// 平台子对象为空（该平台没查过）时的整组占位
function platCells(stat: KeywordPlatformStat | null) {
  if (!stat) {
    return (
      <>
        <TableCell className="text-right text-sm text-muted-foreground">—</TableCell>
        <TableCell className="text-right text-sm text-muted-foreground">—</TableCell>
        <TableCell className="text-right text-sm text-muted-foreground">—</TableCell>
        <TableCell className="text-sm text-muted-foreground">—</TableCell>
        <TableCell className="text-sm text-muted-foreground">—</TableCell>
      </>
    )
  }
  return (
    <>
      <TableCell className="text-right text-sm">{num(stat.last_new)}</TableCell>
      <TableCell className="text-right text-sm">{num(stat.new)}</TableCell>
      <TableCell className="text-right text-sm">{num(stat.q)}</TableCell>
      <TableCell className="text-sm text-muted-foreground">{showTime(stat.last_q_at)}</TableCell>
      <TableCell>{platBadge(stat)}</TableCell>
    </>
  )
}

// 单平台状态徽标：活跃=emerald 成功态，已退役=secondary（DESIGN.md §5）
function platBadge(stat: KeywordPlatformStat) {
  return stat.retired ? (
    <Badge variant="secondary">已退役</Badge>
  ) : (
    <Badge
      variant="outline"
      className="border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
    >
      活跃
    </Badge>
  )
}

// 可排序表头：点击切换排序键 / 升降序
function SortableHead({
  label,
  sortKey,
  sort,
  order,
  onSort,
}: {
  label: string
  sortKey: KeywordSort
  sort: KeywordSort
  order: 'asc' | 'desc'
  onSort: (key: KeywordSort) => void
}) {
  const active = sort === sortKey
  return (
    <TableHead className="text-right">
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          'inline-flex items-center gap-1 transition-colors hover:text-foreground',
          active ? 'text-foreground' : 'text-muted-foreground',
        )}
      >
        {label}
        {active ? (
          order === 'desc' ? <ArrowDown className="h-3.5 w-3.5" /> : <ArrowUp className="h-3.5 w-3.5" />
        ) : (
          <ArrowUpDown className="h-3.5 w-3.5 opacity-40" />
        )}
      </button>
    </TableHead>
  )
}

export default function Keywords() {
  const [keyword, setKeyword] = useState('')
  const [platform, setPlatform] = useState<KeywordPlatformFilter>('all')
  const [status, setStatus] = useState<KeywordStatusFilter>('all')
  const [sort, setSort] = useState<KeywordSort>('total_new')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const q = useDebouncedValue(keyword.trim(), 500)

  // 筛选/搜索/排序变化时回到第 1 页
  useEffect(() => {
    setPage(1)
  }, [q, platform, status, sort, order])

  const fetcher = useCallback(
    () => api.keywordsList({ q, platform, status, sort, order, page, page_size: size }),
    [q, platform, status, sort, order, page, size],
  )
  const { data, loading, error, reload } = useApiData(fetcher, 30000, [
    q, platform, status, sort, order, page, size,
  ])

  const onSort = (key: KeywordSort) => {
    if (sort === key) {
      setOrder(order === 'desc' ? 'asc' : 'desc')
    } else {
      setSort(key)
      setOrder('desc')
    }
  }

  return (
    <div className="p-6">
      <PageHeader
        title="词库"
        desc="各关键词在 X / FB 两平台的采集产量（数据来自脚本 kw_stats，30s 自动刷新）"
      />
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <Input
            className="w-64"
            placeholder="搜索关键词"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Select value={platform} onValueChange={(v) => setPlatform(v as KeywordPlatformFilter)}>
            <SelectTrigger className="h-8 w-fit font-medium">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部平台</SelectItem>
              <SelectItem value="x">仅 X</SelectItem>
              <SelectItem value="fb">仅 FB</SelectItem>
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={(v) => setStatus(v as KeywordStatusFilter)}>
            <SelectTrigger className="h-8 w-fit font-medium">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="active">任一活跃</SelectItem>
              <SelectItem value="x_retired">X 已退役</SelectItem>
              <SelectItem value="fb_retired">FB 已退役</SelectItem>
              <SelectItem value="retired">两平台均退役</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {loading && !data ? (
          <LoadingState />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState text="没有符合条件的关键词" />
        ) : (
          <>
            <div className="rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>关键词</TableHead>
                    <SortableHead label="X 上轮" sortKey="x_last_new" sort={sort} order={order} onSort={onSort} />
                    <SortableHead label="X 累计" sortKey="x_new" sort={sort} order={order} onSort={onSort} />
                    <SortableHead label="X 轮数" sortKey="x_q" sort={sort} order={order} onSort={onSort} />
                    <TableHead>X 最近采集</TableHead>
                    <TableHead>X 状态</TableHead>
                    <SortableHead label="FB 上轮" sortKey="fb_last_new" sort={sort} order={order} onSort={onSort} />
                    <SortableHead label="FB 累计" sortKey="fb_new" sort={sort} order={order} onSort={onSort} />
                    <SortableHead label="FB 轮数" sortKey="fb_q" sort={sort} order={order} onSort={onSort} />
                    <TableHead>FB 最近采集</TableHead>
                    <TableHead>FB 状态</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((item) => (
                    <TableRow key={item.kw}>
                      <TableCell className="max-w-72">
                        <div className="truncate text-sm font-medium" title={item.kw}>
                          {item.kw}
                        </div>
                      </TableCell>
                      {platCells(item.x)}
                      {platCells(item.fb)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <PaginationBar
              page={data.page}
              size={data.page_size}
              total={data.total}
              onPageChange={setPage}
              onSizeChange={(s) => {
                setSize(s)
                setPage(1)
              }}
            />
          </>
        )}
      </div>
    </div>
  )
}
