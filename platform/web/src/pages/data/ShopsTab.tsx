// 店铺 Tab：筛选（状态 / 关键词防抖）+ 表格 + 分页
import { useCallback, useEffect, useState } from 'react'
import { dataApi, type Paged, type ShopItem } from '@/lib/api-data'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { PaginationBar, showTime, useDebouncedValue } from './shared'

export function shopStatusBadge(status: string) {
  switch (status) {
    case 'done':
      return (
        <Badge
          variant="outline"
          className="border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
        >
          已完成
        </Badge>
      )
    case 'pending':
      return <Badge variant="secondary">待采集</Badge>
    case 'no_contact':
      return (
        <Badge variant="outline" className="text-muted-foreground">
          无联系方式
        </Badge>
      )
    case 'failed':
      return <Badge variant="destructive">失败</Badge>
    default:
      return <Badge variant="outline">{status}</Badge>
  }
}

export function ShopsTab() {
  const [status, setStatus] = useState<string>('all')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const q = useDebouncedValue(keyword.trim(), 500)

  const [data, setData] = useState<Paged<ShopItem> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setPage(1)
  }, [status, q])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await dataApi.shops({
        status: status === 'all' ? '' : status,
        q,
        page,
        size,
      })
      setData(result)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '未知错误')
    } finally {
      setLoading(false)
    }
  }, [status, q, page, size])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-4 pt-4">
      <div className="flex flex-wrap items-center gap-4">
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部</SelectItem>
            <SelectItem value="pending">待采集</SelectItem>
            <SelectItem value="done">已完成</SelectItem>
            <SelectItem value="no_contact">无联系方式</SelectItem>
            <SelectItem value="failed">失败</SelectItem>
          </SelectContent>
        </Select>
        <Input
          className="w-64"
          placeholder="搜索域名 / 店名"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      {loading && !data ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState text="没有符合条件的店铺" />
      ) : (
        <>
          <div className="rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>域名</TableHead>
                  <TableHead>店名</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">联系方式数</TableHead>
                  <TableHead>首次采集</TableHead>
                  <TableHead>最近见到</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-mono text-sm">{s.domain}</TableCell>
                    <TableCell className="max-w-64">
                      <span className="block truncate font-medium" title={s.name ?? undefined}>
                        {s.name || '—'}
                      </span>
                    </TableCell>
                    <TableCell>{shopStatusBadge(s.status)}</TableCell>
                    <TableCell className="text-right text-sm">{s.contact_count}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {showTime(s.first_seen_at)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {showTime(s.last_seen_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <PaginationBar
            page={data.page}
            size={data.size}
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
  )
}
