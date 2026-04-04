import {
  Clock,
  Zap,
  TestTube2,
  CheckCircle2,
  XCircle,
  Brain,
  Database,
  Globe,
  Coins,
  Target,
  Layers,
  type LucideIcon,
} from 'lucide-react'
import type { StatusResponse } from '../api/types'

interface StatCardProps {
  icon: LucideIcon
  label: string
  value: string | number
  sub?: string
  color?: string
}

function StatCard({ icon: Icon, label, value, sub, color = 'text-accent' }: StatCardProps) {
  return (
    <div className="card px-4 py-3 flex items-center gap-3">
      <div className={`w-10 h-10 rounded-lg bg-navy-50 flex items-center justify-center ${color}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <div className="text-lg font-bold text-navy-800 leading-tight">{value}</div>
        <div className="text-xs text-navy-500 truncate">{label}</div>
        {sub && <div className="text-[10px] text-navy-400">{sub}</div>}
      </div>
    </div>
  )
}

interface StatsCardsProps {
  status: StatusResponse | null
  liveStats?: Record<string, unknown> | null
}

export function StatsCards({ status, liveStats }: StatsCardsProps) {
  const state = status?.state
  const latest = status?.latest_run
  const stats = (liveStats as { stats?: Record<string, number> })?.stats || latest?.stats || {}
  const tests = latest?.tests

  // Duration
  let duration = '—'
  if (state?.started_at) {
    const end = state.running ? Date.now() / 1000 : state.finished_at || Date.now() / 1000
    const secs = Math.round(end - state.started_at)
    duration = secs >= 60 ? `${Math.floor(secs / 60)}m ${secs % 60}s` : `${secs}s`
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
      <StatCard icon={Clock} label="Duration" value={duration} color="text-blue-500" />
      <StatCard
        icon={TestTube2}
        label="Tests"
        value={tests ? `${tests.passed}/${tests.total}` : '—'}
        sub={tests ? `${tests.failed} failed` : undefined}
        color="text-purple-500"
      />
      <StatCard
        icon={Coins}
        label="Tokens Used"
        value={fmt(stats.tokens_total)}
        sub={`Saved: ${fmt(stats.tokens_saved_total)}`}
        color="text-amber-500"
      />
      <StatCard icon={Brain} label="RAG Hits" value={fmt(stats.rag_resolutions)} color="text-accent" />
      <StatCard icon={Globe} label="Pages Scanned" value={fmt(stats.pages_scanned)} color="text-indigo-500" />
      <StatCard icon={Database} label="DOM Elements" value={fmt(stats.dom_elements)} color="text-pink-500" />
    </div>
  )
}

interface CumulativeStatsProps {
  status: StatusResponse | null
}

export function CumulativeStats({ status }: CumulativeStatsProps) {
  const cum = status?.cumulative_stats?.cumulative || {}

  return (
    <div className="card">
      <div className="card-header">
        <h3 className="font-semibold text-sm text-navy-700">Cumulative Stats (All Runs)</h3>
      </div>
      <div className="card-body">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MiniStat icon={Layers} label="Total Runs" value={fmt((cum as Record<string, number>).runs)} />
          <MiniStat icon={Coins} label="Tokens Used" value={fmt((cum as Record<string, number>).tokens_total)} />
          <MiniStat icon={Target} label="Tokens Saved" value={fmt((cum as Record<string, number>).tokens_saved_total)} />
          <MiniStat icon={Brain} label="RAG Resolutions" value={fmt((cum as Record<string, number>).rag_resolutions)} />
          <MiniStat icon={Database} label="Cache Hits" value={fmt((cum as Record<string, number>).aoai_cache_hits)} />
          <MiniStat icon={Zap} label="Chat Calls" value={fmt((cum as Record<string, number>).aoai_chat_calls)} />
          <MiniStat icon={Globe} label="Embed Calls" value={fmt((cum as Record<string, number>).aoai_embedding_calls)} />
          <MiniStat icon={CheckCircle2} label="Steps Normalized" value={fmt((cum as Record<string, number>).normalized_steps)} />
        </div>
      </div>
    </div>
  )
}

function MiniStat({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <Icon className="w-4 h-4 text-navy-400 shrink-0" />
      <div>
        <div className="text-sm font-semibold text-navy-800">{value}</div>
        <div className="text-[11px] text-navy-500">{label}</div>
      </div>
    </div>
  )
}

function fmt(val: unknown): string {
  if (val === undefined || val === null) return '—'
  const n = Number(val)
  if (isNaN(n)) return String(val)
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}
