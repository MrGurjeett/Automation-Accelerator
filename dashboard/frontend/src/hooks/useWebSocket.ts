import { useEffect, useRef, useState, useCallback } from 'react'
import type { WsEvent } from '../api/types'

const LOG_POLL_URL = '/api/live-logs'

/**
 * Simple, reliable log delivery via HTTP polling.
 *
 * Previous attempts using WebSocket had intermittent delivery failures
 * in the browser (stale closures, reconnection loops, thread-safety issues).
 *
 * This hook uses a straightforward HTTP polling approach:
 * - Polls /api/live-logs?since=N every 500ms when active
 * - Server maintains an in-memory event buffer
 * - Cursor-based pagination ensures no events are missed
 * - Zero WebSocket complexity
 */
export function useWebSocket(onEvent: (event: WsEvent) => void) {
  const [connected, setConnected] = useState(false)
  const cursorRef = useRef(0)
  const onEventRef = useRef(onEvent)
  const timerRef = useRef<ReturnType<typeof setInterval>>()
  onEventRef.current = onEvent

  useEffect(() => {
    let active = true

    async function poll() {
      if (!active) return
      try {
        const res = await fetch(`${LOG_POLL_URL}?since=${cursorRef.current}`)
        if (!res.ok) {
          setConnected(false)
          return
        }
        setConnected(true)
        const data = await res.json()

        if (data.events && data.events.length > 0) {
          for (const event of data.events) {
            if (event.type !== 'heartbeat') {
              onEventRef.current(event as WsEvent)
            }
          }
          cursorRef.current = data.next_since
        }
      } catch {
        setConnected(false)
      }
    }

    // Initial poll
    poll()
    // Poll every 500ms
    timerRef.current = setInterval(poll, 500)

    return () => {
      active = false
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

  // Allow resetting cursor (e.g., when starting a new run)
  const resetCursor = useCallback(() => {
    cursorRef.current = 0
  }, [])

  return { connected, resetCursor }
}
