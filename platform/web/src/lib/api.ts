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
}

export interface Pipeline {
  window: { start: string; end: string; bucket: 'hour' | 'day' }
  backlog: number
  totals: { collected: number; consumed: number }
  rates: { unit: string; collect: number; consume: number }
  buckets: { label: string; collected: number; consumed: number }[]
}

// FB/X 采号管道（fb_contacts）：first_seen_at 采集量分 FB/X，wa_checked_at 查号分注册/未注册；snapshot 为全表口径总数
export interface FbPipeline {
  window: { start: string; end: string; bucket: 'hour' | 'day' }
  totals: { fb: number; x: number; wa_registered: number; wa_unregistered: number; fb_wa_registered: number; fb_wa_unregistered: number; x_wa_registered: number; x_wa_unregistered: number; fb_pending: number; x_pending: number }
  snapshot: { fb_total: number; x_total: number; fb_registered: number; x_registered: number; pending: number; fb_pending: number; x_pending: number; reg_rate: number | null }
  rates: { unit: string; fb: number; x: number; wa_check: number }
  // 窗口成本估算（USD）：FB/X 采集 + WA 校验；cost_records 缺失时为 null
  costs: { fb: number; x: number; wa: number; total: number; per_registered: number | null; fb_per: number | null; x_per: number | null; wa_per: number | null; currency: string } | null
  buckets: { label: string; fb: number; x: number; wa_registered: number; wa_unregistered: number }[]
}

export type PipelinePeriod = '1h' | '3h' | '12h' | 'today' | 'yesterday' | '7d' | '30d' | 'custom'

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
  billing?: ProviderBilling | null
}

