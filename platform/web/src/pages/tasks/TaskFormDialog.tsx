// 任务表单对话框：新建 / 编辑双模式（task 为空 = 新建，否则编辑其 params）
// 数字输入留空 = 不传该参数（CLI 默认值生效）；底部实时预览将执行的命令（防抖 500ms）
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  api, ApiError, type Task, type TaskParams, type TaskPreview, type TaskTemplate, type TaskType,
  type WaAccount,
} from '@/lib/api'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { ChevronDown, Save, Terminal, Trash2 } from 'lucide-react'
import { TASK_TYPE_OPTIONS, taskTypeLabel } from './task-ui'

interface NumField {
  key: string
  label: string
  placeholder: string
  hint?: string
}

// 基础区常用数字参数
const BASIC_FIELDS: NumField[] = [
  { key: 'batch_num', label: '每批数量', placeholder: '默认 10' },
  { key: 'limit', label: '采集上限', placeholder: '0 = 不限', hint: '0 = 不限' },
  { key: 'max_batches', label: '最大批数', placeholder: '0 = 不限', hint: '0 = 不限' },
  { key: 'workers', label: '并发数', placeholder: '留空 = 默认' },
]

// 高级参数：节奏
const RHYTHM_FIELDS: NumField[] = [
  { key: 'batch_rest', label: '批间休息（秒）', placeholder: '默认 900' },
  { key: 'sample_min', label: '取样下限', placeholder: '默认 13' },
  { key: 'sample_max', label: '取样上限', placeholder: '默认 20' },
  { key: 'rest_every', label: '每隔 N 次休息', placeholder: '留空 = 默认' },
  { key: 'rest_min', label: '休息下限（秒）', placeholder: '默认 60' },
  { key: 'rest_max', label: '休息上限（秒）', placeholder: '默认 180' },
  { key: 'stagger_min', label: '错开下限（秒）', placeholder: '默认 15' },
  { key: 'stagger_max', label: '错开上限（秒）', placeholder: '默认 60' },
]

// 高级参数：重试与风控
const RETRY_FIELDS: NumField[] = [
  { key: 'ip_retry', label: 'IP 重试次数', placeholder: '默认 3' },
  { key: 'net_retry', label: '网络重试次数', placeholder: '默认 5' },
  { key: 'max_consecutive_fail', label: '最大连续失败', placeholder: '默认 5' },
  { key: 'block_rest_min', label: '封禁休息下限（秒）', placeholder: '默认 600' },
  { key: 'block_rest_max', label: '封禁休息上限（秒）', placeholder: '默认 900' },
]

// 高级参数：其他（数字类）
const MISC_NUM_FIELDS: NumField[] = [
  { key: 'repeat_interval', label: '循环间隔（秒）', placeholder: '0 = 不循环，如 1800' },
]

