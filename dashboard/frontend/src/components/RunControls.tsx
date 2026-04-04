import { useState, useRef, useCallback, useEffect } from 'react'
import {
  Play,
  Square,
  Trash2,
  Upload,
  ChevronDown,
  ChevronUp,
  Settings,
  Globe,
  Eye,
  EyeOff,
  Zap,
  Pause,
  SkipForward,
} from 'lucide-react'
import { startRun, stopRun, pauseRun, resumeRun, clearOutput, uploadExcel, getInputs, listConfigs } from '../api/client'
import type { InputFile, PipelineConfigSummary } from '../api/types'
import { Toggle } from './Toggle'

interface RunControlsProps {
  isRunning: boolean
  isPaused?: boolean
  addToast: (msg: string, type?: 'info' | 'error') => void
}

export function RunControls({ isRunning, isPaused = false, addToast }: RunControlsProps) {
  const [mode, setMode] = useState('pipeline')
  const [selectedConfig, setSelectedConfig] = useState<string | null>(null)
  const [configs, setConfigs] = useState<PipelineConfigSummary[]>([])
  const [forceScan, setForceScan] = useState(false)
  const [forceRegen, setForceRegen] = useState(false)
  const [showEnv, setShowEnv] = useState(false)
  const [showPasswords, setShowPasswords] = useState(false)
  const [inputs, setInputs] = useState<InputFile[]>([])
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [env, setEnv] = useState({
    BASE_URL: '',
    UI_USERNAME: '',
    UI_PASSWORD: '',
    DOM_BASE_URL: '',
    DOM_USERNAME: '',
    DOM_PASSWORD: '',
  })

  // Load available configs on mount
  useEffect(() => {
    listConfigs()
      .then((res) => setConfigs(res.configs))
      .catch(() => {})
  }, [])

  const loadInputs = useCallback(async () => {
    try {
      const res = await getInputs()
      setInputs(res.files)
    } catch { /* ignore */ }
  }, [])

  const handleStart = async () => {
    try {
      const cleanEnv: Record<string, string> = {}
      for (const [k, v] of Object.entries(env)) {
        if (v.trim()) cleanEnv[k] = v.trim()
      }
      await startRun({
        mode: selectedConfig ? 'pipeline' : mode,
        force: forceRegen,
        scan: forceScan,
        env: cleanEnv,
        config: selectedConfig,
      })
      addToast(`Pipeline started${selectedConfig ? ` (config: ${selectedConfig})` : ''}`)
    } catch (e: unknown) {
      addToast(`Failed to start: ${(e as Error).message}`, 'error')
    }
  }

  const handleStop = async () => {
    try {
      await stopRun()
      addToast('Pipeline stopped')
    } catch (e: unknown) {
      addToast(`Failed to stop: ${(e as Error).message}`, 'error')
    }
  }

  const handlePause = async () => {
    try {
      if (isPaused) {
        await resumeRun()
        addToast('Pipeline resumed')
      } else {
        await pauseRun()
        addToast('Pipeline paused')
      }
    } catch (e: unknown) {
      addToast(`Failed: ${(e as Error).message}`, 'error')
    }
  }

  const handleClear = async () => {
    try {
      const res = await clearOutput()
      addToast(`Cleared: ${res.removed.length} items`)
    } catch (e: unknown) {
      addToast(`Clear failed: ${(e as Error).message}`, 'error')
    }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = async () => {
      const base64 = (reader.result as string).split(',')[1]
      try {
        await uploadExcel(file.name, base64)
        setUploadedFileName(file.name)
        addToast(`Uploaded: ${file.name}`)
        await loadInputs()
      } catch (err: unknown) {
        addToast(`Upload failed: ${(err as Error).message}`, 'error')
      }
    }
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  const activeConfig = configs.find((c) => c.name === selectedConfig)

  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <h3 className="font-semibold text-sm text-navy-700">Run Configuration</h3>
        <div className="flex gap-2">
          <button onClick={handleClear} className="btn btn-ghost text-xs flex items-center gap-1.5" disabled={isRunning}>
            <Trash2 className="w-3.5 h-3.5" />
            Clear Output
          </button>
        </div>
      </div>

      <div className="card-body space-y-4">
        {/* Top row: Config/Mode + Upload + Actions */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Pipeline Config / Mode */}
          <div>
            <label className="block text-xs font-medium text-navy-600 mb-1.5">Pipeline Config</label>
            {configs.length > 0 ? (
              <>
                <select
                  value={selectedConfig || '__legacy__'}
                  onChange={(e) => {
                    const v = e.target.value
                    setSelectedConfig(v === '__legacy__' ? null : v)
                  }}
                  className="select"
                  disabled={isRunning}
                >
                  <option value="__legacy__">Classic Mode</option>
                  {configs.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name} ({c.step_count} steps)
                    </option>
                  ))}
                </select>
                {activeConfig && (
                  <p className="text-[10px] text-navy-400 mt-1">
                    {activeConfig.description}
                  </p>
                )}
                {!selectedConfig && (
                  <>
                    <select
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                      className="select mt-2"
                      disabled={isRunning}
                    >
                      <option value="pipeline">Full Pipeline (Generate + Execute)</option>
                      <option value="generate-only">Generate Only</option>
                      <option value="run-e2e">Execute Tests Only</option>
                    </select>
                    <p className="text-[10px] text-navy-400 mt-1 flex items-center gap-1">
                      <Zap className="w-3 h-3" />
                      Runs main.py directly
                    </p>
                  </>
                )}
              </>
            ) : (
              <>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  className="select"
                  disabled={isRunning}
                >
                  <option value="pipeline">Full Pipeline (Generate + Execute)</option>
                  <option value="generate-only">Generate Only</option>
                  <option value="run-e2e">Execute Tests Only</option>
                </select>
                <p className="text-[10px] text-navy-400 mt-1 flex items-center gap-1">
                  <Zap className="w-3 h-3" />
                  Runs main.py directly
                </p>
              </>
            )}
          </div>

          {/* Upload Excel */}
          <div>
            <label className="block text-xs font-medium text-navy-600 mb-1.5">Upload Excel</label>
            <div
              onClick={() => fileInputRef.current?.click()}
              className={`input flex items-center gap-2 cursor-pointer hover:border-accent transition-colors ${
                uploadedFileName ? 'border-accent/50 bg-accent/5' : ''
              }`}
            >
              <Upload className={`w-4 h-4 ${uploadedFileName ? 'text-accent' : 'text-navy-400'}`} />
              <span className={`text-sm truncate ${uploadedFileName ? 'text-accent font-medium' : 'text-navy-400'}`}>
                {uploadedFileName ? `${uploadedFileName}` : 'Choose .xlsx file...'}
              </span>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls"
              onChange={handleUpload}
              className="hidden"
            />
          </div>

          {/* Action Buttons */}
          <div className="flex items-end gap-2">
            {!isRunning ? (
              <button
                onClick={handleStart}
                className="btn btn-primary flex items-center gap-2 flex-1"
              >
                <Play className="w-4 h-4" />
                Start Pipeline
              </button>
            ) : (
              <>
                <button onClick={handlePause} className="btn btn-ghost flex items-center gap-2 flex-1" title={isPaused ? 'Resume' : 'Pause'}>
                  {isPaused ? <SkipForward className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
                  {isPaused ? 'Resume' : 'Pause'}
                </button>
                <button onClick={handleStop} className="btn btn-danger flex items-center gap-2 flex-1">
                  <Square className="w-4 h-4" />
                  Stop
                </button>
              </>
            )}
          </div>
        </div>

        {/* Toggles */}
        <div className="flex flex-wrap gap-6">
          <Toggle label="Force DOM Scan" checked={forceScan} onChange={setForceScan} disabled={isRunning} />
          <Toggle label="Force Regenerate" checked={forceRegen} onChange={setForceRegen} disabled={isRunning} />
        </div>

        {/* Environment Overrides (collapsible) */}
        <div className="border border-navy-200 rounded-lg">
          <button
            onClick={() => { setShowEnv(!showEnv); if (!showEnv) loadInputs() }}
            className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-navy-600 hover:bg-navy-50 rounded-lg transition-colors"
          >
            <span className="flex items-center gap-2">
              <Settings className="w-4 h-4" />
              Environment Overrides
            </span>
            {showEnv ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {showEnv && (
            <div className="px-4 pb-4 space-y-3 border-t border-navy-100">
              <div className="pt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-navy-500 mb-1">
                    <Globe className="w-3 h-3 inline mr-1" />App URL
                  </label>
                  <input
                    type="url"
                    value={env.BASE_URL}
                    onChange={(e) => setEnv({ ...env, BASE_URL: e.target.value })}
                    className="input"
                    placeholder="https://..."
                    disabled={isRunning}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-navy-500 mb-1">
                    <Globe className="w-3 h-3 inline mr-1" />DOM Scan URL
                  </label>
                  <input
                    type="url"
                    value={env.DOM_BASE_URL}
                    onChange={(e) => setEnv({ ...env, DOM_BASE_URL: e.target.value })}
                    className="input"
                    placeholder="https://..."
                    disabled={isRunning}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-navy-500 mb-1">App Username</label>
                  <input
                    value={env.UI_USERNAME}
                    onChange={(e) => setEnv({ ...env, UI_USERNAME: e.target.value })}
                    className="input"
                    placeholder="Username"
                    disabled={isRunning}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-navy-500 mb-1">DOM Username</label>
                  <input
                    value={env.DOM_USERNAME}
                    onChange={(e) => setEnv({ ...env, DOM_USERNAME: e.target.value })}
                    className="input"
                    placeholder="Username"
                    disabled={isRunning}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-navy-500 mb-1 flex items-center gap-1">
                    App Password
                    <button onClick={() => setShowPasswords(!showPasswords)} className="text-navy-400 hover:text-navy-600">
                      {showPasswords ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                    </button>
                  </label>
                  <input
                    type={showPasswords ? 'text' : 'password'}
                    value={env.UI_PASSWORD}
                    onChange={(e) => setEnv({ ...env, UI_PASSWORD: e.target.value })}
                    className="input"
                    placeholder="Password"
                    disabled={isRunning}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-navy-500 mb-1">DOM Password</label>
                  <input
                    type={showPasswords ? 'text' : 'password'}
                    value={env.DOM_PASSWORD}
                    onChange={(e) => setEnv({ ...env, DOM_PASSWORD: e.target.value })}
                    className="input"
                    placeholder="Password"
                    disabled={isRunning}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
