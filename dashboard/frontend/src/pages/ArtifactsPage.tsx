import { useState, useEffect } from 'react'
import { listFiles, readFile } from '../api/client'
import type { FileEntry } from '../api/types'
import {
  FolderOpen, File, FileCode, FileJson, ChevronRight, ChevronDown,
  Download, Copy, Check,
} from 'lucide-react'

const ROOTS = [
  { key: 'generated', label: 'Generated Features', icon: FileCode },
  { key: 'artifacts', label: 'Artifacts', icon: FolderOpen },
  { key: 'input', label: 'Input Files', icon: File },
]

const LANG_MAP: Record<string, string> = {
  '.feature': 'gherkin',
  '.py': 'python',
  '.json': 'json',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.js': 'javascript',
  '.ts': 'typescript',
  '.html': 'html',
  '.css': 'css',
  '.log': 'log',
}

export function ArtifactsPage() {
  const [selectedRoot, setSelectedRoot] = useState('generated')
  const [files, setFiles] = useState<FileEntry[]>([])
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [fileContent, setFileContent] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    listFiles(selectedRoot)
      .then((res) => setFiles(res.files))
      .catch(() => setFiles([]))
  }, [selectedRoot])

  const handleFileClick = async (path: string) => {
    setSelectedFile(path)
    setLoading(true)
    try {
      const res = await readFile(path)
      setFileContent(res.content)
    } catch {
      setFileContent('Failed to read file')
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(fileContent)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const filesByDir = groupByDirectory(files.filter((f) => !f.is_dir))

  return (
    <div className="animate-fade-in flex gap-4 h-[calc(100vh-8rem)]">
      {/* File Tree */}
      <div className="w-72 shrink-0 card overflow-auto">
        <div className="card-header">
          <h3 className="font-semibold text-sm text-navy-700">File Browser</h3>
        </div>
        <div className="p-2">
          {/* Root selector */}
          <div className="flex flex-wrap gap-1 mb-3 px-2">
            {ROOTS.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => { setSelectedRoot(key); setSelectedFile(null) }}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors
                  ${selectedRoot === key ? 'bg-accent/10 text-accent' : 'text-navy-500 hover:bg-navy-50'}`}
              >
                <Icon className="w-3 h-3" />
                {label}
              </button>
            ))}
          </div>

          {/* File tree */}
          {Object.entries(filesByDir).map(([dir, dirFiles]) => (
            <DirectoryGroup
              key={dir}
              dir={dir}
              files={dirFiles}
              selectedFile={selectedFile}
              onSelect={handleFileClick}
            />
          ))}

          {files.length === 0 && (
            <p className="text-xs text-navy-400 px-3 py-4 text-center">No files found</p>
          )}
        </div>
      </div>

      {/* File Viewer */}
      <div className="flex-1 card flex flex-col overflow-hidden">
        {selectedFile ? (
          <>
            <div className="card-header flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <FileCode className="w-4 h-4 text-navy-500 shrink-0" />
                <span className="text-sm font-medium text-navy-700 truncate">{selectedFile}</span>
              </div>
              <div className="flex gap-1.5">
                <button onClick={handleCopy} className="btn btn-ghost p-1.5" title="Copy">
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-auto bg-navy-900 p-4">
              {loading ? (
                <div className="flex items-center justify-center h-full">
                  <div className="animate-spin w-6 h-6 border-2 border-accent border-t-transparent rounded-full" />
                </div>
              ) : (
                <pre className="font-mono text-xs text-green-300 whitespace-pre-wrap break-all leading-5">
                  {fileContent}
                </pre>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-navy-400">
            <div className="text-center">
              <FolderOpen className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">Select a file to view its contents</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function DirectoryGroup({
  dir,
  files,
  selectedFile,
  onSelect,
}: {
  dir: string
  files: FileEntry[]
  selectedFile: string | null
  onSelect: (path: string) => void
}) {
  const [open, setOpen] = useState(true)

  return (
    <div className="mb-1">
      {dir && (
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-1.5 px-2 py-1 w-full text-xs font-medium text-navy-600 hover:bg-navy-50 rounded"
        >
          {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          <FolderOpen className="w-3 h-3 text-amber-500" />
          {dir}
        </button>
      )}
      {open &&
        files.map((f) => (
          <button
            key={f.path}
            onClick={() => onSelect(f.path)}
            className={`flex items-center gap-2 px-4 py-1 w-full text-xs rounded transition-colors
              ${selectedFile === f.path ? 'bg-accent/10 text-accent' : 'text-navy-600 hover:bg-navy-50'}`}
          >
            <FileIcon ext={f.ext} />
            <span className="truncate">{f.name}</span>
            <span className="ml-auto text-[10px] text-navy-400">{fmtSize(f.size)}</span>
          </button>
        ))}
    </div>
  )
}

function FileIcon({ ext }: { ext: string }) {
  if (ext === '.feature') return <FileCode className="w-3 h-3 text-emerald-500 shrink-0" />
  if (ext === '.json') return <FileJson className="w-3 h-3 text-amber-500 shrink-0" />
  return <File className="w-3 h-3 text-navy-400 shrink-0" />
}

function groupByDirectory(files: FileEntry[]): Record<string, FileEntry[]> {
  const groups: Record<string, FileEntry[]> = {}
  for (const f of files) {
    const parts = f.path.split('/')
    const dir = parts.length > 2 ? parts.slice(1, -1).join('/') : ''
    if (!groups[dir]) groups[dir] = []
    groups[dir].push(f)
  }
  return groups
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}
