import { useEffect, useRef, useState } from 'react'
import type { StatusResponse, ProgressResponse } from '../api/types'
import { PipelineStepper } from '../components/PipelineStepper'
import { RunControls } from '../components/RunControls'
import { LogTerminal } from '../components/LogTerminal'
import { StatsCards, CumulativeStats } from '../components/StatsCards'

interface RunPageProps {
  status: StatusResponse | null
  progress: ProgressResponse | null
  logLines: string[]
  liveStats: Record<string, unknown> | null
  addToast: (msg: string, type?: 'info' | 'error') => void
  wsConnected: boolean
}

const defaultSteps = [
  { key: 'detect_excel', label: 'Upload & Parse', status: 'pending' as const },
  { key: 'read_excel', label: 'Read Excel', status: 'pending' as const },
  { key: 'validate', label: 'Schema Validation', status: 'pending' as const },
  { key: 'init_dom', label: 'DOM Extraction', status: 'pending' as const },
  { key: 'normalize', label: 'AI Normalisation', status: 'pending' as const },
  { key: 'generate', label: 'Feature Generation', status: 'pending' as const },
  { key: 'execute', label: 'Test Execution', status: 'pending' as const },
]

export function RunPage({
  status,
  progress,
  logLines,
  liveStats,
  addToast,
  wsConnected,
}: RunPageProps) {
  const isRunning = status?.state?.running ?? false
  const isPaused = status?.state?.paused ?? false

  // Track if the user has scrolled past the stepper's natural position
  const [isStuck, setIsStuck] = useState(false)
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => setIsStuck(!entry.isIntersecting),
      { threshold: [1], rootMargin: '0px' }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // Use progress steps from API (which now reflect the active config)
  // Fall back to default steps if no progress data yet
  const displaySteps = progress?.steps?.length ? progress.steps : defaultSteps

  return (
    <div className="animate-fade-in relative">
      {/* Sentinel — marks the stepper's natural position */}
      <div ref={sentinelRef} className="h-1 -mt-1" />

      {/* Pipeline Progress — becomes sticky ONLY after scrolling past */}
      <div
        className={`transition-shadow duration-300 ${
          isStuck
            ? 'sticky top-0 z-30 bg-navy-50 shadow-md shadow-navy-200/40 -mx-6 px-6 py-3'
            : ''
        }`}
      >
        <PipelineStepper steps={displaySteps} />
      </div>

      <div className="space-y-4 mt-4">
        {/* Stats Cards */}
        <StatsCards status={status} liveStats={liveStats} />

        {/* Run Controls */}
        <RunControls isRunning={isRunning} isPaused={isPaused} addToast={addToast} />

        {/* Log Terminal */}
        <LogTerminal lines={logLines} wsConnected={wsConnected} />

        {/* Cumulative Stats */}
        <CumulativeStats status={status} />
      </div>
    </div>
  )
}
