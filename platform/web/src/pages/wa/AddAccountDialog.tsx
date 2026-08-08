// 添加 WhatsApp 账号对话框：账号名校验 + 登录方式（扫码/配对码）+ 创建
import { useState } from 'react'
import { toast } from 'sonner'
import { api, ApiError, type WaLoginMethod } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

const NAME_RE = /^[A-Za-z0-9-]{1,20}$/
// 配对码登录手机号：带国家码纯数字 8-15 位
const PHONE_RE = /^\d{8,15}$/

export function validateAccountName(name: string): string | null {
  if (!name) return '请输入账号名'
  if (!NAME_RE.test(name)) return '仅限字母、数字、短横线，长度 1-20 位'
  return null
}

interface AddAccountDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 创建成功（进入 waiting_scan）后回调，携带账号名、登录方式与手机号（配对码方式） */
  onCreated: (name: string, method: WaLoginMethod, phone?: string) => void
}

export function AddAccountDialog({ open, onOpenChange, onCreated }: AddAccountDialogProps) {
  const [name, setName] = useState('')
  const [method, setMethod] = useState<WaLoginMethod>('qr')
  const [phone, setPhone] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setName('')
      setMethod('qr')
      setPhone('')
    }
    onOpenChange(next)
  }

  const handleSubmit = async () => {
    const trimmed = name.trim()
    const invalid = validateAccountName(trimmed)
    if (invalid) {
      toast.error(invalid)
      return
    }
    const trimmedPhone = phone.trim()
    if (method === 'pairing' && !PHONE_RE.test(trimmedPhone)) {
      toast.error('请输入带国家码的纯数字手机号（8-15 位），如 8613800138000')
      return
    }
    setSubmitting(true)
    try {
      const res = await api.createWaAccount(
        trimmed, method, method === 'pairing' ? trimmedPhone : undefined)
      toast.success(method === 'pairing'
        ? `账号「${res.name}」已创建，正在获取配对码`
        : `账号「${res.name}」已创建，请扫码登录`)
      handleOpenChange(false)
      onCreated(res.name, method, method === 'pairing' ? trimmedPhone : undefined)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.error('账号已存在或存在冲突，请换个名字')
      } else if (e instanceof ApiError && e.status === 422) {
        toast.error(e.message || '账号名或手机号不合法')
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
            创建后需要用 WhatsApp 手机端完成登录，可选扫码或配对码方式。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
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
          <div className="space-y-2">
            <Label>登录方式</Label>
            <RadioGroup
              value={method}
              onValueChange={(v) => setMethod(v as WaLoginMethod)}
              className="flex gap-6"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="qr" id="wa-method-qr" />
                <Label htmlFor="wa-method-qr" className="font-normal">扫码登录</Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="pairing" id="wa-method-pairing" />
                <Label htmlFor="wa-method-pairing" className="font-normal">配对码登录</Label>
              </div>
            </RadioGroup>
          </div>
          {method === 'pairing' && (
            <div className="space-y-2">
              <Label htmlFor="wa-account-phone">手机号</Label>
              <Input
                id="wa-account-phone"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="带国家码纯数字，如 8613800138000"
                className="font-mono"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSubmit()
                }}
              />
              <p className="text-xs text-muted-foreground">
                该手机号对应的 WhatsApp 账号将收到 8 位配对码，在「已链接的设备 → 关联设备 → 改用电话号码」输入。
              </p>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? '创建中…' : method === 'pairing' ? '创建并获取配对码' : '创建并扫码'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
