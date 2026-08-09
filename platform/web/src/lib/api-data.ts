// 数据浏览页 API 封装：shops / contacts 分页查询
// 风格与 lib/api.ts 的 request() 保持一致（BASE=/api，统一错误语义）

const BASE = '/api'

export class ApiDataError extends Error {
  status: number
  constructor(message: string, status = 0) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new ApiDataError('无法连接后端服务（http://127.0.0.1:8765）')
  }
  if (!res.ok) {
    throw new ApiDataError(`请求失败：${res.status} ${res.statusText}`, res.status)
  }
  return (await res.json()) as T
}

// ---------- 类型定义（与后端契约一致） ----------

export interface ShopItem {
  id: number
  domain: string
  name: string | null
  status: string
  first_seen_at: string | null
  last_seen_at: string | null
  contact_count: number
}

export interface ContactItem {
  id: number
  shop_id: number
  contact_person: string | null
  gender: string | null
  phone: string | null
  mobile: string | null
  address: string | null
  scraped_at: string | null
  wa_registered: number | null
  wa_checked_at: string | null
  shop_domain: string | null
  shop_name: string | null
}

export interface Paged<T> {
  total: number
  page: number
  size: number
  items: T[]
}

export interface FbContactItem {
  id: number
  number: string
  bucket: string
  wa_source: string | null
  wa_registered: number | null
  wa_checked_at: string | null
  post_url: string
  group_id: string | null
  first_seen_at: string | null
  group_name: string | null
  keyword: string | null
}

export type WaFilter = 'registered' | 'unregistered' | 'unchecked'

export interface ShopsQuery {
  status?: string
  q?: string
  page?: number
  size?: number
}

export interface ContactsQuery {
  wa?: WaFilter | ''
  has_mobile?: boolean
  q?: string
  page?: number
  size?: number
}

export type FbBucket = 'declared_wa' | 'cn_uncertain' | 'overseas'

export interface FbContactsQuery {
  wa?: WaFilter | ''
  bucket?: FbBucket | ''
  q?: string
  page?: number
  size?: number
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

// ---------- 接口方法 ----------

export const dataApi = {
  shops: ({ status, q, page = 1, size = 20 }: ShopsQuery) =>
    request<Paged<ShopItem>>(
      `/data/shops${qs({ status, q, page, size })}`),
  contacts: ({ wa, has_mobile, q, page = 1, size = 20 }: ContactsQuery) =>
    request<Paged<ContactItem>>(
      `/data/contacts${qs({ wa: wa || undefined, has_mobile: has_mobile ? '1' : undefined, q, page, size })}`),
  fbContacts: ({ wa, bucket, q, page = 1, size = 20 }: FbContactsQuery) =>
    request<Paged<FbContactItem>>(
      `/data/fb-contacts${qs({ wa: wa || undefined, bucket: bucket || undefined, q, page, size })}`),
}
