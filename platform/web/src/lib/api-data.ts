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
  // 微信查号结果（wx_lookup_runner 写回；列未迁移时全为 null）
  wx_registered: number | null
  wx_checked_at: string | null
  wx_nick: string | null
  wx_gender: 'male' | 'female' | 'unknown' | null
  wx_avatar: string | null
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
  source?: 'fb' | 'x' | ''
  q?: string
  page?: number
  size?: number
}

export interface FbExportQuery {
  wa?: WaFilter | ''
  bucket?: FbBucket | ''
  source?: 'fb' | 'x' | ''
  q?: string
  fields: string[]
  format: 'csv' | 'xlsx'
  /** 发现时间范围（YYYY-MM-DD，含首尾日），空串为不限 */
  dateFrom?: string
  dateTo?: string
  /** first=仅未导出过的（默认）；repeat=含已导出过的 */
  mode?: 'first' | 'repeat'
  /** 最多导出条数（最新优先），0/undefined=不限 */
  limit?: number
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
  fbContacts: ({ wa, bucket, source, q, page = 1, size = 20 }: FbContactsQuery) =>
    request<Paged<FbContactItem>>(
      `/data/fb-contacts${qs({ wa: wa || undefined, bucket: bucket || undefined, source: source || undefined, q, page, size })}`),
  // 导出 FB/X 联系方式（blob 下载，非 JSON，不走 request()），返回文件名与条数
  exportFbContacts: async ({ wa, bucket, source, q, fields, format, dateFrom, dateTo, mode, limit }: FbExportQuery): Promise<{ filename: string; count: number }> => {
    const path = `/data/fb-contacts/export${qs({
      wa: wa || undefined,
      bucket: bucket || undefined,
      source: source || undefined,
      q,
      fields: fields.join(','),
      format,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      mode: mode || undefined,
      limit: limit || undefined,
    })}`
    let res: Response
    try {
      res = await fetch(`${BASE}${path}`)
    } catch {
      throw new ApiDataError('无法连接后端服务（http://127.0.0.1:8765）')
    }
    if (!res.ok) {
      throw new ApiDataError(`请求失败：${res.status} ${res.statusText}`, res.status)
    }
    const blob = await res.blob()
    const m = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') ?? '')
    const filename = m?.[1] ?? `contacts.${format}`
    const count = Number(res.headers.get('X-Exported-Count') ?? 0)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    return { filename, count }
  },
}
