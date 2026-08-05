// API 层封装：类型定义 + fetch 封装 + 通用数据加载 Hook
import { useCallback, useEffect, useRef, useState } from 'react'

const BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(message: string, status = 0) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiError('无法连接后端服务（http://127.0.0.1:8765）')
  }
  if (!res.ok) {
    // 优先透传后端 detail（如 422 无法识别命令的具体原因）
    let detail = ''
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* 非 JSON 错误体，忽略 */
    }
    throw new ApiError(detail || `请求失败：${res.status} ${res.statusText}`, res.status)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

// ---------- 类型定义（与后端契约一致） ----------

export interface Overview {
  ts: string
  shops: { pending: number; done: number; no_contact: number; failed: number; total: number }
  contacts: { total: number; with_mobile: number; wa_registered: number; wa_unregistered: number; wa_unchecked: number }
  tasks: { running: number; pending: number; done: number; failed: number }
}

export interface Pipeline {
  window: { start: string; end: string; bucket: 'hour' | 'day' }
  backlog: number
  totals: { collected: number; consumed: number }
  rates: { unit: string; collect: number; consume: number }
  buckets: { label: string; collected: number; consumed: number }[]
}

export type PipelinePeriod = '12h' | 'today' | 'yesterday' | '7d' | '30d' | 'custom'

export interface Task {
  id: number
  type: string
  status: string
  params: Record<string, unknown>
  progress: Record<string, unknown> | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type TaskType = '1688_shop' | '1688_company' | '1688_contact' | 'yiwugo_search' | 'wa_check'

// 采集类参数全量可选键：留空即不传，由 CLI 默认值生效。
// wa_check 使用 limit / accounts / sample_min / sample_max / batch_num /
// batch_rest_min / batch_rest_max（interval 为旧参数，向后兼容）。
export interface TaskParams {
  batch_num?: number
  limit?: number
  max_batches?: number
  workers?: number
  channels?: string
  batch_rest?: number
  sample_min?: number
  sample_max?: number
  rest_every?: number
  rest_min?: number
  rest_max?: number
  stagger_min?: number
  stagger_max?: number
  ip_retry?: number
  net_retry?: number
  max_consecutive_fail?: number
  block_rest_min?: number
  block_rest_max?: number
  use_proxy?: boolean
  headless?: boolean
  auto_solve?: boolean
  retry_failed?: boolean // 仅 1688_contact
  // 任务结束后自动重启的间隔（秒）；0 或不传 = 不循环
  repeat_interval?: number
  // wa_check 专用
  interval?: number // 旧参数：固定调用间隔（等价 sample_min == sample_max）
  accounts?: string[]
  batch_rest_min?: number // wa_check 批间休息下限（秒）
  batch_rest_max?: number // wa_check 批间休息上限（秒）
}

export interface CreateTaskRequest {
  type: TaskType
  params: TaskParams
}

export interface TaskPreview {
  cmd: string[] | null // wa_check 为进程内任务，返回 null
  cmdline: string // cmd 拼接的命令行，或 wa_check 的说明文案
}

// 命令解析结果：422 时 request() 抛出带后端 detail 的 ApiError
export interface TaskParseResult {
  type: TaskType
  params: TaskParams
  warnings: string[]
}

export interface TaskTemplate {
  id: number
  name: string
  type: TaskType
  params: TaskParams
  created_at: string
}

export interface CreateTaskTemplateRequest {
  name: string
  type: TaskType
  params: TaskParams
}

export interface TaskBatchResult {
  ok: number
  failed: number
  results: { id: number; ok: boolean; detail: string }[]
}

export interface StartTaskResult {
  ok: boolean
  pid: number
}

export type TaskEventLevel = 'info' | 'success' | 'warning' | 'error'

export interface TaskEvent {
  id: number
  ts: string
  level: TaskEventLevel
  message: string
  data?: { worker?: number | string } & Record<string, unknown> | null
}

export interface TaskStatusEvent {
  status: string
  finished_at: string | null
}

export interface ProviderChannel {
  id: number
  tunnel: string
  exit_ip: string | null
  status: string
  ip_expires_at: string | null
  last_probe_at: string | null
}

export interface Provider {
  id: number
  kind: string
  name: string
  enabled: number
  config: Record<string, unknown>
  channels: ProviderChannel[]
}

export interface CreateProviderRequest {
  kind: string
  name: string
  config: Record<string, unknown>
  enabled: boolean
}

export interface UpdateProviderRequest {
  name?: string
  config?: Record<string, unknown>
  enabled?: boolean
}

export interface ProbeChannelResult {
  tunnel: string
  ok: boolean
  exit_ip?: string
  error?: string
}

export interface ProbeResult {
  ok: number
  fail: number
  results: ProbeChannelResult[]
}

export type ProviderConfigSchema = Record<string, string>

export interface WaAccount {
  name: string
  auth_dir: string
  logged_in: boolean
  phone: string | null
}

export type WaLoginState = 'waiting_scan' | 'connected' | 'failed' | 'expired'

export interface WaAccountCreateResult {
  ok: boolean
  name: string
  state: WaLoginState
}

export interface WaLoginStatus {
  name: string
  state: WaLoginState
  qr_url: string | null
  qr_mtime: number | null
}

// ---------- 接口方法 ----------

// 后端 provider 原始结构（config_json / proxy_channels）归一化为前端
// 契约（config / channels），单点适配，页面层不感知字段名差异。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeProvider(p: any): Provider {
  return {
    ...p,
    config: p.config ?? p.config_json ?? {},
    channels: p.channels ?? p.proxy_channels ?? [],
  }
}

