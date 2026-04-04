interface ToggleProps {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
}

export function Toggle({ label, checked, onChange, disabled }: ToggleProps) {
  return (
    <label className={`flex items-center gap-2.5 cursor-pointer select-none ${disabled ? 'opacity-50' : ''}`}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative w-10 h-5.5 rounded-full transition-colors duration-200
          ${checked ? 'bg-accent' : 'bg-navy-300'}
          ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}
        `}
        style={{ width: 40, height: 22 }}
        disabled={disabled}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-[18px] h-[18px] rounded-full bg-white shadow transition-transform duration-200
            ${checked ? 'translate-x-[18px]' : 'translate-x-0'}
          `}
        />
      </button>
      <span className="text-sm text-navy-600 font-medium">{label}</span>
    </label>
  )
}
