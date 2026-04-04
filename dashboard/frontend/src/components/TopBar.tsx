import type { StatusResponse } from '../api/types'
import { Wifi, WifiOff, User } from 'lucide-react'

interface TopBarProps {
  status: StatusResponse | null
  wsConnected: boolean
}

export function TopBar({ status, wsConnected }: TopBarProps) {
  const state = status?.state
  const isRunning = state?.running ?? false

  // Determine overall status from multiple sources
  const latestRun = status?.latest_run
  const testExitCode = latestRun?.tests?.exit_code
  const stateExitCode = state?.exit_code

  // Use test exit code (most reliable) → then state exit code
  const exitCode = testExitCode ?? stateExitCode

  let badgeClass = 'badge-idle'
  let badgeText = 'Idle'

  if (isRunning) {
    badgeClass = 'badge-info'
    badgeText = 'Running'
  } else if (exitCode === 0) {
    badgeClass = 'badge-success'
    badgeText = 'Passed'
  } else if (latestRun && testExitCode === undefined) {
    // Has a latest run but no test results (e.g., generate-only mode)
    badgeClass = 'badge-success'
    badgeText = 'Completed'
  } else if (exitCode !== null && exitCode !== undefined && exitCode !== 0) {
    badgeClass = 'badge-error'
    badgeText = 'Failed'
  }

  return (
    <header className="h-14 bg-white border-b border-navy-200/50 px-6 flex items-center justify-between shrink-0">
      <div className="flex items-center gap-4">
        <h1 className="text-lg font-semibold text-navy-800">
          Dashboard
        </h1>
        <span className={`badge ${badgeClass}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${
            isRunning ? 'bg-blue-500 animate-pulse-dot' :
            exitCode === 0 ? 'bg-emerald-500' :
            (exitCode !== null && exitCode !== undefined && exitCode !== 0) ? 'bg-red-500' : 'bg-gray-400'
          }`} />
          {badgeText}
        </span>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-navy-500">
          {wsConnected ? (
            <>
              <Wifi className="w-3.5 h-3.5 text-accent" />
              <span>Live</span>
            </>
          ) : (
            <>
              <WifiOff className="w-3.5 h-3.5 text-red-400" />
              <span>Polling</span>
            </>
          )}
        </div>

        <div className="w-px h-5 bg-navy-200" />

        <div className="w-8 h-8 rounded-full bg-navy-100 flex items-center justify-center">
          <User className="w-4 h-4 text-navy-500" />
        </div>
      </div>
    </header>
  )
}
