import type { ProgressStep } from '../api/types'
import {
  Upload,
  ShieldCheck,
  Globe,
  Brain,
  FileCode,
  PlayCircle,
  CheckCircle2,
  XCircle,
  Loader2,
  Circle,
} from 'lucide-react'

const stepIcons: Record<string, typeof Upload> = {
  detect_excel: Upload,
  read_excel: Upload,
  validate: ShieldCheck,
  init_dom: Globe,
  normalize: Brain,
  generate: FileCode,
  execute: PlayCircle,
}

const statusConfig = {
  done: {
    color: 'text-emerald-600',
    bg: 'bg-emerald-50',
    border: 'border-emerald-400',
    lineColor: 'bg-emerald-400',
    labelColor: 'text-emerald-700 font-semibold',
    Icon: CheckCircle2,
  },
  active: {
    color: 'text-blue-600',
    bg: 'bg-blue-50',
    border: 'border-blue-400',
    lineColor: 'bg-blue-300',
    labelColor: 'text-blue-700 font-semibold',
    Icon: Loader2,
  },
  error: {
    color: 'text-red-600',
    bg: 'bg-red-50',
    border: 'border-red-400',
    lineColor: 'bg-red-300',
    labelColor: 'text-red-700 font-semibold',
    Icon: XCircle,
  },
  skipped: {
    color: 'text-amber-500',
    bg: 'bg-amber-50',
    border: 'border-amber-300',
    lineColor: 'bg-amber-300',
    labelColor: 'text-amber-600',
    Icon: Circle,
  },
  paused: {
    color: 'text-orange-500',
    bg: 'bg-orange-50',
    border: 'border-orange-400',
    lineColor: 'bg-orange-300',
    labelColor: 'text-orange-600 font-semibold',
    Icon: Loader2,
  },
  pending: {
    color: 'text-navy-300',
    bg: 'bg-gray-50',
    border: 'border-gray-200',
    lineColor: 'bg-gray-200',
    labelColor: 'text-navy-400',
    Icon: Circle,
  },
}

interface PipelineStepperProps {
  steps: ProgressStep[]
}

export function PipelineStepper({ steps }: PipelineStepperProps) {
  return (
    <div className="card">
      <div className="card-body py-3 px-4">
        <div className="flex items-center justify-between">
          {steps.map((step, i) => {
            const config = statusConfig[step.status]
            const StepIcon = stepIcons[step.key] || Circle
            const StatusIcon = config.Icon
            const isActive = step.status === 'active'
            const isDone = step.status === 'done'
            const isError = step.status === 'error'

            return (
              <div key={step.key} className="flex items-center flex-1 last:flex-none">
                {/* Step */}
                <div className="flex flex-col items-center gap-1">
                  <div
                    className={`relative w-9 h-9 rounded-lg border-2 flex items-center justify-center
                      transition-all duration-500 ease-in-out
                      ${config.bg} ${config.border}
                      ${isActive ? 'shadow-md shadow-blue-200 scale-105' : ''}
                      ${isDone ? 'shadow-sm shadow-emerald-100' : ''}
                      ${isError ? 'shadow-sm shadow-red-100' : ''}
                    `}
                  >
                    {isActive && (
                      <div className="absolute inset-0 rounded-lg border-2 border-blue-400 animate-ping opacity-30" />
                    )}

                    <StepIcon className={`w-4 h-4 ${config.color} transition-colors duration-300`} />

                    <div className={`absolute -top-1 -right-1 rounded-full p-px
                      ${isDone ? 'bg-emerald-500' : isActive ? 'bg-blue-500' : isError ? 'bg-red-500' : 'bg-gray-300'}
                    `}>
                      <StatusIcon
                        className={`w-2.5 h-2.5 text-white ${isActive ? 'animate-spin' : ''}`}
                      />
                    </div>
                  </div>

                  <span className={`text-[10px] text-center max-w-[80px] leading-tight transition-colors duration-300 ${config.labelColor}`}>
                    {step.label}
                  </span>
                  {isDone && step.duration_ms != null && (
                    <span className="text-[9px] text-emerald-500 font-mono">
                      {step.duration_ms < 1000
                        ? `${step.duration_ms}ms`
                        : `${(step.duration_ms / 1000).toFixed(1)}s`}
                    </span>
                  )}
                </div>

                {/* Connector line */}
                {i < steps.length - 1 && (
                  <div className="flex-1 mx-2 mt-[-16px]">
                    <div className="relative h-0.5 w-full rounded-full bg-gray-100 overflow-hidden">
                      <div
                        className={`absolute left-0 top-0 h-full rounded-full transition-all duration-700 ease-in-out
                          ${isDone ? 'w-full bg-emerald-400' :
                            isActive ? 'w-1/2 bg-blue-400 animate-pulse' :
                            'w-0 bg-gray-200'}
                        `}
                      />
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
