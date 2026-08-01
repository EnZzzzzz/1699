import { useEffect, useRef, useState } from 'react'
import type { WsMessage } from '@/api/types'

interface UseRealtimeOptions {
  /** 收到 WebSocket 消息时回调 */
  onMessage?: (msg: WsMessage) => void
  /** WS 断开时的降级轮询函数（2s 一次）；返回 void */
  poll?: () => void | Promise<void>
  /** 轮询间隔，默认 2000ms */
  pollInterval?: number
  /** 是否启用，默认 true */
  enabled?: boolean
  /** WS 每次（重）连上后调用，用于发送订阅等上行消息 */
  onOpen?: (send: (msg: unknown) => void) => void
}

export interface RealtimeState {
  connected: boolean
  polling: boolean
}

/**
 * 连接 /ws，断线自动重连（指数退避，封顶 10s），
 * 断开期间降级为 2s 轮询对应 REST。组件卸载时全部清理。
 */
export function useRealtime({ onMessage, poll, pollInterval = 2000, enabled = true, onOpen }: UseRealtimeOptions): RealtimeState {
  const [connected, setConnected] = useState(false)
  const [polling, setPolling] = useState(false)
  const onMessageRef = useRef(onMessage)
  const pollRef = useRef(poll)
  const onOpenRef = useRef(onOpen)
  onMessageRef.current = onMessage
  pollRef.current = poll
  onOpenRef.current = onOpen

  useEffect(() => {
    if (!enabled) return

    let ws: WebSocket | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let pollTimer: ReturnType<typeof setInterval> | null = null
    let attempts = 0
    let disposed = false

    const stopPolling = () => {
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
      setPolling(false)
    }

    const startPolling = () => {
      if (pollTimer || !pollRef.current) return
      setPolling(true)
      pollTimer = setInterval(() => {
        void pollRef.current?.()
      }, pollInterval)
    }

    const connect = () => {
      if (disposed) return
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      ws = new WebSocket(`${proto}//${window.location.host}/ws`)

      ws.onopen = () => {
        attempts = 0
        setConnected(true)
        stopPolling()
        onOpenRef.current?.((msg) => {
          if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
        })
      }

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as WsMessage
          onMessageRef.current?.(msg)
        } catch {
          // 忽略非 JSON 消息
        }
      }

      ws.onclose = () => {
        setConnected(false)
        ws = null
        if (disposed) return
        startPolling()
        const delay = Math.min(1000 * 2 ** attempts, 10000)
        attempts += 1
        retryTimer = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        ws?.close()
      }
    }

    connect()

    return () => {
      disposed = true
      stopPolling()
      if (retryTimer) clearTimeout(retryTimer)
      if (ws) {
        ws.onclose = null // 阻止重连逻辑
        ws.close()
      }
    }
  }, [enabled, pollInterval])

  return { connected, polling }
}
