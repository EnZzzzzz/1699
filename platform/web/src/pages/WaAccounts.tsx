import { api, useApiData, type WaAccount } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader, LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { MessageCircle, Plus, Phone, FolderKey } from 'lucide-react'

function AccountCard({ account }: { account: WaAccount }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent">
            <MessageCircle className="h-4 w-4" />
          </div>
          <CardTitle className="text-base">{account.name}</CardTitle>
        </div>
        {account.logged_in ? (
          <Badge className="bg-emerald-600 hover:bg-emerald-600">已登录</Badge>
        ) : (
          <Badge variant="secondary">未登录</Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center gap-2">
          <Phone className="h-4 w-4 text-muted-foreground" />
          <span className={account.phone ? 'font-mono' : 'text-muted-foreground'}>
            {account.phone ?? '未知（登录后显示）'}
          </span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <FolderKey className="h-4 w-4" />
          <span className="truncate font-mono text-xs" title={account.auth_dir}>
            {account.auth_dir}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

export default function WaAccounts() {
  const { data, loading, error, reload } = useApiData(api.waAccounts, 60_000)

  return (
    <div className="p-6">
      <PageHeader
        title="WhatsApp 账号"
        desc="用于触达店铺的 WhatsApp 登录态管理"
        extra={
          <Button size="sm" disabled title="即将上线">
            <Plus className="mr-2 h-4 w-4" />
            添加账号（即将上线）
          </Button>
        }
      />

      {loading && !data ? (
        <LoadingState />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState text="暂无 WhatsApp 账号，等待「添加账号」功能上线" />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((a) => (
            <AccountCard key={a.name} account={a} />
          ))}
        </div>
      )}
    </div>
  )
}
