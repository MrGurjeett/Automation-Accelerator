import { X } from 'lucide-react'

export interface ToastItem {
  id: number
  message: string
  type: 'info' | 'error'
}

interface ToastProps {
  toasts: ToastItem[]
  onRemove: (id: number) => void
}

export function Toast({ toasts, onRemove }: ToastProps) {
  if (toasts.length === 0) return null

  return (
    <div className="fixed top-4 right-4 z-50 space-y-2 max-w-sm">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`animate-fade-in flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg text-sm ${
            toast.type === 'error'
              ? 'bg-red-600 text-white'
              : 'bg-navy-800 text-white'
          }`}
        >
          <span className="flex-1">{toast.message}</span>
          <button
            onClick={() => onRemove(toast.id)}
            className="text-white/60 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  )
}
