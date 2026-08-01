// API 契约类型定义（依据 docs/service-architecture.md §4/§8 + 后端真实返回核对）

export type TaskType = 'shop_crawl' | 'contact_fetch'

export type TaskStatus =
  | 'pending'
  | 'waiting_channel'
  | 'running'
  | 'stopping'
  | 'done'
  | 'failed'
  | 'stopped'

export interface TaskProgress {
  collected?: number
  pending?: number
  per_minute?: number
  total?: number
  phase?: string // worker 上报的阶段；'waiting_confirm' = 等待人工确认开始采集
  // [待后端确认] 其余 progress_json 内的键
  [key: string]: number | string | undefined
}

export interface Task {
  id: number
  type: TaskType
  params: TaskParams
  celery_id?: string | null
  status: TaskStatus
  progress?: TaskProgress | null
  error?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

/** GET /api/tasks/{id} 响应 = Task + board（旧进程可能未附加 board，故可选） */
export interface TaskDetail extends Task {
  stop_requested?: boolean
  board?: Board
}

// ---------- 任务详情实时看板（board，每次请求现算） ----------

export interface BoardChannel {
  id: number
  tunnel: string | null
  exit_ip: string | null
  provider_name: string // 直连为 "本机 IP"
  status: ChannelStatus
  requests_5m: number
}

interface BoardBase {
  type: TaskType
  phase: string | null // 'waiting_confirm' 等
  collected: number
  total: number | null // contact_fetch 未设 limit 时为 null
  remaining: number | null
  per_minute: number
  elapsed_seconds: number | null // started_at 为空时为 null
  eta_seconds: number | null
  channels: BoardChannel[]
}

export interface CategoryProgress {
  keyword: string
  next_page: number
  exhausted: boolean
}

export interface ShopCrawlBoard extends BoardBase {
  type: 'shop_crawl'
  target: number
  pending_contacts: number // 全库待抓联系方式店铺数
  categories: CategoryProgress[] // 类目分页进度 Top10
}

export interface ContactFetchStatusCounts {
  pending: number
  in_progress: number
  done: number
  no_contact: number
  failed: number
  blocked: number
}

export interface ContactFetchBoard extends BoardBase {
  type: 'contact_fetch'
  status_counts: ContactFetchStatusCounts
  task_done: number
  task_failed: number
}

export type Board = ShopCrawlBoard | ContactFetchBoard

// ---------- 任务创建 ----------

// 已核对后端 GET /api/tasks/param-specs 实际返回（shop_crawl 13 个 / contact_fetch 16 个）
export interface ParamSpec {
  name: string // 提交时 params 的键
  label: string // 中文标签
  type: 'int' | 'float' | 'bool' | 'str' | 'select'
  default: unknown
  min?: number
  max?: number
  help?: string
  group?: string // 基本/浏览器/节奏控制/重试策略
  options?: { value: string; label: string }[]
}

export type ParamSpecs = Partial<Record<TaskType, ParamSpec[]>>

export interface TaskParams {
  target?: number // shop_crawl：目标店铺数，0=每 worker 采 1 轮
  category?: string
  workers?: number
  channels?: number
  proxy?: boolean
  headed?: boolean
  yes?: boolean // shop_crawl：跳过人工确认
  start_delay_min?: number // 启动前等待下限（秒）；与上限相等=固定，不等=区间内随机
  start_delay_max?: number // 启动前等待上限（秒），需 >= 下限
  rest_every?: number
  rotate_every?: number // 每成功处理 N 个主动更换出口 IP，0=不主动换
  rest_min?: number
  rest_max?: number
  delay_min?: number
  delay_max?: number
  limit?: number // contact_fetch：本次限抓数量，0=抓完全部 pending
  num?: number
  batch_rest?: number
  max_batches?: number
  ip_retry?: number
  block_retry?: number
  net_retry?: number
  max_consecutive_fail?: number
}

export interface CreateTaskPayload {
  type: TaskType
  params: TaskParams
}

// ---------- IP 池 ----------

export type ChannelStatus = 'idle' | 'in_use' | 'error'

export interface Channel {
  id: number
  provider_id: number | null // null = 直连
  provider_name: string // 直连为 "本机 IP"（已核对）
  tunnel: string | null
  exit_ip: string | null
  status: ChannelStatus
  used_by_task: number | null
  used_by_task_type: TaskType | null // 已核对
  ip_expires_at: string | null
  last_probe_at?: string | null
  requests_5m: number // 已核对：近 5 分钟请求数
  freq_5m: number[] // 已核对：近 5 分钟每分钟频率序列（后端另返回 rpm_5m 均值，未使用）
}

export interface PoolUsageBucket {
  channel_id: number
  requests: number
  freq: number[]
}

export interface PoolUsage {
  minutes: number
  buckets: PoolUsageBucket[] // [待后端确认] /api/pool/usage 聚合结构
}

// ---------- 厂商配置 ----------

export interface ConfigField {
  key: string
  label: string
  type: 'string' | 'password' | 'number' | 'boolean'
  required?: boolean
  default?: string | number | boolean
  placeholder?: string
}

export interface Provider {
  id: number
  kind: string // qingguo / direct / 未来厂商
  name: string
  config: Record<string, string | number | boolean> // config_json 解析后的对象
  config_schema?: ConfigField[] // [待后端确认] 后端返回 schema 驱动表单
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ProviderPayload {
  kind: string
  name: string
  config: Record<string, string | number | boolean>
  enabled: boolean
}

export interface TestResult {
  ok: boolean
  message?: string
  channels?: number
  exit_ip?: string
  latency_ms?: number
  quota?: unknown // 后端额外调试字段，前端不使用
  probes?: unknown // 后端额外调试字段，前端不使用
}

// ---------- 数据浏览 ----------

// 已核对后端 /api/shops 实际返回（M5）
export interface Shop {
  id: number
  domain: string
  name: string
  url: string
  category_keyword?: string
  run_id?: number
  picked?: number
  first_seen_at?: string
  last_seen_at?: string
  status: string // pending / done / failed / blocked
  attempts?: number
}

// 已核对后端 /api/contacts 实际返回（contacts JOIN shops）
export interface Contact {
  id: number
  shop_id: number
  contact_person?: string | null
  gender?: string | null
  phone?: string | null
  mobile?: string | null
  fax?: string | null
  address?: string | null
  source_url?: string | null
  scraped_at?: string | null
  raw_text?: string | null
  domain?: string
  shop_name?: string
  category_keyword?: string
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ---------- Dashboard ----------

export interface StatsOverview {
  total_shops: number
  pending_shops: number
  today_new: number
  running_tasks: number
  channels_total: number
  channels_in_use: number
  rate_last_hour: number[] // 已核对：60 个每分钟采集数
}

// ---------- Worker 看板 ----------

// 已核对后端 GET /api/workers 实际返回
export interface ActiveTaskInfo {
  celery_id: string | null
  name: string | null
  task_id: number | null // 平台任务 id，可跳 /tasks/:id；解析失败为 null
  time_start?: number | null
}

export interface WorkerInfo {
  hostname: string
  status: string // 'online'
  pid?: number | null
  uptime_seconds?: number | null
  concurrency?: number | null
  pool_impl?: string | null
  registered: string[]
  active: ActiveTaskInfo[]
}

export interface WorkersOverview {
  online: boolean
  count: number
  workers: WorkerInfo[]
  error?: string | null
  checked_at: string
}

// ---------- broker 队列 ----------

// 已核对后端 GET /api/workers/queue 实际返回
export interface QueueMessage {
  celery_id: string | null
  name: string | null
  task_id: number | null // 平台任务 id，可跳 /tasks/:id；解析失败为 null
  argsrepr?: string | null
  eta?: string | null
  retries: number
  db_status?: TaskStatus | null // 对应平台任务状态；任务不存在为 null
  stale?: boolean // true = 任务已终态或不存在，消息已不会被正确处理，建议清除
  unparseable?: boolean
}

export interface QueueOverview {
  available: boolean
  error?: string | null
  count: number
  messages: QueueMessage[] // 第 1 条 = 下一个被 worker 消费
  checked_at: string
}

// ---------- 任务实时事件 ----------

export type TaskEventLevel = 'info' | 'success' | 'warning' | 'error'

// 已核对后端 GET /api/tasks/{id}/events 实际返回
export interface TaskEvent {
  id: number
  ts: string // "2026-08-01 02:03:42"
  level: TaskEventLevel
  message: string
  data: Record<string, unknown> | null
}

export interface TaskEventsResponse {
  items: TaskEvent[]
  latest_id: number
}

// ---------- WebSocket ----------
export type WsMessage =
  | { type: 'task_progress'; task: Task }
  | { type: 'pool_status'; channels: Channel[] }
  | { type: 'task_event'; task_id: number; event: TaskEvent }
