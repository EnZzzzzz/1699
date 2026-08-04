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
    throw new ApiError(`请求失败：${res.status} ${res.statusText}`, res.status)
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
  contacts: { total: number; with_mobile: number }
  tasks: { running: number; pending: number; done: number; failed: number }
}

export interface Pipeline {
  window: { start: string; end: string; hours: number }
  backlog: number
  rates: { collect_per_hour: number; consume_per_hour: number }
  hourly: { label: string; collected: number; consumed: number }[]
}

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

export type TaskType = '1688_shop' | '1688_contact' | 'yiwugo_search'

export interface TaskParams {
  batch_num: number
  max_batches: number
  limit: number
  use_proxy: boolean
  headless: boolean
}

export interface CreateTaskRequest {
  type: TaskType
  params: TaskParams
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

export const api = {
  health: () => request<{ ok: boolean }>('/health'),
  overview: () => request<Overview>('/dashboard/overview'),
  pipeline: (hours = 12) => request<Pipeline>(`/dashboard/pipeline?hours=${hours}`),
  tasks: () => request<Task[]>('/tasks'),
  createTask: (body: CreateTaskRequest) =>
    request<Task>('/tasks', { method: 'POST', body: JSON.stringify(body) }),
  getTask: (id: number) => request<Task>(`/tasks/${id}`),
  startTask: (id: number) => request<StartTaskResult>(`/tasks/${id}/start`, { method: 'POST' }),
  stopTask: (id: number) => request<{ ok: boolean }>(`/tasks/${id}/stop`, { method: 'POST' }),
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

export function useApiData<T>(fetcher: () => Promise<T>, refreshMs = 0): ApiState<T> {
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
