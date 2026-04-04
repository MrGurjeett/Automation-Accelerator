import { useEffect, useState } from 'react'
import { listRuns } from '../api/client'
import type { RunHistoryEntry, LatestRun } from '../api/types'
import {
  History, Clock, CheckCircle2, XCircle, AlertTriangle,
  ChevronRight, Calendar, FileCode,
} from 'lucide-react'

export function HistoryPage() {
  const [runs, setRuns] = useState<RunHistoryEntry[]>([])
  const [selected, setSelected] = useState<RunHistoryEntry | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listRuns()
      .then((res) => setRuns(res.runs))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-accent border-t-transparent rounded-full" />
      </div>
    )
  }

  return (
    <div className="animate-fade-in flex gap-4 h-[calc(100vh-8rem)]">
      {/* Runs List */}
      <div className="w-96 shrink-0 card overflow-auto">
        <div className="card-header flex items-center gap-2">
          <History className="w-4 h-4 text-navy-500" />
          <h3 className="font-semibold text-sm text-navy-700">Run History</h3>
          <span className="badge badge-info ml-auto">{runs.length} runs</span>
        </div>
        <div className="divide-y divide-navy-100">
          {runs.length === 0 ? (
            <p className="text-sm text-navy-400 px-4 py-8 text-center">No runs found</p>
          ) : (
            runs.map((run) => (
              <RunListItem
                key={run.folder}
                run={run}
                isSelected={selected?.folder === run.folder}
                onClick={() => setSelected(run)}
              />
            ))
          )}
        </div>
      </div>

      {/* Run Detail */}
      <div className="flex-1 card overflow-auto">
        {selected?.summary ? (
          <RunDetail summary={selected.summary} folder={selected.folder} />
        ) : (
          <div className="flex-1 flex items-center justify-center h-full text-navy-400">
            <div className="text-center">
              <History className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">Select a run to view details</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function RunListItem({
  run,
  isSelected,
  onClick,
}: {
  run: RunHistoryEntry
  isSelected: boolean
  onClick: () => void
}) {
  const summary = run.summary
  const tests = summary?.tests
  const isPass = tests?.exit_code === 0
  const isFail = tests?.exit_code !== undefined && tests.exit_code !== null && tests.exit_code !== 0

  return (
    <button
      onClick={onClick}
      className={`w-full px-4 py-3 text-left hover:bg-navy-50 transition-colors flex items-center gap-3
        ${isSelected ? 'bg-accent/5 border-l-2 border-accent' : ''}`}
    >
      <div className="shrink-0">
        {isPass ? (
          <CheckCircle2 className="w-5 h-5 text-emerald-500" />
        ) : isFail ? (
          <XCircle className="w-5 h-5 text-red-500" />
        ) : (
          <AlertTriangle className="w-5 h-5 text-amber-500" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-navy-700 truncate">
          {summary?.mode || 'pipeline'} run
        </div>
        <div className="flex items-center gap-2 text-[11px] text-navy-400 mt-0.5">
          <Calendar className="w-3 h-3" />
          {summary?.completed_at || run.folder}
        </div>
        {tests && (
          <div className="flex items-center gap-2 mt-1">
            <span className="badge badge-success text-[10px]">{tests.passed} passed</span>
            {tests.failed > 0 && (
              <span className="badge badge-error text-[10px]">{tests.failed} failed</span>
            )}
          </div>
        )}
      </div>
      <ChevronRight className="w-4 h-4 text-navy-300 shrink-0" />
    </button>
  )
}

function RunDetail({ summary, folder }: { summary: LatestRun; folder: string }) {
  const tests = summary.tests
  const stats = summary.stats || {}

  return (
    <div>
      <div className="card-header flex items-center justify-between">
        <h3 className="font-semibold text-sm text-navy-700">Run Details</h3>
        <span className={`badge ${tests?.exit_code === 0 ? 'badge-success' : 'badge-error'}`}>
          Exit Code: {tests?.exit_code ?? '?'}
        </span>
      </div>
      <div className="card-body space-y-6">
        {/* Overview */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <DetailItem label="Completed" value={summary.completed_at} />
          <DetailItem label="Mode" value={summary.mode} />
          <DetailItem label="Regenerated" value={summary.regenerated ? 'Yes' : 'No'} />
          <DetailItem label="Folder" value={folder} />
        </div>

        {/* Test Results */}
        {tests && (
          <div>
            <h4 className="text-xs font-semibold text-navy-600 uppercase tracking-wider mb-3">Test Results</h4>
            <div className="grid grid-cols-4 gap-3">
              <div className="bg-emerald-50 rounded-lg px-4 py-3 text-center">
                <div className="text-2xl font-bold text-emerald-600">{tests.passed}</div>
                <div className="text-xs text-emerald-600">Passed</div>
              </div>
              <div className="bg-red-50 rounded-lg px-4 py-3 text-center">
                <div className="text-2xl font-bold text-red-600">{tests.failed}</div>
                <div className="text-xs text-red-600">Failed</div>
              </div>
              <div className="bg-amber-50 rounded-lg px-4 py-3 text-center">
                <div className="text-2xl font-bold text-amber-600">{tests.errors || 0}</div>
                <div className="text-xs text-amber-600">Errors</div>
              </div>
              <div className="bg-blue-50 rounded-lg px-4 py-3 text-center">
                <div className="text-2xl font-bold text-blue-600">{tests.total}</div>
                <div className="text-xs text-blue-600">Total</div>
              </div>
            </div>
          </div>
        )}

        {/* Stats */}
        <div>
          <h4 className="text-xs font-semibold text-navy-600 uppercase tracking-wider mb-3">Run Stats</h4>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.entries(stats).map(([key, val]) => (
              <div key={key} className="flex justify-between px-3 py-2 bg-navy-50 rounded-lg">
                <span className="text-xs text-navy-600">{formatKey(key)}</span>
                <span className="text-xs font-semibold text-navy-800">{String(val)}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Files */}
        {summary.feature && (
          <div>
            <h4 className="text-xs font-semibold text-navy-600 uppercase tracking-wider mb-2">Files</h4>
            <div className="flex items-center gap-2 text-sm text-navy-600">
              <FileCode className="w-4 h-4" />
              {summary.feature}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-navy-400 font-medium">{label}</div>
      <div className="text-sm text-navy-700 mt-0.5 truncate">{value}</div>
    </div>
  )
}

function formatKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
