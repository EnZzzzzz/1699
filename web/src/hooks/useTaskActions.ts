import { useState } from 'react'
import { api, errorMessage } from '@/api/client'
import type { Task } from '@/api/types'
import { toast } from 'sonner'

/** 任务停止/人工确认操作，列表页与详情页共用 */
export function useTaskActions(onChanged: () => void) {
  const [confirmingId, setConfirmingId] = useState<number | null>(null)

  const stopTask = async (task: Task) => {
    try {
      await api.post(`/tasks/${task.id}/stop`)
      toast.success(`已请求停止任务 #${task.id}`)
      onChanged()
    } catch (e) {
      toast.error(`停止失败：${errorMessage(e)}`)
    }
  }

  const confirmTask = async (task: Task) => {
    setConfirmingId(task.id)
    try {
      await api.post(`/tasks/${task.id}/confirm`)
      toast.success(`已确认任务 #${task.id}，采集将继续进行`)
      onChanged()
    } catch (e) {
      toast.error(`确认失败：${errorMessage(e)}`)
    } finally {
      setConfirmingId(null)
    }
  }

  return { stopTask, confirmTask, confirmingId, canStop, needsConfirm }
}

export function canStop(t: Task) {
  return t.status === 'running' || t.status === 'pending' || t.status === 'waiting_channel'
}

/** headed 且未传 yes 的 shop_crawl 任务：worker 打开引导浏览器后置 progress.phase='waiting_confirm'，等待人工确认（10 分钟超时） */
export function needsConfirm(t: Task) {
  return t.type === 'shop_crawl' && t.status === 'running' && t.progress?.phase === 'waiting_confirm'
}
