import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Users } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, qs } from '../api'
import { GoalRow } from '../components/goals'
import { Badge, Button, Card, Empty, PageHeader, Spinner, Stat, Table, Tabs, td, th } from '../components/ui'
import { fmtDate, fmtDay, mondayOf, todayIso } from '../lib/format'
import { WeekPicker } from '../components/WeekPicker'
import type { Goal, Team } from '../types'

interface Overview {
  week_start: string
  cards: {
    total_employees: number
    active_goals: number
    completed_goals: number
    in_progress_goals: number
    blocked_or_overdue: number
    submission_rate: number | null
    reports_pending_review: number
  }
  team_overview: {
    employee_id: number
    name: string
    department: string | null
    teams: string[]
    goals_assigned: number
    goals_completed: number
    pending_tasks: number
    blocked_items: number
    average_progress: number | null
    latest_update: string | null
    submitted_today: boolean
    missing_dates: string[]
  }[]
  goals: Goal[]
  missing_updates: { employee_id: number; name: string; missing_dates: string[]; expected_days: number; reported_days: number }[]
  blockers: { employee_id: number; name: string; date: string; text: string; log_id: number }[]
}

interface Analytics {
  weeks: { week_start: string; goals: number; completed: number; completion_rate: number | null; average_progress: number | null; submission_rate: number | null }[]
  recurring_blockers: { text: string; count: number; employees: string[]; last_seen: string }[]
  overdue_goals: Goal[]
  workload: { employee_id: number; name: string; work_items: number; reported_hours: number; open_tasks: number }[]
}

