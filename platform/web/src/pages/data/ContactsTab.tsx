// 联系方式 Tab：筛选（wa 状态 / 仅含手机号 / 关键词防抖）+ 表格 + 分页
import { useCallback, useEffect, useState } from 'react'
import { dataApi, type ContactItem, type Paged, type WaFilter } from '@/lib/api-data'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { PaginationBar, showTime, useDebouncedValue } from './shared'

function waBadge(item: ContactItem) {
  if (item.wa_registered === 1) {
    return (
      <Badge
        variant="outline"
        className="border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
      >
        已注册
      </Badge>
    )
  }
  if (item.wa_registered === 0) {
    return <Badge variant="secondary">未注册</Badge>
  }
  return (
    <Badge variant="outline" className="text-muted-foreground">
      未查
    </Badge>
  )
}

export function ContactsTab() {
  const [wa, setWa] = useState<WaFilter | 'all'>('all')
  const [hasMobile, setHasMobile] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const q = useDebouncedValue(keyword.trim(), 500)

  const [data, setData] = useState<Paged<ContactItem> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 筛选条件变化时回到第 1 页
  useEffect(() => {
    setPage(1)
  }, [wa, hasMobile, q])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await dataApi.contacts({
        wa: wa === 'all' ? '' : wa,
        has_mobile: hasMobile,
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
  }, [wa, hasMobile, q, page, size])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-4 pt-4">
      <div className="flex flex-wrap items-center gap-4">
        <Select value={wa} onValueChange={(v) => setWa(v as WaFilter | 'all')}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="WhatsApp 状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部</SelectItem>
            <SelectItem value="registered">已注册</SelectItem>
            <SelectItem value="unregistered">未注册</SelectItem>
            <SelectItem value="unchecked">未查</SelectItem>
          </SelectContent>
        </Select>
        <div className="flex items-center gap-2">
          <Switch id="has-mobile" checked={hasMobile} onCheckedChange={setHasMobile} />
          <Label htmlFor="has-mobile" className="text-sm text-muted-foreground">
            仅含手机号
          </Label>
        </div>
        <Input
          className="w-64"
          placeholder="搜索联系人 / 手机号 / 固话"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      {loading && !data ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState text="没有符合条件的联系方式" />
      ) : (
        <>
          <div className="rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>联系人</TableHead>
                  <TableHead>性别</TableHead>
                  <TableHead>手机号</TableHead>
                  <TableHead>固话</TableHead>
                  <TableHead>所属店铺</TableHead>
                  <TableHead>WhatsApp</TableHead>
                  <TableHead>查询时间</TableHead>
                  <TableHead>采集时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">{c.contact_person || '—'}</TableCell>
                    <TableCell className="text-sm">{c.gender || '—'}</TableCell>
                    <TableCell className="font-mono text-sm">{c.mobile || '—'}</TableCell>
                    <TableCell className="font-mono text-sm">{c.phone || '—'}</TableCell>
                    <TableCell className="max-w-56">
                      <div className="truncate text-sm" title={c.shop_name ?? undefined}>
                        {c.shop_name || '—'}
                      </div>
                      <div className="truncate text-xs text-muted-foreground">
                        {c.shop_domain || ''}
                      </div>
                    </TableCell>
                    <TableCell>{waBadge(c)}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {showTime(c.wa_checked_at)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {showTime(c.scraped_at)}
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
