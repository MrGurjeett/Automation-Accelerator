export interface RunState {
  running: boolean
  mode: string
  started_at: number
  finished_at: number
  command: string[] | null
  exit_code: number | null
  pid: number | null
  error: string | null
  trace_id: string
  run_id: string
  paused: boolean
  step_durations: Record<string, number>
  duration_ms: number
}

export interface StatsData {
  dom_elements: number
  pages_scanned: number
  raw_steps_converted: number
  normalized_steps: number
  rag_resolutions: number
  locator_healing: number
  aoai_chat_calls: number
  aoai_embedding_calls: number
  aoai_cache_hits: number
  tokens_prompt: number
  tokens_completion: number
  tokens_total: number
  tokens_saved_total: number
}

export interface LatestStats {
  updated_at: number
  stats: Partial<StatsData>
}

export interface TestResults {
  exit_code: number
  passed: number
  failed: number
  errors?: number
  total: number
}

export interface LatestRun {
  completed_at: string
  trace_id: string
  mode: string
  regenerated: boolean
  excel: string
  feature: string
  version_folder: string
  tests: TestResults
  stats: Partial<StatsData>
  cumulative: Partial<StatsData & { runs: number }>
}

export interface CumulativeStats {
  updated_at: string
  cumulative: Partial<StatsData & { runs: number }>
}

export interface StatusResponse {
  state: RunState
  ui_state: Record<string, unknown>
  latest_run: LatestRun | null
  latest_stats: LatestStats | null
  cumulative_stats: CumulativeStats | null
}

export interface ProgressStep {
  key: string
  label: string
  status: 'pending' | 'active' | 'done' | 'error' | 'skipped' | 'paused'
  duration_ms?: number
}

export interface PipelineConfigSummary {
  name: string
  description: string
  step_count: number
  steps: Array<{ key: string; label: string }>
  is_builtin: boolean
  path: string
}

export interface ProgressResponse {
  steps: ProgressStep[]
  running: boolean
  mode: string
  trace_id?: string
  run_id?: string
  source?: 'events' | 'logs'
}

export interface InputFile {
  name: string
  path: string
  is_raw: boolean
  size: number
}

export interface FileEntry {
  name: string
  path: string
  size: number
  is_dir: boolean
  ext: string
}

export interface RunHistoryEntry {
  folder: string
  path: string
  summary: LatestRun | null
}

export interface DbRun {
  id: string
  trace_id: string
  run_id: string
  started_at: string
  completed_at: string
  mode: string
  excel_path: string
  feature_path: string
  version_folder: string
  exit_code: number | null
  passed: number
  failed: number
  errors: number
  total: number
  regenerated: number
  duration_s: number
  duration_ms: number
  stats: Partial<StatsData>
  cumulative: Partial<StatsData & { runs: number }>
  stage_timings: Array<{ stage: string; duration_s: number; status: string }>
  step_durations: Record<string, number>
}

export interface AnalyticsResponse {
  runs: DbRun[]
  summary: {
    total_runs: number
    avg_duration: number
    total_passed: number
    total_failed: number
    total_tests: number
    success_rate: number
  }
}

export interface WsEvent {
  type: 'log' | 'stats' | 'status' | 'run_complete' | 'heartbeat' | 'pipeline_event'
  line?: string
  data?: Record<string, unknown>
}

export interface PipelineEventData {
  event_type: string
  trace_id: string
  run_id: string
  step_name: string
  stage: string
  status: string
  metadata: Record<string, unknown>
  timestamp: string
  duration_ms?: number
}