// 后端 task 原始结构（params_json / progress_json）归一化为前端契约
// （params / progress），单点适配。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeTask(t: any): Task {
  return {
    ...t,
    params: t.params ?? t.params_json ?? {},
    progress: t.progress ?? t.progress_json ?? null,
  }
}

export const api = {
  health: () => request<{ ok: boolean }>('/health'),
  overview: () => request<Overview>('/dashboard/overview'),
  pipeline: (period: PipelinePeriod = '12h', start?: string, end?: string) => {
    let qs: string
    if (period === '12h') qs = 'hours=12'
    else if (period === 'custom') qs = `period=custom&start=${encodeURIComponent(start ?? '')}&end=${encodeURIComponent(end ?? '')}`
    else qs = `period=${period}`
    return request<Pipeline>(`/dashboard/pipeline?${qs}`)
  },
  tasks: async () => (await request<unknown[]>('/tasks')).map(normalizeTask),
  createTask: async (body: CreateTaskRequest) =>
    normalizeTask(await request<unknown>('/tasks', { method: 'POST', body: JSON.stringify(body) })),
  previewTask: (body: CreateTaskRequest) =>
    request<TaskPreview>('/tasks/preview', { method: 'POST', body: JSON.stringify(body) }),
  parseCommand: (command: string) =>
    request<TaskParseResult>('/tasks/parse', {
      method: 'POST',
      body: JSON.stringify({ command }),
    }),
  putTask: async (id: number, params: TaskParams) =>
    normalizeTask(
      await request<unknown>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify({ params }) })),
  getTask: async (id: number) => normalizeTask(await request<unknown>(`/tasks/${id}`)),
  startTask: (id: number) => request<StartTaskResult>(`/tasks/${id}/start`, { method: 'POST' }),
  stopTask: (id: number) => request<{ ok: boolean }>(`/tasks/${id}/stop`, { method: 'POST' }),
  deleteTask: (id: number) => request<{ ok: boolean }>(`/tasks/${id}`, { method: 'DELETE' }),
  batchTasks: (action: 'start' | 'stop' | 'delete', ids: number[]) =>
    request<TaskBatchResult>('/tasks/batch', {
      method: 'POST',
      body: JSON.stringify({ action, ids }),
    }),
  // 任务模板：params 字段兼容后端 params_json 命名
  getTaskTemplates: async () =>
    ((await request<unknown[]>('/task-templates')) as (TaskTemplate & { params_json?: TaskParams })[]).map(
      (t) => ({ ...t, params: t.params ?? t.params_json ?? {} }),
    ),
  createTaskTemplate: (body: CreateTaskTemplateRequest) =>
    request<TaskTemplate>('/task-templates', { method: 'POST', body: JSON.stringify(body) }),
  deleteTaskTemplate: (id: number) =>
    request<{ ok: boolean }>(`/task-templates/${id}`, { method: 'DELETE' }),
  providers: async () => (await request<unknown[]>('/providers')).map(normalizeProvider),
  createProvider: async (body: CreateProviderRequest) =>
    normalizeProvider(
      await request<unknown>('/providers', { method: 'POST', body: JSON.stringify(body) })),
  updateProvider: async (id: number, body: UpdateProviderRequest) =>
    normalizeProvider(
      await request<unknown>(`/providers/${id}`, { method: 'PUT', body: JSON.stringify(body) })),
  probeProvider: (id: number) => request<ProbeResult>(`/providers/${id}/probe`, { method: 'POST' }),
  refreshProviderChannels: async (id: number) =>
    normalizeProvider(
      await request<unknown>(`/providers/${id}/channels/refresh`, { method: 'POST' })),
  providerConfigSchema: () => request<ProviderConfigSchema>('/providers/config-schema'),
  waAccounts: () => request<WaAccount[]>('/wa/accounts'),
  createWaAccount: (name: string) =>
    request<WaAccountCreateResult>('/wa/accounts', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  waAccountLogin: (name: string) =>
    request<WaLoginStatus>(`/wa/accounts/${encodeURIComponent(name)}/login`),
  deleteWaAccount: (name: string) =>
    request<{ ok: boolean }>(`/wa/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' }),
}

// ---------- 通用数据加载 Hook（加载态 / 错误态 / 自动刷新） ----------

export interface ApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

export function useApiData<T>(
  fetcher: () => Promise<T>,
  refreshMs = 0,
  deps: unknown[] = [],
): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const result = await fetcherRef.current()
      setData(result)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '未知错误')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    if (refreshMs > 0) {
      const timer = setInterval(() => load(true), refreshMs)
      return () => clearInterval(timer)
    }
  }, [load, refreshMs])

  // 依赖变化（如筛选条件切换）时立即重新加载
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(true) }, deps)

  return { data, loading, error, reload: () => load() }
}

// ---------- 展示辅助 ----------

export function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function formatDuration(start: string | null, end: string | null): string {
  if (!start) return '—'
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  if (Number.isNaN(s) || Number.isNaN(e) || e < s) return '—'
  const sec = Math.round((e - s) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
}
