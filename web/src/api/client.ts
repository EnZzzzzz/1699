import axios, { AxiosError } from 'axios'

// 后端 FastAPI 基址由 vite dev proxy 转发：/api -> http://localhost:8765
export const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

/** 是否为"端点未实现"错误（501 / 404），页面据此降级展示空态 */
export function isNotImplemented(err: unknown): boolean {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status
    return status === 501 || status === 404
  }
  return false
}

/** 提取可读的错误信息 */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const e = err as AxiosError<{ detail?: string }>
    if (e.response?.data?.detail) return String(e.response.data.detail)
    if (e.code === 'ERR_NETWORK' || e.code === 'ECONNREFUSED') return '无法连接后端服务（http://localhost:8765）'
    return e.message
  }
  if (err instanceof Error) return err.message
  return '未知错误'
}

/** 兼容后端返回数组或 {items: []} / {list: []} 的分页结构 */
export function asArray<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>
    for (const key of ['items', 'list', 'data', 'channels', 'tasks', 'providers']) {
      if (Array.isArray(obj[key])) return obj[key] as T[]
    }
  }
  return []
}

/** 解析分页结果 */
export function asPaged<T>(data: unknown, fallbackPage = 1): { items: T[]; total: number; page: number } {
  if (Array.isArray(data)) return { items: data as T[], total: data.length, page: fallbackPage }
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>
    const items = asArray<T>(data)
    const total = typeof obj.total === 'number' ? obj.total : items.length
    const page = typeof obj.page === 'number' ? obj.page : fallbackPage
    return { items, total, page }
  }
  return { items: [], total: 0, page: fallbackPage }
}
