import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, asPaged, errorMessage, isNotImplemented } from '@/api/client'
import type { Contact, Shop } from '@/api/types'
import { EmptyState, NotImplementedState } from '@/components/EmptyState'
import { toast } from 'sonner'
import { Download, Search, ChevronLeft, ChevronRight } from 'lucide-react'

const PAGE_SIZE = 20

interface Filters {
  status: string
  category: string
  keyword: string
}

const EMPTY_FILTERS: Filters = { status: '', category: '', keyword: '' }

export default function Data() {
  const [tab, setTab] = useState<'shops' | 'contacts'>('shops')
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<(Shop | Contact)[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [notImpl, setNotImpl] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { page, page_size: PAGE_SIZE }
      if (tab === 'shops') {
        if (applied.status) params.status = applied.status
        if (applied.category) params.category = applied.category
      }
      // 后端 /api/contacts 仅支持 keyword 筛选
      if (applied.keyword) params.keyword = applied.keyword
      const res = await api.get(`/${tab === 'shops' ? 'shops' : 'contacts'}`, { params })
      const paged = asPaged<Shop | Contact>(res.data, page)
      setRows(paged.items)
      setTotal(paged.total)
      setNotImpl(false)
      setError(null)
    } catch (e) {
      if (isNotImplemented(e)) {
        setNotImpl(true)
        setRows([])
        setTotal(0)
      } else {
        setError(errorMessage(e))
      }
    } finally {
      setLoading(false)
    }
  }, [tab, page, applied])

  useEffect(() => {
    void load()
  }, [load])

  const switchTab = (v: string) => {
    setTab(v as 'shops' | 'contacts')
    setFilters(EMPTY_FILTERS)
    setApplied(EMPTY_FILTERS)
    setPage(1)
  }

  const search = () => {
    setPage(1)
    setApplied({ ...filters })
  }

  const exportUrl = (fmt: 'xlsx' | 'csv') => {
    const target = tab === 'shops' ? 'shops' : 'contacts'
    const qs = new URLSearchParams()
    if (tab === 'shops') {
      if (applied.status) qs.set('status', applied.status)
      if (applied.category) qs.set('category', applied.category)
    }
    if (applied.keyword) qs.set('keyword', applied.keyword)
    const suffix = qs.toString()
    return `/api/export/${target}.${fmt}${suffix ? `?${suffix}` : ''}`
  }

  const doExport = (fmt: 'xlsx' | 'csv') => {
    // 直接触发浏览器下载（带当前筛选条件）；端点未实现时后端返回 501/404 页面，不会白屏
    window.open(exportUrl(fmt), '_blank')
    toast.info(`已请求导出 ${fmt.toUpperCase()}（带当前筛选条件）`)
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">数据</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => doExport('xlsx')}>
            <Download className="mr-2 h-4 w-4" />
            导出 Excel
          </Button>
          <Button variant="outline" size="sm" onClick={() => doExport('csv')}>
            <Download className="mr-2 h-4 w-4" />
            导出 CSV
          </Button>
        </div>
      </div>

      <Tabs value={tab} onValueChange={switchTab}>
        <TabsList>
          <TabsTrigger value="shops">店铺</TabsTrigger>
          <TabsTrigger value="contacts">联系方式</TabsTrigger>
        </TabsList>

        <div className="my-4 flex flex-wrap items-center gap-3">
          {tab === 'shops' && (
            <>
              <Select
                value={filters.status || '__all__'}
                onValueChange={(v) => setFilters((f) => ({ ...f, status: v === '__all__' ? '' : v }))}
              >
                <SelectTrigger className="w-36">
                  <SelectValue placeholder="状态" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">全部状态</SelectItem>
                  <SelectItem value="pending">待抓取</SelectItem>
                  <SelectItem value="done">已完成</SelectItem>
                  <SelectItem value="failed">失败</SelectItem>
                  <SelectItem value="blocked">被风控</SelectItem>
                </SelectContent>
              </Select>
              <Input
                className="w-40"
                placeholder="类目"
                value={filters.category}
                onChange={(e) => setFilters((f) => ({ ...f, category: e.target.value }))}
              />
            </>
          )}
          <Input
            className="w-56"
            placeholder={tab === 'shops' ? '关键词（店铺名等）' : '关键词（店铺名/联系人/手机）'}
            value={filters.keyword}
            onChange={(e) => setFilters((f) => ({ ...f, keyword: e.target.value }))}
            onKeyDown={(e) => e.key === 'Enter' && search()}
          />
          <Button size="sm" onClick={search}>
            <Search className="mr-2 h-4 w-4" />
            查询
          </Button>
        </div>

        <TabsContent value="shops" forceMount className="data-[state=inactive]:hidden">
          <DataBody
            kind="shops"
            rows={rows}
            loading={loading}
            notImpl={notImpl}
            error={error}
            total={total}
            page={page}
            totalPages={totalPages}
            onRetry={() => void load()}
            onPage={setPage}
          />
        </TabsContent>
        <TabsContent value="contacts" forceMount className="data-[state=inactive]:hidden">
          <DataBody
            kind="contacts"
            rows={rows}
            loading={loading}
            notImpl={notImpl}
            error={error}
            total={total}
            page={page}
            totalPages={totalPages}
            onRetry={() => void load()}
            onPage={setPage}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function DataBody({
  kind,
  rows,
  loading,
  notImpl,
  error,
  total,
  page,
  totalPages,
  onRetry,
  onPage,
}: {
  kind: 'shops' | 'contacts'
  rows: (Shop | Contact)[]
  loading: boolean
  notImpl: boolean
  error: string | null
  total: number
  page: number
  totalPages: number
  onRetry: () => void
  onPage: (p: number) => void
}) {
  if (notImpl) {
    return <NotImplementedState feature={kind === 'shops' ? '店铺数据浏览' : '联系方式数据浏览'} />
  }
  if (error) {
    return <EmptyState icon="error" title="无法获取数据" description={error} actionLabel="重试" onAction={onRetry} />
  }
  if (loading) {
    return <div className="py-16 text-center text-muted-foreground">加载中…</div>
  }
  if (rows.length === 0) {
    return <EmptyState title="暂无数据" description="调整筛选条件或先运行采集任务" />
  }

  return (
    <>
      <div className="rounded-lg border bg-background">
        <Table>
          {kind === 'shops' ? <ShopHeader /> : <ContactHeader />}
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>{kind === 'shops' ? <ShopCells shop={row as Shop} /> : <ContactCells contact={row as Contact} />}</TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">共 {total.toLocaleString()} 条</p>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            <ChevronLeft className="mr-1 h-4 w-4" />
            上一页
          </Button>
          <span className="text-sm tabular-nums text-muted-foreground">
            {page} / {totalPages}
          </span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
            下一页
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        </div>
      </div>
    </>
  )
}

const cell = (v: unknown) =>
  v === null || v === undefined || v === '' ? <span className="text-muted-foreground">-</span> : String(v)

function ShopHeader() {
  return (
    <TableHeader>
      <TableRow>
        <TableHead className="w-16">ID</TableHead>
        <TableHead>店铺名</TableHead>
        <TableHead>类目</TableHead>
        <TableHead>状态</TableHead>
        <TableHead>链接</TableHead>
      </TableRow>
    </TableHeader>
  )
}

function ShopCells({ shop }: { shop: Shop }) {
  return (
    <>
      <TableCell className="font-mono text-muted-foreground">#{shop.id}</TableCell>
      <TableCell>{cell(shop.name)}</TableCell>
      <TableCell>{cell(shop.category_keyword)}</TableCell>
      <TableCell>{cell(shop.status)}</TableCell>
      <TableCell className="max-w-56 truncate font-mono text-xs">
        {shop.url ? (
          <a href={shop.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
            {shop.domain || shop.url}
          </a>
        ) : (
          '-'
        )}
      </TableCell>
    </>
  )
}

function ContactHeader() {
  return (
    <TableHeader>
      <TableRow>
        <TableHead className="w-16">ID</TableHead>
        <TableHead>店铺</TableHead>
        <TableHead>联系人</TableHead>
        <TableHead>手机</TableHead>
        <TableHead>电话</TableHead>
        <TableHead>地址</TableHead>
        <TableHead>抓取时间</TableHead>
      </TableRow>
    </TableHeader>
  )
}

function ContactCells({ contact }: { contact: Contact }) {
  return (
    <>
      <TableCell className="font-mono text-muted-foreground">#{contact.id}</TableCell>
      <TableCell>
        {contact.shop_name ? (
          <span title={contact.domain}>{contact.shop_name}</span>
        ) : (
          cell(contact.shop_id)
        )}
      </TableCell>
      <TableCell>{cell(contact.contact_person)}</TableCell>
      <TableCell className="font-mono text-sm">{cell(contact.mobile)}</TableCell>
      <TableCell className="font-mono text-sm">{cell(contact.phone)}</TableCell>
      <TableCell className="max-w-56 truncate" title={contact.address ?? undefined}>
        {cell(contact.address)}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{cell(contact.scraped_at)}</TableCell>
    </>
  )
}
