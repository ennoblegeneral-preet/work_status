export function parseDate(d: string): Date {
  // API dates are YYYY-MM-DD (local calendar dates); avoid UTC shifting.
  const [y, m, day] = d.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, day)
}

export function iso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function todayIso(): string {
  return iso(new Date())
}

export function mondayOf(d: string | Date): string {
  const date = typeof d === 'string' ? parseDate(d) : new Date(d)
  const diff = (date.getDay() + 6) % 7
  date.setDate(date.getDate() - diff)
  return iso(date)
}

export function addDays(d: string, n: number): string {
  const date = parseDate(d)
  date.setDate(date.getDate() + n)
  return iso(date)
}

export function fmtDate(d: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' }): string {
  if (!d) return '-'
  return parseDate(d).toLocaleDateString(undefined, opts)
}

export function fmtDay(d: string): string {
  return fmtDate(d, { weekday: 'short', day: 'numeric', month: 'short' })
}

export function fmtDateTime(d: string | null | undefined): string {
  if (!d) return '-'
  return new Date(d).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function weekLabel(weekStart: string): string {
  return `${fmtDate(weekStart)} – ${fmtDate(addDays(weekStart, 6), { day: 'numeric', month: 'short', year: 'numeric' })}`
}

export const STATUS_LABEL: Record<string, string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  blocked: 'Blocked',
  completed: 'Completed',
  deferred: 'Deferred',
  cancelled: 'Cancelled',
  on_track: 'On track',
  at_risk: 'At risk',
  off_track: 'Off track',
  draft: 'Draft',
  submitted: 'Submitted',
  returned: 'Returned',
  approved: 'Approved',
  activity: 'Activity',
  outcome: 'Outcome',
}

export const label = (s: string | null | undefined) => (s ? STATUS_LABEL[s] ?? s.replace(/_/g, ' ') : '-')

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
