import { useState } from 'react'
import { toast } from 'sonner'
import { api, useApiData, type WaAccount } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { LoadingState, ErrorState, EmptyState } from '@/components/PageState'
import { MessageCircle, Plus, Phone, FolderKey, Trash2, Loader2, ScanLine } from 'lucide-react'
import { AddAccountDialog } from './wa/AddAccountDialog'
import { ScanLoginDialog } from './wa/ScanLoginDialog'

interface AccountCardProps {
  account: WaAccount
  scanning: boolean
  onDeleted: () => void
}

function AccountCard({ account, scanning, onDeleted }: AccountCardProps) {
  const [deleting, setDeleting] = useState(false)

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await api.deleteWaAccount(account.name)
      toast.success(`账号「${account.name}」已删除`)
      onDeleted()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent">
            <MessageCircle className="h-4 w-4" />
          </div>
          <CardTitle className="text-base">{account.name}</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          {scanning && (
            <Badge className="bg-info text-info-foreground hover:bg-info">
              <ScanLine className="mr-1 h-3 w-3" />
              扫码登录中
            </Badge>
          )}
          {account.logged_in ? (
            <Badge className="bg-success text-success-foreground hover:bg-success">已登录</Badge>
          ) : (
            !scanning && <Badge variant="secondary">未登录</Badge>
          )}
        </div>
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
        <div className="flex justify-end pt-2">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm" className="text-danger hover:text-danger">
                {deleting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="mr-2 h-4 w-4" />
                )}
                删除
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>删除账号「{account.name}」？</AlertDialogTitle>
                <AlertDialogDescription>
                  删除后将同时清除该账号的登录凭证（auth 目录），需要重新扫码登录。此操作不可恢复。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction onClick={handleDelete}>确认删除</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </CardContent>
    </Card>
  )
}

export default function WaAccounts() {
  const { data, loading, error, reload } = useApiData(api.waAccounts, 60_000)
  const [addOpen, setAddOpen] = useState(false)
  /** 正在扫码引导的账号名；null 表示未在扫码流程中 */
  const [scanningName, setScanningName] = useState<string | null>(null)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          用于触达店铺的 WhatsApp 登录态管理，多账号凭证完全隔离
        </p>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          添加账号
        </Button>
      </div>

      {loading && !data ? (
        <LoadingState />
      ) : error && !data ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState text="暂无 WhatsApp 账号，点击右上角「添加账号」开始" />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((a) => (
            <AccountCard
              key={a.name}
              account={a}
              scanning={scanningName === a.name}
              onDeleted={reload}
            />
          ))}
        </div>
      )}

      <AddAccountDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={(name) => {
          setScanningName(name)
          reload()
        }}
      />
      <ScanLoginDialog
        name={scanningName}
        onClose={(connected) => {
          setScanningName(null)
          reload()
          if (connected) toast.success('账号已登录')
        }}
      />
    </div>
  )
}
