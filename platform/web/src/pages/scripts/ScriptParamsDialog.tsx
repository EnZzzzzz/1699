// 采集脚本参数对话框：每脚本暴露 1 个关键启动参数，支持「保存」与「保存并重启」
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api, type ScriptInfo, type ScriptName } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

// 每脚本可调的启动参数（键与后端 SPECS 一一对应）
export const PARAM_FIELDS: Record<ScriptName, { key: string; label: string; desc: string }[]> = {
  fb: [{ key: 'memo23_daily_results', label: 'memo23 日额度', desc: 'memo23 actor 每日交付结果上限' }],
  x: [{ key: 'daily_results', label: '日结果上限', desc: '每日最多交付的搜索结果行数' }],
  wa: [{ key: 'min_batch', label: '最小批量', desc: '启动参数 --min-batch，每轮最少查号数量' }],
  li: [
    { key: 'target', label: 'WA 注册目标数', desc: 'us_contacts WA 已注册达此数自动退出（--target）' },
    { key: 'max_budget', label: '预算上限（美元）', desc: 'state 累计费用达此值自动退出（--max-budget，整数美元）' },
  ],
}

interface ScriptParamsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 目标脚本，null 时不渲染内容 */
  script: ScriptInfo | null
  onSaved: () => void
}

export function ScriptParamsDialog({ open, onOpenChange, script, onSaved }: ScriptParamsDialogProps) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState<'save' | 'restart' | null>(null)

  // 打开时回填当前参数
  useEffect(() => {
    if (!open || !script) return
    const init: Record<string, string> = {}
    for (const f of PARAM_FIELDS[script.name]) {
      init[f.key] = String(script.params[f.key] ?? '')
    }
    setValues(init)
  }, [open, script])

  if (!script) return null
  const fields = PARAM_FIELDS[script.name]

  // 校验并组装参数（正整数），非法返回 null
  const collectParams = (): Record<string, number> | null => {
    const params: Record<string, number> = {}
    for (const f of fields) {
      const raw = (values[f.key] ?? '').trim()
      if (!/^\d+$/.test(raw) || Number(raw) <= 0) {
        toast.error(`「${f.label}」必须是正整数`)
        return null
      }
      params[f.key] = Number(raw)
    }
    return params
  }

  const handleSave = async (andRestart: boolean) => {
    const params = collectParams()
    if (!params) return
    setSubmitting(andRestart ? 'restart' : 'save')
    try {
      await api.scriptSaveParams(script.name, params)
      if (andRestart) {
        await api.scriptRestart(script.name)
        toast.success(`「${script.title}」参数已保存并重启`)
      } else {
        toast.success(`「${script.title}」参数已保存，下次启动生效`)
      }
      onOpenChange(false)
      onSaved()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>参数配置 · {script.title}</DialogTitle>
          <DialogDescription>
            脚本只认启动参数：保存后需重启进程才会生效。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {fields.map((f) => (
            <div key={f.key} className="space-y-2">
              <Label htmlFor={`param-${f.key}`}>{f.label}</Label>
              <Input
                id={`param-${f.key}`}
                inputMode="numeric"
                value={values[f.key] ?? ''}
                onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
              />
              <p className="text-xs text-muted-foreground">{f.desc}</p>
            </div>
          ))}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting !== null}>
            取消
          </Button>
          <Button variant="outline" onClick={() => handleSave(false)} disabled={submitting !== null}>
            {submitting === 'save' ? '保存中…' : '保存'}
          </Button>
          {script.running && (
            <Button onClick={() => handleSave(true)} disabled={submitting !== null}>
              {submitting === 'restart' ? '重启中…' : '保存并重启'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
