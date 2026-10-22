import { ChevronLeft, ChevronRight } from 'lucide-react'
import { addDays, mondayOf, todayIso, weekLabel } from '../lib/format'

export function WeekPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const current = mondayOf(todayIso())
  return (
    <div className="flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-1 shadow-sm">
      <button className="rounded p-1.5 text-slate-500 hover:bg-slate-100" onClick={() => onChange(addDays(value, -7))} aria-label="Previous week">
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="min-w-40 text-center text-sm font-medium text-slate-700">{weekLabel(value)}</span>
      <button
        className="rounded p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30"
        onClick={() => onChange(addDays(value, 7))}
        disabled={value >= addDays(current, 7)}
        aria-label="Next week"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )
}
