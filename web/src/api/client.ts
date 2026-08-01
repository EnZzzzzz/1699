import axios, { AxiosError } from 'axios'
import type { AtomSpec, Dag, DagValidation, Flow, FlowDetail, Task } from './types'

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

// ---------- 流水线（flows / atoms，docs/flow-architecture.md §7） ----------

export const flowApi = {
  /** 模板列表（不含 dag 大字段） */
  list: async (): Promise<Flow[]> => (await api.get('/flows')).data as Flow[],
  /** 模板详情（含 dag） */
  get: async (id: number): Promise<FlowDetail> => (await api.get(`/flows/${id}`)).data as FlowDetail,
  /** 新建模板（后端先校验 DAG，errors 非空 400） */
  create: async (payload: { name: string; description?: string; dag: Dag }): Promise<FlowDetail> =>
    (await api.post('/flows', payload)).data as FlowDetail,
  /** 独立 DAG 校验（保存前调用） */
  validate: async (dag: unknown): Promise<DagValidation> =>
    (await api.post('/flows/validate', { dag })).data as DagValidation,
  /** 更新模板（builtin=1 后端拒绝；dag 变更后端重新校验） */
  update: async (id: number, payload: { name?: string; description?: string; dag?: Dag }): Promise<FlowDetail> =>
    (await api.put(`/flows/${id}`, payload)).data as FlowDetail,
  /** 复制出新版本（name 加「（副本）」，builtin=0） */
  duplicate: async (id: number): Promise<FlowDetail> =>
    (await api.post(`/flows/${id}/duplicate`)).data as FlowDetail,
  /** 删除模板（builtin / 被任务引用时后端拒绝） */
  remove: async (id: number): Promise<void> => {
    await api.delete(`/flows/${id}`)
  },
}

/** 原子目录（带会话级缓存；失败时清空缓存以便下次重试） */
let atomCatalogPromise: Promise<AtomSpec[]> | null = null
export function getAtomCatalog(): Promise<AtomSpec[]> {
  if (!atomCatalogPromise) {
    atomCatalogPromise = (api.get('/atoms').then((r) => r.data) as Promise<AtomSpec[]>).catch((e) => {
      atomCatalogPromise = null
      throw e
    })
  }
  return atomCatalogPromise
}

/** 原子名 → 显示名映射（FlowGraph 卡片标题用；目录不可用时退回原名） */
export async function getAtomTitles(): Promise<Record<string, string>> {
  const catalog = await getAtomCatalog()
  const map: Record<string, string> = {}
  for (const a of catalog) map[a.name] = a.title
  return map
}

/** 创建 flow 任务：params 即 dag.run_inputs 的实参；响应含 dispatched/warning */
export async function createFlowTask(
  flowId: number,
  runInputs: Record<string, unknown>,
): Promise<Task & { dispatched?: boolean; warning?: string }> {
  const res = await api.post('/tasks', { type: 'flow', flow_id: flowId, params: runInputs })
  return res.data as Task & { dispatched?: boolean; warning?: string }
}
