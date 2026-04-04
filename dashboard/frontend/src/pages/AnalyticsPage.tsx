import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line, Area, AreaChart,
} from 'recharts'
import { getAnalytics } from '../api/client'
import type { AnalyticsResponse, StatusResponse } from '../api/types'
import {
  BarChart3, TrendingUp, Target, Clock, CheckCircle2, XCircle,
  Layers, Coins,
} from 'lucide-react'

const COLORS = {
  passed: '#10b981',
  failed: '#ef4444',
  tokens: '#14b8a6',
  saved: '#8b5cf6',
  accent: '#3b82f6',
}

interface AnalyticsPageProps {
  status: StatusResponse | null
}

export function AnalyticsPage({ status }: AnalyticsPageProps) {
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getAnalytics()
      .then(setAnalytics)
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

  const summary = analytics?.summary
  const runs = (analytics?.runs || []).slice().reverse()

  // Chart data: token usage per run
  const tokenData = runs.map((r, i) => ({
    name: `Run ${i + 1}`,
    used: r.stats?.tokens_total || 0,
    saved: r.stats?.tokens_saved_total || 0,
  }))

  // Chart data: test results per run
  const testData = runs.map((r, i) => ({
    name: `Run ${i + 1}`,
    passed: r.passed || 0,
    failed: r.failed || 0,
  }))

  // Chart data: duration per run
  const durationData = runs.map((r, i) => ({
    name: `Run ${i + 1}`,
    duration: Math.round(r.duration_s || 0),
  }))

  // Pie chart: overall pass/fail
  const totalPassed = summary?.total_passed || 0
  const totalFailed = summary?.total_failed || 0
  const pieData = [
    { name: 'Passed', value: totalPassed },
    { name: 'Failed', value: totalFailed },
  ].filter((d) => d.value > 0)

  // Cumulative from status
  const cum = (status?.cumulative_stats?.cumulative || {}) as Record<string, number>

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryCard
          icon={Layers}
          label="Total Runs"
          value={summary?.total_runs || cum.runs || 0}
          color="bg-blue-50 text-blue-600"
        />
        <SummaryCard
          icon={Target}
          label="Success Rate"
          value={`${summary?.success_rate || 0}%`}
          color="bg-emerald-50 text-emerald-600"
        />
        <SummaryCard
          icon={Clock}
          label="Avg Duration"
          value={`${Math.round(summary?.avg_duration || 0)}s`}
          color="bg-amber-50 text-amber-600"
        />
        <SummaryCard
          icon={Coins}
          label="Total Tokens"
          value={fmtNum(cum.tokens_total || 0)}
          sub={`Saved: ${fmtNum(cum.tokens_saved_total || 0)}`}
          color="bg-purple-50 text-purple-600"
        />
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Token Usage Chart */}
        <div className="card">
          <div className="card-header flex items-center gap-2">
            <Coins className="w-4 h-4 text-navy-500" />
            <h3 className="font-semibold text-sm text-navy-700">Token Usage per Run</h3>
          </div>
          <div className="card-body h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={tokenData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="used" fill={COLORS.tokens} name="Tokens Used" radius={[4, 4, 0, 0]} />
                <Bar dataKey="saved" fill={COLORS.saved} name="Tokens Saved" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Test Results Chart */}
        <div className="card">
          <div className="card-header flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-navy-500" />
            <h3 className="font-semibold text-sm text-navy-700">Test Results per Run</h3>
          </div>
          <div className="card-body h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={testData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="passed" fill={COLORS.passed} name="Passed" stackId="a" radius={[4, 4, 0, 0]} />
                <Bar dataKey="failed" fill={COLORS.failed} name="Failed" stackId="a" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Duration Trend */}
        <div className="card">
          <div className="card-header flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-navy-500" />
            <h3 className="font-semibold text-sm text-navy-700">Run Duration Trend</h3>
          </div>
          <div className="card-body h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={durationData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="s" />
                <Tooltip
                  contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
                  formatter={(val: number) => [`${val}s`, 'Duration']}
                />
                <Area
                  type="monotone"
                  dataKey="duration"
                  stroke={COLORS.accent}
                  fill={COLORS.accent}
                  fillOpacity={0.1}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Pass/Fail Pie */}
        <div className="card">
          <div className="card-header flex items-center gap-2">
            <Target className="w-4 h-4 text-navy-500" />
            <h3 className="font-semibold text-sm text-navy-700">Overall Pass/Fail Ratio</h3>
          </div>
          <div className="card-body h-72 flex items-center justify-center">
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={3}
                    dataKey="value"
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  >
                    <Cell fill={COLORS.passed} />
                    <Cell fill={COLORS.failed} />
                  </Pie>
                  <Tooltip
                    contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-navy-400 text-sm">No test data available</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: typeof Layers
  label: string
  value: string | number
  sub?: string
  color: string
}) {
  return (
    <div className="card px-5 py-4">
      <div className="flex items-center gap-3">
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div>
          <div className="text-2xl font-bold text-navy-800">{value}</div>
          <div className="text-xs text-navy-500">{label}</div>
          {sub && <div className="text-[10px] text-navy-400 mt-0.5">{sub}</div>}
        </div>
      </div>
    </div>
  )
}

function fmtNum(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}