// 供应商费用侧信息（来自 cost_records real 行）：brightdata=可用余额快照
// （consumed 为本账期消耗，两者均按 config.billing_offset 校准为官方后台口径），
// apify=本账期已用（limit 为套餐月度硬上限，无快照时退化为本月已用）
export interface ProviderBilling {
  label: string
  usd: number
  as_of: string | null
  limit?: number | null
  consumed?: number | null
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

// /providers/config-schema 响应中的 provider_config_structure 部分
export type ProviderConfigSchema = Record<string, string>

// /providers/config-schema 完整响应（kind + 结构模板；qingguo 另附隧道缓存字段）
export interface ProviderConfigSchemaResponse {
  kind: string
  provider_config_structure: ProviderConfigSchema
  tunnel_cache_path?: string
  tunnel_cache_exists?: boolean
  tunnel_cache_structure?: Record<string, unknown> | null
}

// ---------- 采集脚本管理（/scripts） ----------

export type ScriptName = 'fb' | 'x' | 'wa'

// 各脚本额度/产量统计（键按脚本类型出现，缺数据为 null，前端展示 —）
export interface ScriptStats {
  memo23_used?: number | null
  memo23_limit?: number | null
  serp_queries?: number | null
  x_used?: number | null
  x_limit?: number | null
  total_results?: number | null
  total_cap?: number | null
  collected_today?: number | null
  checked_today?: number | null
  backlog?: number | null
}

export interface ScriptInfo {
  name: ScriptName
  title: string
  log_file: string
  running: boolean
  pid: number | null
  started_at: string | null
  uptime: string | null
  params: Record<string, number>
  stats: ScriptStats
}

// 日志增量 tail 响应：content 为新增内容，offset 为下次续传位置
export interface ScriptLogChunk {
  content: string
  offset: number
  missing?: boolean
}

// 选词面板：单个关键词（retired=脚本已自动退役，选了也会被跳过）
export interface ScriptKeyword {
  word: string
  retired: boolean
}

// GET /scripts/{name}/keywords 响应：默认词库全量 + 当前选词状态
export interface ScriptKeywordsResp {
  keywords: ScriptKeyword[]
  selection_active: boolean
  selected_count: number | null
}

// 启动选项：params 先落配置；keywords 选词子集（fb/x）；clearKeywords 回默认词库
export interface ScriptStartOptions {
  params?: Record<string, number>
  keywords?: string[]
  clearKeywords?: boolean
}

// ---------- 词库产量（/keywords） ----------

export type KeywordPlatformFilter = 'all' | 'x' | 'fb'
export type KeywordStatusFilter = 'all' | 'active' | 'x_retired' | 'fb_retired' | 'retired'
export type KeywordSort = 'total_new' | 'last_new' | 'q'
  | 'x_new' | 'x_last_new' | 'x_q'
  | 'fb_new' | 'fb_last_new' | 'fb_q'

// 单平台统计；该平台没查过则整个子对象为 null；last_new 历史词缺失为 null
export interface KeywordPlatformStat {
  q: number
  new: number
  last_new: number | null
  last_q_at: string | null
  retired: boolean
}

export interface KeywordItem {
  kw: string
  x: KeywordPlatformStat | null
  fb: KeywordPlatformStat | null
}

export interface KeywordsPage {
  items: KeywordItem[]
  total: number
  page: number
  page_size: number
}

export interface KeywordsQuery {
  q?: string
  platform?: KeywordPlatformFilter
  status?: KeywordStatusFilter
  sort?: KeywordSort
  order?: 'asc' | 'desc'
  page?: number
  page_size?: number
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
  pipeline: (period: PipelinePeriod = '12h', start?: string, end?: string) => {
    let qs: string
    if (period === '1h') qs = 'hours=1'
    else if (period === '3h') qs = 'hours=3'
    else if (period === '12h') qs = 'hours=12'
    else if (period === 'custom') qs = `period=custom&start=${encodeURIComponent(start ?? '')}&end=${encodeURIComponent(end ?? '')}`
    else qs = `period=${period}`
    return request<Pipeline>(`/dashboard/pipeline?${qs}`)
  },
  fbPipeline: (period: PipelinePeriod = '12h', start?: string, end?: string) => {
    let qs: string
    if (period === '1h') qs = 'hours=1'
    else if (period === '3h') qs = 'hours=3'
    else if (period === '12h') qs = 'hours=12'
    else if (period === 'custom') qs = `period=custom&start=${encodeURIComponent(start ?? '')}&end=${encodeURIComponent(end ?? '')}`
    else qs = `period=${period}`
    return request<FbPipeline>(`/dashboard/fb-pipeline?${qs}`)
  },
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
  providerConfigSchema: (kind?: string) =>
    request<ProviderConfigSchemaResponse>(
      `/providers/config-schema${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`),
  // 手动触发单个供应商的费用同步（brightdata=余额快照，apify=该账号账单/用量）
  syncProviderCosts: (kind: string, name: string) =>
    request<{ synced_at: string; brightdata?: { ok: boolean }; apify?: { ok: boolean } }>(
      `/costs/sync?provider=${encodeURIComponent(kind)}&account=${encodeURIComponent(name)}`,
      { method: 'POST' }),
  // ---------- 采集脚本管理 ----------
  scriptsList: () => request<ScriptInfo[]>('/scripts'),
  scriptStart: (name: ScriptName, opts?: ScriptStartOptions) =>
    request<{ pid: number }>(`/scripts/${name}/start`, {
      method: 'POST',
      body: JSON.stringify({
        params: opts?.params,
        keywords: opts?.keywords,
        clear_keywords: opts?.clearKeywords ?? false,
      }),
    }),
  scriptStop: (name: ScriptName) =>
    request<{ stopped: number }>(`/scripts/${name}/stop`, { method: 'POST' }),
  scriptRestart: (name: ScriptName, params?: Record<string, number>) =>
    request<{ pid: number }>(`/scripts/${name}/restart`, {
      method: 'POST',
      body: JSON.stringify(params ? { params } : {}),
    }),
  // 保存参数（仅落库，重启后生效）
  scriptSaveParams: (name: ScriptName, params: Record<string, number>) =>
    request<{ name: string; params: Record<string, number> }>(`/scripts/${name}/params`, {
      method: 'POST',
      body: JSON.stringify({ params }),
    }),
  scriptLogs: (name: ScriptName, offset: number) =>
    request<ScriptLogChunk>(`/scripts/${name}/logs?offset=${offset}`),
  // 选词面板数据（仅 fb/x）
  scriptKeywords: (name: ScriptName) =>
    request<ScriptKeywordsResp>(`/scripts/${name}/keywords`),
  // ---------- 词库产量 ----------
  keywordsList: (params: KeywordsQuery = {}) => {
    const qs = new URLSearchParams()
    if (params.q) qs.set('q', params.q)
    if (params.platform && params.platform !== 'all') qs.set('platform', params.platform)
    if (params.status && params.status !== 'all') qs.set('status', params.status)
    if (params.sort) qs.set('sort', params.sort)
    if (params.order) qs.set('order', params.order)
    if (params.page) qs.set('page', String(params.page))
    if (params.page_size) qs.set('page_size', String(params.page_size))
    const s = qs.toString()
    return request<KeywordsPage>(`/keywords${s ? `?${s}` : ''}`)
  },
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
