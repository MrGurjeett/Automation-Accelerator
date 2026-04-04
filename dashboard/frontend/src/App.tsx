import { useState, useCallback, useRef } from 'react'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'
import { RunPage } from './pages/RunPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { ArtifactsPage } from './pages/ArtifactsPage'
import { HistoryPage } from './pages/HistoryPage'
import { Toast, ToastItem } from './components/Toast'
import { usePolling } from './hooks/usePolling'
import { useWebSocket } from './hooks/useWebSocket'
import { getStatus, getProgress } from './api/client'
import type { StatusResponse, ProgressResponse, WsEvent } from './api/types'

export type Page = 'run' | 'history' | 'analytics' | 'artifacts'

export default function App() {
  const [page, setPage] = useState<Page>('run')
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [progress, setProgress] = useState<ProgressResponse | null>(null)
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const [logLines, setLogLines] = useState<string[]>([])
  const [liveStats, setLiveStats] = useState<Record<string, unknown> | null>(null)
  const toastId = useRef(0)

  const addToast = useCallback((message: string, type: 'info' | 'error' = 'info') => {
    const id = ++toastId.current
    setToasts((prev) => [...prev.slice(-3), { id, message, type }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 5000)
  }, [])

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const isRunning = status?.state?.running ?? false
  const pollInterval = isRunning ? 1200 : 5000

  usePolling(
    useCallback(async () => {
      try {
        const [s, p] = await Promise.all([getStatus(), getProgress()])
        setStatus(s)
        setProgress(p)
      } catch {
        // silent
      }
    }, []),
    pollInterval,
    true
  )

  // WebSocket / HTTP polling event handler
  const handleWsEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case 'log':
        if (event.line !== undefined) {
          setLogLines((prev) => [...prev.slice(-2000), event.line!])
        }
        break
      case 'stats':
        if (event.data) {
          setLiveStats(event.data)
        }
        break
      case 'pipeline_event': {
        // Real-time stepper update from structured pipeline events
        const evt = event.data as Record<string, unknown> | undefined
        if (!evt) break
        const eventType = evt.event_type as string
        const stepName = evt.step_name as string
        const durationMs = evt.duration_ms as number | undefined

        // Handle pipeline-level events (PIPELINE_STARTED with config steps)
        if (eventType === 'PIPELINE_STARTED') {
          const configSteps = (evt.metadata as Record<string, unknown>)?.steps as Array<{ key: string; label: string }> | undefined
          if (configSteps?.length) {
            setProgress((prev) => ({
              steps: configSteps.map((s) => ({ key: s.key, label: s.label, status: 'pending' as const })),
              running: true,
              mode: (evt.metadata as Record<string, unknown>)?.config as string || prev?.mode || '',
            }))
          }
          break
        }

        // Handle BRANCH_TAKEN — log for observability but no stepper change needed
        if (eventType === 'BRANCH_TAKEN') {
          const fromStep = evt.from_step as string
          const toStep = evt.to_step as string
          const branch = evt.branch as string
          console.debug(`[BRANCH] ${fromStep} → ${toStep} (${branch})`)
          break
        }

        // Handle DECISION_TAKEN / RETRY_DECISION — Phase 4.3 observability
        if (eventType === 'DECISION_TAKEN') {
          const source = evt.source as string
          const selected = evt.selected as string
          const confidence = evt.confidence as number
          console.debug(`[DECISION] ${evt.from_step} → ${selected} (${source}, confidence=${confidence || 'N/A'})`)
          break
        }
        if (eventType === 'RETRY_DECISION') {
          const retry = evt.retry as boolean
          const source = evt.source as string
          console.debug(`[RETRY] ${stepName} retry=${retry} (${source})`)
          break
        }

        if (!stepName) break
        setProgress((prev) => {
          if (!prev) return prev
          const updated = prev.steps.map((s) => {
            if (s.key !== stepName) return s
            if (eventType === 'STEP_STARTED') return { ...s, status: 'active' as const }
            if (eventType === 'STEP_COMPLETED') return { ...s, status: 'done' as const, duration_ms: durationMs }
            if (eventType === 'STEP_FAILED') return { ...s, status: 'error' as const, duration_ms: durationMs }
            if (eventType === 'STEP_SKIPPED') return { ...s, status: 'skipped' as const }
            return s
          })
          return { ...prev, steps: updated }
        })
        break
      }
      case 'run_complete':
        addToast(
          `Run completed (exit code: ${(event.data as Record<string, unknown>)?.exit_code ?? '?'})`,
          (event.data as Record<string, unknown>)?.exit_code === 0 ? 'info' : 'error'
        )
        break
    }
  }, [addToast])

  const { connected: wsConnected } = useWebSocket(handleWsEvent)

  const renderPage = () => {
    switch (page) {
      case 'run':
        return (
          <RunPage
            status={status}
            progress={progress}
            logLines={logLines}
            liveStats={liveStats}
            addToast={addToast}
            wsConnected={wsConnected}
          />
        )
      case 'analytics':
        return <AnalyticsPage status={status} />
      case 'artifacts':
        return <ArtifactsPage />
      case 'history':
        return <HistoryPage />
      default:
        return null
    }
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar currentPage={page} onNavigate={setPage} isRunning={isRunning} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <TopBar status={status} wsConnected={wsConnected} />
        <main className="flex-1 overflow-auto p-6 bg-navy-50">
          {renderPage()}
        </main>
      </div>
      <Toast toasts={toasts} onRemove={removeToast} />
    </div>
  )
}
