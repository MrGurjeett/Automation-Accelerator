import { useEffect, useRef, useState } from 'react'
import { Terminal, Download, Trash2, ArrowDown, Search } from 'lucide-react'

interface LogTerminalProps {
  lines: string[]
  wsConnected: boolean
}

export function LogTerminal({ lines, wsConnected }: LogTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [showSearch, setShowSearch] = useState(false)

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [lines, autoScroll])

  const handleScroll = () => {
    if (!containerRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 50)
  }

  const handleDownload = () => {
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `pipeline-logs-${new Date().toISOString().slice(0, 19)}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const colorize = (line: string) => {
    if (/error|exception|traceback|failed/i.test(line)) return 'text-red-400'
    if (/warn/i.test(line)) return 'text-yellow-400'
    if (/success|passed|done|complete/i.test(line)) return 'text-emerald-400'
    if (/\[info\]/i.test(line)) return 'text-blue-300'
    if (/^\[exit \d+\]/.test(line)) return line.includes('exit 0') ? 'text-emerald-400' : 'text-red-400'
    return 'text-green-300'
  }

  const filteredLines = searchTerm
    ? lines.filter((l) => l.toLowerCase().includes(searchTerm.toLowerCase()))
    : lines

  return (
    <div className="card flex flex-col">
      <div className="card-header flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-navy-500" />
          <h3 className="font-semibold text-sm text-navy-700">Live Logs</h3>
          <span className={`badge ${wsConnected ? 'badge-success' : 'badge-warning'}`}>
            {wsConnected ? 'Live' : 'Polling'}
          </span>
          <span className="text-xs text-navy-400">{lines.length} lines</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowSearch(!showSearch)}
            className="btn btn-ghost p-1.5"
            title="Search logs"
          >
            <Search className="w-3.5 h-3.5" />
          </button>
          <button onClick={handleDownload} className="btn btn-ghost p-1.5" title="Download logs">
            <Download className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => {
              setAutoScroll(true)
              if (containerRef.current) {
                containerRef.current.scrollTop = containerRef.current.scrollHeight
              }
            }}
            className={`btn btn-ghost p-1.5 ${autoScroll ? 'text-accent' : ''}`}
            title="Auto-scroll"
          >
            <ArrowDown className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {showSearch && (
        <div className="px-4 py-2 border-b border-navy-100">
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="input text-xs"
            placeholder="Filter logs..."
            autoFocus
          />
        </div>
      )}

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto bg-navy-900 rounded-b-xl p-4 font-mono text-xs leading-5 min-h-[300px] max-h-[500px]"
      >
        {filteredLines.length === 0 ? (
          <div className="text-navy-500 text-center py-8">
            No logs yet. Start a pipeline run to see output here.
          </div>
        ) : (
          filteredLines.map((line, i) => (
            <div key={i} className={`whitespace-pre-wrap break-all ${colorize(line)}`}>
              {searchTerm ? highlightMatch(line, searchTerm) : line}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function highlightMatch(text: string, term: string) {
  const idx = text.toLowerCase().indexOf(term.toLowerCase())
  if (idx === -1) return text
  return (
    <>
      {text.slice(0, idx)}
      <span className="bg-yellow-500/30 text-yellow-200 rounded px-0.5">{text.slice(idx, idx + term.length)}</span>
      {text.slice(idx + term.length)}
    </>
  )
}
