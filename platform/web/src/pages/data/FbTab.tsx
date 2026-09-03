// FB / X 联系方式 Tab：筛选（来源 / wa 状态 / 分桶 / 关键词防抖）+ 导出 + 表格 + 分页
import { useCallback, useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { dataApi, type FbBucket, type FbContactItem, type Paged, type WaFilter } from '@/lib/api-data'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { FbExportDialog } from './FbExportDialog'
import { PaginationBar, showTime, useDebouncedValue } from './shared'

function waBadge(item: FbContactItem) {
  // 运营商/提供商拒绝的无效号（虚拟段等，永远查不出），单独标识，不再落入「未查」
  if (item.wa_source === 'invalid') {
    return (
      <Badge
        variant="outline"
        className="border-destructive/40 bg-destructive/10 text-destructive"
      >
        无效
      </Badge>
    )
  }
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

const BUCKET_LABELS: Record<FbBucket, string> = {
  declared_wa: '声明 WA',
  cn_uncertain: '国内待查',
  overseas: '海外',
}

function bucketBadge(bucket: string) {
  const label = BUCKET_LABELS[bucket as FbBucket] ?? bucket
  return <Badge variant="secondary">{label}</Badge>
}

// X 来源判定与后端/看板同口径（post_url 含 x.com/twitter.com）
function isX(postUrl: string) {
  return postUrl.includes('x.com') || postUrl.includes('twitter.com')
}

function sourceBadge(postUrl: string) {
  return isX(postUrl)
    ? <Badge variant="outline" className="text-foreground">X</Badge>
    : <Badge variant="outline" className="text-muted-foreground">FB</Badge>
}

// 微信查号单元格：有微信 → 头像+昵称；无微信/未查 → 徽标
function wxCell(c: FbContactItem) {
  if (c.wx_registered === 1) {
    return (
      <div className="flex items-center gap-2">
        {c.wx_avatar && (
          <img
            src={`/api/wechat/avatar/${c.number}`}
            alt=""
            className="h-8 w-8 shrink-0 rounded-full bg-muted object-cover"
            loading="lazy"
            onError={(e) => { e.currentTarget.style.display = 'none' }}
          />
        )}
        <span className="max-w-32 truncate text-sm" title={c.wx_nick ?? undefined}>
          {c.wx_nick || '—'}
        </span>
      </div>
    )
  }
  if (c.wx_registered === 0) {
    return <Badge variant="secondary">无微信</Badge>
  }
  return (
    <Badge variant="outline" className="text-muted-foreground">
      未查
    </Badge>
  )
}

const WX_GENDER_LABELS: Record<string, string> = {
  male: '男',
  female: '女',
  unknown: '未知',
}

export function FbTab() {
  const [wa, setWa] = useState<WaFilter | 'all'>('all')
  const [bucket, setBucket] = useState<FbBucket | 'all'>('all')
  const [source, setSource] = useState<'fb' | 'x' | 'all'>('all')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const q = useDebouncedValue(keyword.trim(), 500)

  const [data, setData] = useState<Paged<FbContactItem> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)

  // 筛选条件变化时回到第 1 页
  useEffect(() => {
    setPage(1)
  }, [wa, bucket, source, q])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await dataApi.fbContacts({
        wa: wa === 'all' ? '' : wa,
        bucket: bucket === 'all' ? '' : bucket,
        source: source === 'all' ? '' : source,
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
  }, [wa, bucket, source, q, page, size])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-4 pt-4">
      <div className="flex flex-wrap items-center gap-4">
        <Select value={source} onValueChange={(v) => setSource(v as 'fb' | 'x' | 'all')}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="来源" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部来源</SelectItem>
            <SelectItem value="fb">Facebook</SelectItem>
            <SelectItem value="x">X</SelectItem>
          </SelectContent>
        </Select>
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
        <Select value={bucket} onValueChange={(v) => setBucket(v as FbBucket | 'all')}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="分桶" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部分桶</SelectItem>
            <SelectItem value="declared_wa">声明 WA</SelectItem>
            <SelectItem value="cn_uncertain">国内待查</SelectItem>
          </SelectContent>
        </Select>
        <Input
          className="w-64"
          placeholder="搜索号码 / 群组 / 帖子链接"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() => setExportOpen(true)}
        >
          <Download className="mr-1.5 h-4 w-4" />
          导出
        </Button>
      </div>

      <FbExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        filters={{
          wa: wa === 'all' ? '' : wa,
          bucket: bucket === 'all' ? '' : bucket,
          source: source === 'all' ? '' : source,
          q,
        }}
      />

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
                  <TableHead>来源</TableHead>
                  <TableHead>号码</TableHead>
                  <TableHead>分桶</TableHead>
                  <TableHead>WhatsApp</TableHead>
                  <TableHead>查询时间</TableHead>
                  <TableHead>微信</TableHead>
                  <TableHead>性别</TableHead>
                  <TableHead>来源群组</TableHead>
                  <TableHead>帖子链接</TableHead>
                  <TableHead>发现时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>{sourceBadge(c.post_url)}</TableCell>
                    <TableCell className="font-mono text-sm font-medium">{c.number}</TableCell>
                    <TableCell>{bucketBadge(c.bucket)}</TableCell>
                    <TableCell>{waBadge(c)}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {showTime(c.wa_checked_at)}
                    </TableCell>
                    <TableCell>{wxCell(c)}</TableCell>
                    <TableCell className="text-sm">
                      {c.wx_gender ? WX_GENDER_LABELS[c.wx_gender] ?? '—' : '—'}
                    </TableCell>
                    <TableCell className="max-w-56">
                      <div className="truncate text-sm" title={c.group_name ?? undefined}>
                        {c.group_name || '—'}
                      </div>
                      <div className="truncate text-xs text-muted-foreground">
                        {c.keyword || ''}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-56">
                      <a
                        className="block truncate text-sm text-muted-foreground underline-offset-4 hover:underline"
                        href={c.post_url}
                        target="_blank"
                        rel="noreferrer"
                        title={c.post_url}
                      >
                        {c.post_url}
                      </a>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {showTime(c.first_seen_at)}
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
