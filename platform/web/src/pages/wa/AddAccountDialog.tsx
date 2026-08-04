// 添加 WhatsApp 账号对话框：账号名校验 + 创建，成功后进入扫码引导
import { useState } from 'react'
import { toast } from 'sonner'
import { api, ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const NAME_RE = /^[A-Za-z0-9-]{1,20}$/

export function validateAccountName(name: string): string | null {
  if (!name) return '请输入账号名'
  if (!NAME_RE.test(name)) return '仅限字母、数字、短横线，长度 1-20 位'
  return null
}

interface AddAccountDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 创建成功（进入 waiting_scan）后回调，携带账号名 */
  onCreated: (name: string) => void
}

export function AddAccountDialog({ open, onOpenChange, onCreated }: AddAccountDialogProps) {
  const [name, setName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleOpenChange = (next: boolean) => {
    if (!next) setName('')
    onOpenChange(next)
  }

  const handleSubmit = async () => {
    const trimmed = name.trim()
    const invalid = validateAccountName(trimmed)
    if (invalid) {
      toast.error(invalid)
      return
    }
    setSubmitting(true)
    try {
      const res = await api.createWaAccount(trimmed)
      toast.success(`账号「${res.name}」已创建，请扫码登录`)
      handleOpenChange(false)
      onCreated(res.name)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.error('账号已存在或存在冲突，请换个名字')
      } else if (e instanceof ApiError && e.status === 422) {
        toast.error('账号名不合法：仅限字母、数字、短横线，长度 1-20 位')
      } else {
        toast.error(e instanceof Error ? e.message : '创建失败')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加 WhatsApp 账号</DialogTitle>
          <DialogDescription>
            创建后需要用 WhatsApp 手机端扫描二维码完成登录。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 py-2">
          <Label htmlFor="wa-account-name">账号名</Label>
          <Input
            id="wa-account-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如 shop-01"
            maxLength={20}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSubmit()
            }}
          />
          <p className="text-xs text-muted-foreground">仅限字母、数字、短横线，最长 20 位。</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? '创建中…' : '创建并扫码'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
