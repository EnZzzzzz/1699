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

async function request<T>(path: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { headers: { Accept: 'application/json' } })
  } catch {
    throw new ApiError('无法连接后端服务（http://127.0.0.1:8765）')
  }
  if (!res.ok) {
    throw new ApiError(`请求失败：${res.status} ${res.statusText}`, res.status)
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
  channels: ProviderChannel[]
}

export interface WaAccount {
  name: string
  auth_dir: string
  logged_in: boolean
  phone: string | null
}

// ---------- 接口方法 ----------

export const api = {
  health: () => request<{ ok: boolean }>('/health'),
  overview: () => request<Overview>('/dashboard/overview'),
  pipeline: (hours = 12) => request<Pipeline>(`/dashboard/pipeline?hours=${hours}`),
  tasks: () => request<Task[]>('/tasks'),
  providers: () => request<Provider[]>('/providers'),
  waAccounts: () => request<WaAccount[]>('/wa/accounts'),
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
