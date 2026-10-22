import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, qs } from '../api'
import { useAuth, useUser } from '../auth'
import { Alert, Button, Card, ErrorText, Field, PageHeader, Spinner } from '../components/ui'
import { addDays, fmtDay, todayIso, WEEKDAYS } from '../lib/format'
import type { OrgSettings, TimeOff } from '../types'

function OrgSettingsCard() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['settings'], queryFn: () => api<OrgSettings>('/settings') })
  const [f, setF] = useState<OrgSettings | null>(null)
  useEffect(() => {
    if (data) setF(data)
  }, [data])
  const save = useMutation({
    mutationFn: () => {
      const { ai_mode: _ai, ...body } = f!
      void _ai
      return api<OrgSettings>('/settings', { method: 'PATCH', json: body })
    },
    onSuccess: (d) => qc.setQueryData(['settings'], d),
  })
  const run = useMutation({ mutationFn: () => api<Record<string, number>>('/admin/run-automation', { method: 'POST' }) })
  if (!f) return <Spinner />
  const set = (patch: Partial<OrgSettings>) => setF({ ...f, ...patch })
  return (
    <Card title="Organization & reporting schedule">
      <div className="grid gap-4 p-4 sm:grid-cols-2">
        <Field label="Organization name"><input className="input" value={f.org_name} onChange={(e) => set({ org_name: e.target.value })} /></Field>
        <Field label="Time zone" hint="IANA name, e.g. Asia/Kolkata"><input className="input" value={f.timezone} onChange={(e) => set({ timezone: e.target.value })} /></Field>
        <div className="sm:col-span-2">
          <p className="label">Working days</p>
          <div className="flex flex-wrap gap-1.5">
            {WEEKDAYS.map((d, i) => (
              <button
                key={d}
                type="button"
                onClick={() => set({ working_days: f.working_days.includes(i) ? f.working_days.filter((x) => x !== i) : [...f.working_days, i].sort() })}
                className={clsx('rounded-lg border px-3 py-1.5 text-sm', f.working_days.includes(i) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-500')}
              >
                {d}
              </button>
            ))}
          </div>
        </div>
        <Field label="Daily reminder time"><input type="time" className="input" value={f.daily_reminder_time} onChange={(e) => set({ daily_reminder_time: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Weekly report day">
            <select className="input" value={f.report_generation_day} onChange={(e) => set({ report_generation_day: Number(e.target.value) })}>
              {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
          </Field>
          <Field label="at"><input type="time" className="input" value={f.report_generation_time} onChange={(e) => set({ report_generation_time: e.target.value })} /></Field>
        </div>
        <Field label="Minimum daily hours (warning)" hint="Leave empty to disable">
          <input type="number" min={0} max={24} className="input" value={f.min_daily_hours ?? ''} onChange={(e) => set({ min_daily_hours: e.target.value === '' ? null : Number(e.target.value) })} />
        </Field>
        <Field label="Maximum daily hours (warning)">
          <input type="number" min={0} max={24} className="input" value={f.max_daily_hours ?? ''} onChange={(e) => set({ max_daily_hours: e.target.value === '' ? null : Number(e.target.value) })} />
        </Field>
        <div className="space-y-2 sm:col-span-2">
          {([
            ['reminders_enabled', 'Send daily update reminders on working days'],
            ['auto_generate_reports', 'Draft weekly reports automatically on the report day'],
            ['managers_can_assign_goals', 'Managers can assign goals to their team'],
          ] as const).map(([k, l]) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="accent-brand-600" checked={f[k]} onChange={(e) => set({ [k]: e.target.checked } as Partial<OrgSettings>)} />
              {l}
            </label>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 p-4">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Button variant="ghost" size="sm" onClick={() => run.mutate()} loading={run.isPending}>Run reminders & checks now</Button>
          {run.data && <span>{Object.entries(run.data).map(([k, v]) => `${k}: ${v}`).join(' · ')}</span>}
        </div>
        <div className="flex items-center gap-2">
          {save.isSuccess && <span className="text-sm text-emerald-600">Saved</span>}
          <Button onClick={() => save.mutate()} loading={save.isPending}>Save settings</Button>
        </div>
      </div>
      <div className="px-4 pb-4"><ErrorText error={save.error ?? run.error} /></div>
    </Card>
  )
}

function PreferencesCard() {
  const { refresh } = useAuth()
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['prefs'], queryFn: () => api<{ key: string; label: string; enabled: boolean }[]>('/auth/me/preference-options') })
  const save = useMutation({
    mutationFn: (p: Record<string, boolean>) => api('/auth/me/preferences', { method: 'PATCH', json: { notification_prefs: p } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['prefs'] })
      refresh()
    },
  })
  return (
    <Card title="My notifications">
      <div className="space-y-2 p-4">
        {data?.map((p) => (
          <label key={p.key} className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-brand-600" checked={p.enabled} onChange={(e) => save.mutate({ [p.key]: e.target.checked })} />
            {p.label}
          </label>
        ))}
        <p className="pt-1 text-xs text-slate-400">Notifications appear in the bell at the top of the page.</p>
      </div>
    </Card>
  )
}

function TimeOffCard() {
  const user = useUser()
  const qc = useQueryClient()
  const [start, setStart] = useState(todayIso())
  const [end, setEnd] = useState(todayIso())
  const [reason, setReason] = useState('')
  const [holiday, setHoliday] = useState(false)
  const { data = [] } = useQuery({
    queryKey: ['time-off'],
    queryFn: () => api<TimeOff[]>(`/time-off${qs({ start: addDays(todayIso(), -30), user_id: user.role === 'admin' ? undefined : user.id })}`),
  })
  const add = useMutation({
    mutationFn: () => api('/time-off', { method: 'POST', json: { user_id: holiday ? null : user.id, start, end, reason: reason || null } }),
    onSuccess: () => {
      setReason('')
      qc.invalidateQueries({ queryKey: ['time-off'] })
    },
  })
  const remove = useMutation({ mutationFn: (id: number) => api(`/time-off/${id}`, { method: 'DELETE' }), onSuccess: () => qc.invalidateQueries({ queryKey: ['time-off'] }) })
  const shown = data.filter((t) => t.user_id === null || t.user_id === user.id)
  return (
    <Card title="Leave & holidays">
      <div className="space-y-3 p-4">
        <p className="text-xs text-slate-500">Days off are excluded from missing-update checks and reminders.</p>
        <div className="grid grid-cols-2 gap-2">
          <Field label="From"><input type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="To"><input type="date" className="input" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></Field>
        </div>
        <Field label="Reason"><input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional" /></Field>
        {user.role === 'admin' && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-brand-600" checked={holiday} onChange={(e) => setHoliday(e.target.checked)} /> Organization holiday (everyone)
          </label>
        )}
        <ErrorText error={add.error} />
        <Button variant="secondary" onClick={() => add.mutate()} loading={add.isPending}>Add {holiday ? 'holiday' : 'leave'}</Button>
        <ul className="divide-y divide-slate-100 text-sm">
          {shown.map((t) => (
            <li key={t.id} className="flex items-center justify-between py-1.5">
              <span>
                {fmtDay(t.day)} <span className="text-slate-400">· {t.user_id === null ? 'Holiday' : 'My leave'}{t.reason && ` · ${t.reason}`}</span>
              </span>
              {(t.user_id !== null || user.role === 'admin') && (
                <button className="rounded p-1 text-slate-300 hover:text-rose-600" onClick={() => remove.mutate(t.id)} aria-label="Remove"><Trash2 className="h-4 w-4" /></button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}

export default function Settings() {
  const user = useUser()
  const { data } = useQuery({ queryKey: ['settings'], queryFn: () => api<OrgSettings>('/settings') })
  return (
    <>
      <PageHeader title="Settings" />
      {data && (
        <Alert tone={data.ai_mode === 'ai' ? 'success' : 'warning'} className="mb-5">
          <Sparkles className="mr-1 inline h-4 w-4" />
          {data.ai_mode === 'ai'
            ? 'AI is enabled: daily updates are parsed by Claude and weekly reports include AI summaries.'
            : 'AI is not configured. Updates use a basic rule-based parser and reports contain record data only. Set ANTHROPIC_API_KEY on the server to enable AI.'}
        </Alert>
      )}
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">{user.role === 'admin' ? <OrgSettingsCard /> : <PreferencesCard />}</div>
        <div className="space-y-5">
          {user.role === 'admin' && <PreferencesCard />}
          <TimeOffCard />
        </div>
      </div>
    </>
  )
}
