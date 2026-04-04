import type { Page } from '../App'
import {
  Play,
  History,
  BarChart3,
  FolderOpen,
  Zap,
} from 'lucide-react'

const navItems: { key: Page; label: string; icon: typeof Play }[] = [
  { key: 'run', label: 'Run Pipeline', icon: Play },
  { key: 'history', label: 'Run History', icon: History },
  { key: 'analytics', label: 'Analytics', icon: BarChart3 },
  { key: 'artifacts', label: 'Artifacts', icon: FolderOpen },
]

interface SidebarProps {
  currentPage: Page
  onNavigate: (page: Page) => void
  isRunning: boolean
}

export function Sidebar({ currentPage, onNavigate, isRunning }: SidebarProps) {
  return (
    <aside className="w-64 bg-navy-900 text-white flex flex-col shrink-0">
      {/* Brand */}
      <div className="px-5 py-5 flex items-center gap-3 border-b border-white/10">
        <div className="w-9 h-9 rounded-lg bg-accent flex items-center justify-center">
          <Zap className="w-5 h-5 text-white" />
        </div>
        <div>
          <div className="font-semibold text-sm leading-tight">Automation</div>
          <div className="text-xs text-white/60">Accelerator</div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => onNavigate(key)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all
              ${
                currentPage === key
                  ? 'bg-white/15 text-white'
                  : 'text-white/60 hover:text-white hover:bg-white/5'
              }`}
          >
            <Icon className="w-4.5 h-4.5" />
            <span>{label}</span>
            {key === 'run' && isRunning && (
              <span className="ml-auto w-2 h-2 rounded-full bg-accent animate-pulse-dot" />
            )}
          </button>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-white/10">
        <p className="text-[11px] text-white/30 leading-relaxed">
          AI-Driven Test Automation Pipeline
        </p>
      </div>
    </aside>
  )
}