const ALL_NUM_KEYS = [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map(
  (f) => f.key,
)

// 高级区包含的数字键（模板加载命中时自动展开高级区）
const ADVANCED_NUM_KEYS = [...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map((f) => f.key)

// fb_discover 新建时预填的默认关键词矩阵（SPEC §7.4）
const FB_DISCOVER_DEFAULT_KEYWORDS = `site:facebook.com/groups 外贸 whatsapp
site:facebook.com/groups 跨境电商 whatsapp
site:facebook.com/groups china sourcing whatsapp
site:facebook.com/groups 货代 微信
site:facebook.com/groups 亚马逊卖家 微信`

interface TaskFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
  task?: Task | null // 传入 = 编辑模式（type 只读，回填 params）
}

export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDialogProps) {
  const editing = task != null

  const [type, setType] = useState<TaskType>('1688_shop')
  const [values, setValues] = useState<Record<string, string>>({})
  const [channels, setChannels] = useState('')
  const [useProxy, setUseProxy] = useState(true)
  const [headless, setHeadless] = useState(true)
  const [autoSolve, setAutoSolve] = useState(true)
  const [retryFailed, setRetryFailed] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // wa_check 专用表单状态
  const [waLimit, setWaLimit] = useState('')
  const [waAccounts, setWaAccounts] = useState<WaAccount[]>([])
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])

  // P4 批次采集专用：limit（contact=条数、shop/company=页数）
  const [batchLimit, setBatchLimit] = useState('')

  // P4 fb_discover 专用
  const [fbDiscoverKeywords, setFbDiscoverKeywords] = useState('')
  const [fbDiscoverPages, setFbDiscoverPages] = useState('')
  // P4 fb_group 专用
  const [fbGroupProvider, setFbGroupProvider] = useState<'brightdata' | 'apify'>('brightdata')
  const [fbGroupPostsPerGroup, setFbGroupPostsPerGroup] = useState('')

  // 命令预览
  const [preview, setPreview] = useState<TaskPreview | null>(null)

  // 任务模板
  const [templates, setTemplates] = useState<TaskTemplate[]>([])
  const [templateSel, setTemplateSel] = useState('')
  const [saveTplOpen, setSaveTplOpen] = useState(false)
  const [tplName, setTplName] = useState('')
  const [savingTpl, setSavingTpl] = useState(false)
  const [tplToDelete, setTplToDelete] = useState<TaskTemplate | null>(null)
  const [deletingTpl, setDeletingTpl] = useState(false)
  const [tplManageOpen, setTplManageOpen] = useState(false)

  const isWaCheck = type === 'wa_check'
  // P4 批次采集类型：表单只留 limit + repeat_interval（节奏/代理收敛 daemon 级）
  const isBatch = ['1688_shop', '1688_company', '1688_contact',
                   'madeinchina_shop', 'madeinchina_contact',
                   'fb_post'].includes(type)
  const isFbDiscover = type === 'fb_discover'
  const isFbGroup = type === 'fb_group'

  const setValue = (key: string, v: string) =>
    setValues((prev) => ({ ...prev, [key]: v }))

  // 用一组 params 回填整个表单（编辑初始化 / 模板加载共用）
  const fillFromParams = (p: Record<string, unknown>) => {
    const next: Record<string, string> = {}
    for (const key of ALL_NUM_KEYS) {
      if (typeof p[key] === 'number') next[key] = String(p[key])
    }
    setValues(next)
    setChannels(typeof p.channels === 'number' ? String(p.channels) : '')
    setUseProxy(p.use_proxy !== false)
    setHeadless(p.headless !== false)
    setAutoSolve(p.auto_solve !== false)
    setRetryFailed(p.retry_failed === true)
    setWaLimit(typeof p.limit === 'number' ? String(p.limit) : '')
    setBatchLimit(typeof p.limit === 'number' ? String(p.limit) : '')
    // wa 表单只保留 limit + accounts：历史任务 params_json 中的旧字段
    // （batch_num/sample_min/… 等）后端忽略，回填时跳过未知键（SPEC C3）
    setSelectedAccounts(
      Array.isArray(p.accounts)
        ? (p.accounts as unknown[]).filter((a): a is string => typeof a === 'string')
        : [],
    )
    if (ADVANCED_NUM_KEYS.some((k) => typeof p[k] === 'number')) setAdvancedOpen(true)
    // fb_discover / fb_group 回填
    setFbDiscoverKeywords(typeof p.keywords === 'string' ? p.keywords : '')
    setFbDiscoverPages(typeof p.pages === 'number' ? String(p.pages) : '')
    setFbGroupProvider(p.provider === 'apify' ? 'apify' : 'brightdata')
    setFbGroupPostsPerGroup(typeof p.posts_per_group === 'number' ? String(p.posts_per_group) : '')
  }

  // 打开时初始化：编辑模式回填 task.params，新建模式重置为空白默认
  useEffect(() => {
    if (!open) return
    setPreview(null)
    setAdvancedOpen(false)
    setTemplateSel('')
    if (task) {
      setType(task.type as TaskType)
      fillFromParams((task.params ?? {}) as Record<string, unknown>)
      setAdvancedOpen(false) // 编辑初始化不强制展开高级区
    } else {
      setType('1688_shop')
      setValues({})
      setChannels('')
      setUseProxy(true)
      setHeadless(true)
      setAutoSolve(true)
      setRetryFailed(false)
      setWaLimit('')
      setSelectedAccounts([])
      setFbDiscoverKeywords(FB_DISCOVER_DEFAULT_KEYWORDS)
      setFbDiscoverPages('1')
      setFbGroupProvider('brightdata')
      setFbGroupPostsPerGroup('50')
      setBatchLimit('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, task])

  // 打开时拉取模板列表
  useEffect(() => {
    if (!open) return
    api.getTaskTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]))
  }, [open])

  // 拉取 WhatsApp 账号列表（仅 logged_in 可选）
  useEffect(() => {
    if (!open) return
    api.waAccounts()
      .then((accs) => setWaAccounts(accs.filter((a) => a.logged_in)))
      .catch(() => setWaAccounts([]))
  }, [open])

  const toggleAccount = (name: string, checked: boolean) => {
    setSelectedAccounts((prev) =>
      checked ? [...prev, name] : prev.filter((n) => n !== name))
  }

  // 由当前表单构造 params（宽松模式：无法解析的数字直接跳过，供预览使用）
  const buildParams = (): TaskParams => {
    if (isBatch) {
      // P4 批次采集：只提交 limit + repeat_interval（其余 daemon 级收敛）
      const params: TaskParams = {}
      const limitN = Number(batchLimit)
      if (batchLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) {
        params.limit = limitN
      }
      const riRaw = (values.repeat_interval ?? '').trim()
      const riN = Number(riRaw)
      if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
      return params
    }
    if (isWaCheck) {
      const params: TaskParams = { accounts: selectedAccounts }
      const limitN = Number(waLimit)
      if (waLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) params.limit = limitN
      // 循环间隔：由模板回填时透传（wa 表单不展示该字段）
      const riRaw = (values.repeat_interval ?? '').trim()
      const riN = Number(riRaw)
      if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
      return params
    }
    if (isFbDiscover) {
      const params: TaskParams = {}
      const kw = fbDiscoverKeywords.trim()
      if (kw !== '') params.keywords = kw
      const pagesN = Number(fbDiscoverPages)
      if (fbDiscoverPages.trim() !== '' && Number.isInteger(pagesN) && pagesN >= 1 && pagesN <= 10) {
        params.pages = pagesN
      }
      const riRaw = (values.repeat_interval ?? '').trim()
      const riN = Number(riRaw)
      if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
      return params
    }
    if (isFbGroup) {
      const params: TaskParams = { provider: fbGroupProvider }
      const ppgN = Number(fbGroupPostsPerGroup)
      if (fbGroupPostsPerGroup.trim() !== '' && Number.isInteger(ppgN) && ppgN >= 1) {
        params.posts_per_group = ppgN
      }
      const limitN = Number(batchLimit)
      if (batchLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) {
        params.limit = limitN
      }
      const riRaw = (values.repeat_interval ?? '').trim()
      const riN = Number(riRaw)
      if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
      return params
    }
    const params: TaskParams = { use_proxy: useProxy, headless, auto_solve: autoSolve }
    for (const key of ALL_NUM_KEYS) {
      const raw = (values[key] ?? '').trim()
      if (raw === '') continue
      const n = Number(raw)
      if (!Number.isInteger(n) || n < 0) continue
      if (key === 'repeat_interval' && n === 0) continue // 0 = 不循环，不传
      ;(params as Record<string, unknown>)[key] = n
    }
    // 后端 channels 为 int（代理通道 id）：整数才提交（Number.isFinite 会放行 '1.5'，后端 int 会 422）
    const channelsRaw = channels.trim()
    if (channelsRaw !== '') {
      const channelsN = Number(channelsRaw)
      if (Number.isInteger(channelsN)) params.channels = channelsN
    }
    if (retryFailed && type === '1688_contact') params.retry_failed = true
    return params
  }

  // 参数签名：内容变化时触发防抖预览
  const paramsKey = useMemo(
    () =>
      JSON.stringify({
        type, values, channels, useProxy, headless, autoSolve, retryFailed,
        waLimit, selectedAccounts,
        fbDiscoverKeywords, fbDiscoverPages, fbGroupProvider, fbGroupPostsPerGroup,
      }),
    [type, values, channels, useProxy, headless, autoSolve, retryFailed,
      waLimit, selectedAccounts,
      fbDiscoverKeywords, fbDiscoverPages, fbGroupProvider, fbGroupPostsPerGroup],
  )

  // 命令预览：防抖 500ms 调 preview 接口，失败静默不阻塞
  useEffect(() => {
    if (!open) return
    const timer = setTimeout(() => {
      api.previewTask({ type, params: buildParams() })
        .then((res) => setPreview(res))
        .catch(() => setPreview(null))
    }, 500)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, paramsKey])

  // 严格校验（提交时）：已填写的数字必须是合法的非负整数
  const validate = (): boolean => {
    if (isBatch) {
      if (batchLimit.trim() !== '') {
        const n = Number(batchLimit)
        if (!Number.isInteger(n) || n < 0) {
          toast.error('采集上限需为不小于 0 的整数（0 = 不限）')
          return false
        }
      }
      return true
    }
    if (isWaCheck) {
      if (waLimit.trim() !== '') {
        const n = Number(waLimit)
        if (!Number.isInteger(n) || n < 0) {
          toast.error('查号上限需为不小于 0 的整数（0 = 全部未查）')
          return false
        }
      }
      return true
    }
    if (isFbDiscover) {
      // keywords 空 → 警告但不阻塞（后端 enqueue 空→0 幂等，裁定#5）
      if (fbDiscoverKeywords.trim() === '') {
        toast.warning('未填写查询词，将使用空关键词（后端幂等跳过）')
      }
      if (fbDiscoverPages.trim() !== '') {
        const n = Number(fbDiscoverPages)
        if (!Number.isInteger(n) || n < 1 || n > 10) {
          toast.error('每词页数需为 1-10 的整数')
          return false
        }
      }
      return true
    }
    if (isFbGroup) {
      // provider 防御校验：Select 已限定，代码级再兜底（裁定#5）
      const provider = fbGroupProvider as string
      if (provider !== 'brightdata' && provider !== 'apify') {
        toast.error('数据来源仅支持 Bright Data 或 Apify')
        return false
      }
      if (fbGroupPostsPerGroup.trim() !== '') {
        const n = Number(fbGroupPostsPerGroup)
        if (!Number.isInteger(n) || n < 1) {
          toast.error('每群帖数上限需为不小于 1 的整数')
          return false
        }
      }
      if (batchLimit.trim() !== '') {
        const n = Number(batchLimit)
        if (!Number.isInteger(n) || n < 0) {
          toast.error('群数上限需为不小于 0 的整数（0 = 不限）')
          return false
        }
      }
      return true
    }
    for (const f of [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS]) {
      const raw = (values[f.key] ?? '').trim()
      if (raw === '') continue
      const n = Number(raw)
      if (!Number.isInteger(n) || n < 0) {
        toast.error(`「${f.label}」需为不小于 0 的整数，或留空使用默认值`)
        return false
      }
    }
    const batchNum = Number(values.batch_num)
    if ((values.batch_num ?? '').trim() !== '' && batchNum < 1) {
      toast.error('每批数量需为不小于 1 的整数')
      return false
    }
    return true
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setSubmitting(true)
    try {
      const params = buildParams()
      if (editing) {
        const saved = await api.putTask(task.id, params)
        toast.success(`任务 #${saved.id} 参数已保存`)
      } else {
        const created = await api.createTask({ type, params })
        toast.success(`任务 #${created.id} 创建成功`)
      }
      onOpenChange(false)
      onSaved()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.warning('任务状态已变化，当前状态不允许修改参数')
        onSaved() // 刷新列表反映最新状态
      } else {
        toast.error(e instanceof Error ? e.message : editing ? '保存参数失败' : '创建任务失败')
      }
    } finally {
      setSubmitting(false)
    }
  }

  // 编辑模式类型只读：模板类型与当前任务不同时忽略 type，仅回填参数
  const applyImportedType = (incoming: TaskType): boolean => {
    if (!editing) {
      setType(incoming)
      return true
    }
    if (incoming !== task.type) {
      toast.info(
        `类型不可修改，已忽略「${taskTypeLabel(incoming)}」，仅回填参数`,
      )
      return false
    }
    return true
  }

  // 从模板加载：选中即回填
  const handleLoadTemplate = (idStr: string) => {
    setTemplateSel('') // 加载动作而非选中态，复位占位
    const tpl = templates.find((t) => String(t.id) === idStr)
    if (!tpl) return
    applyImportedType(tpl.type)
    fillFromParams((tpl.params ?? {}) as Record<string, unknown>)
    toast.success(`已加载模板「${tpl.name}」`)
  }

  const handleDeleteTemplate = async () => {
    if (!tplToDelete) return
    setDeletingTpl(true)
    try {
      await api.deleteTaskTemplate(tplToDelete.id)
      setTemplates((prev) => prev.filter((t) => t.id !== tplToDelete.id))
      toast.success(`模板「${tplToDelete.name}」已删除`)
      setTplToDelete(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '删除模板失败')
    } finally {
      setDeletingTpl(false)
    }
  }

  const handleSaveTemplate = async () => {
    const name = tplName.trim()
    if (name === '') {
      toast.warning('请输入模板名称')
      return
    }
    setSavingTpl(true)
    try {
      const created = await api.createTaskTemplate({
        name,
        type: editing ? (task.type as TaskType) : type,
        params: buildParams(),
      })
      setTemplates((prev) => [...prev, created])
      toast.success(`模板「${created.name}」已保存`)
      setSaveTplOpen(false)
      setTplName('')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存模板失败')
    } finally {
      setSavingTpl(false)
    }
  }

  const renderNumField = (f: NumField) => (
    <div key={f.key} className="space-y-1.5">
      <Label htmlFor={`tf-${f.key}`} className="text-xs">{f.label}</Label>
      <Input
        id={`tf-${f.key}`}
        type="number"
        min={0}
        value={values[f.key] ?? ''}
        placeholder={f.placeholder}
        onChange={(e) => setValue(f.key, e.target.value)}
      />
      {f.hint && <p className="text-xs text-muted-foreground">{f.hint}</p>}
    </div>
  )

  const renderGroup = (title: string, fields: NumField[]) => (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {fields.map(renderNumField)}
      </div>
    </div>
  )

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{editing ? `编辑任务 #${task.id} 参数` : '新建任务'}</DialogTitle>
          <DialogDescription>
            {editing
              ? '任务类型不可修改；留空的参数将使用 CLI 默认值。'
              : '选择任务类型并配置参数，留空即使用 CLI 默认值，创建后进入排队。'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 从模板加载 */}
          <div className="space-y-2">
            <Label>从模板加载</Label>
            <div className="flex gap-2">
              <Select value={templateSel} onValueChange={handleLoadTemplate}>
                <SelectTrigger className="flex-1">
                  <SelectValue
                    placeholder={templates.length > 0 ? '选择模板，立即回填表单' : '暂无已保存模板'}
                  />
                </SelectTrigger>
                <SelectContent>
                  {templates.map((t) => (
                    <SelectItem key={t.id} value={String(t.id)}>
                      {t.name}
                      <span className="ml-1.5 text-xs text-muted-foreground">
                        {taskTypeLabel(t.type)}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="sm"
                className="shrink-0"
                disabled={templates.length === 0}
                onClick={() => setTplManageOpen(true)}
              >
                管理
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            <Label>任务类型</Label>
            <Select
              value={type}
              onValueChange={(v) => setType(v as TaskType)}
              disabled={editing}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择任务类型" />
              </SelectTrigger>
              <SelectContent>
                {TASK_TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isBatch ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="batch-limit">采集上限</Label>
                <Input
                  id="batch-limit"
                  type="number"
                  min={0}
                  value={batchLimit}
                  placeholder="0 = 不限"
                  onChange={(e) => setBatchLimit(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  {type === '1688_contact' || type === 'madeinchina_contact'
                    ? '联系方式采集：条数上限（0 = 不限）'
                    : type === 'fb_post'
                      ? '帖子采集：条数上限（0 = 不限）'
                      : '店铺/公司采集：页数上限（0 = 不限）'}
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="batch-repeat">循环间隔（秒）</Label>
                <Input
                  id="batch-repeat"
                  type="number"
                  min={0}
                  value={values.repeat_interval ?? ''}
                  placeholder="0 = 不循环"
                  onChange={(e) => setValue('repeat_interval', e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  批次跑完后 N 秒自动重启同参数批次（0 = 不循环）
                </p>
              </div>
              <p className="text-xs text-muted-foreground">
                节奏/代理/并发/有头模式已收敛到 daemon 启动参数（当前全局有头运行），不再逐任务下发。
              </p>
            </>
          ) : isWaCheck ? (
            <>
              <div className="max-w-xs space-y-2">
                <Label htmlFor="wa-limit">查号上限</Label>
                <Input
                  id="wa-limit"
                  type="number"
                  min={0}
                  value={waLimit}
                  placeholder="0 = 全部未查"
                  onChange={(e) => setWaLimit(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">0 = 全部未查</p>
              </div>

              <div className="space-y-2 rounded-md border border-border px-3 py-2">
                <Label>查号账号</Label>
                {waAccounts.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    暂无已登录账号，将使用默认账号
                  </p>
                ) : (
                  <div className="space-y-2">
                    {waAccounts.map((a) => (
                      <div key={a.name} className="flex items-center gap-2">
                        <Checkbox
                          id={`wa-acc-${a.name}`}
                          checked={selectedAccounts.includes(a.name)}
                          onCheckedChange={(c) => toggleAccount(a.name, c === true)}
                        />
                        <Label htmlFor={`wa-acc-${a.name}`} className="cursor-pointer font-normal">
                          {a.name}
                          {a.phone ? `（+${a.phone}）` : ''}
                        </Label>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-xs text-muted-foreground">全不选 = 仅默认账号；多选按批轮换</p>
              </div>
            </>
          ) : isFbDiscover ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="fb-discover-kw">搜索关键词</Label>
                <Textarea
                  id="fb-discover-kw"
                  className="min-h-24 font-mono text-xs"
                  value={fbDiscoverKeywords}
                  placeholder="每行一个查询词"
                  onChange={(e) => setFbDiscoverKeywords(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  DDG SERP 单 IP 限流（实测约 2 连查即封、约 4 分钟恢复），查询间有节奏冷却，整批约 8-15 分钟跑完
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="fb-discover-pages">每词页数</Label>
                  <Input
                    id="fb-discover-pages"
                    type="number"
                    min={1}
                    max={10}
                    value={fbDiscoverPages}
                    placeholder="1"
                    onChange={(e) => setFbDiscoverPages(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="fb-discover-repeat">循环间隔（秒）</Label>
                  <Input
                    id="fb-discover-repeat"
                    type="number"
                    min={0}
                    value={values.repeat_interval ?? ''}
                    placeholder="0 = 不循环"
                    onChange={(e) => setValue('repeat_interval', e.target.value)}
                  />
                </div>
              </div>
            </>
          ) : isFbGroup ? (
            <>
              <div className="space-y-2">
                <Label>数据来源</Label>
                <Select value={fbGroupProvider} onValueChange={(v) => setFbGroupProvider(v as 'brightdata' | 'apify')}>
                  <SelectTrigger className="h-8 font-medium">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="brightdata">Bright Data（默认）</SelectItem>
                    <SelectItem value="apify">Apify</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="fb-group-ppg">每群帖数上限</Label>
                  <Input
                    id="fb-group-ppg"
                    type="number"
                    min={1}
                    value={fbGroupPostsPerGroup}
                    placeholder="50"
                    onChange={(e) => setFbGroupPostsPerGroup(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="fb-group-limit">群数上限</Label>
                  <Input
                    id="fb-group-limit"
                    type="number"
                    min={0}
                    value={batchLimit}
                    placeholder="留空 = 不限"
                    onChange={(e) => setBatchLimit(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="fb-group-repeat">循环间隔（秒）</Label>
                <Input
                  id="fb-group-repeat"
                  type="number"
                  min={0}
                  value={values.repeat_interval ?? ''}
                  placeholder="0 = 不循环"
                  onChange={(e) => setValue('repeat_interval', e.target.value)}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Bright Data 免费层 5K 条/月额度；provider key 走环境变量 BRIGHTDATA_API_KEY / APIFY_TOKEN（缺失时该群采集失败）
              </p>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {BASIC_FIELDS.map(renderNumField)}
              </div>

              <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                <div>
                  <Label htmlFor="use-proxy" className="cursor-pointer">使用代理</Label>
                  <p className="text-xs text-muted-foreground">通过代理通道发起请求</p>
                </div>
                <Switch id="use-proxy" checked={useProxy} onCheckedChange={setUseProxy} />
              </div>

              <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                <div>
                  <Label htmlFor="headless" className="cursor-pointer">无头浏览器</Label>
                  <p className="text-xs text-muted-foreground">后台运行，不弹出浏览器窗口</p>
                </div>
                <Switch id="headless" checked={headless} onCheckedChange={setHeadless} />
              </div>

              <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
                <CollapsibleTrigger asChild>
                  <Button variant="outline" size="sm" className="w-full justify-between">
                    高级参数
                    <ChevronDown
                      className={`h-4 w-4 transition-transform ${advancedOpen ? 'rotate-180' : ''}`}
                    />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="space-y-4 pt-3">
                  {renderGroup('节奏', RHYTHM_FIELDS)}
                  {renderGroup('重试与风控', RETRY_FIELDS)}

                  <div className="space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">其他</p>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                      {MISC_NUM_FIELDS.map(renderNumField)}
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="tf-channels" className="text-xs">代理通道</Label>
                      <Input
                        id="tf-channels"
                        value={channels}
                        placeholder="留空 = 全部通道"
                        onChange={(e) => setChannels(e.target.value)}
                      />
                    </div>
                    <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                      <div>
                        <Label htmlFor="auto-solve" className="cursor-pointer">自动过验证码</Label>
                        <p className="text-xs text-muted-foreground">遇到滑块时自动尝试求解</p>
                      </div>
                      <Switch id="auto-solve" checked={autoSolve} onCheckedChange={setAutoSolve} />
                    </div>
                    {type === '1688_contact' && (
                      <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                        <div>
                          <Label htmlFor="retry-failed" className="cursor-pointer">重试失败记录</Label>
                          <p className="text-xs text-muted-foreground">重新采集此前失败的店铺</p>
                        </div>
                        <Switch
                          id="retry-failed"
                          checked={retryFailed}
                          onCheckedChange={setRetryFailed}
                        />
                      </div>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </>
          )}

          {/* 命令预览：批次类型（含 wa_check）返回 cmd=null + 批次文案 */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <Terminal className="h-3.5 w-3.5" />
              命令预览
            </div>
            <div className="min-h-12 rounded-md border border-border bg-muted/50 px-3 py-2">
              {preview ? (
                <code className="block whitespace-pre-wrap break-all font-mono text-xs text-foreground">
                  {preview.cmdline}
                </code>
              ) : (
                <span className="text-xs text-muted-foreground">预览不可用</span>
              )}
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <Button
            variant="outline"
            onClick={() => { setTplName(''); setSaveTplOpen(true) }}
            disabled={submitting}
          >
            <Save className="mr-1.5 h-3.5 w-3.5" />
            保存为模板
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              取消
            </Button>
            <Button onClick={handleSubmit} disabled={submitting}>
              {submitting
                ? editing ? '保存中…' : '创建中…'
                : editing ? '保存参数' : '创建任务'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* 保存为模板：输入模板名 */}
    <Dialog open={saveTplOpen} onOpenChange={setSaveTplOpen}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>保存为模板</DialogTitle>
          <DialogDescription>
            将当前类型与参数保存为模板，之后可在表单顶部一键回填。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="tpl-name">模板名称</Label>
          <Input
            id="tpl-name"
            value={tplName}
            placeholder="如：公司采集 · 50/批 · 半小时循环"
            onChange={(e) => setTplName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSaveTemplate() }}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setSaveTplOpen(false)} disabled={savingTpl}>
            取消
          </Button>
          <Button onClick={handleSaveTemplate} disabled={savingTpl}>
            {savingTpl ? '保存中…' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* 模板管理 */}
    <Dialog open={tplManageOpen} onOpenChange={setTplManageOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>模板管理</DialogTitle>
          <DialogDescription>已保存的任务模板，可在此删除。</DialogDescription>
        </DialogHeader>
        <div className="max-h-72 space-y-2 overflow-y-auto">
          {templates.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">暂无模板</p>
          ) : (
            templates.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2"
              >
                <div>
                  <div className="text-sm font-medium">{t.name}</div>
                  <div className="text-xs text-muted-foreground">{taskTypeLabel(t.type)}</div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setTplToDelete(t)}
                >
                  <Trash2 className="mr-1 h-3.5 w-3.5" />
                  删除
                </Button>
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>

    {/* 删除模板确认 */}
    <AlertDialog open={tplToDelete != null} onOpenChange={(o) => { if (!o) setTplToDelete(null) }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>删除模板</AlertDialogTitle>
          <AlertDialogDescription>
            确认删除模板「{tplToDelete?.name}」？此操作不可恢复。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={deletingTpl}>取消</AlertDialogCancel>
          <AlertDialogAction onClick={handleDeleteTemplate} disabled={deletingTpl}>
            {deletingTpl ? '删除中…' : '删除'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  )
}
