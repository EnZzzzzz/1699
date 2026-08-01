import { api } from '@/api/client'
import type { ParamSpec, ParamSpecs, TaskType } from '@/api/types'

// 接口失败时的本地兜底 spec（与后端 PARAM_SPEC 字段集一致，默认值以编写时后端为准）
const FALLBACK_SPECS: ParamSpecs = {
  shop_crawl: [
    { name: 'target', label: '目标数量', type: 'int', default: 0, min: 0, group: '基本', help: '本任务新增店铺数，0=每 worker 采 1 轮' },
    { name: 'category', label: '指定类目', type: 'str', default: '', group: '基本', help: '类目关键词（空=全类目轮采）' },
    { name: 'workers', label: '并发数', type: 'int', default: 1, min: 1, max: 8, group: '基本' },
    { name: 'channels', label: '通道数', type: 'int', default: 1, min: 1, max: 8, group: '基本' },
    { name: 'proxy', label: '走代理', type: 'bool', default: true, group: '基本', help: 'False=直连本机 IP' },
    { name: 'start_delay_min', label: '启动前等待下限（秒）', type: 'int', default: 0, min: 0, group: '基本', help: '任务 running 后先等待再申请通道执行；与上限相等=固定等待，不等=区间内随机抽一个等待时长' },
    { name: 'start_delay_max', label: '启动前等待上限（秒）', type: 'int', default: 0, min: 0, group: '基本', help: '需 ≥ 下限；等待期间可停止，不占用任何资源' },
    { name: 'headed', label: '有头模式', type: 'bool', default: false, group: '浏览器', help: '弹出浏览器窗口（可用于人工过滑块/登录）' },
    { name: 'yes', label: '跳过人工确认', type: 'bool', default: true, group: '浏览器', help: '无人值守；headed+yes=False 时引导页打开后等人工确认' },
    { name: 'rest_every', label: '每 N 轮长休', type: 'int', default: 0, min: 0, group: '节奏控制' },
    { name: 'rotate_every', label: '每 N 个主动换 IP', type: 'int', default: 0, min: 0, group: '节奏控制', help: '0=不主动换；>0 时每成功处理 N 个随机更换一次出口 IP（新 IP 可能无 Cookie 需重新验证）' },
    { name: 'delay_min', label: '轮间延迟下限（秒）', type: 'float', default: 15, min: 0, group: '节奏控制' },
    { name: 'delay_max', label: '轮间延迟上限（秒）', type: 'float', default: 45, min: 0, group: '节奏控制' },
    { name: 'rest_min', label: '长休时长下限（秒）', type: 'float', default: 300, min: 0, group: '节奏控制' },
    { name: 'rest_max', label: '长休时长上限（秒）', type: 'float', default: 600, min: 0, group: '节奏控制' },
  ],
  contact_fetch: [
    { name: 'limit', label: '本次限抓数量', type: 'int', default: 0, min: 0, group: '基本', help: '0=抓完全部 pending' },
    { name: 'workers', label: '并发数', type: 'int', default: 1, min: 1, max: 8, group: '基本' },
    { name: 'channels', label: '通道数', type: 'int', default: 1, min: 1, max: 8, group: '基本' },
    { name: 'proxy', label: '走代理', type: 'bool', default: true, group: '基本', help: 'False=直连本机 IP' },
    { name: 'start_delay_min', label: '启动前等待下限（秒）', type: 'int', default: 0, min: 0, group: '基本', help: '任务 running 后先等待再申请通道执行；与上限相等=固定等待，不等=区间内随机抽一个等待时长' },
    { name: 'start_delay_max', label: '启动前等待上限（秒）', type: 'int', default: 0, min: 0, group: '基本', help: '需 ≥ 下限；等待期间可停止，不占用任何资源' },
    { name: 'headed', label: '有头模式', type: 'bool', default: false, group: '浏览器' },
    { name: 'num', label: '每批数量', type: 'int', default: 10, min: 1, group: '节奏控制' },
    { name: 'batch_rest', label: '批间休息（秒）', type: 'float', default: 900, min: 0, group: '节奏控制' },
    { name: 'max_batches', label: '最多批数', type: 'int', default: 0, min: 0, group: '节奏控制', help: '0=不限批数' },
    { name: 'rest_every', label: '每 N 个长休', type: 'int', default: 20, min: 0, group: '节奏控制' },
    { name: 'rotate_every', label: '每 N 个主动换 IP', type: 'int', default: 0, min: 0, group: '节奏控制', help: '0=不主动换；>0 时每成功处理 N 个随机更换一次出口 IP（新 IP 可能无 Cookie 需重新验证）' },
    { name: 'rest_min', label: '长休时长下限（秒）', type: 'float', default: 60, min: 0, group: '节奏控制' },
    { name: 'rest_max', label: '长休时长上限（秒）', type: 'float', default: 180, min: 0, group: '节奏控制' },
    { name: 'ip_retry', label: '换 IP 重试次数', type: 'int', default: 3, min: 0, group: '重试策略' },
    { name: 'block_retry', label: '风控换通道重试次数', type: 'int', default: 2, min: 0, group: '重试策略' },
    { name: 'net_retry', label: '网络故障重试次数', type: 'int', default: 5, min: 0, group: '重试策略' },
    { name: 'max_consecutive_fail', label: '连续失败中止阈值', type: 'int', default: 5, min: 1, group: '重试策略' },
  ],
}

// 旧的硬编码中文标签（param-specs 取不到时的兜底）
const LEGACY_LABELS: Record<string, string> = {
  target: '目标数量',
  category: '类目',
  workers: '并发数',
  channels: '通道数',
  proxy: '走代理',
  headed: '有头模式',
  yes: '跳过人工确认',
  rest_every: '轮间休息（条）',
  limit: '抓取上限',
}

let cache: ParamSpecs | null = null
let inflight: Promise<ParamSpecs> | null = null

/**
 * 拉取参数规格（带缓存）。接口失败时返回本地兜底 spec，
 * fallback=true 时调用方可 toast 提示。
 */
export async function getParamSpecs(): Promise<{ specs: ParamSpecs; fallback: boolean }> {
  if (cache) return { specs: cache, fallback: false }
  if (!inflight) {
    inflight = api
      .get<ParamSpecs>('/tasks/param-specs')
      .then((res) => {
        cache = res.data
        return cache
      })
      .catch(() => FALLBACK_SPECS)
      .finally(() => {
        inflight = null
      })
  }
  const specs = await inflight
  return { specs, fallback: specs === FALLBACK_SPECS }
}

/** 按参数名取中文标签：优先 param-specs（两类都查），取不到用旧映射，再兜底原键名 */
export function paramLabel(name: string, specs?: ParamSpecs | null): string {
  const all: ParamSpec[] = [
    ...(specs?.shop_crawl ?? cache?.shop_crawl ?? []),
    ...(specs?.contact_fetch ?? cache?.contact_fetch ?? []),
  ]
  return all.find((s) => s.name === name)?.label ?? LEGACY_LABELS[name] ?? name
}

/** 某任务类型的 spec 列表（永不返回 undefined） */
export function specsFor(specs: ParamSpecs | null, type: TaskType): ParamSpec[] {
  return specs?.[type] ?? FALLBACK_SPECS[type] ?? []
}
