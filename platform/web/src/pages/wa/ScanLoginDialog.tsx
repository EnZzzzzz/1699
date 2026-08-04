// WhatsApp 扫码登录引导：展示二维码，2s 轮询登录状态，支持失败重试
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { api, type WaLoginState, type WaLoginStatus } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { CheckCircle2, Loader2, RefreshCw, XCircle } from 'lucide-react'

const POLL_MS = 2_000
/** 二维码大约 60s 自动刷新一次，用于倒计时提示 */
const QR_REFRESH_SEC = 60

interface ScanLoginDialogProps {
  /** 账号名；null 表示未开启扫码流程 */
  name: string | null
  onClose: (connected: boolean) => void
}

export function ScanLoginDialog({ name, onClose }: ScanLoginDialogProps) {
  const [status, setStatus] = useState<WaLoginStatus | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  /** 距离下一次二维码自动刷新的倒计时（秒） */
  const [countdown, setCountdown] = useState(QR_REFRESH_SEC)
  const connectedRef = useRef(false)
  const mtimeRef = useRef<number | null>(null)
  /** 是否已到达终态（connected / failed / expired），到达后停止轮询 */
  const terminalRef = useRef(false)

  const open = name !== null

  const poll = useCallback(async (accountName: string) => {
    try {
      const res = await api.waAccountLogin(accountName)
      setLoadError(null)
      setStatus(() => {
        if (res.qr_mtime !== mtimeRef.current) {
          mtimeRef.current = res.qr_mtime
          setCountdown(QR_REFRESH_SEC)
        }
        return res
      })
      if (res.state === 'connected') connectedRef.current = true
      if (res.state !== 'waiting_scan') terminalRef.current = true
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '获取登录状态失败')
    }
  }, [])

  // 打开时立即拉取并启动 2s 轮询；到达终态后停止
  useEffect(() => {
    if (!name) return
    connectedRef.current = false
    terminalRef.current = false
    mtimeRef.current = null
    setStatus(null)
    setLoadError(null)
    setCountdown(QR_REFRESH_SEC)
    poll(name)
    const timer = setInterval(() => {
      if (!terminalRef.current) poll(name)
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [name, poll])

  const state: WaLoginState | null = status?.state ?? null

  // 倒计时：仅在等待扫码时每秒递减
  useEffect(() => {
    if (!open || state !== 'waiting_scan') return
    const timer = setInterval(() => {
      setCountdown((c) => (c <= 1 ? QR_REFRESH_SEC : c - 1))
    }, 1_000)
    return () => clearInterval(timer)
  }, [open, state])

  const handleRetry = async () => {
    if (!name) return
    setRetrying(true)
    try {
      await api.createWaAccount(name)
      terminalRef.current = false
      mtimeRef.current = null
      setCountdown(QR_REFRESH_SEC)
      await poll(name)
      toast.info('已重新发起登录，请扫描新二维码')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '重试失败')
    } finally {
      setRetrying(false)
    }
  }

  const handleClose = () => {
    onClose(connectedRef.current)
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>扫码登录「{name}」</DialogTitle>
          <DialogDescription>
            打开 WhatsApp 手机端 → 已关联的设备 → 关联设备，扫描下方二维码。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col items-center gap-4 py-2">
          {state === 'connected' ? (
            <div className="flex flex-col items-center gap-3 py-8">
              <CheckCircle2 className="h-14 w-14 text-success" />
              <p className="text-base font-medium">已登录</p>
              <p className="text-sm text-muted-foreground">账号「{name}」登录成功，可以开始使用了。</p>
            </div>
          ) : state === 'failed' || state === 'expired' ? (
            <div className="flex flex-col items-center gap-3 py-8">
              <XCircle className="h-14 w-14 text-danger" />
              <p className="text-base font-medium">
                {state === 'expired' ? '二维码已过期' : '登录失败'}
              </p>
              <p className="text-sm text-muted-foreground">请重新发起登录并扫描新的二维码。</p>
              <Button onClick={handleRetry} disabled={retrying}>
                {retrying ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                重新获取二维码
              </Button>
            </div>
          ) : (
            <>
              <div className="flex h-64 w-64 items-center justify-center rounded-lg border border-border bg-muted/40">
                {status?.qr_url ? (
                  <img
                    key={status.qr_mtime ?? 'qr'}
                    src={status.qr_url}
                    alt="WhatsApp 登录二维码"
                    className="h-60 w-60 rounded-md object-contain"
                  />
                ) : (
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {loadError ? (
                  <span className="text-danger">{loadError}（重试中…）</span>
                ) : (
                  <>二维码约 {QR_REFRESH_SEC} 秒自动刷新属正常，约 {countdown}s 后刷新</>
                )}
              </p>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {state === 'connected' ? '完成' : '关闭'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
