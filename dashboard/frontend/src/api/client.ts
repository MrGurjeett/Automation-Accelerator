import type {
  StatusResponse,
  ProgressResponse,
  InputFile,
  FileEntry,
  RunHistoryEntry,
  AnalyticsResponse,
  DbRun,
  PipelineConfigSummary,
} from './types'

const BASE = ''  // Proxied by Vite in dev, same-origin in prod

async function apiJson<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ─── Status ──────────────────────────────────────────
export const getStatus = () => apiJson<StatusResponse>('/api/status')
export const getProgress = () => apiJson<ProgressResponse>('/api/progress')
export const getLogs = (lines = 200) => apiJson<{ lines: string[] }>(`/api/logs?lines=${lines}`)
export const getInputs = () => apiJson<{ files: InputFile[] }>('/api/inputs')

// ─── Run Control ─────────────────────────────────────
export const startRun = (body: {
  mode: string
  force: boolean
  scan: boolean
  env: Record<string, string>
  config?: string | null
}) =>
  apiJson<{ ok: boolean; state: unknown }>('/api/run', {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const stopRun = () =>
  apiJson<{ ok: boolean }>('/api/stop', { method: 'POST' })

export const pauseRun = () =>
  apiJson<{ ok: boolean }>('/api/pause', { method: 'POST' })

export const resumeRun = () =>
  apiJson<{ ok: boolean }>('/api/resume', { method: 'POST' })

// ─── Pipeline Configs ───────────────────────────────
export const listConfigs = () =>
  apiJson<{ configs: PipelineConfigSummary[] }>('/api/configs')

export const clearOutput = () =>
  apiJson<{ ok: boolean; removed: string[] }>('/api/clear_output', { method: 'POST' })

export const uploadExcel = (filename: string, content_base64: string) =>
  apiJson<{ ok: boolean; path: string }>('/api/upload_excel', {
    method: 'POST',
    body: JSON.stringify({ filename, content_base64 }),
  })

// ─── Files ───────────────────────────────────────────
export const listFiles = (root: string) =>
  apiJson<{ files: FileEntry[]; root: string }>(`/api/files?root=${root}`)

export const readFile = (path: string) =>
  apiJson<{ path: string; content: string; mime: string; ext: string }>(`/api/file?path=${encodeURIComponent(path)}`)

// ─── History & Analytics ─────────────────────────────
export const listRuns = () => apiJson<{ runs: RunHistoryEntry[] }>('/api/runs')
export const listRunsDb = (limit = 100) => apiJson<{ runs: DbRun[] }>(`/api/runs/db?limit=${limit}`)
export const getAnalytics = () => apiJson<AnalyticsResponse>('/api/analytics')

// ─── Live Logs ──────────────────────────────────────
export const getLiveLogs = (since = 0) =>
  apiJson<{ events: Array<{ type: string; line?: string; data?: Record<string, unknown> }>; total: number; next_since: number }>(
    `/api/live-logs?since=${since}`
  )

export const clearLiveLogs = () =>
  apiJson<{ ok: boolean }>('/api/live-logs/clear', { method: 'POST' })