function OverviewTab({ week, teamId }: { week: string; teamId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['overview', week, teamId],
    queryFn: () => api<Overview>(`/dashboard/overview${qs({ week_start: week, team_id: teamId })}`),
  })
  const [goalFilter, setGoalFilter] = useState<'all' | 'attention'>('attention')
  if (isLoading || !data) return <Spinner />
  const c = data.cards
  const attention = data.goals.filter((g) => g.status === 'blocked' || ['at_risk', 'off_track'].includes(g.health))
  const shownGoals = goalFilter === 'all' ? data.goals : attention

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <Stat label="Employees" value={c.total_employees} />
        <Stat label="Active goals" value={c.active_goals} />
        <Stat label="Completed" value={c.completed_goals} tone="good" />
        <Stat label="In progress" value={c.in_progress_goals} />
        <Stat label="Blocked / overdue" value={c.blocked_or_overdue} tone={c.blocked_or_overdue ? 'bad' : undefined} />
        <Stat label="Update rate" value={c.submission_rate === null ? '-' : `${c.submission_rate}%`} hint="Working days so far" tone={c.submission_rate !== null && c.submission_rate < 80 ? 'warn' : undefined} />
        <Stat label="Reports to review" value={<Link to="/reports?status=submitted" className="hover:underline">{c.reports_pending_review}</Link>} tone={c.reports_pending_review ? 'warn' : undefined} />
      </div>

      <Card title="Team overview">
        {data.team_overview.length === 0 ? (
          <Empty icon={<Users className="h-8 w-8" />} title="No team members yet" />
        ) : (
          <Table>
            <thead className="bg-slate-50">
              <tr>
                <th className={th}>Employee</th>
                <th className={th}>Goals</th>
                <th className={th}>Progress</th>
                <th className={th}>Pending tasks</th>
                <th className={th}>Blocked</th>
                <th className={th}>Latest update</th>
                <th className={th}>Missing</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.team_overview.map((r) => (
                <tr key={r.employee_id} className="hover:bg-slate-50">
                  <td className={td}>
                    <Link to={`/history?employee=${r.employee_id}`} className="font-medium text-slate-800 hover:text-brand-600">{r.name}</Link>
                    <p className="text-xs text-slate-400">{r.teams.join(', ') || r.department}</p>
                  </td>
                  <td className={td}>{r.goals_completed}/{r.goals_assigned}</td>
                  <td className={td}>{r.average_progress === null ? '-' : `${Math.round(r.average_progress)}%`}</td>
                  <td className={td}>{r.pending_tasks}</td>
                  <td className={td}>{r.blocked_items ? <Badge value="blocked">{r.blocked_items}</Badge> : '0'}</td>
                  <td className={td}>
                    {r.latest_update ? fmtDay(r.latest_update) : <span className="text-slate-400">never</span>}
                    {r.submitted_today && <Badge value="completed" className="ml-2">today</Badge>}
                  </td>
                  <td className={td}>
                    {r.missing_dates.length ? (
                      <span className="text-amber-700" title={r.missing_dates.map(fmtDay).join(', ')}>{r.missing_dates.length} day(s)</span>
                    ) : (
                      <span className="text-slate-400">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Weekly goal tracking"
          actions={
            <Tabs
              value={goalFilter}
              onChange={setGoalFilter}
              tabs={[
                { value: 'attention', label: `Needs attention (${attention.length})` },
                { value: 'all', label: `All (${data.goals.length})` },
              ]}
            />
          }
        >
          {shownGoals.length === 0 ? (
            <Empty title={goalFilter === 'attention' ? 'Nothing needs attention' : 'No goals this week'} />
          ) : (
            <ul className="max-h-[32rem] divide-y divide-slate-100 overflow-y-auto">
              {shownGoals.map((g) => <GoalRow key={g.id} goal={g} showOwner />)}
            </ul>
          )}
        </Card>
        <div className="space-y-5">
          <Card title="Missing updates">
            {data.missing_updates.length === 0 ? (
              <Empty title="Everyone is up to date" />
            ) : (
              <ul className="divide-y divide-slate-100 text-sm">
                {data.missing_updates.map((m) => (
                  <li key={m.employee_id} className="px-4 py-2.5">
                    <p className="font-medium text-slate-700">{m.name}</p>
                    <p className="text-xs text-slate-500">
                      {m.reported_days}/{m.expected_days} days · missing {m.missing_dates.map((d) => fmtDate(d, { weekday: 'short' })).join(', ')}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">Excludes weekends, holidays and leave. A gap is missing data, not a performance signal.</p>
          </Card>
          <Card title="Blockers this week">
            {data.blockers.length === 0 ? (
              <Empty title="No blockers reported" />
            ) : (
              <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto text-sm">
                {data.blockers.map((b, i) => (
                  <li key={i} className="flex gap-2 px-4 py-2.5">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
                    <div>
                      <p className="text-slate-700">{b.text}</p>
                      <p className="text-xs text-slate-400">{b.name} · {fmtDay(b.date)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function AnalyticsTab({ teamId }: { teamId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['analytics', teamId],
    queryFn: () => api<Analytics>(`/dashboard/analytics${qs({ weeks: 8, team_id: teamId })}`),
  })
  if (isLoading || !data) return <Spinner />
  const weeks = data.weeks.map((w) => ({ ...w, label: fmtDate(w.week_start) }))
  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Goal completion trend">
          <div className="h-64 p-4">
            <ResponsiveContainer>
              <BarChart data={weeks}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="goals" name="Goals" fill="#c7d2fe" radius={[4, 4, 0, 0]} />
                <Bar dataKey="completed" name="Completed" fill="#4f46e5" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Average progress & update rate (%)">
          <div className="h-64 p-4">
            <ResponsiveContainer>
              <LineChart data={weeks}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="average_progress" name="Avg progress" stroke="#4f46e5" strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="submission_rate" name="Update rate" stroke="#10b981" strokeWidth={2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Recurring blockers">
          {data.recurring_blockers.length === 0 ? (
            <Empty title="No recurring blockers" />
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {data.recurring_blockers.map((b, i) => (
                <li key={i} className="px-4 py-2.5">
                  <p className="text-slate-700">{b.text}</p>
                  <p className="text-xs text-slate-400">
                    {b.count}× · {b.employees.join(', ')} · last {fmtDay(b.last_seen)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Overdue deliverables">
          {data.overdue_goals.length === 0 ? (
            <Empty title="Nothing overdue" />
          ) : (
            <ul className="divide-y divide-slate-100">{data.overdue_goals.map((g) => <GoalRow key={g.id} goal={g} showOwner />)}</ul>
          )}
        </Card>
        <Card title="Workload (8 weeks)">
          <Table>
            <thead className="bg-slate-50">
              <tr>
                <th className={th}>Employee</th>
                <th className={th}>Items</th>
                <th className={th}>Hours</th>
                <th className={th}>Open</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.workload.map((w) => (
                <tr key={w.employee_id}>
                  <td className={td}>{w.name}</td>
                  <td className={td}>{w.work_items}</td>
                  <td className={td}>{w.reported_hours}</td>
                  <td className={td}>{w.open_tasks}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </div>
    </div>
  )
}

export default function TeamDashboard() {
  const [week, setWeek] = useState(mondayOf(todayIso()))
  const [teamId, setTeamId] = useState('')
  const [tab, setTab] = useState<'overview' | 'analytics'>('overview')
  const { data: teams = [] } = useQuery({ queryKey: ['teams'], queryFn: () => api<Team[]>('/teams') })

  return (
    <>
      <PageHeader
        title="Team dashboard"
        actions={
          <>
            <select className="input w-auto" value={teamId} onChange={(e) => setTeamId(e.target.value)} aria-label="Team">
              <option value="">All my teams</option>
              {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            {tab === 'overview' && <WeekPicker value={week} onChange={setWeek} />}
            <Link to="/reports"><Button variant="secondary">Report center</Button></Link>
          </>
        }
      />
      <div className="mb-4">
        <Tabs value={tab} onChange={setTab} tabs={[{ value: 'overview', label: 'Overview' }, { value: 'analytics', label: 'Achievement analytics' }]} />
      </div>
      {tab === 'overview' ? <OverviewTab week={week} teamId={teamId} /> : <AnalyticsTab teamId={teamId} />}
    </>
  )
}
