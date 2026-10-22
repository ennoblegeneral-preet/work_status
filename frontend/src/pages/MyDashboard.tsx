import { useQuery } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, FileText, MessageSquarePlus, Target } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useUser } from '../auth'
import { GoalRow } from '../components/goals'
import { Badge, Card, Empty, PageHeader, Spinner, Stat } from '../components/ui'
import { fmtDay, weekLabel } from '../lib/format'
import type { Goal } from '../types'

interface MeData {
  today: string
  week_start: string
  goals: Goal[]
  summary: { goals: number; completed: number; average_progress: number; at_risk: number }
  submitted_today: boolean
  open_drafts: number
  coverage: { expected_days: number; reported_days: number; missing_dates: string[] }
  recent_logs: { id: number; report_date: string; items: number; total_hours: number | null; blockers: number }[]
  report: { id: number; status: string } | null
}

export default function MyDashboard() {
  const user = useUser()
  const { data, isLoading } = useQuery({ queryKey: ['dashboard', 'me'], queryFn: () => api<MeData>('/dashboard/me') })
  if (isLoading || !data) return <Spinner />
  const s = data.summary

  return (
    <>
      <PageHeader title={`Hi ${user.full_name.split(' ')[0]}`} subtitle={`Week of ${weekLabel(data.week_start)}`} />

      {!data.submitted_today ? (
        <Link
          to="/update"
          className="mb-5 flex items-center gap-3 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-brand-800 transition hover:bg-brand-100"
        >
          <MessageSquarePlus className="h-5 w-5" />
          <div className="flex-1">
            <p className="font-medium">Add today's work update</p>
            <p className="text-sm text-brand-700/80">Paste your status or chat with the assistant - it takes about a minute.</p>
          </div>
          {data.open_drafts > 0 && <Badge>{data.open_drafts} unsaved draft(s)</Badge>}
        </Link>
      ) : (
        <div className="mb-5 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <CheckCircle2 className="h-5 w-5" /> Today's update is in. You can add more if you do more work.
        </div>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Goals this week" value={s.goals} />
        <Stat label="Completed" value={`${s.completed}/${s.goals}`} tone={s.goals && s.completed === s.goals ? 'good' : undefined} />
        <Stat label="Average progress" value={`${Math.round(s.average_progress)}%`} />
        <Stat
          label="Updates this week"
          value={`${data.coverage.reported_days}/${data.coverage.expected_days}`}
          hint={data.coverage.missing_dates.length ? `Missing: ${data.coverage.missing_dates.map((d) => fmtDay(d)).join(', ')}` : 'All caught up'}
          tone={data.coverage.missing_dates.length ? 'warn' : 'good'}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="My weekly goals" actions={<Link className="text-xs text-brand-600 hover:underline" to="/goals">All goals</Link>}>
          {data.goals.length === 0 ? (
            <Empty icon={<Target className="h-8 w-8" />} title="No goals assigned this week">Your manager will assign weekly goals here.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.goals.map((g) => <GoalRow key={g.id} goal={g} />)}
            </ul>
          )}
        </Card>
        <div className="space-y-5">
          <Card title="Recent updates" actions={<Link className="text-xs text-brand-600 hover:underline" to="/history">History</Link>}>
            {data.recent_logs.length === 0 ? (
              <Empty title="No updates yet" />
            ) : (
              <ul className="divide-y divide-slate-100">
                {data.recent_logs.map((l) => (
                  <li key={l.id}>
                    <Link to={`/history?log=${l.id}`} className="flex items-center justify-between px-4 py-2.5 text-sm hover:bg-slate-50">
                      <span className="font-medium text-slate-700">{fmtDay(l.report_date)}</span>
                      <span className="flex items-center gap-2 text-xs text-slate-500">
                        {l.items} item{l.items !== 1 && 's'} · {l.total_hours !== null ? `${l.total_hours} h` : 'hours n/a'}
                        {l.blockers > 0 && <AlertCircle className="h-3.5 w-3.5 text-rose-500" />}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Weekly report">
            <div className="p-4 text-sm">
              {data.report ? (
                <Link to={`/reports/${data.report.id}`} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 hover:bg-slate-50">
                  <span className="flex items-center gap-2"><FileText className="h-4 w-4 text-slate-400" /> This week's report</span>
                  <Badge value={data.report.status} />
                </Link>
              ) : (
                <p className="text-slate-500">
                  Your report is drafted automatically at the end of the week. You can also{' '}
                  <Link to="/reports" className="text-brand-600 hover:underline">generate it now</Link>.
                </p>
              )}
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
